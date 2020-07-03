#!/usr/bin/env python
import setuptools
import shutil
import os

cur_dir = os.path.dirname(__file__)

shutil.copy(
    f"{cur_dir}/../custom_component/blitzortung/version.py",
    f"{cur_dir}/ws_client/component_version.py",
)
setuptools.setup()
