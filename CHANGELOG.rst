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
