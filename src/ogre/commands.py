import yaml
from dfir_ogre_common import OgrePlugin, PluginDescription

from .configuration import build_configuration
from .parser_execution import run_batch_parser, run_parser
from .parser_results import FileStat, OutputStat, RunResult, metadata_to_dict
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
