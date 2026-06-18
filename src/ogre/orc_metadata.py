import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import dateutil.parser


@dataclass
class OrcOutcome:
    id: str
    computer_name: str
    date: datetime
    dir_tree: Optional[str]
    archives: List[str]


def load_archive_metadata(archive_path: str) -> OrcOutcome:
    archive_path = archive_path.strip()
    if not archive_path:
        raise Exception("No archive path provided")

    if archive_path[0] in "{[":
        return _load_json_definition(archive_path)

    if archive_path.endswith(".json"):
        return _load_outcome_file(archive_path)

    archives = [arch.strip() for arch in archive_path.split(",") if arch.strip()]
    if not archives:
        raise Exception("No archive path provided")

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
    if not isinstance(json_data, dict):
        raise Exception("Invalid json archive definition")

    archives: List[str] = json_data.get("unencrypted_data_files", [])
    if not archives:
        raise Exception("No unencrypted archives defined in the json archive definition")

    computer_name = json_data.get("hostname")
    if not computer_name:
        raise Exception("The hostname is not defined in the json archive definition")

    id = str(json_data.get("id", ""))
    if not id:
        raise Exception("The orc id is not defined in the json archive definition")

    timestamp: str = json_data.get("timestamp", "")
    if not timestamp:
        raise Exception("No timestamp  defined in the json archive definition")

    date = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    dir_tree = json_data.get("dir_tree", None)

    return OrcOutcome(id, str(computer_name), date, dir_tree, archives)


def _load_outcome_file(outcome_file) -> OrcOutcome:
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
        command_set = outcome.get("command_set", [])
        if not isinstance(command_set, list):
            raise Exception(
                f"{outcome_file} is not a valid Orc outcome file: 'command_set' node must be a list"
            )

        path = Path(outcome_file).parent

        for command in command_set:
            if not isinstance(command, dict):
                raise Exception(
                    f"{outcome_file} is not a valid Orc outcome file: command entry must be an object"
                )
            archive = command.get("archive", None)
            if not isinstance(archive, dict):
                raise Exception(
                    f"{outcome_file} is not a valid Orc outcome file: command does not contains the 'archive' parameter "
                )
            archive_name = archive.get("name", None)
            if not archive_name:
                raise Exception(
                    f"{outcome_file} is not a valid Orc outcome file: archive name is empty"
                )
            archive_path = str(path / archive_name)
            archives.append(archive_path)
    return OrcOutcome(id, computer_name, timestamp, None, archives)
