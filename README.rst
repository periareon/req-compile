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

You have a project with requirements `requirements.txt` and test requirements `test-requirements.txt`. You want
to produce a fully constrained output of `requirements.txt` to use to deploy your application. Easy, right? Just
compile `requirements.txt`. However, if your test requirements will in any way constrain packages you need,
even those needed transitively, it means you will have tested with different versions than you'll ship.

For this reason, you can user Qer to compile `requirements.txt` using `test-requirements.txt` as constraints.

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

Identifying source of constraints
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Why did I just get version 1.11.0 of `six`? Find out by examining the output::

    six==1.11.0  # astroid, pathlib2, pymodbus (==1.11.0), pytest (>=1.10.0), more_itertools (<2.0.0,>=1.0.0)

See "Extra requirements pedigree" for more.

Hashing input requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~
Hash input requirements by allowing Qer to parse, combine, and hash a single list. This will allow
multiple input files to be logically combined so irrelevant changes don't cause recompilations. For example,
adding `tenacity` to a nested requirements file when `tenacity` is already included elsewhere.::

    > req-hash projectreqs.txt
    dc2f25c1b28226b25961a5320e25c339e630342d0ce700b126a5857eeeb9ba12

Constraining output
~~~~~~~~~~~~~~~~~~~
Constrain production outputs with test requirements using the `--constraints` flag. More than one file can be
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

Note that astroid is constrained by `pylint`, even though `pylint` is not included in the output.

Advanced Features
-----------------

Extra requirements pedigree
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Passing the `--no-combine` flag will instruct Qer to retain all of the source information about
requirements files. This means every line of the output file will contain an annotation::

    > cat projectreqs.txt
    astroid
    pylint>=1.5

    > req-compile requirements.txt --no-combine
    astroid==1.6.5                             # projectreqs.txt, pylint (<2.0,>=1.6)
    backports.functools-lru-cache==1.5         # astroid, pylint
    colorama==0.4.1                            # pylint
    configparser==3.7.1                        # pylint
    enum34==1.1.6                              # astroid (>=1.1.3)
    futures==3.2.0                             # isort
    isort==4.3.4                               # pylint (>=4.2.5)
    lazy-object-proxy==1.3.1                   # astroid
    mccabe==0.6.1                              # pylint
    pylint==1.9.4                              # projectreqs.txt (>=1.5)
    singledispatch==3.4.0.3                    # astroid, pylint
    six==1.12.0                                # astroid, singledispatch, pylint
    wrapt==1.11.1                              # astroid

Resolving constraint conflicts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
`--no-combine` is also useful when deconflicting::

    > cat projectreqs.txt
    astroid<1.6
    pylint>=1.5

    > req-compile projectreqs.txt --no-combine
    No version of astroid could satisfy the following requirements:
       projectreqs.txt requires astroid<1.6
       pylint 1.9.4 (via projectreqs.txt (>=1.5)) requires astroid<2.0,>=1.6

Saving distributions
~~~~~~~~~~~~~~~~~~~~
Files downloading during the compile process can be saved for later install. This can optimize
the execution times of builds when a separate compile step is required.::

    > req-compile projectreqs.txt --wheel-dir .wheeldir > compiledreqs.txt
    > pip install -r compilereqs.txt --find-links .wheeldir --no-index
