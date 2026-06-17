import copy
from pathlib import Path

from dfir_ogre_common import OutputConfiguration

from .configuration import Configuration, Mapping
from .dfir_orc_unpack import OrcOutcome


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
