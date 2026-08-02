import tempfile
import unittest
from pathlib import Path

from opencoeus.core.hashing import sha256_file


class HashingTests(unittest.TestCase):
    def test_identical_files_produce_same_hash(self):
        # VERIFIES THAT TWO FILES WITH THE SAME CONTENT HAVE IDENTICAL SHA-256 HASHES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            first_file = test_root / "copy_a.bin"
            second_file = test_root / "copy_b.bin"
            shared_content = b"shared content for hashing test"
            first_file.write_bytes(shared_content)
            second_file.write_bytes(shared_content)
            hash_of_first = sha256_file(first_file)
            hash_of_second = sha256_file(second_file)
            self.assertEqual(hash_of_first, hash_of_second)

    def test_different_files_produce_different_hashes(self):
        # VERIFIES THAT TWO FILES WITH DIFFERENT CONTENT HAVE DIFFERENT SHA-256 HASHES.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            first_file = test_root / "unique_a.bin"
            second_file = test_root / "unique_b.bin"
            first_file.write_bytes(b"content version one")
            second_file.write_bytes(b"content version two")
            hash_of_first = sha256_file(first_file)
            hash_of_second = sha256_file(second_file)
            self.assertNotEqual(hash_of_first, hash_of_second)

    def test_hash_is_hex_string_of_expected_length(self):
        # VERIFIES THAT THE HASH IS A 64 CHARACTER HEXADECIMAL STRING.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            test_file = test_root / "hash_check.bin"
            test_file.write_bytes(b"test data")
            computed_hash = sha256_file(test_file)
            self.assertEqual(len(computed_hash), 64)
            self.assertTrue(all(character in "0123456789abcdef" for character in computed_hash))

    def test_empty_file_produces_valid_hash(self):
        # VERIFIES THAT AN EMPTY FILE CAN BE HASHED WITHOUT ERRORS.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            empty_file = test_root / "empty.bin"
            empty_file.write_bytes(b"")
            computed_hash = sha256_file(empty_file)
            self.assertEqual(len(computed_hash), 64)

    def test_large_file_hashes_correctly_with_small_chunks(self):
        # VERIFIES THAT A LARGE FILE CAN BE HASHED USING A SMALL CHUNK SIZE.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            large_file = test_root / "large.bin"
            large_content = b"\xaa" * (1024 * 100)
            large_file.write_bytes(large_content)
            hash_with_small_chunks = sha256_file(large_file, read_chunk_size=1024)
            hash_with_large_chunks = sha256_file(large_file, read_chunk_size=1024 * 1024)
            # CHUNK SIZE SHOULD NOT AFFECT THE RESULT.
            self.assertEqual(hash_with_small_chunks, hash_with_large_chunks)

    def test_hashing_nonexistent_file_raises_os_error(self):
        # VERIFIES THAT HASHING A NONEXISTENT FILE RAISES AN OS ERROR.
        non_existent_file = Path("C:\\nonexistent_file_12345.bin")
        with self.assertRaises(OSError):
            sha256_file(non_existent_file)

    def test_known_sha256_value_matches(self):
        # VERIFIES THAT THE HASH MATCHES A KNOWN SHA-256 VALUE FOR A SPECIFIC INPUT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            test_file = test_root / "known.bin"
            test_file.write_bytes(b"hello")
            computed_hash = sha256_file(test_file)
            # SHA-256 OF "hello" IS A WELL KNOWN VALUE.
            expected_hash = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
            self.assertEqual(computed_hash, expected_hash)

    def test_hash_is_deterministic_across_multiple_calls(self):
        # VERIFIES THAT HASHING THE SAME FILE MULTIPLE TIMES PRODUCES THE SAME RESULT.
        with tempfile.TemporaryDirectory() as temporary_directory:
            test_root = Path(temporary_directory)
            test_file = test_root / "deterministic.bin"
            test_file.write_bytes(b"repeatable content")
            first_hash = sha256_file(test_file)
            second_hash = sha256_file(test_file)
            third_hash = sha256_file(test_file)
            self.assertEqual(first_hash, second_hash)
            self.assertEqual(second_hash, third_hash)


if __name__ == "__main__":
    unittest.main()
