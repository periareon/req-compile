"""Errors describing problems that can occur when extracting metadata"""


class MetadataError(Exception):
    def __init__(self, name, version, ex):
        super(MetadataError, self).__init__()
        self.name = name
        self.version = version
        self.ex = ex

    def __str__(self):
        return "Failed to parse metadata for package {} ({}) - {}: {}".format(
            self.name, self.version, self.ex.__class__.__name__, str(self.ex)
        )
