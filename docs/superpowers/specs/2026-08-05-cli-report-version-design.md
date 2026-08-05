# CLI Run Report Version Design

## Goal

Include the installed `dfir-ogre` package version in every archive run report produced by the CLI, allowing investigators to identify which release generated a report.

## Report schema

Add an `ogre_version` string to the top level of `ArchiveReport`. A normal installed CLI run will serialize a value such as:

```json
{
  "ogre_version": "2.0.0b2"
}
```

The value is the installed distribution's canonical PEP 440 representation,
which may normalize the spelling used in `pyproject.toml` (for example,
`2.0.0-beta2` becomes `2.0.0b2`).

The remaining report fields and their behavior are unchanged.

## Version source and data flow

Resolve the version through `importlib.metadata.version("dfir-ogre")`, which reads the installed distribution metadata generated from the project configuration at build or installation time and returns its canonical version string. Keep the lookup in the report-building layer so all callers of the shared archive pipeline receive the same field without additional CLI argument plumbing.

`ReportBuilder.get_report()` will populate `ArchiveReport.ogre_version`. The existing dataclass JSON encoder will then include it automatically in the JSON written by `archive_runner.parse_archive()`.

Because both the `orc` and `timeline` CLI commands use `parse_archive()`, both report types gain the field. The `plugin` command is unchanged because it does not produce an archive run report.

## Error handling

If the distribution metadata is unavailable, report generation must continue and set `ogre_version` to `"unknown"`. This supports direct execution from an uninstalled source checkout without weakening normal installed-package behavior.

## Testing

Add focused tests that verify:

- `ReportBuilder` places the resolved package version on `ArchiveReport`.
- JSON serialization includes a top-level `ogre_version` field.
- The archive report written to disk includes the field.
- Missing distribution metadata produces `"unknown"` rather than preventing report creation.

No configuration or command-line changes are required.
