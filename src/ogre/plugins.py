from __future__ import annotations

import importlib
import pkgutil
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass

from dfir_ogre_common import OgreBatchedPlugin, OgrePlugin, PluginDescription


@dataclass(frozen=True)
class PluginDefinition:
    parser_name: str
    module_name: str
    batch: bool


@dataclass(frozen=True)
class PluginParserConfig:
    parser_name: str
    batch: bool


class PluginRegistry:
    """Registry of discovered parser plugins and parsed plugin XML metadata."""

    def __init__(self) -> None:
        self._definitions: dict[str, PluginDefinition] = {}
        self._parser_classes: dict[str, type[OgrePlugin]] = {}
        self._batched_parser_classes: dict[str, type[OgreBatchedPlugin]] = {}
        self._plugin_parser_cache: dict[str, PluginParserConfig] = {}

    @classmethod
    def from_prefixes(cls, plugin_prefixes: Iterable[str]) -> PluginRegistry:
        registry = cls()
        registry.import_prefixed_modules(plugin_prefixes)
        registry.register_current_plugins()
        return registry

    @classmethod
    def from_current_plugins(cls) -> PluginRegistry:
        registry = cls()
        registry.register_current_plugins()
        return registry

    @property
    def definitions(self) -> dict[str, PluginDefinition]:
        return dict(self._definitions)

    def import_prefixed_modules(self, plugin_prefixes: Iterable[str]) -> None:
        prefixes = tuple(plugin_prefixes)
        for _, name, _ in pkgutil.iter_modules():
            if name.startswith(prefixes):
                importlib.import_module(name)

    def register_current_plugins(self) -> None:
        self.register_plugin_classes(OgrePlugin.__subclasses__(), batch=False)
        self.register_plugin_classes(OgreBatchedPlugin.__subclasses__(), batch=True)

    def register_plugin_classes(self, parser_classes: Iterable[type], batch: bool) -> None:
        for parser_class in parser_classes:
            module_name = parser_class.__module__
            parser_name = parser_class().description().get_command()

            existing = self._definitions.get(parser_name)
            if existing:
                raise KeyError(
                    f"Parser name: '{parser_name}' from module: '{module_name}' "
                    f"is already defined in module: '{existing.module_name}'"
                )

            self._definitions[parser_name] = PluginDefinition(parser_name, module_name, batch)
            if batch:
                self._batched_parser_classes[parser_name] = parser_class
            else:
                self._parser_classes[parser_name] = parser_class

    def get_definition(self, parser_name: str) -> PluginDefinition | None:
        return self._definitions.get(parser_name)

    def list_descriptions(self) -> list[PluginDescription]:
        descriptions = []
        for parser_name in sorted(self._parser_classes):
            parser_class = self._parser_classes[parser_name]
            descriptions.append(parser_class().description())
        return descriptions

    def create_parser(self, parser_name: str) -> OgrePlugin | None:
        parser_class = self._parser_classes.get(parser_name)
        if parser_class:
            return parser_class()
        return None

    def create_batched_parser(self, parser_name: str) -> OgreBatchedPlugin | None:
        parser_class = self._batched_parser_classes.get(parser_name)
        if parser_class:
            return parser_class()
        return None

    def load_plugin_parser(self, plugin_file: str) -> PluginParserConfig:
        plugin_parser = self._plugin_parser_cache.get(plugin_file)
        if plugin_parser is not None:
            return plugin_parser

        tree = ET.parse(plugin_file)
        root = tree.getroot()

        plugin_name = root.attrib.get("parser")
        batch = root.attrib.get("batch")
        is_batched = batch is not None

        if not plugin_name:
            raise Exception(f"'parser' attribute not found in plugin file :'{plugin_file}'")

        plugin_parser = PluginParserConfig(plugin_name, is_batched)
        self._plugin_parser_cache[plugin_file] = plugin_parser
        return plugin_parser


def build_plugin_registry(plugin_prefixes: Iterable[str]) -> PluginRegistry:
    return PluginRegistry.from_prefixes(plugin_prefixes)


def build_current_plugin_registry() -> PluginRegistry:
    return PluginRegistry.from_current_plugins()
