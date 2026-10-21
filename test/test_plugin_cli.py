"""Subprocess regressions for single-file plugin CLI results and supervision."""

import gzip
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
    if mode == 'race':
        target = Path(input_file).parent / 'output' / 'race.fixture.jsonl'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'concurrent evidence')
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
    if mode == 'partial_error':
        report.add_error('one record could not be parsed')
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
    def run_cli(
        self, folder, filename, configuration, *, library=None, timeout=5, extra_args=()
    ):
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
        command.extend(extra_args)
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

    def run_fixture(
        self, folder, mode, *, batch=False, timeout=5, extra_args=(), mapping=MAPPING
    ):
        (folder / "cli_fixture.py").write_text(WORKER_LIBRARY, encoding="utf-8")
        configuration = folder / "plugin.xml"
        parser = "CliBatchFixture" if batch else "CliFixture"
        batch_attribute = ' batch="true"' if batch else ""
        configuration.write_text(
            f'<plugin parser="{parser}"{batch_attribute}>{mapping}</plugin>',
            encoding="utf-8",
        )
        filename = folder / mode
        filename.write_bytes(b"fixture")
        return self.run_cli(
            folder,
            filename,
            configuration,
            library="cli_fixture",
            timeout=timeout,
            extra_args=extra_args,
        )

    def test_gzip_and_name_template_preserve_single_and_batched_records(self):
        for batch in (False, True):
            for level in (0, 9):
                with (
                    self.subTest(batch=batch, level=level),
                    TemporaryDirectory() as directory,
                ):
                    folder = Path(directory)
                    result = self.run_fixture(
                        folder,
                        "success",
                        batch=batch,
                        extra_args=(
                            "--output_type",
                            "gzip",
                            "--compression_level",
                            str(level),
                            "--output_name",
                            "$computer_name_${parser}_$file_name",
                        ),
                    )
                    self.assertEqual(result.returncode, 0, self.logs(result))
                    parser = "CliBatchFixture" if batch else "CliFixture"
                    output = (
                        folder
                        / "output"
                        / f"coverage-host_{parser}_success.fixture.jsonl.gz"
                    )
                    with gzip.open(output, "rt", encoding="utf-8") as stream:
                        records = [json.loads(line) for line in stream]
                    self.assertEqual(len(records), 1)
                    self.assertEqual(records[0]["value"], "parsed")
                    self.assertEqual(records[0]["ogre_md"]["computer"], "coverage-host")

    def test_dry_run_lists_all_outputs_without_invoking_parser_or_creating_folder(self):
        for format in (
            "jsonl",
            "csv",
            "normalized_jsonl",
            "normalized_csv",
            "analytics_jsonl",
        ):
            with self.subTest(format=format), TemporaryDirectory() as directory:
                folder = Path(directory)
                mapping = MAPPING + MAPPING.replace(
                    'data_type="fixture"', 'data_type="other"'
                )
                result = self.run_fixture(
                    folder,
                    "exception",
                    mapping=mapping,
                    extra_args=(
                        "--dry_run",
                        "--output_format",
                        format,
                        "--output_type",
                        "gzip",
                        "--output_name",
                        "$computer_name-$parser-$file_name-$timestamp",
                        "--timeline",
                    ),
                )
                self.assertEqual(result.returncode, 0, self.logs(result))
                plan = json.loads(result.stdout)
                self.assertEqual(plan["parser"], "CliFixture")
                self.assertEqual(plan["output_type"], "gzip")
                self.assertEqual(plan["format"], format)
                prefix = plan["base_file_name"]
                self.assertRegex(
                    prefix, r"^coverage-host-CliFixture-exception-\d{8}_\d{6}$"
                )
                extension = (
                    "csv"
                    if format.endswith("csv") and not format.endswith("jsonl")
                    else "jsonl"
                )
                expected = {
                    f"{prefix}.{data_type}.{extension}.gz"
                    for data_type in ("fixture", "other")
                }
                if format.startswith("normalized_") or format == "analytics_jsonl":
                    expected.add(f"ogre_metadata.{extension}.gz")
                    expected.update(
                        f"{prefix}.{data_type}.tl.{extension}.gz"
                        for data_type in ("fixture", "other")
                    )
                self.assertEqual({Path(path).name for path in plan["files"]}, expected)
                self.assertFalse((folder / "output").exists())
                self.assertNotIn("worker parse failed", self.logs(result))

    def test_existing_data_or_sidecar_rejects_entire_run_without_changes(self):
        for name in (
            "success.fixture.jsonl",
            "success.other.jsonl",
            "ogre_metadata.jsonl",
            "success.other.tl.jsonl",
        ):
            for dry_run in (False, True):
                with (
                    self.subTest(name=name, dry_run=dry_run),
                    TemporaryDirectory() as directory,
                ):
                    folder = Path(directory)
                    output = folder / "output"
                    output.mkdir()
                    sentinel = output / name
                    sentinel.write_bytes(b"existing evidence\n")
                    mapping = MAPPING + MAPPING.replace(
                        'data_type="fixture"', 'data_type="other"'
                    )
                    result = self.run_fixture(
                        folder,
                        "success",
                        mapping=mapping,
                        extra_args=(
                            "--output_format",
                            "normalized_jsonl",
                            "--timeline",
                            *(("--dry_run",) if dry_run else ()),
                        ),
                    )
                    self.assertNotEqual(result.returncode, 0, self.logs(result))
                    self.assertIn("already exists", self.logs(result))
                    self.assertEqual(
                        {path.name: path.read_bytes() for path in output.iterdir()},
                        {name: b"existing evidence\n"},
                    )

    def test_repeated_default_command_errors_instead_of_appending(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            first = self.run_fixture(folder, "success")
            self.assertEqual(first.returncode, 0, self.logs(first))
            output = folder / "output" / "success.fixture.jsonl"
            original = output.read_bytes()
            second = self.run_fixture(folder, "success")
            self.assertNotEqual(second.returncode, 0, self.logs(second))
            self.assertEqual(output.read_bytes(), original)

    def test_dry_run_file_names_match_actual_files_in_every_format(self):
        for output_type in ("file", "gzip"):
            for format in (
                "jsonl",
                "csv",
                "normalized_jsonl",
                "normalized_csv",
                "analytics_jsonl",
            ):
                with (
                    self.subTest(output_type=output_type, format=format),
                    TemporaryDirectory() as directory,
                ):
                    folder = Path(directory)
                    options = (
                        "--output_type",
                        output_type,
                        "--output_format",
                        format,
                        "--timeline",
                    )
                    dry_run = self.run_fixture(
                        folder, "success", extra_args=(*options, "--dry_run")
                    )
                    self.assertEqual(dry_run.returncode, 0, self.logs(dry_run))
                    planned = {
                        Path(path).name for path in json.loads(dry_run.stdout)["files"]
                    }
                    actual = self.run_fixture(folder, "success", extra_args=options)
                    self.assertEqual(actual.returncode, 0, self.logs(actual))
                    self.assertEqual(
                        {path.name for path in (folder / "output").iterdir()}, planned
                    )

    def test_target_created_after_preflight_is_preserved(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            result = self.run_fixture(folder, "race")
            self.assertNotEqual(result.returncode, 0, self.logs(result))
            self.assertEqual(
                (folder / "output" / "race.fixture.jsonl").read_bytes(),
                b"concurrent evidence",
            )
            self.assertFalse(list((folder / "output").glob(".ogre-plugin-*")))

    def test_dry_run_rejects_broken_output_directory_symlink(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "output").symlink_to(folder / "missing", target_is_directory=True)
            result = self.run_fixture(folder, "success", extra_args=("--dry_run",))
            self.assertNotEqual(result.returncode, 0, self.logs(result))
            self.assertIn("not a directory", self.logs(result))
            self.assertFalse((folder / "missing").exists())

    def test_valid_partial_results_remain_available_after_reported_error(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            result = self.run_fixture(folder, "partial_error")
            self.assertNotEqual(result.returncode, 0, self.logs(result))
            records = [
                json.loads(line)
                for line in (folder / "output" / "partial_error.fixture.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["value"], "parsed")
            self.assertFalse(list((folder / "output").glob(".ogre-plugin-*")))

    def test_data_and_timeline_filename_collisions_are_rejected(self):
        mapping = MAPPING + MAPPING.replace(
            'data_type="fixture"', 'data_type="fixture.tl"'
        )
        for output_type in ("file", "gzip"):
            for dry_run in (False, True):
                with (
                    self.subTest(output_type=output_type, dry_run=dry_run),
                    TemporaryDirectory() as directory,
                ):
                    folder = Path(directory)
                    result = self.run_fixture(
                        folder,
                        "success",
                        mapping=mapping,
                        extra_args=(
                            "--timeline",
                            "--output_type",
                            output_type,
                            "--output_format",
                            "normalized_jsonl",
                            *(("--dry_run",) if dry_run else ()),
                        ),
                    )
                    self.assertNotEqual(result.returncode, 0, self.logs(result))
                    self.assertIn("collid", self.logs(result))
                    self.assertFalse((folder / "output").exists())

    def test_invalid_options_and_templates_fail_before_output_creation(self):
        for options, message in (
            (("--output_type", "zip"), "invalid choice"),
            (("--output_format", "json"), "invalid choice"),
            (("--compression_level", "10"), "invalid choice"),
            (("--compression_level", "1"), "requires --output_type gzip"),
            (("--output_date_format", "%Q"), "date"),
            (("--timeline_include_undated",), "requires --timeline"),
            (
                (
                    "--timeline",
                    "--timeline_include_undated",
                    "--output_format",
                    "analytics_jsonl",
                ),
                "analytics_jsonl",
            ),
            (("--output_name", "$unknown"), "placeholder"),
            (("--output_name", "../escape"), "filename"),
            (("--output_name", ""), "filename"),
        ):
            for dry_run in (False, True):
                with (
                    self.subTest(options=options, dry_run=dry_run),
                    TemporaryDirectory() as directory,
                ):
                    folder = Path(directory)
                    result = self.run_fixture(
                        folder,
                        "success",
                        extra_args=(
                            *options,
                            *(("--dry_run",) if dry_run else ()),
                        ),
                    )
                    self.assertNotEqual(result.returncode, 0, self.logs(result))
                    self.assertIn(message, self.logs(result))
                    self.assertFalse((folder / "output").exists())

    def test_timeline_can_include_undated_records(self):
        mapping = """<mapping data_type="fixture"><timeline>
            <timeline_type value="Standard" />
            <description><output_name value="value" /></description>
            </timeline><fields><field input="value" parser="String" />
            <field input="when" parser="DateTime" /></fields></mapping>"""
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            result = self.run_fixture(
                folder,
                "success",
                mapping=mapping,
                extra_args=(
                    "--timeline",
                    "--timeline_include_undated",
                ),
            )
            self.assertEqual(result.returncode, 0, self.logs(result))
            records = [
                json.loads(line)
                for line in (folder / "output" / "success.fixture.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0]["timestamp"])
            self.assertEqual(records[0]["timestamp_meaning"], "empty placeholder")

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
            self.assertFalse(list((Path(directory) / "output").glob(".ogre-plugin-*")))
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
