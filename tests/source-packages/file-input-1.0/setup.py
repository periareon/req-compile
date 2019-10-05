import setuptools
import sys, fileinput


def replaceString(file, searchExp, replaceExp):
    if file == None: return  # fail silently
    for line in fileinput.input(file, inplace=1):
        if searchExp in line:
            line = line.replace(searchExp, replaceExp)
        sys.stdout.write(line)

replaceString('versions.cfg', 'version', 'VERSION')

setuptools.setup(
    name='file-input',
    version='1.0',
)