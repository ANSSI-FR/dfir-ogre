import os
import shutil
from unittest import TestCase

from ogre.configuration import Mapping
from ogre.dfir_orc_unpack import load_archive_metadata, unpack_dfir_orc

from . import PLUGIN_FOLDER, TEMP_FOLDER


class TestDfirUnpack(TestCase):
    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_original_file -v
    def test_original_file(self):
        temp_folder = os.path.join(TEMP_FOLDER, "TestDfirUnpackOrignal")
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")
        mapping: list[Mapping] = [
            Mapping(
                None,
                ".*Windows\\\\System32\\\\winevt\\\\Logs\\\\Microsoft-Windows-Kernel-Event.*",
                plugin_file,
                "nothing",
                True,
                True,
                10,
                {},
                [],
            ),
            Mapping(
                None,
                ".*CLR_v4.0_32\\\\ngen.log$",
                plugin_file,
                "nothing",
                True,
                True,
                10,
                {},
                [],
            ),
        ]

        mappings = unpack_dfir_orc(
            "test/data/archive/SampleOrc.7z", "password", None, mapping, temp_folder
        )

        if mappings.errors:
            print(mappings.errors)
            self.fail("should not produce error")

        self.assertEqual(2, len(mappings.valid_mapping))

        for valid in mappings.valid_mapping:
            self.assertTrue(os.path.isfile(valid.file))
            self.assertTrue(valid.original_file)

        first_mapping = mappings.valid_mapping[0]
        self.assertEqual(
            first_mapping.original_file,
            "\\Windows\\System32\\winevt\\Logs\\Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
        )
        self.assertEqual(first_mapping.original_creation_date, "2021-11-30 12:36:15.818")
        self.assertEqual(first_mapping.original_modification_date, "2021-11-30 12:36:20.364")
        shutil.rmtree(temp_folder)

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_original_file_skip_short_name
    def test_original_file_skip_short_name(self):
        temp_folder = os.path.join(TEMP_FOLDER, "TestDfirUnpackSkipShort")
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")
        # skip windows short name
        mapping: list[Mapping] = [
            Mapping(
                None,
                ".*\\.evtx$",
                plugin_file,
                "nothing",
                True,
                True,
                10,
                {},
                [],
            ),
        ]

        mappings = unpack_dfir_orc(
            "test/data/archive/SampleOrc.7z", "password", None, mapping, temp_folder
        )

        self.assertEqual(3, len(mappings.valid_mapping))
        for valid in mappings.valid_mapping:
            self.assertTrue(os.path.isfile(valid.file))
            self.assertTrue(valid.original_file)

        # do not skip windows short name
        mapping = [
            Mapping(
                None,
                ".*\\.evtx$",
                plugin_file,
                "nothing",
                False,
                True,
                10,
                {},
                [],
            ),
        ]

        mappings = unpack_dfir_orc(
            "test/data/archive/SampleOrc.7z", "password", None, mapping, temp_folder
        )

        self.assertEqual(5, len(mappings.valid_mapping))
        shutil.rmtree(temp_folder)

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_archive_file_filter
    def test_archive_file_filter_short_name(self):
        temp_folder = os.path.join(TEMP_FOLDER, "TestDfirUnpackSkipShort")
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")
        # skip windows short name
        mapping: list[Mapping] = [
            Mapping(
                ".*EventTracing\\.evtx_.*",
                None,
                plugin_file,
                "nothing",
                True,
                True,
                10,
                {},
                [],
            ),
        ]

        mappings = unpack_dfir_orc(
            "test/data/archive/SampleOrc.7z", "password", None, mapping, temp_folder
        )

        self.assertEqual(1, len(mappings.valid_mapping))
        valid = mappings.valid_mapping[0]
        self.assertTrue(os.path.isfile(valid.file))

        self.assertEqual(valid.original_file, "\\Windows\\Prefetch\\prefetch_sample.evtx")

        shutil.rmtree(temp_folder)

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_archive_file -v
    def test_archive_file(self):
        temp_folder = os.path.join(TEMP_FOLDER, "TestArchiveFile")
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")
        mapping: list[Mapping] = [
            Mapping(
                "evtx/.*Microsoft-Windows-Kernel-Event.*",
                None,
                plugin_file,
                "nothing",
                True,
                True,
                10,
                {},
                [],
            ),
            Mapping(
                "arp_.*\\.txt",
                None,
                plugin_file,
                "nothing",
                True,
                True,
                10,
                {},
                [],
            ),
        ]

        mappings = unpack_dfir_orc(
            "test/data/archive/SampleOrc.7z",
            "password",
            "password",
            mapping,
            temp_folder,
        )

        self.assertEqual(2, len(mappings.valid_mapping))
        for valid in mappings.valid_mapping:
            self.assertTrue(os.path.isfile(valid.file))
        shutil.rmtree(temp_folder)

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_outcome_from_json -v
    def test_outcome_from_json(self):
        outcome = """{
    "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
    "hostname": "APPS2008R2-DC",
    "timestamp": "20250904_221144",
    "dir_tree": "results/APPS2008R2-DC",
    "nb_errors": 0,
    "encrypted_data_files": [],
    "unencrypted_data_files": [
        "/data/operationnel/traitements/test/data/machines/orc_windows/results/APPS2008R2-DC/ORC_DomainController_APPS2008R2-DC.apps2008r2.lab_Little.7z",
        "/data/operationnel/traitements/test/data/machines/orc_windows/results/APPS2008R2-DC/ORC_DomainController_APPS2008R2-DC.apps2008r2.lab_General.7z"
    ]
}"""
        orc_outcome = load_archive_metadata(outcome)

        self.assertEqual(orc_outcome.id, "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}")
        self.assertEqual(orc_outcome.computer_name, "APPS2008R2-DC")
        self.assertEqual(orc_outcome.date.isoformat(), "2025-09-04T22:11:44+00:00")

        self.assertListEqual(
            orc_outcome.archives,
            [
                "/data/operationnel/traitements/test/data/machines/orc_windows/results/APPS2008R2-DC/ORC_DomainController_APPS2008R2-DC.apps2008r2.lab_Little.7z",
                "/data/operationnel/traitements/test/data/machines/orc_windows/results/APPS2008R2-DC/ORC_DomainController_APPS2008R2-DC.apps2008r2.lab_General.7z",
            ],
        )

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_outcome_from_json_file -v
    def test_outcome_from_json_file(self):
        outcome = "test/data/archive/ORC_WorkStation_SampleOrc_162358_Outcome.json"
        orc_outcome = load_archive_metadata(outcome)

        self.assertEqual(orc_outcome.id, "072AE647-1CBD-44EA-82AC-D2532B0F499A")
        self.assertEqual(orc_outcome.computer_name, "W11-22H2U")
        self.assertEqual(orc_outcome.date.isoformat(), "2023-05-31T16:23:58+00:00")

        self.assertListEqual(
            orc_outcome.archives,
            ["test/data/archive/SampleOrc.7z", "test/data/archive/SampleOrc2.7z"],
        )

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_outcome_default -v
    def test_outcome_default(self):
        archive = "test/data/archive/ORC_server_bad_naming_scheme.7z"
        orc_outcome = load_archive_metadata(archive)
        self.assertEqual(orc_outcome.computer_name, "ORC_server_bad_naming_scheme")

        machine_name = "W11-22H2U"
        archive = f"test/data/archive/ORC_WorkStation_{machine_name}_General.7z"
        orc_outcome = load_archive_metadata(archive)
        self.assertEqual(orc_outcome.computer_name, machine_name)

        archive = f"test/data/archive/ORC_Server_{machine_name}_General.7z"
        orc_outcome = load_archive_metadata(archive)
        self.assertEqual(orc_outcome.computer_name, machine_name)

        archive = f"test/data/archive/ORC_DomainController_{machine_name}_General.7z"
        orc_outcome = load_archive_metadata(archive)
        self.assertEqual(orc_outcome.computer_name, machine_name)

    # python -m unittest test.test_dfir_orc_unpack.TestDfirUnpack.test_outcome_mutiple -v
    def test_outcome_mutiple(self):
        archive = "test/data/archive/ORC_1.7z , test/data/archive/ORC_2.7z , "
        orc_outcome = load_archive_metadata(archive)
        self.assertListEqual(
            orc_outcome.archives,
            ["test/data/archive/ORC_1.7z", "test/data/archive/ORC_2.7z"],
        )
