from setuptools import setup, find_packages

setup(
    name="req-compile",
    version="0.10.21",
    author="Spencer Putt",
    author_email="sputt@alumni.iu.edu",
    description="Python requirements compiler",
    long_description=open("CHANGELOG.rst").read() + "\n" + open("README.rst").read(),
    url="https://github.com/sputt/req-compile",
    install_requires=open("requirements.txt").readlines(),
    packages=find_packages(include=["req_compile*"]),
    license="MIT License",
    entry_points={
        "console_scripts": [
            "req-compile = req_compile.cmdline:compile_main",
            "req-candidates = req_compile.candidates:candidates_main",
        ],
    },
    python_requires=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Operating System :: OS Independent",
        "Environment :: Console",
        "Topic :: Software Development",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
    ],
)
