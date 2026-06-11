import copy
import importlib
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import dateutil.parser
import yaml
from dfir_ogre_common import BatchEntry, Metadata, PluginDescription, RunConfiguration

from .archive_extraction import unpack_dfir_orc
from .archive_metadata import load_archive_metadata
from .configuration import Configuration, build_configuration
from .plugins import (
    PluginDefinition,
    find_batched_parser,
    find_parser,
    list_plugin_descriptions,
    load_plugin_parser,
)
from .plugins import (
    load_plugins as _load_plugins,
)
from .template_vars import TIMESTAMP_FORMAT, apply_dir_tree, replace_placeholders

CASE_PARAM = "case"


@dataclass
class OgreRunConfiguration:
    batch_entries: list[BatchEntry]
    plugin_file: str
    mapping_label: str
    module: str
    parser: str
    batch: bool
    timeout: int


class RunConfigMap:
    map: dict[str, OgreRunConfiguration]

    def __init__(self):
        self.map = {}

    def add_configuration(
        self,
        batch_entry: BatchEntry,
        plugin_file: str,
        mapping_label: str,
        module: str,
        parser: str,
        batch: bool,
        timeout: int,
    ):
        entry = self.map.get(plugin_file, None)
        if entry:
            entry.batch_entries.append(batch_entry)
        else:
            self.map[plugin_file] = OgreRunConfiguration(
                [batch_entry], plugin_file, mapping_label, module, parser, batch, timeout
            )


def load_config(
    conf_file: str, global_var: dict[str, str]
) -> tuple[Configuration, dict[str, "PluginDefinition"]]:
    """
    Load and validate a YAML configuration file. Ensures:
    1. All specified plugins are available via registered prefixes
    2. All referenced outputs exist in the configuration
    3. All regular expressions are valid

    The function:
    1. Loads YAML configuration
    2. Builds configuration object with global variable overrides
    3. Loads plugins from configured prefixes
    4. Validates all mappings in the configuration


    Parameters:
    - conf_file (str): Path to the YAML configuration file
    - global_var (Dict[str, str]): Global variables that override config parameters

    Returns:
    - Tuple[Configuration, Dict[str, str]]:
        (validated configuration object, dictionary of loaded plugins)

    Raises:
    - TypeError: If:
        - A required parser plugin is not loaded
        - An output reference is invalid/undefined
    """

    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_var)
    plugins = _load_plugins(config.plugin_prefixes)

    for map in config.mapping:
        if map.archive_file_pattern:
            try:
                _ = re.compile(map.archive_file_pattern, re.IGNORECASE)
            except Exception as e:
                raise Exception(
                    f"{e} in archive_file_pattern regex:'{map.archive_file_pattern}', "
                    f"mapping_label:'{map.mapping_label}'"
                ) from e

        if map.original_file_pattern:
            try:
                _ = re.compile(map.original_file_pattern, re.IGNORECASE)
            except Exception as e:
                raise Exception(
                    f"{e} in original_file_pattern regex:'{map.original_file_pattern}', "
                    f"mapping_label:'{map.mapping_label}'"
                ) from e
        for output_name in map.output:
            if output_name not in config.output:
                raise TypeError(
                    f"output '{output_name}' referenced by mapping_label:"
                    f"'{map.mapping_label}' is not defined"
                )

    return config, plugins


def list_parsers(conf_file: str, global_vars: dict[str, str]) -> list[PluginDescription]:
    """
    List all available parsers based on a YAML configuration file.

    This function:
    1. Loads plugin prefixes from the specified YAML config file.
    2. Registers plugins via `_load_plugins` using the prefix defined in the configuration.
    3. Discovers all `OgrePlugin` subclasses to collect their descriptions.

    Parameters:
        conf_file (str): Path to the YAML configuration file specifying plugin prefixes.

    Returns:
        List[PluginDescription]: Descriptions for discovered parser plugins.

    Raises:
        KeyError: If two plugins define the same command name.
    """

    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_vars)
    _load_plugins(config.plugin_prefixes)

    return list_plugin_descriptions()


@dataclass
class PrepareRunResult:
    archive: str
    runs: RunConfigMap
    errors: list[str]
    computer: str
    orc_id: str
    output_folder: str
    report_folder: str
    tmp_folder: str


def prepare_runs(
    conf_file: str,
    archive: str,
    password: str | None,
    global_var: dict[str, str] | None = None,
) -> PrepareRunResult:
    """
    Prepare and configure runs based on a configuration file.
    This function:
    1. Loads and validates the YAML configuration.
    2. Loads metadata from the main archive.
    3. For each archive:
        a. Copies the configuration to avoid modifying the original.
        b. Replaces wildcards in output paths and filenames.
        c. Unpacks the archive and collects mapping information.
        d. Processes each mapping to create run configurations.
        e. Builds metadata for the run, including archive, computer, and file details.
        f. Adds the configured run to the list.
    4. Returns the list of runs and any errors.

    Parameters:
    - conf_file (str): Path to the YAML configuration file.
    - archive (str): Name of the archive to be processed.
    - password (Optional[str]): Password for sub-archives, if necessary.
    - global_var (Dict[str, str]): Global variables that override config values.

    Returns:
    - PrepareRunResult: Configured runs and any errors encountered.

    """
    run_config_map = RunConfigMap()
    runtime_vars = dict(global_var or {})
    # Load and validate the configuration
    configuration, parsers = load_config(conf_file, runtime_vars)

    # Load metadata from the main archive
    orc_outcome = load_archive_metadata(archive)
    archives = orc_outcome.archives
    runtime_vars["computer_name"] = orc_outcome.computer_name
    runtime_vars["orc_id"] = orc_outcome.id
    runtime_vars["orc_start_date"] = orc_outcome.date.isoformat()

    errors = []

    # replace wildcards in configuration.report_folder
    timestamp = orc_outcome.date.strftime(TIMESTAMP_FORMAT)
    configuration.report_folder = replace_placeholders(
        configuration.report_folder,
        {"case": configuration.case, "timestamp": timestamp},
    )
    configuration.report_folder = apply_dir_tree(
        configuration.report_folder,
        orc_outcome.dir_tree,
        configuration.dir_tree,
    )

    for archive in archives:
        # Create a deep copy of the configuration to avoid modifying the original
        conf = copy.deepcopy(configuration)

        # Replace global wildcards in output configurations
        for output_conf in conf.output.values():
            archive_variables = {
                "output_folder": conf.output_folder,
                "archive_name": Path(archive).stem,
                "case": configuration.case,
                "timestamp": timestamp,
            }
            output_folder = replace_placeholders(
                output_conf.output_folder,
                archive_variables,
            )
            output_folder = apply_dir_tree(
                output_folder, orc_outcome.dir_tree, configuration.dir_tree
            )

            output_conf.output_folder = output_folder

            base_file_name = replace_placeholders(
                output_conf.base_file_name,
                archive_variables,
            )
            output_conf.base_file_name = base_file_name

        # Unpack the archive and get mapping information
        vmapping = unpack_dfir_orc(
            archive,
            password,
            conf.inner_archive_password,
            conf.mapping,
            conf.temp_folder,
        )

        # Collect any errors from unpacking
        errors = errors + vmapping.errors

        for v_map in vmapping.valid_mapping:
            mapping = v_map.mapping
            # replace wildcards in the plugin_file parameter
            plugin_file = replace_placeholders(
                mapping.plugin_file,
                {
                    "output_folder": conf.output_folder,
                    "archive_name": Path(archive).stem,
                    "case": configuration.case,
                    "plugin_folder": conf.plugin_folder,
                },
            )
            parser_definition = load_plugin_parser(plugin_file)

            # Get the module for the parser
            plugin_definition = parsers.get(parser_definition[0], None)
            if not plugin_definition:
                raise Exception(f"plugin '{parser_definition}' not found in the loaded plugins")

            # Prepare output configurations for this run
            output = [copy.deepcopy(conf.output[out_name]) for out_name in mapping.output]

            # Replace run-specific wildcards in output parameters
            for output_conf in output:
                run_variables = {
                    "mapping_label": mapping.mapping_label,
                    "parser": parser_definition[0],
                    "file_name": Path(v_map.file).stem,
                    "computer_name": orc_outcome.computer_name,
                }
                output_folder = replace_placeholders(
                    output_conf.output_folder,
                    run_variables,
                )
                output_conf.output_folder = output_folder

                base_file_name = replace_placeholders(
                    output_conf.base_file_name,
                    run_variables,
                )
                output_conf.base_file_name = base_file_name

            # Build metadata for this run
            metadata = Metadata(runtime_vars["computer_name"])

            # Extract folder and archive names from the path
            archive_abs_path = os.path.abspath(archive)
            folder = os.path.basename(os.path.dirname(archive_abs_path))
            archive_name = os.path.basename(archive)
            subarchive_name = Path(v_map.archive_name).stem

            metadata.folder = folder

            metadata.archive = archive_name
            if archive != subarchive_name and subarchive_name:
                metadata.subarchive = subarchive_name + ".7z"

            metadata.orc_start_date = orc_outcome.date
            metadata.orc_id = orc_outcome.id
            metadata.archive_filename = v_map.archive_file
            metadata.original_filename = v_map.original_file
            metadata.vss = v_map.vss

            if v_map.original_creation_date:
                metadata.creation_date = dateutil.parser.isoparse(
                    v_map.original_creation_date
                ).astimezone(timezone.utc)
            if v_map.original_modification_date:
                metadata.modif_date = dateutil.parser.isoparse(
                    v_map.original_modification_date
                ).astimezone(timezone.utc)

            # replace wildcards in the additional parameters
            additional_params: dict[str, str | None] = {}
            for key, value in mapping.params.items():
                if isinstance(value, str):
                    additional_params[key] = replace_placeholders(
                        value,
                        {
                            "output_folder": conf.output_folder,
                            "archive_name": Path(archive).stem,
                            "case": configuration.case,
                            "plugin_folder": conf.plugin_folder,
                        },
                    )
                else:
                    additional_params[key] = str(value)

            # Create the parser configuration for this run
            run_config = RunConfiguration(
                output,
                mapping.force_nake_case,
                additional_params,
            )
            # Get absolute path of the file to process
            abs_path = os.path.abspath(v_map.file)
            batch_entry = BatchEntry(abs_path, run_config, metadata)

            run_config_map.add_configuration(
                batch_entry,
                plugin_file,
                mapping.mapping_label,
                plugin_definition.module_name,
                parser_definition[0],
                parser_definition[1],
                mapping.timeout,
            )
            # Add the run configuration to the list

    # Return the final list of runs and any errors encountered
    return PrepareRunResult(
        archive,
        run_config_map,
        errors,
        orc_outcome.computer_name,
        orc_outcome.id,
        configuration.output_folder,
        configuration.report_folder,
        configuration.temp_folder,
    )


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


def run_parser(entry: BatchEntry, config: OgreRunConfiguration) -> RunResult:
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
    importlib.import_module(config.module)
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

    parser = find_parser(config.parser)
    if not parser:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(entry.file, config.plugin_file, entry.run_config, entry.metadata)
        run_result.last_error = report.last_error
        run_result.num_errors = report.num_errors
        _add_output_reports(run_result, report.output_reports)
    except Exception as e:
        run_result.last_error = f"{e}"
    run_result.time_s = time.time() - start

    return _finalize_run_result(run_result)


def run_batch_parser(config: OgreRunConfiguration) -> RunResult:
    """
    Execute a parser plugin in batch mode with the provided configuration.

    """
    importlib.import_module(config.module)
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

    parser = find_batched_parser(config.parser)
    if not parser:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(config.batch_entries, config.plugin_file)
        run_result.last_error = report.last_error
        run_result.num_errors = report.num_errors
        _add_output_reports(run_result, report.output_reports)
    except Exception as e:
        run_result.last_error = f"{e}"
    run_result.time_s = time.time() - start

    return _finalize_run_result(run_result)


def _add_output_reports(run_result: RunResult, output_reports) -> None:
    for out_report in output_reports:
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


def _finalize_run_result(run_result: RunResult) -> RunResult:
    for stat in run_result.output:
        for file_stat in stat.file_stats:
            run_result.rows += file_stat.num_rows

    if run_result.time_s > 0:
        run_result.row_sec = round(run_result.rows / run_result.time_s, 0)
    else:
        run_result.row_sec = 0
    run_result.time_s = round(run_result.time_s, 3)
    return run_result


def metadata_to_dict(metadata: Metadata) -> dict:
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
