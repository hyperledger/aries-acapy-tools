"""Module setup."""

import os
from setuptools import setup, find_packages

PACKAGE_NAME = "aries_askar_upgrade"
VERSION = "0.1.0"


with open(os.path.abspath("./README.md"), "r") as fh:
    long_description = fh.read()


if __name__ == "__main__":
    setup(
        name=PACKAGE_NAME,
        version=VERSION,
        long_description=long_description,
        long_description_content_type="text/markdown",
        url="https://github.com/hyperledger/aries-askar",
        packages=find_packages(),
        install_requires=[
            "aiosqlite~=0.17",
            "aries_askar~=0.2",
            "asyncpg~=0.22",
            "base58~=1.0",
            "cbor2~=5.2",
            "msgpack~=1.0",
            "pynacl~=1.4",
        ],
        python_requires=">=3.6.3",
        classifiers=[
            "Programming Language :: Python :: 3",
            "License :: OSI Approved :: Apache Software License",
            "Operating System :: OS Independent",
        ],
        scripts=["bin/askar-upgrade.py"],
    )
