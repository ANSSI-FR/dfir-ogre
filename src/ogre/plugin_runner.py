import importlib
import json
import logging
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


def run_plugin(args):
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
