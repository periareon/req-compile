from ._common import LINUX
from ._common import WINDOWS

if LINUX:
    from . import _pslinux as _psplatform
elif WINDOWS:
    from . import _pswindows as _psplatform

__all__.extend(_psplatform.__extra__all__)
__author__ = "Giampaolo Rodola'"
__version__ = "5.6.2"
version_info = tuple([int(num) for num in __version__.split('.')])
