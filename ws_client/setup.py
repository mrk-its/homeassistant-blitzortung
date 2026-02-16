#!/usr/bin/env python
import os
import shutil

import setuptools

cur_dir = os.path.dirname(__file__)

shutil.copy(
    f"{cur_dir}/../custom_components/blitzortung/version.py",
    f"{cur_dir}/ws_client/component_version.py",
)
setuptools.setup()
