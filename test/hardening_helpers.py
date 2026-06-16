import os
import shutil
from unittest import TestCase

from . import TEMP_FOLDER


class TempFolderTestCase(TestCase):
    temp_name = "hardening"

    def setUp(self):
        self.temp_folder = os.path.join(
            TEMP_FOLDER,
            self.temp_name,
            self.__class__.__name__,
            self._testMethodName,
        )
        shutil.rmtree(self.temp_folder, ignore_errors=True)
        os.makedirs(self.temp_folder, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_folder, ignore_errors=True)
