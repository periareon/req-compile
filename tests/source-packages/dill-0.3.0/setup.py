import os

# set version numbers
stable_version = '0.3.0'
target_version = '0.3.0'
is_release = stable_version == target_version

# check if easy_install is available
try:
#   import __force_distutils__ #XXX: uncomment to force use of distutills
    from setuptools import setup
    has_setuptools = True
except ImportError:
    from distutils.core import setup
    has_setuptools = False

# generate version number
if os.path.exists('dill/info.py'):
    # is a source distribution, so use existing version
    os.chdir('dill')
    with open('info.py','r') as f:
        f.readline() # header
        this_version = f.readline().split()[-1].strip("'")
    os.chdir('..')
elif stable_version == target_version:
    # we are building a stable release
    this_version = target_version
else:
    # we are building a distribution
    this_version = target_version + '.dev0'
    if is_release:
        from datetime import date
        today = "".join(date.isoformat(date.today()).split('-'))
        this_version += "-" + today

# get the license info
with open('LICENSE') as file:
    license_text = file.read()

# generate the readme text
long_description = \
"""%(relver)s %(thisver)s""" % {'relver' : stable_version, 'thisver' : this_version}

# write readme file
with open('README', 'w') as file:
    file.write(long_description)

# generate 'info' file contents
def write_info_py(filename='dill/info.py'):
    contents = """# THIS FILE GENERATED FROM SETUP.PY
this_version = '%(this_version)s'
stable_version = '%(stable_version)s'
readme = '''%(long_description)s'''
license = '''%(license_text)s'''
"""
    with open(filename, 'w') as file:
        file.write(contents % {'this_version' : this_version,
                               'stable_version' : stable_version,
                               'long_description' : long_description,
                               'license_text' : license_text })
    return

# write info file
write_info_py()

# build the 'setup' call
setup_code = """
setup(name='dill',
      version='%s',
      long_description = '''%s''',
      download_url = 'https://dill-%s/dill-%s.tar.gz',
      python_requires='>=2.6, !=3.0.*',
      packages = ['dill','dill.tests'],
      package_dir = {'dill':'dill', 'dill.tests':'tests'},
""" % (target_version, long_description, stable_version, stable_version)

# add dependencies
ctypes_version = '>=1.0.1'
objgraph_version = '>=1.7.2'
pyreadline_version = '>=1.7.1'
import sys
if has_setuptools:
    setup_code += """
      zip_safe=False,
"""
    if sys.platform[:3] == 'win':
        setup_code += """
      extras_require = {'readline': ['pyreadline%s'], 'graph': ['objgraph%s']},
""" % (pyreadline_version, objgraph_version)
    # verrrry unlikely that this is still relevant
    elif hex(sys.hexversion) < '0x20500f0':
        setup_code += """
      install_requires = ['ctypes%s'],
      extras_require = {'readline': [], 'graph': ['objgraph%s']},
""" % (ctypes_version, objgraph_version)
    else:
        setup_code += """
      extras_require = {'readline': [], 'graph': ['objgraph%s']},
""" % (objgraph_version)

# add the scripts, and close 'setup' call
setup_code += """    
      scripts=['scripts/undill','scripts/get_objgraph'])
"""

# exec the 'setup' code
exec(setup_code)

# if dependencies are missing, print a warning
try:
    import ctypes
    import readline
except ImportError:
    print ("\n***********************************************************")
    print ("WARNING: One of the following dependencies is unresolved:")
    print ("    ctypes %s" % ctypes_version)
    if sys.platform[:3] == 'win':
        print ("    readline %s" % pyreadline_version)
    print ("***********************************************************\n")
