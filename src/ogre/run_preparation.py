import copy
import os
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

import dateutil.parser
from dfir_ogre_common import BatchEntry, Metadata, OutputConfiguration, RunConfiguration

from .configuration import Configuration, Mapping
from .dfir_orc_unpack import FileMapping, OrcOutcome


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
