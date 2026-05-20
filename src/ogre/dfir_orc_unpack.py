import csv

from datetime import datetime, timezone
import json
import logging
import os
import re
import uuid 
from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Dict, List, Optional, Tuple
from .sevenzip_rename_factory import need_rename, rename_file,MAX_FILE_NAME_BYTE_LENGTH
import dateutil.parser
import py7zr
from dfir_ogre_common import (extract_7z_file,extract_7z_files, FilesToExtract)

from .configuration import Mapping

logger = logging.getLogger(__name__)
# match windows short name ex: \SVA592~1.PF short names are duplicates in the GetThis.csv file
WINDOWS_SHORT_FILE_PATTERN = re.compile(".*~[0-9]+\\.[a-zA-Z0-9_]+", re.IGNORECASE)
EXTRACT_BATCH_SIZE = 10000
FILE_NAME_MAPPING = "GetThis.csv"


@dataclass
class OriginalNameMapping:
    """
    Represents the mapping between an archive file and its original name.
    """

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


@dataclass
class UnpackResult:
    valid_mapping: List[FileMapping]
    errors: List[str]


def unpack_dfir_orc(
    archive: str,
    password: Optional[str],
    inner_archive_password: Optional[str],
    mapping: Collection[Mapping],
    temp_folder: str,
) -> UnpackResult:
    """
    Selectively extract files from a 7z archive based on mapping rules.

    Args:
        archive (str): Path to the 7z archive file.
        password (Optional[str]): Password for the archive (if encrypted).
        inner_archive_password (Optional[str]): Password for nested archives.
        mapping (Collection[Mapping]): Rules to select files for extraction.
        temp_folder (str): Directory to store extracted files.

    Returns:
        UnpackResult: A result object containing:
            - List of successfully extracted file mappings.
            - List of errors encountered during extraction.

    Raises:
        None directly, but exceptions during extraction are caught and returned
        as error messages in the UnpackResult.
    """
    os.makedirs(temp_folder, exist_ok=True)

    #remove p7b extension. if the filename comes from output.json, it references encrypted files
    if archive.endswith("p7b"):
        archive = os.path.splitext(archive)[0]

    if not os.path.isfile(archive):
        return UnpackResult([], [f"'{archive}' not found or is not a file"])

    if not archive.endswith(".7z"):
        return UnpackResult([], [f"'{archive}' is not a 7z file"])

    archive_name = Path(archive).stem
    archive_extract_folder = os.path.join(temp_folder, archive_name)
    os.makedirs(archive_extract_folder, exist_ok=True)

    # Extract nested archives (sub-archives) from the main archive
    try:
        sub_archives_list = _extract_nested_archives(
            archive, password, archive_extract_folder
        )
    except Exception as e:
        return UnpackResult(
            [],
            [
                f"An error occured while extracting sub archives for '{archive}' error:{e}"
            ],
        )
    errors: List[str] = []
    sub_archives = []

    for sub_archive in sub_archives_list:
        if sub_archive.error:
            errors.append(sub_archive.error)
        else:
            sub_archives.append(sub_archive.path)

    # Build file mapping for original files in the archive
    original_files = _build_file_mapping(
        archive, sub_archives, inner_archive_password, archive_extract_folder
    )
    errors = errors + original_files.errors

    # Separate mapping rules into archive-based and original-file-based
    archive_file_mapping: List[Mapping] = []
    original_file_mapping: List[Mapping] = []

    for m in mapping:
        if m.archive_file_pattern:
            archive_file_mapping.append(m)
        elif m.original_file_pattern:
            original_file_mapping.append(m)

    valid_map = []
    valid_archive_mapping = []
    valid_original_mapping = []
    try:
        # Match files against archive-based patterns
        archive_mapping = _match_archive_files(
            archive,
            sub_archives,
            archive_file_mapping,
            original_files.name_mapping,
            password,
            inner_archive_password,
            archive_extract_folder,
        )

        for mapping_candidate in archive_mapping:
            if mapping_candidate.error:
                errors.append(mapping_candidate.error)
            else:
                valid_archive_mapping.append(mapping_candidate)

    except Exception as e:
        errors.append(
            f"An error occured while extracting files from archive match for '{archive}' error:{e}"
        )
    try:
        # Match files against original file patterns
        original_mapping = _match_original_files(
            original_files.name_mapping,
            original_file_mapping,
            inner_archive_password,
            archive_extract_folder,
        )

        for mapping_candidate in original_mapping:
            if mapping_candidate.error:
                errors.append(mapping_candidate.error)
            else:
                valid_original_mapping.append(mapping_candidate)

    except Exception as e:
        errors.append(
            f"An error occured while extracting files from original files match for '{archive}' error:{e}"
        )
     # Combine valid mappings from both strategies
    valid_map = valid_archive_mapping + valid_original_mapping
    return UnpackResult(valid_map, errors)


INNER_TEMP_ARCHIVE = ".inner"


@dataclass
class NestedArchive:
    path: str
    error: Optional[str]


def _extract_nested_archives(
    archive: str, password: Optional[str], temp_folder: str
) -> List[NestedArchive]:
    """
    Extracts nested 7z archives from the main archive and returns their file paths.

    Args:
        archive (str): Path to the main archive file to extract from.
        password (Optional[str]): Optional password for decrypting the archive.
        temp_folder (str): Directory path where extracted files will be stored.

    Returns:
        List[str]: List of file paths to the extracted nested archives.
    """
    inner_archive_folder = os.path.join(temp_folder, INNER_TEMP_ARCHIVE)
    os.makedirs(inner_archive_folder, exist_ok=True)
    files_to_extract = []
    inner_archive_path = []
    with py7zr.SevenZipFile(archive, password=password) as file7z:
        file_list = file7z.getnames()
        for file in file_list:
            if file.lower().endswith(".7z"):
                files_to_extract.append(file)

    # extract inner archive one by one to avoid errors
    for file in files_to_extract:
        inner_file = os.path.join(inner_archive_folder, file)
        try:
            extract_7z_file(archive, file, inner_archive_folder, password)
            inner_archive_path.append(NestedArchive(inner_file, None))
        except Exception as e:
            error = f"An error occured while extracting inner_archive:'{file}' from archive:'{archive}' , target: '{inner_file}', error:'{e}'"
            inner_archive_path.append(NestedArchive(inner_file, error))

    return inner_archive_path



@dataclass
class OriginalFileMappingResult:
    name_mapping: List[OriginalNameMapping]
    errors: List[str]


def _build_file_mapping(
    main_archive,
    sub_archives: Collection[str],
    password: Optional[str],
    temp_folder: str,
) -> OriginalFileMappingResult:
    """
    Search sub-archives for 'GetThis.csv' and build original file name mappings.
    Processes each sub-archive by:
    1. Checking for 'GetThis.csv' file
    2. Extracting the CSV file to temp folder
    3. Parsing the CSV to build name mappings

    Args:
        main_archive: Main archive path
        sub_archives: Collection of sub-archive paths to search
        password: Optional password for archive decryption
        temp_folder: Temporary folder for extraction

    Returns:
        OriginalFileMappingResult containing:
        - List of OriginalNameMapping entries
        - List of error messages for failed archives
    """
    mapping: List[OriginalNameMapping] = []
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
                f"An error occured while searching for {FILE_NAME_MAPPING} in archive {main_archive}/{archive}. Error: {e}"
            )

    return OriginalFileMappingResult(mapping, errors)


def _build_file_mapping_list(
    get_this_file: str, archive: str, file_mapping: List[OriginalNameMapping]
):
    """
    Parse 'GetThis.csv' file and populate original name mappings.

    Args:
        get_this_file: Path to 'GetThis.csv' file
        archive: Name of the archive containing the CSV
        file_mapping: List to append OriginalNameMapping entries to

    """
    with open(get_this_file, "r") as data:
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


def _match_original_files(
    original_files: List[OriginalNameMapping],
    original_file_mapping: List[Mapping],
    inner_archive_password: Optional[str],
    archive_extract_folder: str,
) -> List[FileMapping]:
    """
    Match patterns in `original_file_mapping` against original file names.

    This function:
    1. Filters out Windows short names (e.g., `SVA592~1.PF`) based on `skip_short_name` flags.
    2. Matches original file names against pattern-matched mappings using case-insensitive
       pattern matching.
    3. Builds a list of `ValidMapping` objects for files that match.
    4. Extracts matched files from archives using `py7zr` with the provided password.

    Args:
        original_files: List of `OriginalNameMapping` objects representing files
            to be matched.
        original_file_mapping: List of `Mapping` objects containing pattern rules
            for matching.
        inner_archive_password: Optional password for decrypting archives.
        archive_extract_folder: Base directory for extracting matched files.

    Returns:
        List of `ValidMapping` objects containing extracted file paths and metadata.
    """

    file_mappings: List[FileMapping] = []
    file_to_extract: Dict[str, FilesToExtract] = {}


    for original_file in original_files:
        for mapping in original_file_mapping:
            if mapping.original_file_pattern:
                # skip windows short name ex: \SVA592~1.PF short names are duplicates in the GetThis.csv file
                if mapping.skip_short_name and WINDOWS_SHORT_FILE_PATTERN.match(
                    original_file.original_name,
                ):
                    continue

                try:
                    pattern = re.compile(mapping.original_file_pattern, re.IGNORECASE)
                except Exception as e:
                    raise Exception(f"{e} in regex:{mapping.original_file_pattern}")

                if pattern.match(
                    original_file.original_name,
                ):

                    extraction_path = os.path.join(
                        archive_extract_folder,
                        Path(original_file.archive).stem,
                    )

                    extracted_file = os.path.join(
                        extraction_path,
                        original_file.sample_name,
                    )

                    mapping = FileMapping(
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
                        # if file_name is too long, change its output name to its hex hash
                        renamed_path = rename_file(original_file.sample_name)
                        to_extract.add(original_file.sample_name, renamed_path)
                        mapping.file =  os.path.join(
                            extraction_path,
                            renamed_path,
                        )
                    else:
                        to_extract.add(original_file.sample_name,original_file.sample_name)

                    file_to_extract[original_file.archive] = to_extract

                    file_mappings.append(mapping)

    for arch, to_extract in file_to_extract.items():
        extract_folder = os.path.join(archive_extract_folder, Path(arch).stem)

        if to_extract.len() > 0:
            try:
                logger.info(
                    f"Extracting {to_extract.len()} files that match an original file pattern, from archive:'{arch}'"
                )
                extract_7z_files(arch, to_extract, extract_folder, inner_archive_password )
            except Exception as e:
                logger.info(
                    f"An error occured while extracting {to_extract.len()} files from archive:'{arch}', error: {e} "
                )
    return file_mappings



def _match_archive_files(
    archive: str,
    sub_archives: List[str],
    archive_file_mapping: List[Mapping],
    original_files: List[OriginalNameMapping],
    password: Optional[str],
    inner_archive_password: Optional[str],
    archive_extract_folder: str,
) -> List[FileMapping]:

    """
    Match file patterns from mappings against files in the main archive and sub-archives.
    Processes:
        1. Extracts files from the main archive matching patterns in `archive_file_mapping`.
        2. Processes sub-archives, matching files against the same patterns.
        3. Associates extracted files with original metadata from `original_files`.
        4. Returns a list of `ValidMapping` objects for further processing.

    Args:
        archive: Path to the main archive file.
        sub_archives: List of paths to sub-archive files.
        archive_file_mapping: List of mappings defining file patterns to match against archive contents.
        original_files: List of original file metadata for mapping against extracted files.
        password: Password for the main archive.
        inner_archive_password: Password for sub-archives.
        archive_extract_folder: Directory to extract matched files to.

    Returns:
        List[ValidMapping]: List of valid file extraction mappings, including
            extracted paths, archive sources, and original file metadata.
    """

    valid_mapping: List[FileMapping] = []

    # Match pattern from main archive
    with py7zr.SevenZipFile(archive, password=password) as f:
        file_list = f.getnames()
        to_extract: List[str] = []

        for file in file_list:
            for mapping in archive_file_mapping:
                if mapping.archive_file_pattern:
                    try:
                        pattern = re.compile(
                            mapping.archive_file_pattern, re.IGNORECASE
                        )
                    except Exception as e:
                        raise Exception(f"{e} in regex:{mapping.archive_file_pattern}")

                    if pattern.match(
                        file,
                    ):

                        extracted_file = os.path.join(
                            archive_extract_folder,
                            file,
                        )

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
                            file_mapping.error = f"File name is too long '{file}', length:{len(sample_file_name)}, maximum allowed:{MAX_FILE_NAME_BYTE_LENGTH}, , archive: '{archive}'"
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

    # build a mapping dict, giving priority to file_names that are not windows short files
    file_dict: Dict[str, OriginalNameMapping] = {}
    for original in original_files:
        inserted = file_dict.get(original.sample_name, None)
        if inserted:
            if WINDOWS_SHORT_FILE_PATTERN.match(
                inserted.original_name,
            ):
                file_dict[original.sample_name] = original
        else:
            file_dict[original.sample_name] = original

    # match pattern from sub archives
    for sub_archive in sub_archives:
        try:
            _match_inner_archive_files(
                archive,
                archive_file_mapping,
                inner_archive_password,
                archive_extract_folder,
                valid_mapping,
                file_dict,
                sub_archive,
            )
        except Exception as e:
            logger.info(
                f"An error occured while trying to match archive file pattern from sub archive :'{archive}/{sub_archive}', error: {e} "
            )
    return valid_mapping


def _match_inner_archive_files(
    archive: str,
    archive_file_mapping: List[Mapping],
    inner_archive_password: Optional[str],
    archive_extract_folder: str,
    valid_mapping: List[FileMapping],
    file_dict: Dict[str, OriginalNameMapping],
    inner_archive: str,
):
    """
    Match archive name pattern in inner archives and extract related files
    """
    archive_name = Path(inner_archive).stem
    extract_folder = os.path.join(archive_extract_folder, archive_name)
    os.makedirs(extract_folder, exist_ok=True)

    to_extract = _process_inner_archive_file_names(
        inner_archive,inner_archive_password,archive_file_mapping, file_dict,archive_extract_folder, valid_mapping
    )

    if to_extract.len() > 0:
        try:
            logger.info(f"Extracting {to_extract.len()} files from archive:'{archive}' ")
            extract_7z_files(inner_archive, to_extract, extract_folder, inner_archive_password )
        except Exception as e:
            logger.info(
                f"An error occured while extracting {to_extract.len()} files from archive:'{archive}', error: {e} "
            )



def _process_inner_archive_file_names(
    inner_archive: str,
    inner_archive_password: Optional[str],
    archive_file_mapping: List[Mapping],
    file_dict: Dict[str, OriginalNameMapping],
    archive_extract_folder: str,
    valid_mapping: List[FileMapping],
) -> FilesToExtract:
    """Create ``FileMapping`` objects for files that match a pattern.

    Returns the subset of *file_list* that should be extracted.
    """
    to_extract = FilesToExtract()

    # match files in the archive agains a regexp
    with py7zr.SevenZipFile(inner_archive, password=inner_archive_password) as f:
        file_list = f.getnames()

        archive_name = Path(inner_archive).stem
        extraction_path = os.path.join(
            archive_extract_folder,
            archive_name
        )
        for file in file_list:
            for mapping in archive_file_mapping:
                if mapping.archive_file_pattern:
                    try:
                        pattern = re.compile(
                            mapping.archive_file_pattern, re.IGNORECASE
                        )
                    except Exception as e:
                        raise Exception(f"{e} in regex:{mapping.archive_file_pattern}")

                    if pattern.match(
                        file,
                    ):
                        extracted_file = os.path.join(
                            extraction_path,
                            file
                        )
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
                            file_mapping.original_modification_date = (
                                original.modification_date
                            )
                            file_mapping.vss = original.vss

                        if need_rename(file):
                            renamed_path = rename_file(file)
                            to_extract.add(file, renamed_path)
                            file_mapping.file =  os.path.join(
                                extraction_path,
                                renamed_path,
                            )
                        else:
                            to_extract.add(file, file)

                        valid_mapping.append(file_mapping)

    return to_extract


@dataclass
class OrcOutcome:
    id: str
    computer_name: str
    date: datetime
    dir_tree: Optional[str]
    archives: List[str]


def load_archive_metadata(archive_path: str) -> OrcOutcome:
    """Load metadata and archive list from the given archive path.

    If the path ends with `.json`, it is loaded directly using `_load_outcome_file`.

    If the path contains multiple paths separated by commas, the function processes the first archive path to extract the machine name using a regex
    pattern. If no match is found, the machine name is derived from the stem of the first archive path.

    Args:
        archive_path (str): A string representing a single archive path or multiple paths
            separated by commas.

    Returns:
        OrcOutcome: An object containing:
            - `id`: A UUID for the outcome.
            - `computer_name`: Extracted from the archive filename via regex, or the stem
              of the first archive path if no match is found.
            - `start_date`: The current UTC timestamp in ISO format.
            - `archives`: A list of processed archive paths.
    """
    archive_path = archive_path.strip()

    if archive_path.startswith("{"):
        return _load_json_definition(archive_path)

    if archive_path.endswith(".json"):
        return _load_outcome_file(archive_path)

    archives = []

    for arch in archive_path.split(","):
        arch = arch.strip()
        if arch:
            archives.append(arch)

    pattern = re.compile(
        ".+_(WorkStation|Server|DomainController)_(?P<machine_name>.+)_.+.7z"
    )
    matched = pattern.match(archives[0])
    if matched and "machine_name" in pattern.groupindex.keys():
        computer_name = matched.group("machine_name")
    else:
        computer_name = Path(archives[0]).stem

    start_date = datetime.now(timezone.utc)
    id = str(uuid.uuid4())

    return OrcOutcome(id, computer_name, start_date, None, archives)


def _load_json_definition(archive_path: str) -> OrcOutcome:
    json_data = json.loads(archive_path)
    if isinstance(json_data, dict):
        archives: List[str] = json_data.get("unencrypted_data_files", [])
        if not archives:
            raise Exception(
                "No unencrypted archives defined in the json archive definition"
            )

        computer_name = str(json_data.get("hostname", None))
        if not computer_name:
            raise Exception(
                "The hostname is not defined in the json archive definition"
            )

        id = str(json_data.get("id", ""))
        if not id:
            raise Exception("The orc id is not defined in the json archive definition")

        timestamp: str = json_data.get(
            "timestamp", ""
        )  # datetime.strptime('Mon Feb 15 2010', '%a %b %d %Y').strftime('%d/%m/%Y')
        if not timestamp:
            raise Exception("No timestamp  defined in the json archive definition")

        date = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)


        dir_tree = json_data.get("dir_tree", None)

        return OrcOutcome(id, computer_name, date, dir_tree, archives)
    else:
        raise Exception("Invalid json archive definition")


def _load_outcome_file(outcome_file) -> OrcOutcome:
    """
    Load metadata and archives from an Orc outcome file.

    Process:
    1. Parses JSON data from the file.
    2. Extracts 'id', 'computer_name', 'start_date', and 'command_set' from the 'outcome' section.
    3. Generates a UUID if 'id' is missing.
    4. Derives computer_name from:
        - Existing 'computer_name' field
        - or Filename regex match
        - or File stem if no match found
    5. Uses current time if 'start_date' is missing.
    6. Collects archive paths from command_set entries.

    Args:
        outcome_file (str): Path to the outcome.json file to process.

    Returns:
        OrcOutcome: Object containing metadata and archive paths.

    Raises:
        Exception: If the file is not a valid Orc outcome file (missing 'dfir-orc', 'outcome', or 'archive' nodes).
    """
    with open(outcome_file) as f:
        json_data = json.load(f)
        dfir_orc = json_data.get("dfir-orc", None)
        if dfir_orc is None:
            raise Exception(
                f"{outcome_file} is not a valid Orc outcome file: 'dfir-orc' root node not found"
            )

        outcome = dfir_orc.get("outcome", None)
        if outcome is None:
            raise Exception(
                f"{outcome_file} is not a valid Orc outcome file: 'outcome' node not found"
            )

        id = outcome.get("id", None)
        if id:
            id = id.lstrip(id[0]).rstrip(id[-1])
        else:
            id = str(uuid.uuid4())

        computer_name = outcome.get("computer_name", None)
        if computer_name is None:
            pattern = re.compile(
                ".+_(WorkStation|Server|DomainController)_(?P<machine_name>.+)_.+.json"
            )
            matched = pattern.match(outcome_file)
            if matched and "machine_name" in pattern.groupindex.keys():
                computer_name = matched.group("machine_name")
            else:
                computer_name = Path(outcome_file).stem

        start_date = outcome.get("start", None)
        if start_date is None:
            timestamp = datetime.now(timezone.utc)
        else:
            timestamp = dateutil.parser.isoparse(start_date).replace(tzinfo=timezone.utc)


        archives: List[str] = []
        command_set: Dict = outcome.get("command_set", {})

        path = Path(outcome_file).parent

        for command in command_set:
            archive = command.get("archive", None)
            if archive is None:
                raise Exception(
                    f"{outcome_file} is not a valid Orc outcome file: command does not contains the 'archive' parameter "
                )
            archive_name = archive.get("name", None)
            archive_path = str(path / archive_name)
            if archive_name:
                archives.append(archive_path)
    return OrcOutcome(id, computer_name, timestamp, None, archives)
