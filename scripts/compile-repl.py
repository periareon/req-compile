import subprocess
import sys

from six.moves import input
while True:
    pkg_name = input('Package name: ')
    p = subprocess.Popen([sys.executable, '-m', 'req_compile', '--verbose'], stdin=subprocess.PIPE)
    p.communicate(pkg_name + '\n')
