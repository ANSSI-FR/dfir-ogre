# Folder Artifact Input Design

## Goal

Let an investigator parse a folder of ordinary artifact files from one computer using the existing OGRE configuration and parser pipeline. Keep the command's configuration, execution, output, and report behavior as close to `orc` as the different input source allows. The files need no DFIR-ORC archive, `Outcome.json`, `GetThis.csv`, or other ORC structure. Folder input uses only `archive_file_pattern` mappings; `original_file_pattern` mappings do not apply.

Folder scanning and cleanup leave source artifacts in place. Parsers receive their original file paths through the existing `BatchEntry` interface.

## Command-line interface

Add a `folder` subcommand:

```bash
dfir-ogre folder \
    --folder /evidence/host-01 \
    --configuration configuration/ogre.yaml \
    --computer_name host-01 \
    --case incident-42
```

`--folder` and `--configuration` are required. `--computer_name` is optional; when omitted, use the input folder's name after resolving the path. Validate the effective computer name as a nonempty single path component, without path separators or `.`/`..`, because `$computer_name` is used in output paths. `--case` has the same default and meaning as on `orc`. Folder mode does not take an archive password. Reject an input whose resolved path has no usable folder name.

The existing `orc`, `timeline`, `plugin`, and `list` command behavior remains unchanged. Folder input is scoped to the new `folder` command; it does not add a folder option to `timeline`.

## Existing code and reuse boundary

The current pipeline already provides the pieces folder mode needs:

| Existing code | Use in folder mode |
| --- | --- |
| `build_configuration`, `load_config`, `load_plugins`, `load_plugin_parser` | Load the same YAML, output definitions, parser registry, and plugin XML. Make mapping regex validation selectable so folder mode skips ignored original-name regexes while `orc` still validates both types. |
| `partition_mappings`, `compile_mapping_pattern`, `FileMapping`, `UnpackResult` | Select only archive-name mappings, match with existing case-insensitive regex semantics, and hand selected files plus scan errors to run preparation. The folder scanner sets `FileMapping.file` to the source path and `archive_file` to its folder-relative path. |
| `VariableResolver`, `BatchEntryBuilder`, `RunConfigGrouper`, `PrepareRunResult`, `ArchiveRunPlanner` | Share template expansion, `RunConfiguration`/`BatchEntry` construction, plugin lookup, grouping, and the common prepared-run fields. Extract the planner's existing `FileMapping`-to-entry loop for both input modes; keep archive iteration and 7z unpacking in `ArchiveRunPlanner`. Supply folder metadata at the builder boundary instead of manufacturing an `OrcOutcome` or fake archive fields. |
| `archive_runner`, `process_runner`, `ReportBuilder`, `DataclassJSONEncoder` | Share the existing batch and single-file execution loop, timeouts, result aggregation, and JSON serialization. The two commands select their own preparation and report filename/extra fields around that shared loop. |

Give `VariableResolver` the shared source values it actually uses (computer name, date, and directory tree), or an equivalent small shared context. Pass the source name separately for each archive or folder when resolving templates, because one `orc` run can contain several outer archives. For `orc`, keep current `OrcOutcome` values and archive-stem expansion. For folder mode, use the folder values below. Keep `unpack_dfir_orc` and `load_archive_metadata` exclusive to `orc`. Do not add another parser runner, output writer, plugin registry, or report aggregator.

The shared refactor is limited to the existing mapping-to-entry loop, the execution/report loop, and the resolver inputs they need. Keep source-specific scanning, unpacking, metadata, and report naming at their current boundaries.

`build_configuration` already appends a UUID child to the configured temporary root. Folder mode can use that UUID as its `run_id`; it need not create a second identifier. Cleanup, if needed, targets only that generated child.

## Selection and execution flow

1. Validate that the resolved input is a readable directory and load configuration through the shared loader. The shared YAML mapping schema still applies to ignored original-name mappings, but folder mode neither compiles their regexes nor loads their plugin XML.
2. Before scanning or initializing file logging, resolve paths that OGRE may write to or remove: configured output, report, and temporary areas, the generated temporary child, the optional rotating log file and backups, and the fixed prefixes of mapping output folders. Reject a write or cleanup destination equal to or containing the input root. Reserve destinations strictly inside the input root as output areas and exclude them from scanning. A dynamic output template under the input root must have a separable fixed area to exclude before the scan; otherwise fail before parsing. Resolve existing symlinks when comparing paths. After selecting files, validate every concrete mapped output folder before starting parsers.
3. Take a sorted snapshot of regular file paths by recursively enumerating the input without following symbolic links. Skip files in reserved output areas, including output from earlier runs. Express each candidate relative to the input folder with `/` separators. The snapshot is a list of paths; folder mode does not copy or freeze file contents.
4. Use `partition_mappings` to keep `archive_file_pattern` rules, compile them case-insensitively through `compile_mapping_pattern`, and apply `re.match` to each folder-relative path. The regexp alone controls which depths match; do not retry against the basename. For example, `^events/.*\.evtx$` selects files below `events/`, while `^autoruns\.csv$` selects only a root-level file. A file may match several mappings and is sent to each selected parser, as in archive mode.
5. Produce `FileMapping` entries and scan errors in the existing `UnpackResult` shape. Reuse the shared planning loop to resolve plugin files, outputs, parameters, batch entries, and grouping. Pass each source path directly to its parser. Reuse the existing execution and report aggregation loop.

The folder scanner does not call the 7z unpacker, interpret nested archives, parse `GetThis.csv`, or construct ORC metadata. Existing `archive_file_pattern` configurations can be reused, subject to their regexes matching folder-relative paths.

## Output templates and `$relative_path`

Use the supplied or derived computer name for parser metadata and `$computer_name` templates. In folder mode, `$archive_name` resolves to the complete input folder name, including dots, in output definitions, plugin-file paths, and mapping parameters. `orc` keeps its existing archive-stem behavior in each of those places. Capture folder run start once for `$timestamp` and the report, and use the existing configuration fallback for `$dir_tree`. Folder mode supplies no ORC ID or ORC start date.

Add `$relative_path` to `output_folder` and `base_file_name` templates in both modes. It is the logical parent path of the artifact, with `/` separators:

| Input and artifact | `$relative_path` |
| --- | --- |
| Folder `host` containing `a.evtx`, or outer archive containing `a.evtx` | Empty string |
| Folder or outer archive containing `logs/a.evtx` | `logs` |
| `main.7z` containing `inner.7z` containing `logs/a.evtx` | `inner/logs` |
| `main.7z` containing `collection/inner.7z` containing `a.evtx` | `collection/inner` |

For ORC, derive this from the archive member path. Prefix members of a nested archive with that archive's path inside the outer archive, dropping its `.7z` extension. This also applies to `original_file_pattern` matches: use the stored member path, not the original Windows pathname or a renamed temporary extraction path. Keep the existing `$file_name` expansion unchanged. Carry the logical parent path with `FileMapping` so output naming does not infer it from a temporary path. The current ORC unpacker extracts nested archives into directories named by stem; the new variable must not treat those temporary directory names as the logical path. Nested archives with the same stem in different outer-archive directories already share an extraction destination; changing that existing extraction behavior is outside this feature.

In `output_folder`, `$relative_path` retains its directory separators. In `base_file_name`, replace path separators with `_` and flatten the resulting template to one filename component. When `$relative_path` is empty, remove one immediately following `/` or `_` separator, or one immediately preceding separator if none follows. Thus `$relative_path/$file_name` resolves to `$file_name` alone for a root file. Reject an empty resolved output folder. Do not change `dfir_ogre_common`'s output writer, which creates the output folder and appends data-type and format extensions to `base_file_name`.

Underscore flattening can give the same name to different paths, such as `a/b_c/file` and `a/b/c/file`. Before parser execution, inspect resolved `(output_folder, base_file_name)` pairs across the whole run. For a collision involving a template that uses `$relative_path` in `base_file_name`, add a deterministic suffix based on the logical source identity to the new relative-path outputs, then check the final pairs and disambiguate further if needed. Include outer archive identity and mapping/output identity when relevant. Existing templates without `$relative_path` retain their current names and behavior. This prevents new relative-path naming from sending distinct planned entries to the same base output name; it does not rename pre-existing files from earlier runs.

## Provenance and reports

For each matched file, set the existing metadata fields as follows:

| Field | Folder-mode value |
| --- | --- |
| `computer` | Supplied `--computer_name`, otherwise input folder name |
| `folder` | Input folder name |
| `archive_filename` | Path of the artifact relative to the input folder, using `/` |
| `archive`, `subarchive`, `orc_id`, `orc_start_date`, `original_filename`, `vss` | Unset |

`archive_filename` is reused to preserve file-level provenance in current plugin output without changing `dfir_ogre_common.Metadata`. Its value is a folder-relative artifact path in this mode, even though the field name mentions an archive.

Use `ReportBuilder` for both modes. Keep the archive report's fields and aggregation rules: `timestamp`, `command_line`, `ogre_version`, `computer`, `orc_id`, `output_folder`, `extract_errors`, `parsing_errors`, `summary`, and `run_results`. In folder reports, `extract_errors` holds input scan errors and `orc_id` is `null`. Add the resolved absolute `source_folder` and generated `run_id` only to folder report JSON; archive report JSON stays unchanged. Name the folder file `report_<safe-computer-name>_<run-id>.json`; sanitize only the filename component, preserving the supplied computer name in metadata. Reuse the existing JSON encoder and report writer path.

## Errors and boundaries

- A missing, non-directory, or unreadable input root is a command error and returns a nonzero status before parser execution.
- Symbolic links are skipped, including links to files or directories outside the input root. Skipped links do not become parser inputs.
- A readable folder with no matching files still writes a zero-result report, records the reason in `extract_errors`, emits a clear warning, and returns a nonzero status. A configuration containing only `original_file_pattern` mappings falls into this case.
- An unreadable child directory is recorded in `extract_errors` while readable files continue. A file read failure discovered by a parser goes into `parsing_errors`, using the same report aggregation as `orc`; other matched files continue.
- The folder command returns a nonzero process status when input or parsing errors are recorded. The CLI handler must set that status explicitly because the current dispatcher ignores handler return values. `orc` exit behavior does not change.
- Folder scanning and cleanup never delete, move, or overwrite selected source artifacts. Areas configured for output inside the input root are excluded from the source set. Cleanup removes only the run-generated temporary child after path validation. File logging is initialized only after its destination is accounted for in the scan exclusion and overlap checks.

## Verification

Add focused tests for root-only and nested regexes, case-insensitive matching, multiple matches for one file, ignored `original_file_pattern` rules (including an invalid ignored regex), and no matching files. Cover explicit and fallback computer names, including a dotted folder name; `$archive_name` in output, plugin, and parameter templates; folder provenance and report fields; batch execution through the existing runner; symlink skipping; configured output, report, temp, and log exclusions and overlap rejection; unreadable paths; nonzero folder exit status; and source preservation after cleanup.

Cover `$relative_path` for root and nested folder files; direct, nested, and original-name ORC mappings; a nested archive stored below an outer-archive directory; and an ORC file renamed during extraction. Verify directory structure in `output_folder`, single-component `base_file_name`, empty-root expansion, and deterministic disambiguation of `a/b_c/file` versus `a/b/c/file`. Existing templates without `$relative_path` must keep their names. Run an existing `.7z` CLI path and compare its output/report contract to ensure archive behavior remains intact.

Document the `folder` command, the fact that only `archive_file_pattern` mappings apply, and `$relative_path` examples in the user documentation. The repository's default `ogre.yaml` contains many `original_file_pattern` mappings, so a generic artifact folder may need additional archive-name rules in its configuration.
