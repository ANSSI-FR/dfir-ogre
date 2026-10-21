
# DFIR-Ogre
[![badge_repo](https://img.shields.io/badge/ANSSI--FR-DFIR--Ogre-white)](https://github.com/ANSSI-FR/dfir-ogre)
[![category_badge_external](https://img.shields.io/badge/category-external-%23b556b6)](https://anssi-fr.github.io/README.en.html#project-categories)
[![openess_badge_A](https://img.shields.io/badge/code.gouv.fr-collaborative-blue)](https://anssi-fr.github.io/README.en.html#openness-level)

**DFIR-OGRE** is a command‑line utility that extracts windows forensic artefact from [DFIR-ORC](https://github.com/DFIR-ORC/dfir-orc) archives into structured data that can be consumed by Splunk, ELK or other databases.

It provides a collection of **plug‑ins**, each dedicated to parsing a specific class of Windows artefacts. 
The built‑in plug‑ins cover a lot of artefact that appears in a typical DFIR-ORC archive:
* **Application Specific** – shortcut (`.lnk`) files, Java download index, etc.  
* **Browser artefacts** – Chrome and Firefox extensions, download histories, and general browsing history.  
* **File system** – NTFS information, USN journal entries, recycle‑bin records, etc. 
* **Processes and applications** – AmCache, scheduled tasks, Shell Bags, Prefetch Files, Orc processes, etc.
* **System logs** – Windows Event logs (EVTX), Windows Error Reporting files, SRUM usage databases, etc.


## ⚠️ Beta Status
This software is currently in **beta**. While functional and actively developed, it may still undergo breaking changes, and some artefact parsers may not yet be fully stabilized. We welcome feedback, bug reports, and contributions using the [issue tracker](https://github.com/ANSSI-FR/dfir-ogre/issues).


## Documentation

The full documentation is available on the website : https://anssi-fr.github.io/dfir-ogre-documentation/

## Installation

### Prerequisites

| Item | Minimum version |
|------|-----------------|
| **Python** | 3.10 or newer |
| **git** | any recent version |
| **uv** | ≥ 0.4 (installable with `pip`)


### Clone and install the repositories

```bash
# Choose a location 
mkdir -p ~/dfir-ogre && cd ~/dfir-ogre

git clone https://github.com/ANSSI-FR/dfir-ogre-plugin-windows.git
git clone https://github.com/ANSSI-FR/dfir-ogre.git

#create the virtual environment
uv venv 
uv pip install ./dfir-ogre

# Activate the virtual environment
source .venv/bin/activate
```

The prompt should now show the venv name, e.g. `(dfir-ogre) $`.

and the `dfir-ogre` command should be available
```bash
dfir-ogre --help 
```

## Usage example

Extract a DFIR-ORC archive from its Outcome.json file, using the ogre.yaml configuration.

```bash
dfir-ogre orc \
    --archive ORC_xxx_Outcome.json \
    --case sample_case \
    --configuration dfir-ogre/configuration/ogre.yaml
```

### Run a single plugin

```bash
dfir-ogre plugin \
    --filename SRUDB.dat \
    --plugin_config ../dfir-ogre-plugin-windows/configuration/srum.xml \
    --computer_name HOST01 \
    --output_folder ./output \
    --output_type gzip \
    --compression_level 5 \
    --output_name '$computer_name-$parser-$file_name-$timestamp' \
    --dry_run
```

`--dry_run` validates output settings and prints a JSON plan without parsing the
artifact or creating output files. Remove that flag to parse. The plan lists
possible outputs from every XML mapping; missing SRUM providers, for example,
may leave some of those files unwritten.

Output types are `file` (default) and `gzip`. Formats are `jsonl` (default), `csv`,
`normalized_jsonl`, `normalized_csv`, and `analytics_jsonl`. The filename template
defaults to `$file_name`, the input filename without its final extension; it also
accepts `$computer_name`, `$parser`, and `$timestamp` (one UTC timestamp in
`YYYYMMDD_HHMMSS` form). Braced placeholders such as `${file_name}` work too.
Quote templates to prevent shell expansion. OGRE adds the data type and extension,
for example `HOST01-Srum-SRUDB-20261021_120000.srum_application_resources.jsonl.gz`.
Use `--output_folder` for directories; names cannot contain path separators.

Existing output files cause an error before parsing, including normalized
metadata and timeline companion files. The plugin command does not append to or
overwrite existing files. Use another directory or base name for a new run;
normalized metadata filenames are fixed, so those collisions need another directory.

`--output_date_format` accepts `iso` (default), `iso_utc`, `utc_naive`, or a custom
chrono strftime pattern. `--timeline_include_undated` retains entries with no
date; it requires `--timeline` and is incompatible with `analytics_jsonl`.

### Parse a folder of artifacts

Use `folder` for ordinary files collected from one computer, without a DFIR-ORC
archive or `Outcome.json`:

```bash
dfir-ogre folder \
    --folder /evidence/host-01 \
    --configuration my-ogre.yaml \
    --computer_name host-01 \
    --case sample_case
```

`--computer_name` is optional; it defaults to the input folder name. The folder
is scanned recursively without following symbolic links. Each
`archive_file_pattern` is matched, case-insensitively, against a path relative
to the folder using `/` separators. The regex controls the depth: for example,
`^logs/.*\.evtx$` selects EVTX files below `logs/`, while `^autoruns\.csv$`
selects only a root-level file.

For an unpacked ORC export, `folder` also discovers `GetThis.csv` indices
recursively and applies `original_file_pattern` to their `FullName` values.
Each `SampleName` is resolved relative to the directory containing its CSV;
both `/` and `\` separators are accepted. Original filenames, creation and
modification dates, and snapshot IDs are retained in output metadata,
including for files selected by `archive_file_pattern`. The source files
are read in place, without unpacking archives. Without a corresponding
CSV entry, a file is considered only by `archive_file_pattern`; its physical
path is not used as an original Windows path.

CSV filenames are matched case-insensitively and UTF-8 BOMs are supported.
Indices with missing columns, unsafe or unavailable sample paths, or
overlapping collections are reported as errors; other valid collections
can still be processed. Symbolic links and excluded output areas are not
used as sample targets. Repeated identical CSV rows are processed once;
distinct mapping rules still run independently.

In `orc` mode, `GetThis.csv` is likewise discovered at any depth within each
nested archive, with sample paths resolved relative to its directory.

Output definitions can use `$relative_path` in `output_folder` and
`base_file_name` for both `folder` and `orc`:

```yaml
output_folder: $output_folder/$computer_name/$relative_path
base_file_name: $relative_path/$file_name
```

For `logs/a.evtx`, `$relative_path` is `logs`: the output stays in a `logs/`
directory and its base filename becomes `logs_a`. For a file at the input root,
the variable is empty and the base filename remains `a`. Inside an ORC archive,
the path also includes a nested archive's name, such as `inner/logs`. Distinct
paths that flatten to the same base filename receive stable suffixes. Folder
reports include the source folder and run ID; source artifacts stay in place.

## French Cybersecurity Agency (ANSSI)
<img src="https://www.sgdsn.gouv.fr/files/styles/ds_image_paragraphe/public/files/Notre_Organisation/logo_anssi.png" alt="ANSSI logo" width="25%">
    
*This projet is managed by [ANSSI](https://cyber.gouv.fr/). To find out more, you can visit the [page](https://cyber.gouv.fr/enjeux-technologiques/open-source/) (in French) dedicated to ANSSI’s open-source strategy. You can also click on the badges above to learn more about their meaning.*
