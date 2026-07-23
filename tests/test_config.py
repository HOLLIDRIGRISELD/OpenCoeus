import unittest
from pathlib import Path

from opencoeus.config import default_application_data_directory, default_protected_patterns


class CrossPlatformConfigTests(unittest.TestCase):
    def test_platform_protected_patterns_include_common_application_folder(self):
        for operating_system_name in ("Windows", "Darwin", "Linux"):
            self.assertIn(r"^\.opencoeus$", default_protected_patterns(operating_system_name))

    def test_native_data_directories_use_expected_platform_locations(self):
        self.assertEqual(default_application_data_directory("Darwin").name, "OpenCoeus")
        self.assertEqual(default_application_data_directory("Linux").name, "OpenCoeus")
        self.assertEqual(default_application_data_directory("Windows").name, "OpenCoeus")
