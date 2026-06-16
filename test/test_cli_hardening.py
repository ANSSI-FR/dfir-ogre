import json
from unittest import TestCase

from ogre.cli import DataclassJSONEncoder, ReportBuilder, parse_params
from ogre.commands import RunResult


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


class TestCliHardening(TestCase):
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
        builder.add_result(
            make_run_result(rows=3, time_s=2.0, last_error="bad row", num_errors=1),
            "two.txt",
        )

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
