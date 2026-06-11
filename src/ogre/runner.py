from __future__ import annotations

import datetime
import importlib
import json
import logging
import multiprocessing
import os
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable
from multiprocessing.managers import ListProxy, SyncManager
from pathlib import Path
from typing import Any

from dfir_ogre_common import BatchEntry, Metadata, OutputConfiguration, RunConfiguration

from .commands import (
    OgreRunConfiguration,
    RunResult,
    metadata_to_dict,
    prepare_runs,
    run_batch_parser,
    run_parser,
)
from .logging import init_logger
from .plugins import find_batched_parser, find_parser
from .reporting import ArchiveReport, DataclassJSONEncoder, ReportBuilder

logger = logging.getLogger(__name__)


def parse_archive(
    configuration: str,
    archive: str,
    global_vars: dict[str, str],
    password: str | None,
    command_line: str,
) -> ArchiveReport:
    """
    Unpack an ORC archive, run configured parsers, and write a JSON report.
    """
    logger.info(f"Unpacking archive '{archive}'")

    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    prepared_runs = prepare_runs(configuration, archive, password, global_vars)
    report_builder = ReportBuilder(
        start_date,
        command_line,
        prepared_runs.computer,
        prepared_runs.orc_id,
        prepared_runs.output_folder,
    )
    for error in prepared_runs.errors:
        logger.error(f"{error}")
        report_builder.add_extract_error(error)

    manager = multiprocessing.Manager()
    try:
        for run_configuration in prepared_runs.runs.map.values():
            if run_configuration.batch:
                _run_batch_configuration(run_configuration, manager, report_builder)
            else:
                _run_single_file_configuration(run_configuration, manager, report_builder)

        archive_report = report_builder.get_report()
        json_str = json.dumps(archive_report, cls=DataclassJSONEncoder)
        report_name = f"report_{prepared_runs.computer}_{prepared_runs.orc_id}.json"

        os.makedirs(prepared_runs.report_folder, exist_ok=True)
        report_file = os.path.join(prepared_runs.report_folder, report_name)
        logger.info(f"Writing report: {report_file}")
        with open(report_file, "w") as f:
            _ = f.write(json_str)

        return archive_report
    finally:
        manager.shutdown()
        logger.info(f"Deleting temporary data: {prepared_runs.tmp_folder}")
        shutil.rmtree(prepared_runs.tmp_folder, ignore_errors=True)


def _run_batch_configuration(
    run_configuration: OgreRunConfiguration,
    manager: SyncManager,
    report_builder: ReportBuilder,
) -> None:
    try:
        logger.info(
            f"Running a batch of {len(run_configuration.batch_entries)} files with parser "
            f"'{run_configuration.parser}', for mapping label "
            f"'{run_configuration.mapping_label}' "
        )
        result = run_batch_parser_with_timeout(run_configuration, manager)
        report_builder.add_result(
            result, f"A batch of {len(run_configuration.batch_entries)} files"
        )
    except Exception as e:
        error = (
            f"An error occurred while parsing a batch of "
            f"{len(run_configuration.batch_entries)} with parser: "
            f"'{run_configuration.parser}'  for mapping label "
            f"'{run_configuration.mapping_label}' error: {e}"
        )
        logger.error(error)
        report_builder.add_parsing_error(error)


def _run_single_file_configuration(
    run_configuration: OgreRunConfiguration,
    manager: SyncManager,
    report_builder: ReportBuilder,
) -> None:
    for batch_entry in run_configuration.batch_entries:
        try:
            logger.info(f"Running '{run_configuration.parser}', on file '{batch_entry.file}' ")
            result = run_parser_with_timeout(batch_entry, run_configuration, manager)
            report_builder.add_result(result, batch_entry.file)
        except Exception as e:
            error = (
                f"An error occurred while parsing file '{batch_entry.file}' with parser: "
                f"'{run_configuration.parser}' from module: '{run_configuration.module}' "
                f"error: {e}"
            )
            logger.error(error)
            report_builder.add_parsing_error(error)


def run_parser_with_timeout(
    batch_entry: BatchEntry,
    config: OgreRunConfiguration,
    manager: SyncManager,
) -> RunResult:
    """Execute a parser in a separate process with a timeout."""
    return _run_process_with_timeout(
        run_parser_command,
        (batch_entry, config),
        config.timeout,
        manager,
    )


def run_batch_parser_with_timeout(
    config: OgreRunConfiguration,
    manager: SyncManager,
) -> RunResult:
    """Execute a batched parser in a separate process with a timeout."""
    return _run_process_with_timeout(
        run_batch_parser_command,
        (config,),
        config.timeout,
        manager,
    )


def _run_process_with_timeout(
    target: Callable[..., None],
    args: tuple[Any, ...],
    timeout: int | float,
    manager: SyncManager,
) -> RunResult:
    result = manager.list()
    process = multiprocessing.Process(target=target, args=(*args, result))
    process.start()
    try:
        process.join(timeout)
        if process.is_alive():
            _stop_process(process)
            raise Exception(f"parsing timed out, could not finish in {timeout} seconds")

        if len(result) == 0:
            raise Exception("The parsing process crashed and did not produce a report")

        return result.pop()
    finally:
        if process.is_alive():
            _stop_process(process)
        _close_process(process)


def _stop_process(process: multiprocessing.Process) -> None:
    process.terminate()
    process.join(1)
    if process.is_alive():
        process.kill()
        process.join(1)


def _close_process(process: multiprocessing.Process) -> None:
    try:
        process.close()
    except ValueError:
        # ``close`` raises if the process is still running; the caller already
        # made a best effort to stop it, so keep the original parser error.
        pass


def run_parser_command(
    batch_entry: BatchEntry,
    config: OgreRunConfiguration,
    result: ListProxy,
) -> None:
    """Wrapper that invokes ``ogre.commands.run_parser`` and stores the result."""
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_parser(batch_entry, config))
    except Exception as e:
        error = (
            f"A critical error occurred while parsing file '{config.batch_entries}' "
            f"with parser: '{config.parser}' from module: '{config.module}' error: {e}"
        )
        logger.error(error)

        result.append(
            RunResult(
                config.mapping_label,
                1,
                error,
                0,
                0,
                0,
                config.parser,
                config.module,
                start_date,
                metadata_to_dict(batch_entry.metadata),
                [],
            )
        )


def run_batch_parser_command(config: OgreRunConfiguration, result: ListProxy) -> None:
    """Wrapper that invokes ``ogre.commands.run_batch_parser`` and stores the result."""
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_batch_parser(config))
    except Exception as e:
        error = (
            f"A critical error occurred while parsing file '{config.batch_entries}' "
            f"with parser: '{config.parser}' from module: '{config.module}' error: {e}"
        )
        logger.error(error)

        result.append(
            RunResult(
                config.mapping_label,
                1,
                error,
                0,
                0,
                0,
                config.parser,
                config.module,
                start_date,
                {},
                [],
            )
        )


def run_plugin(args: Any) -> None:
    """
    Execute a single OGRE parser against a provided file.
    """
    init_logger()

    output_name = Path(args.filename).stem

    importlib.import_module("dfir_ogre_plugin_windows")
    if args.library:
        importlib.import_module(args.library)

    output_format = args.output_format or "jsonl"
    date_format = args.output_date_format or "iso"

    output_config = OutputConfiguration(
        output_name,
        args.output_folder,
        "file",
        output_format,
        date_format,
        args.timeline,
        False,
        args.include_empty,
        {},
    )

    plugin_file = args.plugin_config
    tree = ET.parse(plugin_file)
    root = tree.getroot()
    plugin = root.attrib.get("parser")
    is_batch = root.attrib.get("batch", None)

    params = parse_params(args.params)
    run_config = RunConfiguration([output_config], False, params)
    metadata = Metadata(args.computer_name)
    metadata.archive_filename = args.filename

    if is_batch:
        parser_obj = find_batched_parser(str(plugin))
        if parser_obj:
            try:
                logger.info(f"Running '{plugin}', on file '{args.filename}' ")
                result = parser_obj.parse(
                    [BatchEntry(args.filename, run_config, Metadata("test"))],
                    plugin_file,
                )
                if result.last_error:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' "
                        f"error: {result.last_error}"
                    )
            except Exception as e:
                logger.error(f"file: '{args.filename}' with parser: '{plugin}' error: {e}")
            return
    else:
        parser_obj = find_parser(str(plugin))
        if parser_obj:
            try:
                logger.info(f"Running '{plugin}', on file '{args.filename}' ")
                result = parser_obj.parse(args.filename, plugin_file, run_config, metadata)
                if result.last_error:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' "
                        f"error: {result.last_error}"
                    )
            except Exception as e:
                logger.error(f"file: '{args.filename}' with parser: '{plugin}' error: {e}")
            return

    logger.error(f"Unknown plugin '{plugin}'")


def parse_params(params: str | None) -> dict[str, str | None]:
    """
    Parse a JSON string supplied on the command line into a dictionary.
    """
    if not params:
        return {}

    json_data = json.loads(params)
    param_dict = {}
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            param_dict[key] = str(value)

    return param_dict
