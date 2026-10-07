import datetime
import json
import logging
import multiprocessing
import os
import shutil
import sys
from typing import Any

from .logging import init_logger
from .process_runner import run_batch_parser_with_timeout, run_parser_with_timeout
from .reports import ArchiveReport, DataclassJSONEncoder, ReportBuilder
from .run_preparation import PrepareRunResult, prepare_runs

logger = logging.getLogger(__name__)


def handle_orc_archive(args):
    init_logger(args.configuration)
    if args.case:
        global_vars = {"case": str(args.case)}
    else:
        global_vars = {}

    _ = parse_archive(
        args.configuration,
        args.archive,
        global_vars,
        args.password,
        " ".join(sys.argv),
    )


def parse_archive(
    configuration: str,
    archive: str,
    global_vars: dict[str, str],
    password: str | None,
    command_line: str,
) -> ArchiveReport:
    logger.info(f"Unpacking archive '{archive}'")

    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    prepared_runs = prepare_runs(configuration, archive, password, global_vars)
    archive_report = execute_prepared_runs(prepared_runs, command_line, start_date)
    report_name = f"report_{prepared_runs.computer}_{prepared_runs.orc_id}.json"
    write_report_and_cleanup(archive_report, prepared_runs, report_name)
    return archive_report


def execute_prepared_runs(
    prepared_runs: PrepareRunResult, command_line: str, timestamp: str
) -> ArchiveReport:
    """Run grouped parser entries and aggregate the existing report fields."""
    report_builder = ReportBuilder(
        timestamp,
        command_line,
        prepared_runs.computer,
        prepared_runs.orc_id,
        prepared_runs.output_folder,
    )
    for errors in prepared_runs.errors:
        logger.error(f"{errors}")
        report_builder.add_extract_error(errors)

    if not prepared_runs.runs.map:
        return report_builder.get_report()

    manager = multiprocessing.Manager()
    for run_configuration in prepared_runs.runs.map.values():
        if run_configuration.batch:
            try:
                logger.info(f"Running a batch of {len(run_configuration.batch_entries)} files with parser '{run_configuration.parser}', for mapping label '{run_configuration.mapping_label}' ")
                result = run_batch_parser_with_timeout(run_configuration, manager)
                report_builder.add_result(result, f"A batch of {len(run_configuration.batch_entries)} files")
            except Exception as error:
                message = f"An error occurred while parsing a batch of {len(run_configuration.batch_entries)} with parser: '{run_configuration.parser}'  for mapping label '{run_configuration.mapping_label}' error: {error}"
                logger.error(message)
                report_builder.add_parsing_error(message)
        else:
            for batch_entry in run_configuration.batch_entries:
                try:
                    logger.info(f"Running '{run_configuration.parser}', on file '{batch_entry.file}' ")
                    result = run_parser_with_timeout(batch_entry, run_configuration, manager)
                    report_builder.add_result(result, batch_entry.file)
                except Exception as error:
                    message = f"An error occurred while parsing file '{batch_entry.file}' with parser: '{run_configuration.parser}' from module: '{run_configuration.module}' error: {error}"
                    logger.error(message)
                    report_builder.add_parsing_error(message)

    return report_builder.get_report()


def write_report_and_cleanup(
    report: ArchiveReport | dict[str, Any],
    prepared_runs: PrepareRunResult,
    report_name: str,
) -> str:
    """Write a report and remove only this run's generated temp child."""
    json_str = json.dumps(report, cls=DataclassJSONEncoder)
    os.makedirs(prepared_runs.report_folder, exist_ok=True)
    report_file = os.path.join(prepared_runs.report_folder, report_name)
    logger.info(f"Writing report: {report_file}")
    with open(report_file, "w") as file:
        _ = file.write(json_str)

    logger.info(f"Deleting temporary data: {prepared_runs.tmp_folder}")
    shutil.rmtree(prepared_runs.tmp_folder, ignore_errors=True)
    return report_file
