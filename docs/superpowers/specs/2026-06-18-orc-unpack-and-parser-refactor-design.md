# ORC Unpack And Parser Refactor Design

## Goal

Make `dfir_orc_unpack.py` and `commands.py` easier to understand and maintain while hardening targeted edge cases around ORC metadata parsing, archive mapping, parser execution, and parser result statistics.

## Scope

This refactor keeps the public API and CLI behavior stable. Existing imports from `ogre.dfir_orc_unpack` and `ogre.commands` must continue to work, and serialized report shape must remain compatible.

The work is limited to:

- Splitting ORC metadata loading, mapping helpers, and unpack orchestration into focused modules behind `dfir_orc_unpack.py`.
- Splitting parser result construction and parser execution helpers out of `commands.py`.
- Adding tests for current fragile edge cases before hardening them.
- Preserving existing successful archive extraction and parser execution behavior.

Out of scope:

- Replacing the current result/error style with a full typed exception hierarchy.
- Changing CLI flags or report JSON fields.
- Refactoring run preparation, archive runner, plugin runner, timeline generation, or configuration loading beyond import updates needed for the new module boundaries.

## Architecture

`dfir_orc_unpack.py` remains a compatibility facade. It re-exports the public dataclasses and functions used by tests and by `run_preparation.py`, while implementation moves into smaller files:

- `orc_metadata.py`: owns `OrcOutcome`, `load_archive_metadata`, inline JSON definition parsing, outcome file parsing, comma-separated archive list parsing, and metadata validation.
- `orc_mapping.py`: owns `OriginalNameMapping`, `FileMapping`, `UnpackResult`, `OriginalFileMappingResult`, `NestedArchive`, `GetThis.csv` parsing, original-name lookup helpers, mapping partitioning, and regex compilation helpers.
- `orc_unpacker.py`: owns `unpack_dfir_orc`, archive input validation, nested archive extraction, mapping-file discovery, archive-file matching, original-file matching, and extraction error accumulation.

`commands.py` also remains a compatibility facade for the public parser commands and dataclasses. Internals move into:

- `parser_results.py`: owns `FileStat`, `OutputStat`, `RunResult`, `metadata_to_dict`, plugin report conversion, and safe final statistics calculation.
- `parser_execution.py`: owns single-parser and batch-parser lookup/execution, timing, exception capture, and `RunResult` creation.

This keeps external users on the current import paths while giving each new module one responsibility and a smaller test surface.

## Data Flow

ORC archive processing keeps the same top-level flow:

1. `run_preparation.py` calls `load_archive_metadata()` and `unpack_dfir_orc()` through `ogre.dfir_orc_unpack`.
2. `load_archive_metadata()` delegates to metadata-specific parsing helpers.
3. `unpack_dfir_orc()` validates input, extracts nested archives, builds original-name mappings, splits mappings by match type, and dispatches archive-file and original-file matching.
4. Extraction failures that belong to archive processing continue to accumulate in `UnpackResult.errors`.
5. Successful `FileMapping` objects keep the same fields and semantics consumed by `run_preparation.py`.

Parser execution keeps the same top-level flow:

1. `process_runner.py` calls `run_parser()` and `run_batch_parser()` through `ogre.commands`.
2. Parser execution helpers import the plugin module, locate the requested parser class, execute it, and convert its output report.
3. Result helpers calculate row totals, elapsed time, and row/sec without changing the public `RunResult` fields.
4. Plugin exceptions continue to become `RunResult.last_error`; missing parsers remain explicit `TypeError`s.

## Hardening

The refactor adds narrow behavior fixes where the current code can fail unclearly:

- Empty archive metadata input must raise a clear validation error instead of indexing an empty archive list.
- Inline JSON archive definitions must validate that the parsed value is an object and that `unencrypted_data_files`, `hostname`, `id`, and `timestamp` are present and usable.
- Outcome files must validate the `dfir-orc` root, `outcome` node, iterable `command_set`, and archive names before path construction.
- Comma-separated archive strings must ignore whitespace-only entries and reject the result when no archive remains.
- Invalid archive and original regex patterns must include the pattern and mapping label in their error message.
- Parser result finalization must avoid division by zero when a parser returns instantly or produces no output rows.
- Parser report conversion must handle empty output reports without treating a successful parse as a crash.

Existing extraction failures that are already represented as `UnpackResult.errors` should stay in that error list. The refactor should not convert those failures into top-level exceptions unless the current API already raises for that path.

## Testing

Implementation must follow test-first development for behavioral hardening:

- Add focused tests for ORC metadata edge cases before changing metadata parsing.
- Add focused tests for invalid regex context before changing mapping validation.
- Add focused tests for zero-time or zero-row parser result finalization before changing parser result code.
- Add focused tests for parser report conversion with empty output reports before changing parser execution.

Refactor-only module moves are verified by the existing suite and by keeping compatibility imports in place.

Final verification command:

```bash
uv run --with pytest python -m pytest -q
```

Expected result: all tests pass with no unrelated output changes.

## Compatibility Requirements

The following imports must continue to work:

```python
from ogre.dfir_orc_unpack import (
    FileMapping,
    OrcOutcome,
    UnpackResult,
    load_archive_metadata,
    unpack_dfir_orc,
)
from ogre.commands import (
    FileStat,
    OutputStat,
    RunResult,
    list_parsers,
    metadata_to_dict,
    run_batch_parser,
    run_parser,
)
```

No caller should need to change unless it imports private helpers from the old large files.

## Risks

The highest-risk area is archive extraction, because it depends on real sample archive contents, password handling, nested archives, and filename renaming behavior. That risk is managed by keeping `unpack_dfir_orc()` behavior-compatible and running the existing real-archive tests after each extraction-related move.

The parser execution risk is smaller but still visible: report statistics are consumed by JSON reports and summary generation. The new result helpers must preserve field names, defaults, and rounding behavior except for the explicit division-by-zero hardening.
