# Test Harness Hardening Design

## Context

DFIR-Ogre is a Python CLI that extracts Windows forensic artifacts from DFIR-ORC archives and runs configured parser plugins. The current codebase is small, but several modules carry multiple responsibilities:

- `src/ogre/dfir_orc_unpack.py` handles archive metadata loading, nested archive extraction, `GetThis.csv` parsing, file matching, rename handling, and extraction error aggregation.
- `src/ogre/commands.py` handles configuration loading, plugin discovery, wildcard expansion, archive preparation, metadata construction, parser execution, and run grouping.
- `src/ogre/cli.py` handles argument parsing, command handlers, archive workflow orchestration, multiprocessing timeout wrappers, single-plugin execution, and report generation.

The next larger refactor should be protected by a characterization test harness first. This design focuses on pinning existing behavior and making only low-risk hardening changes.

## Goals

- Add focused tests around current public seams so future refactoring can preserve behavior confidently.
- Document current contracts for archive metadata, extraction mappings, prepared parser runs, report summaries, timeout handling, and CLI dispatch.
- Preserve current user-visible behavior unless an existing failing test or explicit future decision says otherwise.
- Keep production code changes small and local, limited to hardening that directly supports test reliability.

## Non-Goals

- Do not split `cli.py`, `commands.py`, or `dfir_orc_unpack.py` into new architecture modules in this pass.
- Do not redesign configuration parsing, plugin discovery, archive extraction, or report generation.
- Do not normalize all exception and returned-error behavior yet.
- Do not rewrite existing tests wholesale; improve or add targeted tests where they increase confidence.

## Architecture Boundary

The harness treats the existing modules as the current architecture boundary:

- `dfir_orc_unpack`: archive metadata parsing and extraction/mapping behavior.
- `commands`: configuration validation, wildcard expansion, plugin discovery, run preparation, parser execution, and metadata construction.
- `cli`: command dispatch, archive workflow orchestration, timeout wrappers, report building, JSON encoding, single-plugin execution, and timeline entry points.

Tests should call current public functions directly where possible. Internal helpers may be tested when they already encode important behavior that is difficult to observe through public seams, but those tests should be written as characterization tests, not as a commitment to preserve private helper names forever.

## Test Plan

### Archive Metadata And Extraction

Cover `load_archive_metadata` and `unpack_dfir_orc` behavior:

- JSON archive definition input.
- Outcome file input.
- Comma-separated archive list input.
- Invalid archive paths returning `UnpackResult.errors`.
- Non-7z archive inputs returning `UnpackResult.errors`.
- Invalid JSON archive definitions raising exceptions.
- Missing outcome nodes raising exceptions.
- Original-file pattern mapping.
- Archive-file pattern mapping.
- Windows short-name skip behavior.
- Long-name rename behavior when a stable fixture exists or can be created without fragile archive manipulation.

### Commands And Run Preparation

Cover `load_config`, `load_plugin_parser`, `list_parsers`, `prepare_runs`, `run_parser`, and `run_batch_parser` behavior:

- Configuration validation and regex errors.
- Missing output references.
- Plugin parser cache behavior, including a test-safe cache reset approach if needed.
- Wildcard expansion for case, archive name, timestamp, output folder, report folder, plugin folder, mapping label, parser, file name, computer name, and dir tree.
- Metadata construction for archive, subarchive, ORC id, ORC date, archive filename, original filename, VSS, creation date, and modification date.
- Run grouping by plugin config path.
- Batch versus non-batch parser detection.
- Repeated calls with separate global variable inputs to catch state leakage from mutable defaults or in-place mutation.

### CLI And Reporting

Cover `cli` behavior without invoking unnecessary full extraction when mocks can pin the contract:

- `ReportBuilder` summary aggregation and error aggregation.
- `DataclassJSONEncoder` serialization of report dataclasses.
- `parse_params` handling of empty input, JSON objects, non-string values, and `null` values as currently implemented.
- Timeout wrapper behavior with mocked `multiprocessing.Process` and manager lists.
- CLI dispatch from subcommands to handlers with mocked handlers.
- `parse_archive` report writing and cleanup using existing small fixtures.
- Timeline handler behavior with the existing timeline fixture and the fixed line-count baseline.

## Error Handling Contract

The harness should preserve the current distinction between returned errors and raised exceptions:

- `unpack_dfir_orc` returns an `UnpackResult` with an `errors` list for invalid archive paths, non-7z inputs, nested archive extraction problems, and extraction or matching problems that are currently caught.
- Bad configuration loading and invalid archive metadata parsing raise exceptions.
- Parser execution reports plugin errors through `RunResult.last_error` and `num_errors` where current behavior does so.
- `ReportBuilder` converts `RunResult` errors into parsing errors and parser summaries.

Tests should make these distinctions explicit so future refactoring does not accidentally hide exceptions, convert returned errors into exceptions, or silently drop errors.

## Allowed Hardening

Production code changes are allowed only when they reduce test flakiness or state leakage without changing user-visible behavior:

- Replace mutable default arguments with `None` plus local initialization.
- Add a small test-facing cache reset helper for global plugin parser cache if direct cache mutation would make tests brittle.
- Tighten temp directory cleanup in tests.
- Prevent duplicated logging handlers if tests show repeated logger initialization duplicates output.
- Extract tiny pure helpers only when they directly support stable tests and do not start a broader module split.

Any larger cleanup should be deferred to the future refactor that this harness is meant to support.

## Data Flow To Pin

The harness should preserve the current runtime flow:

`archive input` -> `load_archive_metadata` -> `unpack_dfir_orc` -> `prepare_runs` -> parser execution -> `ReportBuilder` -> JSON report or timeline output.

Tests should pin these handoff values:

- Archive list.
- Computer name.
- ORC id and ORC date.
- Directory tree value.
- Extracted file mappings.
- Mapping labels and plugin config paths.
- Output folders and base file names.
- Parser names and module names.
- Batch entries and run grouping.
- Metadata fields.
- Parser run results.
- Report summaries and collected errors.

## Verification

The baseline verification command is:

```bash
uv run python -m unittest
```

`pytest` is not currently available as a project executable, so the harness should follow the existing `unittest` style unless the project explicitly adds pytest later.

## Rollout

Implement in small commits or reviewable chunks:

1. Add or strengthen characterization tests for archive metadata and extraction.
2. Add or strengthen characterization tests for command preparation and parser run contracts.
3. Add or strengthen characterization tests for CLI reporting, parsing, dispatch, and timeout wrappers.
4. Apply small hardening changes only when tests require them or clearly expose state leakage.
5. Run the full `uv run python -m unittest` suite after each meaningful chunk.
