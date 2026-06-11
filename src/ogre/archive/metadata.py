from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import dateutil.parser


@dataclass
class OrcOutcome:
    id: str
    computer_name: str
    date: datetime
    dir_tree: str | None
    archives: list[str]


def load_archive_metadata(archive_path: str) -> OrcOutcome:
    """Load metadata and archive list from a JSON definition, outcome file, or archive path."""
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

    pattern = re.compile(".+_(WorkStation|Server|DomainController)_(?P<machine_name>.+)_.+.7z")
    matched = pattern.match(archives[0])
    if matched and "machine_name" in pattern.groupindex.keys():
        computer_name = matched.group("machine_name")
    else:
        computer_name = Path(archives[0]).stem

    start_date = datetime.now(timezone.utc)
    orc_id = str(uuid.uuid4())

    return OrcOutcome(orc_id, computer_name, start_date, None, archives)


def _load_json_definition(archive_path: str) -> OrcOutcome:
    json_data = json.loads(archive_path)
    if not isinstance(json_data, dict):
        raise Exception("Invalid json archive definition")

    archives: list[str] = json_data.get("unencrypted_data_files", [])
    if not archives:
        raise Exception("No unencrypted archives defined in the json archive definition")

    computer_name = str(json_data.get("hostname", None))
    if not computer_name:
        raise Exception("The hostname is not defined in the json archive definition")

    orc_id = str(json_data.get("id", ""))
    if not orc_id:
        raise Exception("The orc id is not defined in the json archive definition")

    timestamp: str = json_data.get("timestamp", "")
    if not timestamp:
        raise Exception("No timestamp  defined in the json archive definition")

    date = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    dir_tree = json_data.get("dir_tree", None)

    return OrcOutcome(orc_id, computer_name, date, dir_tree, archives)


def _load_outcome_file(outcome_file: str) -> OrcOutcome:
    """
    Load metadata and archives from an ORC outcome file.
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

        orc_id = outcome.get("id", None)
        if orc_id:
            orc_id = orc_id.lstrip(orc_id[0]).rstrip(orc_id[-1])
        else:
            orc_id = str(uuid.uuid4())

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

        archives: list[str] = []
        command_set: list[dict] = outcome.get("command_set", {})
        path = Path(outcome_file).parent

        for command in command_set:
            archive = command.get("archive", None)
            if archive is None:
                raise Exception(
                    f"{outcome_file} is not a valid Orc outcome file: command does not "
                    f"contains the 'archive' parameter "
                )
            archive_name = archive.get("name", None)
            archive_path = str(path / archive_name)
            if archive_name:
                archives.append(archive_path)
    return OrcOutcome(orc_id, computer_name, timestamp, None, archives)
