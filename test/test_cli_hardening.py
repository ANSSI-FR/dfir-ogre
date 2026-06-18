import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

from ogre import archive_runner, cli, plugin_runner, process_runner
from ogre.plugin_runner import parse_params
from ogre.commands import OgreRunConfiguration, RunResult
from ogre.reports import DataclassJSONEncoder, ReportBuilder

from .hardening_helpers import TempFolderTestCase


def make_run_result(
    mapping_label="mapping",
    rows=0,
    time_s=0.0,
    last_error=None,
    num_errors=0,
):
    return RunResult(
        mapping_label,
        num_errors,
        last_error,
        rows,
        time_s,
        0,
        "Parser",
        "parser.module",
        "2026-06-16T00:00:00+00:00",
        {"computer": "host1"},
        [],
    )


class TestCliHardening(TempFolderTestCase):
    temp_name = "cli_hardening"

    def test_parse_params_preserves_current_string_conversion(self):
        self.assertEqual(parse_params(None), {})
        self.assertEqual(parse_params(""), {})
        self.assertEqual(parse_params("[1, 2]"), {})
        self.assertEqual(
            parse_params(
                '{"number": 7, "flag": true, "missing": null, "text": "abc"}'
            ),
            {
                "number": "7",
                "flag": "True",
                "missing": "None",
                "text": "abc",
            },
        )

    def test_run_plugin_logs_unknown_plugin(self):
        plugin_file = os.path.join(self.temp_folder, "unknown_plugin.xml")
        with open(plugin_file, "w") as file:
            file.write('<plugin parser="NoSuchParser" />')

        args = SimpleNamespace(
            filename=os.path.join(self.temp_folder, "input.txt"),
            plugin_config=plugin_file,
            computer_name="host1",
            output_folder=self.temp_folder,
            output_format=None,
            output_date_format=None,
            params=None,
            timeline=False,
            include_empty=False,
            library=None,
        )

        with mock.patch("ogre.plugin_runner.importlib.import_module") as import_module:
            with self.assertLogs("ogre.plugin_runner", level="ERROR") as logs:
                plugin_runner.run_plugin(args)

        import_module.assert_called_once_with("dfir_ogre_plugin_windows")
        self.assertIn("Unknown plugin 'NoSuchParser'", "\n".join(logs.output))

    def test_report_builder_aggregates_summary_and_errors(self):
        builder = ReportBuilder(
            "2026-06-16T00:00:00+00:00",
            "dfir-ogre orc",
            "host1",
            "orc1",
            ".tmp/output",
        )
        builder.add_extract_error("extract failed")
        builder.add_result(make_run_result(rows=2, time_s=1.25), "one.txt")
        with self.assertLogs("ogre.reports", level="ERROR") as logs:
            builder.add_result(
                make_run_result(
                    rows=3,
                    time_s=2.0,
                    last_error="bad row",
                    num_errors=1,
                ),
                "two.txt",
            )
        self.assertIn("bad row", "\n".join(logs.output))

        report = builder.get_report()

        self.assertEqual(report.extract_errors, ["extract failed"])
        self.assertEqual(len(report.parsing_errors), 1)
        self.assertIn("bad row", report.parsing_errors[0])
        self.assertEqual(len(report.run_results), 2)
        self.assertEqual(len(report.summary), 1)
        self.assertEqual(report.summary[0].parser, "mapping")
        self.assertEqual(report.summary[0].runs, 2)
        self.assertEqual(report.summary[0].rows, 5)
        self.assertEqual(report.summary[0].time, 3.25)
        self.assertEqual(len(report.summary[0].errors), 1)

    def test_dataclass_json_encoder_serializes_report_dataclasses(self):
        builder = ReportBuilder(
            "2026-06-16T00:00:00+00:00",
            "dfir-ogre orc",
            "host1",
            "orc1",
            ".tmp/output",
        )
        builder.add_result(make_run_result(rows=4, time_s=1.0), "input.txt")

        encoded = json.loads(json.dumps(builder.get_report(), cls=DataclassJSONEncoder))

        self.assertEqual(encoded["computer"], "host1")
        self.assertEqual(encoded["summary"][0]["rows"], 4)
        self.assertEqual(encoded["run_results"][0]["metadata"]["computer"], "host1")

    def test_run_parser_with_timeout_returns_child_result(self):
        expected = make_run_result(rows=1, time_s=0.5)

        class FakeManager:
            def list(self):
                return []

        class FinishedProcess:
            def __init__(self, target, args):
                self.args = args

            def start(self):
                self.args[2].append(expected)

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", False, 5)
        batch_entry = SimpleNamespace(file="input.txt", metadata=SimpleNamespace())

        with mock.patch("ogre.process_runner.multiprocessing.Process", FinishedProcess):
            result = process_runner.run_parser_with_timeout(batch_entry, config, FakeManager())

        self.assertIs(result, expected)

    def test_run_parser_with_timeout_raises_when_child_produces_no_result(self):
        class FakeManager:
            def list(self):
                return []

        class FinishedWithoutResult:
            def __init__(self, target, args):
                return None

            def start(self):
                return None

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", False, 5)
        batch_entry = SimpleNamespace(file="input.txt", metadata=SimpleNamespace())

        with mock.patch("ogre.process_runner.multiprocessing.Process", FinishedWithoutResult):
            with self.assertRaises(Exception) as context:
                process_runner.run_parser_with_timeout(batch_entry, config, FakeManager())

        self.assertEqual(
            str(context.exception),
            "The parsing process crashed and did not produce a report",
        )

    def test_run_parser_with_timeout_terminates_hanging_process(self):
        instances = []

        class FakeManager:
            def list(self):
                return []

        class HangingProcess:
            def __init__(self, target, args):
                self.alive = True
                self.closed = False
                self.terminated = False
                self.killed = False
                self.join_calls = []
                instances.append(self)

            def start(self):
                return None

            def join(self, timeout=None):
                self.join_calls.append(timeout)
                return None

            def is_alive(self):
                return self.alive

            def close(self):
                if self.alive:
                    raise ValueError("Cannot close a process while it is still running")
                self.closed = True

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True
                self.alive = False

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", False, 5)
        batch_entry = SimpleNamespace(file="input.txt", metadata=SimpleNamespace())

        with mock.patch("ogre.process_runner.multiprocessing.Process", HangingProcess):
            with self.assertRaises(Exception) as context:
                process_runner.run_parser_with_timeout(batch_entry, config, FakeManager())

        self.assertIn("parsing timed out", str(context.exception))
        self.assertEqual(instances[0].join_calls, [config.timeout, 1, 1])
        self.assertTrue(instances[0].closed)
        self.assertTrue(instances[0].terminated)
        self.assertTrue(instances[0].killed)

    def test_main_dispatches_list_subcommand(self):
        configuration = os.path.join("test", "data", "test_commands.yaml")

        with mock.patch("ogre.cli.display_plugin_list") as handler:
            with mock.patch.object(
                sys,
                "argv",
                [
                    "dfir-ogre",
                    "list",
                    "--configuration",
                    configuration,
                    "--case",
                    "case1",
                ],
            ):
                cli.main()

        handler.assert_called_once()
        args = handler.call_args.args[0]
        self.assertEqual(args.configuration, configuration)
        self.assertEqual(args.case, "case1")

    def test_parse_archive_writes_report_and_cleans_tmp_folder(self):
        report_folder = os.path.join(self.temp_folder, "report")
        output_folder = os.path.join(self.temp_folder, "output")
        tmp_folder = os.path.join(self.temp_folder, "tmp")
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(tmp_folder, exist_ok=True)

        run_config = OgreRunConfiguration(
            [SimpleNamespace(file="input.txt")],
            "plugin.xml",
            "mapping",
            "module",
            "Parser",
            False,
            5,
        )
        prepared = SimpleNamespace(
            errors=[],
            runs=SimpleNamespace(map={"plugin.xml": run_config}),
            computer="host1",
            orc_id="orc1",
            output_folder=output_folder,
            report_folder=report_folder,
            tmp_folder=tmp_folder,
        )

        with mock.patch("ogre.archive_runner.prepare_runs", return_value=prepared):
            with mock.patch("ogre.archive_runner.multiprocessing.Manager", return_value=object()):
                with mock.patch(
                    "ogre.archive_runner.run_parser_with_timeout",
                    return_value=make_run_result(rows=6, time_s=1.0),
                ) as runner:
                    report = archive_runner.parse_archive(
                        "config.yaml",
                        "archive.7z",
                        {"case": "case1"},
                        None,
                        "dfir-ogre orc",
                    )

        runner.assert_called_once()
        self.assertEqual(report.computer, "host1")
        self.assertEqual(report.summary[0].rows, 6)
        self.assertFalse(os.path.exists(tmp_folder))

        report_file = os.path.join(report_folder, "report_host1_orc1.json")
        with open(report_file) as f:
            report_json = json.load(f)

        self.assertEqual(report_json["computer"], "host1")
        self.assertEqual(report_json["summary"][0]["rows"], 6)

    def test_run_batch_parser_with_timeout_terminates_hanging_process(self):
        instances = []

        class FakeManager:
            def list(self):
                return []

        class HangingProcess:
            def __init__(self, target, args):
                self.alive = True
                self.closed = False
                self.terminated = False
                self.killed = False
                self.join_calls = []
                instances.append(self)

            def start(self):
                return None

            def join(self, timeout=None):
                self.join_calls.append(timeout)
                return None

            def is_alive(self):
                return self.alive

            def close(self):
                if self.alive:
                    raise ValueError("Cannot close a process while it is still running")
                self.closed = True

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True
                self.alive = False

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", True, 5)

        with mock.patch("ogre.process_runner.multiprocessing.Process", HangingProcess):
            with self.assertRaises(Exception) as context:
                process_runner.run_batch_parser_with_timeout(config, FakeManager())

        self.assertIn("parsing timed out", str(context.exception))
        self.assertEqual(instances[0].join_calls, [config.timeout, 1, 1])
        self.assertTrue(instances[0].closed)
        self.assertTrue(instances[0].terminated)
        self.assertTrue(instances[0].killed)
