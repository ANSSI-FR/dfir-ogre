import time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from ogre.runner import _run_process_with_timeout, run_plugin


def _append_success(result):
    result.put("ok")


def _produce_no_result(result):
    return None


def _sleep_too_long(result):
    time.sleep(2)


class TestRunner(TestCase):
    def test_run_process_with_timeout_returns_success_result(self):
        result = _run_process_with_timeout(_append_success, (), 1)

        self.assertEqual(result, "ok")

    def test_run_process_with_timeout_reports_missing_result(self):
        with self.assertRaisesRegex(Exception, "crashed"):
            _run_process_with_timeout(_produce_no_result, (), 1)

    def test_run_process_with_timeout_reports_timeout(self):
        with self.assertRaisesRegex(Exception, "timed out"):
            _run_process_with_timeout(_sleep_too_long, (), 0.1)

    def test_run_plugin_invokes_single_file_parser_with_cli_metadata_and_defaults(self):
        parser = _CapturingParser()
        registry = _PluginRegistry(parser=parser, batch=False)
        args = _plugin_args()

        with (
            patch("ogre.runner.init_logger"),
            patch("ogre.runner.importlib.import_module") as import_module,
            patch("ogre.runner.build_current_plugin_registry", return_value=registry),
        ):
            run_plugin(args)

        import_module.assert_called_once_with("dfir_ogre_plugin_windows")
        self.assertEqual(parser.calls, 1)
        self.assertEqual(parser.input_file, "input.evtx")
        self.assertEqual(parser.plugin_file, "parser.xml")
        self.assertEqual(parser.metadata.computer, "workstation-01")
        self.assertEqual(parser.metadata.archive_filename, "input.evtx")
        self.assertEqual(parser.run_config.params, {"limit": "10", "enabled": "True"})

        output = parser.run_config.output[0]
        self.assertEqual(output.base_file_name, "input")
        self.assertEqual(output.output_folder, "out")
        self.assertEqual(output.format, "jsonl")
        self.assertEqual(output.date_format, "iso")
        self.assertFalse(output.with_timeline)
        self.assertFalse(output.include_empty)

    def test_run_plugin_invokes_batch_parser_with_cli_metadata(self):
        parser = _CapturingBatchParser()
        registry = _PluginRegistry(parser=parser, batch=True)
        args = _plugin_args(timeline=True, include_empty=True)

        with (
            patch("ogre.runner.init_logger"),
            patch("ogre.runner.importlib.import_module"),
            patch("ogre.runner.build_current_plugin_registry", return_value=registry),
        ):
            run_plugin(args)

        self.assertEqual(parser.calls, 1)
        self.assertEqual(parser.plugin_file, "parser.xml")
        self.assertEqual(len(parser.entries), 1)

        entry = parser.entries[0]
        self.assertEqual(entry.file, "input.evtx")
        self.assertEqual(entry.metadata.computer, "workstation-01")
        self.assertEqual(entry.metadata.archive_filename, "input.evtx")

        output = entry.run_config.output[0]
        self.assertTrue(output.with_timeline)
        self.assertTrue(output.include_empty)

    def test_run_plugin_imports_custom_library_when_requested(self):
        parser = _CapturingParser()
        registry = _PluginRegistry(parser=parser, batch=False)
        args = _plugin_args(library="custom.parsers")

        with (
            patch("ogre.runner.init_logger"),
            patch("ogre.runner.importlib.import_module") as import_module,
            patch("ogre.runner.build_current_plugin_registry", return_value=registry),
        ):
            run_plugin(args)

        self.assertEqual(
            [call.args[0] for call in import_module.call_args_list],
            ["dfir_ogre_plugin_windows", "custom.parsers"],
        )


def _plugin_args(**overrides):
    values = {
        "filename": "input.evtx",
        "plugin_config": "parser.xml",
        "computer_name": "workstation-01",
        "output_folder": "out",
        "output_format": None,
        "output_date_format": None,
        "params": '{"limit": 10, "enabled": true}',
        "timeline": False,
        "include_empty": False,
        "library": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _PluginRegistry:
    def __init__(self, parser, batch: bool):
        self.parser = parser
        self.batch = batch

    def load_plugin_parser(self, plugin_file):
        self.plugin_file = plugin_file
        return SimpleNamespace(parser_name="FakeParser", batch=self.batch)

    def create_parser(self, parser_name):
        self.parser_name = parser_name
        return None if self.batch else self.parser

    def create_batched_parser(self, parser_name):
        self.parser_name = parser_name
        return self.parser if self.batch else None


class _CapturingParser:
    calls = 0

    def parse(self, input_file, plugin_file, run_config, metadata):
        self.calls += 1
        self.input_file = input_file
        self.plugin_file = plugin_file
        self.run_config = run_config
        self.metadata = metadata
        return SimpleNamespace(last_error=None)


class _CapturingBatchParser:
    calls = 0

    def parse(self, entries, plugin_file):
        self.calls += 1
        self.entries = entries
        self.plugin_file = plugin_file
        return SimpleNamespace(last_error=None)
