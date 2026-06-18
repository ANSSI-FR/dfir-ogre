from unittest import TestCase

from dfir_ogre_common import Metadata, RunReport

from ogre.parser_results import (
    RunResult,
    apply_report_to_result,
    create_run_result,
    finalize_run_result,
    metadata_to_dict,
)


class TestParserResults(TestCase):
    def test_finalize_run_result_sets_zero_row_sec_when_elapsed_is_zero(self):
        result = RunResult(
            "mapping",
            0,
            None,
            0,
            0,
            0,
            "Parser",
            "module.name",
            "2026-06-18T00:00:00+00:00",
            {},
            [],
        )

        finalized = finalize_run_result(result, 0)

        self.assertIs(finalized, result)
        self.assertEqual(finalized.rows, 0)
        self.assertEqual(finalized.time_s, 0)
        self.assertEqual(finalized.row_sec, 0)

    def test_apply_report_to_result_accepts_empty_output_reports(self):
        result = create_run_result(
            "mapping",
            "Parser",
            "module.name",
            "2026-06-18T00:00:00+00:00",
            {},
        )
        report = RunReport()

        apply_report_to_result(result, report)
        finalized = finalize_run_result(result, 0.25)

        self.assertEqual(finalized.last_error, None)
        self.assertEqual(finalized.num_errors, 0)
        self.assertEqual(finalized.output, [])
        self.assertEqual(finalized.rows, 0)
        self.assertEqual(finalized.row_sec, 0)

    def test_metadata_to_dict_preserves_current_metadata_contract(self):
        metadata = Metadata("COMPUTER")
        metadata.orc_id = "orc-id"
        metadata.folder = "case-folder"
        metadata.archive = "archive.7z"
        metadata.subarchive = "inner.7z"
        metadata.archive_filename = "archive/path.txt"
        metadata.original_filename = "C:\\path.txt"
        metadata.vss = "{00000000-0000-0000-0000-000000000000}"

        result = metadata_to_dict(metadata)

        self.assertEqual(result["computer"], "COMPUTER")
        self.assertEqual(result["orc_id"], "orc-id")
        self.assertEqual(result["folder"], "case-folder")
        self.assertEqual(result["archive"], "archive.7z")
        self.assertEqual(result["subarchive"], "inner.7z")
        self.assertEqual(result["archive_filename"], "archive/path.txt")
        self.assertEqual(result["original_filename"], "C:\\path.txt")
        self.assertEqual(result["vss"], "{00000000-0000-0000-0000-000000000000}")
