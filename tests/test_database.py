import tempfile
import unittest
from pathlib import Path

from opencoeus.database import AuditStore


class AuditStoreRecordTests(unittest.TestCase):
    def test_records_new_file_successfully(self):
        # VERIFIES THAT A NEW FILE CAN BE RECORDED IN THE AUDIT DATABASE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/file.txt", 1024, "abc123", "unique")
            # RECORDDING SHOULD NOT RAISE ANY ERRORS.
            store.close()

    def test_updates_existing_file_record(self):
        # VERIFIES THAT RECORDING THE SAME FILE PATH TWICE UPDATES THE EXISTING RECORD.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/file.txt", 1024, "hash1", "unique")
            store.record_file("/test/file.txt", 2048, "hash2", "duplicate")
            # THE SECOND RECORD SHOULD UPDATE, NOT CREATE A NEW ROW.
            store.close()

    def test_records_file_with_none_hash(self):
        # VERIFIES THAT A FILE CAN BE RECORDED WITH A NONE HASH VALUE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/protected.bin", 512, None, "protected")
            store.close()

    def test_records_multiple_files_independently(self):
        # VERIFIES THAT MULTIPLE DIFFERENT FILES ARE STORED AS SEPARATE RECORDS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/file_a.txt", 100, "hash_a", "unique")
            store.record_file("/file_b.txt", 200, "hash_b", "duplicate")
            store.record_file("/file_c.txt", 300, None, "protected")
            store.close()


class AuditStoreReserveTitleTests(unittest.TestCase):
    def test_reserves_unique_title(self):
        # VERIFIES THAT A TITLE NOT ALREADY IN THE DATABASE IS RESERVED AS-IS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            reserved = store.reserve_title("My Document Title", "/path/to/file.pdf")
            self.assertEqual(reserved, "My Document Title")
            store.close()

    def test_returns_same_title_for_same_source_path(self):
        # VERIFIES THAT REQUESTING THE SAME TITLE FOR THE SAME SOURCE RETURNS THE SAME RESULT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            first_reservation = store.reserve_title("First Title", "/same/path.pdf")
            second_reservation = store.reserve_title("Different Title", "/same/path.pdf")
            self.assertEqual(first_reservation, second_reservation)
            self.assertEqual(first_reservation, "First Title")
            store.close()

    def test_appends_number_on_duplicate_title(self):
        # VERIFIES THAT A DUPLICATE TITLE GETS A NUMBER SUFFIX LIKE (2).
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            first_reservation = store.reserve_title("Shared Title", "/file_a.pdf")
            second_reservation = store.reserve_title("Shared Title", "/file_b.pdf")
            self.assertEqual(first_reservation, "Shared Title")
            self.assertEqual(second_reservation, "Shared Title (2)")
            store.close()

    def test_appends_incrementing_numbers(self):
        # VERIFIES THAT MULTIPLE DUPLICATE TITLES GET INCREMENTING NUMBERS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            first = store.reserve_title("Collision", "/a.pdf")
            second = store.reserve_title("Collision", "/b.pdf")
            third = store.reserve_title("Collision", "/c.pdf")
            fourth = store.reserve_title("Collision", "/d.pdf")
            self.assertEqual(first, "Collision")
            self.assertEqual(second, "Collision (2)")
            self.assertEqual(third, "Collision (3)")
            self.assertEqual(fourth, "Collision (4)")
            store.close()

    def test_different_titles_for_different_source_paths(self):
        # VERIFIES THAT DIFFERENT SOURCE PATHS CAN HAVE DIFFERENT TITLES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            title_a = store.reserve_title("Alpha Document", "/alpha.pdf")
            title_b = store.reserve_title("Beta Document", "/beta.pdf")
            self.assertEqual(title_a, "Alpha Document")
            self.assertEqual(title_b, "Beta Document")
            store.close()


class AuditStoreCloseTests(unittest.TestCase):
    def test_close_disposes_engine(self):
        # VERIFIES THAT close() DOES NOT RAISE ERRORS AND CAN BE CALLED MULTIPLE TIMES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.close()
            # DOUBLE-CLOSE SHOULD NOT RAISE.
            store.close()


# STAGE 2: PROFILE MANAGEMENT TESTS.


class AuditStoreProfileTests(unittest.TestCase):
    def test_create_profile_returns_profile_with_id(self):
        # VERIFIES THAT A NEW PROFILE IS CREATED AND HAS AN INTEGER ID ASSIGNED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Work Files", "/Users/me/Documents")
            self.assertIsNotNone(profile.id)
            self.assertIsInstance(profile.id, int)
            self.assertEqual(profile.name, "Work Files")
            store.close()

    def test_create_profile_stores_default_values(self):
        # VERIFIES THAT DEFAULT FOLDER LISTS ARE EMPTY JSON ARRAYS AND EXTRACTION IS TRUE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Defaults")
            self.assertEqual(profile.included_folders, "[]")
            self.assertEqual(profile.excluded_folders, "[]")
            self.assertEqual(profile.custom_protected_patterns, "[]")
            self.assertTrue(profile.document_extraction)
            store.close()

    def test_list_profiles_returns_all_ordered_by_name(self):
        # VERIFIES THAT LISTING PROFILES RETURNS THEM IN ALPHABETICAL NAME ORDER.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.create_profile("Zulu Profile")
            store.create_profile("Alpha Profile")
            store.create_profile("Mid Profile")
            profiles = store.list_profiles()
            names = [p.name for p in profiles]
            self.assertEqual(names, ["Alpha Profile", "Mid Profile", "Zulu Profile"])
            store.close()

    def test_get_profile_returns_profile_by_id(self):
        # VERIFIES THAT A PROFILE CAN BE RETRIEVED BY ITS ID.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            created = store.create_profile("Fetchable")
            fetched = store.get_profile(created.id)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.name, "Fetchable")
            store.close()

    def test_get_profile_returns_none_for_missing_id(self):
        # VERIFIES THAT REQUESTING A NONEXISTENT PROFILE ID RETURNS NONE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.get_profile(9999)
            self.assertIsNone(result)
            store.close()

    def test_get_profile_by_name_returns_profile(self):
        # VERIFIES THAT A PROFILE CAN BE RETRIEVED BY ITS UNIQUE NAME.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.create_profile("Named Profile")
            found = store.get_profile_by_name("Named Profile")
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "Named Profile")
            store.close()

    def test_get_profile_by_name_returns_none_for_missing(self):
        # VERIFIES THAT REQUESTING A NONEXISTENT PROFILE NAME RETURNS NONE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.get_profile_by_name("Ghost Profile")
            self.assertIsNone(result)
            store.close()

    def test_update_profile_modifies_fields(self):
        # VERIFIES THAT UPDATE CHANGES SPECIFIED FIELDS ON A PROFILE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Original")
            store.update_profile(profile.id, name="Updated", root_path="/new/path")
            updated = store.get_profile(profile.id)
            self.assertEqual(updated.name, "Updated")
            self.assertEqual(updated.root_path, "/new/path")
            store.close()

    def test_update_profile_serializes_list_fields(self):
        # VERIFIES THAT LIST FIELDS ARE AUTOMATICALLY CONVERTED TO JSON STRINGS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Lists")
            store.update_profile(profile.id, included_folders=["docs", "images"], excluded_folders=["temp"])
            updated = store.get_profile(profile.id)
            self.assertEqual(updated.included_folders, '["docs", "images"]')
            self.assertEqual(updated.excluded_folders, '["temp"]')
            store.close()

    def test_update_profile_returns_none_for_missing_id(self):
        # VERIFIES THAT UPDATING A NONEXISTENT PROFILE RETURNS NONE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.update_profile(9999, name="Nope")
            self.assertIsNone(result)
            store.close()

    def test_delete_profile_returns_true(self):
        # VERIFIES THAT DELETING AN EXISTING PROFILE RETURNS TRUE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("To Delete")
            result = store.delete_profile(profile.id)
            self.assertTrue(result)
            self.assertIsNone(store.get_profile(profile.id))
            store.close()

    def test_delete_profile_returns_false_for_missing(self):
        # VERIFIES THAT DELETING A NONEXISTENT PROFILE RETURNS FALSE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.delete_profile(9999)
            self.assertFalse(result)
            store.close()

    def test_delete_profile_cascades_classifications_and_rules(self):
        # VERIFIES THAT DELETING A PROFILE REMOVES ITS ASSOCIATED CLASSIFICATIONS AND RULES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Cascade")
            store.save_classifications(profile.id, [
                {"folder_path": "/a", "classification": "stable", "recommended_action": "no_action"},
            ])
            store.create_rule(profile.id, "Test Rule", "extension", {}, "/dest/{filename}")
            store.delete_profile(profile.id)
            self.assertEqual(len(store.get_classifications(profile.id)), 0)
            self.assertEqual(len(store.get_rules(profile.id)), 0)
            store.close()


# STAGE 2: FOLDER CLASSIFICATION TESTS.


class AuditStoreClassificationTests(unittest.TestCase):
    def _create_profile_with_store(self, store: AuditStore) -> int:
        # HELPER TO CREATE A PROFILE AND RETURN ITS ID.
        profile = store.create_profile("Classification Test")
        return profile.id

    def test_save_classifications_stores_records(self):
        # VERIFIES THAT SAVING CLASSIFICATIONS PERSISTS THEM IN THE DATABASE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_classifications(profile_id, [
                {"folder_path": "/projects/alpha", "classification": "stable", "recommended_action": "no_action"},
                {"folder_path": "/temp/scratch", "classification": "disposable", "recommended_action": "suggest_delete"},
            ])
            results = store.get_classifications(profile_id)
            self.assertEqual(len(results), 2)
            store.close()

    def test_save_classifications_replaces_existing(self):
        # VERIFIES THAT SAVING NEW CLASSIFICATIONS REPLACES THE OLD ONES FOR A PROFILE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_classifications(profile_id, [
                {"folder_path": "/old", "classification": "stable", "recommended_action": "no_action"},
            ])
            store.save_classifications(profile_id, [
                {"folder_path": "/new_a", "classification": "active", "recommended_action": "organize"},
                {"folder_path": "/new_b", "classification": "active", "recommended_action": "organize"},
            ])
            results = store.get_classifications(profile_id)
            self.assertEqual(len(results), 2)
            paths = {c.folder_path for c in results}
            self.assertEqual(paths, {"/new_a", "/new_b"})
            store.close()

    def test_get_classifications_returns_empty_for_profile_with_none(self):
        # VERIFIES THAT A PROFILE WITH NO CLASSIFICATIONS RETURNS AN EMPTY LIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            results = store.get_classifications(profile_id)
            self.assertEqual(results, [])
            store.close()

    def test_update_classification_override_sets_value(self):
        # VERIFIES THAT A USER OVERRIDE CAN BE SET ON A CLASSIFICATION.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_classifications(profile_id, [
                {"folder_path": "/data", "classification": "unknown", "recommended_action": "ask_user"},
            ])
            classification = store.get_classifications(profile_id)[0]
            result = store.update_classification_override(classification.id, "stable")
            self.assertTrue(result)
            updated = store.get_classifications(profile_id)[0]
            self.assertEqual(updated.user_override, "stable")
            store.close()

    def test_update_classification_override_clears_value(self):
        # VERIFIES THAT A USER OVERRIDE CAN BE SET BACK TO NONE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_classifications(profile_id, [
                {"folder_path": "/data", "classification": "unknown", "recommended_action": "ask_user",
                 "user_override": "stable"},
            ])
            classification = store.get_classifications(profile_id)[0]
            store.update_classification_override(classification.id, None)
            updated = store.get_classifications(profile_id)[0]
            self.assertIsNone(updated.user_override)
            store.close()

    def test_update_classification_override_returns_false_for_missing(self):
        # VERIFIES THAT UPDATING A NONEXISTENT CLASSIFICATION RETURNS FALSE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.update_classification_override(9999, "stable")
            self.assertFalse(result)
            store.close()

    def test_classifications_store_reason(self):
        # VERIFIES THAT THE REASON FIELD IS PERSISTED ON A CLASSIFICATION.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_classifications(profile_id, [
                {"folder_path": "/reasoned", "classification": "stable", "recommended_action": "no_action",
                 "reason": "Contains production data"},
            ])
            result = store.get_classifications(profile_id)[0]
            self.assertEqual(result.reason, "Contains production data")
            store.close()


# STAGE 2: ORGANIZATION RULE TESTS.


class AuditStoreRuleTests(unittest.TestCase):
    def _create_profile_with_store(self, store: AuditStore) -> int:
        # HELPER TO CREATE A PROFILE AND RETURN ITS ID.
        profile = store.create_profile("Rule Test")
        return profile.id

    def test_create_rule_returns_rule_with_id(self):
        # VERIFIES THAT A NEW RULE IS CREATED AND HAS AN INTEGER ID ASSIGNED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            rule = store.create_rule(profile_id, "By Extension", "extension", {"extensions": [".pdf"]}, "/docs/{filename}")
            self.assertIsNotNone(rule.id)
            self.assertEqual(rule.name, "By Extension")
            self.assertEqual(rule.rule_type, "extension")
            store.close()

    def test_get_rules_returns_all_ordered_by_priority(self):
        # VERIFIES THAT RULES ARE RETURNED IN PRIORITY ORDER (LOWEST FIRST).
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.create_rule(profile_id, "Low Priority", "extension", {}, "/a", priority=10)
            store.create_rule(profile_id, "High Priority", "extension", {}, "/b", priority=1)
            store.create_rule(profile_id, "Mid Priority", "extension", {}, "/c", priority=5)
            rules = store.get_rules(profile_id)
            names = [r.name for r in rules]
            self.assertEqual(names, ["High Priority", "Mid Priority", "Low Priority"])
            store.close()

    def test_get_enabled_rules_excludes_disabled(self):
        # VERIFIES THAT ONLY ENABLED RULES ARE RETURNED BY get_enabled_rules.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.create_rule(profile_id, "Enabled", "extension", {}, "/a", enabled=True)
            store.create_rule(profile_id, "Disabled", "extension", {}, "/b", enabled=False)
            enabled = store.get_enabled_rules(profile_id)
            names = [r.name for r in enabled]
            self.assertEqual(names, ["Enabled"])
            store.close()

    def test_update_rule_modifies_fields(self):
        # VERIFIES THAT UPDATE CHANGES SPECIFIED FIELDS ON A RULE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            rule = store.create_rule(profile_id, "Original", "extension", {}, "/old")
            store.update_rule(rule.id, name="Renamed", enabled=False)
            updated = store.get_rules(profile_id)[0]
            self.assertEqual(updated.name, "Renamed")
            self.assertFalse(updated.enabled)
            store.close()

    def test_update_rule_serializes_rule_config(self):
        # VERIFIES THAT A DICT RULE_CONFIG IS AUTOMATICALLY SERIALIZED TO JSON.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            rule = store.create_rule(profile_id, "Config", "extension", {}, "/dest")
            store.update_rule(rule.id, rule_config={"key": "value", "number": 42})
            updated = store.get_rules(profile_id)[0]
            self.assertEqual(updated.rule_config, '{"key": "value", "number": 42}')
            store.close()

    def test_update_rule_returns_none_for_missing(self):
        # VERIFIES THAT UPDATING A NONEXISTENT RULE RETURNS NONE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.update_rule(9999, name="Nope")
            self.assertIsNone(result)
            store.close()

    def test_delete_rule_returns_true(self):
        # VERIFIES THAT DELETING AN EXISTING RULE RETURNS TRUE AND REMOVES IT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            rule = store.create_rule(profile_id, "Delete Me", "extension", {}, "/dest")
            result = store.delete_rule(rule.id)
            self.assertTrue(result)
            self.assertEqual(len(store.get_rules(profile_id)), 0)
            store.close()

    def test_delete_rule_returns_false_for_missing(self):
        # VERIFIES THAT DELETING A NONEXISTENT RULE RETURNS FALSE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.delete_rule(9999)
            self.assertFalse(result)
            store.close()


# STAGE 2: PROPOSED ACTION TESTS.


class AuditStoreProposedActionTests(unittest.TestCase):
    def _create_profile_with_store(self, store: AuditStore) -> int:
        # HELPER TO CREATE A PROFILE AND RETURN ITS ID.
        profile = store.create_profile("Action Test")
        return profile.id

    def test_save_proposed_actions_stores_records(self):
        # VERIFIES THAT SAVING PROPOSED ACTIONS PERSISTS THEM IN THE DATABASE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_proposed_actions(profile_id, [
                {"original_path": "/old/file_a.txt", "proposed_path": "/new/file_a.txt", "action_type": "move"},
                {"original_path": "/old/file_b.txt", "proposed_path": "/new/file_b.txt", "action_type": "move"},
            ])
            results = store.get_proposed_actions(profile_id)
            self.assertEqual(len(results), 2)
            store.close()

    def test_save_proposed_actions_replaces_existing(self):
        # VERIFIES THAT SAVING NEW ACTIONS REPLACES PREVIOUS ONES FOR A PROFILE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_proposed_actions(profile_id, [
                {"original_path": "/old/a", "proposed_path": "/new/a", "action_type": "move"},
            ])
            store.save_proposed_actions(profile_id, [
                {"original_path": "/new/b", "proposed_path": "/dest/b", "action_type": "rename"},
                {"original_path": "/new/c", "proposed_path": "/dest/c", "action_type": "rename"},
                {"original_path": "/new/d", "proposed_path": "/dest/d", "action_type": "rename"},
            ])
            results = store.get_proposed_actions(profile_id)
            self.assertEqual(len(results), 3)
            store.close()

    def test_approve_action_sets_approved_true(self):
        # VERIFIES THAT APPROVING AN ACTION MARKS IT AS APPROVED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_proposed_actions(profile_id, [
                {"original_path": "/file.txt", "proposed_path": "/new.txt", "action_type": "move"},
            ])
            action = store.get_proposed_actions(profile_id)[0]
            self.assertFalse(action.approved)
            result = store.approve_action(action.id)
            self.assertTrue(result)
            updated = store.get_proposed_actions(profile_id)[0]
            self.assertTrue(updated.approved)
            store.close()

    def test_approve_action_returns_false_for_missing(self):
        # VERIFIES THAT APPROVING A NONEXISTENT ACTION RETURNS FALSE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.approve_action(9999)
            self.assertFalse(result)
            store.close()

    def test_approve_all_actions_marks_all_as_approved(self):
        # VERIFIES THAT approve_all_actions MARKS EVERY ACTION AS APPROVED AND RETURNS COUNT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            store.save_proposed_actions(profile_id, [
                {"original_path": "/a.txt", "proposed_path": "/new_a.txt", "action_type": "move"},
                {"original_path": "/b.txt", "proposed_path": "/new_b.txt", "action_type": "move"},
                {"original_path": "/c.txt", "proposed_path": "/new_c.txt", "action_type": "delete"},
            ])
            count = store.approve_all_actions(profile_id)
            self.assertEqual(count, 3)
            actions = store.get_proposed_actions(profile_id)
            self.assertTrue(all(a.approved for a in actions))
            store.close()

    def test_approve_all_actions_returns_zero_for_empty(self):
        # VERIFIES THAT approve_all_actions RETURNS ZERO WHEN NO ACTIONS EXIST.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            count = store.approve_all_actions(profile_id)
            self.assertEqual(count, 0)
            store.close()

    def test_proposed_actions_store_rule_id(self):
        # VERIFIES THAT THE OPTIONAL RULE_ID FIELD IS PERSISTED ON A PROPOSED ACTION.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile_id = self._create_profile_with_store(store)
            rule = store.create_rule(profile_id, "Test Rule", "extension", {}, "/dest")
            store.save_proposed_actions(profile_id, [
                {"original_path": "/file.txt", "proposed_path": "/new.txt", "action_type": "move",
                 "rule_id": rule.id},
            ])
            action = store.get_proposed_actions(profile_id)[0]
            self.assertEqual(action.rule_id, rule.id)
            store.close()


# STAGE 2: EXTENDED FILE AUDIT COLUMNS TESTS.


class AuditStoreExtendedColumnsTests(unittest.TestCase):
    def test_extended_file_audit_columns_exist_in_schema(self):
        # VERIFIES THAT THE NEW STAGE 2 COLUMNS ON FILE_AUDITS ARE PRESENT IN THE DATABASE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            store.record_file("/test/doc.pdf", 2048, "abc123", "unique")
            # EXTENDED COLUMNS SHOULD EXIST AND DEFAULT TO EMPTY STRINGS WHEN NOT PROVIDED.
            with store.session_factory() as session:
                from sqlalchemy import text
                result = session.execute(
                    text("SELECT relative_path, extension, modified_at, folder_path FROM file_audits LIMIT 1")
                ).fetchone()
                self.assertIsNotNone(result)
                self.assertEqual(result[0], "")
                self.assertEqual(result[1], "")
                self.assertIsNone(result[2])
                self.assertEqual(result[3], "")
            # EXTENDED COLUMNS SHOULD PERSIST WHEN PROVIDED.
            store.record_file(
                "/test/doc2.pdf", 4096, "def456", "unique",
                relative_path="doc2.pdf", extension=".pdf",
                modified_at=None, folder_path="/test",
            )
            with store.session_factory() as session:
                result2 = session.execute(
                    text("SELECT relative_path, extension, folder_path FROM file_audits WHERE path = '/test/doc2.pdf'")
                ).fetchone()
                self.assertEqual(result2[0], "doc2.pdf")
                self.assertEqual(result2[1], ".pdf")
                self.assertEqual(result2[2], "/test")
            store.close()


# STAGE 2: PROPOSED ACTION REASON TESTS.


class AuditStoreProposedActionReasonTests(unittest.TestCase):
    def test_proposed_actions_store_reason(self):
        # VERIFIES THAT THE REASON FIELD IS PERSISTED ON A PROPOSED ACTION.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Reason Test")
            store.save_proposed_actions(profile.id, [
                {"original_path": "/file.txt", "proposed_path": "/new.txt", "action_type": "move",
                 "reason": "Matched rule 'Documents' (extension)"},
            ])
            action = store.get_proposed_actions(profile.id)[0]
            self.assertEqual(action.reason, "Matched rule 'Documents' (extension)")
            store.close()

    def test_proposed_actions_reason_defaults_to_empty(self):
        # VERIFIES THAT REASON DEFAULTS TO EMPTY STRING WHEN NOT PROVIDED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Reason Default")
            store.save_proposed_actions(profile.id, [
                {"original_path": "/file.txt", "proposed_path": "/new.txt", "action_type": "move"},
            ])
            action = store.get_proposed_actions(profile.id)[0]
            self.assertEqual(action.reason, "")
            store.close()


# STAGE 2: PROPOSED ACTION REJECTION TESTS.


class AuditStoreRejectActionTests(unittest.TestCase):
    def test_reject_action_removes_action(self):
        # VERIFIES THAT REJECTING AN ACTION DELETES IT FROM THE DATABASE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Reject Test")
            store.save_proposed_actions(profile.id, [
                {"original_path": "/file.txt", "proposed_path": "/new.txt", "action_type": "move"},
            ])
            action = store.get_proposed_actions(profile.id)[0]
            result = store.reject_action(action.id)
            self.assertTrue(result)
            self.assertEqual(len(store.get_proposed_actions(profile.id)), 0)
            store.close()

    def test_reject_action_returns_false_for_missing(self):
        # VERIFIES THAT REJECTING A NONEXISTENT ACTION RETURNS FALSE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.reject_action(9999)
            self.assertFalse(result)
            store.close()

    def test_delete_proposed_actions_by_ids_removes_multiple(self):
        # VERIFIES THAT MULTIPLE ACTIONS CAN BE DELETED BY THEIR IDS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Batch Reject")
            store.save_proposed_actions(profile.id, [
                {"original_path": "/a.txt", "proposed_path": "/new_a.txt", "action_type": "move"},
                {"original_path": "/b.txt", "proposed_path": "/new_b.txt", "action_type": "move"},
                {"original_path": "/c.txt", "proposed_path": "/new_c.txt", "action_type": "move"},
            ])
            actions = store.get_proposed_actions(profile.id)
            deleted = store.delete_proposed_actions_by_ids([actions[0].id, actions[2].id])
            self.assertEqual(deleted, 2)
            remaining = store.get_proposed_actions(profile.id)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].original_path, "/b.txt")
            store.close()

    def test_delete_proposed_actions_by_ids_returns_zero_for_empty(self):
        # VERIFIES THAT PASSING AN EMPTY LIST RETURNS ZERO DELETED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            count = store.delete_proposed_actions_by_ids([])
            self.assertEqual(count, 0)
            store.close()


# STAGE 3: TRANSACTION BATCH TESTS.


class AuditStoreTransactionBatchTests(unittest.TestCase):
    def test_create_batch_returns_batch_with_id(self):
        # VERIFIES THAT A NEW BATCH IS CREATED AND HAS AN INTEGER ID.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Batch Test")
            batch = store.create_batch(profile.id, "Move 5 files")
            self.assertIsNotNone(batch.id)
            self.assertIsInstance(batch.id, int)
            self.assertEqual(batch.scan_profile_id, profile.id)
            self.assertEqual(batch.description, "Move 5 files")
            self.assertEqual(batch.status, "pending")
            store.close()

    def test_create_batch_default_status(self):
        # VERIFIES THAT A NEW BATCH DEFAULTS TO PENDING STATUS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Default Status")
            batch = store.create_batch(profile.id)
            self.assertEqual(batch.status, "pending")
            self.assertIsNone(batch.completed_at)
            self.assertIsNone(batch.undone_at)
            store.close()

    def test_mark_batch_updates_status(self):
        # VERIFIES THAT mark_batch CHANGES THE STATUS FIELD.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Mark Batch")
            batch = store.create_batch(profile.id)
            result = store.mark_batch(batch.id, "completed")
            self.assertTrue(result)
            batches = store.get_undoable_batches(profile.id)
            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0].status, "completed")
            store.close()

    def test_mark_batch_sets_timestamps(self):
        # VERIFIES THAT mark_batch CAN SET COMPLETED_AT AND UNDONE_AT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            from datetime import datetime
            profile = store.create_profile("Timestamps")
            batch = store.create_batch(profile.id)
            now = datetime.now()
            store.mark_batch(batch.id, "completed", completed_at=now)
            batches = store.get_undoable_batches()
            self.assertEqual(len(batches), 1)
            self.assertIsNotNone(batches[0].completed_at)
            store.close()

    def test_mark_batch_returns_false_for_missing(self):
        # VERIFIES THAT mark_batch RETURNS FALSE FOR NONEXISTENT BATCH.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.mark_batch(9999, "completed")
            self.assertFalse(result)
            store.close()

    def test_get_undoable_batches_returns_completed(self):
        # VERIFIES THAT ONLY COMPLETED BATCHES ARE RETURNED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Undoable")
            b1 = store.create_batch(profile.id, "batch1")
            b2 = store.create_batch(profile.id, "batch2")
            store.mark_batch(b1.id, "completed")
            store.mark_batch(b2.id, "failed")
            undoable = store.get_undoable_batches(profile.id)
            self.assertEqual(len(undoable), 1)
            self.assertEqual(undoable[0].id, b1.id)
            store.close()

    def test_get_undoable_batches_reverse_order(self):
        # VERIFIES THAT BATCHES ARE RETURNED IN REVERSE ID ORDER (MOST RECENT FIRST).
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Order")
            b1 = store.create_batch(profile.id, "first")
            b2 = store.create_batch(profile.id, "second")
            b3 = store.create_batch(profile.id, "third")
            store.mark_batch(b1.id, "completed")
            store.mark_batch(b2.id, "completed")
            store.mark_batch(b3.id, "completed")
            undoable = store.get_undoable_batches(profile.id)
            ids = [b.id for b in undoable]
            self.assertEqual(ids, [b3.id, b2.id, b1.id])
            store.close()

    def test_get_undoable_batches_filters_by_profile(self):
        # VERIFIES THAT PROFILE FILTERING WORKS FOR UNDOABLE BATCHES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            p1 = store.create_profile("Profile 1")
            p2 = store.create_profile("Profile 2")
            b1 = store.create_batch(p1.id)
            b2 = store.create_batch(p2.id)
            store.mark_batch(b1.id, "completed")
            store.mark_batch(b2.id, "completed")
            undoable = store.get_undoable_batches(p1.id)
            self.assertEqual(len(undoable), 1)
            self.assertEqual(undoable[0].scan_profile_id, p1.id)
            store.close()

    def test_get_latest_completed_batch(self):
        # VERIFIES THAT THE MOST RECENT COMPLETED BATCH IS RETURNED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Latest")
            b1 = store.create_batch(profile.id, "older")
            b2 = store.create_batch(profile.id, "newer")
            store.mark_batch(b1.id, "completed")
            store.mark_batch(b2.id, "completed")
            latest = store.get_latest_completed_batch(profile.id)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.id, b2.id)
            store.close()

    def test_get_latest_completed_batch_returns_none_for_missing(self):
        # VERIFIES THAT NONE IS RETURNED WHEN NO COMPLETED BATCH EXISTS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("No Batch")
            result = store.get_latest_completed_batch(profile.id)
            self.assertIsNone(result)
            store.close()


# STAGE 3: TRANSACTION ENTRY TESTS.


class AuditStoreTransactionEntryTests(unittest.TestCase):
    def test_add_entry_returns_entry_with_id(self):
        # VERIFIES THAT A NEW ENTRY IS CREATED AND HAS AN INTEGER ID.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Entry Test")
            batch = store.create_batch(profile.id)
            entry = store.add_entry(
                batch.id, None, "move",
                "/source/file.txt", "/dest/file.txt",
                source_hash="abc123", source_size=1024,
            )
            self.assertIsNotNone(entry.id)
            self.assertEqual(entry.batch_id, batch.id)
            self.assertEqual(entry.source_path, "/source/file.txt")
            self.assertEqual(entry.destination_path, "/dest/file.txt")
            self.assertEqual(entry.source_hash, "abc123")
            self.assertEqual(entry.source_size, 1024)
            self.assertEqual(entry.status, "pending")
            store.close()

    def test_get_entries_by_batch_returns_all(self):
        # VERIFIES THAT ALL ENTRIES FOR A BATCH ARE RETURNED.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Entries All")
            batch = store.create_batch(profile.id)
            store.add_entry(batch.id, None, "move", "/a.txt", "/new_a.txt")
            store.add_entry(batch.id, None, "move", "/b.txt", "/new_b.txt")
            store.add_entry(batch.id, None, "rename", "/c.txt", "/c_new.txt")
            entries = store.get_entries_by_batch(batch.id)
            self.assertEqual(len(entries), 3)
            store.close()

    def test_get_entries_by_batch_filters_status(self):
        # VERIFIES THAT STATUS FILTERING WORKS FOR ENTRIES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Entries Filter")
            batch = store.create_batch(profile.id)
            e1 = store.add_entry(batch.id, None, "move", "/a.txt", "/new_a.txt")
            e2 = store.add_entry(batch.id, None, "move", "/b.txt", "/new_b.txt")
            e3 = store.add_entry(batch.id, None, "move", "/c.txt", "/new_c.txt")
            store.update_entry(e1.id, status="completed")
            store.update_entry(e2.id, status="completed")
            pending = store.get_entries_by_batch(batch.id, status="pending")
            completed = store.get_entries_by_batch(batch.id, status="completed")
            self.assertEqual(len(pending), 1)
            self.assertEqual(len(completed), 2)
            store.close()

    def test_update_entry_modifies_fields(self):
        # VERIFIES THAT update_entry CHANGES SPECIFIED FIELDS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Update Entry")
            batch = store.create_batch(profile.id)
            entry = store.add_entry(batch.id, None, "move", "/a.txt", "/new_a.txt")
            from datetime import datetime
            store.update_entry(
                entry.id,
                status="completed",
                holding_path="/holding/a.txt",
                destination_hash="def456",
                executed_at=datetime(2026, 1, 1),
            )
            updated = store.get_entries_by_batch(batch.id)[0]
            self.assertEqual(updated.status, "completed")
            self.assertEqual(updated.holding_path, "/holding/a.txt")
            self.assertEqual(updated.destination_hash, "def456")
            self.assertIsNotNone(updated.executed_at)
            store.close()

    def test_update_entry_returns_false_for_missing(self):
        # VERIFIES THAT update_entry RETURNS FALSE FOR NONEXISTENT ENTRY.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            result = store.update_entry(9999, status="completed")
            self.assertFalse(result)
            store.close()

    def test_add_entry_with_action_id(self):
        # VERIFIES THAT AN ENTRY CAN LINK TO A PROPOSED ACTION.
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.sqlite3"
            store = AuditStore(f"sqlite:///{database_path.as_posix()}")
            profile = store.create_profile("Link Entry")
            store.save_proposed_actions(profile.id, [
                {"original_path": "/file.txt", "proposed_path": "/new.txt", "action_type": "move"},
            ])
            action = store.get_proposed_actions(profile.id)[0]
            batch = store.create_batch(profile.id)
            entry = store.add_entry(batch.id, action.id, "move", "/file.txt", "/new.txt")
            self.assertEqual(entry.action_id, action.id)
            store.close()


if __name__ == "__main__":
    unittest.main()
