import json
from pathlib import Path
from unittest import mock

from ogre import archive_runner
from ogre.parser_results import create_run_result
from ogre.run_preparation import OgreRunConfiguration, PrepareRunResult, RunConfigGrouper

from .hardening_helpers import TempFolderTestCase


class TestSharedRunner(TempFolderTestCase):
    def _prepared(self, *, computer="host", orc_id=None, errors=None):
        return PrepareRunResult(
            archive=None,
            runs=RunConfigGrouper(),
            errors=list(errors or []),
            computer=computer,
            orc_id=orc_id,
            output_folder=str(Path(self.temp_folder) / "out"),
            report_folder=str(Path(self.temp_folder) / "reports"),
            tmp_folder=str(Path(self.temp_folder) / "tmp" / "uuid"),
        )

    def test_zero_runs_builds_error_report_without_starting_manager(self):
        from ogre.archive_runner import execute_prepared_runs

        prepared = self._prepared(errors=["No files matched"])
        with mock.patch(
            "ogre.archive_runner.multiprocessing.Manager",
            side_effect=AssertionError("unused manager started"),
        ):
            report = execute_prepared_runs(prepared, "dfir-ogre folder", "2025-09-04T22:11:44+00:00")

        self.assertEqual(report.extract_errors, ["No files matched"])
        self.assertEqual(report.summary, [])
        self.assertEqual(report.run_results, [])
        self.assertIsNone(report.orc_id)

    def test_existing_result_aggregation_is_used_for_prepared_run(self):
        from ogre.archive_runner import execute_prepared_runs

        prepared = self._prepared(orc_id="orc-1", errors=["scan warning"])
        prepared.runs.map["plugin.xml"] = OgreRunConfiguration(
            [mock.Mock(file="/evidence/a.evtx")],
            "plugin.xml",
            "event",
            "plugin.module",
            "Parser",
            False,
            10,
        )
        result = create_run_result("event", "Parser", "plugin.module", "start", {})
        result.rows = 3
        result.time_s = 1.5
        result.last_error = "bad row"
        result.num_errors = 1
        with mock.patch("ogre.archive_runner.multiprocessing.Manager", return_value=object()):
            with mock.patch("ogre.archive_runner.run_parser_with_timeout", return_value=result):
                report = execute_prepared_runs(
                    prepared, "dfir-ogre orc", "2025-09-04T22:11:44+00:00"
                )

        self.assertEqual(report.extract_errors, ["scan warning"])
        self.assertEqual(len(report.run_results), 1)
        self.assertEqual(report.summary[0].rows, 3)
        self.assertEqual(report.summary[0].runs, 1)
        self.assertEqual(len(report.parsing_errors), 1)
        self.assertIn("bad row", report.parsing_errors[0])

    def test_report_writer_removes_only_generated_temp_child(self):
        from ogre.archive_runner import write_report_and_cleanup

        prepared = self._prepared()
        temp_child = Path(prepared.tmp_folder)
        temp_child.mkdir(parents=True)
        sibling = temp_child.parent / "other-run"
        sibling.mkdir()

        report_path = write_report_and_cleanup(
            {"computer": "host", "orc_id": None, "source_folder": "/evidence/host"},
            prepared,
            "report_host_uuid.json",
        )

        self.assertEqual(Path(report_path).name, "report_host_uuid.json")
        self.assertEqual(json.loads(Path(report_path).read_text())["orc_id"], None)
        self.assertFalse(temp_child.exists())
        self.assertTrue(sibling.exists())

    def test_archive_wrapper_keeps_existing_filename_and_json_fields(self):
        prepared = self._prepared(orc_id="orc-1")
        prepared.archive = "main.7z"
        with mock.patch("ogre.archive_runner.prepare_runs", return_value=prepared):
            with mock.patch(
                "ogre.archive_runner.multiprocessing.Manager",
                side_effect=AssertionError("unused manager started"),
            ):
                report = archive_runner.parse_archive(
                    "config.yaml", "main.7z", {}, None, "dfir-ogre orc"
                )

        report_path = Path(prepared.report_folder) / "report_host_orc-1.json"
        report_json = json.loads(report_path.read_text())
        self.assertEqual(report.orc_id, "orc-1")
        self.assertEqual(report_json["orc_id"], "orc-1")
        self.assertNotIn("source_folder", report_json)
        self.assertNotIn("run_id", report_json)
