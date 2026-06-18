# CLI Orchestration Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `src/ogre/cli.py` into focused CLI orchestration modules while preserving command-line behavior, report output, timeout handling, and cleanup.

**Architecture:** Keep `ogre.cli.main()` as the script entry point and argparse owner. Move report aggregation to `ogre.reports`, child-process timeout handling to `ogre.process_runner`, ORC archive execution to `ogre.archive_runner`, and standalone plugin execution to `ogre.plugin_runner`. Existing run preparation, parser execution, archive unpacking, and timeline generation remain in their current modules.

**Tech Stack:** Python 3.10, `argparse`, `multiprocessing`, `dataclasses`, `json`, `unittest`/`pytest`, `dfir_ogre_common`, `uv run --with pytest python -m pytest`.

---

## File Structure

- Create: `src/ogre/reports.py`
  - Owns `ParserResult`, `ArchiveReport`, `ReportBuilder`, and `DataclassJSONEncoder`.
- Create: `src/ogre/process_runner.py`
  - Owns child-process parser execution, timeout lifecycle, and child command wrappers.
- Create: `src/ogre/archive_runner.py`
  - Owns `handle_orc_archive()` and `parse_archive()` for ORC archive execution and report writing.
- Create: `src/ogre/plugin_runner.py`
  - Owns `run_plugin()` and `parse_params()` for the standalone `dfir-ogre plugin` command.
- Modify: `src/ogre/cli.py`
  - Keep `main()`, `display_plugin_list()`, and timeline glue.
  - Import focused runner functions with underscore aliases for dispatch.
  - Remove moved implementation code.
- Modify: `test/test_cli_hardening.py`
  - Move imports and mocks to the new module boundaries.
  - Keep `main()` dispatch coverage against `ogre.cli`.

## Baseline

- [ ] **Step 1: Confirm the existing suite is green**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
65 passed
```

Do not continue if this fails. Investigate and record the failing test before starting the refactor.

---

### Task 1: Extract Report Aggregation

**Files:**
- Create: `src/ogre/reports.py`
- Modify: `src/ogre/cli.py`
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Write the failing report import test change**

In `test/test_cli_hardening.py`, change the imports and report logger assertion exactly this way:

```diff
 from ogre import cli
-from ogre.cli import DataclassJSONEncoder, ReportBuilder, parse_params
+from ogre.cli import parse_params
+from ogre.reports import DataclassJSONEncoder, ReportBuilder
 from ogre.commands import OgreRunConfiguration, RunResult
```

```diff
-        with self.assertLogs("ogre.cli", level="ERROR") as logs:
+        with self.assertLogs("ogre.reports", level="ERROR") as logs:
```

- [ ] **Step 2: Run the focused report tests and verify failure**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_report_builder_aggregates_summary_and_errors \
  test/test_cli_hardening.py::TestCliHardening::test_dataclass_json_encoder_serializes_report_dataclasses \
  -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ogre.reports'`.

- [ ] **Step 3: Create `src/ogre/reports.py`**

Create `src/ogre/reports.py` with this complete content:

```python
import json
import logging
from dataclasses import asdict, dataclass, is_dataclass

from typing_extensions import override

from .commands import RunResult

logger = logging.getLogger(__name__)


@dataclass
class ParserResult:
    """Aggregated statistics for a single parser across many files."""

    parser: str
    runs: int
    rows: int
    time: float
    errors: list[str]


@dataclass
class ArchiveReport:
    """JSON-serialisable report for an ORC processing run."""

    timestamp: str
    command_line: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    summary: list[ParserResult]
    run_results: list[RunResult]


class ReportBuilder:
    timestamp: str
    command_line: str
    computer: str
    orc_id: str
    output_folder: str
    extract_errors: list[str]
    parsing_errors: list[str]
    run_results: list[RunResult]
    summary_builder: dict[str, ParserResult]

    def __init__(
        self,
        timestamp: str,
        command_line: str,
        computer: str,
        orc_id: str,
        output_folder: str,
    ):
        self.timestamp = timestamp
        self.command_line = command_line
        self.computer = computer
        self.orc_id = orc_id
        self.output_folder = output_folder
        self.extract_errors = []
        self.parsing_errors = []
        self.run_results = []
        self.summary_builder = {}

    def add_extract_error(self, error: str):
        self.extract_errors.append(error)

    def add_parsing_error(self, error: str):
        self.parsing_errors.append(error)

    def add_result(self, result: RunResult, file):
        self.run_results.append(result)

        parser_result = self.summary_builder.get(result.mapping_label, None)
        if not parser_result:
            parser_result = ParserResult(result.mapping_label, 0, 0, 0.0, [])
        parser_result.runs += 1
        parser_result.rows += result.rows
        parser_result.time += result.time_s

        if result.last_error:
            error = f"{result.num_errors} error(s) occurred while parsing data: '{result.mapping_label}', file: '{file}', parser: '{result.parser}', last error: {result.last_error}"
            logger.error(error)
            parser_result.errors.append(error)
            self.parsing_errors.append(error)

        self.summary_builder[result.mapping_label] = parser_result

    def get_report(self) -> ArchiveReport:
        summary = []
        for val in self.summary_builder.values():
            summary.append(val)
        summary.sort(key=lambda x: x.parser)

        return ArchiveReport(
            self.timestamp,
            self.command_line,
            self.computer,
            self.orc_id,
            self.output_folder,
            self.extract_errors,
            self.parsing_errors,
            summary,
            self.run_results,
        )


class DataclassJSONEncoder(json.JSONEncoder):
    """JSON encoder capable of serialising dataclass instances."""

    @override
    def default(self, o):
        if is_dataclass(o):
            return asdict(o)  # ignore  # pyright: ignore[reportArgumentType]
        return super().default(o)
```

- [ ] **Step 4: Update `src/ogre/cli.py` to import reports**

In `src/ogre/cli.py`, add:

```python
from .reports import ArchiveReport, DataclassJSONEncoder, ReportBuilder
```

Remove these imports because report code no longer lives in `cli.py`:

```python
from dataclasses import asdict, dataclass, is_dataclass
from typing_extensions import override
```

Delete the local definitions of `ParserResult`, `ArchiveReport`, `ReportBuilder`, and `DataclassJSONEncoder` from the bottom of `src/ogre/cli.py`.

Keep the existing `parse_archive()` return annotation as:

```python
) -> ArchiveReport:
```

- [ ] **Step 5: Run the focused report tests and verify pass**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_report_builder_aggregates_summary_and_errors \
  test/test_cli_hardening.py::TestCliHardening::test_dataclass_json_encoder_serializes_report_dataclasses \
  -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
65 passed
```

- [ ] **Step 7: Commit the report extraction**

Run:

```bash
git add src/ogre/reports.py src/ogre/cli.py test/test_cli_hardening.py
git commit -m "refactor: extract cli report aggregation"
```

---

### Task 2: Extract Process Timeout Runner

**Files:**
- Create: `src/ogre/process_runner.py`
- Modify: `src/ogre/cli.py`
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Write the failing process runner test changes**

In `test/test_cli_hardening.py`, change the package import:

```diff
-from ogre import cli
+from ogre import cli, process_runner
```

Change timeout runner patches and calls:

```diff
-        with mock.patch("ogre.cli.multiprocessing.Process", FinishedProcess):
-            result = cli.run_parser_with_timeout(batch_entry, config, FakeManager())
+        with mock.patch("ogre.process_runner.multiprocessing.Process", FinishedProcess):
+            result = process_runner.run_parser_with_timeout(batch_entry, config, FakeManager())
```

```diff
-        with mock.patch("ogre.cli.multiprocessing.Process", HangingProcess):
+        with mock.patch("ogre.process_runner.multiprocessing.Process", HangingProcess):
             with self.assertRaises(Exception) as context:
-                cli.run_parser_with_timeout(batch_entry, config, FakeManager())
+                process_runner.run_parser_with_timeout(batch_entry, config, FakeManager())
```

```diff
-        with mock.patch("ogre.cli.multiprocessing.Process", HangingProcess):
+        with mock.patch("ogre.process_runner.multiprocessing.Process", HangingProcess):
             with self.assertRaises(Exception) as context:
-                cli.run_batch_parser_with_timeout(config, FakeManager())
+                process_runner.run_batch_parser_with_timeout(config, FakeManager())
```

Add this test method inside `TestCliHardening` after `test_run_parser_with_timeout_returns_child_result`:

```python
    def test_run_parser_with_timeout_raises_when_child_produces_no_result(self):
        class FakeManager:
            def list(self):
                return []

        class FinishedWithoutResult:
            def __init__(self, target, args):
                return None

            def start(self):
                return None

            def join(self, timeout=None):
                return None

            def is_alive(self):
                return False

        config = OgreRunConfiguration([], "plugin.xml", "mapping", "module", "Parser", False, 5)
        batch_entry = SimpleNamespace(file="input.txt", metadata=SimpleNamespace())

        with mock.patch("ogre.process_runner.multiprocessing.Process", FinishedWithoutResult):
            with self.assertRaises(Exception) as context:
                process_runner.run_parser_with_timeout(batch_entry, config, FakeManager())

        self.assertEqual(
            str(context.exception),
            "The parsing process crashed and did not produce a report",
        )
```

- [ ] **Step 2: Run the focused process tests and verify failure**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_run_parser_with_timeout_returns_child_result \
  test/test_cli_hardening.py::TestCliHardening::test_run_parser_with_timeout_raises_when_child_produces_no_result \
  test/test_cli_hardening.py::TestCliHardening::test_run_parser_with_timeout_terminates_hanging_process \
  test/test_cli_hardening.py::TestCliHardening::test_run_batch_parser_with_timeout_terminates_hanging_process \
  -q
```

Expected: FAIL with `ImportError` for `process_runner` or `ModuleNotFoundError: No module named 'ogre.process_runner'`.

- [ ] **Step 3: Create `src/ogre/process_runner.py`**

Create `src/ogre/process_runner.py` with this complete content:

```python
import datetime
import logging
import multiprocessing
from multiprocessing.managers import ListProxy, SyncManager
from typing import Callable

from dfir_ogre_common import BatchEntry

from .commands import (
    OgreRunConfiguration,
    RunResult,
    metadata_to_dict,
    run_batch_parser,
    run_parser,
)

logger = logging.getLogger(__name__)


def run_parser_with_timeout(
    batch_entry: BatchEntry,
    config: OgreRunConfiguration,
    manager: SyncManager,
) -> RunResult:
    return _run_with_timeout(
        run_parser_command,
        (batch_entry, config),
        config.timeout,
        manager,
    )


def run_batch_parser_with_timeout(
    config: OgreRunConfiguration,
    manager: SyncManager,
) -> RunResult:
    return _run_with_timeout(
        run_batch_parser_command,
        (config,),
        config.timeout,
        manager,
    )


def _run_with_timeout(
    target: Callable[..., None],
    args: tuple,
    timeout: int,
    manager: SyncManager,
) -> RunResult:
    result = manager.list()
    process = multiprocessing.Process(target=target, args=(*args, result))
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join(1)
        if not process.is_alive():
            process.close()
        raise Exception(f"parsing timed out, could not finish in {timeout} seconds")
    if len(result) == 0:
        raise Exception("The parsing process crashed and did not produce a report")

    return result.pop()


def run_parser_command(
    batch_entry: BatchEntry,
    config: OgreRunConfiguration,
    result: ListProxy,
):
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_parser(batch_entry, config))
    except Exception as error:
        message = f"A critical error occurred while parsing file '{config.batch_entries}' with parser: '{config.parser}' from module: '{config.module}' error: {error}"
        logger.error(message)

        result.append(
            RunResult(
                config.mapping_label,
                1,
                message,
                0,
                0,
                0,
                config.parser,
                config.module,
                start_date,
                metadata_to_dict(batch_entry.metadata),
                [],
            )
        )


def run_batch_parser_command(config: OgreRunConfiguration, result: ListProxy):
    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        result.append(run_batch_parser(config))
    except Exception as error:
        message = f"A critical error occurred while parsing file '{config.batch_entries}' with parser: '{config.parser}' from module: '{config.module}' error: {error}"
        logger.error(message)

        result.append(
            RunResult(
                config.mapping_label,
                1,
                message,
                0,
                0,
                0,
                config.parser,
                config.module,
                start_date,
                {},
                [],
            )
        )
```

- [ ] **Step 4: Update `src/ogre/cli.py` to use `process_runner`**

Add this import:

```python
from .process_runner import run_batch_parser_with_timeout, run_parser_with_timeout
```

Remove these imports if they are no longer used in `src/ogre/cli.py` after deleting the local process functions:

```python
from multiprocessing.managers import ListProxy, SyncManager
from dfir_ogre_common import BatchEntry
from .commands import metadata_to_dict, run_batch_parser, run_parser
```

Delete these local functions from `src/ogre/cli.py`:

```python
run_parser_with_timeout
run_batch_parser_with_timeout
run_parser_command
run_batch_parser_command
```

Keep `multiprocessing` imported in `src/ogre/cli.py` for now because `parse_archive()` still creates `multiprocessing.Manager()` until Task 3.

- [ ] **Step 5: Run the focused process tests and verify pass**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_run_parser_with_timeout_returns_child_result \
  test/test_cli_hardening.py::TestCliHardening::test_run_parser_with_timeout_raises_when_child_produces_no_result \
  test/test_cli_hardening.py::TestCliHardening::test_run_parser_with_timeout_terminates_hanging_process \
  test/test_cli_hardening.py::TestCliHardening::test_run_batch_parser_with_timeout_terminates_hanging_process \
  -q
```

Expected:

```text
4 passed
```

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
66 passed
```

- [ ] **Step 7: Commit the process runner extraction**

Run:

```bash
git add src/ogre/process_runner.py src/ogre/cli.py test/test_cli_hardening.py
git commit -m "refactor: extract parser process runner"
```

---

### Task 3: Extract Archive Runner

**Files:**
- Create: `src/ogre/archive_runner.py`
- Modify: `src/ogre/cli.py`
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Write the failing archive runner test change**

In `test/test_cli_hardening.py`, change the package import:

```diff
-from ogre import cli, process_runner
+from ogre import archive_runner, cli, process_runner
```

In `test_parse_archive_writes_report_and_cleans_tmp_folder`, change patches and the call:

```diff
-        with mock.patch("ogre.cli.prepare_runs", return_value=prepared):
-            with mock.patch("ogre.cli.multiprocessing.Manager", return_value=object()):
+        with mock.patch("ogre.archive_runner.prepare_runs", return_value=prepared):
+            with mock.patch("ogre.archive_runner.multiprocessing.Manager", return_value=object()):
                 with mock.patch(
-                    "ogre.cli.run_parser_with_timeout",
+                    "ogre.archive_runner.run_parser_with_timeout",
                     return_value=make_run_result(rows=6, time_s=1.0),
                 ) as runner:
-                    report = cli.parse_archive(
+                    report = archive_runner.parse_archive(
                         "config.yaml",
                         "archive.7z",
                         {"case": "case1"},
```

- [ ] **Step 2: Run the focused archive runner test and verify failure**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_parse_archive_writes_report_and_cleans_tmp_folder \
  -q
```

Expected: FAIL with `ImportError` for `archive_runner` or `ModuleNotFoundError: No module named 'ogre.archive_runner'`.

- [ ] **Step 3: Create `src/ogre/archive_runner.py`**

Create `src/ogre/archive_runner.py` with this complete content:

```python
import datetime
import json
import logging
import multiprocessing
import os
import shutil
import sys

from .logging import init_logger
from .process_runner import run_batch_parser_with_timeout, run_parser_with_timeout
from .reports import ArchiveReport, DataclassJSONEncoder, ReportBuilder
from .run_preparation import prepare_runs

logger = logging.getLogger(__name__)


def handle_orc_archive(args):
    init_logger(args.configuration)
    if args.case:
        global_vars = {"case": str(args.case)}
    else:
        global_vars = {}

    _ = parse_archive(
        args.configuration,
        args.archive,
        global_vars,
        args.password,
        " ".join(sys.argv),
    )


def parse_archive(
    configuration: str,
    archive: str,
    global_vars: dict[str, str],
    password: str | None,
    command_line: str,
) -> ArchiveReport:
    logger.info(f"Unpacking archive '{archive}'")

    start_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    prepared_runs = prepare_runs(configuration, archive, password, global_vars)
    report_builder = ReportBuilder(
        start_date,
        command_line,
        prepared_runs.computer,
        prepared_runs.orc_id,
        prepared_runs.output_folder,
    )
    for errors in prepared_runs.errors:
        logger.error(f"{errors}")
        report_builder.add_extract_error(errors)

    manager = multiprocessing.Manager()
    for run_configuration in prepared_runs.runs.map.values():
        if run_configuration.batch:
            try:
                logger.info(f"Running a batch of {len(run_configuration.batch_entries)} files with parser '{run_configuration.parser}', for mapping label '{run_configuration.mapping_label}' ")
                result = run_batch_parser_with_timeout(run_configuration, manager)
                report_builder.add_result(result, f"A batch of {len(run_configuration.batch_entries)} files")
            except Exception as error:
                message = f"An error occurred while parsing a batch of {len(run_configuration.batch_entries)} with parser: '{run_configuration.parser}'  for mapping label '{run_configuration.mapping_label}' error: {error}"
                logger.error(message)
                report_builder.add_parsing_error(message)
        else:
            for batch_entry in run_configuration.batch_entries:
                try:
                    logger.info(f"Running '{run_configuration.parser}', on file '{batch_entry.file}' ")
                    result = run_parser_with_timeout(batch_entry, run_configuration, manager)
                    report_builder.add_result(result, batch_entry.file)
                except Exception as error:
                    message = f"An error occurred while parsing file '{batch_entry.file}' with parser: '{run_configuration.parser}' from module: '{run_configuration.module}' error: {error}"
                    logger.error(message)
                    report_builder.add_parsing_error(message)

    archive_report = report_builder.get_report()
    json_str = json.dumps(archive_report, cls=DataclassJSONEncoder)
    report_name = f"report_{prepared_runs.computer}_{prepared_runs.orc_id}.json"

    os.makedirs(prepared_runs.report_folder, exist_ok=True)
    report_file = os.path.join(prepared_runs.report_folder, report_name)
    logger.info(f"Writing report: {report_file}")
    with open(report_file, "w") as file:
        _ = file.write(json_str)

    logger.info(f"Deleting temporary data: {prepared_runs.tmp_folder}")
    shutil.rmtree(prepared_runs.tmp_folder, ignore_errors=True)

    return archive_report
```

- [ ] **Step 4: Update `src/ogre/cli.py` to use `archive_runner`**

Add these imports:

```python
from .archive_runner import handle_orc_archive as _handle_orc_archive
from .archive_runner import parse_archive as _parse_archive
```

Change the `orc` parser default:

```diff
-    orc.set_defaults(func=handle_orc_archive)
+    orc.set_defaults(func=_handle_orc_archive)
```

In `handle_timeline()`, change the archive call:

```diff
-    report = parse_archive(
+    report = _parse_archive(
```

Delete local `handle_orc_archive()` and `parse_archive()` from `src/ogre/cli.py`.

Remove these imports from `src/ogre/cli.py` if they are no longer used:

```python
import datetime
import json
import multiprocessing
from .reports import ArchiveReport, DataclassJSONEncoder, ReportBuilder
from .process_runner import run_batch_parser_with_timeout, run_parser_with_timeout
from .commands import prepare_runs
```

- [ ] **Step 5: Run the focused archive runner test and verify pass**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_parse_archive_writes_report_and_cleans_tmp_folder \
  -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
66 passed
```

- [ ] **Step 7: Commit the archive runner extraction**

Run:

```bash
git add src/ogre/archive_runner.py src/ogre/cli.py test/test_cli_hardening.py
git commit -m "refactor: extract archive runner"
```

---

### Task 4: Extract Plugin Runner

**Files:**
- Create: `src/ogre/plugin_runner.py`
- Modify: `src/ogre/cli.py`
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Write the failing plugin runner test changes**

In `test/test_cli_hardening.py`, change imports:

```diff
-from ogre import archive_runner, cli, process_runner
-from ogre.cli import parse_params
+from ogre import archive_runner, cli, plugin_runner, process_runner
+from ogre.plugin_runner import parse_params
```

Add this test method after `test_parse_params_preserves_current_string_conversion`:

```python
    def test_run_plugin_logs_unknown_plugin(self):
        plugin_file = os.path.join(self.temp_folder, "unknown_plugin.xml")
        with open(plugin_file, "w") as file:
            file.write('<plugin parser="NoSuchParser" />')

        args = SimpleNamespace(
            filename=os.path.join(self.temp_folder, "input.txt"),
            plugin_config=plugin_file,
            computer_name="host1",
            output_folder=self.temp_folder,
            output_format=None,
            output_date_format=None,
            params=None,
            timeline=False,
            include_empty=False,
            library=None,
        )

        with mock.patch("ogre.plugin_runner.importlib.import_module") as import_module:
            with self.assertLogs("ogre.plugin_runner", level="ERROR") as logs:
                plugin_runner.run_plugin(args)

        import_module.assert_called_once_with("dfir_ogre_plugin_windows")
        self.assertIn("Unknown plugin 'NoSuchParser'", "\n".join(logs.output))
```

- [ ] **Step 2: Run the focused plugin tests and verify failure**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_parse_params_preserves_current_string_conversion \
  test/test_cli_hardening.py::TestCliHardening::test_run_plugin_logs_unknown_plugin \
  -q
```

Expected: FAIL with `ImportError` for `plugin_runner` or `ModuleNotFoundError: No module named 'ogre.plugin_runner'`.

- [ ] **Step 3: Create `src/ogre/plugin_runner.py`**

Create `src/ogre/plugin_runner.py` with this complete content:

```python
import importlib
import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from dfir_ogre_common import (
    BatchEntry,
    Metadata,
    OgreBatchedPlugin,
    OgrePlugin,
    OutputConfiguration,
    RunConfiguration,
)

from .logging import init_logger

logger = logging.getLogger(__name__)


def run_plugin(args):
    init_logger()

    output_name = Path(args.filename).stem

    importlib.import_module("dfir_ogre_plugin_windows")
    if args.library:
        importlib.import_module(args.library)

    format = "jsonl"
    if args.output_format:
        format = args.output_format

    date_format = "iso"
    if args.output_date_format:
        date_format = args.output_date_format

    rust_output = OutputConfiguration(
        output_name,
        args.output_folder,
        "file",
        format,
        date_format,
        args.timeline,
        False,
        args.include_empty,
        {},
    )

    plugin_file = args.plugin_config

    tree = ET.parse(plugin_file)
    root = tree.getroot()
    plugin = root.attrib.get("parser")
    is_batch = root.attrib.get("batch", None)

    params = parse_params(args.params)

    runconfig = RunConfiguration([rust_output], False, params)
    metadata = Metadata(args.computer_name)

    metadata.archive_filename = args.filename

    found = False
    if is_batch:
        for parser in OgreBatchedPlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        [BatchEntry(args.filename, runconfig, Metadata("test"))],
                        plugin_file,
                    )

                    if result.last_error:
                        logger.error(
                            f"file: '{args.filename}' with parser: '{plugin}' error: {result.last_error}"
                        )
                except Exception as error:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {error}"
                    )
    else:
        for parser in OgrePlugin.__subclasses__():
            parser_obj = parser()
            parser_descr = parser_obj.description()
            if parser_descr.get_command() == plugin:
                found = True
                try:
                    logger.info(f"Running '{plugin}', on file '{args.filename}' ")

                    result = parser_obj.parse(
                        args.filename,
                        plugin_file,
                        runconfig,
                        metadata,
                    )

                    if result.last_error:
                        logger.error(
                            f"file: '{args.filename}' with parser: '{plugin}' error: {result.last_error}"
                        )
                except Exception as error:
                    logger.error(
                        f"file: '{args.filename}' with parser: '{plugin}' error: {error}"
                    )

    if not found:
        logger.error(f"Unknown plugin '{plugin}'")


def parse_params(params) -> dict[str, str | None]:
    if not params:
        return {}

    json_data = json.loads(params)
    param_dict = {}
    if isinstance(json_data, dict):
        for key, value in json_data.items():
            param_dict[key] = str(value)

    return param_dict
```

- [ ] **Step 4: Update `src/ogre/cli.py` to use `plugin_runner`**

Add this import:

```python
from .plugin_runner import run_plugin as _run_plugin
```

Change the plugin parser default:

```diff
-    run.set_defaults(func=run_plugin)
+    run.set_defaults(func=_run_plugin)
```

Delete local `run_plugin()` and `parse_params()` from `src/ogre/cli.py`.

Remove these imports from `src/ogre/cli.py` if they are no longer used:

```python
import importlib
import json
import xml.etree.ElementTree as ET
from dfir_ogre_common import (
    BatchEntry,
    Metadata,
    OgrePlugin,
    OgreBatchedPlugin,
    OutputConfiguration,
    RunConfiguration,
)
```

Keep this import in `src/ogre/cli.py` because it registers the built-in `Void` parser when the `ogre` package imports `cli`:

```python
from .void_parser import VoidParser as VoidParser
```

- [ ] **Step 5: Run the focused plugin tests and verify pass**

Run:

```bash
uv run --with pytest python -m pytest \
  test/test_cli_hardening.py::TestCliHardening::test_parse_params_preserves_current_string_conversion \
  test/test_cli_hardening.py::TestCliHardening::test_run_plugin_logs_unknown_plugin \
  -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
67 passed
```

- [ ] **Step 7: Commit the plugin runner extraction**

Run:

```bash
git add src/ogre/plugin_runner.py src/ogre/cli.py test/test_cli_hardening.py
git commit -m "refactor: extract plugin runner"
```

---

### Task 5: Final CLI Cleanup and Boundary Verification

**Files:**
- Modify: `src/ogre/cli.py`
- Modify: `test/test_cli_hardening.py`

- [ ] **Step 1: Update `src/ogre/cli.py` to the final import shape**

After the previous tasks, the top of `src/ogre/cli.py` should have this import block:

```python
"""
Command line interface for DFIR-OGRE.
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

import yaml
from tabulate import tabulate

from .archive_runner import handle_orc_archive as _handle_orc_archive
from .archive_runner import parse_archive as _parse_archive
from .commands import list_parsers
from .logging import init_logger
from .plugin_runner import run_plugin as _run_plugin
from .timeline import build_timeline
from .void_parser import VoidParser as VoidParser

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Update CLI dispatch aliases**

In `main()`, these defaults should use the imported runner aliases:

```python
    orc.set_defaults(func=_handle_orc_archive)
```

```python
    run.set_defaults(func=_run_plugin)
```

The list and timeline defaults should stay local:

```python
    list_parser.set_defaults(func=display_plugin_list)
```

```python
    timeline.set_defaults(func=handle_timeline)
```

- [ ] **Step 3: Update timeline to call the archive runner alias**

In `handle_timeline()`, the archive execution call should be:

```python
    report = _parse_archive(
        args.configuration,
        args.archive,
        global_vars,
        args.password,
        " ".join(sys.argv),
    )
```

- [ ] **Step 4: Confirm no old helper imports remain in tests**

Run:

```bash
rg -n "from ogre\\.cli import|ogre\\.cli\\.multiprocessing|ogre\\.cli\\.prepare_runs|ogre\\.cli\\.run_parser_with_timeout|ogre\\.cli\\.parse_archive|ogre\\.cli\\.run_batch_parser_with_timeout" test src
```

Expected: no output.

- [ ] **Step 5: Confirm the CLI entry point is still package-visible**

Run:

```bash
uv run --with pytest python -m pytest test/test_main.py::TestMain::test_main_run -q
```

Expected:

```text
1 passed
```

- [ ] **Step 6: Run CLI hardening tests**

Run:

```bash
uv run --with pytest python -m pytest test/test_cli_hardening.py -q
```

Expected:

```text
10 passed
```

- [ ] **Step 7: Run the full suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
67 passed
```

- [ ] **Step 8: Commit the final CLI cleanup**

Run:

```bash
git add src/ogre/cli.py test/test_cli_hardening.py
git commit -m "refactor: slim cli entry point"
```

---

## Final Verification

- [ ] **Step 1: Review the final module boundaries**

Run:

```bash
wc -l src/ogre/cli.py src/ogre/reports.py src/ogre/process_runner.py src/ogre/archive_runner.py src/ogre/plugin_runner.py
```

Expected: `src/ogre/cli.py` is substantially smaller than its original 771 lines, and each new module has one responsibility.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected:

```text
67 passed
```

- [ ] **Step 3: Check the worktree**

Run:

```bash
git status --short
```

Expected: no output.

- [ ] **Step 4: Inspect the commit series**

Run:

```bash
git log --oneline -n 6
```

Expected: the newest commits include:

```text
refactor: slim cli entry point
refactor: extract plugin runner
refactor: extract archive runner
refactor: extract parser process runner
refactor: extract cli report aggregation
```
