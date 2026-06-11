import csv
import os
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import py7zr

from .matching import OriginalNameMapping

FILE_NAME_MAPPING = "GetThis.csv"


@dataclass
class OriginalFileMappingResult:
    name_mapping: list[OriginalNameMapping]
    errors: list[str]


def build_file_mapping(
    main_archive: str,
    sub_archives: Collection[str],
    password: str | None,
    temp_folder: str,
) -> OriginalFileMappingResult:
    mapping: list[OriginalNameMapping] = []
    errors = []
    for archive in sub_archives:
        archive_name = Path(archive).stem
        try:
            with py7zr.SevenZipFile(archive, password=password) as file7z:
                file_list = file7z.getnames()
                for file in file_list:
                    if file == FILE_NAME_MAPPING:
                        inner_folder = os.path.join(temp_folder, archive_name)

                        file7z.extract(inner_folder, [file])
                        get_this_file = os.path.join(inner_folder, file)
                        _build_file_mapping_list(get_this_file, archive, mapping)

        except Exception as e:
            errors.append(
                f"An error occured while searching for {FILE_NAME_MAPPING} "
                f"in archive {main_archive}/{archive}. Error: {e}"
            )

    return OriginalFileMappingResult(mapping, errors)


def _build_file_mapping_list(
    get_this_file: str,
    archive: str,
    file_mapping: list[OriginalNameMapping],
) -> None:
    with open(get_this_file) as data:
        for line in csv.DictReader(data):
            sample_name = line["SampleName"]
            if sample_name:
                sample_name = sample_name.replace("\\", "/")
                file_mapping.append(
                    OriginalNameMapping(
                        archive,
                        sample_name,
                        line["FullName"],
                        line["CreationDate"],
                        line["LastModificationDate"],
                        line["SnapshotID"],
                    )
                )
