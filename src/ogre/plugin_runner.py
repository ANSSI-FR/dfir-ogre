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
    process = multiprocessing.Process(target=_run_plugin_child, args=(args,))
    process.start()
    try:
        process.join(timeout)
        if process.is_alive():
            _terminate_process(process)
            logger.error(f"parsing timed out, could not finish in {timeout} seconds")
        else:
            if process.exitcode not in (0, None):
                logger.error(f"The parsing process crashed with exit code {process.exitcode}")
            _close_process(process)
    except KeyboardInterrupt:
        _terminate_process(process)
        raise


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
        _run_plugin_direct(args)
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
        output_name,
        args.output_folder,
        "file",
        format,
        date_format,
        args.timeline,
        args.include_empty,
        {},
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
    if is_batch:
        for parser in OgreBatchedPlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        [BatchEntry(args.filename, runconfig, Metadata("test"))],
                        plugin_file,
                    )

                    if result.last_error:
                        logger.error(
                            f"file: '{args.filename}' with parser: '{plugin}' error: {result.last_error}"
                        )
                except Exception as error:
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

                    if result.last_error:
                        logger.error(
                            f"file: '{args.filename}' with parser: '{plugin}' error: {result.last_error}"
                        )
                except Exception as error:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {error}"
                    )

    if not found:
        logger.error(f"Unknown plugin '{plugin}'")


def parse_params(params) -> dict[str, str | None]:
    if not params:
        return {}

    json_data = json.loads(params)
    param_dict = {}
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            param_dict[key] = str(value)

    return param_dict
