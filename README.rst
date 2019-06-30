README for Qer Python Requirements Compiler
============================================

.. image:: https://travis-ci.org/sputt/qer.svg?branch=master
    :target: https://travis-ci.org/sputt/qer

.. image:: https://img.shields.io/pypi/v/qer.svg
    :alt: PyPI Package version
    :target: https://pypi.python.org/pypi/qer

================================
Qer Python Requirements Compiler
================================

Qer is a Python work-in-progress requirements compiler geared toward large Python projects. It allows you to:

* Produce an output file consisting of fully constrained exact versions of your requirements
* Identify sources of constraints on your requirements
* Constrain your output requirements using requirements that will not be included in the output
* Save distributions that are downloaded while compiling
* Use a current solution as a source of requirements. In other words, you can easily compile a subset from an existing solution.

Why use it?
-----------
**pip-tools** is the defacto requirements compiler for Python, but is missing some important features.

* Does not allow you to use constraints that are not included in the final output
* Provides no tools to track down where conflicting constraints originate
* Cannot treat source directories recursively as package sources

Qer has these features, making it an effective tool for large Python projects.

This situation is very common:

You have a project with requirements ``requirements.txt`` and test requirements ``test-requirements.txt``. You want
to produce a fully constrained output of ``requirements.txt`` to use to deploy your application. Easy, right? Just
compile ``requirements.txt``. However, if your test requirements will in any way constrain packages you need,
even those needed transitively, it means you will have tested with different versions than you'll ship.

For this reason, you can user Qer to compile ``requirements.txt`` using ``test-requirements.txt`` as constraints.

The Basics
----------

Install and run
~~~~~~~~~~~~~~~
Qer can be simply installed by running::

    pip install qer

Two entrypoint scripts are provided::

    req-compile <input reqfile1> ... <input_reqfileN> [--constraints constraint_file] [--index-url https://...]
    req-hash <input reqfile1> ... <input_reqfileN>

Producing output requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
To produce a fully constrained set of requirements for a given number of input requirements files, pass requirements
files to req-compile::

    > cat requirements.txt
    astroid>=2.0.0
    isort >= 4.2.5
    mccabe

    > req-compile requirements.txt
    astroid==2.1.0                          #
    futures==3.2.0                          # isort
    isort==4.3.4                            #
    lazy-object-proxy==1.3.1                #
    mccabe==0.6.1                           #
    six==1.12.0                             # astroid
    typing==3.6.6                           # astroid
    wrapt==1.11.1                           # astroid

Output is always emitted to stdout. Possible inputs include::

    > req-compile
    > req-compile .
    # Compiles the current directory (looks for a setup.py)

    > req-compile .[test]
    # Compiles the current directory with the extra "test"

    > req-compile subdir/project
    # Compiles the project in the subdir/project directory

    > req-compile subdir/project2[test,docs]
    # Compiles the project in the subdir/project2 directory with the test and docs extra requirements included

    > req-candidates --paths-only | req-compile
    # Search for candidates and compile them piped in via stdin

    > echo flask | req-compile
    # Compile the requirement 'flask' using the defaut remote index (PyPI)


Specifying source of distributions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Qer supports obtaining python distributions from multiple sources, each of which can be specified more than once. The following sources
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
  a remote index would, wheels, zips, and source tarballs. This matches pip's commmand line.
* ``--index-url``

  URL of a remote index to search for packages in. When compiling, it's necessary to download
  a package to determine its requirements.  ``--wheel-dir`` can be supplied to specify where to save
  these distributions. Otherwise they will be deleted after compilation is complete.

All options can be repeated multiple times, with the resolution order within types matching what
was passed on the commandline. However, overall resolution order will always match the order
of the list above.

By default, PyPI (https://pypi.org/) is added as a default source.  It can be removed by passing
``--no-index`` on the commandline.

Identifying source of constraints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Why did I just get version 1.11.0 of ``six``? Find out by examining the output::

    six==1.11.0  # astroid, pathlib2, pymodbus (==1.11.0), pytest (>=1.10.0), more_itertools (<2.0.0,>=1.0.0)

Hashing input requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~
Hash input requirements by allowing Qer to parse, combine, and hash a single list. This will allow
multiple input files to be logically combined so irrelevant changes don't cause recompilations. For example,
adding ``tenacity`` to a nested requirements file when ``tenacity`` is already included elsewhere.::

    > req-hash projectreqs.txt
    dc2f25c1b28226b25961a5320e25c339e630342d0ce700b126a5857eeeb9ba12

Constraining output
~~~~~~~~~~~~~~~~~~~
Constrain production outputs with test requirements using the ``--constraints`` flag. More than one file can be
passed::

    > cat requirements.txt
    astroid

    > cat test-requirements.txt
    pylint<1.6

    > req-compile requirements.txt --constraints test-requirements.txt
    astroid==1.4.9                          # (via constraints: pylint (<1.5.0,>=1.4.5))
    lazy-object-proxy==1.3.1                # astroid
    six==1.12.0                             # astroid
    wrapt==1.11.1                           # astroid

Note that astroid is constrained by ``pylint``, even though ``pylint`` is not included in the output.

Advanced Features
-----------------
Compiling a constrained subset
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Input can be supplied via stdin as well as via as through files.  For example, to supply a full
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
    No version of astroid could satisfy the following requirements:
       projectreqs.txt requires astroid<1.6
       pylint 1.9.4 (via projectreqs.txt (>=1.5)) requires astroid<2.0,>=1.6

Saving distributions
~~~~~~~~~~~~~~~~~~~~
Files downloading during the compile process can be saved for later install. This can optimize
the execution times of builds when a separate compile step is required::

    > req-compile projectreqs.txt --wheel-dir .wheeldir > compiledreqs.txt
    > pip install -r compilereqs.txt --find-links .wheeldir --no-index

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
in the current directory (as defined by a setup.py).  This is a *stable* set, in that only changes to
the requirements and constraints would produce a new output.  To produce a totally fresh compilation,
don't pass in a previous solution.

The find-links parameter to the sync or pip install will *reuse* the wheels already downloaded by Qer during
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
Qer can discover requirements that are grouped together on the filesystem. The
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
