import importlib
import json
import logging
import multiprocessing
import xml.etree.ElementTree as ET
from pathlib import Path

from dfir_ogre_common import (
    BatchEntry,
    Metadata,
    OgreBatchedPlugin,
    OgrePlugin,
    OutputConfiguration,
    RunConfiguration,
)

from .logging import init_logger

logger = logging.getLogger(__name__)

PLUGIN_DEFAULT_TIMEOUT = 60


def run_plugin(args):
    init_logger()

    timeout = getattr(args, "timeout", PLUGIN_DEFAULT_TIMEOUT)
    failed = False
    process = multiprocessing.Process(target=_run_plugin_child, args=(args,))
    process.start()
    try:
        process.join(timeout)
        if process.is_alive():
            _terminate_process(process)
            logger.error(f"parsing timed out, could not finish in {timeout} seconds")
            failed = True
        else:
            if process.exitcode not in (0, None):
                logger.error(f"The parsing process failed with exit code {process.exitcode}")
                failed = True
            _close_process(process)
    except KeyboardInterrupt:
        _terminate_process(process)
        raise

    if failed:
        raise SystemExit(1)


def _terminate_process(process):
    if process.is_alive():
        process.terminate()
        _join_while_stopping(process)
    if process.is_alive():
        process.kill()
        _join_while_stopping(process)
    _close_process(process)


def _close_process(process):
    if not process.is_alive():
        try:
            process.close()
        except ValueError:
            pass


def _join_while_stopping(process):
    try:
        process.join(1)
    except KeyboardInterrupt:
        pass


def _run_plugin_child(args):
    try:
        if not _run_plugin_direct(args):
            raise SystemExit(1)
    except Exception as error:
        logger.error(f"A critical error occurred while running plugin: {error}")
        raise


def _run_plugin_direct(args):
    init_logger()

    output_name = Path(args.filename).stem

    importlib.import_module("dfir_ogre_plugin_windows")
    if args.library:
        importlib.import_module(args.library)

    format = "jsonl"
    if args.output_format:
        format = args.output_format

    date_format = "iso"
    if args.output_date_format:
        date_format = args.output_date_format

    rust_output = OutputConfiguration(
        base_file_name=output_name,
        output_folder=args.output_folder,
        output_type="file",
        format=format,
        date_format=date_format,
        with_timeline=args.timeline,
        include_empty=args.include_empty,
        params={},
    )

    plugin_file = args.plugin_config

    tree = ET.parse(plugin_file)
    root = tree.getroot()
    plugin = root.attrib.get("parser")
    is_batch = root.attrib.get("batch", None)

    params = parse_params(args.params)

    runconfig = RunConfiguration([rust_output], False, params)
    metadata = Metadata(args.computer_name)

    metadata.archive_filename = args.filename

    found = False
    succeeded = True
    if is_batch:
        for parser in OgreBatchedPlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        [BatchEntry(args.filename, runconfig, metadata)],
                        plugin_file,
                    )

                    if not _report_succeeded(result, args.filename, plugin):
                        succeeded = False
                except Exception as error:
                    succeeded = False
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {error}"
                    )
    else:
        for parser in OgrePlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        args.filename,
                        plugin_file,
                        runconfig,
                        metadata,
                    )

                    if not _report_succeeded(result, args.filename, plugin):
                        succeeded = False
                except Exception as error:
                    succeeded = False
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {error}"
                    )

    if not found:
        logger.error(f"Unknown plugin '{plugin}'")

    return found and succeeded


def _report_succeeded(result, filename, plugin):
    succeeded = True
    for report in (result, *(result.output_reports or [])):
        if report.last_error or report.num_errors:
            succeeded = False
            error = report.last_error or f"{report.num_errors} error(s) reported"
            logger.error(f"file: '{filename}' with parser: '{plugin}' error: {error}")
    return succeeded


def parse_params(params) -> dict[str, str | None]:
    if not params:
        return {}

    json_data = json.loads(params)
    param_dict = {}
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            param_dict[key] = str(value)

    return param_dict
