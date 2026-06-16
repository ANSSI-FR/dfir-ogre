import os
import xml.etree.ElementTree as ET
from unittest import mock

from ogre.commands import (
    clear_plugin_parser_cache,
    load_plugin_parser,
    prepare_runs,
)

from . import PLUGIN_FOLDER
from .hardening_helpers import TempFolderTestCase


class TestCommandsHardening(TempFolderTestCase):
    def setUp(self):
        super().setUp()
        clear_plugin_parser_cache()

    def tearDown(self):
        clear_plugin_parser_cache()
        super().tearDown()

    def test_load_plugin_parser_caches_xml_parse_result(self):
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")

        with mock.patch("ogre.commands.ET.parse", wraps=ET.parse) as parse:
            self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))
            self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))

        parse.assert_called_once_with(plugin_file)

    def test_load_plugin_parser_detects_batch_attribute(self):
        plugin_file = os.path.join(PLUGIN_FOLDER, "batched_void.xml")

        self.assertEqual(load_plugin_parser(plugin_file), ("Void", True))

    def test_prepare_runs_does_not_keep_mutable_default_global_vars(self):
        self.assertEqual(prepare_runs.__defaults__, (None,))

    def test_prepare_runs_raises_key_error_for_unknown_output_reference(self):
        with self.assertRaises(KeyError) as context:
            prepare_runs(
                os.path.join("test", "data", "test_commands_bad_output.yaml"),
                os.path.join("test", "data", "archive", "SampleOrc.7z"),
                None,
                {"temp_folder": self.temp_folder},
            )

        self.assertEqual(context.exception.args[0], "bad_output")

    def test_prepare_runs_preserves_grouping_and_metadata_contract(self):
        result = prepare_runs(
            os.path.join("test", "data", "test_commands_run.yaml"),
            os.path.join("test", "data", "archive", "SampleOrc.7z"),
            None,
            {"temp_folder": self.temp_folder},
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.computer, "SampleOrc")
        self.assertEqual(result.output_folder, ".tmp/output")
        self.assertEqual(result.report_folder, ".tmp/output")
        self.assertEqual(len(result.runs.map), 1)

        run = next(iter(result.runs.map.values()))
        self.assertEqual(run.mapping_label, "arp")
        self.assertEqual(run.parser, "Void")
        self.assertEqual(run.module, "ogre.void_parser")
        self.assertFalse(run.batch)
        self.assertEqual(len(run.batch_entries), 2)

        archive_entry = next(
            entry
            for entry in run.batch_entries
            if entry.metadata.archive_filename == "arp_cache.txt"
        )
        self.assertEqual(archive_entry.metadata.computer, "SampleOrc")
        self.assertEqual(archive_entry.metadata.archive, "SampleOrc.7z")
        self.assertIsNone(archive_entry.metadata.subarchive)
        self.assertIsNone(archive_entry.metadata.original_filename)
        self.assertEqual(archive_entry.run_config.output[0].output_folder, "event")
        self.assertEqual(archive_entry.run_config.output[0].base_file_name, "test")

        original_entry = next(
            entry for entry in run.batch_entries if entry.metadata.original_filename
        )
        self.assertEqual(original_entry.metadata.computer, "SampleOrc")
        self.assertEqual(original_entry.metadata.archive, "SampleOrc.7z")
        self.assertEqual(original_entry.metadata.subarchive, "Event.7z")
        self.assertIn(
            "Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
            original_entry.metadata.archive_filename,
        )
        self.assertEqual(
            original_entry.metadata.original_filename,
            "\\Windows\\System32\\winevt\\Logs\\Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
        )
        self.assertEqual(
            original_entry.metadata.creation_date.isoformat(),
            "2021-11-30T11:36:15.818000+00:00",
        )
        self.assertEqual(
            original_entry.metadata.modif_date.isoformat(),
            "2021-11-30T11:36:20.364000+00:00",
        )
        self.assertEqual(
            original_entry.metadata.vss,
            "{00000000-0000-0000-0000-000000000000}",
        )
