from setuptools import setup, find_packages


def load_version(path: str) -> str:
    """Load the current version from a file expected to contain `VERSION = "{version}"`."""
    version = None
    with open(path, "r", encoding="utf-8") as file:
        for line in file.readlines():
            if not line.startswith("VERSION = "):
                continue
            version = line[len("VERSION = ") :].strip(' \r\n"')

    if not version:
        raise ValueError(f"No version data found in {path}")

    return version


setup(
    name="req-compile",
    version=load_version("version.bzl"),
    author="Spencer Putt",
    author_email="sputt@alumni.iu.edu",
    description="Python requirements compiler",
    long_description=open("CHANGELOG.rst").read() + "\n" + open("README.rst").read(),
    url="https://github.com/sputt/req-compile",
    install_requires=open("requirements.in").readlines(),
    packages=find_packages(include=["req_compile*"]),
    package_data={"": ["py.typed"]},
    license="MIT License",
    entry_points={
        "console_scripts": [
            "req-compile = req_compile.cmdline:compile_main",
            "req-candidates = req_compile.candidates:candidates_main",
        ],
    },
    python_requires=">=3.0, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Environment :: Console",
        "Topic :: Software Development",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
    ],
)
