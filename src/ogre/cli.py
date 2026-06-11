"""
Command line interface for DFIR‑OGRE.
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

import yaml
from tabulate import tabulate

from .config.loader import list_parsers
from .logging import init_logger
from .runner import parse_archive, run_plugin
from .timeline import build_timeline

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ogre",
        description="The DFIR-OGRE command line interface",
    )
    sub_parser = parser.add_subparsers()

    # list available plugins
    list_parser = sub_parser.add_parser("list", help="List available plugins")
    list_parser.set_defaults(func=display_plugin_list)
    _ = list_parser.add_argument(
        "--configuration", required=True, help="The ogre yaml configuration file"
    )
    _ = list_parser.add_argument("--case", default="default_case", help="The case name")

    # Run a list of parser against files provided in an Orc archive
    orc = sub_parser.add_parser(
        "orc", help="Run a list of parser against files provided in an Orc archive"
    )
    orc.set_defaults(func=handle_orc_archive)
    _ = orc.add_argument("--configuration", required=True, help="the ogre yaml configuration file")
    _ = orc.add_argument(
        "--archive",
        required=True,
        help=(
            "either: a json String, a list of coma separated archive files "
            "or an orc outcome.json file"
        ),
    )
    _ = orc.add_argument("--case", default="default_case", help="The case name")
    _ = orc.add_argument(
        "--password",
        help="Optional archive password",
    )
    # plugin parser
    run = sub_parser.add_parser(
        "plugin", help="Execute a single OGRE parser (plugin) against a provided file."
    )
    _ = run.add_argument(
        "--filename", required=True, help="Path to the input file that the parser will process."
    )
    _ = run.add_argument(
        "--plugin_config",
        required=True,
        help="Path to the XML file that describes the plugin configuration. ",
    )
    _ = run.add_argument(
        "--computer_name",
        required=True,
        help=(
            "Identifier of the machine where the input file comes from. "
            "This value is stored in the output metadata."
        ),
    )
    _ = run.add_argument(
        "--output_folder", required=True, help="Destination directory where output will be written."
    )
    _ = run.add_argument(
        "--output_format", help="the output format: jsonl, csv, normalized_jsonl, normalized_csv"
    )
    _ = run.add_argument(
        "--output_date_format",
        help="the output format: jsonl, csv, normalized_jsonl, normalized_csv",
    )
    _ = run.add_argument(
        "--params",
        help=(
            "a json key value pair object that defines additional parameters "
            "that can be required by a plugin. Example: --params '{\"test\":1}'"
        ),
    )
    _ = run.add_argument(
        "--timeline",
        action="store_true",
        help="When ``True`` add timeline informations to the output.",
    )
    _ = run.add_argument(
        "--include_empty",
        action="store_true",
        help="When ``True`` empty fields are retained in the output.",
    )
    _ = run.add_argument("--library", help="defines a python library that contains custom parsers")

    run.set_defaults(func=run_plugin)

    # timeline
    timeline = sub_parser.add_parser(
        "timeline", help="Run a list of parser against files provided in an Orc archive"
    )

    _ = timeline.add_argument("--timeline_folder", required=True, help="where to put the timeline")
    _ = timeline.add_argument(
        "--archive",
        required=True,
        help=(
            "either: a json String, a list of coma separated archive files "
            "or an orc outcome.json file"
        ),
    )
    _ = timeline.add_argument(
        "--configuration", required=True, help="the ogre yaml configuration file"
    )
    _ = timeline.add_argument("--case", default="default_case", help="The case name")
    _ = timeline.add_argument(
        "--password",
        help="Optional archive password",
    )

    timeline.set_defaults(func=handle_timeline)

    return parser


def main() -> None:
    """
    Entry point for the Ogre CLI.

    It parses the command-line arguments and dispatches to the appropriate
    sub-command implementation.
    """
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


def display_plugin_list(args):
    """
    Print a formatted table of available parser plugins.

    Parameters
    ----------
    args : argparse.Namespace
        Must contain ``configuration`` (path to the YAML config) and an
        optional ``case`` identifier. The ``case`` value is made available to
        the configuration as a global variable for Jinja‑style templating.
    """
    init_logger()
    if args.case:
        global_vars = {"case": args.case}
    else:
        global_vars = {}
    unsorted = {}
    for c in list_parsers(args.configuration, global_vars):
        unsorted[c.get_command()] = c.get_description()

    sorted_command = dict(sorted(unsorted.items()))
    print(
        tabulate(
            sorted_command.items(),
            headers=["Command", "Description"],
            tablefmt="simple_grid",
        )
    )


def handle_orc_archive(args):
    """
    Process an ORC archive according to a configuration file.

    This function is the implementation behind the ``ogre orc`` sub‑command.
    It forwards the arguments to :func:`parse_archive`, which performs the
    extraction, runs the parsers, and writes a JSON report.

    Parameters
    ----------
    args : argparse.Namespace
        Expected attributes:
        ``configuration`` (path to YAML),
        ``archive`` (archive identifier),
        ``case`` (optional case name),
        ``password`` (optional password for encrypted archives).
    """
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


def handle_timeline(args):
    """
    Generate a timeline CSV from an ORC archive.

    The function extracts the archive, runs the parsers, then builds a CSV
    timeline file.

    Parameters
    ----------
    args : argparse.Namespace
        Must contain ``timeline_folder`` (output directory), ``configuration``,
        ``archive`` and optionally ``password``.
    """
    init_logger(args.configuration)
    timeline_folder = args.timeline_folder
    if not timeline_folder:
        print("timeline_folder cannot be empty")
        return
    path = Path(timeline_folder)
    path.mkdir(parents=True, exist_ok=True)

    with Path(args.configuration).open("r") as f:
        ogre_yaml = f.read()

    config_dict = yaml.safe_load(ogre_yaml)
    tmp_folder = config_dict["temp_folder"]
    Path(tmp_folder).mkdir(parents=True, exist_ok=True)

    data_folder = config_dict["output_folder"]
    Path(data_folder).mkdir(parents=True, exist_ok=True)

    global_vars = {"report_folder": str(timeline_folder)}
    if args.case:
        global_vars["case"] = str(args.case)

    report = parse_archive(
        args.configuration,
        args.archive,
        global_vars,
        args.password,
        " ".join(sys.argv),
    )

    timeline_file = os.path.join(timeline_folder, f"{report.computer}.timeline.csv")
    tmp_database_folder = os.path.join(tmp_folder, "tempdb")
    Path(tmp_database_folder).mkdir(parents=True, exist_ok=True)

    logger.info(f"Creating timeline from extracted artefacts: '{timeline_file}'")
    build_timeline(data_folder, timeline_file, tmp_database_folder)

    shutil.rmtree(tmp_folder, ignore_errors=True)
    shutil.rmtree(data_folder, ignore_errors=True)
