# Folder Artifact Input Design

## Goal

Let an investigator parse a folder of ordinary artifact files from one computer using the existing OGRE configuration and parser pipeline. The files need no DFIR-ORC archive, `Outcome.json`, `GetThis.csv`, or other ORC structure. Folder input uses only `archive_file_pattern` mappings; `original_file_pattern` mappings do not apply.

The source artifact files must remain untouched.

## Command-line interface

Add a `folder` subcommand:

```bash
dfir-ogre folder \
    --folder /evidence/host-01 \
    --configuration configuration/ogre.yaml \
    --computer_name host-01 \
    --case incident-42
```

`--folder` and `--configuration` are required. `--computer_name` is optional; when omitted, use the input folder's name after resolving the path. `--case` has the same default and meaning as on `orc`. Folder mode does not take an archive password. Reject an input whose resolved path has no usable folder name.

The existing `orc`, `timeline`, `plugin`, and `list` command behavior remains unchanged. Folder input is scoped to the new `folder` command; it does not add a folder option to `timeline`.

## Selection and execution flow

1. Load the configuration and validate that the input is a readable directory before starting parsers.
2. Recursively enumerate regular files without following symbolic links. Exclude the configured output, report, and temporary directory trees if they are strict descendants of the input folder. Reject a configuration that makes one of those directories equal to the input folder. Take a stable, sorted snapshot of candidate paths before parser execution so files created during the run cannot enter the scan.
3. Express each candidate as a path relative to the input folder, with `/` separators. Compile each `archive_file_pattern` case-insensitively and apply the same `re.match` behavior used for archive members. The regexp controls which files and directory depths match. There is no implicit filename-only match. For example, `^events/.*\.evtx$` selects files below `events/`, while `^autoruns\.csv$` selects only a root-level file.
4. Ignore `original_file_pattern` mappings in folder mode. A file may match multiple `archive_file_pattern` mappings and must be sent to each selected parser, as archive mode does. Use the existing plugin lookup, batch grouping, timeouts, output configuration, and parser execution path. Pass the source file path directly to the parser; do not copy or extract it.

The folder scanner is a separate input planner. Parser scheduling and execution are shared with archive mode, avoiding a second implementation of plugin running. Folder scanning must not call the 7z unpacker or construct synthetic ORC metadata.

## Output paths and provenance

Use the supplied or derived computer name for parser metadata and `$computer_name` templates. Resolve existing `$archive_name` templates to the input folder's name so current output configurations can be reused. Folder mode supplies no `$orc_id` or ORC start date.

For each matched file, set the existing metadata fields as follows:

| Field | Folder-mode value |
| --- | --- |
| `computer` | Supplied `--computer_name`, otherwise input folder name |
| `folder` | Input folder name |
| `archive_filename` | Path of the artifact relative to the input folder, using `/` |
| `archive`, `subarchive`, `orc_id`, `orc_start_date`, `original_filename`, `vss` | Unset |

`archive_filename` is reused to preserve file-level provenance in current plugin output without changing `dfir_ogre_common.Metadata`. Its value is a folder-relative artifact path in this mode, even though the field name mentions an archive.

Write a folder-specific JSON run report with the same `summary`, `run_results`, and `parsing_errors` structures as an archive report. It also includes `timestamp`, `command_line`, `ogre_version`, `computer`, `output_folder`, the resolved absolute `source_folder`, a generated `run_id`, and `scan_errors`. It has no ORC ID. Name the file `report_<safe-computer-name>_<run-id>.json`; sanitize only the filename component, preserving the supplied computer name in metadata. The existing archive report schema and filename remain unchanged.

## Errors and boundaries

- A missing, non-directory, or unreadable input root is a command error and returns a nonzero status before parser execution.
- Symbolic links are skipped, including links to files or directories outside the input root. Skipped links do not become parser inputs.
- A readable folder with no matching files still writes a zero-result report, records the reason in `scan_errors`, emits a clear warning, and returns a nonzero status. A configuration containing only `original_file_pattern` mappings falls into this case.
- An unreadable child directory is recorded as a scan error while readable parts of the folder continue. An unreadable matched file or parser failure is recorded in the report while other matched files continue. The command returns a nonzero status when scan or parsing errors are recorded.
- The command never deletes or modifies source files. Output, report, and temporary paths are checked against the input root before writing to prevent source cleanup or recursive ingestion.

## Verification

Add focused tests for root-only and nested relative-path regexes, case-insensitive matching, multiple matches for one file, ignored `original_file_pattern` rules, and a configuration with no matching files. Cover explicit and fallback computer names; provenance in parser output and the folder report; a batch parser; symlink skipping and internal output directory exclusion; missing and unreadable paths; and source-file preservation. Run an existing `.7z` CLI path to verify archive behavior remains intact.
