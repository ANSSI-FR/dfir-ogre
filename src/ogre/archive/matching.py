import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import py7zr
from dfir_ogre_common import FilesToExtract, extract_7z_files

from ogre.config.models import Mapping

from .sevenzip_rename import MAX_FILE_NAME_BYTE_LENGTH, need_rename, rename_file

logger = logging.getLogger(__name__)
WINDOWS_SHORT_FILE_PATTERN = re.compile(".*~[0-9]+\\.[a-zA-Z0-9_]+", re.IGNORECASE)


@dataclass
class OriginalNameMapping:
    archive: str
    sample_name: str
    original_name: str
    creation_date: str | None
    modification_date: str | None
    vss: str


@dataclass
class FileMapping:
    file: str
    archive_name: str
    archive_file: str
    original_file: str | None
    original_creation_date: str | None
    original_modification_date: str | None
    mapping: Mapping
    vss: str | None
    error: str | None


def compile_mapping_patterns(
    mappings: list[Mapping],
    attribute: str,
) -> list[tuple[Mapping, re.Pattern[str]]]:
    compiled: list[tuple[Mapping, re.Pattern[str]]] = []
    for mapping in mappings:
        pattern_value = getattr(mapping, attribute)
        if pattern_value:
            try:
                compiled.append((mapping, re.compile(pattern_value, re.IGNORECASE)))
            except Exception as e:
                raise Exception(f"{e} in regex:{pattern_value}") from e
    return compiled


def match_original_files(
    original_files: list[OriginalNameMapping],
    original_file_mapping: list[Mapping],
    inner_archive_password: str | None,
    archive_extract_folder: str,
) -> list[FileMapping]:
    file_mappings: list[FileMapping] = []
    file_to_extract: dict[str, FilesToExtract] = {}
    compiled_original_file_mapping = compile_mapping_patterns(
        original_file_mapping,
        "original_file_pattern",
    )

    for original_file in original_files:
        for mapping, pattern in compiled_original_file_mapping:
            if mapping.skip_short_name and WINDOWS_SHORT_FILE_PATTERN.match(
                original_file.original_name,
            ):
                continue

            if pattern.match(original_file.original_name):
                extraction_path = os.path.join(
                    archive_extract_folder,
                    Path(original_file.archive).stem,
                )
                extracted_file = os.path.join(extraction_path, original_file.sample_name)

                file_mapping = FileMapping(
                    extracted_file,
                    original_file.archive,
                    original_file.sample_name,
                    original_file.original_name,
                    original_file.creation_date,
                    original_file.modification_date,
                    mapping,
                    original_file.vss,
                    None,
                )

                to_extract = file_to_extract.get(original_file.archive, FilesToExtract())
                if need_rename(original_file.sample_name):
                    renamed_path = rename_file(original_file.sample_name)
                    to_extract.add(original_file.sample_name, renamed_path)
                    file_mapping.file = os.path.join(extraction_path, renamed_path)
                else:
                    to_extract.add(original_file.sample_name, original_file.sample_name)

                file_to_extract[original_file.archive] = to_extract
                file_mappings.append(file_mapping)

    for arch, to_extract in file_to_extract.items():
        extract_folder = os.path.join(archive_extract_folder, Path(arch).stem)
        if to_extract.len() > 0:
            try:
                logger.info(
                    f"Extracting {to_extract.len()} files that match an original file "
                    f"pattern, from archive:'{arch}'"
                )
                extract_7z_files(arch, to_extract, extract_folder, inner_archive_password)
            except Exception as e:
                logger.info(
                    f"An error occured while extracting {to_extract.len()} files "
                    f"from archive:'{arch}', error: {e} "
                )
    return file_mappings


def match_archive_files(
    archive: str,
    sub_archives: list[str],
    archive_file_mapping: list[Mapping],
    original_files: list[OriginalNameMapping],
    password: str | None,
    inner_archive_password: str | None,
    archive_extract_folder: str,
) -> list[FileMapping]:
    valid_mapping: list[FileMapping] = []
    compiled_archive_file_mapping = compile_mapping_patterns(
        archive_file_mapping,
        "archive_file_pattern",
    )

    with py7zr.SevenZipFile(archive, password=password) as f:
        file_list = f.getnames()
        to_extract: list[str] = []

        for file in file_list:
            for mapping, pattern in compiled_archive_file_mapping:
                if pattern.match(file):
                    extracted_file = os.path.join(archive_extract_folder, file)
                    sample_file_name = file.split("/").pop()

                    file_mapping = FileMapping(
                        extracted_file,
                        "",
                        file,
                        None,
                        None,
                        None,
                        mapping,
                        None,
                        None,
                    )
                    if len(sample_file_name) > MAX_FILE_NAME_BYTE_LENGTH:
                        file_mapping.error = (
                            f"File name is too long '{file}', length:{len(sample_file_name)}, "
                            f"maximum allowed:{MAX_FILE_NAME_BYTE_LENGTH}, , archive: '{archive}'"
                        )
                    else:
                        to_extract.append(file)

                    valid_mapping.append(file_mapping)

        if len(to_extract) > 0:
            logger.info(f"Extracting {len(to_extract)} files from archive:'{archive}' ")
            try:
                f.extract(archive_extract_folder, to_extract)
            except Exception as e:
                logger.info(
                    f"An error occured while extracting files from archive:'{archive}', error: {e} "
                )

    file_dict = _build_sample_name_lookup(original_files)
    for sub_archive in sub_archives:
        try:
            _match_inner_archive_files(
                archive,
                compiled_archive_file_mapping,
                inner_archive_password,
                archive_extract_folder,
                valid_mapping,
                file_dict,
                sub_archive,
            )
        except Exception as e:
            logger.info(
                "An error occured while trying to match archive file pattern "
                f"from sub archive :'{archive}/{sub_archive}', error: {e} "
            )
    return valid_mapping


def _build_sample_name_lookup(
    original_files: list[OriginalNameMapping],
) -> dict[str, OriginalNameMapping]:
    file_dict: dict[str, OriginalNameMapping] = {}
    for original in original_files:
        inserted = file_dict.get(original.sample_name)
        if inserted:
            if WINDOWS_SHORT_FILE_PATTERN.match(inserted.original_name):
                file_dict[original.sample_name] = original
        else:
            file_dict[original.sample_name] = original
    return file_dict


def _match_inner_archive_files(
    archive: str,
    archive_file_mapping: list[tuple[Mapping, re.Pattern[str]]],
    inner_archive_password: str | None,
    archive_extract_folder: str,
    valid_mapping: list[FileMapping],
    file_dict: dict[str, OriginalNameMapping],
    inner_archive: str,
) -> None:
    archive_name = Path(inner_archive).stem
    extract_folder = os.path.join(archive_extract_folder, archive_name)
    os.makedirs(extract_folder, exist_ok=True)

    to_extract = _process_inner_archive_file_names(
        inner_archive,
        inner_archive_password,
        archive_file_mapping,
        file_dict,
        archive_extract_folder,
        valid_mapping,
    )

    if to_extract.len() > 0:
        try:
            logger.info(f"Extracting {to_extract.len()} files from archive:'{archive}' ")
            extract_7z_files(inner_archive, to_extract, extract_folder, inner_archive_password)
        except Exception as e:
            logger.info(
                f"An error occured while extracting {to_extract.len()} files "
                f"from archive:'{archive}', error: {e} "
            )


def _process_inner_archive_file_names(
    inner_archive: str,
    inner_archive_password: str | None,
    archive_file_mapping: list[tuple[Mapping, re.Pattern[str]]],
    file_dict: dict[str, OriginalNameMapping],
    archive_extract_folder: str,
    valid_mapping: list[FileMapping],
) -> FilesToExtract:
    to_extract = FilesToExtract()

    with py7zr.SevenZipFile(inner_archive, password=inner_archive_password) as f:
        file_list = f.getnames()
        archive_name = Path(inner_archive).stem
        extraction_path = os.path.join(archive_extract_folder, archive_name)
        for file in file_list:
            for mapping, pattern in archive_file_mapping:
                if pattern.match(file):
                    extracted_file = os.path.join(extraction_path, file)
                    file_mapping = FileMapping(
                        extracted_file,
                        archive_name,
                        file,
                        None,
                        None,
                        None,
                        mapping,
                        None,
                        None,
                    )

                    original = file_dict.get(file)
                    if original:
                        file_mapping.original_file = original.original_name
                        file_mapping.original_creation_date = original.creation_date
                        file_mapping.original_modification_date = original.modification_date
                        file_mapping.vss = original.vss

                    if need_rename(file):
                        renamed_path = rename_file(file)
                        to_extract.add(file, renamed_path)
                        file_mapping.file = os.path.join(extraction_path, renamed_path)
                    else:
                        to_extract.add(file, file)

                    valid_mapping.append(file_mapping)

    return to_extract
