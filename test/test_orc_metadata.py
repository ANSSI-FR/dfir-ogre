import json
import os

from ogre.orc_metadata import load_archive_metadata

from .hardening_helpers import TempFolderTestCase


class TestOrcMetadata(TempFolderTestCase):
    def test_empty_archive_metadata_input_raises_clear_error(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata("   ")

        self.assertIn("No archive path provided", str(context.exception))

    def test_json_archive_definition_must_be_object(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata('["test/data/archive/SampleOrc.7z"]')

        self.assertIn("Invalid json archive definition", str(context.exception))

    def test_json_archive_definition_requires_archive_list(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "HOST",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": "abc"
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "No unencrypted archives defined in the json archive definition",
            str(context.exception),
        )

    def test_json_archive_definition_rejects_empty_archive_entries(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "HOST",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": [""]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "No unencrypted archives defined in the json archive definition",
            str(context.exception),
        )

    def test_comma_separated_archives_rejects_empty_values(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata(" , ")

        self.assertIn("No archive path provided", str(context.exception))

    def test_comma_separated_archives_rejects_embedded_empty_values(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata("a.7z,,b.7z")

        self.assertIn("Empty archive path in archive list", str(context.exception))

    def test_json_archive_definition_requires_hostname_without_stringifying_none(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": ["test/data/archive/SampleOrc.7z"]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "The hostname is not defined in the json archive definition",
            str(context.exception),
        )

    def test_json_archive_definition_requires_id_without_stringifying_none(self):
        archive_definition = """{
            "id": null,
            "hostname": "HOST",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": ["test/data/archive/SampleOrc.7z"]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "The orc id is not defined in the json archive definition",
            str(context.exception),
        )

    def test_json_archive_definition_requires_timestamp(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "HOST",
            "unencrypted_data_files": ["test/data/archive/SampleOrc.7z"]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "No timestamp  defined in the json archive definition",
            str(context.exception),
        )

    def test_outcome_file_requires_command_set_list(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": {"archive": {"name": "SampleOrc.7z"}},
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'command_set' node must be a list", str(context.exception))

    def test_outcome_file_requires_command_entry_object(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": ["bad"],
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("command entry must be an object", str(context.exception))

    def test_outcome_file_requires_archive_object(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": [{"archive": "bad"}],
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn(
            "command does not contains the 'archive' parameter",
            str(context.exception),
        )

    def test_outcome_file_requires_object_root(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump([], file)

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("root node must be an object", str(context.exception))

    def test_outcome_file_requires_dfir_orc_object(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump({"dfir-orc": []}, file)

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'dfir-orc' node must be an object", str(context.exception))

    def test_outcome_file_requires_outcome_object(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump({"dfir-orc": {"outcome": []}}, file)

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'outcome' node must be an object", str(context.exception))

    def test_outcome_file_requires_command_set(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'command_set' node must be a list", str(context.exception))

    def test_outcome_file_requires_archive_name(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": [{"archive": {}}],
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("archive name is empty", str(context.exception))

    def test_outcome_file_requires_archive_name_string(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": [{"archive": {"name": []}}],
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("archive name is empty", str(context.exception))
