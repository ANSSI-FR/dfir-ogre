import copy
import importlib
import os
import pkgutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Sequence

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
from .orc_mapping import compile_mapping_pattern
from .folder_input import (
    plan_folder_exclusions,
    scan_folder,
    validate_concrete_folder_outputs,
    validate_folder_root,
)
from .output_naming import OutputNameRegistry, expand_relative_path


@dataclass(frozen=True)
class RunVariables:
    computer_name: str
    date: datetime
    dir_tree: str | None


def _set_original_metadata(metadata: Metadata, file_mapping: FileMapping) -> None:
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


class VariableResolver:
    def __init__(self, configuration: Configuration, outcome: OrcOutcome | RunVariables):
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
        *,
        source_name: str | None = None,
    ) -> OutputConfiguration:
        resolved = copy.deepcopy(output)
        archive_name = source_name if source_name is not None else Path(archive).stem
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
        relative_path: str = "",
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
        resolved.output_folder = expand_relative_path(
            resolved.output_folder, relative_path, filename=False
        )
        resolved.base_file_name = expand_relative_path(
            resolved.base_file_name, relative_path, filename=True
        )
        if not resolved.output_folder:
            raise ValueError("Resolved output folder is empty")
        return resolved

    def resolve_plugin_file(
        self, mapping: Mapping, archive: str, *, source_name: str | None = None
    ) -> str:
        archive_name = source_name if source_name is not None else Path(archive).stem
        return (
            mapping.plugin_file.replace(
                "$output_folder", self.configuration.output_folder
            )
            .replace("$archive_name", archive_name)
            .replace("$case", self.configuration.case)
            .replace("$plugin_folder", self.configuration.plugin_folder)
        )

    def resolve_mapping_params(
        self,
        mapping: Mapping,
        archive: str,
        *,
        source_name: str | None = None,
    ) -> dict[str, str | None]:
        archive_name = source_name if source_name is not None else Path(archive).stem
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
        outcome: OrcOutcome | RunVariables,
        resolver: VariableResolver,
        *,
        metadata_factory: Callable[[str, FileMapping], Metadata] | None = None,
        name_registry: OutputNameRegistry | None = None,
    ):
        self.configuration = configuration
        self.outcome = outcome
        self.resolver = resolver
        self.metadata_factory = metadata_factory
        self.name_registry = name_registry
        self._pending_output_refresh: list[
            tuple[BatchEntry, list[OutputConfiguration], bool, dict[str, str | None]]
        ] = []

    def build(
        self,
        archive: str,
        archive_outputs: dict[str, OutputConfiguration],
        file_mapping: FileMapping,
        selection: ParserSelection,
        *,
        source_name: str | None = None,
    ) -> BatchEntry:
        mapping = file_mapping.mapping
        output = []
        for out_name in mapping.output:
            resolved = self.resolver.resolve_run_output(
                archive_outputs[out_name],
                mapping.mapping_label,
                selection.parser,
                file_mapping.file,
                relative_path=file_mapping.relative_path,
            )
            output.append(resolved)
            if self.name_registry is not None:
                source_key = "\0".join(
                    (
                        str(Path(archive).resolve(strict=False)),
                        file_mapping.relative_path,
                        file_mapping.archive_file,
                    )
                )
                self.name_registry.register(
                    resolved,
                    source_key=source_key,
                    mapping_label=mapping.mapping_label,
                    output_name=out_name,
                    uses_relative_path=(
                        "$relative_path" in self.configuration.output[out_name].base_file_name
                    ),
                )
        params = self.resolver.resolve_mapping_params(
            mapping, archive, source_name=source_name
        )
        run_config = RunConfiguration(
            output,
            mapping.force_nake_case,
            params,
        )
        metadata = (
            self.metadata_factory(archive, file_mapping)
            if self.metadata_factory is not None
            else self._build_metadata(archive, file_mapping)
        )
        entry = BatchEntry(os.path.abspath(file_mapping.file), run_config, metadata)
        if self.name_registry is not None:
            self._pending_output_refresh.append(
                (entry, output, mapping.force_nake_case, params)
            )
        return entry

    def finalize_output_names(self) -> None:
        if self.name_registry is None:
            return
        self.name_registry.finalize()
        for entry, output, force_snake_case, params in self._pending_output_refresh:
            entry.run_config = RunConfiguration(output, force_snake_case, params)

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
        _set_original_metadata(metadata, file_mapping)
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


class MappingRunPlanner:
    """Turn selected file mappings from either source into parser entries."""

    def __init__(
        self,
        configuration: Configuration,
        parsers: dict[str, PluginDefinition],
        resolver: VariableResolver,
        builder: BatchEntryBuilder,
        load_parser: Callable[[str], tuple[str, bool]],
    ):
        self.configuration = configuration
        self.parsers = parsers
        self.resolver = resolver
        self.builder = builder
        self.load_parser = load_parser

    def add_source(
        self,
        source: str,
        file_mappings: Sequence[FileMapping],
        runs: RunConfigGrouper,
        *,
        source_name: str | None = None,
    ) -> None:
        archive_outputs = {
            name: self.resolver.resolve_archive_output(
                output, source, source_name=source_name
            )
            for name, output in self.configuration.output.items()
        }
        for file_mapping in file_mappings:
            mapping = file_mapping.mapping
            plugin_file = self.resolver.resolve_plugin_file(
                mapping, source, source_name=source_name
            )
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
            batch_entry = self.builder.build(
                source,
                archive_outputs,
                file_mapping,
                selection,
                source_name=source_name,
            )
            runs.add(
                batch_entry,
                plugin_file,
                mapping.mapping_label,
                parser_definition.module,
                parser_name,
                is_batched,
                mapping.timeout,
            )


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
        builder = BatchEntryBuilder(
            self.configuration,
            self.outcome,
            self.resolver,
            name_registry=OutputNameRegistry(),
        )
        mapping_planner = MappingRunPlanner(
            self.configuration,
            self.parsers,
            self.resolver,
            builder,
            self.load_parser,
        )

        for archive in self.outcome.archives:
            last_archive = archive
            unpacked = self.unpack(
                archive,
                self.password,
                self.configuration.inner_archive_password,
                self.configuration.mapping,
                self.configuration.temp_folder,
            )
            errors.extend(unpacked.errors)
            mapping_planner.add_source(archive, unpacked.valid_mapping, grouper)

        builder.finalize_output_names()
        return ArchivePlanResult(grouper, errors, last_archive)


def load_config(
    conf_file: str,
    global_var: dict[str, str],
    *,
    pattern_scope: Literal["all", "archive"] = "all",
) -> tuple[Configuration, dict[str, PluginDefinition]]:
    if pattern_scope not in ("all", "archive"):
        raise ValueError(f"Unknown pattern scope: {pattern_scope}")
    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_var)
    plugins = load_plugins(config.plugin_prefixes)

    for mapping in config.mapping:
        if mapping.archive_file_pattern:
            compile_mapping_pattern(mapping, "archive_file_pattern")

        if pattern_scope == "all" and mapping.original_file_pattern:
            compile_mapping_pattern(mapping, "original_file_pattern")

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
    archive: str | None
    runs: RunConfigGrouper
    errors: list[str]
    computer: str
    orc_id: str | None
    output_folder: str
    report_folder: str
    tmp_folder: str
    source_folder: str | None = None
    run_id: str | None = None


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


def prepare_folder_runs(
    conf_file: str,
    folder: str,
    computer_name: str | None,
    global_var: dict[str, str] | None = None,
    *,
    started_at: datetime | None = None,
) -> PrepareRunResult:
    root = validate_folder_root(folder)
    effective_computer = root.name if computer_name is None else computer_name
    if (
        not effective_computer.strip()
        or effective_computer in (".", "..")
        or "/" in effective_computer
        or "\\" in effective_computer
        or "\x00" in effective_computer
    ):
        raise ValueError("Computer name must be one nonempty path component")

    configuration, parsers = load_config(conf_file, dict(global_var or {}))
    run_date = started_at if started_at is not None else datetime.now(timezone.utc)
    resolver = VariableResolver(
        configuration, RunVariables(effective_computer, run_date, None)
    )
    report_folder = resolver.resolve_report_folder()
    exclusions = plan_folder_exclusions(root, configuration, resolver, conf_file)
    scanned = scan_folder(root, configuration.mapping, exclusions)
    errors = list(scanned.errors)
    if not scanned.valid_mapping:
        errors.append(f"No files matched mapping rules in folder '{root}'")

    def folder_metadata(_source: str, file_mapping: FileMapping) -> Metadata:
        metadata = Metadata(effective_computer)
        metadata.folder = root.name
        metadata.archive_filename = file_mapping.archive_file
        _set_original_metadata(metadata, file_mapping)
        return metadata

    runs = RunConfigGrouper()
    builder = BatchEntryBuilder(
        configuration,
        resolver.outcome,
        resolver,
        metadata_factory=folder_metadata,
        name_registry=OutputNameRegistry(),
    )
    mapping_planner = MappingRunPlanner(
        configuration,
        parsers,
        resolver,
        builder,
        load_plugin_parser,
    )
    mapping_planner.add_source(
        str(root), scanned.valid_mapping, runs, source_name=root.name
    )
    builder.finalize_output_names()
    validate_concrete_folder_outputs(root, runs, exclusions)

    return PrepareRunResult(
        None,
        runs,
        errors,
        effective_computer,
        None,
        configuration.output_folder,
        report_folder,
        configuration.temp_folder,
        str(root),
        Path(configuration.temp_folder).name,
    )
