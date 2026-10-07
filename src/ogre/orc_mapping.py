import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Collection, Optional

from .configuration import Mapping


WINDOWS_SHORT_FILE_PATTERN = re.compile(".*~[0-9]+\\.[a-zA-Z0-9_]+", re.IGNORECASE)
EXTRACT_BATCH_SIZE = 10000
FILE_NAME_MAPPING = "GetThis.csv"
INNER_TEMP_ARCHIVE = ".inner"


@dataclass
class OriginalNameMapping:
    archive: str
    sample_name: str
    original_name: str
    creation_date: Optional[str]
    modification_date: Optional[str]
    vss: str


@dataclass
class FileMapping:
    file: str
    archive_name: str
    archive_file: str
    original_file: Optional[str]
    original_creation_date: Optional[str]
    original_modification_date: Optional[str]
    mapping: Mapping
    vss: Optional[str]
    error: Optional[str]
    relative_path: str = ""


@dataclass
class UnpackResult:
    valid_mapping: list[FileMapping]
    errors: list[str]


@dataclass
class NestedArchive:
    path: str
    error: Optional[str]


@dataclass
class OriginalFileMappingResult:
    name_mapping: list[OriginalNameMapping]
    errors: list[str]


def source_relative_parent(
    member_path: str, nested_archive_member: str | None = None
) -> str:
    """Return the logical parent of an archive member, without temp paths."""
    parent = PurePosixPath(member_path.replace("\\", "/")).parent
    parts = []
    if nested_archive_member:
        nested = PurePosixPath(nested_archive_member.replace("\\", "/"))
        parts.append(nested.with_suffix("").as_posix())
    if parent != PurePosixPath("."):
        parts.append(parent.as_posix())
    return "/".join(parts)


def partition_mappings(
    mappings: Collection[Mapping],
) -> tuple[list[Mapping], list[Mapping]]:
    archive_file_mapping: list[Mapping] = []
    original_file_mapping: list[Mapping] = []

    for mapping in mappings:
        if mapping.archive_file_pattern:
            archive_file_mapping.append(mapping)
        elif mapping.original_file_pattern:
            original_file_mapping.append(mapping)

    return archive_file_mapping, original_file_mapping


def compile_mapping_pattern(mapping: Mapping, field_name: str) -> re.Pattern:
    pattern_text = getattr(mapping, field_name)
    try:
        return re.compile(pattern_text, re.IGNORECASE)
    except Exception as error:
        raise Exception(
            f"{error} in {field_name} regex:'{pattern_text}', mapping_label:'{mapping.mapping_label}'"
        )


def build_original_lookup(
    original_files: list[OriginalNameMapping],
) -> dict[str, OriginalNameMapping]:
    file_dict: dict[str, OriginalNameMapping] = {}
    for original in original_files:
        inserted = file_dict.get(original.sample_name, None)
        if inserted:
            if WINDOWS_SHORT_FILE_PATTERN.match(inserted.original_name):
                file_dict[original.sample_name] = original
        else:
            file_dict[original.sample_name] = original
    return file_dict
