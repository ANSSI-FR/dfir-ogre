import importlib
import time

from datetime import datetime, timezone


import yaml
from dfir_ogre_common import (
    BatchEntry,
    OgreBatchedPlugin,
    OgrePlugin,
    PluginDescription,
)

from .configuration import build_configuration
from .parser_results import (
    FileStat,
    OutputStat,
    RunResult,
    apply_report_to_result,
    create_run_result,
    finalize_run_result,
    metadata_to_dict,
)
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

    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        metadata_to_dict(entry.metadata),
    )

    for parser in OgrePlugin.__subclasses__():
        p = parser()
        if p.description().get_command() == config.parser:
            start = time.time()
            try:
                report = p.parse(
                    entry.file, config.plugin_file, entry.run_config, entry.metadata
                )
                apply_report_to_result(run_result, report)

            except Exception as e:
                run_result.last_error = f"{e}"

            end = time.time()
            found = True

            run_result.time_s = end - start
            break

    if not found:
        raise TypeError(f"parser {config.parser} not found")
    else:
        return finalize_run_result(run_result, run_result.time_s)

def run_batch_parser(config: OgreRunConfiguration) -> RunResult:
    """
    Execute a parser plugin in batch mode with the provided configuration.

    """
    importlib.import_module(config.module)
    found = False
    start_date = datetime.now(timezone.utc).astimezone().isoformat()

    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        {},
    )

    for parser in OgreBatchedPlugin.__subclasses__():
        p = parser()
        if p.description().get_command() == config.parser:
            start = time.time()
            try:
                report = p.parse(
                    config.batch_entries, config.plugin_file
                )
                apply_report_to_result(run_result, report)

            except Exception as e:
                run_result.last_error = f"{e}"

            end = time.time()
            found = True

            run_result.time_s = end - start
            break

    if not found:
        raise TypeError(f"parser {config.parser} not found")
    else:
        return finalize_run_result(run_result, run_result.time_s)
