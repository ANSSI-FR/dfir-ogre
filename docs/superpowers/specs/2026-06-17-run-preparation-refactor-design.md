# Run Preparation Refactor Design

## Context

DFIR-Ogre's CLI is the stable compatibility boundary. The `ogre orc`,
`ogre timeline`, and `ogre plugin` commands must keep the same arguments and
observable behavior.

The current run-preparation logic is concentrated in
`src/ogre/commands.py::prepare_runs`. That function currently loads and
validates configuration, loads archive metadata, mutates global variables,
resolves wildcard values, unpacks archives, converts unpacked file mappings into
parser batch entries, builds metadata, and groups parser runs. This makes the
code difficult to test in isolation and brittle to change.

Import compatibility for `prepare_runs()` is not required. It can become a thin
compatibility wrapper or be bypassed by CLI orchestration if the replacement is
clearer. The CLI behavior remains the contract.

## Goals

- Preserve CLI behavior and reports while changing internal structure.
- Refactor in small, test-backed stages.
- Improve testability by separating pure planning logic from archive, file, and
  plugin side effects.
- Improve readability by replacing the single large run-preparation flow with
  named components.
- Improve extensibility for future archive inputs, mapping modes, output
  variable rules, and parser execution modes.
- Improve robustness by reducing hidden mutation and making state transitions
  explicit.

## Non-Goals

- Do not change CLI arguments or user-visible command behavior.
- Do not redesign archive extraction internals in `dfir_orc_unpack.py`.
- Do not redesign parser execution or reporting in `cli.py`.
- Do not introduce a new exception hierarchy in this pass.
- Do not require `prepare_runs()` to remain import-compatible.

## Recommended Approach

Use a staged extraction into a run-preparation pipeline.

The refactor should split `prepare_runs()` into explicit internal stages:

1. Load preparation context.
2. Resolve archive-level report and output variables.
3. Unpack archives and collect returned extraction errors.
4. Convert valid file mappings into parser batch entries.
5. Group batch entries into parser run configurations.

This approach gives immediate readability and testability wins while keeping
each change small enough to review. It can introduce a few internal data objects
where they simplify the stage boundaries, but it should avoid a broad rewrite in
one step.

## Architecture Boundary

The CLI remains the external contract:

`CLI args -> parse_archive() -> run preparation -> unpack_dfir_orc() -> prepared grouped runs -> parser execution -> report`

The new internal run-preparation boundary owns:

- loading validated configuration and plugin definitions
- loading archive metadata
- resolving report, output, plugin, mapping, parser, file, and computer
  variables
- invoking archive unpacking
- converting file mappings into `BatchEntry` objects
- grouping entries by parser/plugin configuration

Archive unpacking, parser execution, and report writing remain outside this
refactor. The new code should call existing dependencies such as
`load_archive_metadata()`, `unpack_dfir_orc()`, and `load_plugin_parser()` rather
than redesigning those modules.

## Components

### RunPreparationContext

Owns request-wide state for one preparation request:

- configuration path
- archive input
- password
- caller-provided global variables
- loaded `Configuration`
- loaded plugin definitions
- loaded `OrcOutcome`

The context should make derived globals explicit, including `computer_name`,
`orc_id`, and `orc_start_date`.

### VariableResolver

Centralizes wildcard replacement rules currently spread through
`prepare_runs()`:

- `$case`
- `$timestamp`
- `$archive_name`
- `$dir_tree`
- `$output_folder`
- `$plugin_folder`
- `$mapping_label`
- `$parser`
- `$file_name`
- `$computer_name`

It should expose small methods for each resolution level, such as report-folder
resolution, archive-level output resolution, run-level output resolution,
plugin-file resolution, and mapping-param resolution.

### ArchiveRunPlanner

Iterates over archives listed in `OrcOutcome`, calls `unpack_dfir_orc()`, keeps
the current extraction-error behavior, and passes valid `FileMapping` objects to
the batch-entry stage.

### BatchEntryBuilder

Converts a `FileMapping` plus resolved mapping/output configuration into:

- `RunConfiguration`
- `Metadata`
- `BatchEntry`

Metadata construction should be isolated here so archive, subarchive, ORC id,
ORC date, archive filename, original filename, VSS, creation date, and
modification date behavior can be tested directly.

### RunConfigGrouper

Replaces the current grouping behavior behind `RunConfigMap.add_configuration()`
with a clearer internal grouping component. It should preserve the same
effective grouping behavior for batch and non-batch parsers.

## Data Flow

The refactored flow should preserve these steps:

1. Load config and plugin definitions from the YAML file and global variables.
2. Load archive metadata from the archive input string or path.
3. Add the existing derived globals: `computer_name`, `orc_id`, and
   `orc_start_date`.
4. Resolve report folder once from archive metadata.
5. For each archive listed in metadata:
   - build an archive-specific resolved config view
   - resolve archive-level output folders and base file names
   - call `unpack_dfir_orc()`
   - append unpacking errors unchanged
   - resolve plugin file, parser definition, run-level output configs,
     metadata, additional params, and batch entry for each valid file mapping
6. Group entries into `OgreRunConfiguration` objects.
7. Return the same effective information required by `parse_archive()`.

## Behavior To Preserve

- Same CLI arguments and observable CLI behavior.
- Same wildcard expansion results.
- Same archive metadata fields.
- Same grouping behavior for batch and non-batch parsers.
- Same returned extraction errors versus raised configuration or
  parser-definition errors.
- Same temp, report, and output folder semantics.
- Same parser cache behavior, with cache reset available for tests.
- Same report behavior through `parse_archive()`.

## Error Handling

Keep the current external error behavior for this pass:

- `unpack_dfir_orc()` errors remain returned as extraction errors in reports.
- bad config, bad regex, unknown output names, missing parser XML attributes,
  and missing loaded parsers may still raise.
- parser execution errors remain handled by existing CLI/reporting code.

The robustness improvement should come from structure:

- avoid mutating shared `global_var`, `Configuration`, `Mapping`, and
  `OutputConfiguration` objects in-place where practical
- make each stage return new values instead of relying on hidden mutation
- isolate wildcard replacement in one component
- keep archive-specific state explicit
- keep parser cache behavior explicit through the existing helper

## Testing Strategy

The staged refactor should add or adjust focused tests around each extracted
boundary:

1. Add tests for `VariableResolver` using existing YAML and archive metadata
   scenarios.
2. Extract metadata construction into `BatchEntryBuilder` and assert it
   preserves the current metadata contract.
3. Extract output, plugin, and additional-parameter resolution and pin wildcard
   behavior.
4. Extract archive iteration and extraction-error aggregation into
   `ArchiveRunPlanner`.
5. Replace the body of `prepare_runs()` with orchestration over the new pieces,
   or update `parse_archive()` to call the new entry point directly.

Run the full test suite after each meaningful step:

```bash
uv run --with pytest python -m pytest
```

## Rollout

Implement in small commits:

1. Add the new run-preparation module and pure variable-resolution tests.
2. Move metadata construction into a builder with tests.
3. Move output/plugin/param resolution into resolver methods with tests.
4. Move archive iteration and error aggregation into the planner with tests.
5. Replace the old `prepare_runs()` orchestration and run the full suite.
6. Remove or thin compatibility wrappers only after CLI tests prove behavior is
   unchanged.

Each step should preserve CLI behavior and keep the existing hardening tests
passing.
