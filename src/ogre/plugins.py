from __future__ import annotations

import importlib
import pkgutil
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass

from dfir_ogre_common import OgreBatchedPlugin, OgrePlugin, PluginDescription


@dataclass
class PluginDefinition:
    parser_name: str
    module_name: str
    batch: bool


# A plugin name cache extracted from plugin XML files, to avoid reading XML for every run.
PLUGIN_PARSER_CACHE: dict[str, tuple[str, bool]] = {}


def load_plugin_parser(plugin_file: str) -> tuple[str, bool]:
    plugin_parser = PLUGIN_PARSER_CACHE.get(plugin_file)
    if plugin_parser is None:
        tree = ET.parse(plugin_file)
        root = tree.getroot()

        plugin_name = root.attrib.get("parser")
        batch = root.attrib.get("batch")
        is_batched = batch is not None

        if not plugin_name:
            raise Exception(f"'parser' attribute not found in plugin file :'{plugin_file}'")
        plugin_parser = (plugin_name, is_batched)
        PLUGIN_PARSER_CACHE[plugin_file] = plugin_parser

    return plugin_parser


def load_plugins(plugin_prefixes: list[str]) -> dict[str, PluginDefinition]:
    """
    Load plugins with modules matching given prefixes and register command parsers.
    """
    for _, name, _ in pkgutil.iter_modules():
        for prefix in plugin_prefixes:
            if name.startswith(prefix):
                importlib.import_module(name)

    parser_dict: dict[str, PluginDefinition] = {}
    _register_plugin_classes(parser_dict, OgrePlugin.__subclasses__(), batch=False)
    _register_plugin_classes(parser_dict, OgreBatchedPlugin.__subclasses__(), batch=True)
    return parser_dict


def list_plugin_descriptions() -> list[PluginDescription]:
    parser_dict: dict[str, str] = {}
    descriptions = []
    for parser in OgrePlugin.__subclasses__():
        module_name = parser.__module__
        parser_descr = parser().description()
        entry_module = parser_dict.get(parser_descr.get_command())
        if entry_module:
            raise KeyError(
                f"Parser: '{parser_descr.get_command()}' for class: {parser.__class__} "
                f"module: {module_name} is already defined in module: {entry_module}"
            )

        parser_dict[parser_descr.get_command()] = module_name
        descriptions.append(parser_descr)

    return descriptions


def find_parser(parser_name: str) -> OgrePlugin | None:
    for parser in OgrePlugin.__subclasses__():
        parser_obj = parser()
        if parser_obj.description().get_command() == parser_name:
            return parser_obj
    return None


def find_batched_parser(parser_name: str) -> OgreBatchedPlugin | None:
    for parser in OgreBatchedPlugin.__subclasses__():
        parser_obj = parser()
        if parser_obj.description().get_command() == parser_name:
            return parser_obj
    return None


def _register_plugin_classes(
    parser_dict: dict[str, PluginDefinition],
    parser_classes: Iterable[type],
    batch: bool,
) -> None:
    for parser in parser_classes:
        module_name = parser.__module__
        parser_name = parser().description().get_command()

        entry_module = parser_dict.get(parser_name)
        if entry_module:
            raise KeyError(
                f"Parser name: '{parser_name}' from module: '{module_name}' "
                f"is already defined in module: '{entry_module}'"
            )

        parser_dict[parser_name] = PluginDefinition(parser_name, module_name, batch)
