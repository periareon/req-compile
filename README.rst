README for Req-Compile Python Requirements Compiler
===================================================

.. image:: https://img.shields.io/pypi/v/req-compile.svg
    :alt: PyPI package version
    :target: https://pypi.python.org/pypi/req-compile

.. image:: https://github.com/sputt/req-compile/actions/workflows/build.yml/badge.svg
    :alt: Github build status
    :target: https://github.com/sputt/req-compile

========================================
Req-Compile Python Requirements Compiler
========================================

Req-Compile is a Python requirements compiler geared toward large Python projects. It allows you to:

* Produce an output file consisting of fully constrained exact versions of your requirements
* Identify sources of constraints on your requirements
* Constrain your output requirements using requirements that will not be included in the output
* Save distributions that are downloaded while compiling in a configurable location
* Use a current solution as a source of requirements. In other words, you can easily compile a subset from an existing solution.

Why use it?
-----------
**pip** and **pip-tools** are missing features and lack usability for some important workflows:
* Using a previous solution as an input file to avoid hitting the network
* pip-compile can't consider constraints that are not included in the final output. While pip accepts a constraints file, there is no way to stop at the "solving" phase, which would be used to push a fully solved solution to your repo
* Track down where conflicting constraints originate
* Treating source directories recursively as sources of requirements, like with --find-links
* Configuring a storage location for downloaded distributions. Finding a fresh solution to a set of input requirements always requires downloading distributions

A common workflow that is difficult to achieve with other tools:

You have a project with requirements ``requirements.txt`` and test requirements ``test-requirements.txt``. You want
to produce a fully constrained output of ``requirements.txt`` to use to deploy your application. Easy, right? Just
compile ``requirements.txt``. However, if your test requirements will in any way constrain packages you need,
even those needed transitively, it means you will have tested with different versions than you'll ship.

For this reason, you can use Req-Compile to compile ``requirements.txt`` using ``test-requirements.txt`` as constraints.

The Basics
----------

Install and run
~~~~~~~~~~~~~~~
Req-Compile can be simply installed by running::

    pip install req-compile

Two entrypoint scripts are provided::

    req-compile <input reqfile1> ... <input_reqfileN> [--constraints constraint_file] [repositories, such as --index-url https://...]
    req-candidates [requirement] [repositories, such as --index-url https://...]

Producing output requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
To produce a fully constrained set of requirements for a given number of input requirements files, pass requirements
files to req-compile::

    > cat requirements.txt
    astroid >= 2.0.0
    isort >= 4.2.5
    mccabe

    > req-compile req-compile requirements.txt
    astroid==2.9.0            # requirements.txt (>=2.0.0)
    isort==5.10.1             # requirements.txt (>=4.2.5)
    lazy-object-proxy==1.7.1  # astroid (>=1.4.0)
    mccabe==0.6.1             # requirements.txt
    setuptools==60.0.1        # astroid (>=20.0)
    typed-ast==1.5.1          # astroid (<2.0,>=1.4.0)
    typing_extensions==4.0.1  # astroid (>=3.10)
    wrapt==1.13.3             # astroid (<1.14,>=1.11)


Output is always emitted to stdout. Possible inputs include::

    > req-compile
    > req-compile .
    # Compiles the current directory (looks for a setup.py or pyproject.toml)

    > req-compile subdir/project
    # Compiles the project in the subdir/project directory

    > req-candidates --paths-only | req-compile
    # Search for candidates and compile them piped in via stdin

    > echo flask | req-compile
    # Compile the requirement 'flask' using the default remote index (PyPI)

    > req-compile . --extra test
    # Compiles the current directory with the extra "test"


Specifying source of distributions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Req-Compile supports obtaining python distributions from multiple sources, each of which can be specified more than once. The following sources
can be specified, resolved in the same order (e.g. source takes precedence over index-url):

* ``--solution``

  Load a previous solution and use it as a source of distributions. This will allow a full
  recompilation of a working solution without requiring any other source. If the
  solution file can't be found, a warning will be emitted but not cause a failure
* ``--source``

  Use a local filesystem with source python packages to compile from. This will search the entire
  tree specified at the source directory, until an __init__.py is reached. ``--remove-source`` can
  be supplied to remove results that were obtained from source directories. You may want to do
  this if compiling for a project and only third party requirements compilation results need to be saved.
* ``--find-links``

  Read a directory to load distributions from. The directory can contain anything
  a remote index would, wheels, zips, and source tarballs. This matches pip's command line.
* ``--index-url``

  URL of a remote index to search for packages in. When compiling, it's necessary to download
  a package to determine its requirements. ``--wheel-dir`` can be supplied to specify where to save
  these distributions. Otherwise they will be deleted after compilation is complete.

All options can be repeated multiple times, with the resolution order within types matching what
was passed on the commandline. However, overall resolution order will always match the order
of the list above.

By default, PyPI (https://pypi.org/) is added as a default source. It can be removed by passing
``--no-index`` on the commandline.

Identifying source of constraints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Why did I just get version 1.11.0 of ``six``? Find out by examining the output::

    six==1.11.0  # astroid, pathlib2, pymodbus (==1.11.0), pytest (>=1.10.0), more_itertools (<2.0.0,>=1.0.0)


In the above output, the (==1.11.0) indicates that pymodbus, the requirement name listed before the
parenthesis, specifically requested version 1.11.0 of six.

Constraining output
~~~~~~~~~~~~~~~~~~~
Constrain production outputs with test requirements using the ``--constraints`` flag. More than one file can be
passed::

    > cat requirements.txt
    astroid

    > cat test-requirements.txt
    pylint<1.6

    > req-compile requirements.txt --constraints test-requirements.txt
    astroid==1.4.9            # pylint (<1.5.0,>=1.4.5), requirements.txt
    lazy-object-proxy==1.7.1  # astroid
    six==1.16.0               # astroid, pylint
    wrapt==1.13.3             # astroid


Note that astroid is constrained by ``pylint``, even though ``pylint`` is not included in the output.

If a passed constraints file is fully pinned, Req-Compile will not attempt to find a solution for
the requirements passed in the constraints files. This behavior only occurs if ALL of the requirements
listed in the constraints files are pinned. This is because pinning a single requirement may
still bring in transitive requirements that would affect the final solution. The heuristic of
checking that all requirements are pinned assumes that you are providing a full solution.

Advanced Features
-----------------
Compiling a constrained subset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Input can be supplied via stdin as well as via as through files. For example, to supply a full
solution through a second compilation in order to obtain a subset of requirements, the
following cmdline might be used::

    > req-compile requirements.txt --constraints compiled-requirements.txt

or, for example to consider two projects together::

    > req-compile /some/other/project /myproject | req-compile /myproject --solution -

which is equivalent to::

    > req-compile /myproject --constraints /some/other/project

Resolving constraint conflicts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Conflicts will automatically print the source of each conflicting requirement::

    > cat projectreqs.txt
    astroid<1.6
    pylint>=1.5

    > req-compile projectreqs.txt
    No version of astroid could possibly satisfy the following requirements (astroid<1.6,<3,>=2.3.0):
      projectreqs.txt -> astroid<1.6
      projectreqs.txt -> pylint 2.4.1 -> astroid<3,>=2.3.0

Saving distributions
~~~~~~~~~~~~~~~~~~~~
Files downloading during the compile process can be saved for later install. This can optimize
the execution times of builds when a separate compile step is required::

    > req-compile projectreqs.txt --wheel-dir .wheeldir > compiledreqs.txt
    > pip install -r compiledreqs.txt --find-links .wheeldir --no-index

Cookbook
--------
Some useful patterns for projects are outlined below.

Compile, then install
~~~~~~~~~~~~~~~~~~~~~
After requirements are compiled, the usual next step is to install them
into a virtualenv.

A script for test might run::

    > req-compile --extra test --solution compiled-requirements.txt --wheel-dir .wheeldir > compiled-requirements.txt
    > pip-sync compiled-requirement.txt --find-links .wheeldir --no-index
    or
    > pip install -r compiled-requirements.txt --find-links .wheeldir --no-index

This would produce an environment containing all of the requirements and test requirements for the project
in the current directory (as defined by a setup.py). This is a *stable* set, in that only changes to
the requirements and constraints would produce a new output. To produce a totally fresh compilation,
don't pass in a previous solution.

The find-links parameter to the sync or pip install will *reuse* the wheels already downloaded by Req-Compile during
the compilation phase. This will make the installation step entirely offline.

When taking this environment to deploy, trim down the set to the install requirements::

    > req-compile --solution compiled-requirements.txt --no-index > install-requirements.txt

install-requirements.txt will contain the pinned requirements that should be installed in your
target environment. The reason for this extra step is that you don't want to distribute
your test requirements, and you also want your installed requirements to be the same
versions that you've tested with. In order to get all of your explicitly declared
requirements and all of the transitive dependencies, you can use the prior solution to
extract a subset. Passing the ``--no-index`` makes it clear that this command will not
hit the remote index at all (though this would naturally be the case as solution files
take precedence over remote indexes in repository search order).

Compile for a group of projects
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Req-Compile can discover requirements that are grouped together on the filesystem. The
``req-candidates`` command will print discovered projects and with the ``--paths-only`` options
will dump their paths to stdout. This allows recursive discovery of projects that you
may want to compile together.

For example, consider a filesystem with this layout::

    solution
      \_ utilities
      |   \_ network_helper
      |_ integrations
      |   \_ github
      \_ frameworks
          |_ neural_net
          \_ cluster

In each of the leaf nodes, there is a setup.py and full python project. To compile these
together and ensure that their requirements will all install into the same environment::

    > cd solution
    > req-candidates --paths-only
    /home/user/projects/solution/utilities/network_helper
    /home/user/projects/solution/integrations/github
    /home/user/projects/solution/frameworks/neural_net
    /home/user/projects/solution/frameworks/cluster

    > req-candidates --paths-only | req-compile --extra test --solution compiled-requirements.txt --wheel-dir .wheeldir > compiled-requirements.txt
    .. all reqs and all test reqs compiled together...

