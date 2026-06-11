import os
import shutil
from unittest import TestCase

from ogre.commands import (
    RunResult,
    _finalize_run_result,
    list_parsers,
    load_config,
    prepare_runs,
    run_parser,
)

from . import TEMP_FOLDER


class TestCommands(TestCase):
    def test_commands_list(self):
        conf_file = os.path.join("test", "data", "test_commands.yaml")
        parsers = list_parsers(conf_file, {})

        parser_found = 0
        for parser in parsers:
            if parser.get_command() == "Test":
                parser_found += 1
            if parser.get_command() == "Void":
                parser_found += 1
        self.assertEqual(2, parser_found)

    def test_add_plugin(self):
        conf_file = os.path.join("test", "data", "test_commands.yaml")
        from .sample_plugin import SampleTexLine

        parsers = list_parsers(conf_file, {})
        self.assertEqual(3, len(parsers))
        del SampleTexLine

    def test_commands_good_parser(self):
        conf_file = os.path.join("test", "data", "test_commands.yaml")

        _ = load_config(conf_file, {})

    def test_commands_bad_regex(self):
        conf_file = os.path.join("test", "data", "test_commands_bad_regex.yaml")

        with self.assertRaises(Exception) as e:
            _ = load_config(conf_file, {})

        result: str = e.exception.__str__()

        self.assertTrue("bad escape \\L at position 2" in result)

    def test_commands_runs(self):
        conf_file = os.path.join("test", "data", "test_commands_run.yaml")
        archive = "test/data/archive/SampleOrc.7z"
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommands"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)

        if runs_result.errors:
            self.fail(f"{runs_result.errors}")

        runs = runs_result.runs.map.values()

        self.assertEqual(1, len(runs))
        for run in runs:
            self.assertEqual(2, len(run.batch_entries))
            for batch_entry in run.batch_entries:
                _ = run_parser(batch_entry, run)
        shutil.rmtree(temp_folder)

    def test_commands_wildcards(self):
        conf_file = os.path.join("test", "data", "test_commands.yaml")
        archive = "test/data/archive/SampleOrc.7z"
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommands"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        runs = [run for run in runs_result.runs.map.values()]
        par = runs[0].batch_entries[0].run_config.output[0]
        self.assertEqual(par.output_folder, ".tmp/output/SampleOrc/text_output/")
        self.assertEqual(par.base_file_name, "Void_BITS_jobs")
        shutil.rmtree(temp_folder)

    def test_prepare_runs_does_not_mutate_global_args(self):
        conf_file = os.path.join("test", "data", "test_commands.yaml")
        archive = "test/data/archive/SampleOrc.7z"
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommands"))
        global_args = {"temp_folder": temp_folder}
        original_global_args = dict(global_args)

        _ = prepare_runs(conf_file, archive, None, global_args)

        self.assertEqual(original_global_args, global_args)
        shutil.rmtree(temp_folder)

    def test_row_sec_is_zero_when_duration_is_zero(self):
        run_result = RunResult(
            "mapping",
            0,
            None,
            10,
            0,
            0,
            "Parser",
            "module",
            "2025-01-01T00:00:00+00:00",
            {},
            [],
        )

        result = _finalize_run_result(run_result)

        self.assertEqual(result.row_sec, 0)

    def test_commands_wildcards_case(self):
        conf_file = os.path.join("test", "data", "test_commands_case.yaml")
        archive = "test/data/archive/SampleOrc.7z"
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommands"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        runs = [run for run in runs_result.runs.map.values()]
        par = runs[0].batch_entries[0].run_config.output[0]
        self.assertEqual(par.output_folder, ".tmp/output/SampleOrc/text_output/")
        self.assertEqual(par.base_file_name, "Void_BITS_jobs")
        shutil.rmtree(temp_folder)

    def test_commands_run_from_outcome(self):
        conf_file = os.path.join("test", "data", "test_commands_run.yaml")
        archive = "test/data/archive/ORC_WorkStation_SampleOrc_162358_Outcome.json"
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommandsOutcome"))
        global_args = {"temp_folder": temp_folder}

        runs_result = prepare_runs(conf_file, archive, None, global_args)
        runs = [run for run in runs_result.runs.map.values()]

        if runs_result.errors:
            self.fail(f"{runs_result.errors}")

        self.assertEqual(1, len(runs))
        for run in runs:
            self.assertEqual(4, len(run.batch_entries))
            for batch_entry in run.batch_entries:
                metadata = batch_entry.metadata
                _ = run_parser(batch_entry, run)

                self.assertEqual(metadata.computer, "W11-22H2U")

        shutil.rmtree(temp_folder)

    def test_commands_run_from_array(self):
        conf_file = os.path.join("test", "data", "test_commands_run.yaml")
        archive = "test/data/archive/SampleOrc.7z,test/data/archive/SampleOrc2.7z"
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommandsOutcome"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        runs = [run for run in runs_result.runs.map.values()]

        if runs_result.errors:
            print(f"errors: {runs_result.errors}")
            self.fail(f"{runs_result.errors}")

        self.assertEqual(1, len(runs))

        for run in runs:
            self.assertEqual(4, len(run.batch_entries))
            # print(run.metadata["computer_name"])
            for batch_entry in run.batch_entries:
                metadata = batch_entry.metadata
                _ = run_parser(batch_entry, run)

                self.assertEqual(metadata.computer, "SampleOrc")

        shutil.rmtree(temp_folder)

    def test_commands_run_from_json(self):
        archive = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "SampleOrc",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": [
                "test/data/archive/SampleOrc.7z",
                "test/data/archive/SampleOrc2.7z"
            ]
        }
        """

        conf_file = os.path.join("test", "data", "test_commands_run.yaml")
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommandsOutcome"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        runs = [run for run in runs_result.runs.map.values()]

        if runs_result.errors:
            self.fail(f"{runs_result.errors}")

        self.assertEqual(1, len(runs))

        for run in runs:
            self.assertEqual(4, len(run.batch_entries))
            for batch_entry in run.batch_entries:
                metadata = batch_entry.metadata
                _ = run_parser(batch_entry, run)

                self.assertEqual(metadata.computer, "SampleOrc")
                self.assertEqual(metadata.orc_id, "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}")

        shutil.rmtree(temp_folder)

    def test_commands_dir_tree_from_json(self):
        archive = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "SampleOrc",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": [
                "test/data/archive/SampleOrc.7z",
                "test/data/archive/SampleOrc2.7z"
            ]
        }
        """

        conf_file = os.path.join("test", "data", "test_commands_json.yaml")
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommandsOutcome"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        self.assertEqual(runs_result.report_folder, "/data/test/ogre/ogre_report")

        runs = [run for run in runs_result.runs.map.values()]

        if runs_result.errors:
            self.fail(f"{runs_result.errors}")

        run = runs[0]
        self.assertEqual(4, len(run.batch_entries))
        output = run.batch_entries[0].run_config.output[0]
        self.assertEqual(output.output_folder, ".tmp/output/SampleOrc/text_output")

        archive = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "SampleOrc",
            "dir_tree":"presta/SuperIR",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": [
                "test/data/archive/SampleOrc.7z",
                "test/data/archive/SampleOrc2.7z"
            ]
        }
        """

        conf_file = os.path.join("test", "data", "test_commands_json.yaml")
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommandsOutcome"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        self.assertEqual(runs_result.report_folder, "/data/test/ogre/presta/SuperIR/ogre_report")

        runs = [run for run in runs_result.runs.map.values()]

        if runs_result.errors:
            self.fail(f"{runs_result.errors}")

        run = runs[0]
        self.assertEqual(4, len(run.batch_entries))
        output = run.batch_entries[0].run_config.output[0]
        self.assertEqual(output.output_folder, ".tmp/output/SampleOrc/text_output/presta/SuperIR")
        shutil.rmtree(temp_folder)

    def test_commands_timestamp_from_json(self):
        archive = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "SampleOrc",
            "dir_tree":"presta/SuperIR",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": [
                "test/data/archive/SampleOrc.7z",
                "test/data/archive/SampleOrc2.7z"
            ]
        }
        """

        conf_file = os.path.join("test", "data", "test_commands_json_timestamp.yaml")
        temp_folder = str(os.path.join(TEMP_FOLDER, "TestCommandsOutcome"))
        global_args = {"temp_folder": temp_folder}
        runs_result = prepare_runs(conf_file, archive, None, global_args)
        self.assertEqual(runs_result.report_folder, "/data/test/ogre/presta/SuperIR/ogre_report")

        runs = [run for run in runs_result.runs.map.values()]

        if runs_result.errors:
            self.fail(f"{runs_result.errors}")

        run = runs[0]
        self.assertEqual(4, len(run.batch_entries))
        output = run.batch_entries[0].run_config.output[0]
        self.assertEqual(output.output_folder, ".tmp/output/SampleOrc/text_output/20250904_221144")

        self.assertEqual(output.base_file_name, "Void_BITS_jobs_20250904_221144")
        shutil.rmtree(temp_folder)
