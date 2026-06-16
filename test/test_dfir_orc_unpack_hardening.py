import os

from ogre.dfir_orc_unpack import load_archive_metadata, unpack_dfir_orc

from .hardening_helpers import TempFolderTestCase


class TestDfirOrcUnpackHardening(TempFolderTestCase):
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
