"""Select ordinary files from one evidence folder using archive-name mappings."""

import os
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Sequence

from .configuration import Configuration, Mapping
from .logging import configured_log_paths
from .orc_mapping import (
    FileMapping,
    UnpackResult,
    compile_mapping_pattern,
    partition_mappings,
)

if TYPE_CHECKING:
    from .run_preparation import RunConfigGrouper, VariableResolver


_DYNAMIC_OUTPUT_VALUE = re.compile(r"\$(?:relative_path|file_name|parser)\b")


def validate_folder_root(folder: str) -> Path:
    """Resolve and establish that the source directory can be enumerated."""
    if not folder:
        raise ValueError("Folder path is empty")
    root = Path(folder).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"'{folder}' is not a directory")
    if not root.name:
        raise ValueError(f"'{folder}' has no usable folder name")
    with os.scandir(root) as entries:
        next(entries, None)
    return root


def _classify_destination(root: Path, destination: Path, label: str) -> Path | None:
    resolved = destination.resolve(strict=False)
    if resolved == root or resolved in root.parents:
        raise ValueError(f"{label} '{destination}' contains the input folder")
    if root in resolved.parents:
        return resolved
    return None


def _classify_output_template(root: Path, template: str) -> Path | None:
    parts = Path(template).parts
    first_dynamic = next(
        (index for index, component in enumerate(parts) if _DYNAMIC_OUTPUT_VALUE.search(component)),
        None,
    )
    if first_dynamic is None:
        return _classify_destination(root, Path(template), "Output folder")
    if ".." in parts:
        raise ValueError(f"Dynamic output folder '{template}' cannot contain '..'")

    fixed_prefix = Path(*parts[:first_dynamic]).resolve(strict=False)
    if fixed_prefix == root:
        raise ValueError(
            f"Dynamic output folder '{template}' has no separate area to exclude"
        )
    if root in fixed_prefix.parents:
        return fixed_prefix
    if fixed_prefix in root.parents:
        next_root_component = root.relative_to(fixed_prefix).parts[0]
        dynamic_component = parts[first_dynamic]
        matches = list(_DYNAMIC_OUTPUT_VALUE.finditer(dynamic_component))
        literal_start = dynamic_component[: matches[0].start()]
        literal_end = dynamic_component[matches[-1].end() :]
        if next_root_component.startswith(literal_start) and next_root_component.endswith(
            literal_end
        ):
            raise ValueError(
                f"Dynamic output folder '{template}' could overlap the input folder"
            )
    return None


def plan_folder_exclusions(
    root: Path,
    configuration: Configuration,
    resolver: "VariableResolver",
    conf_file: str,
) -> tuple[Path, ...]:
    """Validate write areas and reserve those strictly inside the source."""
    excluded: list[Path] = []

    def reserve(destination: Path, label: str) -> None:
        inside = _classify_destination(root, destination, label)
        if inside is not None:
            excluded.append(inside)

    source_name = root.name
    base_output = (
        configuration.output_folder.replace("$computer_name", resolver.outcome.computer_name)
        .replace("$archive_name", source_name)
        .replace("$timestamp", resolver.timestamp)
    )
    base_area = _classify_output_template(root, base_output)
    if base_area is not None:
        excluded.append(base_area)
    reserve(Path(resolver.resolve_report_folder()), "Report folder")
    reserve(Path(configuration.temp_folder).parent, "Temporary root")
    reserve(Path(configuration.temp_folder), "Temporary run folder")
    for log_path in configured_log_paths(conf_file):
        reserve(log_path, "Log file")

    for mapping in configuration.mapping:
        if not mapping.archive_file_pattern:
            continue
        for output_name in mapping.output:
            output = resolver.resolve_archive_output(
                configuration.output[output_name], str(root), source_name=source_name
            )
            template = (
                output.output_folder.replace("$mapping_label", mapping.mapping_label)
                .replace("$computer_name", resolver.outcome.computer_name)
            )
            inside = _classify_output_template(root, template)
            if inside is not None:
                excluded.append(inside)

    return tuple(dict.fromkeys(excluded))


def validate_concrete_folder_outputs(
    root: Path,
    runs: "RunConfigGrouper",
    exclusions: Sequence[Path] | None = None,
) -> None:
    """Keep mapped output folders and basenames inside validated write areas."""
    for run in runs.map.values():
        for entry in run.batch_entries:
            for output in entry.run_config.output:
                folder = Path(output.output_folder)
                # Writers append data-type/format suffixes before joining the basename.
                file_parent = (folder / f"{output.base_file_name}.output").parent
                for destination in (folder, file_parent):
                    inside = _classify_destination(
                        root, destination, "Mapped output folder"
                    )
                    if inside is not None and exclusions is not None and not any(
                        inside == area or area in inside.parents for area in exclusions
                    ):
                        raise ValueError(
                            f"Mapped output folder '{destination}' was not excluded before scanning"
                        )


def scan_folder(
    root: Path, mappings: Sequence[Mapping], exclusions: Sequence[Path]
) -> UnpackResult:
    """Snapshot regular files without following links, then apply mapping regexes."""
    archive_mappings, _ = partition_mappings(mappings)
    patterns = [
        (mapping, compile_mapping_pattern(mapping, "archive_file_pattern"))
        for mapping in archive_mappings
    ]
    errors: list[str] = []
    files: list[Path] = []

    def excluded(path: Path) -> bool:
        return any(path == area or area in path.parents for area in exclusions)

    def collect(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            if directory == root:
                raise
            errors.append(f"Cannot scan '{directory}': {error}")
            return

        for entry in entries:
            path = Path(entry.path)
            if excluded(path):
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    collect(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(path)
            except OSError as error:
                errors.append(f"Cannot inspect '{path}': {error}")

    collect(root)
    selected: list[FileMapping] = []
    for source in sorted(files, key=lambda path: path.relative_to(root).as_posix()):
        relative = source.relative_to(root).as_posix()
        parent = PurePosixPath(relative).parent.as_posix()
        if parent == ".":
            parent = ""
        for mapping, pattern in patterns:
            if pattern.match(relative):
                selected.append(
                    FileMapping(
                        file=str(source),
                        archive_name="",
                        archive_file=relative,
                        original_file=None,
                        original_creation_date=None,
                        original_modification_date=None,
                        mapping=mapping,
                        vss=None,
                        error=None,
                        relative_path=parent,
                    )
                )
    return UnpackResult(selected, errors)
