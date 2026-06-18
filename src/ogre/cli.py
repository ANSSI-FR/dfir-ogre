"""
Command line interface for DFIR‑OGRE.
"""
from ogre.logging import init_logger

import argparse
import datetime
import importlib
import json
import multiprocessing
import os
import shutil
import sys
import logging

import xml.etree.ElementTree as ET

from dfir_ogre_common import (
    BatchEntry,
    Metadata,
    OgrePlugin,
    OgreBatchedPlugin,
    OutputConfiguration,
    RunConfiguration,
)
from pathlib import Path
from tabulate import tabulate
import yaml

logger = logging.getLogger(__name__)

from .timeline import build_timeline
from .reports import ArchiveReport, DataclassJSONEncoder, ReportBuilder

from .commands import (
    OgreRunConfiguration,
    list_parsers,
    prepare_runs,
)
from . import process_runner
from .void_parser import VoidParser as VoidParser
from .logging import init_logger


def main() -> None:
    """
    Entry point for the Ogre CLI.

    It parses the command‑line arguments and dispatches to the appropriate
    sub‑command implementation:

    * ``list`` – List available parser plugins.
    * ``plugin`` – Run a single plugin against a file.
    * ``orc`` – Unpack an ORC archive and run the configured parsers.
    * ``timeline`` – Same as ``orc`` but generates a a unique timeline CSV file.
    """



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
    _ =  orc.add_argument(
       "--configuration", required=True, help="the ogre yaml configuration file"
    )
    _ =  orc.add_argument(
        "--archive",
        required=True,
        help="either: a json String, a list of coma separated archive files or an orc outcome.json file",
    )
    _ = orc.add_argument("--case", default="default_case", help="The case name")
    _ = orc.add_argument(
        "--password",
        help="Optional archive password",
    )
    # plugin parser
    run = sub_parser.add_parser("plugin", help="Execute a single OGRE parser (plugin) against a provided file.")
    _ = run.add_argument( "--filename", required=True, help="Path to the input file that the parser will process.")
    _ = run.add_argument(
        "--plugin_config",
        required=True,
        help="Path to the XML file that describes the plugin configuration. ",
    )
    _ = run.add_argument("--computer_name", required=True, help="Identifier of the machine where the input file comes from. This value is stored in the output metadata.")
    _ = run.add_argument("--output_folder", required=True, help="Destination directory where output will be written.")
    _ = run.add_argument(
        "--output_format", help="the output format: jsonl, csv, normalized_jsonl, normalized_csv"
    )
    _ = run.add_argument(
        "--output_date_format", help="the output format: jsonl, csv, normalized_jsonl, normalized_csv"
    )
    _ = run.add_argument(
        "--params", help="a json key value pair object that defines additional parameters that can be required by a plugin. Example: --params '{\"test\":1}'"
    )
    _ = run.add_argument("--timeline", action="store_true", help="When ``True`` add timeline informations to the output.")
    _ = run.add_argument(
        "--include_empty", action="store_true", help="When ``True`` empty fields are retained in the output."
    )
    _ = run.add_argument(
        "--library", help="defines a python library that contains custom parsers"
    )

    run.set_defaults(func=run_plugin)

    # timeline
    timeline = sub_parser.add_parser(
        "timeline", help="Run a list of parser against files provided in an Orc archive"
    )

    _ = timeline.add_argument(
        "--timeline_folder", required=True, help="where to put the timeline"
    )
    _ = timeline.add_argument(
        "--archive",
        required=True,
        help="either: a json String, a list of coma separated archive files or an orc outcome.json file",
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

    # parse the provided arguments and launch function
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
        print("timeline_folder cannot be empty" )
        return
    path = Path(timeline_folder)
    path.mkdir(parents=True, exist_ok=True)

    with Path( args.configuration).open("r") as f:
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
    build_timeline(data_folder,timeline_file,tmp_database_folder)

    shutil.rmtree(tmp_folder, ignore_errors=True)
    shutil.rmtree(data_folder, ignore_errors=True)

def parse_archive(
    configuration: str,
    archive: str,
    global_vars: dict[str, str],
    password: str| None,
    command_line: str,
) -> ArchiveReport:
    """
       Unpack an ORC archive and run the configured parsers.

       This is the core routine used by both the ``orc`` and ``timeline``
       sub‑commands.  It prepares the runs, executes them, collects results, and writes a JSON report.

       Parameters
       ----------
       configuration :
           Path to the YAML configuration file describing parsers and output
           locations.
       archive :
           Either a JSON string, a comma‑separated list of archive file paths,
           or a path to an ``outcome.json`` file produced by a previous run.
       case :
           Optional case identifier used for variable interpolation in the config.
       password :
           Optional password for encrypted archives.
       command_line :
           Full command line that invoked the CLI – stored in the report for
           reproducibility.
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
    for errors in prepared_runs.errors:
        logger.error(f"{errors}")
        report_builder.add_extract_error(errors)

    manager = multiprocessing.Manager()
    for run_configuration in prepared_runs.runs.map.values():
        if run_configuration.batch:
            try:
                logger.info(f"Running a batch of {len(run_configuration.batch_entries)} files with parser '{run_configuration.parser}', for mapping label '{run_configuration.mapping_label}' ")
                result = process_runner.run_batch_parser_with_timeout(
                    run_configuration, manager
                )
                report_builder.add_result(result, f"A batch of {len(run_configuration.batch_entries)} files")

            except Exception as e:
                error = f"An error occurred while parsing a batch of {len(run_configuration.batch_entries)} with parser: '{run_configuration.parser}'  for mapping label '{run_configuration.mapping_label}' error: {e}"
                logger.error(error)
                report_builder.add_parsing_error(error)
        else:
            for batch_entry in run_configuration.batch_entries:
                try:
                    logger.info(f"Running '{run_configuration.parser}', on file '{batch_entry.file}' ")
                    result = process_runner.run_parser_with_timeout(
                        batch_entry, run_configuration, manager
                    )
                    report_builder.add_result(result, batch_entry.file)

                except Exception as e:
                    error = f"An error occurred while parsing file '{batch_entry.file}' with parser: '{run_configuration.parser}' from module: '{run_configuration.module}' error: {e}"
                    logger.error(error)
                    report_builder.add_parsing_error(error)

    archive_report = report_builder.get_report()
    json_str = json.dumps(archive_report, cls=DataclassJSONEncoder)
    report_name = f"report_{prepared_runs.computer}_{prepared_runs.orc_id}.json"

    os.makedirs(prepared_runs.report_folder, exist_ok=True)
    report_file = os.path.join(prepared_runs.report_folder, report_name)
    logger.info(f"Writing report: {report_file}")
    with open(report_file, "w") as f:
        _ = f.write(json_str)

    logger.info(f"Deleting temporary data: {prepared_runs.tmp_folder}")
    shutil.rmtree(prepared_runs.tmp_folder, ignore_errors=True)

    return archive_report

def run_plugin(
    args,
):
    """
    Execute a single OGRE parser (plugin) against a provided file.

    Parameters
    ----------
    args : argparse.Namespace
        The namespace generated by ``argparse`` for the ``plugin`` sub‑command.
        The following attributes are expected:

        - ``filename`` (str): Path to the input file that the parser will process.
        - ``plugin_config`` (str): Path to the XML file that describes the plugin
            configuration.
        - ``computer_name`` (str): Identifier of the machine where the input file comes from;
            This value is stored in the output metadata.
        - ``output_folder`` (str): Destination directory where output will be written.
        - ``output_format`` (str): The output format: jsonl, csv, normalized_jsonl, normalized_csv
        - ``output_date_format`` (str): The output date format
        - ``timeline`` (bool): When ``True`` add timeline informations to the
            output.
        - ``include_empty`` (bool): When ``True`` empty fields are retained in
            the output.
        - ``library`` (str): Optional. Defines a python library that contains custom parsers


    """
    init_logger()

    output_name = Path(args.filename).stem

    # import the plugin modules
    importlib.import_module("dfir_ogre_plugin_windows")
    if  args.library:
      importlib.import_module(args.library)

    format =  "jsonl"
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

    # create element tree object
    tree = ET.parse(plugin_file)
    root = tree.getroot()
    plugin = root.attrib.get("parser")
    is_batch = root.attrib.get("batch", None)

    params = parse_params(args.params)

    runconfig = RunConfiguration([rust_output], False, params)
    metadata =  Metadata(args.computer_name)

    metadata.archive_filename = args.filename

    found = False
    # process batched plugins
    # dfir-ogre plugin --filename ../dfir-ogre-plugin/tests/data/lnk/desktop.lnk.data --plugin_config ../dfir-ogre-plugin/configuration/lnk_batched.xml  --computer_name test --output_folder .tmp
    if is_batch:
        for parser in OgreBatchedPlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        [BatchEntry(args.filename,runconfig, Metadata("test"))], plugin_file
                    )

                    if result.last_error:
                        logger.error(
                            f"file: '{args.filename}' with parser: '{plugin}' error: {result.last_error}"
                        )
                except Exception as e:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {e}"
                    )


    # process batched plugins
    else:
        for parser in OgrePlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        args.filename, plugin_file, runconfig, metadata
                    )

                    if result.last_error:
                        logger.error(
                            f"file: '{args.filename}' with parser: '{plugin}' error: {result.last_error}"
                        )
                except Exception as e:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {e}"
                    )

    if not found:
        logger.error(f"Unknown plugin '{plugin}'")

def parse_params(params)-> dict[str,str|None]:
    """
    Parse a JSON string supplied on the command line into a dictionary.

    The CLI accepts a ``--params`` option that contains a JSON object where each
    key/value pair represents a plugin‑specific parameter.  This helper converts
    that string into a ``dict`` with string values (or ``None`` when a value is
    null).

    Parameters
    ----------
    params :
        JSON‑encoded string passed to ``--params``.  If ``None`` or an empty
        string is supplied, an empty dictionary is returned.

    Returns
    -------
    dict
        Mapping from parameter names to their stringified values.
    """
    if not params:
        return {}

    json_data = json.loads(params)
    param_dict = {}
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            param_dict[key] = str(value)

    return param_dict
