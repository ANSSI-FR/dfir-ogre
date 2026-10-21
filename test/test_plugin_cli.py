"""Subprocess regressions for single-file plugin CLI results and supervision."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless


SOURCE = Path(__file__).resolve().parents[1] / "src"
WINDOWS_PLUGIN = SOURCE.parents[1] / "dfir-ogre-plugin-windows"
LNK_FIXTURE = WINDOWS_PLUGIN / "tests" / "data" / "lnk" / "desktop.lnk.data"
LNK_CONFIGURATION = WINDOWS_PLUGIN / "configuration" / "lnk_batched.xml"

# A custom parser lets the real CLI and multiprocessing worker exercise each
# failure boundary without relying on platform-specific parser failures.
WORKER_LIBRARY = """
import os
import time
from pathlib import Path
from types import SimpleNamespace

from dfir_ogre_common import (
    OgreBatchedPlugin, OgrePlugin, Output, PluginConfiguration,
    PluginDescription, Record, RunReport, Value,
)


def parse_result(input_file, plugin_file, run_config, metadata):
    mode = Path(input_file).name
    if mode == 'exception':
        raise RuntimeError('worker parse failed')
    if mode == 'crash':
        os._exit(7)
    if mode == 'timeout':
        time.sleep(60)
    if mode == 'report_error':
        report = RunReport()
        report.add_error('parser reported an error')
        return report
    if mode == 'report_count':
        return SimpleNamespace(last_error=None, num_errors=1, output_reports=[])
    if mode == 'report_last_error':
        return SimpleNamespace(last_error='parser error', num_errors=0, output_reports=[])
    if mode in ('output_count', 'output_last_error'):
        output = SimpleNamespace(
            last_error='output failed' if mode == 'output_last_error' else None,
            num_errors=1 if mode == 'output_count' else 0,
            file_reports=[],
        )
        return SimpleNamespace(last_error=None, num_errors=0, output_reports=[output])
    report = RunReport()
    with Output(run_config, PluginConfiguration.load(plugin_file), metadata) as output:
        record = Record()
        record.add('value', Value.String('parsed'))
        output.write(record)
        report.add_output_report(output.get_report())
    return report


class CliFixture(OgrePlugin):
    def description(self):
        return PluginDescription('CliFixture', 'CLI result fixture')

    def parse(self, input_file, plugin_file, run_config, metadata):
        return parse_result(input_file, plugin_file, run_config, metadata)


class CliBatchFixture(OgreBatchedPlugin):
    def description(self):
        return PluginDescription('CliBatchFixture', 'Batched CLI result fixture')

    def parse(self, input_files, plugin_file):
        entry = input_files[0]
        return parse_result(entry.file, plugin_file, entry.run_config, entry.metadata)
"""

MAPPING = """<mapping data_type="fixture"><fields>
    <field input="value" parser="String" />
</fields></mapping>"""


class TestPluginCli(TestCase):
    def run_cli(self, folder, filename, configuration, *, library=None, timeout=5):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(SOURCE), str(folder)))
        command = [
            sys.executable,
            "-c",
            "from ogre import main; main()",
            "plugin",
            "--filename",
            str(filename),
            "--plugin_config",
            str(configuration),
            "--computer_name",
            "coverage-host",
            "--output_folder",
            str(folder / "output"),
            "--timeout",
            str(timeout),
        ]
        if library:
            command.extend(("--library", library))
        return subprocess.run(
            command,
            cwd=folder,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    @staticmethod
    def logs(result):
        return f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    def run_fixture(self, folder, mode, *, batch=False, timeout=5):
        (folder / "cli_fixture.py").write_text(WORKER_LIBRARY, encoding="utf-8")
        configuration = folder / "plugin.xml"
        parser = "CliBatchFixture" if batch else "CliFixture"
        batch_attribute = ' batch="true"' if batch else ""
        configuration.write_text(
            f'<plugin parser="{parser}"{batch_attribute}>{MAPPING}</plugin>',
            encoding="utf-8",
        )
        filename = folder / mode
        filename.write_bytes(b"fixture")
        return self.run_cli(
            folder, filename, configuration, library="cli_fixture", timeout=timeout
        )

    def test_batched_parser_preserves_requested_computer_and_input_filename(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            result = self.run_fixture(folder, "success", batch=True)
            self.assertEqual(result.returncode, 0, self.logs(result))
            records = [
                json.loads(line)
                for output in (folder / "output").glob("*.jsonl")
                for line in output.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                records,
                [
                    {
                        "value": "parsed",
                        "ogre_md": {
                            "computer": "coverage-host",
                            "data_type": "fixture",
                            "archive_filename": str(folder / "success"),
                        },
                    }
                ],
                self.logs(result),
            )

    @skipUnless(
        LNK_FIXTURE.is_file() and LNK_CONFIGURATION.is_file(),
        "requires the sibling Windows plugin checkout's real LNK fixture",
    )
    def test_batched_lnk_preserves_requested_computer_and_input_filename(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            result = self.run_cli(folder, LNK_FIXTURE, LNK_CONFIGURATION)
            # A single LNK lacks its SYSTEM hive and may report a timezone
            # resolution error; its emitted row must still identify the source.
            records = [
                json.loads(line)
                for output in (folder / "output").glob("*.jsonl")
                for line in output.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(len(records), 1, self.logs(result))
        self.assertEqual(records[0]["ogre_md"]["computer"], "coverage-host")
        self.assertEqual(records[0]["ogre_md"]["archive_filename"], str(LNK_FIXTURE))

    def test_successful_parser_exits_zero(self):
        for batch in (False, True):
            with self.subTest(batch=batch), TemporaryDirectory() as directory:
                result = self.run_fixture(Path(directory), "success", batch=batch)
                self.assertEqual(result.returncode, 0, self.logs(result))

    def test_parser_and_output_report_errors_exit_nonzero(self):
        for batch in (False, True):
            for mode in (
                "report_error",
                "report_count",
                "report_last_error",
                "output_count",
                "output_last_error",
            ):
                with self.subTest(batch=batch, mode=mode):
                    with TemporaryDirectory() as directory:
                        result = self.run_fixture(Path(directory), mode, batch=batch)
                        self.assertNotEqual(result.returncode, 0, self.logs(result))

    def test_parser_exception_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            result = self.run_fixture(Path(directory), "exception")
        self.assertNotEqual(result.returncode, 0, self.logs(result))
        self.assertIn("worker parse failed", self.logs(result))

    def test_worker_crash_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            result = self.run_fixture(Path(directory), "crash")
        self.assertNotEqual(result.returncode, 0, self.logs(result))
        self.assertIn("exit code 7", self.logs(result))

    def test_worker_timeout_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            result = self.run_fixture(Path(directory), "timeout", timeout=1)
        self.assertNotEqual(result.returncode, 0, self.logs(result))
        self.assertIn("parsing timed out", self.logs(result))

    def test_unknown_parser_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            configuration = folder / "unknown.xml"
            configuration.write_text(
                '<plugin parser="NoSuchParser" />', encoding="utf-8"
            )
            result = self.run_cli(folder, folder / "input", configuration)
        self.assertNotEqual(result.returncode, 0, self.logs(result))
        self.assertIn("Unknown plugin 'NoSuchParser'", self.logs(result))

    def test_missing_input_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            configuration = folder / "jsonl.xml"
            configuration.write_text(
                f'<plugin parser="Jsonl">{MAPPING}</plugin>', encoding="utf-8"
            )
            result = self.run_cli(folder, folder / "missing.jsonl", configuration)
        self.assertNotEqual(result.returncode, 0, self.logs(result))

    def test_malformed_input_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            filename = folder / "malformed.jsonl"
            filename.write_bytes(b"not a JSON record\n")
            configuration = folder / "jsonl.xml"
            configuration.write_text(
                f'<plugin parser="Jsonl">{MAPPING}</plugin>', encoding="utf-8"
            )
            result = self.run_cli(folder, filename, configuration)
        self.assertNotEqual(result.returncode, 0, self.logs(result))

    def test_malformed_configuration_exits_nonzero(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            configuration = folder / "malformed.xml"
            configuration.write_text("<plugin", encoding="utf-8")
            result = self.run_cli(folder, folder / "input", configuration)
        self.assertNotEqual(result.returncode, 0, self.logs(result))
