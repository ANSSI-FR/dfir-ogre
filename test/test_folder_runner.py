import json
import os
from pathlib import Path
from unittest import mock
from uuid import UUID

import yaml

from ogre import cli

from .hardening_helpers import TempFolderTestCase
from .sample_plugin import SampleTexLine  # noqa: F401 - register the real test parser


class TestFolderRunner(TempFolderTestCase):
    def _root(self) -> Path:
        root = (Path(self.temp_folder) / "host.v2").resolve()
        (root / "logs").mkdir(parents=True)
        (root / "logs" / "a.txt").write_text("Evidence line\n")
        return root

    def _config(self, root: Path, pattern: str = r"^logs/.*\.txt$") -> str:
        config = {
            "plugin_prefixes": ["test"],
            "case": "test",
            "output_folder": str(root.parent / "out"),
            "report_folder": str(root.parent / "reports"),
            "temp_folder": str(root.parent / "tmp"),
            "plugin_folder": "test/plugin_config",
            "mapping": [
                {
                    "archive_file_pattern": pattern,
                    "plugin_file": "$plugin_folder/sample_text.xml",
                    "mapping_label": "text_output",
                    "output": ["rawjson"],
                }
            ],
            "output": {
                "rawjson": {
                    "type": "file",
                    "format": "jsonl",
                    "date_format": "iso",
                    "output_folder": "$output_folder/$computer_name/$relative_path",
                    "base_file_name": "$relative_path/$file_name",
                }
            },
        }
        path = Path(self.temp_folder) / "config.yaml"
        path.write_text(yaml.safe_dump(config))
        return str(path)

    def _argv(self, root: Path, config: str, *extra: str) -> list[str]:
        return [
            "dfir-ogre",
            "folder",
            "--folder",
            str(root),
            "--configuration",
            config,
            *extra,
        ]

    def _report(self, root: Path) -> tuple[Path, dict]:
        report_files = list((root.parent / "reports").glob("report_*.json"))
        self.assertEqual(len(report_files), 1)
        return report_files[0], json.loads(report_files[0].read_text())

    def test_cli_dispatches_folder_arguments_and_default_case(self):
        root = self._root()
        config = self._config(root)
        captured = []
        with mock.patch("ogre.cli._handle_folder", side_effect=captured.append):
            with mock.patch("sys.argv", self._argv(root, config, "--computer_name", "chosen")):
                cli.main()

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].folder, str(root))
        self.assertEqual(captured[0].configuration, config)
        self.assertEqual(captured[0].computer_name, "chosen")
        self.assertEqual(captured[0].case, "default_case")

    def test_real_parser_writes_folder_metadata_report_and_preserves_source(self):
        root = self._root()
        config = self._config(root)
        source = root / "logs" / "a.txt"
        original = source.read_bytes()
        sibling = root.parent / "tmp" / "other-run"
        sibling.mkdir(parents=True)
        (sibling / "marker").write_text("keep")

        with mock.patch("sys.argv", self._argv(root, config)):
            cli.main()

        output_path = root.parent / "out" / "host.v2" / "logs" / "logs_a.test.jsonl"
        parsed = json.loads(output_path.read_text())
        report_path, report = self._report(root)
        self.assertEqual(parsed["line"], "Evidence line")
        self.assertEqual(parsed["ogre_md"]["computer"], "host.v2")
        self.assertEqual(parsed["ogre_md"]["folder"], "host.v2")
        self.assertEqual(parsed["ogre_md"]["archive_filename"], "logs/a.txt")
        self.assertEqual(report["run_results"][0]["metadata"]["archive_filename"], "logs/a.txt")
        self.assertEqual(report["source_folder"], str(root))
        self.assertIsNone(report["orc_id"])
        self.assertEqual(report["computer"], "host.v2")
        self.assertEqual(report["summary"][0]["rows"], 1)
        self.assertEqual(report["extract_errors"], [])
        self.assertEqual(report["parsing_errors"], [])
        UUID(report["run_id"])
        self.assertEqual(report_path.name, f"report_host.v2_{report['run_id']}.json")
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual((sibling / "marker").read_text(), "keep")
        self.assertFalse((root.parent / "tmp" / report["run_id"]).exists())

    def test_no_match_writes_zero_result_report_and_returns_error(self):
        root = self._root()
        config = self._config(root, pattern=r"^never$")
        with self.assertLogs("ogre.folder_runner", level="WARNING") as logs:
            with mock.patch("sys.argv", self._argv(root, config)):
                with self.assertRaises(SystemExit) as exit_context:
                    cli.main()

        _, report = self._report(root)
        self.assertEqual(exit_context.exception.code, 1)
        self.assertTrue(any("No files matched" in item for item in logs.output))
        self.assertTrue(any("No files matched" in item for item in report["extract_errors"]))
        self.assertEqual(report["summary"], [])
        self.assertEqual(report["run_results"], [])

    def test_getthis_original_mapping_runs_parser_and_preserves_provenance(self):
        from .test_getthis_mapping import write_getthis

        root = self._root()
        config_path = self._config(root)
        config = yaml.safe_load(Path(config_path).read_text())
        mapping = config["mapping"][0]
        mapping.pop("archive_file_pattern")
        mapping["original_file_pattern"] = r".*\\Report\.wer$"
        Path(config_path).write_text(yaml.safe_dump(config))
        write_getthis(root / "GetThis.csv", [[
            r"logs\a.txt", r"C:\Windows\Report.wer", "2026-01-01T00:00:00Z", "", "snapshot",
        ]])
        source = root / "logs" / "a.txt"
        original = source.read_bytes()

        with mock.patch(
            "ogre.run_preparation.ArchiveRunPlanner.plan",
            side_effect=AssertionError("7z planner called"),
        ):
            with mock.patch("sys.argv", self._argv(root, config_path)):
                cli.main()

        output_path = root.parent / "out" / "host.v2" / "logs" / "logs_a.test.jsonl"
        parsed = json.loads(output_path.read_text())
        _, report = self._report(root)
        self.assertEqual(parsed["line"], "Evidence line")
        self.assertEqual(parsed["ogre_md"]["original_filename"], r"C:\Windows\Report.wer")
        self.assertEqual(parsed["ogre_md"]["vss"], "snapshot")
        self.assertEqual(report["run_results"][0]["metadata"]["original_filename"], r"C:\Windows\Report.wer")
        self.assertEqual(report["extract_errors"], [])
        self.assertEqual(report["parsing_errors"], [])
        self.assertEqual(source.read_bytes(), original)

    def test_child_scan_error_is_reported_after_readable_file_runs(self):
        root = self._root()
        config = self._config(root)
        blocked = root / "blocked"
        blocked.mkdir()
        original_scandir = os.scandir

        def fail_blocked(path):
            if isinstance(path, (str, os.PathLike)) and Path(path) == blocked:
                raise PermissionError("blocked child")
            return original_scandir(path)

        with mock.patch("ogre.folder_input.os.scandir", side_effect=fail_blocked):
            with mock.patch("sys.argv", self._argv(root, config)):
                with self.assertRaises(SystemExit) as exit_context:
                    cli.main()

        _, report = self._report(root)
        self.assertEqual(exit_context.exception.code, 1)
        self.assertEqual(report["summary"][0]["rows"], 1)
        self.assertTrue(any("blocked child" in error for error in report["extract_errors"]))

    def test_parser_error_is_reported_and_returns_error(self):
        root = self._root()
        config = self._config(root)
        with mock.patch(
            "ogre.archive_runner.run_parser_with_timeout",
            side_effect=RuntimeError("parser failed"),
        ):
            with mock.patch("sys.argv", self._argv(root, config)):
                with self.assertRaises(SystemExit) as exit_context:
                    cli.main()

        _, report = self._report(root)
        self.assertEqual(exit_context.exception.code, 1)
        self.assertTrue(any("parser failed" in error for error in report["parsing_errors"]))

    def test_invalid_root_and_computer_names_exit_before_parsing(self):
        root = self._root()
        config = self._config(root)
        cases = [
            self._argv(root / "missing", config),
            *(self._argv(root, config, "--computer_name", name) for name in ("", ".", "..", "host/other")),
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with mock.patch("sys.argv", argv):
                    with self.assertRaises(SystemExit) as exit_context:
                        cli.main()
                self.assertNotEqual(exit_context.exception.code, 0)
        self.assertEqual(list((root.parent / "reports").glob("*.json")), [])

    def test_report_filename_sanitizes_computer_without_changing_metadata(self):
        root = self._root()
        config = self._config(root)
        with mock.patch("sys.argv", self._argv(root, config, "--computer_name", "host:one")):
            cli.main()

        report_path, report = self._report(root)
        self.assertTrue(report_path.name.startswith("report_host_one_"))
        self.assertEqual(report["computer"], "host:one")
        self.assertEqual(report["run_results"][0]["metadata"]["computer"], "host:one")
