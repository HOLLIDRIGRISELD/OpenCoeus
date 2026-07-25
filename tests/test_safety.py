import unittest
from pathlib import Path

from opencoeus.safety import is_protected


class SafetyTests(unittest.TestCase):
    def test_opencoeus_folder_is_protected(self):
        # VERIFIES THAT .opencoeus IS RECOGNIZED AS A PROTECTED FOLDER.
        test_path = Path(".opencoeus") / "data.db"
        self.assertTrue(is_protected(test_path, [r"^\.opencoeus$"]))

    def test_regular_folder_is_not_protected(self):
        # VERIFIES THAT A REGULAR FOLDER NAME IS NOT FLAGGED AS PROTECTED.
        test_path = Path("Documents") / "report.pdf"
        self.assertFalse(is_protected(test_path, [r"^\.opencoeus$"]))

    def test_protected_detection_is_case_insensitive(self):
        # VERIFIES THAT PROTECTED FOLDER DETECTION WORKS REGARDLESS OF CASE.
        lower_path = Path(".opencoeus") / "file.txt"
        upper_path = Path(".OPENCOEUS") / "file.txt"
        mixed_path = Path(".OpEnCoEuS") / "file.txt"
        patterns = [r"^\.opencoeus$"]
        self.assertTrue(is_protected(lower_path, patterns))
        self.assertTrue(is_protected(upper_path, patterns))
        self.assertTrue(is_protected(mixed_path, patterns))

    def test_nested_protected_folder_is_detected(self):
        # VERIFIES THAT A PROTECTED FOLDER IS DETECTED EVEN WHEN NESTED DEEPLY.
        test_path = Path("projects") / "archive" / ".opencoeus" / "old_data.db"
        self.assertTrue(is_protected(test_path, [r"^\.opencoeus$"]))

    def test_multiple_patterns_are_checked(self):
        # VERIFIES THAT ANY MATCHING PATTERN IN THE LIST TRIGGERS PROTECTION.
        test_patterns = [r"^\.opencoeus$", r"^System Volume Information$", r"^\$RECYCLE\.BIN$"]
        opencoeus_path = Path(".opencoeus") / "file.txt"
        system_path = Path("System Volume Information") / "file.txt"
        recycle_path = Path("$RECYCLE.BIN") / "file.txt"
        self.assertTrue(is_protected(opencoeus_path, test_patterns))
        self.assertTrue(is_protected(system_path, test_patterns))
        self.assertTrue(is_protected(recycle_path, test_patterns))

    def test_empty_pattern_list_protects_nothing(self):
        # VERIFIES THAT AN EMPTY PATTERN LIST DOES NOT PROTECT ANY PATH.
        test_path = Path(".opencoeus") / "file.txt"
        self.assertFalse(is_protected(test_path, []))

    def test_windows_platform_patterns_work(self):
        # VERIFIES THAT WINDOWS SPECIFIC PROTECTED FOLDER PATTERNS ARE DETECTED.
        windows_patterns = [r"^\$RECYCLE\.BIN$", r"^System Volume Information$", r"^Windows$", r"^Program Files(?: \(x86\))?$"]
        recycle_path = Path("$RECYCLE.BIN") / "file.txt"
        system_path = Path("System Volume Information") / "catalog.xml"
        windows_path = Path("Windows") / "System32" / "file.dll"
        program_files_path = Path("Program Files") / "app" / "file.exe"
        program_files_x86_path = Path("Program Files (x86)") / "app" / "file.exe"
        self.assertTrue(is_protected(recycle_path, windows_patterns))
        self.assertTrue(is_protected(system_path, windows_patterns))
        self.assertTrue(is_protected(windows_path, windows_patterns))
        self.assertTrue(is_protected(program_files_path, windows_patterns))
        self.assertTrue(is_protected(program_files_x86_path, windows_patterns))

    def test_macos_platform_patterns_work(self):
        # VERIFIES THAT MACOS SPECIFIC PROTECTED FOLDER PATTERNS ARE DETECTED.
        macos_patterns = [r"^\.Trashes$", r"^\.Spotlight-V100$", r"^\.fseventsd$", r"^System$"]
        trash_path = Path(".Trashes") / "501" / "file.txt"
        spotlight_path = Path(".Spotlight-V100") / "store.db"
        fseventsd_path = Path(".fseventsd") / "log"
        system_path = Path("System") / "Library" / "file"
        self.assertTrue(is_protected(trash_path, macos_patterns))
        self.assertTrue(is_protected(spotlight_path, macos_patterns))
        self.assertTrue(is_protected(fseventsd_path, macos_patterns))
        self.assertTrue(is_protected(system_path, macos_patterns))

    def test_linux_platform_patterns_work(self):
        # VERIFIES THAT LINUX SPECIFIC PROTECTED FOLDER PATTERNS ARE DETECTED.
        linux_patterns = [r"^proc$", r"^sys$", r"^dev$", r"^run$", r"^lost\+found$"]
        proc_path = Path("proc") / "cpuinfo"
        sys_path = Path("sys") / "kernel" / "file"
        dev_path = Path("dev") / "sda1"
        run_path = Path("run") / "lock" / "file"
        lost_path = Path("lost+found") / "file"
        self.assertTrue(is_protected(proc_path, linux_patterns))
        self.assertTrue(is_protected(sys_path, linux_patterns))
        self.assertTrue(is_protected(dev_path, linux_patterns))
        self.assertTrue(is_protected(run_path, linux_patterns))
        self.assertTrue(is_protected(lost_path, linux_patterns))

    def test_single_part_path_is_checked(self):
        # VERIFIES THAT A SINGLE PART PATH (JUST A FOLDER NAME) IS CHECKED CORRECTLY.
        self.assertTrue(is_protected(Path(".opencoeus"), [r"^\.opencoeus$"]))
        self.assertFalse(is_protected(Path("Documents"), [r"^\.opencoeus$"]))

    def test_protected_pattern_uses_anchored_regex(self):
        # VERIFIES THAT ANCHORED REGEX PATTERNS DO NOT MATCH PARTIAL NAMES.
        # THE PATTERN ^\.opencoeus$ SHOULD NOT MATCH ".opencoeus_backup".
        test_path = Path(".opencoeus_backup") / "file.txt"
        self.assertFalse(is_protected(test_path, [r"^\.opencoeus$"]))


class CacheEvictionTests(unittest.TestCase):
    def test_cache_evicts_when_full(self):
        # VERIFIES THAT _COMPILED_CACHE CAPS AT MAX_CACHE_SIZE AND EVICTS OLDEST.
        from opencoeus.safety import _compiled_cache, MAX_CACHE_SIZE
        _compiled_cache.clear()
        # FILL THE CACHE TO THE LIMIT USING IS_PROTECTED.
        for i in range(MAX_CACHE_SIZE):
            is_protected(Path(f"test_{i}"), [f"^test_{i}$"])
        self.assertEqual(len(_compiled_cache), MAX_CACHE_SIZE)
        # ADDING ONE MORE SHOULD EVICT THE OLDEST.
        is_protected(Path(f"test_{MAX_CACHE_SIZE}"), [f"^test_{MAX_CACHE_SIZE}$"])
        self.assertEqual(len(_compiled_cache), MAX_CACHE_SIZE)
        _compiled_cache.clear()


if __name__ == "__main__":
    unittest.main()
