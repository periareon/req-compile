import os
from os.path import expanduser
import sys

from six.moves import configparser


def _get_config_paths():
    # Try user specific config file first
    if sys.platform.startswith('linux2'):
        home = expanduser("~")
        user_config = os.path.join(home, '.config', 'pip', 'pip.conf')
        site_config = '/etc/pip.conf'
    elif sys.platform == 'win32':
        user_config = os.path.join(os.getenv('LOCALAPPDATA'), 'pip', 'pip.ini')
        site_config = os.path.join(os.getenv('PROGRAMDATA'), 'pip', 'pip.ini')
    else:
        return ()

    return site_config, user_config


def read_pip_default_index():
    config_files = _get_config_paths()

    config = configparser.ConfigParser()
    config.read(config_files)

    try:
        return config.get('global', 'index-url')
    except configparser.NoSectionError:
        return None
