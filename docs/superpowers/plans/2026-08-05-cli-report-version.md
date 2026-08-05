# CLI Run Report Version Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the installed `dfir-ogre` package version to every archive run report produced by the CLI.

**Architecture:** The report layer will resolve the installed distribution version through `importlib.metadata` and store it in a new top-level `ArchiveReport.ogre_version` field. The existing shared `parse_archive()` and dataclass encoder paths will propagate the field to reports written by both `orc` and `timeline`, while a narrow fallback keeps report generation working from an uninstalled source tree.

**Tech Stack:** Python 3.10+, standard-library `dataclasses`, `importlib.metadata`, `json`, and `unittest.mock`.

## Global Constraints

- The JSON key is exactly `ogre_version` and its value is a string.
- Resolve normal values with `importlib.metadata.version("dfir-ogre")`.
- Preserve the canonical PEP 440 value returned by installed metadata (for example, `2.0.0b2` for the project spelling `2.0.0-beta2`).
- If the `dfir-ogre` distribution metadata is unavailable, use exactly `"unknown"` and continue report generation.
- Apply the field to archive reports produced through the shared `orc` and `timeline` path.
- Do not add configuration or command-line options.
- Do not change the `plugin` command, which does not produce an archive run report.

---

### Task 1: Include distribution metadata in archive reports

**Files:**

- Modify: `src/ogre/reports.py:1-107`
- Test: `test/test_cli_hardening.py:1-479`

**Interfaces:**

- Consumes: `importlib.metadata.version("dfir-ogre") -> str` and `importlib.metadata.PackageNotFoundError`.
- Produces: private helper `_get_ogre_version() -> str` and public dataclass field `ArchiveReport.ogre_version: str`.
- Preserves: `ReportBuilder` constructor signature and `archive_runner.parse_archive()` signature.

- [ ] **Step 1: Write failing report and serialization tests**

Add `import importlib.metadata` near the top of `test/test_cli_hardening.py` so the fallback exception is explicit in the test.

Add these tests beside the existing `ReportBuilder` tests:

```python
def test_report_builder_includes_installed_ogre_version(self):
    builder = ReportBuilder(
        "2026-06-16T00:00:00+00:00",
        "dfir-ogre orc",
        "host1",
        "orc1",
        ".tmp/output",
    )

    with mock.patch(
        "ogre.reports.importlib.metadata.version",
        return_value="2.1.0",
    ) as package_version:
        report = builder.get_report()

    self.assertEqual(report.ogre_version, "2.1.0")
    package_version.assert_called_once_with("dfir-ogre")

def test_report_builder_uses_unknown_when_distribution_metadata_is_missing(self):
    builder = ReportBuilder(
        "2026-06-16T00:00:00+00:00",
        "dfir-ogre orc",
        "host1",
        "orc1",
        ".tmp/output",
    )

    with mock.patch(
        "ogre.reports.importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError,
    ):
        report = builder.get_report()

    self.assertEqual(report.ogre_version, "unknown")
```

Make the existing JSON encoder test deterministic by wrapping its `get_report()` call and asserting the new top-level key:

```python
with mock.patch(
    "ogre.reports.importlib.metadata.version",
    return_value="2.1.0",
):
    encoded = json.loads(json.dumps(builder.get_report(), cls=DataclassJSONEncoder))

self.assertEqual(encoded["ogre_version"], "2.1.0")
```

In `test_parse_archive_writes_report_and_cleans_tmp_folder`, wrap the existing call with the version patch:

```python
with mock.patch(
    "ogre.reports.importlib.metadata.version",
    return_value="2.1.0",
):
    with mock.patch("ogre.archive_runner.prepare_runs", return_value=prepared):
        with mock.patch(
            "ogre.archive_runner.multiprocessing.Manager",
            return_value=object(),
        ):
            with mock.patch(
                "ogre.archive_runner.run_parser_with_timeout",
                return_value=make_run_result(rows=6, time_s=1.0),
            ) as runner:
                report = archive_runner.parse_archive(
                    "config.yaml",
                    "archive.7z",
                    {"case": "case1"},
                    None,
                    "dfir-ogre orc",
                )

self.assertEqual(report.ogre_version, "2.1.0")
```

After loading `report_json` from disk, assert the serialized value:

```python
self.assertEqual(report_json["ogre_version"], "2.1.0")
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run python -m unittest \
  test.test_cli_hardening.TestCliHardening.test_report_builder_includes_installed_ogre_version \
  test.test_cli_hardening.TestCliHardening.test_report_builder_uses_unknown_when_distribution_metadata_is_missing \
  test.test_cli_hardening.TestCliHardening.test_dataclass_json_encoder_serializes_report_dataclasses \
  test.test_cli_hardening.TestCliHardening.test_parse_archive_writes_report_and_cleans_tmp_folder \
  -v
```

Expected: FAIL because `ogre.reports` does not yet expose the patched `importlib` module and `ArchiveReport` does not contain `ogre_version`.

- [ ] **Step 3: Implement the minimal metadata lookup and report field**

At the top of `src/ogre/reports.py`, import the standard-library module:

```python
import importlib.metadata
```

Add this focused helper below the logger:

```python
def _get_ogre_version() -> str:
    try:
        return importlib.metadata.version("dfir-ogre")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
```

Add the field to `ArchiveReport` immediately after `command_line`:

```python
ogre_version: str
```

Pass the resolved value in the matching position inside `ReportBuilder.get_report()`:

```python
return ArchiveReport(
    self.timestamp,
    self.command_line,
    _get_ogre_version(),
    self.computer,
    self.orc_id,
    self.output_folder,
    self.extract_errors,
    self.parsing_errors,
    summary,
    self.run_results,
)
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run the same four-test command from Step 2.

Expected: `Ran 4 tests` followed by `OK`.

- [ ] **Step 5: Run the complete regression suite**

Run:

```bash
uv run python -m unittest discover -v
```

Expected: all tests pass with `OK`.

- [ ] **Step 6: Commit the tested implementation**

```bash
git add src/ogre/reports.py test/test_cli_hardening.py
git commit -m "feat: include package version in run reports"
```
