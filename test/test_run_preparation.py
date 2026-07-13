import os
from datetime import datetime, timezone
from typing import Any
from unittest import TestCase

from dfir_ogre_common import OutputConfiguration

from ogre.configuration import Configuration, Mapping
from ogre.dfir_orc_unpack import FileMapping, OrcOutcome, UnpackResult
from ogre.run_preparation import (
    ArchiveRunPlanner,
    BatchEntryBuilder,
    ParserSelection,
    PluginDefinition,
    RunConfigGrouper,
    RunPreparationContext,
    VariableResolver,
    clear_plugin_parser_cache,
    load_config,
    load_plugin_parser,
    load_plugins,
    prepare_runs,
)

from .hardening_helpers import TempFolderTestCase


def _mapping(**overrides):
    values = {
        "archive_file_pattern": ".*\\.txt$",
        "original_file_pattern": None,
        "plugin_file": "$plugin_folder/void.xml",
        "mapping_label": "text_output",
        "skip_short_name": True,
        "force_nake_case": True,
        "timeout": 3600,
        "params": {
            "folder": "$output_folder/$archive_name/$case",
            "constant": 7,
        },
        "output": ["rawjson"],
    }
    values.update(overrides)
    return Mapping(**values)


def _output(**overrides):
    values = {
        "base_file_name": "$parser_$file_name_$timestamp",
        "output_folder": "$output_folder/$archive_name/$mapping_label/$dir_tree",
        "output_type": "file",
        "format": "jsonl",
        "date_format": "iso",
        "with_timeline": False,
        "include_empty": False,
        "parameters": {},
    }
    values.update(overrides)
    return OutputConfiguration(
        base_file_name=values["base_file_name"],
        output_folder=values["output_folder"],
        output_type=values["output_type"],
        format=values["format"],
        date_format=values["date_format"],
        with_timeline=values["with_timeline"],
        include_empty=values["include_empty"],
        params=values["parameters"],
    )


def _configuration(**overrides: Any) -> Configuration:
    rawjson = _output()
    values: dict[str, Any] = {
        "plugin_prefixes": ["test"],
        "case": "test",
        "dir_tree": "",
        "temp_folder": ".tmp/extract/request",
        "output_folder": ".tmp/output",
        "plugin_folder": "test/plugin_config",
        "report_folder": "/data/$case/ogre/$dir_tree/ogre_report",
        "force_snake_case": True,
        "default_timeout": 3600,
        "inner_archive_password": None,
        "mapping": [_mapping()],
        "output": {"rawjson": rawjson},
    }
    values.update(overrides)
    return Configuration(**values)


def _outcome(**overrides):
    values = {
        "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
        "computer_name": "SampleOrc",
        "date": datetime(2025, 9, 4, 22, 11, 44, tzinfo=timezone.utc),
        "dir_tree": None,
        "archives": ["test/data/archive/SampleOrc.7z"],
    }
    values.update(overrides)
    return OrcOutcome(**values)


class TestVariableResolver(TestCase):
    def test_report_folder_uses_config_dir_tree_fallback_when_archive_has_none(self):
        resolver = VariableResolver(_configuration(), _outcome())

        self.assertEqual(
            resolver.resolve_report_folder(),
            "/data/test/ogre/ogre_report",
        )

    def test_report_folder_uses_archive_dir_tree_when_present(self):
        resolver = VariableResolver(
            _configuration(),
            _outcome(dir_tree="presta/SuperIR"),
        )

        self.assertEqual(
            resolver.resolve_report_folder(),
            "/data/test/ogre/presta/SuperIR/ogre_report",
        )

    def test_archive_output_resolution_preserves_existing_timestamp_behavior(self):
        config = _configuration()
        resolver = VariableResolver(config, _outcome(dir_tree="presta/SuperIR"))

        resolved = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )

        self.assertEqual(
            resolved.output_folder,
            ".tmp/output/SampleOrc/$mapping_label/presta/SuperIR",
        )
        self.assertEqual(
            resolved.base_file_name,
            "$parser_$file_name_20250904_221144",
        )

    def test_run_output_resolution_replaces_mapping_parser_file_and_computer(self):
        config = _configuration()
        resolver = VariableResolver(config, _outcome())
        archive_output = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )

        resolved = resolver.resolve_run_output(
            archive_output,
            mapping_label="text_output",
            parser="Void",
            file_path="/tmp/BITS_jobs.txt",
        )

        self.assertEqual(
            resolved.output_folder,
            ".tmp/output/SampleOrc/text_output",
        )
        self.assertEqual(
            resolved.base_file_name,
            "Void_BITS_jobs_20250904_221144",
        )

    def test_plugin_file_and_mapping_params_are_resolved_without_mutating_mapping(self):
        config = _configuration()
        mapping = config.mapping[0]
        resolver = VariableResolver(config, _outcome())

        plugin_file = resolver.resolve_plugin_file(
            mapping,
            "test/data/archive/SampleOrc.7z",
        )
        params = resolver.resolve_mapping_params(
            mapping,
            "test/data/archive/SampleOrc.7z",
        )

        self.assertEqual(plugin_file, "test/plugin_config/void.xml")
        self.assertEqual(params["folder"], ".tmp/output/SampleOrc/test")
        self.assertEqual(params["constant"], "7")
        self.assertEqual(mapping.plugin_file, "$plugin_folder/void.xml")


class TestBatchEntryBuilder(TempFolderTestCase):
    def test_build_entry_preserves_metadata_and_resolved_output_contract(self):
        config = _configuration()
        outcome = _outcome()
        resolver = VariableResolver(config, outcome)
        archive_output = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )
        archive_outputs = {"rawjson": archive_output}
        mapping = config.mapping[0]
        file_mapping = FileMapping(
            file=os.path.join(self.temp_folder, "Event.7z", "BITS_jobs.txt"),
            archive_name="Event.7z",
            archive_file="BITS_jobs.txt",
            original_file="\\Windows\\System32\\BITS_jobs.txt",
            original_creation_date="2021-11-30T11:36:15.818000+00:00",
            original_modification_date="2021-11-30T11:36:20.364000+00:00",
            mapping=mapping,
            vss="{00000000-0000-0000-0000-000000000000}",
            error=None,
        )

        entry = BatchEntryBuilder(config, outcome, resolver).build(
            archive="test/data/archive/SampleOrc.7z",
            archive_outputs=archive_outputs,
            file_mapping=file_mapping,
            selection=ParserSelection(
                plugin_file="test/plugin_config/void.xml",
                parser="Void",
                module="ogre.void_parser",
                batch=False,
            ),
        )

        self.assertEqual(entry.file, os.path.abspath(file_mapping.file))
        self.assertEqual(entry.run_config.force_snake_case, True)
        self.assertEqual(
            entry.run_config.params["folder"], ".tmp/output/SampleOrc/test"
        )
        self.assertEqual(
            entry.run_config.output[0].output_folder,
            ".tmp/output/SampleOrc/text_output",
        )
        self.assertEqual(
            entry.run_config.output[0].base_file_name,
            "Void_BITS_jobs_20250904_221144",
        )

        metadata = entry.metadata
        self.assertEqual(metadata.computer, "SampleOrc")
        self.assertEqual(metadata.folder, "archive")
        self.assertEqual(metadata.archive, "SampleOrc.7z")
        self.assertEqual(metadata.subarchive, "Event.7z")
        self.assertEqual(
            metadata.orc_id, "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}"
        )
        self.assertEqual(metadata.archive_filename, "BITS_jobs.txt")
        self.assertEqual(
            metadata.original_filename, "\\Windows\\System32\\BITS_jobs.txt"
        )
        self.assertEqual(metadata.vss, "{00000000-0000-0000-0000-000000000000}")
        creation_date = metadata.creation_date
        modif_date = metadata.modif_date
        assert creation_date is not None
        assert modif_date is not None
        self.assertEqual(
            creation_date.isoformat(), "2021-11-30T11:36:15.818000+00:00"
        )
        self.assertEqual(
            modif_date.isoformat(), "2021-11-30T11:36:20.364000+00:00"
        )

    def test_build_entry_raises_key_error_for_unknown_output_reference(self):
        mapping = _mapping(output=["missing_output"])
        config = _configuration(mapping=[mapping])
        outcome = _outcome()
        resolver = VariableResolver(config, outcome)
        file_mapping = FileMapping(
            file=os.path.join(self.temp_folder, "sample.txt"),
            archive_name="",
            archive_file="sample.txt",
            original_file=None,
            original_creation_date=None,
            original_modification_date=None,
            mapping=mapping,
            vss=None,
            error=None,
        )

        with self.assertRaises(KeyError) as context:
            BatchEntryBuilder(config, outcome, resolver).build(
                archive="test/data/archive/SampleOrc.7z",
                archive_outputs={},
                file_mapping=file_mapping,
                selection=ParserSelection(
                    plugin_file="test/plugin_config/void.xml",
                    parser="Void",
                    module="ogre.void_parser",
                    batch=False,
                ),
            )

        self.assertEqual(context.exception.args[0], "missing_output")


class TestRunConfigGrouper(TestCase):
    def test_grouper_preserves_existing_plugin_file_grouping_contract(self):
        config = _configuration()
        outcome = _outcome()
        resolver = VariableResolver(config, outcome)
        archive_output = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )
        file_mapping = FileMapping(
            file="/tmp/sample.txt",
            archive_name="",
            archive_file="sample.txt",
            original_file=None,
            original_creation_date=None,
            original_modification_date=None,
            mapping=config.mapping[0],
            vss=None,
            error=None,
        )
        builder = BatchEntryBuilder(config, outcome, resolver)
        first = builder.build(
            "test/data/archive/SampleOrc.7z",
            {"rawjson": archive_output},
            file_mapping,
            ParserSelection(
                "test/plugin_config/void.xml",
                "Void",
                "ogre.void_parser",
                False,
            ),
        )
        second = builder.build(
            "test/data/archive/SampleOrc.7z",
            {"rawjson": archive_output},
            file_mapping,
            ParserSelection(
                "test/plugin_config/void.xml",
                "Void",
                "ogre.void_parser",
                False,
            ),
        )

        grouper = RunConfigGrouper()
        grouper.add(
            first,
            "test/plugin_config/void.xml",
            "text_output",
            "ogre.void_parser",
            "Void",
            False,
            3600,
        )
        grouper.add(
            second,
            "test/plugin_config/void.xml",
            "text_output",
            "ogre.void_parser",
            "Void",
            False,
            3600,
        )

        self.assertEqual(len(grouper.map), 1)
        run = grouper.map["test/plugin_config/void.xml"]
        self.assertEqual(len(run.batch_entries), 2)
        self.assertEqual(run.plugin_file, "test/plugin_config/void.xml")
        self.assertEqual(run.mapping_label, "text_output")
        self.assertEqual(run.module, "ogre.void_parser")
        self.assertEqual(run.parser, "Void")
        self.assertFalse(run.batch)
        self.assertEqual(run.timeout, 3600)


class TestArchiveRunPlanner(TempFolderTestCase):
    def test_planner_collects_unpack_errors_and_groups_valid_mappings(self):
        config = _configuration()
        outcome = _outcome(archives=["test/data/archive/SampleOrc.7z"])
        resolver = VariableResolver(config, outcome)
        mapping = config.mapping[0]
        file_mapping = FileMapping(
            file=os.path.join(self.temp_folder, "sample.txt"),
            archive_name="",
            archive_file="sample.txt",
            original_file=None,
            original_creation_date=None,
            original_modification_date=None,
            mapping=mapping,
            vss=None,
            error=None,
        )

        def fake_unpack(archive, password, inner_archive_password, mappings, temp_folder):
            self.assertEqual(archive, "test/data/archive/SampleOrc.7z")
            self.assertIsNone(password)
            self.assertIsNone(inner_archive_password)
            self.assertEqual(list(mappings), config.mapping)
            self.assertEqual(temp_folder, config.temp_folder)
            return UnpackResult([file_mapping], ["extract warning"])

        def fake_load_plugin_parser(plugin_file):
            self.assertEqual(plugin_file, "test/plugin_config/void.xml")
            return ("Void", False)

        planner = ArchiveRunPlanner(
            configuration=config,
            outcome=outcome,
            password=None,
            parsers={"Void": PluginDefinition("Void", "ogre.void_parser", False)},
            resolver=resolver,
            unpack=fake_unpack,
            load_parser=fake_load_plugin_parser,
        )

        result = planner.plan()

        self.assertEqual(result.errors, ["extract warning"])
        self.assertEqual(len(result.runs.map), 1)
        run = result.runs.map["test/plugin_config/void.xml"]
        self.assertEqual(run.parser, "Void")
        self.assertEqual(run.module, "ogre.void_parser")
        self.assertEqual(len(run.batch_entries), 1)


class TestRunPreparationConfigLoading(TempFolderTestCase):
    def setUp(self):
        super().setUp()
        clear_plugin_parser_cache()

    def tearDown(self):
        clear_plugin_parser_cache()
        super().tearDown()

    def test_load_config_validates_regex_and_outputs(self):
        config, plugins = load_config(
            os.path.join("test", "data", "test_commands.yaml"),
            {"temp_folder": self.temp_folder},
        )

        self.assertEqual(config.case, "test")
        self.assertIn("Void", plugins)

    def test_load_plugin_parser_cache_is_owned_by_run_preparation(self):
        plugin_file = os.path.join("test", "plugin_config", "void.xml")

        self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))
        self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))

    def test_load_plugins_discovers_test_void_parser(self):
        plugins = load_plugins(["test"])

        self.assertIn("Void", plugins)
        self.assertEqual(plugins["Void"].module, "ogre.void_parser")


class TestRunPreparationOrchestration(TempFolderTestCase):
    def test_context_load_copies_global_vars_and_adds_derived_values(self):
        global_vars = {"temp_folder": self.temp_folder}

        context = RunPreparationContext.load(
            os.path.join("test", "data", "test_commands_run.yaml"),
            os.path.join("test", "data", "archive", "SampleOrc.7z"),
            None,
            global_vars,
        )

        self.assertEqual(global_vars, {"temp_folder": self.temp_folder})
        self.assertEqual(context.global_vars["computer_name"], "SampleOrc")
        self.assertEqual(context.global_vars["orc_id"], context.outcome.id)
        self.assertEqual(
            context.global_vars["orc_start_date"], context.outcome.date.isoformat()
        )
        self.assertEqual(
            context.configuration.temp_folder.startswith(self.temp_folder), True
        )
        self.assertIn("Void", context.parsers)

    def test_prepare_runs_preserves_existing_grouping_and_metadata_contract(self):
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
        archive_filename = original_entry.metadata.archive_filename
        creation_date = original_entry.metadata.creation_date
        modif_date = original_entry.metadata.modif_date
        assert archive_filename is not None
        assert creation_date is not None
        assert modif_date is not None
        self.assertIn(
            "Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
            archive_filename,
        )
        self.assertEqual(
            original_entry.metadata.original_filename,
            "\\Windows\\System32\\winevt\\Logs\\Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
        )
        self.assertEqual(
            creation_date.isoformat(),
            "2021-11-30T11:36:15.818000+00:00",
        )
        self.assertEqual(
            modif_date.isoformat(),
            "2021-11-30T11:36:20.364000+00:00",
        )
        self.assertEqual(
            original_entry.metadata.vss,
            "{00000000-0000-0000-0000-000000000000}",
        )

    def test_prepare_runs_preserves_unknown_output_key_error(self):
        with self.assertRaises(KeyError) as context:
            prepare_runs(
                os.path.join("test", "data", "test_commands_bad_output.yaml"),
                os.path.join("test", "data", "archive", "SampleOrc.7z"),
                None,
                {"temp_folder": self.temp_folder},
            )

        self.assertEqual(context.exception.args[0], "bad_output")
