import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from dfir_ogre_common import OutputConfiguration

DEFAULT_PLUGIN_NAME = "dfir_ogre_plugin"
DEFAULT_TIMEOUT = 3600


@dataclass
class Mapping:
    archive_file_pattern: str | None
    original_file_pattern: str | None
    plugin_file: str
    mapping_label: str
    skip_short_name: bool
    force_nake_case: bool
    timeout: int
    params: dict[str,Any]
    output: list[str]


@dataclass
class Configuration:
    plugin_prefixes: list[str]
    case: str
    dir_tree: str
    temp_folder: str
    output_folder: str
    plugin_folder: str
    report_folder: str
    force_snake_case: bool
    default_timeout: int
    inner_archive_password: str | None
    mapping: list[Mapping]
    output: dict[str, OutputConfiguration]


def load_mapping(dict: dict, default_timeout: int, force_nake_case: bool) -> Mapping:
    archive_file_pattern = dict.pop("archive_file_pattern", None)
    original_file_pattern = dict.pop("original_file_pattern", None)

    if not archive_file_pattern and not original_file_pattern:
        raise KeyError(
            f"Either 'archive_file_pattern' or 'original_file_pattern' must be defined: {dict}"
        )
    if archive_file_pattern and original_file_pattern:
        raise KeyError(
            f"Only one 'archive_file_pattern' or 'original_file_pattern' must be defined: {dict}"
        )
    force_nake_case = dict.pop("force_nake_case", force_nake_case)
    skip_short_name = dict.pop("skip_original_short_name", True)

    plugin_file = dict.pop("plugin_file", None)
    if not plugin_file:
        raise KeyError(f"'plugin_file' not found in mapping definition: {dict}")

    mapping_label = dict.pop("mapping_label", None)
    if not mapping_label:
        raise KeyError(f"'mapping_label' not found in mapping definition: {dict}")

    output = dict.pop("output", None)
    if not output:
        raise KeyError(f"'output' not found in mapping definition: {dict}")

    timeout = dict.pop("timeout", default_timeout)

    return Mapping(
        archive_file_pattern,
        original_file_pattern,
        plugin_file,
        mapping_label,
        skip_short_name,
        force_nake_case,
        timeout,
        dict,
        output,
    )


def build_configuration(config_dict: dict, global_var: dict[str, str]) -> Configuration:
    plugin_prefixes = config_dict.get("plugin_prefixes", [DEFAULT_PLUGIN_NAME])

    mappings_list = config_dict.get("mapping", [])
    case = load_variable("case", config_dict, global_var)
    if not case:
        raise TypeError("'case' must be defined")

    dir_tree = load_variable("dir_tree", config_dict, global_var)
    if not dir_tree:
        dir_tree = ""

    temp_folder = load_variable("temp_folder", config_dict, global_var)
    if not temp_folder:
        raise TypeError("'temp_folder' must be defined")
    temp_folder = temp_folder.replace("$case", case)
    path = Path(temp_folder)
    #add a random folder to the path to avoid conflicts when processing data in parallel
    path = path / str(uuid4())
    temp_folder = str(path)

    output_folder = load_variable("output_folder", config_dict, global_var)
    if not output_folder:
        raise TypeError("'output_folder' must be defined")
    output_folder = output_folder.replace("$case", case)

    plugin_folder = load_variable("plugin_folder", config_dict, global_var)
    if not plugin_folder:
        raise TypeError("'plugin_folder' must be defined")
    plugin_folder = plugin_folder.replace("$case", case)

    report_folder = load_variable("report_folder", config_dict, global_var)
    if not report_folder:
        report_folder = output_folder
    report_folder = report_folder.replace("$case", case)

    force_snake_case = config_dict.pop("force_snake_case", True)

    inner_archive_password = load_variable("inner_archive_password", config_dict, global_var)
    default_timeout = config_dict.pop("default_timeout", DEFAULT_TIMEOUT)

    mappings = [
        load_mapping(mapp, default_timeout, force_snake_case) for mapp in mappings_list
    ]

    output_map: dict[str, Any] = config_dict.get("output", {})
    output = {}
    for key, value in output_map.items():
        output[key] = load_output_configuration(value)

    return Configuration(
        plugin_prefixes,
        case,
        dir_tree,
        temp_folder,
        output_folder,
        plugin_folder,
        report_folder,
        force_snake_case,
        default_timeout,
        inner_archive_password,
        mappings,
        output,
    )


def load_output_configuration(config_dict: dict[str, Any]) -> OutputConfiguration:
    type = config_dict.pop("type", None)
    if not type:
        raise KeyError(f"'type' not found in mapping definition: {config_dict}")

    format = config_dict.pop("format", None)
    if not format:
        raise KeyError(f"'format' not found in mapping definition: {config_dict}")

    date_format = config_dict.pop("date_format", None)
    if not date_format:
        raise KeyError(f"'date_format' not found in mapping definition: {config_dict}")

    output_folder = config_dict.pop("output_folder", None)
    if not output_folder:
        raise KeyError(f"'output_folder' not found in mapping definition: {config_dict}")

    base_file_name = config_dict.pop("base_file_name", None)
    if not base_file_name:
        raise KeyError(f"'base_file_name' not found in mapping definition: {config_dict}")

    with_timeline: bool = config_dict.pop("with_timeline", False)
    with_qualifiers: bool = config_dict.pop("with_qualifiers", False)
    include_empty: bool = config_dict.pop("include_empty_field", False)
    string_dict: dict[str, str] = {}

    for key, value in config_dict.items():
        string_dict[key] = str(value)
    return OutputConfiguration(
        base_file_name,
        output_folder,
        type,
        format,
        date_format,
        with_timeline,
        with_qualifiers,
        include_empty,
        string_dict,
    )


def load_variable(name: str, config_dict: dict, global_var: dict[str, str]) -> str | None:
    """Load a variable with the following priority
    - search in the 'global_var'
    - search the env variable OGRE_ + upper_case(name)
    - search in the 'dict'
    """
    value = global_var.get(name, None)
    if value is not None:
        return value

    env_var = "OGRE_" + name.upper()
    value = os.environ.get(env_var, None)
    if value is not None:
        return value

    value = config_dict.get(name, None)
    if value is not None:
        return value

    return None
