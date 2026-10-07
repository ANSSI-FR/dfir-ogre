import os
import csv
import io
from pathlib import Path

import py7zr

from ogre.configuration import Mapping
from ogre.dfir_orc_unpack import load_archive_metadata, unpack_dfir_orc

from .hardening_helpers import TempFolderTestCase


class TestDfirOrcUnpackHardening(TempFolderTestCase):
    def _escaped_path(self, filename):
        path = os.path.abspath(os.path.join(self.temp_folder, "..", filename))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def _write_archive_entry(self, archive, entry_name, data):
        with py7zr.SevenZipFile(archive, "w") as archive7z:
            archive7z._writestr(data, entry_name)

    def test_unpack_missing_archive_returns_error_list(self):
        result = unpack_dfir_orc(
            os.path.join(self.temp_folder, "missing.7z"),
            None,
            None,
            [],
            self.temp_folder,
        )

        self.assertEqual(result.valid_mapping, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("not found or is not a file", result.errors[0])

    def test_unpack_non_7z_archive_returns_error_list(self):
        result = unpack_dfir_orc("README.md", None, None, [], self.temp_folder)

        self.assertEqual(result.valid_mapping, [])
        self.assertEqual(result.errors, ["'README.md' is not a 7z file"])

    def test_unpack_rejects_traversal_nested_archive_entry(self):
        archive = os.path.join(self.temp_folder, "main.7z")
        escaped = self._escaped_path("escaped.7z")
        self._write_archive_entry(archive, "../../../escaped.7z", b"owned")

        result = unpack_dfir_orc(archive, None, None, [], self.temp_folder)

        self.assertFalse(os.path.exists(escaped))
        self.assertEqual(result.valid_mapping, [])
        self.assertTrue(
            any("Unsafe archive member path" in error for error in result.errors),
            result.errors,
        )

    def test_unpack_rejects_traversal_inner_archive_entry(self):
        inner_archive = os.path.join(self.temp_folder, "inner.7z")
        main_archive = os.path.join(self.temp_folder, "main.7z")
        escaped = self._escaped_path("inner-escaped.txt")
        self._write_archive_entry(
            inner_archive,
            "../../../inner-escaped.txt",
            b"inner-owned",
        )
        with py7zr.SevenZipFile(main_archive, "w") as archive7z:
            archive7z.write(inner_archive, "inner.7z")
        mapping = [
            Mapping(
                ".*\\.txt$",
                None,
                "unused.xml",
                "text",
                True,
                False,
                10,
                {},
                [],
            )
        ]

        result = unpack_dfir_orc(main_archive, None, None, mapping, self.temp_folder)

        self.assertFalse(os.path.exists(escaped))
        self.assertEqual(result.valid_mapping, [])
        self.assertTrue(
            any("Unsafe archive member path" in error for error in result.errors),
            result.errors,
        )

    def test_json_archive_definition_requires_unencrypted_archives(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "SampleOrc",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": []
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "No unencrypted archives defined in the json archive definition",
            str(context.exception),
        )

    def test_json_archive_definition_requires_id(self):
        archive_definition = """{
            "hostname": "SampleOrc",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": ["test/data/archive/SampleOrc.7z"]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "The orc id is not defined in the json archive definition",
            str(context.exception),
        )

    def test_outcome_file_requires_dfir_orc_root_node(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            file.write("{}")

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'dfir-orc' root node not found", str(context.exception))


class TestRelativePathProvenance(TempFolderTestCase):
    def test_logical_parent_uses_member_and_nested_archive_paths(self):
        from ogre.orc_mapping import source_relative_parent

        self.assertEqual(source_relative_parent("a.evtx"), "")
        self.assertEqual(source_relative_parent("logs/a.evtx"), "logs")
        self.assertEqual(
            source_relative_parent("logs/a.evtx", "collection/inner.7z"),
            "collection/inner/logs",
        )

    def test_nested_archive_and_original_mappings_retain_logical_parent_after_rename(self):
        inner_archive = os.path.join(self.temp_folder, "inner.7z")
        main_archive = os.path.join(self.temp_folder, "main.7z")
        long_name = "a" * 241 + ".evtx"
        member = f"logs/{long_name}"
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(
            ["SampleName", "FullName", "CreationDate", "LastModificationDate", "SnapshotID"]
        )
        writer.writerow([member, r"C:\Windows\test.evtx", "", "", ""])
        source_member = Path(self.temp_folder) / "sample.evtx"
        source_member.write_bytes(b"event")
        source_csv = Path(self.temp_folder) / "source_GetThis.csv"
        source_csv.write_text(csv_buffer.getvalue())
        with py7zr.SevenZipFile(inner_archive, "w") as archive7z:
            archive7z.write(source_member, member)
            archive7z.write(source_csv, "GetThis.csv")
        with py7zr.SevenZipFile(main_archive, "w") as archive7z:
            archive7z.write(inner_archive, "collection/inner.7z")

        mappings = [
            Mapping(r".*\.evtx$", None, "unused.xml", "archive", True, False, 10, {}, []),
            Mapping(None, r".*test\.evtx$", "unused.xml", "original", True, False, 10, {}, []),
        ]
        result = unpack_dfir_orc(main_archive, None, None, mappings, self.temp_folder)

        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.valid_mapping), 2)
        self.assertEqual(
            {mapping.relative_path for mapping in result.valid_mapping},
            {"collection/inner/logs"},
        )
        self.assertEqual(
            {mapping.mapping.mapping_label for mapping in result.valid_mapping},
            {"archive", "original"},
        )
        self.assertTrue(all(Path(mapping.file).name != long_name for mapping in result.valid_mapping))
