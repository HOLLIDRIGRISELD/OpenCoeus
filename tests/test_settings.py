import os
import tempfile
import unittest

from opencoeus.settings import Settings, settings_path


class SettingsTests(unittest.TestCase):
    def setUp(self):
        # POINT THE DATA DIRECTORY AT A TEMP FOLDER FOR ISOLATION.
        self._data_dir = tempfile.TemporaryDirectory()
        self._old_data_dir = os.environ.get("OPENCOEUS_DATA_DIR")
        os.environ["OPENCOEUS_DATA_DIR"] = self._data_dir.name

    def tearDown(self):
        if self._old_data_dir is None:
            os.environ.pop("OPENCOEUS_DATA_DIR", None)
        else:
            os.environ["OPENCOEUS_DATA_DIR"] = self._old_data_dir
        self._data_dir.cleanup()

    def test_load_returns_defaults_when_missing(self):
        # VERIFIES THAT LOAD RETURNS DEFAULTS WHEN NO SETTINGS FILE EXISTS.
        settings = Settings.load()
        self.assertTrue(settings.dark_theme)
        self.assertTrue(settings.organize_after_scan)
        self.assertTrue(settings.confirm_execute)
        self.assertTrue(settings.confirm_undo)

    def test_save_then_load_roundtrip(self):
        # VERIFIES THAT SAVED VALUES SURVIVE A LOAD ROUND TRIP.
        settings = Settings(dark_theme=False, organize_after_scan=False)
        settings.save()
        self.assertTrue(settings_path().exists())
        loaded = Settings.load()
        self.assertFalse(loaded.dark_theme)
        self.assertFalse(loaded.organize_after_scan)
        self.assertTrue(loaded.confirm_execute)
        self.assertTrue(loaded.confirm_undo)

    def test_load_ignores_unknown_keys(self):
        # VERIFIES THAT UNKNOWN JSON KEYS ARE IGNORED ON LOAD.
        settings_path().write_text(
            '{"dark_theme": false, "bogus": 1, "confirm_undo": false}',
            encoding="utf-8",
        )
        loaded = Settings.load()
        self.assertFalse(loaded.dark_theme)
        self.assertFalse(loaded.confirm_undo)

    def test_load_falls_back_to_defaults_on_malformed_file(self):
        # VERIFIES THAT A MALFORMED SETTINGS FILE FALLS BACK TO DEFAULTS.
        settings_path().write_text("{not json", encoding="utf-8")
        loaded = Settings.load()
        self.assertEqual(loaded, Settings())


if __name__ == "__main__":
    unittest.main()
