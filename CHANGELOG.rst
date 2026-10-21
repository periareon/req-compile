New in version 1.6.5:

* ``requirements.update`` no longer takes ``--upgrade`` / ``-U``: that flag worked by running Bazel again from
  inside the update binary, and req-compile's tools do not invoke Bazel. A pin is moved on purpose with the
  variable on the command itself, ``REQ_COMPILE_UPGRADE=<package>[,<package>] bazel run
  @<hub>//:requirements.update`` (``all`` for every package), which the extension reads; a hub without
  ``requirements_txt`` uses it with ``bazel mod deps``. The update leaves a file that is already up to date
  untouched. ``MODULE.bazel.lock`` records the file as it was when the hub resolved, before the update rewrote
  it; the next Bazel command, or ``bazel mod deps --lockfile_mode=update``, brings it up to date.

New in version 1.6.4:

* A bumped pin in ``requirements_txt`` whose hash does not match no longer resolves quietly to the previous
  version. The solver cannot tell, while it resolves, a pin a requirement excludes from one it left for lack
  of a usable, hash-matching artifact, so the finished solution is checked: a pinned version that every
  requirement on the package and every constraint file still allows must be the one used, with one of its
  hashes, or the resolution fails naming the package, the platform with the least to offer and the artifacts
  the index has for that version. This covers a wrong hash (also beside a matching sdist hash, which vouches
  for nothing when sdists are not allowed), a release without a wheel for one platform, and an older release
  on another index. A pin a requirement excludes still moves by itself.

New in version 1.6.3:

* A hub's ``requirements_txt`` is to the resolution what an existing lock is to pip-compile: each package
  keeps the version the file pins, with the file's hashes, while ``requirements_in`` and the other packages
  allow it, and is resolved again when they do not. Raising a bound in ``requirements_in`` therefore moves the
  pin by itself; before, the file's pins were hard and the bump failed until ``--upgrade`` lifted them. The
  file's hashes vouch for the pinned version only, so a bump with a wrong hash still fails naming the package,
  while a version the file does not pin needs no hash and gets one when ``requirements.update`` writes it.
  A mismatch on the pinned version stays an error even when another index or an older release would let the
  solver resolve around it. A pin without a local segment covers every build of its release (``1.0`` covers
  ``1.0+cpu``) and its hashes say which build is meant. With ``enforce_hashes = False`` the file's hashes are
  not read at all.
* A soft pin, the recorded solution's version or the pinned file's, yields before the solver walks back a
  reverse dependency to keep it: raising ``a>=2`` when the new ``a`` needs ``b>=2`` moves the pinned ``b``
  instead of failing on ``a``. This also applies to ``py_reqs_compiler`` recycling a solution.
* The lock records whether a distribution's metadata came from the index's separately served file; once the
  pinned file vouches for the artifact, its metadata is read from the wheel itself, as it always is for a
  hash-pinned artifact, so an index cannot describe a newly pinned wheel through a stale sidecar.
* Every place that tells how to move a pin on purpose says the same thing: ``bazel run
  @<hub>//:requirements.update -- --upgrade <package>`` (``-U`` with no name for every package); the variable
  ``REQ_COMPILE_UPGRADE=<package>[,<package>]`` on that command when the hub itself cannot be resolved, or with
  ``bazel mod deps`` for a hub that has no ``requirements_txt``.

New in version 1.6.2:

* ``@<hub>//:requirements.test`` compares the pinned file by meaning: it passes when the file pins exactly the
  packages and versions the hub resolved and, for each, its hashes include those of the artifacts the hub's
  platforms use. Extra hashes, comments and ordering do not matter, so a file Dependabot regenerates with
  pip-compile passes, as do ``2.0.0`` or ``===2.0`` for ``2.0``; a missing or extra package, another version,
  a missing hash, a package pinned twice at different versions or an ``-r`` include fails naming it.
* ``REQ_COMPILE_UPGRADE`` lifts the pins of the named packages (all of them with ``all``) from the hub's
  ``requirements_txt`` for that resolution, and ``bazel run @<hub>//:requirements.update -- --upgrade [pkg ...]``
  (``-U``) does the same from the command line, so a pin can be moved on purpose; it runs the hub's target by
  canonical label with ``--repo_env``. A pinned hub that fails to resolve says how to lift a pin.
* ``@<hub>//:requirements.test`` compares against a copy of the workspace file the hub repository reads itself,
  so the file needs no ``exports_files``.
* The module archive no longer carries the solver module built during the release, nor a stray diff file.
* A page or distribution that still cannot be downloaded when the solver's failure is retried is reported with
  its URL and Bazel's cause, and with the way out: run the command again once the cause is fixed, and
  ``bazel shutdown`` when the same error comes back although the index is reachable, since Bazel keeps a failed
  module extension evaluation until one of its inputs changes (the lockfile, rewritten after every command in
  its default mode, is one).

New in version 1.6.1:

* Resolve mode moves to its own tag class, ``requirements.resolve``, with the attributes that only mean
  something when resolving; ``requirements.parse`` has exactly the attributes it had before 1.6.0 and defines
  hubs from lock files only.
* A resolved hub can maintain its pinned requirements file: ``requirements_txt`` on the ``resolve`` tag names
  it, ``@<hub>//:requirements.update`` writes what the hub resolved, with the hashes of the artifacts its
  platforms use, and ``@<hub>//:requirements.test`` fails while the file is out of date. Fed back to the hub,
  the file pins the version and hashes of what it lists, so a version Dependabot bumps in it is what the next
  resolution uses, while a package newly added to ``requirements_in`` resolves freely and then appears in it.

New in version 1.6.0:

* The ``requirements`` extension resolves requirement files inside Bazel, without a host Python, when a
  ``parse`` tag sets ``requirements_in`` together with ``python_version`` and ``platforms``. The
  solver is the unmodified ``req_compile`` package running as a WebAssembly module under Bazel's experimental
  ``execute_wasm`` (``--experimental_repository_ctx_execute_wasm``; Bazel 10 compiles it with
  ``--experimental_repository_ctx_wasm_compilation``). Bazel performs every download, in rounds the solver
  asks for, and the solution is recorded in ``MODULE.bazel.lock`` as the repositories of the hub and as
  facts, so an unchanged hub is rebuilt without running the solver and a changed requirements file re-solves
  only what the change touches. ``REQ_COMPILE_UPGRADE=all`` (or a comma-separated list of packages) starts
  over from the indexes.
* Fully pinned requirement files with ``--hash`` lines, as Dependabot's ``pip`` updater maintains them, are
  accepted as ``requirements_in``; ``enforce_hashes`` (default true) fails a version bumped without its hash.
  ``wasm/example`` shows the Dependabot configuration and a workflow that refreshes the lock.
* ``req_compile_solver.wasm`` is built from pinned inputs by ``wasm/build_solver.sh`` and attached to each
  release, whose extension downloads it on first use; ``solver`` on the ``parse`` tag names a locally built
  module instead.

New in version 1.5.0:

* A wheel repository is a single package. Its ``py_library`` is named after the package
  (``@wheel_repo//:requests``) instead of ``//:library``, the ``//:pkg`` alias is gone, and the per-hub
  subpackages (``@wheel_repo//<hub>:...``) are replaced by targets in the root named after the hub:
  ``//:<hub>.<package>`` and ``//:<hub>.entry_point_<script>``. Hubs resolve to these directly.
* The target a hub sees for a wheel is a ``py_library`` holding the modules of the wheel together with the
  dependencies the hub resolved, instead of depending on the dependency-free library of the package. Type
  checkers analyzing one library at a time, such as the mypy aspect of ``rules_venv``, previously saw every
  import of a wheel as missing and typed its classes as ``Any``. When the hub resolved no dependencies for the
  wheel the target is an alias of the package library.
* ``py_package_annotation_consumer`` reads annotation targets from the target a hub alias resolves to and no
  longer walks its dependencies.
* The ``.unavailable`` targets of a hub package are only rendered when the package is missing from some locks
  of the hub and no fallback lock provides it.

New in version 1.4.0:

* ``py_reqs_compiler`` compiles the solutions of several platforms together: ``requirements_txts`` maps a
  solution file to each platform. The solutions use the same version of every package, a package keeps the
  version the first platform resolves it to and a version another platform cannot use is dropped for all of
  them. The compilation fails, naming the platforms, when no version of a package works everywhere. A
  ``py_reqs_solution_test`` of such a target checks every solution, including that they agree.
* The Bazel compiler accepts ``--solution``, ``--platform`` and ``--output`` once per solution.
* ``perform_compile`` accepts soft pins, which yield with ``PinConflictException`` when a package cannot
  satisfy them, and ``perform_compile_group`` compiles the same requirements for several targets with one
  version per package.

New in version 1.2.0:

* ``requirements.parse`` now maps lock files to ids in ``requirements_locks`` and config settings to those
  ids in the new ``config_settings`` attribute. Both are label keyed, so each is resolved by the module
  defining the hub and any config setting visible to it can be used. ``//conditions:default`` names a
  fallback lock. Without ``config_settings``, locks compiled with the ``platform`` attribute of
  ``py_reqs_compiler`` are selected by the platform read from the header of the file. Label strings as
  ``requirements_locks`` values still work but are deprecated.
* Every distinct wheel is downloaded once into a repository named ``{package}_{version}_{sha256[:8]}``
  and shared by all hubs of all modules pinning it. Each hub keeps its own dependency edges, so extras
  and version differences between hubs are preserved. Hub names must be unique across modules.
* ``package_annotation`` applies to the hubs of the module declaring it unless its new ``hubs``
  attribute names particular hubs or ``"*"`` for every hub. Hubs annotated differently get their own
  repository for the package.
* Hubs whose locks do not all contain the same packages are supported. A package missing from a lock
  is incompatible with that lock's platform, so targets depending on it are skipped there.
* Removed the ``defs_id_map`` attribute of the ``parse`` tag and the WORKSPACE-only ``repositories()``
  flow. ``py_requirements_repository`` is now only instantiated by the module extension.
* Cross-platform compilation. ``--platform``, ``--python-version`` and ``--implementation`` select
  wheels and evaluate environment markers for an environment other than the one running ``req-compile``.
  ``--platform`` takes a wheel platform tag such as ``manylinux_2_28_x86_64`` or ``macosx_11_0_arm64``,
  which is recorded in the header of lock files compiled by Bazel.
* The ``py_reqs_compiler`` Bazel rule has new ``platform`` and ``python_version`` attributes, so the
  solutions for every platform a project supports can be compiled and tested from a single machine.
  Solutions record their platform and Python version in their header, and a solution compiled for
  another target is not recycled when recompiling without ``--upgrade``.
* Removed the ``py_reqs_remote_compiler`` Bazel rule. Use the ``platform`` attribute of ``py_reqs_compiler``
  instead.

New in version 1.1.0:

* Python 3.13 and 3.14 support.
* Replaced ``pkg_resources`` with the ``packaging`` library.
* Minimum Python version is now 3.9.

New in version 1.0.0:

* ``--hashes`` option for hashing the distributions used in a solution.
* ``--urls`` option to dump the URL of the distribution downloaded for the solution into a comment.
* ``--multiline`` and ``--no-multiline`` options to change how the solution is printed. When not provided the mode is automatically selected.
* ``--no-explanations`` option to omit the constraint explanations from the comment following the pin in a solution.
* ``req-candidates`` now starts printing candidates at matching versions
  to give a better view of what is available on the index.
* ``--only-binary <project>`` option to force selecting wheels for the provided projects. Passing ``:all:`` will force ``req-compile`` to only use wheels.
* ``--extra-index-url`` option to allow using the system index as the primary with extra indexes as supplements.
* Allow requirements files to use ``--index-url`` and ``--extra-index-url`` directives.
* ``--index-url`` and ``--extra-index-url`` are now emitted to the output if they differ from system default.
* Download setup requirements to a provided wheel directory, even though they aren't necessarily in the solution. This allows for fully offline source distribution installs via ``pip install <project> --no-index --find-links .wheeldir`` when all dependent projects correctly declare their setup requirements.
* Improved errors when passing invalid requirements files.

New in version 0.10.21:

* Allow for setuptools backend projects specified only by pyproject.toml and setup.cfg
