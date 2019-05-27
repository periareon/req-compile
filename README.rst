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

Output is always emitted to stdout.

Specifying source of distributions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Qer supports obtaining python distributions from multiple sources, each of which can be specified more than once. The following sources
can be specified, resolved in the same order (e.g. source takes precedence over index-url):

* ``--source``

  Use a local filesystem with source python packages to compile from. This will search the entire
  tree specified at the source directory, until an __init__.py is reached. ``--remove-source`` can
  be supplied to remove results that were obtained from source directories. You may want to do
  this if compiling for a project and only third party requirements compilation results need to be saved.
* ``--solution``

  Load a previous solution and use it as a source of distributions. This will allow a full
  recompilation of a working solution without requiring any other source
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

