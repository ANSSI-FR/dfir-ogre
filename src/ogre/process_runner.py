import datetime
import logging
import multiprocessing
from multiprocessing.managers import ListProxy, SyncManager
from typing import Callable

from dfir_ogre_common import BatchEntry

from .commands import (
    OgreRunConfiguration,
    RunResult,
    metadata_to_dict,
    run_batch_parser,
    run_parser,
)

logger = logging.getLogger(__name__)


def run_parser_with_timeout(
    batch_entry: BatchEntry,
    config: OgreRunConfiguration,
    manager: SyncManager,
) -> RunResult:
    return _run_with_timeout(
        run_parser_command,
        (batch_entry, config),
        config.timeout,
        manager,
    )


def run_batch_parser_with_timeout(
    config: OgreRunConfiguration,
    manager: SyncManager,
) -> RunResult:
    return _run_with_timeout(
        run_batch_parser_command,
        (config,),
        config.timeout,
        manager,
    )


def _run_with_timeout(
    target: Callable[..., None],
    args: tuple,
    timeout: int,
    manager: SyncManager,
) -> RunResult:
    result = manager.list()
    process = multiprocessing.Process(target=target, args=(*args, result))
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join(1)
        if not process.is_alive():
            process.close()
        raise Exception(f"parsing timed out, could not finish in {timeout} seconds")
    if len(result) == 0:
        raise Exception("The parsing process crashed and did not produce a report")

    return result.pop()


def run_parser_command(
    batch_entry: BatchEntry,
    config: OgreRunConfiguration,
    result: ListProxy,
):
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_parser(batch_entry, config))
    except Exception as error:
        message = f"A critical error occurred while parsing file '{config.batch_entries}' with parser: '{config.parser}' from module: '{config.module}' error: {error}"
        logger.error(message)

        result.append(
            RunResult(
                config.mapping_label,
                1,
                message,
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


def run_batch_parser_command(config: OgreRunConfiguration, result: ListProxy):
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_batch_parser(config))
    except Exception as error:
        message = f"A critical error occurred while parsing file '{config.batch_entries}' with parser: '{config.parser}' from module: '{config.module}' error: {error}"
        logger.error(message)

        result.append(
            RunResult(
                config.mapping_label,
                1,
                message,
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
