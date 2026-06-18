# ORC Unpack And Parser Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `dfir_orc_unpack.py` and `commands.py` into focused modules while hardening targeted ORC metadata, mapping, parser execution, and parser statistics failures.

**Architecture:** Keep `ogre.dfir_orc_unpack` and `ogre.commands` as compatibility facades so existing imports continue to work. Move implementation into `orc_metadata.py`, `orc_mapping.py`, `orc_unpacker.py`, `parser_results.py`, and `parser_execution.py`; add failing tests before each behavior change and use the existing real-archive tests to verify moved extraction behavior.

**Tech Stack:** Python 3.10, `unittest`, `pytest` via `uv run --with pytest python -m pytest`, `py7zr`, `dfir_ogre_common`, `dateutil`.

---

## File Structure

- Create `src/ogre/parser_results.py`: parser result dataclasses, metadata serialization, report conversion, safe row/sec finalization.
- Create `src/ogre/parser_execution.py`: single and batch parser lookup/execution, timing, and exception capture.
- Modify `src/ogre/commands.py`: keep `list_parsers` and re-export parser result/execution symbols for compatibility.
- Create `src/ogre/orc_metadata.py`: `OrcOutcome`, archive metadata parsing, inline JSON parsing, outcome file parsing, comma-separated archive parsing.
- Create `src/ogre/orc_mapping.py`: ORC mapping dataclasses, constants, regex helpers, mapping partitioning, original-name lookup.
- Create `src/ogre/orc_unpacker.py`: `unpack_dfir_orc`, nested archive extraction, `GetThis.csv` discovery, archive/original matching.
- Modify `src/ogre/dfir_orc_unpack.py`: re-export public dataclasses/functions from the new ORC modules.
- Modify `src/ogre/run_preparation.py`: import moved dataclasses/functions from the compatibility facade or focused modules only where needed.
- Add `test/test_parser_results.py`: focused parser result hardening tests.
- Add `test/test_parser_execution.py`: parser execution compatibility and empty-report tests.
- Add `test/test_orc_metadata.py`: focused ORC metadata hardening tests.
- Add `test/test_orc_mapping.py`: regex-context and mapping-helper tests.
- Add `test/test_orc_facades.py`: compatibility import identity tests for `ogre.dfir_orc_unpack` and `ogre.commands`.

## Task 1: Extract Parser Result Helpers

**Files:**
- Create: `src/ogre/parser_results.py`
- Create: `test/test_parser_results.py`
- Modify: `src/ogre/commands.py`

- [ ] **Step 1: Write failing parser result tests**

Create `test/test_parser_results.py`:

```python
from unittest import TestCase

from dfir_ogre_common import Metadata, RunReport

from ogre.parser_results import (
    RunResult,
    apply_report_to_result,
    create_run_result,
    finalize_run_result,
    metadata_to_dict,
)


class TestParserResults(TestCase):
    def test_finalize_run_result_sets_zero_row_sec_when_elapsed_is_zero(self):
        result = RunResult(
            "mapping",
            0,
            None,
            0,
            0,
            0,
            "Parser",
            "module.name",
            "2026-06-18T00:00:00+00:00",
            {},
            [],
        )

        finalized = finalize_run_result(result, 0)

        self.assertIs(finalized, result)
        self.assertEqual(finalized.rows, 0)
        self.assertEqual(finalized.time_s, 0)
        self.assertEqual(finalized.row_sec, 0)

    def test_apply_report_to_result_accepts_empty_output_reports(self):
        result = create_run_result(
            "mapping",
            "Parser",
            "module.name",
            "2026-06-18T00:00:00+00:00",
            {},
        )
        report = RunReport()

        apply_report_to_result(result, report)
        finalized = finalize_run_result(result, 0.25)

        self.assertEqual(finalized.last_error, None)
        self.assertEqual(finalized.num_errors, 0)
        self.assertEqual(finalized.output, [])
        self.assertEqual(finalized.rows, 0)
        self.assertEqual(finalized.row_sec, 0)

    def test_metadata_to_dict_preserves_current_metadata_contract(self):
        metadata = Metadata("COMPUTER")
        metadata.orc_id = "orc-id"
        metadata.folder = "case-folder"
        metadata.archive = "archive.7z"
        metadata.subarchive = "inner.7z"
        metadata.archive_filename = "archive/path.txt"
        metadata.original_filename = "C:\\\\path.txt"
        metadata.vss = "{00000000-0000-0000-0000-000000000000}"

        result = metadata_to_dict(metadata)

        self.assertEqual(result["computer"], "COMPUTER")
        self.assertEqual(result["orc_id"], "orc-id")
        self.assertEqual(result["folder"], "case-folder")
        self.assertEqual(result["archive"], "archive.7z")
        self.assertEqual(result["subarchive"], "inner.7z")
        self.assertEqual(result["archive_filename"], "archive/path.txt")
        self.assertEqual(result["original_filename"], "C:\\\\path.txt")
        self.assertEqual(result["vss"], "{00000000-0000-0000-0000-000000000000}")
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest test/test_parser_results.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ogre.parser_results'`.

- [ ] **Step 3: Create `parser_results.py`**

Create `src/ogre/parser_results.py`:

```python
from dataclasses import dataclass
from typing import Any

from dfir_ogre_common import Metadata


@dataclass
class FileStat:
    file_name: str
    num_rows: int
    output_type: str
    format: str
    date_format: str
    with_timeline: bool
    with_qualifiers: bool
    include_empty: bool


@dataclass
class OutputStat:
    last_error: str | None
    file_stats: list[FileStat]


@dataclass
class RunResult:
    mapping_label: str
    num_errors: int
    last_error: str | None
    rows: int
    time_s: float
    row_sec: float
    parser: str
    module: str
    start_date: str
    metadata: dict[str, str | None]
    output: list[OutputStat]


def create_run_result(
    mapping_label: str,
    parser: str,
    module: str,
    start_date: str,
    metadata: dict[str, str | None],
) -> RunResult:
    return RunResult(
        mapping_label,
        0,
        None,
        0,
        0,
        0,
        parser,
        module,
        start_date,
        metadata,
        [],
    )


def apply_report_to_result(run_result: RunResult, report: Any) -> None:
    run_result.last_error = report.last_error
    run_result.num_errors = report.num_errors

    for out_report in report.output_reports or []:
        output_stat = OutputStat(out_report.last_error, [])
        for file_report in out_report.file_reports:
            output_stat.file_stats.append(
                FileStat(
                    file_report.file_name,
                    file_report.num_lines,
                    file_report.output_type,
                    file_report.format,
                    file_report.date_format,
                    file_report.with_timeline,
                    file_report.with_qualifiers,
                    file_report.include_empty,
                )
            )
        run_result.output.append(output_stat)


def finalize_run_result(run_result: RunResult, elapsed_s: float) -> RunResult:
    rows = 0
    for stat in run_result.output:
        for file_stat in stat.file_stats:
            rows += file_stat.num_rows

    run_result.rows = rows
    run_result.time_s = round(elapsed_s, 3)
    if elapsed_s <= 0 or rows == 0:
        run_result.row_sec = 0
    else:
        run_result.row_sec = round(rows / elapsed_s, 0)
    return run_result


def metadata_to_dict(metadata: Metadata) -> dict:
    meta_dict = {}
    meta_dict["computer"] = metadata.computer

    if metadata.orc_id:
        meta_dict["orc_id"] = metadata.orc_id

    if metadata.folder:
        meta_dict["folder"] = metadata.folder

    if metadata.archive:
        meta_dict["archive"] = metadata.archive

    if metadata.subarchive:
        meta_dict["subarchive"] = metadata.subarchive

    if metadata.archive_filename:
        meta_dict["archive_filename"] = metadata.archive_filename

    if metadata.original_filename:
        meta_dict["original_filename"] = metadata.original_filename

    if metadata.vss:
        meta_dict["vss"] = metadata.vss

    if metadata.creation_date:
        meta_dict["creation_date"] = metadata.creation_date.isoformat()

    if metadata.modif_date:
        meta_dict["modif_date"] = metadata.modif_date.isoformat()

    return meta_dict
```

- [ ] **Step 4: Wire `commands.py` to use parser result helpers**

In `src/ogre/commands.py`, remove local `FileStat`, `OutputStat`, `RunResult`, and `metadata_to_dict` definitions. Add this import near the other local imports:

```python
from .parser_results import (
    FileStat,
    OutputStat,
    RunResult,
    apply_report_to_result,
    create_run_result,
    finalize_run_result,
    metadata_to_dict,
)
```

In `run_parser`, replace the current `RunResult(...)` construction with:

```python
    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        metadata_to_dict(entry.metadata),
    )
```

Inside the successful parser branch in `run_parser`, replace the manual output-report loop with:

```python
                apply_report_to_result(run_result, report)
```

Replace the success return block in `run_parser` with:

```python
        return finalize_run_result(run_result, run_result.time_s)
```

Immediately before `break` in the successful parser branch, store the elapsed time:

```python
            run_result.time_s = end - start
```

In `run_batch_parser`, use the same pattern with an empty metadata dictionary:

```python
    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        {},
    )
```

Inside the successful batch parser branch, replace the manual output-report loop with:

```python
                apply_report_to_result(run_result, report)
```

Replace the success return block in `run_batch_parser` with:

```python
        return finalize_run_result(run_result, run_result.time_s)
```

Immediately before `break` in the successful batch parser branch, store:

```python
            run_result.time_s = end - start
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_parser_results.py test/test_commands.py test/test_commands_hardening.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ogre/parser_results.py src/ogre/commands.py test/test_parser_results.py
git commit -m "refactor: extract parser result helpers"
```

## Task 2: Extract Parser Execution

**Files:**
- Create: `src/ogre/parser_execution.py`
- Create: `test/test_parser_execution.py`
- Modify: `src/ogre/commands.py`

- [ ] **Step 1: Write failing parser execution compatibility tests**

Create `test/test_parser_execution.py`:

```python
from unittest import TestCase

from ogre.commands import RunResult as CommandsRunResult
from ogre.commands import run_batch_parser as commands_run_batch_parser
from ogre.commands import run_parser as commands_run_parser
from ogre.parser_execution import run_batch_parser, run_parser
from ogre.parser_results import RunResult


class TestParserExecution(TestCase):
    def test_commands_re_exports_parser_execution_functions(self):
        self.assertIs(commands_run_parser, run_parser)
        self.assertIs(commands_run_batch_parser, run_batch_parser)

    def test_commands_re_exports_run_result_type(self):
        self.assertIs(CommandsRunResult, RunResult)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest test/test_parser_execution.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ogre.parser_execution'`.

- [ ] **Step 3: Create `parser_execution.py`**

Create `src/ogre/parser_execution.py`:

```python
import importlib
import time
from datetime import datetime, timezone

from dfir_ogre_common import BatchEntry, OgreBatchedPlugin, OgrePlugin

from .parser_results import (
    RunResult,
    apply_report_to_result,
    create_run_result,
    finalize_run_result,
    metadata_to_dict,
)
from .run_preparation import OgreRunConfiguration


def _start_date() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _find_parser(parser_classes, command: str):
    for parser_class in parser_classes:
        parser = parser_class()
        if parser.description().get_command() == command:
            return parser
    return None


def run_parser(entry: BatchEntry, config: OgreRunConfiguration) -> RunResult:
    _ = importlib.import_module(config.module)
    start_date = _start_date()
    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        metadata_to_dict(entry.metadata),
    )

    parser = _find_parser(OgrePlugin.__subclasses__(), config.parser)
    if parser is None:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(
            entry.file,
            config.plugin_file,
            entry.run_config,
            entry.metadata,
        )
        apply_report_to_result(run_result, report)
    except Exception as error:
        run_result.last_error = f"{error}"
    end = time.time()

    return finalize_run_result(run_result, end - start)


def run_batch_parser(config: OgreRunConfiguration) -> RunResult:
    _ = importlib.import_module(config.module)
    start_date = _start_date()
    run_result = create_run_result(
        config.mapping_label,
        config.parser,
        config.module,
        start_date,
        {},
    )

    parser = _find_parser(OgreBatchedPlugin.__subclasses__(), config.parser)
    if parser is None:
        raise TypeError(f"parser {config.parser} not found")

    start = time.time()
    try:
        report = parser.parse(config.batch_entries, config.plugin_file)
        apply_report_to_result(run_result, report)
    except Exception as error:
        run_result.last_error = f"{error}"
    end = time.time()

    return finalize_run_result(run_result, end - start)
```

- [ ] **Step 4: Slim `commands.py` to re-export parser execution**

In `src/ogre/commands.py`, remove `run_parser` and `run_batch_parser`. Remove imports that are only used by those functions: `time`, `datetime`, `timezone`, `BatchEntry`, `Metadata`, and `OgreBatchedPlugin`.

Keep `OgrePlugin` and `PluginDescription` for `list_parsers`.

Add this import:

```python
from .parser_execution import run_batch_parser, run_parser
```

Keep these imports from `parser_results.py` so compatibility imports still work:

```python
from .parser_results import FileStat, OutputStat, RunResult, metadata_to_dict
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_parser_execution.py test/test_parser_results.py test/test_commands.py test/test_commands_hardening.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ogre/parser_execution.py src/ogre/commands.py test/test_parser_execution.py
git commit -m "refactor: extract parser execution"
```

## Task 3: Extract And Harden ORC Metadata Parsing

**Files:**
- Create: `src/ogre/orc_metadata.py`
- Create: `test/test_orc_metadata.py`
- Modify: `src/ogre/dfir_orc_unpack.py`

- [ ] **Step 1: Write failing ORC metadata hardening tests**

Create `test/test_orc_metadata.py`:

```python
import json
import os

from ogre.orc_metadata import load_archive_metadata

from .hardening_helpers import TempFolderTestCase


class TestOrcMetadata(TempFolderTestCase):
    def test_empty_archive_metadata_input_raises_clear_error(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata("   ")

        self.assertIn("No archive path provided", str(context.exception))

    def test_json_archive_definition_must_be_object(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata('["test/data/archive/SampleOrc.7z"]')

        self.assertIn("Invalid json archive definition", str(context.exception))

    def test_comma_separated_archives_rejects_empty_values(self):
        with self.assertRaises(Exception) as context:
            load_archive_metadata(" , ")

        self.assertIn("No archive path provided", str(context.exception))

    def test_json_archive_definition_requires_hostname_without_stringifying_none(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": ["test/data/archive/SampleOrc.7z"]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "The hostname is not defined in the json archive definition",
            str(context.exception),
        )

    def test_outcome_file_requires_command_set_list(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": {"archive": {"name": "SampleOrc.7z"}},
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'command_set' node must be a list", str(context.exception))

    def test_outcome_file_requires_archive_name(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            json.dump(
                {
                    "dfir-orc": {
                        "outcome": {
                            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
                            "computer_name": "HOST",
                            "command_set": [{"archive": {}}],
                        }
                    }
                },
                file,
            )

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("archive name is empty", str(context.exception))
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest test/test_orc_metadata.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ogre.orc_metadata'`.

- [ ] **Step 3: Create `orc_metadata.py`**

Create `src/ogre/orc_metadata.py` by moving `OrcOutcome`, `load_archive_metadata`, `_load_json_definition`, and `_load_outcome_file` out of `dfir_orc_unpack.py`, then apply these exact hardening changes:

```python
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
```

In `_load_json_definition`, replace the current object and required-field checks with:

```python
def _load_json_definition(archive_path: str) -> OrcOutcome:
    json_data = json.loads(archive_path)
    if not isinstance(json_data, dict):
        raise Exception("Invalid json archive definition")

    archives: List[str] = json_data.get("unencrypted_data_files", [])
    if not archives:
        raise Exception(
            "No unencrypted archives defined in the json archive definition"
        )

    computer_name = json_data.get("hostname")
    if not computer_name:
        raise Exception(
            "The hostname is not defined in the json archive definition"
        )

    id = str(json_data.get("id", ""))
    if not id:
        raise Exception("The orc id is not defined in the json archive definition")

    timestamp: str = json_data.get("timestamp", "")
    if not timestamp:
        raise Exception("No timestamp  defined in the json archive definition")

    date = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
    dir_tree = json_data.get("dir_tree", None)

    return OrcOutcome(id, str(computer_name), date, dir_tree, archives)
```

In `_load_outcome_file`, add these checks after reading `command_set`:

```python
        command_set = outcome.get("command_set", [])
        if not isinstance(command_set, list):
            raise Exception(
                f"{outcome_file} is not a valid Orc outcome file: 'command_set' node must be a list"
            )
```

Inside the `for command in command_set:` loop, use:

```python
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
```

- [ ] **Step 4: Re-export metadata from `dfir_orc_unpack.py`**

In `src/ogre/dfir_orc_unpack.py`, remove the local `OrcOutcome`, `load_archive_metadata`, `_load_json_definition`, and `_load_outcome_file` definitions. Add:

```python
from .orc_metadata import OrcOutcome, load_archive_metadata
```

Remove imports from `dfir_orc_unpack.py` that were only used by metadata parsing after the move: `datetime`, `timezone`, `json`, `uuid`, and `dateutil.parser` if no longer used in that file.

- [ ] **Step 5: Run focused and compatibility tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_orc_metadata.py test/test_dfir_orc_unpack.py test/test_dfir_orc_unpack_hardening.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ogre/orc_metadata.py src/ogre/dfir_orc_unpack.py test/test_orc_metadata.py
git commit -m "refactor: extract orc metadata loading"
```

## Task 4: Extract ORC Mapping Helpers

**Files:**
- Create: `src/ogre/orc_mapping.py`
- Create: `test/test_orc_mapping.py`
- Modify: `src/ogre/dfir_orc_unpack.py`

- [ ] **Step 1: Write failing ORC mapping tests**

Create `test/test_orc_mapping.py`:

```python
from unittest import TestCase

from ogre.configuration import Mapping
from ogre.orc_mapping import (
    build_original_lookup,
    compile_mapping_pattern,
    partition_mappings,
)


class TestOrcMapping(TestCase):
    def _mapping(
        self,
        archive_pattern=None,
        original_pattern=None,
        label="label",
        skip_short_name=True,
    ):
        return Mapping(
            archive_pattern,
            original_pattern,
            "plugin.xml",
            label,
            skip_short_name,
            True,
            10,
            {},
            [],
        )

    def test_partition_mappings_splits_archive_and_original_patterns(self):
        archive_mapping = self._mapping(archive_pattern=".*txt")
        original_mapping = self._mapping(original_pattern=".*evtx")

        archive_mappings, original_mappings = partition_mappings(
            [archive_mapping, original_mapping]
        )

        self.assertEqual(archive_mappings, [archive_mapping])
        self.assertEqual(original_mappings, [original_mapping])

    def test_compile_mapping_pattern_reports_label_and_pattern(self):
        mapping = self._mapping(archive_pattern="\\Lite", label="broken")

        with self.assertRaises(Exception) as context:
            compile_mapping_pattern(mapping, "archive_file_pattern")

        message = str(context.exception)
        self.assertIn("archive_file_pattern", message)
        self.assertIn("\\Lite", message)
        self.assertIn("broken", message)

    def test_build_original_lookup_prefers_non_short_name(self):
        from ogre.orc_mapping import OriginalNameMapping

        short = OriginalNameMapping(
            "Event.7z",
            "sample.evtx",
            "\\\\WINDOWS\\\\SVA592~1.PF",
            None,
            None,
            "vss",
        )
        long = OriginalNameMapping(
            "Event.7z",
            "sample.evtx",
            "\\\\Windows\\\\Prefetch\\\\sample.evtx",
            None,
            None,
            "vss",
        )

        result = build_original_lookup([short, long])

        self.assertEqual(result["sample.evtx"], long)
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest test/test_orc_mapping.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'ogre.orc_mapping'`.

- [ ] **Step 3: Create `orc_mapping.py`**

Create `src/ogre/orc_mapping.py`:

```python
import re
from dataclasses import dataclass
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
```

- [ ] **Step 4: Move mapping dataclasses and helpers out of `dfir_orc_unpack.py`**

In `src/ogre/dfir_orc_unpack.py`, remove local definitions for:

```python
WINDOWS_SHORT_FILE_PATTERN
EXTRACT_BATCH_SIZE
FILE_NAME_MAPPING
INNER_TEMP_ARCHIVE
OriginalNameMapping
FileMapping
UnpackResult
NestedArchive
OriginalFileMappingResult
```

Add this import:

```python
from .orc_mapping import (
    FILE_NAME_MAPPING,
    INNER_TEMP_ARCHIVE,
    WINDOWS_SHORT_FILE_PATTERN,
    FileMapping,
    NestedArchive,
    OriginalFileMappingResult,
    OriginalNameMapping,
    UnpackResult,
    build_original_lookup,
    compile_mapping_pattern,
    partition_mappings,
)
```

In `unpack_dfir_orc`, replace the manual mapping split with:

```python
    archive_file_mapping, original_file_mapping = partition_mappings(mapping)
```

In `_match_original_files`, replace:

```python
                    pattern = re.compile(mapping.original_file_pattern, re.IGNORECASE)
```

with:

```python
                    pattern = compile_mapping_pattern(
                        mapping, "original_file_pattern"
                    )
```

In `_match_archive_files` and `_process_inner_archive_file_names`, replace archive pattern compilation with:

```python
                        pattern = compile_mapping_pattern(
                            mapping, "archive_file_pattern"
                        )
```

In `_match_archive_files`, replace the manual `file_dict` construction with:

```python
    file_dict = build_original_lookup(original_files)
```

- [ ] **Step 5: Run focused and real-archive tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_orc_mapping.py test/test_dfir_orc_unpack.py test/test_dfir_orc_unpack_hardening.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ogre/orc_mapping.py src/ogre/dfir_orc_unpack.py test/test_orc_mapping.py
git commit -m "refactor: extract orc mapping helpers"
```

## Task 5: Extract ORC Unpacker Implementation

**Files:**
- Create: `src/ogre/orc_unpacker.py`
- Create: `test/test_orc_facades.py`
- Modify: `src/ogre/dfir_orc_unpack.py`

- [ ] **Step 1: Write failing facade compatibility tests**

Create `test/test_orc_facades.py`:

```python
from unittest import TestCase

import ogre.commands as commands
import ogre.dfir_orc_unpack as dfir_orc_unpack
from ogre import orc_mapping, orc_metadata, orc_unpacker
from ogre import parser_execution, parser_results


class TestCompatibilityFacades(TestCase):
    def test_dfir_orc_unpack_re_exports_public_orc_types_and_functions(self):
        self.assertIs(dfir_orc_unpack.FileMapping, orc_mapping.FileMapping)
        self.assertIs(dfir_orc_unpack.OriginalNameMapping, orc_mapping.OriginalNameMapping)
        self.assertIs(dfir_orc_unpack.UnpackResult, orc_mapping.UnpackResult)
        self.assertIs(dfir_orc_unpack.OrcOutcome, orc_metadata.OrcOutcome)
        self.assertIs(
            dfir_orc_unpack.load_archive_metadata,
            orc_metadata.load_archive_metadata,
        )
        self.assertIs(dfir_orc_unpack.unpack_dfir_orc, orc_unpacker.unpack_dfir_orc)

    def test_commands_re_exports_public_parser_types_and_functions(self):
        self.assertIs(commands.FileStat, parser_results.FileStat)
        self.assertIs(commands.OutputStat, parser_results.OutputStat)
        self.assertIs(commands.RunResult, parser_results.RunResult)
        self.assertIs(commands.metadata_to_dict, parser_results.metadata_to_dict)
        self.assertIs(commands.run_parser, parser_execution.run_parser)
        self.assertIs(commands.run_batch_parser, parser_execution.run_batch_parser)
```

- [ ] **Step 2: Run the focused facade test to verify current unpacker export fails**

Run:

```bash
uv run --with pytest python -m pytest test/test_orc_facades.py -q
```

Expected: FAIL because `ogre.orc_unpacker` does not exist yet or because `dfir_orc_unpack.unpack_dfir_orc` is still local.

- [ ] **Step 3: Create `orc_unpacker.py` by moving unpack implementation**

Move these functions from `src/ogre/dfir_orc_unpack.py` to `src/ogre/orc_unpacker.py`:

```python
unpack_dfir_orc
_extract_nested_archives
_build_file_mapping
_build_file_mapping_list
_match_original_files
_match_archive_files
_match_inner_archive_files
_process_inner_archive_file_names
```

Use these imports at the top of `src/ogre/orc_unpacker.py`:

```python
import csv
import logging
import os
from pathlib import Path
from typing import Collection, Dict, List, Optional

import py7zr
from dfir_ogre_common import FilesToExtract, extract_7z_file, extract_7z_files

from .configuration import Mapping
from .orc_mapping import (
    FILE_NAME_MAPPING,
    INNER_TEMP_ARCHIVE,
    WINDOWS_SHORT_FILE_PATTERN,
    FileMapping,
    NestedArchive,
    OriginalFileMappingResult,
    OriginalNameMapping,
    UnpackResult,
    build_original_lookup,
    compile_mapping_pattern,
    partition_mappings,
)
from .sevenzip_rename_factory import (
    MAX_FILE_NAME_BYTE_LENGTH,
    need_rename,
    rename_file,
)
```

Keep function bodies behavior-compatible with the end of Task 4. Keep accumulated extraction errors in `UnpackResult.errors`.

- [ ] **Step 4: Replace `dfir_orc_unpack.py` with compatibility exports**

Replace `src/ogre/dfir_orc_unpack.py` with:

```python
from .orc_mapping import (
    FileMapping,
    NestedArchive,
    OriginalFileMappingResult,
    OriginalNameMapping,
    UnpackResult,
)
from .orc_metadata import OrcOutcome, load_archive_metadata
from .orc_unpacker import unpack_dfir_orc

__all__ = [
    "FileMapping",
    "NestedArchive",
    "OriginalFileMappingResult",
    "OriginalNameMapping",
    "OrcOutcome",
    "UnpackResult",
    "load_archive_metadata",
    "unpack_dfir_orc",
]
```

- [ ] **Step 5: Run focused and real-archive tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_orc_facades.py test/test_dfir_orc_unpack.py test/test_dfir_orc_unpack_hardening.py test/test_run_preparation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/ogre/orc_unpacker.py src/ogre/dfir_orc_unpack.py test/test_orc_facades.py
git commit -m "refactor: extract orc unpacker"
```

## Task 6: Final Import Cleanup And Full Verification

**Files:**
- Modify: `src/ogre/commands.py`
- Modify: `src/ogre/run_preparation.py`
- Modify: `src/ogre/process_runner.py`
- Modify: `src/ogre/reports.py`

- [ ] **Step 1: Check compatibility imports and stale imports**

Run:

```bash
python3 -m compileall src/ogre
```

Expected: PASS with no syntax errors.

Run:

```bash
rg -n "from \\.commands import \\(|from ogre.commands import \\(|from \\.dfir_orc_unpack import \\(|from ogre.dfir_orc_unpack import \\(" src test
```

Expected: output may list compatibility imports, but no private helper imports such as `_match_archive_files`, `_load_json_definition`, or `_process_inner_archive_file_names`.

- [ ] **Step 2: Prefer focused imports where internal modules do not need facades**

If `src/ogre/process_runner.py` imports parser result symbols from `commands.py`, change it to:

```python
from .parser_execution import (
    run_batch_parser,
    run_parser,
)
from .parser_results import (
    RunResult,
    metadata_to_dict,
)
```

If `src/ogre/reports.py` imports `RunResult` from `commands.py`, change it to:

```python
from .parser_results import RunResult
```

Keep `src/ogre/run_preparation.py` imports from `dfir_orc_unpack.py` unless changing them removes a cycle. The compatibility facade is the stable boundary for ORC archive processing.

- [ ] **Step 3: Run full verification**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected: PASS for the full suite.

- [ ] **Step 4: Check final module sizes and git diff**

Run:

```bash
wc -l src/ogre/dfir_orc_unpack.py src/ogre/orc_metadata.py src/ogre/orc_mapping.py src/ogre/orc_unpacker.py src/ogre/commands.py src/ogre/parser_results.py src/ogre/parser_execution.py
```

Expected: `dfir_orc_unpack.py` and `commands.py` are small compatibility modules; the new modules are focused by responsibility.

Run:

```bash
git diff --stat
```

Expected: changes are limited to the planned modules and tests.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/ogre/commands.py src/ogre/process_runner.py src/ogre/reports.py src/ogre/run_preparation.py
git commit -m "refactor: clean parser and orc imports"
```

If `git status --short` shows no changes after Step 4, skip this commit and record that no final import cleanup was needed.

## Self-Review Checklist

- Spec coverage: Tasks 1 and 2 cover parser result/execution splitting and parser hardening. Tasks 3 through 5 cover ORC metadata, mapping, unpack orchestration, and compatibility facades. Task 6 covers full verification and internal import cleanup.
- Hardening coverage: empty archive input, invalid JSON definition type, missing hostname, malformed outcome command set, missing archive name, invalid regex context, empty parser reports, and zero-duration parser statistics are each covered by a failing test before implementation.
- Compatibility coverage: `test/test_orc_facades.py`, existing command tests, existing real-archive tests, and full-suite verification protect public imports and report/extraction behavior.
- Type consistency: `RunResult`, `FileStat`, `OutputStat`, `OrcOutcome`, `FileMapping`, and `UnpackResult` are defined once in focused modules and re-exported through compatibility facades.
