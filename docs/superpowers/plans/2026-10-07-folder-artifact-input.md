# Folder Artifact Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `dfir-ogre folder` for artifacts from one computer and add collision-safe `$relative_path` output naming to folder and ORC runs.

**Architecture:** A folder scanner yields the existing `FileMapping`/`UnpackResult` shape, and both input modes feed the same mapping planner, parser execution loop, and `ReportBuilder`. The ORC unpacker carries logical member paths for naming; folder mode reads source files directly and adds only folder-specific metadata and report fields.

**Tech Stack:** Python 3.10+, `unittest`, `argparse`, `pathlib`, `py7zr`, existing `dfir_ogre_common` bindings.

**Spec:** `docs/superpowers/specs/2026-10-07-folder-artifact-input-design.md`

## Global Constraints

- Folder mode processes one computer; `--computer_name` defaults to the resolved folder basename and must be one nonempty path component.
- Folder matching uses only `archive_file_pattern`, with `re.IGNORECASE` and `re.match` against root-relative paths using `/`. Ignore `original_file_pattern` regexes and plugin XML in folder mode.
- Folder parsers receive the source file path. Scanning and cleanup preserve selected source artifacts; do not invoke the 7z unpacker for folder input.
- `$relative_path` works only in `output_folder` and `base_file_name`; it is empty at the folder/outer-archive root and includes the nested archive stem and parent path for ORC members.
- Existing templates without `$relative_path`, existing ORC report JSON/filenames, and the `orc`, `timeline`, `plugin`, and `list` commands retain their behavior. Do not modify `dfir-ogre-common`.
- Use `.venv/bin/python -m unittest` for tests. The full suite uses `multiprocessing.Manager` local sockets and needs an environment that permits them; the approved-spec baseline passed 107 tests with that access.

## Review Focus

| Input or failure mode | Expected behavior | Owning test |
| --- | --- | --- |
| Different paths `a/b_c/file` and `a/b/c/file` flatten to the same basename | Planned output basenames become distinct and stable | Task 4 collision test |
| Existing output directory is a symlink into the source folder | Resolved target is excluded or rejected before scanning | Task 5 symlink destination test |
| An unreadable child directory sits beside a readable matched file | Scan error is recorded while the readable file is selected | Task 2 child-error test |
| An ignored original-name mapping contains an invalid regex | Folder mode loads and runs archive-name rules; `orc` still rejects the regex | Task 2 scoped-validation test |
| An ORC member is renamed on disk during extraction | `$relative_path` uses the stored archive member and nested archive path | Task 1 renamed-member test |

---

## File map

| File | Responsibility |
| --- | --- |
| `src/ogre/orc_mapping.py`, `src/ogre/orc_unpacker.py` | Carry and populate a logical parent path for ORC members. |
| `src/ogre/folder_input.py` (new) | Validate the folder and destination paths; scan files into existing mapping results. |
| `src/ogre/output_naming.py` (new) | Expand the new path variable and disambiguate resolved output basenames. |
| `src/ogre/run_preparation.py` | Scope regex validation, share the mapping-to-entry planner, and prepare folder runs. |
| `src/ogre/archive_runner.py`, `src/ogre/reports.py` | Share parser execution and report writing while keeping ORC report shape. |
| `src/ogre/folder_runner.py` (new), `src/ogre/cli.py` | Expose the folder command and its folder-specific report/exit status. |
| `README.md` | Explain the folder command, pattern selection, and `$relative_path`. |

### Task 1: Carry logical ORC member parents

**Files:** Modify `src/ogre/orc_mapping.py`, `src/ogre/orc_unpacker.py`; test `test/test_dfir_orc_unpack_hardening.py`.

**Interfaces:** Add `FileMapping.relative_path: str = ""` as a trailing field so existing constructors still work. Add `source_relative_parent(member_path: str, nested_archive_member: str | None = None) -> str` in `orc_mapping.py`. The second argument is the nested archive's logical path inside the outer archive, including `.7z`.

- [ ] **Step 1: Write failing provenance tests.** In a new `TestRelativePathProvenance`, assert `source_relative_parent("a.evtx") == ""`, `source_relative_parent("logs/a.evtx") == "logs"`, and `source_relative_parent("logs/a.evtx", "collection/inner.7z") == "collection/inner/logs"`. Build a nested test archive as in `TestDfirOrcUnpackHardening` and assert both archive-name and original-name `FileMapping.relative_path` values use the logical nested path even when `FileMapping.file` is renamed.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_dfir_orc_unpack_hardening.TestRelativePathProvenance -q`.** Expect failure because the field/helper does not exist.
- [ ] **Step 3: Implement the field/helper and populate it at the three mapping creation sites:** direct archive members, nested archive members, and original-name matches. Recover a nested archive's logical path relative to `archive_extract_folder/.inner`; normalize member separators to `/`. Keep existing metadata and extraction destinations.
- [ ] **Step 4: Run the Task 1 test class and `test.test_dfir_orc_unpack`.** Expect both to pass.
- [ ] **Step 5: Commit the three Task 1 files** with message `feat: retain logical ORC member parents`.

### Task 2: Scope mapping validation and scan folder artifacts

**Files:** Modify `src/ogre/run_preparation.py`; create `src/ogre/folder_input.py`; test `test/test_run_preparation.py` and new `test/test_folder_input.py`.

**Interfaces:** Extend `load_config(conf_file: str, global_var: dict[str, str], *, pattern_scope: Literal["all", "archive"] = "all") -> tuple[Configuration, dict[str, PluginDefinition]]`. Add `scan_folder(root: Path, mappings: Sequence[Mapping], exclusions: Sequence[Path]) -> UnpackResult`. The scanner expects a validated, resolved root and resolved exclusion paths.

- [ ] **Step 1: Write failing tests.** In `test_run_preparation`, load YAML with a valid archive-name rule and invalid original-name regex: `pattern_scope="archive"` succeeds, while the default raises an error containing `original_file_pattern`. In `TestFolderScan`, create root `a.evtx`, nested `logs/b.EVTX`, and a symlink; use `^a\\.evtx$` and `^logs/.*\\.evtx$` to assert root-only and nested selection, sorted `(archive_file, mapping_label)` pairs, and case-insensitive `re.match`. Assert one file can appear twice for two mappings and the symlink never appears. Mock one child `os.scandir` failure and assert `result.errors` contains it while a sibling match remains.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_folder_input.TestFolderScan test.test_run_preparation.TestRunPreparationConfigLoading -q`.** Expect the new contract tests to fail.
- [ ] **Step 3: Implement selectable validation using the existing `compile_mapping_pattern`/`partition_mappings` helpers; implement a sorted, no-symlink scanner.** Each match yields `FileMapping(file=str(source), archive_name="", archive_file=relative_posix, original_file=None, original_creation_date=None, original_modification_date=None, mapping=rule, vss=None, error=None, relative_path=parent)`. Record child traversal errors in `UnpackResult.errors`.
- [ ] **Step 4: Run the Task 2 tests and `test.test_run_preparation`.** Expect all to pass.
- [ ] **Step 5: Commit the four Task 2 files** with message `feat: select folder artifacts with archive patterns`.

### Task 3: Resolve source names and the new template variable

**Files:** Modify `src/ogre/run_preparation.py`; create `src/ogre/output_naming.py`; test `test/test_run_preparation.py`.

**Interfaces:** Add `RunVariables(computer_name: str, date: datetime, dir_tree: str | None)`. Let `VariableResolver` accept `OrcOutcome | RunVariables`. Add optional keyword `source_name: str | None = None` to `resolve_archive_output`, `resolve_plugin_file`, and `resolve_mapping_params`; `None` retains `Path(archive).stem`. Add `relative_path: str = ""` to `resolve_run_output`. In `output_naming.py`, add `expand_relative_path(template: str, relative_path: str, *, filename: bool) -> str`.

- [ ] **Step 1: Write failing `TestRelativePathResolver` tests.** With folder name `host.v2`, assert `$archive_name` resolves to `host.v2` in output, plugin path, and params, while an ORC archive `main.7z` still resolves to `main`. Assert `base_file_name="$relative_path/$file_name"` becomes `a` for root `a.evtx` and `logs_a` for `logs/a.evtx`; assert `output_folder="$output_folder/$relative_path"` preserves `/logs`. Assert a folder identity without `dir_tree` uses the configuration fallback, and an unchanged template retains its exact prior output.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_run_preparation.TestRelativePathResolver -q`.** Expect failure before implementation.
- [ ] **Step 3: Implement the signatures and field-specific expansion.** For templates using `$relative_path`, remove one adjacent `/` or `_` when the value is empty; flatten path separators only in `base_file_name`; reject an empty resolved output folder. Preserve the old replacement path for templates without the new variable and the existing physical-path meaning of `$file_name`.
- [ ] **Step 4: Run the new resolver tests and existing `TestVariableResolver`.** Expect all to pass.
- [ ] **Step 5: Commit the Task 3 files** with message `feat: expand relative artifact paths in outputs`.

### Task 4: Disambiguate planned output basenames

**Files:** Modify `src/ogre/output_naming.py`; create `test/test_output_naming.py`.

**Interfaces:** Add `OutputNameRegistry.register(output: OutputConfiguration, *, source_key: str, mapping_label: str, output_name: str, uses_relative_path: bool) -> None` and `OutputNameRegistry.finalize() -> None`. The registry holds references to resolved, mutable `OutputConfiguration` objects; Task 6 registers each built output and calls `finalize` once after all source files are planned.

- [ ] **Step 1: Write failing `TestOutputNameRegistry` tests.** Register two outputs with the same resolved folder and flattened name for `a/b_c/file` and `a/b/c/file`; after `finalize()`, assert their `base_file_name` values differ and that rebuilding the same registry yields the same names. Register a legacy output with the same initial name and assert its name stays unchanged while the new relative-path output changes. Include two different outer archive keys in one registry.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_output_naming -q`.** Expect failure because the registry is missing.
- [ ] **Step 3: Implement collision detection across canonical `(output_folder, base_file_name)` pairs.** Use a stable digest of source key, mapping label, and output name as a readable suffix for new relative-path outputs; reserve all initial names and check final names, adding a deterministic numeric disambiguator if needed. Leave legacy outputs unchanged.
- [ ] **Step 4: Run `.venv/bin/python -m unittest test.test_output_naming -q`.** Expect all tests to pass.
- [ ] **Step 5: Commit the Task 4 files** with message `feat: disambiguate relative-path output names`.

### Task 5: Protect folder inputs from configured destinations

**Files:** Modify `src/ogre/folder_input.py`, `src/ogre/logging.py`; test `test/test_folder_input.py` and `test/test_cli_hardening.py`.

**Interfaces:** Add `validate_folder_root(folder: str) -> Path`, `plan_folder_exclusions(root: Path, configuration: Configuration, resolver: VariableResolver, conf_file: str) -> tuple[Path, ...]`, and `validate_concrete_folder_outputs(root: Path, runs: RunConfigGrouper) -> None`. Add `configured_log_paths(conf_file: str) -> tuple[Path, ...]` in `logging.py`, covering the active log file and configured rotated backups.

- [ ] **Step 1: Write failing `TestFolderPathPolicy` tests.** Assert missing/file/unreadable roots fail; a configured output/report/temp destination equal to or above the root fails; a destination strictly below the root is excluded; a symlinked destination is classified by its resolved target; an in-root log file and backup are excluded; and a dynamic output template under the root with no separable fixed area fails. Assert concrete per-file output folders get the same overlap check before parsing.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_folder_input.TestFolderPathPolicy -q`.** Expect failure for missing policy functions.
- [ ] **Step 3: Implement path policy with `Path.resolve(strict=False)` and path-component ancestry checks; attempt to scan the root to establish readability.** Derive fixed output prefixes after known template values are substituted; treat `$relative_path`, `$file_name`, and `$parser` as per-file values. Use `TYPE_CHECKING` for `run_preparation` type imports to avoid a runtime import cycle. Refactor the existing log setting read into a helper shared by `configured_log_paths` and `init_logger`; the folder command calls `init_logger` only after this preflight. Keep ORC logging timing unchanged.
- [ ] **Step 4: Run the Task 5 tests and `test.test_cli_hardening`.** Expect all to pass.
- [ ] **Step 5: Commit the Task 5 files** with message `feat: keep folder inputs outside output cleanup`.

### Task 6: Prepare folder runs through the shared planner

**Files:** Modify `src/ogre/run_preparation.py`; create `test/test_folder_preparation.py`.

**Interfaces:** Add `MappingRunPlanner(configuration: Configuration, parsers: dict[str, PluginDefinition], resolver: VariableResolver, builder: BatchEntryBuilder, load_parser: Callable[[str], tuple[str, bool]])` with `add_source(source: str, file_mappings: Sequence[FileMapping], runs: RunConfigGrouper, *, source_name: str | None = None) -> None`. Let `BatchEntryBuilder.__init__` accept `outcome: OrcOutcome | RunVariables` plus keyword-only `metadata_factory: Callable[[str, FileMapping], Metadata] | None = None` and `name_registry: OutputNameRegistry | None = None`, preserving current positional arguments and ORC defaults. Add `source_name: str | None = None` to `build`. Add `prepare_folder_runs(conf_file: str, folder: str, computer_name: str | None, global_var: dict[str, str] | None = None, *, started_at: datetime | None = None) -> PrepareRunResult`. Extend `PrepareRunResult` with nullable `orc_id`/`archive` and optional `source_folder`/`run_id`; no fake archive or ORC values.

- [ ] **Step 1: Write failing `TestFolderPreparation` tests.** With `host.v2/logs/a.txt`, assert `BatchEntry.file` is the original absolute file path, metadata contains `computer="host.v2"`, `folder="host.v2"`, and `archive_filename="logs/a.txt"`, while archive/ORC fields are unset. Assert an explicit computer name overrides the fallback, two mappings still yield two entries, original-only mappings yield a no-match error without loading their plugin XML, and a patched 7z unpacker is never called. In an ORC planner test, change only the extraction temp UUID and assert colliding relative-path outputs receive the same suffixes.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_folder_preparation -q`.** Expect failure before folder preparation exists.
- [ ] **Step 3: Extract the `ArchiveRunPlanner` mapping-to-entry loop into `MappingRunPlanner`; have both modes use it.** For collision registration, derive `source_key` from the resolved folder root and root-relative file path, or from the outer archive identity, logical `FileMapping.relative_path`, and `archive_file` for ORC. Do not use `FileMapping.file` or `archive_name`: original-name mappings can store temporary extraction paths in both. Add mapping label and output key to the registry identity. Use one registry for the entire command and call `finalize()` after all entries are planned. Folder preparation composes Tasks 2–5, uses the configuration-generated temp UUID as `run_id`, sets `orc_id=None`, and validates concrete outputs before returning.
- [ ] **Step 4: Run `.venv/bin/python -m unittest test.test_folder_preparation test.test_run_preparation test.test_commands_hardening -q`.** Expect all to pass and existing ORC grouping/metadata assertions to remain valid.
- [ ] **Step 5: Commit the Task 6 files** with message `feat: prepare folder files through shared planner`.

### Task 7: Share execution and report writing

**Files:** Modify `src/ogre/archive_runner.py`, `src/ogre/reports.py`; create `test/test_shared_runner.py`.

**Interfaces:** Add `execute_prepared_runs(prepared_runs: PrepareRunResult, command_line: str, timestamp: str) -> ArchiveReport` and `write_report_and_cleanup(report: ArchiveReport | dict[str, Any], prepared_runs: PrepareRunResult, report_name: str) -> str`. Permit `orc_id: str | None` in `ArchiveReport`/`ReportBuilder`; keep the field present in both JSON modes.

- [ ] **Step 1: Write failing `TestSharedRunner` tests.** With zero runs and `orc_id=None`, assert the report has empty `summary`/`run_results` and that `multiprocessing.Manager` was not started. With one mocked parser result, assert `ReportBuilder` produces the existing summary/error fields. For `parse_archive`, assert the report filename remains `report_<computer>_<orc-id>.json` and its JSON lacks `source_folder`/`run_id`.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_shared_runner -q`.** Expect failure for missing shared functions.
- [ ] **Step 3: Extract the current parser loop and report write/cleanup code from `parse_archive` into the two helpers.** Keep batch grouping, timeouts, error aggregation, and successful-write cleanup behavior. Skip creating a Manager only for a zero-run plan. Have `parse_archive` call the helpers with its current timestamp and filename.
- [ ] **Step 4: Run `.venv/bin/python -m unittest test.test_shared_runner test.test_cli_hardening -q`.** Expect all to pass.
- [ ] **Step 5: Commit the Task 7 files** with message `refactor: share prepared-run execution and reports`.

### Task 8: Expose the folder command and document it

**Files:** Create `src/ogre/folder_runner.py`, `test/test_folder_runner.py`; modify `src/ogre/cli.py`, `README.md`, `test/test_cli_hardening.py`.

**Interfaces:** Add `parse_folder(configuration: str, folder: str, global_vars: dict[str, str], computer_name: str | None, command_line: str) -> dict[str, Any]` and `handle_folder(args: argparse.Namespace) -> None`. Add `folder` parser with required `--folder`/`--configuration`, optional `--computer_name`, and `--case` defaulting to `default_case`.

- [ ] **Step 1: Write failing CLI/report tests.** Assert `cli.main()` dispatches the four folder arguments. For a temporary folder and test sample plugin, assert parser output references the source path and folder metadata, and report JSON includes absolute `source_folder`, UUID `run_id`, `orc_id: null`, and the existing report fields. Assert no-match, child-scan-error, and parser-error runs write reports then exit with status 1, with a warning for no matches; missing root and computer names `""`, `"."`, `".."`, and `"host/other"` exit nonzero before parsing. Compare source contents before/after and keep an unrelated sibling in the temporary root to prove cleanup targets only the generated child. Test a name such as `host:one` to show report filename sanitization preserves the metadata value.
- [ ] **Step 2: Run `.venv/bin/python -m unittest test.test_folder_runner -q`.** Expect failure before the command exists.
- [ ] **Step 3: Implement the folder wrapper and CLI parser.** Capture one UTC start value for templates/report, call `prepare_folder_runs` before `init_logger`, then call Task 7 helpers. Extend the report dictionary only for folder runs; sanitize the computer name only for `report_<safe-computer>_<run-id>.json`. Set a nonzero process status after the report is written when `extract_errors` or `parsing_errors` is nonempty.
- [ ] **Step 4: Add README examples** for `dfir-ogre folder`, root-relative `archive_file_pattern`, and `$relative_path` in both output fields; state that the default config's original-name mappings are skipped in folder mode.
- [ ] **Step 5: Run `.venv/bin/python -m unittest test.test_folder_runner test.test_cli_hardening test.test_main -q`, then `.venv/bin/python -m unittest discover -s test -t . -q` with local socket access.** Expect the full suite to pass, including the existing ORC CLI path. Run `git diff --check`.
- [ ] **Step 6: Commit the Task 8 files** with message `feat: add folder artifact command`.
