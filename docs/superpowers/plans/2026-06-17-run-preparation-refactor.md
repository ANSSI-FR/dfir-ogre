# Run Preparation Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic `prepare_runs()` flow with a staged, test-backed run-preparation pipeline while preserving CLI behavior.

**Architecture:** Add `src/ogre/run_preparation.py` as the internal home for run-preparation state, variable resolution, batch-entry construction, archive planning, run grouping, config loading, and plugin parser cache handling. Keep `src/ogre/commands.py` as the parser-execution module and re-export existing names from it so current imports continue to work during the refactor.

**Tech Stack:** Python 3.10, `dataclasses`, `unittest`/`pytest` execution via `uv run --with pytest python -m pytest`, existing fixtures under `test/data` and `test/plugin_config`.

---

## File Structure

- Create: `src/ogre/run_preparation.py`
  - Owns run-preparation dataclasses, variable resolution, metadata and batch-entry building, archive planning, run grouping, configuration loading, plugin loading, and `prepare_runs()`.
- Modify: `src/ogre/commands.py`
  - Re-export run-preparation types and functions used by existing callers.
  - Keep parser listing and parser execution behavior.
  - Remove run-preparation implementation once the new module is wired.
- Create: `test/test_run_preparation.py`
  - Focused tests for `VariableResolver`, `BatchEntryBuilder`, `RunConfigGrouper`, `ArchiveRunPlanner`, and the final `prepare_runs()` compatibility path.
- Modify: existing tests only if imports need to move after the production split.

---

### Task 1: Add Variable Resolver

**Files:**
- Create: `src/ogre/run_preparation.py`
- Create: `test/test_run_preparation.py`

- [ ] **Step 1: Write failing resolver tests**

Create `test/test_run_preparation.py` with these tests:

```python
import copy
import os
from datetime import datetime, timezone
from unittest import TestCase

from dfir_ogre_common import OutputConfiguration

from ogre.configuration import Configuration, Mapping
from ogre.dfir_orc_unpack import OrcOutcome
from ogre.run_preparation import VariableResolver

from .hardening_helpers import TempFolderTestCase


def _mapping(**overrides):
    values = {
        "archive_file_pattern": ".*\\.txt$",
        "original_file_pattern": None,
        "plugin_file": "$plugin_folder/void.xml",
        "mapping_label": "text_output",
        "skip_short_name": True,
        "force_nake_case": True,
        "timeout": 3600,
        "params": {
            "folder": "$output_folder/$archive_name/$case",
            "constant": 7,
        },
        "output": ["rawjson"],
    }
    values.update(overrides)
    return Mapping(**values)


def _output(**overrides):
    values = {
        "base_file_name": "$parser_$file_name_$timestamp",
        "output_folder": "$output_folder/$archive_name/$mapping_label/$dir_tree",
        "output_type": "file",
        "format": "jsonl",
        "date_format": "iso",
        "with_timeline": False,
        "with_qualifiers": False,
        "include_empty": False,
        "parameters": {},
    }
    values.update(overrides)
    return OutputConfiguration(
        values["base_file_name"],
        values["output_folder"],
        values["output_type"],
        values["format"],
        values["date_format"],
        values["with_timeline"],
        values["with_qualifiers"],
        values["include_empty"],
        values["parameters"],
    )


def _configuration(**overrides):
    rawjson = _output()
    values = {
        "plugin_prefixes": ["test"],
        "case": "test",
        "dir_tree": "",
        "temp_folder": ".tmp/extract/request",
        "output_folder": ".tmp/output",
        "plugin_folder": "test/plugin_config",
        "report_folder": "/data/$case/ogre/$dir_tree/ogre_report",
        "force_snake_case": True,
        "default_timeout": 3600,
        "inner_archive_password": None,
        "mapping": [_mapping()],
        "output": {"rawjson": rawjson},
    }
    values.update(overrides)
    return Configuration(**values)


def _outcome(**overrides):
    values = {
        "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
        "computer_name": "SampleOrc",
        "date": datetime(2025, 9, 4, 22, 11, 44, tzinfo=timezone.utc),
        "dir_tree": None,
        "archives": ["test/data/archive/SampleOrc.7z"],
    }
    values.update(overrides)
    return OrcOutcome(**values)


class TestVariableResolver(TestCase):
    def test_report_folder_uses_config_dir_tree_fallback_when_archive_has_none(self):
        resolver = VariableResolver(_configuration(), _outcome())

        self.assertEqual(
            resolver.resolve_report_folder(),
            "/data/test/ogre/ogre_report",
        )

    def test_report_folder_uses_archive_dir_tree_when_present(self):
        resolver = VariableResolver(
            _configuration(),
            _outcome(dir_tree="presta/SuperIR"),
        )

        self.assertEqual(
            resolver.resolve_report_folder(),
            "/data/test/ogre/presta/SuperIR/ogre_report",
        )

    def test_archive_output_resolution_preserves_existing_timestamp_behavior(self):
        config = _configuration()
        resolver = VariableResolver(config, _outcome(dir_tree="presta/SuperIR"))

        resolved = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )

        self.assertEqual(
            resolved.output_folder,
            ".tmp/output/SampleOrc/$mapping_label/presta/SuperIR",
        )
        self.assertEqual(
            resolved.base_file_name,
            "$parser_$file_name_20250904_221144",
        )

    def test_run_output_resolution_replaces_mapping_parser_file_and_computer(self):
        config = _configuration()
        resolver = VariableResolver(config, _outcome())
        archive_output = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )

        resolved = resolver.resolve_run_output(
            archive_output,
            mapping_label="text_output",
            parser="Void",
            file_path="/tmp/BITS_jobs.txt",
        )

        self.assertEqual(
            resolved.output_folder,
            ".tmp/output/SampleOrc/text_output",
        )
        self.assertEqual(
            resolved.base_file_name,
            "Void_BITS_jobs_20250904_221144",
        )

    def test_plugin_file_and_mapping_params_are_resolved_without_mutating_mapping(self):
        config = _configuration()
        mapping = config.mapping[0]
        resolver = VariableResolver(config, _outcome())

        plugin_file = resolver.resolve_plugin_file(
            mapping,
            "test/data/archive/SampleOrc.7z",
        )
        params = resolver.resolve_mapping_params(
            mapping,
            "test/data/archive/SampleOrc.7z",
        )

        self.assertEqual(plugin_file, "test/plugin_config/void.xml")
        self.assertEqual(params["folder"], ".tmp/output/SampleOrc/test")
        self.assertEqual(params["constant"], "7")
        self.assertEqual(mapping.plugin_file, "$plugin_folder/void.xml")
```

- [ ] **Step 2: Run the resolver tests and verify they fail**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestVariableResolver -v
```

Expected: failure during import with `ModuleNotFoundError: No module named 'ogre.run_preparation'` or `ImportError` for `VariableResolver`.

- [ ] **Step 3: Add the resolver implementation**

Create `src/ogre/run_preparation.py` with:

```python
import copy
from pathlib import Path

from dfir_ogre_common import OutputConfiguration

from .configuration import Configuration, Mapping
from .dfir_orc_unpack import OrcOutcome


class VariableResolver:
    def __init__(self, configuration: Configuration, outcome: OrcOutcome):
        self.configuration = configuration
        self.outcome = outcome

    @property
    def timestamp(self) -> str:
        return self.outcome.date.strftime("%Y%m%d_%H%M%S")

    def resolve_report_folder(self) -> str:
        report_folder = (
            self.configuration.report_folder.replace("$case", self.configuration.case)
            .replace("$timestamp", self.timestamp)
        )
        if self.outcome.dir_tree:
            return report_folder.replace("$dir_tree", self.outcome.dir_tree)
        return report_folder.replace("/$dir_tree", self.configuration.dir_tree)

    def resolve_archive_output(
        self,
        output: OutputConfiguration,
        archive: str,
    ) -> OutputConfiguration:
        resolved = copy.deepcopy(output)
        archive_name = Path(archive).stem
        output_folder = (
            resolved.output_folder.replace("$output_folder", self.configuration.output_folder)
            .replace("$archive_name", archive_name)
            .replace("$case", self.configuration.case)
            .replace("$timestamp", self.timestamp)
        )
        if self.outcome.dir_tree:
            output_folder = output_folder.replace("$dir_tree", self.outcome.dir_tree)
        else:
            output_folder = output_folder.replace("/$dir_tree", self.configuration.dir_tree)
        resolved.output_folder = output_folder

        resolved.base_file_name = (
            resolved.base_file_name.replace("$output_folder", self.configuration.output_folder)
            .replace("$archive_name", archive_name)
            .replace("$case", self.configuration.case)
            .replace("$timestamp", self.timestamp)
        )
        return resolved

    def resolve_run_output(
        self,
        output: OutputConfiguration,
        mapping_label: str,
        parser: str,
        file_path: str,
    ) -> OutputConfiguration:
        resolved = copy.deepcopy(output)
        file_name = Path(file_path).stem
        resolved.output_folder = (
            resolved.output_folder.replace("$mapping_label", mapping_label)
            .replace("$parser", parser)
            .replace("$file_name", file_name)
            .replace("$computer_name", self.outcome.computer_name)
        )
        resolved.base_file_name = (
            resolved.base_file_name.replace("$mapping_label", mapping_label)
            .replace("$parser", parser)
            .replace("$file_name", file_name)
            .replace("$computer_name", self.outcome.computer_name)
        )
        return resolved

    def resolve_plugin_file(self, mapping: Mapping, archive: str) -> str:
        return (
            mapping.plugin_file.replace("$output_folder", self.configuration.output_folder)
            .replace("$archive_name", Path(archive).stem)
            .replace("$case", self.configuration.case)
            .replace("$plugin_folder", self.configuration.plugin_folder)
        )

    def resolve_mapping_params(
        self,
        mapping: Mapping,
        archive: str,
    ) -> dict[str, str | None]:
        archive_name = Path(archive).stem
        additional_params: dict[str, str | None] = {}
        for key, value in mapping.params.items():
            if isinstance(value, str):
                additional_params[key] = (
                    value.replace("$output_folder", self.configuration.output_folder)
                    .replace("$archive_name", archive_name)
                    .replace("$case", self.configuration.case)
                    .replace("$plugin_folder", self.configuration.plugin_folder)
                )
            else:
                additional_params[key] = str(value)
        return additional_params
```

- [ ] **Step 4: Run the resolver tests and verify they pass**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestVariableResolver -v
```

Expected: all `TestVariableResolver` tests pass.

- [ ] **Step 5: Run existing command hardening tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_commands_hardening.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git status --short
git add src/ogre/run_preparation.py test/test_run_preparation.py
git commit -m "test: pin run preparation variable resolution"
```

---

### Task 2: Add Batch Entry Builder

**Files:**
- Modify: `src/ogre/run_preparation.py`
- Modify: `test/test_run_preparation.py`

- [ ] **Step 1: Write failing batch-entry builder tests**

Append these imports to `test/test_run_preparation.py`:

```python
from ogre.dfir_orc_unpack import FileMapping
from ogre.run_preparation import BatchEntryBuilder, ParserSelection
```

Append this test class:

```python
class TestBatchEntryBuilder(TempFolderTestCase):
    def test_build_entry_preserves_metadata_and_resolved_output_contract(self):
        config = _configuration()
        outcome = _outcome()
        resolver = VariableResolver(config, outcome)
        archive_output = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )
        archive_outputs = {"rawjson": archive_output}
        mapping = config.mapping[0]
        file_mapping = FileMapping(
            file=os.path.join(self.temp_folder, "Event.7z", "BITS_jobs.txt"),
            archive_name="Event.7z",
            archive_file="BITS_jobs.txt",
            original_file="\\Windows\\System32\\BITS_jobs.txt",
            original_creation_date="2021-11-30T11:36:15.818000+00:00",
            original_modification_date="2021-11-30T11:36:20.364000+00:00",
            mapping=mapping,
            vss="{00000000-0000-0000-0000-000000000000}",
            error=None,
        )

        entry = BatchEntryBuilder(config, outcome, resolver).build(
            archive="test/data/archive/SampleOrc.7z",
            archive_outputs=archive_outputs,
            file_mapping=file_mapping,
            selection=ParserSelection(
                plugin_file="test/plugin_config/void.xml",
                parser="Void",
                module="ogre.void_parser",
                batch=False,
            ),
        )

        self.assertEqual(entry.file, os.path.abspath(file_mapping.file))
        self.assertEqual(entry.run_config.force_snake_case, True)
        self.assertEqual(entry.run_config.params["folder"], ".tmp/output/SampleOrc/test")
        self.assertEqual(entry.run_config.output[0].output_folder, ".tmp/output/SampleOrc/text_output")
        self.assertEqual(entry.run_config.output[0].base_file_name, "Void_BITS_jobs_20250904_221144")

        metadata = entry.metadata
        self.assertEqual(metadata.computer, "SampleOrc")
        self.assertEqual(metadata.folder, "archive")
        self.assertEqual(metadata.archive, "SampleOrc.7z")
        self.assertEqual(metadata.subarchive, "Event.7z")
        self.assertEqual(metadata.orc_id, "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}")
        self.assertEqual(metadata.archive_filename, "BITS_jobs.txt")
        self.assertEqual(metadata.original_filename, "\\Windows\\System32\\BITS_jobs.txt")
        self.assertEqual(metadata.vss, "{00000000-0000-0000-0000-000000000000}")
        self.assertEqual(metadata.creation_date.isoformat(), "2021-11-30T11:36:15.818000+00:00")
        self.assertEqual(metadata.modif_date.isoformat(), "2021-11-30T11:36:20.364000+00:00")

    def test_build_entry_raises_key_error_for_unknown_output_reference(self):
        mapping = _mapping(output=["missing_output"])
        config = _configuration(mapping=[mapping])
        outcome = _outcome()
        resolver = VariableResolver(config, outcome)
        file_mapping = FileMapping(
            file=os.path.join(self.temp_folder, "sample.txt"),
            archive_name="",
            archive_file="sample.txt",
            original_file=None,
            original_creation_date=None,
            original_modification_date=None,
            mapping=mapping,
            vss=None,
            error=None,
        )

        with self.assertRaises(KeyError) as context:
            BatchEntryBuilder(config, outcome, resolver).build(
                archive="test/data/archive/SampleOrc.7z",
                archive_outputs={},
                file_mapping=file_mapping,
                selection=ParserSelection(
                    plugin_file="test/plugin_config/void.xml",
                    parser="Void",
                    module="ogre.void_parser",
                    batch=False,
                ),
            )

        self.assertEqual(context.exception.args[0], "missing_output")
```

- [ ] **Step 2: Run the builder tests and verify they fail**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestBatchEntryBuilder -v
```

Expected: failure during import with `ImportError` for `BatchEntryBuilder` or `ParserSelection`.

- [ ] **Step 3: Add builder types and implementation**

Append these imports to `src/ogre/run_preparation.py`:

```python
import os
from dataclasses import dataclass
from datetime import timezone

import dateutil.parser
from dfir_ogre_common import BatchEntry, Metadata, RunConfiguration

from .dfir_orc_unpack import FileMapping
```

Add these types after `VariableResolver`:

```python
@dataclass(frozen=True)
class ParserSelection:
    plugin_file: str
    parser: str
    module: str
    batch: bool


class BatchEntryBuilder:
    def __init__(
        self,
        configuration: Configuration,
        outcome: OrcOutcome,
        resolver: VariableResolver,
    ):
        self.configuration = configuration
        self.outcome = outcome
        self.resolver = resolver

    def build(
        self,
        archive: str,
        archive_outputs: dict[str, OutputConfiguration],
        file_mapping: FileMapping,
        selection: ParserSelection,
    ) -> BatchEntry:
        mapping = file_mapping.mapping
        output = [
            self.resolver.resolve_run_output(
                archive_outputs[out_name],
                mapping.mapping_label,
                selection.parser,
                file_mapping.file,
            )
            for out_name in mapping.output
        ]
        run_config = RunConfiguration(
            output,
            mapping.force_nake_case,
            self.resolver.resolve_mapping_params(mapping, archive),
        )
        metadata = self._build_metadata(archive, file_mapping)
        return BatchEntry(os.path.abspath(file_mapping.file), run_config, metadata)

    def _build_metadata(self, archive: str, file_mapping: FileMapping) -> Metadata:
        metadata = Metadata(self.outcome.computer_name)
        archive_abs_path = os.path.abspath(archive)
        folder = os.path.basename(os.path.dirname(archive_abs_path))
        archive_name = os.path.basename(archive)
        subarchive_name = Path(file_mapping.archive_name).stem

        metadata.folder = folder
        metadata.archive = archive_name
        if archive != subarchive_name and subarchive_name:
            metadata.subarchive = subarchive_name + ".7z"

        metadata.orc_start_date = self.outcome.date
        metadata.orc_id = self.outcome.id
        metadata.archive_filename = file_mapping.archive_file
        metadata.original_filename = file_mapping.original_file
        metadata.vss = file_mapping.vss

        if file_mapping.original_creation_date:
            metadata.creation_date = dateutil.parser.isoparse(
                file_mapping.original_creation_date
            ).astimezone(timezone.utc)
        if file_mapping.original_modification_date:
            metadata.modif_date = dateutil.parser.isoparse(
                file_mapping.original_modification_date
            ).astimezone(timezone.utc)

        return metadata
```

- [ ] **Step 4: Run the builder tests and verify they pass**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestBatchEntryBuilder -v
```

Expected: all `TestBatchEntryBuilder` tests pass.

- [ ] **Step 5: Run resolver tests again**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestVariableResolver -v
```

Expected: all `TestVariableResolver` tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git status --short
git add src/ogre/run_preparation.py test/test_run_preparation.py
git commit -m "test: pin run preparation batch entry building"
```

---

### Task 3: Add Run Grouper And Archive Planner

**Files:**
- Modify: `src/ogre/run_preparation.py`
- Modify: `test/test_run_preparation.py`

- [ ] **Step 1: Write failing grouper and planner tests**

Append these imports to `test/test_run_preparation.py`:

```python
from ogre.dfir_orc_unpack import UnpackResult
from ogre.run_preparation import ArchiveRunPlanner, PluginDefinition, RunConfigGrouper
```

Append this test class:

```python
class TestRunConfigGrouper(TestCase):
    def test_grouper_preserves_existing_plugin_file_grouping_contract(self):
        config = _configuration()
        outcome = _outcome()
        resolver = VariableResolver(config, outcome)
        archive_output = resolver.resolve_archive_output(
            config.output["rawjson"],
            "test/data/archive/SampleOrc.7z",
        )
        file_mapping = FileMapping(
            file="/tmp/sample.txt",
            archive_name="",
            archive_file="sample.txt",
            original_file=None,
            original_creation_date=None,
            original_modification_date=None,
            mapping=config.mapping[0],
            vss=None,
            error=None,
        )
        builder = BatchEntryBuilder(config, outcome, resolver)
        first = builder.build(
            "test/data/archive/SampleOrc.7z",
            {"rawjson": archive_output},
            file_mapping,
            ParserSelection("test/plugin_config/void.xml", "Void", "ogre.void_parser", False),
        )
        second = builder.build(
            "test/data/archive/SampleOrc.7z",
            {"rawjson": archive_output},
            file_mapping,
            ParserSelection("test/plugin_config/void.xml", "Void", "ogre.void_parser", False),
        )

        grouper = RunConfigGrouper()
        grouper.add(first, "test/plugin_config/void.xml", "text_output", "ogre.void_parser", "Void", False, 3600)
        grouper.add(second, "test/plugin_config/void.xml", "text_output", "ogre.void_parser", "Void", False, 3600)

        self.assertEqual(len(grouper.map), 1)
        run = grouper.map["test/plugin_config/void.xml"]
        self.assertEqual(len(run.batch_entries), 2)
        self.assertEqual(run.plugin_file, "test/plugin_config/void.xml")
        self.assertEqual(run.mapping_label, "text_output")
        self.assertEqual(run.module, "ogre.void_parser")
        self.assertEqual(run.parser, "Void")
        self.assertFalse(run.batch)
        self.assertEqual(run.timeout, 3600)


class TestArchiveRunPlanner(TempFolderTestCase):
    def test_planner_collects_unpack_errors_and_groups_valid_mappings(self):
        config = _configuration()
        outcome = _outcome(archives=["test/data/archive/SampleOrc.7z"])
        resolver = VariableResolver(config, outcome)
        mapping = config.mapping[0]
        file_mapping = FileMapping(
            file=os.path.join(self.temp_folder, "sample.txt"),
            archive_name="",
            archive_file="sample.txt",
            original_file=None,
            original_creation_date=None,
            original_modification_date=None,
            mapping=mapping,
            vss=None,
            error=None,
        )

        def fake_unpack(archive, password, inner_archive_password, mappings, temp_folder):
            self.assertEqual(archive, "test/data/archive/SampleOrc.7z")
            self.assertIsNone(password)
            self.assertIsNone(inner_archive_password)
            self.assertEqual(list(mappings), config.mapping)
            self.assertEqual(temp_folder, config.temp_folder)
            return UnpackResult([file_mapping], ["extract warning"])

        def fake_load_plugin_parser(plugin_file):
            self.assertEqual(plugin_file, "test/plugin_config/void.xml")
            return ("Void", False)

        planner = ArchiveRunPlanner(
            configuration=config,
            outcome=outcome,
            password=None,
            parsers={"Void": PluginDefinition("Void", "ogre.void_parser", False)},
            resolver=resolver,
            unpack=fake_unpack,
            load_parser=fake_load_plugin_parser,
        )

        result = planner.plan()

        self.assertEqual(result.errors, ["extract warning"])
        self.assertEqual(len(result.runs.map), 1)
        run = result.runs.map["test/plugin_config/void.xml"]
        self.assertEqual(run.parser, "Void")
        self.assertEqual(run.module, "ogre.void_parser")
        self.assertEqual(len(run.batch_entries), 1)
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestRunConfigGrouper test/test_run_preparation.py::TestArchiveRunPlanner -v
```

Expected: failure during import with `ImportError` for `ArchiveRunPlanner` or `RunConfigGrouper`.

- [ ] **Step 3: Add grouper and planner implementation**

Append these imports to `src/ogre/run_preparation.py`:

```python
from typing import Callable

from .dfir_orc_unpack import UnpackResult, unpack_dfir_orc
```

Add these dataclasses and classes after `BatchEntryBuilder`:

```python
@dataclass(frozen=True)
class PluginDefinition:
    parser_name: str
    module: str
    batch: bool


@dataclass
class OgreRunConfiguration:
    batch_entries: list[BatchEntry]
    plugin_file: str
    mapping_label: str
    module: str
    parser: str
    batch: bool
    timeout: int


class RunConfigGrouper:
    def __init__(self):
        self.map: dict[str, OgreRunConfiguration] = {}

    def add(
        self,
        batch_entry: BatchEntry,
        plugin_file: str,
        mapping_label: str,
        module: str,
        parser: str,
        batch: bool,
        timeout: int,
    ) -> None:
        entry = self.map.get(plugin_file)
        if entry:
            entry.batch_entries.append(batch_entry)
            return
        self.map[plugin_file] = OgreRunConfiguration(
            [batch_entry],
            plugin_file,
            mapping_label,
            module,
            parser,
            batch,
            timeout,
        )


@dataclass
class ArchivePlanResult:
    runs: RunConfigGrouper
    errors: list[str]
    last_archive: str


class ArchiveRunPlanner:
    def __init__(
        self,
        configuration: Configuration,
        outcome: OrcOutcome,
        password: str | None,
        parsers: dict[str, PluginDefinition],
        resolver: VariableResolver,
        unpack: Callable[
            [str, str | None, str | None, list[Mapping], str],
            UnpackResult,
        ] = unpack_dfir_orc,
        load_parser: Callable[[str], tuple[str, bool]] | None = None,
    ):
        self.configuration = configuration
        self.outcome = outcome
        self.password = password
        self.parsers = parsers
        self.resolver = resolver
        self.unpack = unpack
        self.load_parser = load_parser

    def plan(self) -> ArchivePlanResult:
        if self.load_parser is None:
            raise TypeError("load_parser must be provided")

        errors: list[str] = []
        grouper = RunConfigGrouper()
        last_archive = ""
        builder = BatchEntryBuilder(self.configuration, self.outcome, self.resolver)

        for archive in self.outcome.archives:
            last_archive = archive
            archive_outputs = {
                name: self.resolver.resolve_archive_output(output, archive)
                for name, output in self.configuration.output.items()
            }
            unpacked = self.unpack(
                archive,
                self.password,
                self.configuration.inner_archive_password,
                self.configuration.mapping,
                self.configuration.temp_folder,
            )
            errors.extend(unpacked.errors)
            for file_mapping in unpacked.valid_mapping:
                mapping = file_mapping.mapping
                plugin_file = self.resolver.resolve_plugin_file(mapping, archive)
                parser_name, is_batched = self.load_parser(plugin_file)
                parser_definition = self.parsers.get(parser_name)
                if not parser_definition:
                    raise Exception(f"plugin '{(parser_name, is_batched)}' not found in the loaded plugins")
                selection = ParserSelection(
                    plugin_file,
                    parser_name,
                    parser_definition.module,
                    is_batched,
                )
                batch_entry = builder.build(
                    archive,
                    archive_outputs,
                    file_mapping,
                    selection,
                )
                grouper.add(
                    batch_entry,
                    plugin_file,
                    mapping.mapping_label,
                    parser_definition.module,
                    parser_name,
                    is_batched,
                    mapping.timeout,
                )

        return ArchivePlanResult(grouper, errors, last_archive)
```

- [ ] **Step 4: Run the new tests and verify they pass**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestRunConfigGrouper test/test_run_preparation.py::TestArchiveRunPlanner -v
```

Expected: all new grouper and planner tests pass.

- [ ] **Step 5: Run all run-preparation tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py -v
```

Expected: all `test_run_preparation.py` tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git status --short
git add src/ogre/run_preparation.py test/test_run_preparation.py
git commit -m "test: pin archive run planning"
```

---

### Task 4: Move Config Loading And Plugin Cache Into Run Preparation

**Files:**
- Modify: `src/ogre/run_preparation.py`
- Modify: `src/ogre/commands.py`
- Modify: `test/test_run_preparation.py`

- [ ] **Step 1: Write failing tests for config loading exports**

Append these imports to `test/test_run_preparation.py`:

```python
from ogre.run_preparation import (
    clear_plugin_parser_cache,
    load_config,
    load_plugin_parser,
    load_plugins,
)
```

Append this test class:

```python
class TestRunPreparationConfigLoading(TempFolderTestCase):
    def setUp(self):
        super().setUp()
        clear_plugin_parser_cache()

    def tearDown(self):
        clear_plugin_parser_cache()
        super().tearDown()

    def test_load_config_validates_regex_and_outputs(self):
        config, plugins = load_config(
            os.path.join("test", "data", "test_commands.yaml"),
            {"temp_folder": self.temp_folder},
        )

        self.assertEqual(config.case, "test")
        self.assertIn("Void", plugins)

    def test_load_plugin_parser_cache_is_owned_by_run_preparation(self):
        plugin_file = os.path.join("test", "plugin_config", "void.xml")

        self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))
        self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))

    def test_load_plugins_discovers_test_void_parser(self):
        plugins = load_plugins(["test"])

        self.assertIn("Void", plugins)
        self.assertEqual(plugins["Void"].module, "ogre.void_parser")
```

- [ ] **Step 2: Run the config-loading tests and verify they fail**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestRunPreparationConfigLoading -v
```

Expected: failure during import with `ImportError` for `load_config`, `load_plugin_parser`, `load_plugins`, or `clear_plugin_parser_cache`.

- [ ] **Step 3: Move config-loading imports into `run_preparation.py`**

Add these imports to `src/ogre/run_preparation.py`:

```python
import importlib
import pkgutil
import re
import xml.etree.ElementTree as ET

import yaml
from dfir_ogre_common import OgreBatchedPlugin, OgrePlugin

from .configuration import build_configuration
```

- [ ] **Step 4: Add config and plugin loading functions**

Append this implementation to `src/ogre/run_preparation.py`:

```python
def load_config(
    conf_file: str,
    global_var: dict[str, str],
) -> tuple[Configuration, dict[str, PluginDefinition]]:
    with open(conf_file) as conf:
        config_dict = yaml.safe_load(conf)

    config = build_configuration(config_dict, global_var)
    plugins = load_plugins(config.plugin_prefixes)

    for mapping in config.mapping:
        if mapping.archive_file_pattern:
            try:
                re.compile(mapping.archive_file_pattern, re.IGNORECASE)
            except Exception as error:
                raise Exception(
                    f"{error} in archive_file_pattern regex:'{mapping.archive_file_pattern}', mapping_label:'{mapping.mapping_label}'"
                )

        if mapping.original_file_pattern:
            try:
                re.compile(mapping.original_file_pattern, re.IGNORECASE)
            except Exception as error:
                raise Exception(
                    f"{error} in original_file_pattern regex:'{mapping.original_file_pattern}', mapping_label:'{mapping.mapping_label}'"
                )

    return config, plugins


PLUGIN_PARSER_CACHE: dict[str, tuple[str, bool]] = {}


def clear_plugin_parser_cache() -> None:
    PLUGIN_PARSER_CACHE.clear()


def load_plugin_parser(plugin_file: str) -> tuple[str, bool]:
    plugin_parser = PLUGIN_PARSER_CACHE.get(plugin_file)
    if plugin_parser is None:
        tree = ET.parse(plugin_file)
        root = tree.getroot()
        plugin_name = root.attrib.get("parser")
        batch = root.attrib.get("batch")
        is_batched = batch is not None

        if not plugin_name:
            raise Exception(
                f"'parser' attribute not found in plugin file :'{plugin_file}'"
            )
        plugin_parser = (plugin_name, is_batched)
        PLUGIN_PARSER_CACHE[plugin_file] = plugin_parser

    return plugin_parser


def load_plugins(plugin_prefixes: list[str]) -> dict[str, PluginDefinition]:
    for _, name, _ in pkgutil.iter_modules():
        for prefix in plugin_prefixes:
            if name.startswith(prefix):
                importlib.import_module(name)

    parser_dict: dict[str, PluginDefinition] = {}

    for parser in OgrePlugin.__subclasses__():
        module_name = parser.__module__
        parser_name = parser().description().get_command()
        entry = parser_dict.get(parser_name)
        if entry:
            raise KeyError(
                f"Parser name: '{parser_name}' from module: '{module_name}' is already defined in module: '{entry}'"
            )
        parser_dict[parser_name] = PluginDefinition(parser_name, module_name, False)

    for parser in OgreBatchedPlugin.__subclasses__():
        module_name = parser.__module__
        parser_name = parser().description().get_command()
        entry = parser_dict.get(parser_name)
        if entry:
            raise KeyError(
                f"Parser name: '{parser_name}' from module: '{module_name}' is already defined in module: '{entry}'"
            )
        parser_dict[parser_name] = PluginDefinition(parser_name, module_name, True)

    return parser_dict
```

- [ ] **Step 5: Re-export moved functions from `commands.py`**

Modify the import section of `src/ogre/commands.py` so it imports these names from `run_preparation.py`:

```python
from .run_preparation import (
    OgreRunConfiguration,
    PluginDefinition,
    RunConfigGrouper,
    clear_plugin_parser_cache,
    load_config,
    load_plugin_parser,
    load_plugins,
)
```

Keep the old `RunConfigMap` name available by adding this alias near the imports:

```python
RunConfigMap = RunConfigGrouper
```

Remove the duplicate local definitions for:

```python
OgreRunConfiguration
RunConfigMap
load_config
PLUGIN_PARSER_CACHE
clear_plugin_parser_cache
load_plugin_parser
PluginDefinition
_load_plugins
```

Update `list_parsers()` in `src/ogre/commands.py` to call:

```python
load_plugins(config.plugin_prefixes)
```

instead of:

```python
_load_plugins(config.plugin_prefixes)
```

- [ ] **Step 6: Run the config-loading tests and verify they pass**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestRunPreparationConfigLoading -v
```

Expected: all config-loading tests pass.

- [ ] **Step 7: Run existing command tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_commands.py test/test_commands_hardening.py -v
```

Expected: all command tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git status --short
git add src/ogre/run_preparation.py src/ogre/commands.py test/test_run_preparation.py
git commit -m "refactor: move run preparation config loading"
```

---

### Task 5: Move `prepare_runs()` Orchestration

**Files:**
- Modify: `src/ogre/run_preparation.py`
- Modify: `src/ogre/commands.py`
- Modify: `test/test_run_preparation.py`

- [ ] **Step 1: Write failing tests for new orchestration**

Append these imports to `test/test_run_preparation.py`:

```python
from ogre.run_preparation import RunPreparationContext, prepare_runs
```

Append this test class:

```python
class TestRunPreparationOrchestration(TempFolderTestCase):
    def test_context_load_copies_global_vars_and_adds_derived_values(self):
        global_vars = {"temp_folder": self.temp_folder}

        context = RunPreparationContext.load(
            os.path.join("test", "data", "test_commands_run.yaml"),
            os.path.join("test", "data", "archive", "SampleOrc.7z"),
            None,
            global_vars,
        )

        self.assertEqual(global_vars, {"temp_folder": self.temp_folder})
        self.assertEqual(context.global_vars["computer_name"], "SampleOrc")
        self.assertEqual(context.global_vars["orc_id"], context.outcome.id)
        self.assertEqual(context.global_vars["orc_start_date"], context.outcome.date.isoformat())
        self.assertEqual(context.configuration.temp_folder.startswith(self.temp_folder), True)
        self.assertIn("Void", context.parsers)

    def test_prepare_runs_preserves_existing_grouping_and_metadata_contract(self):
        result = prepare_runs(
            os.path.join("test", "data", "test_commands_run.yaml"),
            os.path.join("test", "data", "archive", "SampleOrc.7z"),
            None,
            {"temp_folder": self.temp_folder},
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.computer, "SampleOrc")
        self.assertEqual(result.output_folder, ".tmp/output")
        self.assertEqual(result.report_folder, ".tmp/output")
        self.assertEqual(len(result.runs.map), 1)

        run = next(iter(result.runs.map.values()))
        self.assertEqual(run.mapping_label, "arp")
        self.assertEqual(run.parser, "Void")
        self.assertEqual(run.module, "ogre.void_parser")
        self.assertFalse(run.batch)
        self.assertEqual(len(run.batch_entries), 2)

        archive_entry = next(
            entry
            for entry in run.batch_entries
            if entry.metadata.archive_filename == "arp_cache.txt"
        )
        self.assertEqual(archive_entry.metadata.computer, "SampleOrc")
        self.assertEqual(archive_entry.metadata.archive, "SampleOrc.7z")
        self.assertIsNone(archive_entry.metadata.subarchive)
        self.assertIsNone(archive_entry.metadata.original_filename)
        self.assertEqual(archive_entry.run_config.output[0].output_folder, "event")
        self.assertEqual(archive_entry.run_config.output[0].base_file_name, "test")

        original_entry = next(
            entry for entry in run.batch_entries if entry.metadata.original_filename
        )
        self.assertEqual(original_entry.metadata.computer, "SampleOrc")
        self.assertEqual(original_entry.metadata.archive, "SampleOrc.7z")
        self.assertEqual(original_entry.metadata.subarchive, "Event.7z")
        self.assertIn(
            "Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
            original_entry.metadata.archive_filename,
        )
        self.assertEqual(
            original_entry.metadata.original_filename,
            "\\Windows\\System32\\winevt\\Logs\\Microsoft-Windows-Kernel-EventTracing%4Admin.evtx",
        )
        self.assertEqual(
            original_entry.metadata.creation_date.isoformat(),
            "2021-11-30T11:36:15.818000+00:00",
        )
        self.assertEqual(
            original_entry.metadata.modif_date.isoformat(),
            "2021-11-30T11:36:20.364000+00:00",
        )
        self.assertEqual(
            original_entry.metadata.vss,
            "{00000000-0000-0000-0000-000000000000}",
        )

    def test_prepare_runs_preserves_unknown_output_key_error(self):
        with self.assertRaises(KeyError) as context:
            prepare_runs(
                os.path.join("test", "data", "test_commands_bad_output.yaml"),
                os.path.join("test", "data", "archive", "SampleOrc.7z"),
                None,
                {"temp_folder": self.temp_folder},
            )

        self.assertEqual(context.exception.args[0], "bad_output")
```

- [ ] **Step 2: Run orchestration tests and verify they fail**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestRunPreparationOrchestration -v
```

Expected: failure during import with `ImportError` for `RunPreparationContext` or `prepare_runs`.

- [ ] **Step 3: Add `PrepareRunResult` and `RunPreparationContext`**

Append this code to `src/ogre/run_preparation.py`:

```python
from .dfir_orc_unpack import load_archive_metadata


@dataclass
class PrepareRunResult:
    archive: str
    runs: RunConfigGrouper
    errors: list[str]
    computer: str
    orc_id: str
    output_folder: str
    report_folder: str
    tmp_folder: str


@dataclass
class RunPreparationContext:
    conf_file: str
    archive: str
    password: str | None
    global_vars: dict[str, str]
    configuration: Configuration
    parsers: dict[str, PluginDefinition]
    outcome: OrcOutcome

    @classmethod
    def load(
        cls,
        conf_file: str,
        archive: str,
        password: str | None,
        global_var: dict[str, str] | None,
    ) -> "RunPreparationContext":
        request_globals = dict(global_var or {})
        configuration, parsers = load_config(conf_file, request_globals)
        outcome = load_archive_metadata(archive)
        request_globals["computer_name"] = outcome.computer_name
        request_globals["orc_id"] = outcome.id
        request_globals["orc_start_date"] = outcome.date.isoformat()
        return cls(
            conf_file,
            archive,
            password,
            request_globals,
            configuration,
            parsers,
            outcome,
        )
```

- [ ] **Step 4: Add the new `prepare_runs()` orchestration**

Append this function to `src/ogre/run_preparation.py`:

```python
def prepare_runs(
    conf_file: str,
    archive: str,
    password: str | None,
    global_var: dict[str, str] | None = None,
) -> PrepareRunResult:
    context = RunPreparationContext.load(conf_file, archive, password, global_var)
    resolver = VariableResolver(context.configuration, context.outcome)
    report_folder = resolver.resolve_report_folder()
    planner = ArchiveRunPlanner(
        configuration=context.configuration,
        outcome=context.outcome,
        password=context.password,
        parsers=context.parsers,
        resolver=resolver,
        load_parser=load_plugin_parser,
    )
    plan = planner.plan()
    return PrepareRunResult(
        plan.last_archive,
        plan.runs,
        plan.errors,
        context.outcome.computer_name,
        context.outcome.id,
        context.configuration.output_folder,
        report_folder,
        context.configuration.temp_folder,
    )
```

- [ ] **Step 5: Re-export new orchestration from `commands.py`**

Add these imports to the existing `from .run_preparation import (...)` block in `src/ogre/commands.py`:

```python
PrepareRunResult,
RunPreparationContext,
prepare_runs,
```

Remove the old local `PrepareRunResult` dataclass and the old local `prepare_runs()` function from `src/ogre/commands.py`.

- [ ] **Step 6: Run orchestration tests and verify they pass**

Run:

```bash
uv run --with pytest python -m pytest test/test_run_preparation.py::TestRunPreparationOrchestration -v
```

Expected: all orchestration tests pass.

- [ ] **Step 7: Run existing command tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_commands.py test/test_commands_hardening.py -v
```

Expected: all existing command tests pass.

- [ ] **Step 8: Commit**

Run:

```bash
git status --short
git add src/ogre/run_preparation.py src/ogre/commands.py test/test_run_preparation.py
git commit -m "refactor: extract run preparation orchestration"
```

---

### Task 6: Final Cleanup And Verification

**Files:**
- Modify: `src/ogre/commands.py`
- Modify: `src/ogre/run_preparation.py`
- Modify: `test/test_run_preparation.py`

- [ ] **Step 1: Remove unused imports from `commands.py`**

Inspect imports with:

```bash
python3 - <<'PY'
import ast
from pathlib import Path

for path in [Path("src/ogre/commands.py"), Path("src/ogre/run_preparation.py")]:
    tree = ast.parse(path.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend(f"{module}.{alias.name}" for alias in node.names)
    print(path)
    for item in imports:
        print(f"  {item}")
PY
```

Then remove imports from `src/ogre/commands.py` that were only used by the old `prepare_runs()` implementation, such as `copy`, `os`, `dateutil.parser`, `timezone`, `Configuration`, `build_configuration`, `load_archive_metadata`, and `unpack_dfir_orc`, if they are no longer referenced.

- [ ] **Step 2: Run a static import smoke check**

Run:

```bash
uv run python - <<'PY'
from ogre.commands import prepare_runs, run_parser, list_parsers
from ogre.run_preparation import VariableResolver, BatchEntryBuilder, ArchiveRunPlanner

print(prepare_runs.__name__)
print(run_parser.__name__)
print(list_parsers.__name__)
print(VariableResolver.__name__)
print(BatchEntryBuilder.__name__)
print(ArchiveRunPlanner.__name__)
PY
```

Expected output:

```text
prepare_runs
run_parser
list_parsers
VariableResolver
BatchEntryBuilder
ArchiveRunPlanner
```

- [ ] **Step 3: Run the full test suite**

Run:

```bash
uv run --with pytest python -m pytest
```

Expected: all tests pass. At the time this plan was written, the suite collected 50 tests before this refactor; after adding `test/test_run_preparation.py`, the collected test count should be higher and all collected tests should pass.

- [ ] **Step 4: Inspect diff for behavior drift**

Run:

```bash
git diff -- src/ogre/commands.py src/ogre/run_preparation.py test/test_run_preparation.py
```

Check that:

- `cli.py` command argument parsing is untouched.
- `parse_archive()` still receives a result with `.runs`, `.errors`, `.computer`, `.orc_id`, `.output_folder`, `.report_folder`, and `.tmp_folder`.
- `commands.py` still exposes `prepare_runs`, `OgreRunConfiguration`, `RunResult`, `run_parser`, `run_batch_parser`, `load_config`, `load_plugin_parser`, and `clear_plugin_parser_cache`.
- extraction errors from `unpack_dfir_orc()` still flow into `PrepareRunResult.errors`.
- unknown output references still raise `KeyError` with the missing output name.

- [ ] **Step 5: Commit cleanup**

Run:

```bash
git status --short
git add src/ogre/commands.py src/ogre/run_preparation.py test/test_run_preparation.py
git commit -m "refactor: clean run preparation split"
```

- [ ] **Step 6: Record final verification**

Run:

```bash
git status --short --branch
git log --oneline -6
uv run --with pytest python -m pytest
```

Expected:

- `git status` shows a clean worktree on the refactor branch or worktree.
- recent commits include the run-preparation refactor commits from this plan.
- the full pytest suite passes.
