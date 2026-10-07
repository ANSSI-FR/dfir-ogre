"""Select ordinary files from one evidence folder using archive-name mappings."""

import os
from pathlib import Path, PurePosixPath
from typing import Sequence

from .configuration import Mapping
from .orc_mapping import (
    FileMapping,
    UnpackResult,
    compile_mapping_pattern,
    partition_mappings,
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
