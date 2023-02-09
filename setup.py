from setuptools import setup, find_packages

setup(
    name="req-compile",
    version="1.0.0pre4",
    author="Spencer Putt",
    author_email="sputt@alumni.iu.edu",
    description="Python requirements compiler",
    long_description=open("CHANGELOG.rst").read() + "\n" + open("README.rst").read(),
    url="https://github.com/sputt/req-compile",
    install_requires=open("requirements.in").readlines(),
    packages=find_packages(include=["req_compile*"]),
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
        "Operating System :: OS Independent",
        "Environment :: Console",
        "Topic :: Software Development",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
    ],
)
