import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from ogre.config.models import Mapping

from .extract_backend import extract_nested_archives
from .getthis import build_file_mapping
from .matching import FileMapping, match_archive_files, match_original_files


@dataclass
class UnpackResult:
    valid_mapping: list[FileMapping]
    errors: list[str]


def unpack_dfir_orc(
    archive: str,
    password: str | None,
    inner_archive_password: str | None,
    mapping: Collection[Mapping],
    temp_folder: str,
) -> UnpackResult:
    os.makedirs(temp_folder, exist_ok=True)

    if archive.endswith("p7b"):
        archive = os.path.splitext(archive)[0]

    if not os.path.isfile(archive):
        return UnpackResult([], [f"'{archive}' not found or is not a file"])

    if not archive.endswith(".7z"):
        return UnpackResult([], [f"'{archive}' is not a 7z file"])

    archive_name = Path(archive).stem
    archive_extract_folder = os.path.join(temp_folder, archive_name)
    os.makedirs(archive_extract_folder, exist_ok=True)

    try:
        nested_archives = extract_nested_archives(archive, password, archive_extract_folder)
    except Exception as e:
        return UnpackResult(
            [],
            [f"An error occured while extracting sub archives for '{archive}' error:{e}"],
        )

    errors: list[str] = []
    sub_archives = []
    for sub_archive in nested_archives:
        if sub_archive.error:
            errors.append(sub_archive.error)
        else:
            sub_archives.append(sub_archive.path)

    original_files = build_file_mapping(
        archive,
        sub_archives,
        inner_archive_password,
        archive_extract_folder,
    )
    errors += original_files.errors

    archive_file_mapping: list[Mapping] = []
    original_file_mapping: list[Mapping] = []
    for rule in mapping:
        if rule.archive_file_pattern:
            archive_file_mapping.append(rule)
        elif rule.original_file_pattern:
            original_file_mapping.append(rule)

    valid_archive_mapping: list[FileMapping] = []
    valid_original_mapping: list[FileMapping] = []
    try:
        archive_mapping = match_archive_files(
            archive,
            sub_archives,
            archive_file_mapping,
            original_files.name_mapping,
            password,
            inner_archive_password,
            archive_extract_folder,
        )
        valid_archive_mapping = _partition_valid_mappings(archive_mapping, errors)
    except Exception as e:
        errors.append(
            f"An error occured while extracting files from archive match for '{archive}' error:{e}"
        )

    try:
        original_mapping = match_original_files(
            original_files.name_mapping,
            original_file_mapping,
            inner_archive_password,
            archive_extract_folder,
        )
        valid_original_mapping = _partition_valid_mappings(original_mapping, errors)
    except Exception as e:
        errors.append(
            "An error occured while extracting files from original files match "
            f"for '{archive}' error:{e}"
        )

    return UnpackResult(valid_archive_mapping + valid_original_mapping, errors)


def _partition_valid_mappings(
    file_mappings: list[FileMapping],
    errors: list[str],
) -> list[FileMapping]:
    valid_mapping = []
    for mapping_candidate in file_mappings:
        if mapping_candidate.error:
            errors.append(mapping_candidate.error)
        else:
            valid_mapping.append(mapping_candidate)
    return valid_mapping
