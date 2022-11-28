# pylint: disable=exec-used
"""Parsing of metadata that comes from setup.py"""
from __future__ import annotations

import configparser
import functools
import imp  # pylint: disable=deprecated-module
import io
import logging
import os
import os.path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import types
import zipfile
from contextlib import closing
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from io import BytesIO, StringIO
from types import ModuleType
from typing import (
    IO,
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Union,
)

import packaging.version
import pkg_resources
import setuptools  # type: ignore

from req_compile import utils
from req_compile.errors import MetadataError
from req_compile.filename import parse_source_filename

from ..containers import DistInfo, PkgResourcesDistInfo, RequirementContainer
from .dist_info import _fetch_from_wheel
from .extractor import Extractor, NonExtractor
from .patch import begin_patch, end_patch, patch

LOG = logging.getLogger("req_compile.metadata.source")

WHEEL_TIMEOUT = float(os.getenv("REQ_COMPILE_WHEEL_TIMEOUT", "30.0"))
EGG_INFO_TIMEOUT = float(os.getenv("REQ_COMPILE_EGG_INFO_TIMEOUT", "15.0"))

FAILED_BUILDS: Set[str] = set()

THREADLOCAL = threading.local()


def find_in_archive(extractor, filename, max_depth=None):
    # type: (Extractor, str, int) -> Optional[str]
    if extractor.exists(filename):
        return filename

    for info_name in extractor.names():
        if info_name.lower().endswith(filename) and (
            max_depth is None or info_name.count("/") <= max_depth
        ):
            if "/" not in filename and info_name.lower().rsplit("/")[-1] != filename:
                continue
            return info_name
    return None


def _fetch_from_source(
    source_file: str,
    extractor_type: Callable[[str], Extractor],
    run_setup_py: bool = True,
    strict: bool = False,
) -> Optional[RequirementContainer]:
    """

    Args:
        source_file (str): Source file
        extractor_type (type[Extractor]): Type of extractor to use
        strict: Expect all metadata to be valid

    Returns:

    """
    if not os.path.exists(source_file):
        raise ValueError("Source file/path {} does not exist".format(source_file))

    name, version = parse_source_filename(os.path.basename(source_file))

    if source_file in FAILED_BUILDS:
        raise MetadataError(name, version, Exception("Build has already failed before"))

    try:
        extractor = extractor_type(source_file)
        with closing(extractor):
            if run_setup_py:
                LOG.info("Attempting to fetch metadata from setup.py")
                results = _fetch_from_setup_py(source_file, name, version, extractor)
                if results is not None:
                    return results
            else:
                extractor.fake_root = ""

            message = (
                f"No metadata source could be found for the source dist {source_file}"
            )
            LOG.warning(message)
            FAILED_BUILDS.add(source_file)
            if strict:
                raise ValueError(message)
            raise MetadataError(
                name, version, Exception("Invalid project distribution")
            )
    except (zipfile.BadZipfile, tarfile.ReadError) as ex:
        if strict:
            raise IOError(f"Error reading {name}: {ex}")

        LOG.error("Error reading %s: %s", name, str(ex))
        raise MetadataError(name, version, ex)


def _fetch_from_setup_py(
    source_file: str,
    name: str,
    version: Optional[packaging.version.Version],
    extractor: Extractor,
) -> Optional[RequirementContainer]:  # pylint: disable=too-many-branches
    """Attempt a set of executions to obtain metadata from the setup.py without having to build
    a wheel.  First attempt without mocking __import__ at all. This means that projects
    which import a package inside of themselves will not succeed, but all other simple
    source distributions will. If this fails, allow mocking of __import__ to extract from
    tar files and zip files.  Imports will trigger files to be extracted and executed.  If
    this fails, due to true build prerequisites not being satisfied or the mocks being
    insufficient, build the wheel and extract the metadata from it.

    Args:
        source_file (str): The source archive or directory
        name (str): The project name. Use if it cannot be determined from the archive
        extractor (Extractor): The extractor to use to obtain files from the archive

    Returns:
        (DistInfo) The resulting distribution metadata
    """
    results = None

    setattr(THREADLOCAL, "curdir", extractor.fake_root)

    def _fake_chdir(new_dir: str) -> None:
        if os.path.isabs(new_dir):
            dir_test = os.path.relpath(new_dir, extractor.fake_root)
            if dir_test != "." and dir_test.startswith("."):
                raise ValueError(
                    "Cannot operate outside of setup dir ({})".format(dir_test)
                )
        elif new_dir == "..":
            new_dir = "/".join(re.split(r"[/\\]", os.getcwd())[:-1])
        setattr(THREADLOCAL, "curdir", os.path.abspath(new_dir))

    def _fake_getcwd() -> str:
        return getattr(THREADLOCAL, "curdir")

    def _fake_abspath(path: str) -> str:
        """Return the absolute version of a path."""
        if not os.path.isabs(path):
            cwd = os.getcwd()
            path = cwd + "/" + path
        return path

    # fmt: off
    patches = patch(
            os, 'chdir', _fake_chdir,
            os, 'getcwd', _fake_getcwd,
            os, 'getcwdu', _fake_getcwd,
            os.path, 'abspath', _fake_abspath,
    )
    # fmt: on
    with patches:
        setup_file = find_in_archive(extractor, "setup.py", max_depth=1)

        if name == "setuptools":
            LOG.debug("Not running setup.py for setuptools")
            return None

        if setup_file is None:
            setup_cfg = find_in_archive(extractor, "setup.cfg", max_depth=1)
            if setup_cfg is None:
                LOG.warning(
                    "Could not find a setup.py or setup.cfg in %s",
                    os.path.basename(source_file),
                )
                return None

        try:
            LOG.info("Parsing setup.py %s", setup_file)
            results = _parse_setup_py(name, setup_file, extractor)
        except (Exception, RuntimeError, ImportError):  # pylint: disable=broad-except
            LOG.warning("Failed to parse %s", name, exc_info=True)

    if results is None:
        results = _build_egg_info(name, extractor, setup_file)

    if results is None or (results.name is None and results.version is None):
        return None

    if results.name is None:
        results.name = name
    if results.version is None or (version and results.version != version):
        LOG.debug(
            "Parsed version of %s did not match filename %s", results.version, version
        )
        results.version = version or utils.parse_version("0.0.0")

    if not isinstance(extractor, NonExtractor) and utils.normalize_project_name(
        results.name
    ) != utils.normalize_project_name(name):
        LOG.warning("Name coming from setup.py does not match: %s", results.name)
        results.name = name
    return results


def _run_with_output(cmd: Sequence[str], cwd: str = None, timeout: float = 30.0) -> str:
    """Run a subprocess with a timeout and return the output.  Similar check_output with a timeout

    Args:
        cmd (list[str]): Command line parts
        cwd (str, optional): Current working directory to use
        timeout (float, optional): The timeout to apply. After this timeout is exhausted, the
            subprocess will be killed and an exception raise

    Returns:
        (str) The stdout and stderr of the process as ascii

    Raises:
        subprocess.CalledProcessError when the returncode is non-zero or the call times out. If the
            call times out, the returncode will be set to -1
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    def shoveler(output: IO[bytes], input_file: IO[bytes]) -> None:
        for line in iter(lambda: input_file.read(1024), b""):
            output.write(line)

    stdout = BytesIO()
    output_shoveler = threading.Thread(target=shoveler, args=(stdout, proc.stdout))
    output_shoveler.start()

    # Close the stdin pipe immediately to unhang anything attempting to read from stdin
    if proc.stdin is not None:
        proc.stdin.close()

    start = time.time()
    while proc.poll() is None and (time.time() - start) < timeout:
        output_shoveler.join(0.25)

    result = proc.poll()
    if result is None or result != 0:
        ex = subprocess.CalledProcessError(result if result is not None else -1, cmd)
        try:
            proc.terminate()
            proc.kill()
            proc.wait()
        except EnvironmentError:
            pass
        output_shoveler.join()
        ex.output = stdout.getvalue().decode("ascii", "ignore")
        raise ex

    output_shoveler.join()
    return stdout.getvalue().decode("ascii", "ignore")


def _build_wheel(name: str, source_file: str) -> Optional[DistInfo]:
    """Build a wheel from a downloaded source file and extract metadata from the wheel"""
    results = None
    LOG.info("Building wheel file for %s", source_file)

    temp_wheeldir = tempfile.mkdtemp()
    try:
        _run_with_output(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                source_file,
                "--no-deps",
                "--wheel-dir",
                temp_wheeldir,
            ],
            timeout=WHEEL_TIMEOUT,
        )
        wheel_file = os.path.join(temp_wheeldir, os.listdir(temp_wheeldir)[0])
        results = _fetch_from_wheel(wheel_file)
    except subprocess.CalledProcessError as ex:
        LOG.warning(
            'Failed to build wheel for %s:\nThe command "%s" produced:\n%s',
            name,
            subprocess.list2cmdline(ex.cmd),
            ex.output,
        )
    finally:
        shutil.rmtree(temp_wheeldir)
    return results


# Shim to wrap setup.py invocation with an import of setuptools
# This is what pip does to allow building wheels of older dists
SETUPTOOLS_SHIM = (
    "import setuptools, tokenize;"
    "__file__=%r;"
    "f = getattr(tokenize, 'open', open)(__file__);"
    "code = f.read().replace('\\r\\n', '\\n');"
    "f.close();"
    "exec(compile(code, __file__, 'exec'))"
)


def _build_egg_info(name, extractor, setup_file):
    # type: (str, Extractor, Optional[str]) -> Optional[RequirementContainer]
    if setup_file is None:
        return None

    temp_tar = tempfile.mkdtemp()

    extractor.extract(temp_tar)

    extracted_setup_py = os.path.join(temp_tar, setup_file)
    LOG.info("Building egg info for %s", extracted_setup_py)
    try:
        setup_dir = os.path.dirname(extracted_setup_py)
        output = _run_with_output(
            [
                sys.executable,
                "-c",
                SETUPTOOLS_SHIM % extracted_setup_py,
                "egg_info",
                "--egg-base",
                setup_dir,
            ],
            cwd=setup_dir,
            timeout=EGG_INFO_TIMEOUT,
        )

        try:
            egg_info_dir = [
                egg_info
                for egg_info in os.listdir(setup_dir)
                if egg_info.endswith(".egg-info")
            ][0]
            metadata = pkg_resources.PathMetadata(
                setup_dir, os.path.join(setup_dir, egg_info_dir)
            )
            pkg_dist = PkgResourcesDistInfo(
                pkg_resources.Distribution(
                    setup_dir, project_name=name, metadata=metadata
                )
            )
            return pkg_dist
        except IndexError:
            LOG.error(
                "Failed to build .egg-info %s:\n%s", list(os.listdir(setup_dir)), output
            )

    except subprocess.CalledProcessError as ex:
        LOG.warning(
            'Failed to build egg-info for %s:\nThe command "%s" produced:\n%s',
            name,
            subprocess.list2cmdline(ex.cmd),
            ex.output,
        )

    try:
        return _build_wheel(name, os.path.dirname(extracted_setup_py))
    finally:
        shutil.rmtree(temp_tar)


def parse_req_with_marker(req_str: str, marker: str) -> pkg_resources.Requirement:
    return utils.parse_requirement(
        req_str + " and {}".format(marker)
        if ";" in req_str
        else req_str + "; {}".format(marker)
    )


def setup(
    results: List[DistInfo], *_args: Any, **kwargs: Any
) -> Any:  # pylint: disable=too-many-branches,too-many-locals
    # pbr uses a dangerous pattern that only works when you build using setuptools
    # d2to1 uses unknown config options in setup.cfg
    setup_frameworks = ("pbr", "d2to1", "use_pyscaffold")
    for framework in setup_frameworks:
        if framework in kwargs:
            raise ValueError("Must run egg-info if {} is used".format(framework))

    if "setup_requires" in kwargs and (
        "pbr" in kwargs["setup_requires"] or "setupmeta" in kwargs["setup_requires"]
    ):
        raise ValueError("Must run egg-info if pbr/setupmeta is in setup_requires")

    if os.path.exists("setup.cfg"):
        _add_setup_cfg_kwargs(kwargs)

    name = kwargs.get("name", None)
    version = kwargs.get("version", None)
    reqs = kwargs.get("install_requires", [])
    setup_reqs = kwargs.get("setup_requires", [])
    extra_reqs = kwargs.get("extras_require", {})

    if version is not None:
        version = utils.parse_version(str(version))

    if isinstance(reqs, str):
        reqs = [reqs]
    all_reqs = list(utils.parse_requirements(reqs))
    for extra, extra_req_strs in extra_reqs.items():
        extra = extra.strip()
        if not extra:
            continue
        try:
            if isinstance(extra_req_strs, str):
                extra_req_strs = [extra_req_strs]
            cur_reqs = utils.parse_requirements(extra_req_strs)
            if extra.startswith(":"):
                req_with_marker = [
                    parse_req_with_marker(str(cur_req), extra[1:])
                    for cur_req in cur_reqs
                ]
            else:
                req_with_marker = [
                    parse_req_with_marker(
                        str(cur_req), 'extra=="{}"'.format(extra.replace('"', '\\"'))
                    )
                    for cur_req in cur_reqs
                ]
            all_reqs.extend(req_with_marker)
        except pkg_resources.RequirementParseError as ex:  # type: ignore[attr-defined]
            print(
                "Failed to parse extra requirement ({}) "
                "from the set:\n{}".format(str(ex), extra_reqs),
                file=sys.stderr,
            )
            raise

    if name is not None:
        name = name.replace(" ", "-")

    dist_info = DistInfo(name, version, all_reqs)
    dist_info.setup_reqs = list(utils.parse_requirements(setup_reqs))
    results.append(dist_info)

    # Some projects inspect the setup() result
    class FakeResult(object):
        def __getattr__(self, item: str) -> Any:
            return None

    return FakeResult()


def _get_include() -> str:
    return ""


class FakeNumpyModule(ModuleType):
    """A module simulating numpy"""

    def __init__(self, name: str) -> None:
        ModuleType.__init__(  # pylint: disable=non-parent-init-called,no-member
            self, name
        )
        self.__version__ = "2.16.0"
        self.get_include = _get_include


class FakeModule(ModuleType):
    """A module simulating cython"""

    def __init__(self, name: str) -> None:
        ModuleType.__init__(  # pylint: disable=non-parent-init-called,no-member
            self, name
        )

    def __call__(self, *args: Any, **kwargs: Any) -> FakeModule:
        return FakeModule("")

    def __iter__(self) -> Iterator:
        return iter([])

    def __getattr__(self, item: str) -> Any:
        if item == "__path__":
            return []
        if item == "setup":
            return setuptools.setup
        return FakeModule(item)


def _add_setup_cfg_kwargs(kwargs: Dict[str, Any]) -> None:
    LOG.info("Parsing from setup.cfg")

    parser = configparser.ConfigParser()
    parser.read("setup.cfg", encoding="utf-8")

    install_requires = kwargs.get("install_requires", [])
    if parser.has_option("options", "install_requires"):
        install_requires.extend(parser.get("options", "install_requires").split("\n"))
        kwargs["install_requires"] = install_requires

    extras_require = kwargs.get("extras_require", {})
    if parser.has_section("options.extras_require"):
        for extra, req_str in parser.items("options.extras_require"):
            extras_require[extra] = req_str.split("\n")
        kwargs["extras_require"] = extras_require

    if parser.has_option("metadata", "name"):
        kwargs["name"] = parser.get("metadata", "name")

    if parser.has_option("metadata", "version"):
        kwargs["version"] = parser.get("metadata", "version")


def remove_encoding_lines(contents: str) -> str:
    lines = contents.split("\n")
    lines = [
        line
        for line in lines
        if not (
            line.startswith("#")
            and ("-*- coding" in line or "-*- encoding" in line or "encoding:" in line)
        )
    ]
    return "\n".join(lines)


def import_contents(modname: str, filename: str, contents: str) -> types.ModuleType:
    module = imp.new_module(modname)
    if filename.endswith("__init__.py"):
        setattr(module, "__path__", [os.path.dirname(filename)])
    setattr(module, "__name__", modname)
    setattr(module, "__file__", filename)
    sys.modules[modname] = module
    contents = remove_encoding_lines(contents)
    exec(contents, module.__dict__)  # pylint: disable=exec-used
    return module


def _parse_setup_py(
    name: str, setup_file: Optional[str], extractor: Extractor
) -> Optional[RequirementContainer]:
    """Parse from a setup.py/setup.cfg."""
    # pylint: disable=too-many-locals,too-many-statements
    # pylint: disable=bad-option-value,no-name-in-module,no-member,import-outside-toplevel,too-many-branches

    # Capture warnings.warn, which is sometimes used in setup.py files
    logging.captureWarnings(True)

    results: List[DistInfo] = []
    setup_with_results = functools.partial(setup, results)

    import os.path  # pylint: disable=redefined-outer-name,reimported

    # Make sure __file__ contains only os.sep separators
    setup_path = ""
    if setup_file is not None:
        setup_path = os.path.join(extractor.fake_root, setup_file).replace("/", os.sep)
    spy_globals = {
        "__file__": setup_path,
        "__name__": "__main__",
        "setup": setup_with_results,
    }

    # pylint: disable=unused-import,unused-variable
    import codecs
    import distutils.core
    import fileinput
    import multiprocessing

    import requests

    try:
        import importlib.util
        import urllib.request
    except ImportError:
        pass

    if "numpy" not in sys.modules:
        sys.modules["numpy"] = FakeNumpyModule("numpy")
        sys.modules["numpy.distutils"] = FakeModule("distutils")
        sys.modules["numpy.distutils.core"] = FakeModule("core")
        sys.modules["numpy.distutils.misc_util"] = FakeModule("misc_util")
        sys.modules["numpy.distutils.system_info"] = FakeModule("system_info")

    def _fake_exists(path: str) -> bool:
        return extractor.exists(path)

    def _fake_rename(name: str, new_name: str) -> None:
        extractor.add_rename(name, new_name)

    def _fake_execfile(path: str) -> None:
        exec(extractor.contents(path), spy_globals, spy_globals)

    def _fake_file_input(path: str, **_kwargs: Any) -> IO[str]:
        return open(path, "r", encoding="utf-8")

    old_cythonize = None
    try:
        import Cython.Build  # type: ignore

        old_cythonize = Cython.Build.cythonize
        Cython.Build.cythonize = lambda *args, **kwargs: ""
    except ImportError:
        sys.modules["Cython"] = FakeModule("Cython")
        sys.modules["Cython.Build"] = FakeModule("Build")
        sys.modules["Cython.Distutils"] = FakeModule("Distutils")
        sys.modules["Cython.Compiler"] = FakeModule("Compiler")
        sys.modules["Cython.Compiler.Main"] = FakeModule("Main")

    def os_error_call(*args: Any, **kwargs: Any) -> None:
        raise OSError("Popen not permitted: {} {}".format(args, kwargs))

    class FakePopen:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            os_error_call(*args, **kwargs)

    def io_error_call(*args: Any, **kwargs: Any) -> None:
        raise IOError("Network and I/O calls not permitted: {} {}".format(args, kwargs))

    if setup_file is None:
        setup_dir = "."
    else:
        setup_dir = os.path.dirname(setup_file)
    abs_setupdir = os.path.abspath(setup_dir)

    class FakeSpec(ModuleSpec):
        class FakeLoader(Loader):
            def exec_module(self, module: ModuleType) -> None:
                pass

            def module_repr(self, module: ModuleType) -> str:
                return ""

        def __init__(self, modname: str, path: str) -> None:
            super().__init__(modname, FakeSpec.FakeLoader(), origin=path)
            self.path = path
            self.contents = extractor.contents(path)

    # pylint: disable=unused-argument
    def fake_load_source(
        modname: str, filename: str, filehandle: Any = None
    ) -> ModuleType:
        return import_contents(modname, filename, extractor.contents(filename))

    def fake_spec_from_file_location(
        modname: str, path: str, submodule_search_locations: Iterable[str] = None
    ) -> ModuleSpec:
        return FakeSpec(modname, path)

    def fake_module_from_spec(spec: ModuleType) -> ModuleType:
        return import_contents(spec.name, spec.path, spec.contents)

    spec_from_file_location_patch = begin_patch(
        "importlib.util", "spec_from_file_location", fake_spec_from_file_location
    )
    module_from_spec_patch = begin_patch(
        "importlib.util", "module_from_spec", fake_module_from_spec
    )
    load_source_patch = begin_patch(imp, "load_source", fake_load_source)

    class ArchiveMetaHook(Loader, MetaPathFinder):
        def __init__(self) -> None:
            self.mod_mapping: Dict[str, str] = {}

        def find_module(
            self, fullname: str, path: Optional[Sequence[Union[bytes, str]]]
        ) -> Optional[Loader]:
            path_name = fullname.replace(".", "/")
            dirs_to_search = [abs_setupdir]
            if path is not None:
                for extra_path in path:
                    if isinstance(extra_path, str):
                        dirs_to_search.append(extra_path)
                    else:
                        dirs_to_search.append(extra_path.decode("utf-8"))
            for sys_path in sys.path:
                if extractor.contains_path(sys_path):
                    dirs_to_search.append(sys_path)
            for dir_to_search in dirs_to_search:
                for archive_path in (
                    os.path.join(dir_to_search, path_name) + ".py",
                    os.path.join(dir_to_search, path_name, "__init__.py"),
                ):
                    if extractor.exists(archive_path):
                        self.mod_mapping[fullname] = archive_path
                        return self
            return None

        def module_repr(self, module: ModuleType) -> str:
            return ""

        def load_module(self, fullname: str) -> types.ModuleType:
            LOG.debug("Importing module %s from archive", fullname)

            filename = self.mod_mapping[fullname]
            code = extractor.contents(filename)
            ispkg = filename.endswith("__init__.py")
            mod = sys.modules.setdefault(fullname, imp.new_module(fullname))
            mod.__file__ = filename
            mod.__loader__ = self
            if ispkg:
                mod.__path__ = []
                mod.__package__ = fullname
            else:
                mod.__package__ = fullname.rpartition(".")[0]
            exec(code, mod.__dict__)
            return mod

    meta_hook = ArchiveMetaHook()
    sys.meta_path.append(meta_hook)

    fake_stdin = StringIO()

    def _fake_find_packages(*args: Any, **kwargs: Any) -> Iterable[Any]:
        return []

    # fmt: off
    patches = patch(
            sys, 'stderr', StringIO(),
            sys, 'stdout', StringIO(),
            sys, 'stdin', fake_stdin,
            os, '_exit', sys.exit,
            os, 'symlink', lambda *_: None,
            'builtins', 'open', extractor.open,
            '__builtin__', 'open', extractor.open,
            '__builtin__', 'execfile', _fake_execfile,
            subprocess, 'check_call', os_error_call,
            subprocess, 'check_output', os_error_call,
            subprocess, 'Popen', FakePopen,
            multiprocessing, 'Pool', os_error_call,
            multiprocessing, 'Process', os_error_call,
            'urllib.request', 'urlretrieve', io_error_call,
            requests, 'Session', io_error_call,
            requests, 'get', io_error_call,
            requests, 'post', io_error_call,
            os, 'listdir', lambda path: [],
            os.path, 'exists', _fake_exists,
            os.path, 'isfile', _fake_exists,
            os, 'rename', _fake_rename,
            io, 'open', extractor.open,
            codecs, 'open', extractor.open,
            setuptools, 'setup', setup_with_results,
            distutils.core, 'setup', setup_with_results,
            fileinput, 'input', _fake_file_input,
            setuptools, 'find_packages', _fake_find_packages,
            sys, 'argv', ['setup.py', 'egg_info'])
    # fmt: on
    with patches:
        try:
            sys.path.insert(0, abs_setupdir)
            if setup_dir:
                os.chdir(abs_setupdir)

            if setup_file is not None:
                contents = extractor.contents(os.path.basename(setup_file))

                exec(contents, spy_globals, spy_globals)
            else:
                setup(results)
        except SystemExit:
            LOG.warning("setup.py raised SystemExit")
        finally:
            if old_cythonize is not None:
                Cython.Build.cythonize = old_cythonize
            if abs_setupdir in sys.path:
                sys.path.remove(abs_setupdir)

            end_patch(load_source_patch)
            end_patch(spec_from_file_location_patch)
            end_patch(module_from_spec_patch)
            sys.meta_path.remove(meta_hook)

            for module_name in list(sys.modules.keys()):
                try:
                    module = sys.modules[module_name]
                except KeyError:
                    continue

                if isinstance(module, (FakeModule, FakeNumpyModule)):
                    del sys.modules[module_name]
                elif hasattr(module, "__file__") and module.__file__:
                    module_file = module.__file__
                    if hasattr(sys, "real_prefix"):
                        sys_prefix = sys.real_prefix  # type: ignore[attr-defined]
                    elif hasattr(sys, "base_prefix"):
                        sys_prefix = sys.base_prefix
                    else:
                        sys_prefix = sys.prefix
                    if (
                        not module_file.startswith(sys_prefix)
                        and not module_file.startswith(sys.prefix)
                        and extractor.contains_path(module.__file__)
                    ):
                        del sys.modules[module_name]

    if not results:
        raise ValueError(
            "Distutils/setuptools setup() was not ever "
            'called on "{}". Is this a valid project?'.format(name)
        )
    result = results[0]
    if result is None or (result.name is None and result.version is None):
        raise ValueError(
            "Failed to fetch any metadata from setup() call. Is this numpy?"
        )

    return result
