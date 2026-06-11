import re

import yaml
from dfir_ogre_common import PluginDescription

from ogre.plugins import PluginRegistry, build_plugin_registry

from .models import Configuration, build_configuration


def load_config(conf_file: str, global_var: dict[str, str]) -> tuple[Configuration, PluginRegistry]:
    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_var)
    plugin_registry = build_plugin_registry(config.plugin_prefixes)

    for mapping in config.mapping:
        if mapping.archive_file_pattern:
            try:
                _ = re.compile(mapping.archive_file_pattern, re.IGNORECASE)
            except Exception as e:
                raise Exception(
                    f"{e} in archive_file_pattern regex:'{mapping.archive_file_pattern}', "
                    f"mapping_label:'{mapping.mapping_label}'"
                ) from e

        if mapping.original_file_pattern:
            try:
                _ = re.compile(mapping.original_file_pattern, re.IGNORECASE)
            except Exception as e:
                raise Exception(
                    f"{e} in original_file_pattern regex:'{mapping.original_file_pattern}', "
                    f"mapping_label:'{mapping.mapping_label}'"
                ) from e

        for output_name in mapping.output:
            if output_name not in config.output:
                raise TypeError(
                    f"output '{output_name}' referenced by mapping_label:"
                    f"'{mapping.mapping_label}' is not defined"
                )

    return config, plugin_registry


def list_parsers(conf_file: str, global_vars: dict[str, str]) -> list[PluginDescription]:
    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_vars)
    plugin_registry = build_plugin_registry(config.plugin_prefixes)
    return plugin_registry.list_descriptions()
