import copy
import importlib
import os
import pkgutil
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Callable

import dateutil.parser
import yaml
from dfir_ogre_common import (
    BatchEntry,
    Metadata,
    OgreBatchedPlugin,
    OgrePlugin,
    OutputConfiguration,
    RunConfiguration,
)

from .configuration import Configuration, Mapping, build_configuration
from .dfir_orc_unpack import (
    FileMapping,
    OrcOutcome,
    UnpackResult,
    load_archive_metadata,
    unpack_dfir_orc,
)


class VariableResolver:
    def __init__(self, configuration: Configuration, outcome: OrcOutcome):
        self.configuration = configuration
        self.outcome = outcome

    @property
    def timestamp(self) -> str:
        return self.outcome.date.strftime("%Y%m%d_%H%M%S")

    def resolve_report_folder(self) -> str:
        report_folder = self.configuration.report_folder.replace(
            "$case", self.configuration.case
        ).replace("$timestamp", self.timestamp)
        if self.outcome.dir_tree:
            return report_folder.replace("$dir_tree", self.outcome.dir_tree)
        return report_folder.replace("/$dir_tree", self.configuration.dir_tree)

    def resolve_archive_output(
        self,
        output: OutputConfiguration,
        archive: str,
    ) -> OutputConfiguration:
        resolved = copy.deepcopy(output)
        archive_name = Path(archive).stem
        output_folder = (
            resolved.output_folder.replace(
                "$output_folder", self.configuration.output_folder
            )
            .replace("$archive_name", archive_name)
            .replace("$case", self.configuration.case)
            .replace("$timestamp", self.timestamp)
        )
        if self.outcome.dir_tree:
            output_folder = output_folder.replace("$dir_tree", self.outcome.dir_tree)
        else:
            output_folder = output_folder.replace(
                "/$dir_tree", self.configuration.dir_tree
            )
        resolved.output_folder = output_folder

        resolved.base_file_name = (
            resolved.base_file_name.replace(
                "$output_folder", self.configuration.output_folder
            )
            .replace("$archive_name", archive_name)
            .replace("$case", self.configuration.case)
            .replace("$timestamp", self.timestamp)
        )
        return resolved

    def resolve_run_output(
        self,
        output: OutputConfiguration,
        mapping_label: str,
        parser: str,
        file_path: str,
    ) -> OutputConfiguration:
        resolved = copy.deepcopy(output)
        file_name = Path(file_path).stem
        resolved.output_folder = (
            resolved.output_folder.replace("$mapping_label", mapping_label)
            .replace("$parser", parser)
            .replace("$file_name", file_name)
            .replace("$computer_name", self.outcome.computer_name)
        )
        resolved.base_file_name = (
            resolved.base_file_name.replace("$mapping_label", mapping_label)
            .replace("$parser", parser)
            .replace("$file_name", file_name)
            .replace("$computer_name", self.outcome.computer_name)
        )
        return resolved

    def resolve_plugin_file(self, mapping: Mapping, archive: str) -> str:
        return (
            mapping.plugin_file.replace(
                "$output_folder", self.configuration.output_folder
            )
            .replace("$archive_name", Path(archive).stem)
            .replace("$case", self.configuration.case)
            .replace("$plugin_folder", self.configuration.plugin_folder)
        )

    def resolve_mapping_params(
        self,
        mapping: Mapping,
        archive: str,
    ) -> dict[str, str | None]:
        archive_name = Path(archive).stem
        additional_params: dict[str, str | None] = {}
        for key, value in mapping.params.items():
            if isinstance(value, str):
                additional_params[key] = (
                    value.replace("$output_folder", self.configuration.output_folder)
                    .replace("$archive_name", archive_name)
                    .replace("$case", self.configuration.case)
                    .replace("$plugin_folder", self.configuration.plugin_folder)
                )
            else:
                additional_params[key] = str(value)
        return additional_params


@dataclass(frozen=True)
class ParserSelection:
    plugin_file: str
    parser: str
    module: str
    batch: bool


class BatchEntryBuilder:
    def __init__(
        self,
        configuration: Configuration,
        outcome: OrcOutcome,
        resolver: VariableResolver,
    ):
        self.configuration = configuration
        self.outcome = outcome
        self.resolver = resolver

    def build(
        self,
        archive: str,
        archive_outputs: dict[str, OutputConfiguration],
        file_mapping: FileMapping,
        selection: ParserSelection,
    ) -> BatchEntry:
        mapping = file_mapping.mapping
        output = [
            self.resolver.resolve_run_output(
                archive_outputs[out_name],
                mapping.mapping_label,
                selection.parser,
                file_mapping.file,
            )
            for out_name in mapping.output
        ]
        run_config = RunConfiguration(
            output,
            mapping.force_nake_case,
            self.resolver.resolve_mapping_params(mapping, archive),
        )
        metadata = self._build_metadata(archive, file_mapping)
        return BatchEntry(os.path.abspath(file_mapping.file), run_config, metadata)

    def _build_metadata(self, archive: str, file_mapping: FileMapping) -> Metadata:
        metadata = Metadata(self.outcome.computer_name)
        archive_abs_path = os.path.abspath(archive)
        folder = os.path.basename(os.path.dirname(archive_abs_path))
        archive_name = os.path.basename(archive)
        subarchive_name = Path(file_mapping.archive_name).stem

        metadata.folder = folder
        metadata.archive = archive_name
        if archive != subarchive_name and subarchive_name:
            metadata.subarchive = subarchive_name + ".7z"

        metadata.orc_start_date = self.outcome.date
        metadata.orc_id = self.outcome.id
        metadata.archive_filename = file_mapping.archive_file
        metadata.original_filename = file_mapping.original_file
        metadata.vss = file_mapping.vss

        if file_mapping.original_creation_date:
            metadata.creation_date = dateutil.parser.isoparse(
                file_mapping.original_creation_date
            ).astimezone(timezone.utc)
        if file_mapping.original_modification_date:
            metadata.modif_date = dateutil.parser.isoparse(
                file_mapping.original_modification_date
            ).astimezone(timezone.utc)

        return metadata


@dataclass(frozen=True)
class PluginDefinition:
    parser_name: str
    module: str
    batch: bool

    @property
    def module_name(self) -> str:
        return self.module


@dataclass
class OgreRunConfiguration:
    batch_entries: list[BatchEntry]
    plugin_file: str
    mapping_label: str
    module: str
    parser: str
    batch: bool
    timeout: int


class RunConfigGrouper:
    def __init__(self):
        self.map: dict[str, OgreRunConfiguration] = {}

    def add(
        self,
        batch_entry: BatchEntry,
        plugin_file: str,
        mapping_label: str,
        module: str,
        parser: str,
        batch: bool,
        timeout: int,
    ) -> None:
        entry = self.map.get(plugin_file)
        if entry:
            entry.batch_entries.append(batch_entry)
            return
        self.map[plugin_file] = OgreRunConfiguration(
            [batch_entry],
            plugin_file,
            mapping_label,
            module,
            parser,
            batch,
            timeout,
        )

    def add_configuration(
        self,
        batch_entry: BatchEntry,
        plugin_file: str,
        mapping_label: str,
        module: str,
        parser: str,
        batch: bool,
        timeout: int,
    ) -> None:
        self.add(
            batch_entry,
            plugin_file,
            mapping_label,
            module,
            parser,
            batch,
            timeout,
        )


@dataclass
class ArchivePlanResult:
    runs: RunConfigGrouper
    errors: list[str]
    last_archive: str


class ArchiveRunPlanner:
    def __init__(
        self,
        configuration: Configuration,
        outcome: OrcOutcome,
        password: str | None,
        parsers: dict[str, PluginDefinition],
        resolver: VariableResolver,
        unpack: Callable[
            [str, str | None, str | None, list[Mapping], str],
            UnpackResult,
        ] = unpack_dfir_orc,
        load_parser: Callable[[str], tuple[str, bool]] | None = None,
    ):
        self.configuration = configuration
        self.outcome = outcome
        self.password = password
        self.parsers = parsers
        self.resolver = resolver
        self.unpack = unpack
        self.load_parser = load_parser

    def plan(self) -> ArchivePlanResult:
        if self.load_parser is None:
            raise TypeError("load_parser must be provided")

        errors: list[str] = []
        grouper = RunConfigGrouper()
        last_archive = ""
        builder = BatchEntryBuilder(self.configuration, self.outcome, self.resolver)

        for archive in self.outcome.archives:
            last_archive = archive
            archive_outputs = {
                name: self.resolver.resolve_archive_output(output, archive)
                for name, output in self.configuration.output.items()
            }
            unpacked = self.unpack(
                archive,
                self.password,
                self.configuration.inner_archive_password,
                self.configuration.mapping,
                self.configuration.temp_folder,
            )
            errors.extend(unpacked.errors)
            for file_mapping in unpacked.valid_mapping:
                mapping = file_mapping.mapping
                plugin_file = self.resolver.resolve_plugin_file(mapping, archive)
                parser_name, is_batched = self.load_parser(plugin_file)
                parser_definition = self.parsers.get(parser_name)
                if not parser_definition:
                    raise Exception(
                        f"plugin '{(parser_name, is_batched)}' not found in the loaded plugins"
                    )
                selection = ParserSelection(
                    plugin_file,
                    parser_name,
                    parser_definition.module,
                    is_batched,
                )
                batch_entry = builder.build(
                    archive,
                    archive_outputs,
                    file_mapping,
                    selection,
                )
                grouper.add(
                    batch_entry,
                    plugin_file,
                    mapping.mapping_label,
                    parser_definition.module,
                    parser_name,
                    is_batched,
                    mapping.timeout,
                )

        return ArchivePlanResult(grouper, errors, last_archive)


def load_config(
    conf_file: str,
    global_var: dict[str, str],
) -> tuple[Configuration, dict[str, PluginDefinition]]:
    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_var)
    plugins = load_plugins(config.plugin_prefixes)

    for mapping in config.mapping:
        if mapping.archive_file_pattern:
            try:
                re.compile(mapping.archive_file_pattern, re.IGNORECASE)
            except Exception as error:
                raise Exception(
                    f"{error} in archive_file_pattern regex:'{mapping.archive_file_pattern}', mapping_label:'{mapping.mapping_label}'"
                )

        if mapping.original_file_pattern:
            try:
                re.compile(mapping.original_file_pattern, re.IGNORECASE)
            except Exception as error:
                raise Exception(
                    f"{error} in original_file_pattern regex:'{mapping.original_file_pattern}', mapping_label:'{mapping.mapping_label}'"
                )

    return config, plugins


PLUGIN_PARSER_CACHE: dict[str, tuple[str, bool]] = {}


def clear_plugin_parser_cache() -> None:
    PLUGIN_PARSER_CACHE.clear()


def load_plugin_parser(plugin_file: str) -> tuple[str, bool]:
    plugin_parser = PLUGIN_PARSER_CACHE.get(plugin_file)
    if plugin_parser is None:
        tree = ET.parse(plugin_file)
        root = tree.getroot()
        plugin_name = root.attrib.get("parser")
        batch = root.attrib.get("batch")
        is_batched = batch is not None

        if not plugin_name:
            raise Exception(
                f"'parser' attribute not found in plugin file :'{plugin_file}'"
            )
        plugin_parser = (plugin_name, is_batched)
        PLUGIN_PARSER_CACHE[plugin_file] = plugin_parser

    return plugin_parser


def load_plugins(plugin_prefixes: list[str]) -> dict[str, PluginDefinition]:
    for _, name, _ in pkgutil.iter_modules():
        for prefix in plugin_prefixes:
            if name.startswith(prefix):
                importlib.import_module(name)

    parser_dict: dict[str, PluginDefinition] = {}

    for parser in OgrePlugin.__subclasses__():
        module_name = parser.__module__
        parser_name = parser().description().get_command()
        entry = parser_dict.get(parser_name)
        if entry:
            raise KeyError(
                f"Parser name: '{parser_name}' from module: '{module_name}' is already defined in module: '{entry}'"
            )
        parser_dict[parser_name] = PluginDefinition(parser_name, module_name, False)

    for parser in OgreBatchedPlugin.__subclasses__():
        module_name = parser.__module__
        parser_name = parser().description().get_command()
        entry = parser_dict.get(parser_name)
        if entry:
            raise KeyError(
                f"Parser name: '{parser_name}' from module: '{module_name}' is already defined in module: '{entry}'"
            )
        parser_dict[parser_name] = PluginDefinition(parser_name, module_name, True)

    return parser_dict


@dataclass
class PrepareRunResult:
    archive: str
    runs: RunConfigGrouper
    errors: list[str]
    computer: str
    orc_id: str
    output_folder: str
    report_folder: str
    tmp_folder: str


@dataclass
class RunPreparationContext:
    conf_file: str
    archive: str
    password: str | None
    global_vars: dict[str, str]
    configuration: Configuration
    parsers: dict[str, PluginDefinition]
    outcome: OrcOutcome

    @classmethod
    def load(
        cls,
        conf_file: str,
        archive: str,
        password: str | None,
        global_var: dict[str, str] | None,
    ) -> "RunPreparationContext":
        request_globals = dict(global_var or {})
        configuration, parsers = load_config(conf_file, request_globals)
        outcome = load_archive_metadata(archive)
        request_globals["computer_name"] = outcome.computer_name
        request_globals["orc_id"] = outcome.id
        request_globals["orc_start_date"] = outcome.date.isoformat()
        return cls(
            conf_file,
            archive,
            password,
            request_globals,
            configuration,
            parsers,
            outcome,
        )


def prepare_runs(
    conf_file: str,
    archive: str,
    password: str | None,
    global_var: dict[str, str] | None = None,
) -> PrepareRunResult:
    context = RunPreparationContext.load(conf_file, archive, password, global_var)
    resolver = VariableResolver(context.configuration, context.outcome)
    report_folder = resolver.resolve_report_folder()
    planner = ArchiveRunPlanner(
        configuration=context.configuration,
        outcome=context.outcome,
        password=context.password,
        parsers=context.parsers,
        resolver=resolver,
        load_parser=load_plugin_parser,
    )
    plan = planner.plan()
    return PrepareRunResult(
        plan.last_archive,
        plan.runs,
        plan.errors,
        context.outcome.computer_name,
        context.outcome.id,
        context.configuration.output_folder,
        report_folder,
        context.configuration.temp_folder,
    )
