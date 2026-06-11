import copy
import os
from datetime import timezone
from pathlib import Path
from typing import Any

import dateutil.parser
from dfir_ogre_common import BatchEntry, Metadata, RunConfiguration

from ogre.archive.extraction import unpack_dfir_orc
from ogre.archive.metadata import load_archive_metadata
from ogre.config.loader import load_config
from ogre.config.template_vars import TIMESTAMP_FORMAT, apply_dir_tree, replace_placeholders

from .run_models import PrepareRunResult, RunConfigMap


def prepare_runs(
    conf_file: str,
    archive: str,
    password: str | None,
    global_var: dict[str, str] | None = None,
) -> PrepareRunResult:
    run_config_map = RunConfigMap()
    runtime_vars = dict(global_var or {})
    configuration, plugin_registry = load_config(conf_file, runtime_vars)

    orc_outcome = load_archive_metadata(archive)
    archives = orc_outcome.archives
    runtime_vars["computer_name"] = orc_outcome.computer_name
    runtime_vars["orc_id"] = orc_outcome.id
    runtime_vars["orc_start_date"] = orc_outcome.date.isoformat()

    timestamp = orc_outcome.date.strftime(TIMESTAMP_FORMAT)
    configuration.report_folder = replace_placeholders(
        configuration.report_folder,
        {"case": configuration.case, "timestamp": timestamp},
    )
    configuration.report_folder = apply_dir_tree(
        configuration.report_folder,
        orc_outcome.dir_tree,
        configuration.dir_tree,
    )

    errors: list[str] = []
    for source_archive in archives:
        conf = copy.deepcopy(configuration)
        _expand_archive_outputs(conf, source_archive, timestamp, orc_outcome.dir_tree)

        unpacked = unpack_dfir_orc(
            source_archive,
            password,
            conf.inner_archive_password,
            conf.mapping,
            conf.temp_folder,
        )
        errors += unpacked.errors

        for file_mapping in unpacked.valid_mapping:
            mapping = file_mapping.mapping
            plugin_file = _expand_plugin_file(
                mapping.plugin_file,
                conf.output_folder,
                source_archive,
                configuration.case,
                conf.plugin_folder,
            )
            parser_config = plugin_registry.load_plugin_parser(plugin_file)
            plugin_definition = plugin_registry.get_definition(parser_config.parser_name)
            if not plugin_definition:
                raise Exception(
                    f"plugin '{parser_config.parser_name}' not found in the loaded plugins"
                )

            output = [copy.deepcopy(conf.output[out_name]) for out_name in mapping.output]
            _expand_run_outputs(
                output,
                mapping.mapping_label,
                parser_config.parser_name,
                file_mapping.file,
                orc_outcome.computer_name,
            )

            metadata = _build_metadata(file_mapping, source_archive, orc_outcome)
            additional_params = _expand_params(
                mapping.params,
                conf.output_folder,
                source_archive,
                configuration.case,
                conf.plugin_folder,
            )
            run_config = RunConfiguration(output, mapping.force_snake_case, additional_params)
            batch_entry = BatchEntry(os.path.abspath(file_mapping.file), run_config, metadata)

            run_config_map.add_configuration(
                batch_entry,
                plugin_file,
                mapping.mapping_label,
                plugin_definition.module_name,
                parser_config.parser_name,
                parser_config.batch,
                mapping.timeout,
            )

    return PrepareRunResult(
        archive,
        run_config_map,
        errors,
        orc_outcome.computer_name,
        orc_outcome.id,
        configuration.output_folder,
        configuration.report_folder,
        configuration.temp_folder,
    )


def _expand_archive_outputs(
    configuration, archive: str, timestamp: str, dir_tree: str | None
) -> None:
    for output_conf in configuration.output.values():
        archive_variables = {
            "output_folder": configuration.output_folder,
            "archive_name": Path(archive).stem,
            "case": configuration.case,
            "timestamp": timestamp,
        }
        output_folder = replace_placeholders(output_conf.output_folder, archive_variables)
        output_conf.output_folder = apply_dir_tree(
            output_folder,
            dir_tree,
            configuration.dir_tree,
        )
        output_conf.base_file_name = replace_placeholders(
            output_conf.base_file_name,
            archive_variables,
        )


def _expand_plugin_file(
    plugin_file: str,
    output_folder: str,
    archive: str,
    case: str,
    plugin_folder: str,
) -> str:
    return replace_placeholders(
        plugin_file,
        {
            "output_folder": output_folder,
            "archive_name": Path(archive).stem,
            "case": case,
            "plugin_folder": plugin_folder,
        },
    )


def _expand_run_outputs(
    outputs,
    mapping_label: str,
    parser_name: str,
    file_name: str,
    computer_name: str,
) -> None:
    run_variables = {
        "mapping_label": mapping_label,
        "parser": parser_name,
        "file_name": Path(file_name).stem,
        "computer_name": computer_name,
    }
    for output_conf in outputs:
        output_conf.output_folder = replace_placeholders(output_conf.output_folder, run_variables)
        output_conf.base_file_name = replace_placeholders(output_conf.base_file_name, run_variables)


def _build_metadata(file_mapping, archive: str, orc_outcome) -> Metadata:
    metadata = Metadata(orc_outcome.computer_name)

    archive_abs_path = os.path.abspath(archive)
    metadata.folder = os.path.basename(os.path.dirname(archive_abs_path))
    metadata.archive = os.path.basename(archive)

    subarchive_name = Path(file_mapping.archive_name).stem
    if archive != subarchive_name and subarchive_name:
        metadata.subarchive = subarchive_name + ".7z"

    metadata.orc_start_date = orc_outcome.date
    metadata.orc_id = orc_outcome.id
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


def _expand_params(
    params: dict[str, Any],
    output_folder: str,
    archive: str,
    case: str,
    plugin_folder: str,
) -> dict[str, str | None]:
    additional_params: dict[str, str | None] = {}
    for key, value in params.items():
        if isinstance(value, str):
            additional_params[key] = replace_placeholders(
                value,
                {
                    "output_folder": output_folder,
                    "archive_name": Path(archive).stem,
                    "case": case,
                    "plugin_folder": plugin_folder,
                },
            )
        else:
            additional_params[key] = str(value)
    return additional_params
