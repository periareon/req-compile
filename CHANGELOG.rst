New in version 1.2.0:

* Cross-platform compilation. ``--platform``, ``--python-version`` and ``--implementation`` select
  wheels and evaluate environment markers for an environment other than the one running ``req-compile``.
  ``--platform`` takes a wheel platform tag such as ``manylinux_2_28_x86_64`` or ``macosx_11_0_arm64``,
  which is recorded in the header of lock files compiled by Bazel.
* The ``py_reqs_compiler`` Bazel rule has new ``platform`` and ``python_version`` attributes, so the
  solutions for every platform a project supports can be compiled and tested from a single machine.
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
