#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

setup(
    name="ntnu_inginious_multifill",
    version="0.1dev0",
    description="Plugin to add problem types with multiple text entries",
    packages=find_packages(),
    tests_require=[],
    extras_require={},
    scripts=[],
    include_package_data=True,
    author="Håvard Krogstie",
    author_email="inginious@info.ucl.ac.be",
    license="AGPL 3",
    url="https://github.com/thaugdahl/ntnu-inginious-ansible"
)
