"""
Command line interface for DFIR‑OGRE.
"""

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
from dataclasses import asdict, dataclass, is_dataclass
from multiprocessing.managers import ListProxy, SyncManager

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
from typing_extensions import override
import yaml

logger = logging.getLogger(__name__)

from .timeline import build_timeline

from .commands import (
    OgreRunConfiguration,
    RunResult,
    list_parsers,
    metadata_to_dict,
    prepare_runs,
    run_batch_parser,
    run_parser,
)
from .void_parser import VoidParser as VoidParser

def init_logger():
    """
    Initialise the root logger for the CLI.

    The logger is configured with a simple ``INFO``‑level format and
    suppresses overly‑verbose messages from the ``evtx`` library, which
    can to emit a large amount information.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    # evtx: disable logs up to ERROR (to much noise)
    logging.getLogger("evtx").setLevel(logging.ERROR)


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

    init_logger()

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
) -> 'ArchiveReport':
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
                result = run_batch_parser_with_timeout(run_configuration, manager)
                report_builder.add_result(result, f"A batch of {len(run_configuration.batch_entries)} files")

            except Exception as e:
                error = f"An error occurred while parsing a batch of {len(run_configuration.batch_entries)} with parser: '{run_configuration.parser}'  for mapping label '{run_configuration.mapping_label}' error: {e}"
                logger.error(error)
                report_builder.add_parsing_error(error)
        else:
            for batch_entry in run_configuration.batch_entries:
                try:
                    logger.info(f"Running '{run_configuration.parser}', on file '{batch_entry.file}' ")
                    result = run_parser_with_timeout(batch_entry,run_configuration, manager)
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

    for extract_folder in prepared_runs.extract_folders:
        shutil.rmtree(extract_folder, ignore_errors=True)

    return archive_report

def run_parser_with_timeout(batch_entry: BatchEntry,config: OgreRunConfiguration, manager: SyncManager) -> RunResult:
    """
    Execute a parser in a separate process with a timeout.

    The child process places its result into a ``multiprocessing`` manager list.
    If the parser does not finish within ``config.timeout`` seconds, the
    process is terminated (first gently, then forcefully) and an exception is
    raised.

    Parameters
    ----------
    batch_entry :
        The file entry to be processed.
    config :
        Run‑time configuration describing the parser, timeout, output settings,
        etc.
    manager :
        A :class:`multiprocessing.managers.SyncManager` providing a shared
        list for inter‑process communication.
    """
    result = manager.list()
    p = multiprocessing.Process(target=run_parser_command, args=(batch_entry,config, result))
    p.start()
    p.join(config.timeout)
    if p.is_alive():
        # try to gently close the process
        p.close()
        p.join(1)
        if p.is_alive():
            # less nice
            p.terminate()
            p.join(1)
            if p.is_alive():
                # brutal
                p.kill()
                p.join(1)
        raise Exception(
            f"parsing timed out, could not finish in {config.timeout} seconds"
        )
    if len(result) == 0:
        raise Exception("The parsing process crashed and did not produce a report")

    return result.pop()

def run_batch_parser_with_timeout( config: OgreRunConfiguration, manager: SyncManager) -> RunResult:
    """
    Execute a *batched* parser in a separate process with a timeout.

    This mirrors :func:`run_parser_with_timeout` but uses the batch‑oriented
    command implementation.

    Parameters
    ----------
    config :
        Configuration for the batched parser run.
    manager :
        Manager providing a shared list for the child process to return its
        :class:`RunResult`.
    """
    result = manager.list()
    p = multiprocessing.Process(target=run_batch_parser_command, args=( config, result))
    p.start()
    p.join(config.timeout)
    if p.is_alive():
        # try to gently close the process
        p.close()
        p.join(1)
        if p.is_alive():
            # less nice
            p.terminate()
            p.join(1)
            if p.is_alive():
                # brutal
                p.kill()
                p.join(1)
        raise Exception(
            f"parsing timed out, could not finish in {config.timeout} seconds"
        )
    if len(result) == 0:
        raise Exception("The parsing process crashed and did not produce a report")

    return result.pop()

def run_parser_command(batch_entry: BatchEntry,config: OgreRunConfiguration, result: ListProxy):
    """
    Wrapper that invokes :func:`ogre.commands.run_parser` and stores the result.

    All exceptions are caught so that the parent process can continue
    processing other files.

    Parameters
    ----------
    batch_entry :
        Information about the file to be parsed.
    config :
        The run configuration for this parser.
    result :
        A ``multiprocessing`` manager list that the child process appends its
        :class:`RunResult` (or an error placeholder) to.
    """
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_parser(batch_entry, config))
    except Exception as e:
        error = f"A critical error occurred while parsing file '{config.batch_entries}' with parser: '{config.parser}' from module: '{config.module}' error: {e}"
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

def run_batch_parser_command( config: OgreRunConfiguration, result: ListProxy):
    """
    Wrapper that invokes :func:`ogre.commands.run_parser` and stores the result.

    All exceptions are caught so that the parent process can continue processing
    other files.
    """
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_batch_parser(config))
    except Exception as e:
        error = f"A critical error occurred while parsing file '{config.batch_entries}' with parser: '{config.parser}' from module: '{config.module}' error: {e}"
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
        - ``qualifiers`` (bool): When ``True`` field names are suffixed field's qualifier
            if any. eg: ``field_name:qualifier``
        - ``include_empty`` (bool): When ``True`` empty fields are retained in
            the output.
        - ``library`` (str): Optional. Defines a python library that contains custom parsers


    """


    output_name = Path(args.filename).stem

    # import the plugin modules
    importlib.import_module("dfir_ogre_plugin")
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
        args.qualifiers,
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

@dataclass
class ParserResult:
    """Aggregated statistics for a single parser across many files."""

    parser: str
    runs: int
    rows: int
    time: float
    errors: list[str]


@dataclass
class ArchiveReport:
    """JSON‑serialisable report for an ORC processing run."""

    timestamp: str
    command_line: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    summary: list[ParserResult]
    run_results: list[RunResult]


class ReportBuilder:
    timestamp: str
    command_line: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    run_results: list[RunResult]
    summary_builder: dict[str, ParserResult]
    """
    Helper class that incrementally builds an :class:`ArchiveReport`.

    It collects extraction errors, parsing errors, per‑parser statistics, and
    individual`RunResult` objects.  When all processing is complete,
    the `get_report` method returns a fully populated dataclass ready for JSON
    serialisation.
    """

    def __init__(
        self,
        timestamp: str,
        command_line: str,
        computer: str,
        orc_id: str,
        output_folder: str,
    ):
        self.timestamp = timestamp
        self.command_line = command_line
        self.computer = computer
        self.orc_id = orc_id
        self.output_folder = output_folder
        self.extract_errors = []
        self.parsing_errors = []
        self.run_results = []
        self.summary_builder = {}

    def add_extract_error(self, error: str):
        self.extract_errors.append(error)

    def add_parsing_error(self, error: str):
        self.parsing_errors.append(error)

    def add_result(self, result: RunResult, file):
        self.run_results.append(result)

        parser_result = self.summary_builder.get(result.mapping_label, None)
        if not parser_result:
            parser_result = ParserResult(result.mapping_label, 0, 0, 0.0, [])
        parser_result.runs += 1
        parser_result.rows += result.rows
        parser_result.time += result.time_s

        if result.last_error:
            error = f"{result.num_errors} error(s) occurred while parsing data: '{result.mapping_label}', file: '{file}', parser: '{result.parser}', last error: {result.last_error}"
            logger.error(error)
            parser_result.errors.append(error)
            self.parsing_errors.append(error)

        self.summary_builder[result.mapping_label] = parser_result

    def get_report(self) -> ArchiveReport:
        summary = []
        for val in self.summary_builder.values():
            summary.append(val)
        summary.sort(key=lambda x: x.parser)

        return ArchiveReport(
            self.timestamp,
            self.command_line,
            self.computer,
            self.orc_id,
            self.output_folder,
            self.extract_errors,
            self.parsing_errors,
            summary,
            self.run_results,
        )


class DataclassJSONEncoder(json.JSONEncoder):
    """JSON encoder capable of serialising dataclass instances."""
    @override
    def default(self, o):
        if is_dataclass(o):
            return asdict(o)  # ignore  # pyright: ignore[reportArgumentType]
        return super().default(o)
