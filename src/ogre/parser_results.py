from dataclasses import dataclass
from typing import Any

from dfir_ogre_common import Metadata


@dataclass
class FileStat:
    file_name: str
    num_rows: int
    output_type: str
    format: str
    date_format: str
    with_timeline: bool
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


def create_run_result(
    mapping_label: str,
    parser: str,
    module: str,
    start_date: str,
    metadata: dict[str, str | None],
) -> RunResult:
    return RunResult(
        mapping_label,
        0,
        None,
        0,
        0,
        0,
        parser,
        module,
        start_date,
        metadata,
        [],
    )


def apply_report_to_result(run_result: RunResult, report: Any) -> None:
    run_result.last_error = report.last_error
    run_result.num_errors = report.num_errors

    for out_report in report.output_reports or []:
        output_stat = OutputStat(out_report.last_error, [])
        for file_report in out_report.file_reports:
            output_stat.file_stats.append(
                FileStat(
                    file_report.file_name,
                    file_report.num_lines,
                    file_report.output_type,
                    file_report.format,
                    file_report.date_format,
                    file_report.with_timeline,
                    file_report.include_empty,
                )
            )
        run_result.output.append(output_stat)


def finalize_run_result(run_result: RunResult, elapsed_s: float) -> RunResult:
    rows = 0
    for stat in run_result.output:
        for file_stat in stat.file_stats:
            rows += file_stat.num_rows

    run_result.rows = rows
    run_result.time_s = round(elapsed_s, 3)
    if elapsed_s <= 0 or rows == 0:
        run_result.row_sec = 0
    else:
        run_result.row_sec = round(rows / elapsed_s, 0)
    return run_result


def metadata_to_dict(metadata: Metadata) -> dict[str, str | None]:
    meta_dict: dict[str, str | None] = {}
    meta_dict["computer"] = metadata.computer

    if metadata.orc_id:
        meta_dict["orc_id"] = metadata.orc_id

    if metadata.folder:
        meta_dict["folder"] = metadata.folder

    if metadata.archive:
        meta_dict["archive"] = metadata.archive

    if metadata.subarchive:
        meta_dict["subarchive"] = metadata.subarchive

    if metadata.archive_filename:
        meta_dict["archive_filename"] = metadata.archive_filename

    if metadata.original_filename:
        meta_dict["original_filename"] = metadata.original_filename

    if metadata.vss:
        meta_dict["vss"] = metadata.vss

    if metadata.creation_date:
        meta_dict["creation_date"] = metadata.creation_date.isoformat()

    if metadata.modif_date:
        meta_dict["modif_date"] = metadata.modif_date.isoformat()

    return meta_dict
