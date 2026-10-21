import importlib
import json
import logging
import multiprocessing
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from dfir_ogre_common import (
    BatchEntry,
    Metadata,
    OgreBatchedPlugin,
    OgrePlugin,
    RunConfiguration,
)

from .logging import init_logger
from .plugin_output import plan_plugin_output
from .plugin_publication import staged_output

logger = logging.getLogger(__name__)

PLUGIN_DEFAULT_TIMEOUT = 60


def run_plugin(args):
    init_logger()

    timeout = getattr(args, "timeout", PLUGIN_DEFAULT_TIMEOUT)
    failed = False
    workspace_name = f".ogre-plugin-{uuid4().hex}"
    process = multiprocessing.Process(
        target=_run_plugin_child, args=(args, workspace_name)
    )
    process.start()
    try:
        process.join(timeout)
        if process.is_alive():
            _terminate_process(process)
            logger.error(f"parsing timed out, could not finish in {timeout} seconds")
            failed = True
        else:
            if process.exitcode not in (0, None):
                logger.error(
                    f"The parsing process failed with exit code {process.exitcode}"
                )
                failed = True
            _close_process(process)
    except KeyboardInterrupt:
        _terminate_process(process)
        raise
    finally:
        # A terminated or crashed worker cannot execute its context cleanup.
        if hasattr(args, "output_folder"):
            shutil.rmtree(Path(args.output_folder) / workspace_name, ignore_errors=True)

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


def _run_plugin_child(args, workspace_name=None):
    try:
        if not _run_plugin_direct(args, workspace_name):
            raise SystemExit(1)
    except Exception as error:
        logger.error(f"A critical error occurred while running plugin: {error}")
        raise


def _run_plugin_direct(args, workspace_name=None):
    init_logger()

    importlib.import_module("dfir_ogre_plugin_windows")
    if args.library:
        importlib.import_module(args.library)

    plugin_file = args.plugin_config

    tree = ET.parse(plugin_file)
    root = tree.getroot()
    plugin = root.attrib.get("parser")
    is_batch = root.attrib.get("batch", None)

    base_class = OgreBatchedPlugin if is_batch else OgrePlugin
    parsers = [parser() for parser in base_class.__subclasses__()]
    parsers = [
        parser for parser in parsers if parser.description().get_command() == plugin
    ]
    if not parsers:
        logger.error(f"Unknown plugin '{plugin}'")
        return False
    if len(parsers) != 1:
        logger.error(f"Multiple parsers registered for '{plugin}'")
        return False

    try:
        if root.tag != "plugin":
            raise ValueError("The configuration root must be 'plugin'")
        params = parse_params(args.params)
        plan = plan_plugin_output(args, root, plugin)
    except Exception as error:
        logger.error(f"Invalid plugin output configuration: {error}")
        return False

    if getattr(args, "dry_run", False):
        print(json.dumps(plan.as_dict(plugin, args.filename), indent=2))
        return True

    metadata = Metadata(args.computer_name)

    metadata.archive_filename = args.filename

    parser_obj = parsers[0]
    try:
        logger.info(f"Running '{plugin}', on file '{args.filename}' ")
        with staged_output(plan.output, workspace_name) as output:
            runconfig = RunConfiguration([output], False, params)
            if is_batch:
                result = parser_obj.parse(
                    [BatchEntry(args.filename, runconfig, metadata)], plugin_file
                )
            else:
                result = parser_obj.parse(
                    args.filename, plugin_file, runconfig, metadata
                )
            succeeded = _report_succeeded(result, args.filename, plugin)
        return succeeded
    except Exception as error:
        logger.error(f"file: '{args.filename}' with parser: '{plugin}' error: {error}")
        return False


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
