import importlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from dfir_ogre_common import BatchEntry

from ogre.plugins import build_current_plugin_registry

from .metadata_utils import metadata_to_dict
from .run_models import OgreRunConfiguration


@dataclass
class FileStat:
    file_name: str
    num_rows: int
    output_type: str
    format: str
    date_format: str
    with_timeline: bool
    with_qualifiers: bool
    include_empty: bool


@dataclass
class OutputStat:
    last_error: str | None
    file_stats: list[FileStat]


@dataclass
class RunResult:
    mapping_label: str
    num_errors: int
    last_error: str | None
    rows: int
    time_s: float
    row_sec: float
    parser: str
    module: str
    start_date: str
    metadata: dict[str, str | None]
    output: list[OutputStat]


def run_parser(entry: BatchEntry, config: OgreRunConfiguration) -> RunResult:
    importlib.import_module(config.module)
    start_date = datetime.now(timezone.utc).astimezone().isoformat()

    run_result = RunResult(
        config.mapping_label,
        0,
        None,
        0,
        0,
        0,
        config.parser,
        config.module,
        start_date,
        metadata_to_dict(entry.metadata),
        [],
    )

    parser = build_current_plugin_registry().create_parser(config.parser)
    if not parser:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(entry.file, config.plugin_file, entry.run_config, entry.metadata)
        run_result.last_error = report.last_error
        run_result.num_errors = report.num_errors
        _add_output_reports(run_result, report.output_reports)
    except Exception as e:
        run_result.last_error = f"{e}"
    run_result.time_s = time.time() - start

    return _finalize_run_result(run_result)


def run_batch_parser(config: OgreRunConfiguration) -> RunResult:
    importlib.import_module(config.module)
    start_date = datetime.now(timezone.utc).astimezone().isoformat()

    run_result = RunResult(
        config.mapping_label,
        0,
        None,
        0,
        0,
        0,
        config.parser,
        config.module,
        start_date,
        {},
        [],
    )

    parser = build_current_plugin_registry().create_batched_parser(config.parser)
    if not parser:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(config.batch_entries, config.plugin_file)
        run_result.last_error = report.last_error
        run_result.num_errors = report.num_errors
        _add_output_reports(run_result, report.output_reports)
    except Exception as e:
        run_result.last_error = f"{e}"
    run_result.time_s = time.time() - start

    return _finalize_run_result(run_result)


def _add_output_reports(run_result: RunResult, output_reports) -> None:
    for out_report in output_reports:
        output_stat = OutputStat(out_report.last_error, [])
        for fr in out_report.file_reports:
            output_stat.file_stats.append(
                FileStat(
                    fr.file_name,
                    fr.num_lines,
                    fr.output_type,
                    fr.format,
                    fr.date_format,
                    fr.with_timeline,
                    fr.with_qualifiers,
                    fr.include_empty,
                )
            )
        run_result.output.append(output_stat)


def _finalize_run_result(run_result: RunResult) -> RunResult:
    for stat in run_result.output:
        for file_stat in stat.file_stats:
            run_result.rows += file_stat.num_rows

    if run_result.time_s > 0:
        run_result.row_sec = round(run_result.rows / run_result.time_s, 0)
    else:
        run_result.row_sec = 0
    run_result.time_s = round(run_result.time_s, 3)
    return run_result
