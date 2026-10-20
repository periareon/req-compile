New in version 1.6.2:

* ``@<hub>//:requirements.test`` compares the pinned file by meaning: it passes when the file pins exactly the
  packages and versions the hub resolved and, for each, its hashes include those of the artifacts the hub's
  platforms use. Extra hashes, comments and ordering do not matter, so a file Dependabot regenerates with
  pip-compile passes; a missing or extra package, another version or a missing hash fails naming the package.

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
