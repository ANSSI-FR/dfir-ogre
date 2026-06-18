import importlib
import time
from datetime import datetime, timezone

from dfir_ogre_common import BatchEntry, OgreBatchedPlugin, OgrePlugin

from .parser_results import (
    RunResult,
    apply_report_to_result,
    create_run_result,
    finalize_run_result,
    metadata_to_dict,
)
from .run_preparation import OgreRunConfiguration


def _start_date() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _find_parser(parser_classes, command: str):
    for parser_class in parser_classes:
        parser = parser_class()
        if parser.description().get_command() == command:
            return parser
    return None


def run_parser(entry: BatchEntry, config: OgreRunConfiguration) -> RunResult:
    _ = importlib.import_module(config.module)
    start_date = _start_date()
    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        metadata_to_dict(entry.metadata),
    )

    parser = _find_parser(OgrePlugin.__subclasses__(), config.parser)
    if parser is None:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(
            entry.file,
            config.plugin_file,
            entry.run_config,
            entry.metadata,
        )
        apply_report_to_result(run_result, report)
    except Exception as error:
        run_result.last_error = f"{error}"
    end = time.time()

    return finalize_run_result(run_result, end - start)


def run_batch_parser(config: OgreRunConfiguration) -> RunResult:
    _ = importlib.import_module(config.module)
    start_date = _start_date()
    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        {},
    )

    parser = _find_parser(OgreBatchedPlugin.__subclasses__(), config.parser)
    if parser is None:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(config.batch_entries, config.plugin_file)
        apply_report_to_result(run_result, report)
    except Exception as error:
        run_result.last_error = f"{error}"
    end = time.time()

    return finalize_run_result(run_result, end - start)
