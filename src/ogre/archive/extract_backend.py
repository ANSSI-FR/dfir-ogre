import os
from dataclasses import dataclass

import py7zr
from dfir_ogre_common import extract_7z_file

INNER_TEMP_ARCHIVE = ".inner"


@dataclass
class NestedArchive:
    path: str
    error: str | None


def extract_nested_archives(
    archive: str, password: str | None, temp_folder: str
) -> list[NestedArchive]:
    inner_archive_folder = os.path.join(temp_folder, INNER_TEMP_ARCHIVE)
    os.makedirs(inner_archive_folder, exist_ok=True)
    files_to_extract = []
    inner_archive_path = []
    with py7zr.SevenZipFile(archive, password=password) as file7z:
        file_list = file7z.getnames()
        for file in file_list:
            if file.lower().endswith(".7z"):
                files_to_extract.append(file)

    for file in files_to_extract:
        inner_file = os.path.join(inner_archive_folder, file)
        try:
            extract_7z_file(archive, file, inner_archive_folder, password)
            inner_archive_path.append(NestedArchive(inner_file, None))
        except Exception as e:
            error = (
                f"An error occured while extracting inner_archive:'{file}' "
                f"from archive:'{archive}' , target: '{inner_file}', error:'{e}'"
            )
            inner_archive_path.append(NestedArchive(inner_file, error))

    return inner_archive_path
