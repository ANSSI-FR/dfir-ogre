# Test Harness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a characterization-test harness around current DFIR-Ogre behavior with only small hardening changes that reduce test state leakage.

**Architecture:** Keep the current module boundaries in place. Add focused `unittest` coverage around `dfir_orc_unpack`, `commands`, and `cli`, and add only two small production hardening hooks: a plugin parser cache reset helper and a non-mutable `prepare_runs` default.

**Tech Stack:** Python 3.10, `unittest`, `unittest.mock`, `uv run python -m unittest`, existing DFIR-Ogre fixtures under `test/data` and `test/plugin_config`.

---

## File Structure

- Create: `test/hardening_helpers.py`
  - Owns temp-folder setup and cleanup for new characterization tests.
- Create: `test/test_dfir_orc_unpack_hardening.py`
  - Pins archive metadata parsing and `unpack_dfir_orc` returned-error behavior.
- Modify: `test/test_py7zr.py`
  - Adds direct coverage for the long-file-name rename helper behavior used during extraction.
- Create: `test/plugin_config/batched_void.xml`
  - Small XML fixture for `load_plugin_parser` batch detection.
- Create: `test/test_commands_hardening.py`
  - Pins plugin parser cache behavior, `prepare_runs` state hardening, output-reference errors, run grouping, and metadata construction.
- Modify: `src/ogre/commands.py`
  - Adds `clear_plugin_parser_cache()`.
  - Changes `prepare_runs(..., global_var={})` to `prepare_runs(..., global_var=None)` with local initialization.
- Create: `test/test_cli_hardening.py`
  - Pins report aggregation, JSON encoding, params parsing, timeout wrappers, CLI dispatch, and mocked `parse_archive` report writing.

Before each commit, run `git status --short` and make sure unrelated files, including an existing local `test/test_timeline.py` modification, remain unstaged.

---

### Task 1: Add Test Helper And Archive Error Characterization

**Files:**
- Create: `test/hardening_helpers.py`
- Create: `test/test_dfir_orc_unpack_hardening.py`

- [ ] **Step 1: Add a temp-folder helper**

Create `test/hardening_helpers.py`:

```python
import os
import shutil
from unittest import TestCase

from . import TEMP_FOLDER


class TempFolderTestCase(TestCase):
    temp_name = "hardening"

    def setUp(self):
        self.temp_folder = os.path.join(
            TEMP_FOLDER,
            self.temp_name,
            self.__class__.__name__,
            self._testMethodName,
        )
        shutil.rmtree(self.temp_folder, ignore_errors=True)
        os.makedirs(self.temp_folder, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_folder, ignore_errors=True)
```

- [ ] **Step 2: Add archive metadata and returned-error tests**

Create `test/test_dfir_orc_unpack_hardening.py`:

```python
import os

from ogre.dfir_orc_unpack import load_archive_metadata, unpack_dfir_orc

from .hardening_helpers import TempFolderTestCase


class TestDfirOrcUnpackHardening(TempFolderTestCase):
    def test_unpack_missing_archive_returns_error_list(self):
        result = unpack_dfir_orc(
            os.path.join(self.temp_folder, "missing.7z"),
            None,
            None,
            [],
            self.temp_folder,
        )

        self.assertEqual(result.valid_mapping, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn("not found or is not a file", result.errors[0])

    def test_unpack_non_7z_archive_returns_error_list(self):
        result = unpack_dfir_orc("README.md", None, None, [], self.temp_folder)

        self.assertEqual(result.valid_mapping, [])
        self.assertEqual(result.errors, ["'README.md' is not a 7z file"])

    def test_json_archive_definition_requires_unencrypted_archives(self):
        archive_definition = """{
            "id": "{9219B312-D3E5-4CD7-A87E-B21350B01B4B}",
            "hostname": "SampleOrc",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": []
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "No unencrypted archives defined in the json archive definition",
            str(context.exception),
        )

    def test_json_archive_definition_requires_id(self):
        archive_definition = """{
            "hostname": "SampleOrc",
            "timestamp": "20250904_221144",
            "unencrypted_data_files": ["test/data/archive/SampleOrc.7z"]
        }"""

        with self.assertRaises(Exception) as context:
            load_archive_metadata(archive_definition)

        self.assertIn(
            "The orc id is not defined in the json archive definition",
            str(context.exception),
        )

    def test_outcome_file_requires_dfir_orc_root_node(self):
        outcome_file = os.path.join(self.temp_folder, "bad_outcome.json")
        with open(outcome_file, "w") as file:
            file.write("{}")

        with self.assertRaises(Exception) as context:
            load_archive_metadata(outcome_file)

        self.assertIn("'dfir-orc' root node not found", str(context.exception))
```

- [ ] **Step 3: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_dfir_orc_unpack_hardening -v
```

Expected: `OK`. These are characterization tests for existing behavior; a failure means the test expectation does not match current behavior and must be corrected before continuing.

- [ ] **Step 4: Commit**

```bash
git add test/hardening_helpers.py test/test_dfir_orc_unpack_hardening.py
git commit -m "test: characterize archive error handling"
```

---

### Task 2: Pin Long Filename Rename Helpers

**Files:**
- Modify: `test/test_py7zr.py`

- [ ] **Step 1: Add imports**

Modify the import block in `test/test_py7zr.py` to include `hashlib` and the rename helpers:

```python
import hashlib
import os
import shutil
from typing import Optional
from unittest import TestCase, mock
import py7zr
from py7zr.io import Py7zIO, WriterFactory

from ogre.sevenzip_rename_factory import need_rename, rename_file

from . import TEMP_FOLDER
```

- [ ] **Step 2: Add rename helper tests**

Add these methods inside `class TestPy7zr(TestCase):`

```python
    def test_need_rename_detects_utf8_file_name_byte_limit(self):
        short_path = os.path.join("folder", "a" * 240)
        long_path = os.path.join("folder", "a" * 241)

        self.assertFalse(need_rename(short_path))
        self.assertTrue(need_rename(long_path))

    def test_rename_file_preserves_folder_and_hashes_file_name(self):
        file_name = "a" * 241
        path = os.path.join("folder", file_name)

        expected_hash = hashlib.sha256(file_name.encode("utf-8")).hexdigest()

        self.assertEqual(rename_file(path), os.path.join("folder", expected_hash))
```

- [ ] **Step 3: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_py7zr -v
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add test/test_py7zr.py
git commit -m "test: characterize long filename renaming"
```

---

### Task 3: Add Plugin Parser Cache Hardening

**Files:**
- Create: `test/plugin_config/batched_void.xml`
- Create: `test/test_commands_hardening.py`
- Modify: `src/ogre/commands.py`

- [ ] **Step 1: Add a batched plugin XML fixture**

Create `test/plugin_config/batched_void.xml`:

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<plugin parser="Void" batch="true">
  <mapping data_type="empty">
    <description>test parser</description>
    <default_parser value="Ignore" />
    <default_date_pattern value='%Y%m%d-%H%M%S' />
    <fields>
    </fields>
  </mapping>
</plugin>
```

- [ ] **Step 2: Write cache tests that require a reset helper**

Create `test/test_commands_hardening.py`:

```python
import os
import xml.etree.ElementTree as ET
from unittest import mock

from ogre.commands import (
    clear_plugin_parser_cache,
    load_plugin_parser,
)

from . import PLUGIN_FOLDER
from .hardening_helpers import TempFolderTestCase


class TestCommandsHardening(TempFolderTestCase):
    def setUp(self):
        super().setUp()
        clear_plugin_parser_cache()

    def tearDown(self):
        clear_plugin_parser_cache()
        super().tearDown()

    def test_load_plugin_parser_caches_xml_parse_result(self):
        plugin_file = os.path.join(PLUGIN_FOLDER, "void.xml")

        with mock.patch("ogre.commands.ET.parse", wraps=ET.parse) as parse:
            self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))
            self.assertEqual(load_plugin_parser(plugin_file), ("Void", False))

        parse.assert_called_once_with(plugin_file)

    def test_load_plugin_parser_detects_batch_attribute(self):
        plugin_file = os.path.join(PLUGIN_FOLDER, "batched_void.xml")

        self.assertEqual(load_plugin_parser(plugin_file), ("Void", True))
```

- [ ] **Step 3: Run the focused tests to verify the missing helper failure**

Run:

```bash
uv run python -m unittest test.test_commands_hardening -v
```

Expected: `ImportError` for `clear_plugin_parser_cache`.

- [ ] **Step 4: Add the cache reset helper**

In `src/ogre/commands.py`, directly after `PLUGIN_PARSER_CACHE`:

```python
PLUGIN_PARSER_CACHE: dict[str, tuple[str,bool]] = {}


def clear_plugin_parser_cache() -> None:
    PLUGIN_PARSER_CACHE.clear()
```

- [ ] **Step 5: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_commands_hardening -v
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add src/ogre/commands.py test/plugin_config/batched_void.xml test/test_commands_hardening.py
git commit -m "test: characterize plugin parser cache"
```

---

### Task 4: Harden `prepare_runs` Default State

**Files:**
- Modify: `test/test_commands_hardening.py`
- Modify: `src/ogre/commands.py`

- [ ] **Step 1: Add a test for the non-mutable default**

Add `prepare_runs` to the import list in `test/test_commands_hardening.py`:

```python
from ogre.commands import (
    clear_plugin_parser_cache,
    load_plugin_parser,
    prepare_runs,
)
```

Add this method inside `class TestCommandsHardening(TempFolderTestCase):`

```python
    def test_prepare_runs_does_not_keep_mutable_default_global_vars(self):
        self.assertEqual(prepare_runs.__defaults__, (None,))
```

- [ ] **Step 2: Run the focused test to verify the current failure**

Run:

```bash
uv run python -m unittest test.test_commands_hardening.TestCommandsHardening.test_prepare_runs_does_not_keep_mutable_default_global_vars -v
```

Expected: `FAIL` because `prepare_runs.__defaults__` currently contains a dictionary.

- [ ] **Step 3: Replace the mutable default with local initialization**

In `src/ogre/commands.py`, change the function signature and add local initialization at the top of `prepare_runs`:

```python
def prepare_runs(
    conf_file: str,
    archive: str,
    password: str | None,
    global_var: dict[str, str] | None = None,
) -> PrepareRunResult:
```

Then place this immediately before `run_config_map = RunConfigMap()`:

```python
    if global_var is None:
        global_var = {}
```

Keep the rest of the function unchanged so caller-provided dictionaries retain the same mutation behavior as today.

- [ ] **Step 4: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_commands_hardening -v
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add src/ogre/commands.py test/test_commands_hardening.py
git commit -m "test: harden prepare_runs default state"
```

---

### Task 5: Characterize Run Preparation Contracts

**Files:**
- Modify: `test/test_commands_hardening.py`

- [ ] **Step 1: Add output-reference and metadata tests**

Append these methods inside `class TestCommandsHardening(TempFolderTestCase):`

```python
    def test_prepare_runs_raises_key_error_for_unknown_output_reference(self):
        with self.assertRaises(KeyError) as context:
            prepare_runs(
                os.path.join("test", "data", "test_commands_bad_output.yaml"),
                os.path.join("test", "data", "archive", "SampleOrc.7z"),
                None,
                {"temp_folder": self.temp_folder},
            )

        self.assertEqual(context.exception.args[0], "bad_output")

    def test_prepare_runs_preserves_grouping_and_metadata_contract(self):
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
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_commands_hardening -v
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add test/test_commands_hardening.py
git commit -m "test: characterize run preparation contracts"
```

---

### Task 6: Characterize CLI Reporting And Params

**Files:**
- Create: `test/test_cli_hardening.py`

- [ ] **Step 1: Add CLI reporting and params tests**

Create `test/test_cli_hardening.py`:

```python
import json
from unittest import TestCase

from ogre.cli import DataclassJSONEncoder, ReportBuilder, parse_params
from ogre.commands import RunResult


def make_run_result(
    mapping_label="mapping",
    rows=0,
    time_s=0.0,
    last_error=None,
    num_errors=0,
):
    return RunResult(
        mapping_label,
        num_errors,
        last_error,
        rows,
        time_s,
        0,
        "Parser",
        "parser.module",
        "2026-06-16T00:00:00+00:00",
        {"computer": "host1"},
        [],
    )


class TestCliHardening(TestCase):
    def test_parse_params_preserves_current_string_conversion(self):
        self.assertEqual(parse_params(None), {})
        self.assertEqual(parse_params(""), {})
        self.assertEqual(parse_params("[1, 2]"), {})
        self.assertEqual(
            parse_params(
                '{"number": 7, "flag": true, "missing": null, "text": "abc"}'
            ),
            {
                "number": "7",
                "flag": "True",
                "missing": "None",
                "text": "abc",
            },
        )

    def test_report_builder_aggregates_summary_and_errors(self):
        builder = ReportBuilder(
            "2026-06-16T00:00:00+00:00",
            "dfir-ogre orc",
            "host1",
            "orc1",
            ".tmp/output",
        )
        builder.add_extract_error("extract failed")
        builder.add_result(make_run_result(rows=2, time_s=1.25), "one.txt")
        builder.add_result(
            make_run_result(rows=3, time_s=2.0, last_error="bad row", num_errors=1),
            "two.txt",
        )

        report = builder.get_report()

        self.assertEqual(report.extract_errors, ["extract failed"])
        self.assertEqual(len(report.parsing_errors), 1)
        self.assertIn("bad row", report.parsing_errors[0])
        self.assertEqual(len(report.run_results), 2)
        self.assertEqual(len(report.summary), 1)
        self.assertEqual(report.summary[0].parser, "mapping")
        self.assertEqual(report.summary[0].runs, 2)
        self.assertEqual(report.summary[0].rows, 5)
        self.assertEqual(report.summary[0].time, 3.25)
        self.assertEqual(len(report.summary[0].errors), 1)

    def test_dataclass_json_encoder_serializes_report_dataclasses(self):
        builder = ReportBuilder(
            "2026-06-16T00:00:00+00:00",
            "dfir-ogre orc",
            "host1",
            "orc1",
            ".tmp/output",
        )
        builder.add_result(make_run_result(rows=4, time_s=1.0), "input.txt")

        encoded = json.loads(json.dumps(builder.get_report(), cls=DataclassJSONEncoder))

        self.assertEqual(encoded["computer"], "host1")
        self.assertEqual(encoded["summary"][0]["rows"], 4)
        self.assertEqual(encoded["run_results"][0]["metadata"]["computer"], "host1")
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_cli_hardening -v
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add test/test_cli_hardening.py
git commit -m "test: characterize CLI reporting"
```

---

### Task 7: Characterize CLI Timeout Wrappers

**Files:**
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Add imports for timeout tests**

Extend the import section in `test/test_cli_hardening.py`:

```python
import json
from types import SimpleNamespace
from unittest import TestCase, mock

from ogre import cli
from ogre.cli import DataclassJSONEncoder, ReportBuilder, parse_params
from ogre.commands import OgreRunConfiguration, RunResult
```

- [ ] **Step 2: Add timeout wrapper tests**

Append these methods inside `class TestCliHardening(TestCase):`

```python
    def test_run_parser_with_timeout_returns_child_result(self):
        expected = make_run_result(rows=1, time_s=0.5)

        class FakeManager:
            def list(self):
                return []

        class FinishedProcess:
            def __init__(self, target, args):
                self.args = args

            def start(self):
                self.args[2].append(expected)

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", False, 5)
        batch_entry = SimpleNamespace(file="input.txt", metadata=SimpleNamespace())

        with mock.patch("ogre.cli.multiprocessing.Process", FinishedProcess):
            result = cli.run_parser_with_timeout(batch_entry, config, FakeManager())

        self.assertIs(result, expected)

    def test_run_parser_with_timeout_terminates_hanging_process(self):
        instances = []

        class FakeManager:
            def list(self):
                return []

        class HangingProcess:
            def __init__(self, target, args):
                self.closed = False
                self.terminated = False
                self.killed = False
                instances.append(self)

            def start(self):
                return None

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return True

            def close(self):
                self.closed = True

            def terminate(self):
                self.terminated = True

            def kill(self):
                self.killed = True

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", False, 5)
        batch_entry = SimpleNamespace(file="input.txt", metadata=SimpleNamespace())

        with mock.patch("ogre.cli.multiprocessing.Process", HangingProcess):
            with self.assertRaises(Exception) as context:
                cli.run_parser_with_timeout(batch_entry, config, FakeManager())

        self.assertIn("parsing timed out", str(context.exception))
        self.assertTrue(instances[0].closed)
        self.assertTrue(instances[0].terminated)
        self.assertTrue(instances[0].killed)
```

- [ ] **Step 3: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_cli_hardening -v
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add test/test_cli_hardening.py
git commit -m "test: characterize parser timeout wrappers"
```

---

### Task 8: Characterize CLI Dispatch And Mocked Archive Reporting

**Files:**
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Add filesystem and sys imports**

Extend the import section in `test/test_cli_hardening.py`:

```python
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock
```

- [ ] **Step 2: Make the test class use the temp-folder helper**

Add the helper import and change the class definition:

```python
from .hardening_helpers import TempFolderTestCase


class TestCliHardening(TempFolderTestCase):
    temp_name = "cli_hardening"
```

Keep all existing test methods in the class.

- [ ] **Step 3: Add CLI dispatch and parse_archive tests**

Append these methods inside `class TestCliHardening(TempFolderTestCase):`

```python
    def test_main_dispatches_list_subcommand(self):
        with mock.patch("ogre.cli.display_plugin_list") as handler:
            with mock.patch.object(
                sys,
                "argv",
                [
                    "dfir-ogre",
                    "list",
                    "--configuration",
                    os.path.join("test", "data", "test_commands.yaml"),
                    "--case",
                    "case1",
                ],
            ):
                cli.main()

        handler.assert_called_once()
        args = handler.call_args.args[0]
        self.assertEqual(args.configuration, os.path.join("test", "data", "test_commands.yaml"))
        self.assertEqual(args.case, "case1")

    def test_parse_archive_writes_report_and_cleans_tmp_folder(self):
        report_folder = os.path.join(self.temp_folder, "report")
        output_folder = os.path.join(self.temp_folder, "output")
        tmp_folder = os.path.join(self.temp_folder, "tmp")
        os.makedirs(tmp_folder, exist_ok=True)

        run_config = OgreRunConfiguration(
            [SimpleNamespace(file="input.txt")],
            "plugin.xml",
            "mapping",
            "module",
            "Parser",
            False,
            5,
        )
        prepared = SimpleNamespace(
            errors=[],
            runs=SimpleNamespace(map={"plugin.xml": run_config}),
            computer="host1",
            orc_id="orc1",
            output_folder=output_folder,
            report_folder=report_folder,
            tmp_folder=tmp_folder,
        )

        with mock.patch("ogre.cli.prepare_runs", return_value=prepared):
            with mock.patch("ogre.cli.multiprocessing.Manager", return_value=object()):
                with mock.patch(
                    "ogre.cli.run_parser_with_timeout",
                    return_value=make_run_result(rows=6, time_s=1.0),
                ) as runner:
                    report = cli.parse_archive(
                        "config.yaml",
                        "archive.7z",
                        {"case": "case1"},
                        None,
                        "dfir-ogre orc",
                    )

        runner.assert_called_once()
        self.assertEqual(report.computer, "host1")
        self.assertEqual(report.summary[0].rows, 6)
        self.assertFalse(os.path.exists(tmp_folder))

        report_file = os.path.join(report_folder, "report_host1_orc1.json")
        with open(report_file) as file:
            report_json = json.load(file)

        self.assertEqual(report_json["computer"], "host1")
        self.assertEqual(report_json["summary"][0]["rows"], 6)
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
uv run python -m unittest test.test_cli_hardening -v
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add test/test_cli_hardening.py
git commit -m "test: characterize CLI dispatch and reports"
```

---

### Task 9: Full Verification

**Files:**
- No file changes.

- [ ] **Step 1: Run the full unittest suite**

Run:

```bash
uv run python -m unittest
```

Expected: `OK`.

- [ ] **Step 2: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intentional task changes are present. The pre-existing `test/test_timeline.py` local modification must remain unstaged unless the user explicitly asks to include it.

- [ ] **Step 3: Commit any missed intentional test-harness changes**

If `git status --short` shows intentional files from this plan that were not committed in earlier tasks, stage only those files and commit:

```bash
git add src/ogre/commands.py test/hardening_helpers.py test/test_dfir_orc_unpack_hardening.py test/test_py7zr.py test/plugin_config/batched_void.xml test/test_commands_hardening.py test/test_cli_hardening.py
git commit -m "test: complete hardening harness"
```

Expected: no commit is created when all earlier task commits were already made.

---

## Self-Review Notes

- Spec coverage: archive errors, metadata parsing, rename behavior, command cache, state leakage, run preparation, report aggregation, params parsing, timeout wrappers, CLI dispatch, mocked report writing, and full `unittest` verification are covered.
- Scope control: the plan does not split large production modules and only changes `src/ogre/commands.py` for test stability.
- Test style: all tests use `unittest`, matching the current repository.
- Verification command: the plan uses `uv run python -m unittest`, because `pytest` is not currently installed as a project executable.
