"""CLI wrapper for ordinary artifacts collected from one computer."""

import argparse
import datetime
import logging
import re
import sys
from dataclasses import asdict
from typing import Any

from .archive_runner import execute_prepared_runs, write_report_and_cleanup
from .logging import init_logger
from .run_preparation import prepare_folder_runs

logger = logging.getLogger(__name__)


def parse_folder(
    configuration: str,
    folder: str,
    global_vars: dict[str, str],
    computer_name: str | None,
    command_line: str,
) -> dict[str, Any]:
    started_at = datetime.datetime.now(datetime.timezone.utc)
    prepared = prepare_folder_runs(
        configuration,
        folder,
        computer_name,
        global_vars,
        started_at=started_at,
    )
    init_logger(configuration)
    for error in prepared.errors:
        if error.startswith("No files matched"):
            logger.warning(error)

    report = execute_prepared_runs(prepared, command_line, started_at.isoformat())
    report_data = asdict(report)
    report_data["source_folder"] = prepared.source_folder
    report_data["run_id"] = prepared.run_id
    safe_computer = re.sub(r"[^A-Za-z0-9._-]", "_", prepared.computer)
    report_name = f"report_{safe_computer}_{prepared.run_id}.json"
    write_report_and_cleanup(report_data, prepared, report_name)
    return report_data


def handle_folder(args: argparse.Namespace) -> None:
    global_vars = {"case": str(args.case)} if args.case else {}
    try:
        report = parse_folder(
            args.configuration,
            args.folder,
            global_vars,
            args.computer_name,
            " ".join(sys.argv),
        )
    except Exception as error:
        logger.error("%s", error)
        raise SystemExit(1) from None
    if report["extract_errors"] or report["parsing_errors"]:
        raise SystemExit(1)
