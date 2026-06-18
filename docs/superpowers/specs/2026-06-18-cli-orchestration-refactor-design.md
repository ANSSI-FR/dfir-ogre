# CLI Orchestration Refactor Design

## Context

DFIR-Ogre's command-line behavior is the stable compatibility boundary. The
`dfir-ogre list`, `dfir-ogre orc`, `dfir-ogre plugin`, and
`dfir-ogre timeline` commands must keep the same arguments and observable
behavior.

The current `src/ogre/cli.py` module mixes several responsibilities:

- argparse construction and command dispatch
- ORC archive execution and report writing
- child-process timeout management
- single-plugin execution
- report dataclasses, summary aggregation, and JSON encoding
- timeline-specific pre/post processing

This makes CLI behavior harder to test in isolation and encourages future
changes to accumulate in one large module. Recent work already extracted run
preparation into `src/ogre/run_preparation.py`; this refactor should preserve
that boundary and focus on the next high-value split.

Import compatibility for helper functions and classes currently located in
`ogre.cli` is not required. The compatibility contract is the command-line
interface and generated report behavior, not internal helper imports.

## Goals

- Preserve CLI arguments, command behavior, report shape, timeout behavior, and
  cleanup behavior.
- Make `ogre.cli` a thin entry point for parser construction and dispatch.
- Move archive execution, process timeout handling, single-plugin execution,
  and report aggregation into focused modules.
- Improve testability by allowing each behavior to be exercised without
  importing the full CLI parser.
- Keep the refactor staged and test-backed.

## Non-Goals

- Do not change CLI arguments or user-visible command semantics.
- Do not redesign parser execution in `ogre.commands`.
- Do not redesign run planning in `ogre.run_preparation`.
- Do not redesign archive extraction in `ogre.dfir_orc_unpack`.
- Do not introduce a new exception hierarchy in this pass.
- Do not preserve internal imports from `ogre.cli` unless doing so is cheaper
  than removing them.

## Recommended Approach

Use a responsibility-based split around the existing CLI workflow.

Keep `ogre.cli.main()` as the package script entry point, but move the work
behind each command into modules with one clear purpose:

1. Report aggregation and JSON encoding.
2. Child-process timeout execution.
3. ORC archive execution and report writing.
4. Single-plugin command execution.
5. Thin argparse setup and dispatch.

This approach has more file movement than extracting only `parse_archive()`,
but it directly addresses the current mixed responsibilities without replacing
the CLI with a new command framework.

## Architecture Boundary

The external boundary remains:

`CLI args -> command handler -> run preparation/parser execution/reporting`

The refactored internal boundary should be:

- `ogre.cli` owns only command-line parser setup, dispatch, and lightweight
  command handler glue.
- `ogre.archive_runner` owns the `orc` archive workflow.
- `ogre.process_runner` owns child-process timeout behavior.
- `ogre.plugin_runner` owns the `plugin` single-file workflow.
- `ogre.reports` owns report dataclasses, report aggregation, and dataclass JSON
  encoding.
- Existing `ogre.commands`, `ogre.run_preparation`, `ogre.dfir_orc_unpack`, and
  `ogre.timeline` keep their current responsibilities.

## Components

### `ogre.cli`

`ogre.cli` should stay small. It builds the argparse tree, wires each subcommand
to a handler, initializes logging where the current behavior requires it, and
passes parsed arguments to the focused modules.

It continues to expose `main()` for the `dfir-ogre` script entry point.

### `ogre.reports`

Owns:

- `ParserResult`
- `ArchiveReport`
- `ReportBuilder`
- `DataclassJSONEncoder`

This module should not import argparse, multiprocessing, or plugin execution
code. It receives `RunResult` objects and produces report dataclasses and JSON
encoding support.

### `ogre.process_runner`

Owns parser child-process execution with timeout behavior.

It should expose the current single and batch entry points, or expose a generic
helper with small single and batch wrappers. The behavior to preserve is:

- create a manager-backed result list
- start a child process
- wait for the configured timeout
- terminate, wait, kill, wait, and close when a process remains alive
- raise the current timeout-style exception after stopping a timed-out process
- raise the current crash exception when the child produces no result
- return the child-produced `RunResult` when successful

The child command wrappers that call `run_parser()` and `run_batch_parser()` can
live in this module because they are part of the child-process protocol.

### `ogre.archive_runner`

Owns the current `parse_archive()` workflow:

1. Log archive unpacking.
2. Call `prepare_runs()`.
3. Build a `ReportBuilder`.
4. Add extraction errors to the report.
5. Iterate prepared run configurations.
6. Call `process_runner` for batch and non-batch parser execution.
7. Add parser results and parser errors to the report.
8. Write the JSON report file.
9. Remove the run temp folder.
10. Return the `ArchiveReport`.

This module should not build argparse parsers and should not know how to execute
the standalone `plugin` command.

### `ogre.plugin_runner`

Owns the current `dfir-ogre plugin` single-file workflow:

- parse command-line params JSON into string values
- import `dfir_ogre_plugin_windows`
- import an optional custom plugin library
- parse the XML plugin config
- build `OutputConfiguration`, `RunConfiguration`, and `Metadata`
- find and run the matching `OgrePlugin` or `OgreBatchedPlugin`
- log unknown plugins and parser errors as today

The existing `parse_params()` behavior should be preserved, including returning
an empty dict for non-object JSON and stringifying values such as booleans and
`null`.

## Data Flow

For `dfir-ogre orc`:

`cli.main()` -> parsed args -> `archive_runner.handle_orc_archive()` ->
`archive_runner.parse_archive()` -> `prepare_runs()` ->
`process_runner.run_parser_with_timeout()` or
`process_runner.run_batch_parser_with_timeout()` -> `ReportBuilder` -> JSON
report file -> temp cleanup.

For `dfir-ogre timeline`:

`cli.main()` -> parsed args -> timeline handler -> create timeline, temp, and
data folders -> call `archive_runner.parse_archive()` with `report_folder` in
global variables -> call `build_timeline()` -> remove timeline temp and data
folders.

For `dfir-ogre plugin`:

`cli.main()` -> parsed args -> `plugin_runner.run_plugin()` -> import plugin
modules -> parse XML config -> execute matching `OgrePlugin` or
`OgreBatchedPlugin`.

## Behavior To Preserve

- Same CLI subcommands and arguments.
- Same report dataclass fields and JSON output shape.
- Same report filename pattern:
  `report_<computer>_<orc_id>.json`.
- Same extraction-error aggregation.
- Same parser-error aggregation.
- Same parser timeout lifecycle and error messages.
- Same child-process crash behavior when no result is appended.
- Same single-plugin execution behavior.
- Same timeline output creation and cleanup behavior.
- Same temp folder cleanup after archive report writing.

## Error Handling

Keep external error behavior unchanged:

- `prepare_runs()` extraction errors are logged and stored as report
  `extract_errors`.
- Parser run failures caught during archive execution are logged and stored as
  report `parsing_errors`.
- Child parser exceptions still become `RunResult` objects from the child
  command wrappers.
- Timed-out child processes are terminated, killed if still alive, closed when
  stopped, and then reported through the same timeout-style exception.
- A child process that exits without appending a result still raises the current
  crash exception.
- Bad config, bad plugin XML, missing parser, and invalid params can continue
  to raise as they do today.

The refactor should improve structure, not introduce new failure semantics.

## Testing Strategy

Use characterization-first tests:

1. Move report aggregation and JSON encoding tests to import from
   `ogre.reports`.
2. Move timeout lifecycle tests to import from `ogre.process_runner`.
3. Add or move archive execution tests to import from `ogre.archive_runner`,
   using mocked `prepare_runs()` and mocked process runner calls.
4. Move plugin parameter parsing tests to import from `ogre.plugin_runner`.
5. Keep `ogre.cli.main()` dispatch coverage so subcommand wiring remains
   tested.
6. Leave command, run-preparation, configuration, and archive extraction tests
   unchanged unless imports need updating because of the split.

Run the full test suite after each meaningful stage:

```bash
uv run --with pytest python -m pytest -q
```

## Rollout

Implement in small stages:

1. Extract report dataclasses, builder, and JSON encoder into `ogre.reports`.
2. Extract child-process timeout helpers and child command wrappers into
   `ogre.process_runner`.
3. Extract the archive execution workflow into `ogre.archive_runner`.
4. Extract single-plugin execution and param parsing into `ogre.plugin_runner`.
5. Reduce `ogre.cli` to parser setup, logging setup, command dispatch, and
   timeline glue.
6. Update tests and run the full suite after each stage.

Each stage should keep the command-line behavior working and keep the suite
green before moving on.
