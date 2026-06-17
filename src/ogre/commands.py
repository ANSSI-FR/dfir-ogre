import copy
import importlib
import os
import time
import dateutil.parser

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


import yaml
from dfir_ogre_common import BatchEntry,Metadata, OgreBatchedPlugin, OgrePlugin, PluginDescription, RunConfiguration

from .configuration import Configuration, build_configuration
from .dfir_orc_unpack import load_archive_metadata, unpack_dfir_orc
from .run_preparation import (
    OgreRunConfiguration,
    PrepareRunResult,
    PluginDefinition,
    RunConfigGrouper,
    RunPreparationContext,
    clear_plugin_parser_cache,
    load_config,
    load_plugin_parser,
    load_plugins,
    prepare_runs,
)

CASE_PARAM = "case"
RunConfigMap = RunConfigGrouper


def list_parsers(
    conf_file: str, global_vars: dict[str, str]
) -> list[PluginDescription]:
    """
    List all available parsers based on a YAML configuration file.

    This function:
    1. Loads plugin prefixes from the specified YAML config file.
    2. Registers plugins via `_load_plugins` using the prefix defined in the configuration.
    3. Discovers all `OgrePlugin` subclasses to collect their descriptions.

    Parameters:
        conf_file (str): Path to the YAML configuration file specifying plugin prefixes.

    Returns:
        List[PluginDescription]: A list of plugin descriptions, each representing a parser's metadata.

    Raises:
        KeyError: If two plugins define the same command name.
    """

    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_vars)
    load_plugins(config.plugin_prefixes)

    parser_dict = {}
    descriptions = []
    for parser in OgrePlugin.__subclasses__():
        module_name = parser.__module__
        parser_descr = parser().description()
        entry_module = parser_dict.get(parser_descr.get_command())
        if entry_module:
            raise KeyError(
                f"Parser: '{parser_descr.get_command()}' for class: {parser.__class__} module: {module_name} is already defined in module: {entry_module}"
            )
        else:
            parser_dict[parser_descr.get_command()] = module_name
            descriptions.append(parser_descr)

    return descriptions


@dataclass
class FileStat:
    file_name: str
    num_rows: int
    output_type: str
    format: str
    date_format: str
    with_timeline: bool
    with_qualifiers: bool
    include_empty: bool


@dataclass
class OutputStat:
    last_error: str | None
    file_stats: list[FileStat]


@dataclass
class RunResult:
    mapping_label: str
    num_errors: int
    last_error: str | None
    rows: int
    time_s: float
    row_sec: float
    parser: str
    module: str
    start_date: str
    metadata: dict[str, str | None]
    output: list[OutputStat]


def run_parser(entry:BatchEntry, config: OgreRunConfiguration) -> RunResult:
    """
    Execute a parser plugin with the provided configuration.

    1. Imports the specified module
    2. Searches for a matching parser in OgrePlugin subclasses
    3. Executes the parser's `parse` method
    4. Collects output results and error information
    5. Measures execution duration

    Parameters:
        config (OgreRunConfiguration): Configuration object containing:
            - module: Module name where the parser is defined
            - parser: Identifier for the parser plugin to execute
            - file: Input file path
            - config: RunConfiguration parameters
            - metadata: Metadata for the run

    Returns:
        RunResult: Contains:
            - Start time of the run
            - Duration in seconds
            - Module/parser identifiers
            - Output statistics (file names and line counts)
            - Error details if encountered

    Raises:
        TypeError: If the specified parser is not found in registered plugins
    """
    _ = importlib.import_module(config.module)
    found = False
    start_date = datetime.now(timezone.utc).astimezone().isoformat()

    run_result = RunResult(
        config.mapping_label,
        0,
        None,
        0,
        0,
        0,
        config.parser,
        config.module,
        start_date,
        metadata_to_dict(entry.metadata),
        [],
    )

    for parser in OgrePlugin.__subclasses__():
        p = parser()
        if p.description().get_command() == config.parser:
            start = time.time()
            try:
                report = p.parse(
                    entry.file, config.plugin_file, entry.run_config, entry.metadata
                )
                run_result.last_error = report.last_error
                run_result.num_errors = report.num_errors
                for out_report in report.output_reports:
                    output_stat = OutputStat(out_report.last_error, [])
                    for fr in out_report.file_reports:
                        output_stat.file_stats.append(
                            FileStat(
                                fr.file_name,
                                fr.num_lines,
                                fr.output_type,
                                fr.format,
                                fr.date_format,
                                fr.with_timeline,
                                fr.with_qualifiers,
                                fr.include_empty,
                            )
                        )
                    run_result.output.append(output_stat)

            except Exception as e:
                run_result.last_error = f"{e}"

            end = time.time()
            found = True

            run_result.time_s = end - start
            break

    if not found:
        raise TypeError(f"parser {config.parser} not found")
    else:
        for stat in run_result.output:
            for file_stat in stat.file_stats:
                run_result.rows += file_stat.num_rows
        run_result.row_sec = round(run_result.rows / run_result.time_s, 0)
        run_result.time_s = round(run_result.time_s, 3)
        return run_result

def run_batch_parser(config: OgreRunConfiguration) -> RunResult:
    """
    Execute a parser plugin in batch mode with the provided configuration.

    """
    importlib.import_module(config.module)
    found = False
    start_date = datetime.now(timezone.utc).astimezone().isoformat()

    run_result = RunResult(
        config.mapping_label,
        0,
        None,
        0,
        0,
        0,
        config.parser,
        config.module,
        start_date,
        {},
        [],
    )

    for parser in OgreBatchedPlugin.__subclasses__():
        p = parser()
        if p.description().get_command() == config.parser:
            start = time.time()
            try:
                report = p.parse(
                    config.batch_entries, config.plugin_file
                )
                run_result.last_error = report.last_error
                run_result.num_errors = report.num_errors
                for out_report in report.output_reports:
                    output_stat = OutputStat(out_report.last_error, [])
                    for fr in out_report.file_reports:
                        output_stat.file_stats.append(
                            FileStat(
                                fr.file_name,
                                fr.num_lines,
                                fr.output_type,
                                fr.format,
                                fr.date_format,
                                fr.with_timeline,
                                fr.with_qualifiers,
                                fr.include_empty,
                            )
                        )
                    run_result.output.append(output_stat)

            except Exception as e:
                run_result.last_error = f"{e}"

            end = time.time()
            found = True

            run_result.time_s = end - start
            break

    if not found:
        raise TypeError(f"parser {config.parser} not found")
    else:
        for stat in run_result.output:
            for file_stat in stat.file_stats:
                run_result.rows += file_stat.num_rows
        run_result.row_sec = round(run_result.rows / run_result.time_s, 0)
        run_result.time_s = round(run_result.time_s, 3)
        return run_result

def metadata_to_dict(metadata: Metadata)->dict:
    # transform rust metadata into a dict to be able to serialize it in Json
    meta_dict = {}
    meta_dict["computer"] = metadata.computer

    if metadata.orc_id:
        meta_dict["orc_id"] = metadata.orc_id

    if metadata.folder:
        meta_dict["folder"] = metadata.folder

    if metadata.archive:
        meta_dict["archive"] = metadata.archive

    if metadata.subarchive:
        meta_dict["subarchive"] = metadata.subarchive

    if metadata.orc_id:
        meta_dict["orc_id"] = metadata.orc_id

    if metadata.archive_filename:
        meta_dict["archive_filename"] = metadata.archive_filename

    if metadata.original_filename:
        meta_dict["original_filename"] = metadata.original_filename

    if metadata.vss:
        meta_dict["vss"] = metadata.vss

    if metadata.creation_date:
        meta_dict["creation_date"] = metadata.creation_date.isoformat()

    if metadata.modif_date:
        meta_dict["modif_date"] = metadata.modif_date.isoformat()

    return meta_dict
