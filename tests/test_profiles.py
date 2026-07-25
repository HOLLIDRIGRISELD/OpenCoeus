import tempfile
import unittest
from pathlib import Path

from opencoeus.database import AuditStore
from opencoeus.profiles import (
    ProfileConfig,
    create_profile,
    delete_profile,
    list_profiles,
    load_profile,
    load_profile_by_name,
    update_profile,
)


class CreateProfileTests(unittest.TestCase):
    def test_create_profile_returns_config_with_id(self):
        # VERIFIES THAT create_profile RETURNS A ProfileConfig WITH A NON NONE profile_id.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            config = create_profile(store, "Work Files", "/Users/me/Documents")
            self.assertIsNotNone(config.profile_id)
            self.assertEqual(config.name, "Work Files")
            self.assertEqual(config.root_path, "/Users/me/Documents")
            store.close()

    def test_create_profile_default_values(self):
        # VERIFIES THAT create_profile USES EMPTY LISTS AND document_extraction=True BY DEFAULT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            config = create_profile(store, "Defaults")
            self.assertEqual(config.included_folders, [])
            self.assertEqual(config.excluded_folders, [])
            self.assertEqual(config.custom_protected_patterns, [])
            self.assertTrue(config.document_extraction)
            store.close()

    def test_create_profile_with_custom_folders(self):
        # VERIFIES THAT create_profile STORES CUSTOM INCLUDED AND EXCLUDED FOLDER LISTS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            config = create_profile(
                store, "Custom",
                included_folders=["/docs", "/images"],
                excluded_folders=["/temp"],
            )
            self.assertEqual(config.included_folders, ["/docs", "/images"])
            self.assertEqual(config.excluded_folders, ["/temp"])
            store.close()


class LoadProfileTests(unittest.TestCase):
    def test_load_profile_returns_config(self):
        # VERIFIES THAT load_profile RETURNS A ProfileConfig MATCHING THE CREATED PROFILE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            created = create_profile(store, "Loadable")
            loaded = load_profile(store, created.profile_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.name, "Loadable")
            store.close()

    def test_load_profile_returns_none_for_missing(self):
        # VERIFIES THAT load_profile RETURNS NONE WHEN THE PROFILE_ID DOES NOT EXIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            loaded = load_profile(store, 9999)
            self.assertIsNone(loaded)
            store.close()

    def test_load_profile_by_name_returns_config(self):
        # VERIFIES THAT load_profile_by_name RETURNS A ProfileConfig MATCHING THE NAME.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            create_profile(store, "Named Profile")
            loaded = load_profile_by_name(store, "Named Profile")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.name, "Named Profile")
            store.close()

    def test_load_profile_by_name_returns_none_for_missing(self):
        # VERIFIES THAT load_profile_by_name RETURNS NONE WHEN NO PROFILE MATCHES THE NAME.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            loaded = load_profile_by_name(store, "Ghost")
            self.assertIsNone(loaded)
            store.close()


class ListProfilesTests(unittest.TestCase):
    def test_list_profiles_returns_all(self):
        # VERIFIES THAT list_profiles RETURNS ALL CREATED PROFILES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            create_profile(store, "Alpha")
            create_profile(store, "Beta")
            profiles = list_profiles(store)
            names = [p.name for p in profiles]
            self.assertEqual(names, ["Alpha", "Beta"])
            store.close()

    def test_list_profiles_returns_empty_when_none_exist(self):
        # VERIFIES THAT list_profiles RETURNS AN EMPTY LIST WHEN NO PROFILES EXIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profiles = list_profiles(store)
            self.assertEqual(profiles, [])
            store.close()


class UpdateProfileTests(unittest.TestCase):
    def test_update_profile_modifies_fields(self):
        # VERIFIES THAT update_profile CHANGES SPECIFIED FIELDS AND RETURNS UPDATED CONFIG.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            created = create_profile(store, "Original")
            updated = update_profile(store, created.profile_id, name="Updated")
            self.assertEqual(updated.name, "Updated")
            store.close()

    def test_update_profile_serializes_lists(self):
        # VERIFIES THAT LIST FIELDS ARE PROPERLY SERIALIZED WHEN UPDATED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            created = create_profile(store, "Lists")
            updated = update_profile(store, created.profile_id, included_folders=["/a", "/b"])
            self.assertEqual(updated.included_folders, ["/a", "/b"])
            store.close()

    def test_update_profile_returns_none_for_missing(self):
        # VERIFIES THAT update_profile RETURNS NONE WHEN THE PROFILE DOES NOT EXIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = update_profile(store, 9999, name="Nope")
            self.assertIsNone(result)
            store.close()


class DeleteProfileTests(unittest.TestCase):
    def test_delete_profile_returns_true(self):
        # VERIFIES THAT delete_profile RETURNS TRUE AND THE PROFILE CAN NO LONGER BE LOADED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            created = create_profile(store, "Delete Me")
            result = delete_profile(store, created.profile_id)
            self.assertTrue(result)
            self.assertIsNone(load_profile(store, created.profile_id))
            store.close()

    def test_delete_profile_returns_false_for_missing(self):
        # VERIFIES THAT delete_profile RETURNS FALSE WHEN THE PROFILE DOES NOT EXIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = delete_profile(store, 9999)
            self.assertFalse(result)
            store.close()


class ProfileConfigTests(unittest.TestCase):
    def test_profile_config_is_dataclass(self):
        # VERIFIES THAT ProfileConfig IS A DATACLASS WITH THE EXPECTED FIELDS.
        config = ProfileConfig()
        self.assertIsNone(config.profile_id)
        self.assertEqual(config.name, "")
        self.assertEqual(config.root_path, "")
        self.assertEqual(config.included_folders, [])
        self.assertEqual(config.excluded_folders, [])
        self.assertEqual(config.custom_protected_patterns, [])
        self.assertTrue(config.document_extraction)


if __name__ == "__main__":
    unittest.main()
