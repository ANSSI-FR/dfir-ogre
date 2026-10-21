"""Resolve and check single-plugin output settings without creating files."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dfir_ogre_common import OutputConfiguration


OUTPUT_FORMATS = (
    "jsonl",
    "csv",
    "normalized_jsonl",
    "normalized_csv",
    "analytics_jsonl",
)
_PLACEHOLDER = re.compile(
    r"\$\{(?P<braced>[^{}]*)\}|"
    r"\$(?P<bare>computer_name|file_name|parser|timestamp)(?![A-Za-z0-9])|"
    r"(?P<escaped>\$\$)|(?P<invalid>\$)"
)
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _check_filename(name: str) -> None:
    if (
        not name
        or name in (".", "..")
        or name.endswith((".", " "))
        or _INVALID_FILENAME.search(name)
    ):
        raise ValueError(f"Invalid output filename: {name!r}")


def _render_name(template: str, variables: dict[str, str]) -> str:
    def replace(match: re.Match) -> str:
        if match["escaped"]:
            return "$"
        name = match["braced"] or match["bare"]
        if match["invalid"] or name not in variables:
            raise ValueError(
                f"Unknown or invalid output-name placeholder: {match.group()!r}"
            )
        return variables[name]

    name = _PLACEHOLDER.sub(replace, template)
    _check_filename(name)
    return name


@dataclass(frozen=True)
class PluginOutputPlan:
    output: OutputConfiguration
    files: tuple[Path, ...]

    def as_dict(self, parser: str, input_file: str) -> dict:
        output = self.output
        return {
            "parser": parser,
            "input_file": str(Path(input_file).resolve()),
            "output_folder": str(Path(output.output_folder).resolve()),
            "base_file_name": output.base_file_name,
            "output_type": output.output_type,
            "format": output.format,
            "date_format": output.date_format,
            "compression_level": int(output.params.get("compression_level", "5"))
            if output.output_type == "gzip"
            else None,
            "timeline": output.with_timeline,
            "timeline_include_undated": output.timeline_include_undated,
            "include_empty": output.include_empty,
            "files": [str(path.resolve()) for path in self.files],
        }


def plan_plugin_output(args, root, parser: str) -> PluginOutputPlan:
    if not Path(args.filename).is_file():
        raise ValueError(f"Input file does not exist or is not a file: {args.filename}")

    output_type = getattr(args, "output_type", "file")
    compression = getattr(args, "compression_level", None)
    undated = getattr(args, "timeline_include_undated", False)
    if compression is not None and output_type != "gzip":
        raise ValueError("--compression_level requires --output_type gzip")
    if undated and not args.timeline:
        raise ValueError("--timeline_include_undated requires --timeline")

    base_name = _render_name(
        getattr(args, "output_name", "$file_name"),
        {
            "file_name": Path(args.filename).stem,
            "computer_name": args.computer_name,
            "parser": parser,
            "timestamp": datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        },
    )
    output = OutputConfiguration(
        base_file_name=base_name,
        output_folder=args.output_folder,
        output_type=output_type,
        format=args.output_format or "jsonl",
        date_format=args.output_date_format or "iso",
        with_timeline=args.timeline,
        include_empty=args.include_empty,
        timeline_include_undated=undated,
        params={"compression_level": str(compression)}
        if compression is not None
        else {},
    )
    output.validate()

    data_types = [mapping.get("data_type", "") for mapping in root.findall("mapping")]
    if not data_types:
        raise ValueError("Plugin configuration requires at least one mapping")
    for name in data_types:
        _check_filename(name)
    if len(set(data_types)) != len(data_types):
        raise ValueError("Plugin configuration contains duplicate data types")

    extension = "csv" if output.format in ("csv", "normalized_csv") else "jsonl"
    if output_type == "gzip":
        extension += ".gz"
    folder = Path(output.output_folder)
    files = [folder / f"{base_name}.{name}.{extension}" for name in data_types]
    if output.format.startswith("normalized_") or output.format == "analytics_jsonl":
        files.append(folder / f"ogre_metadata.{extension}")
        if output.with_timeline:
            files.extend(
                folder / f"{base_name}.{name}.tl.{extension}" for name in data_types
            )
    if len(set(files)) != len(files):
        raise ValueError("Data and timeline output filenames collide")
    for path in (folder, *folder.parents):
        if (path.exists() or path.is_symlink()) and not path.is_dir():
            raise ValueError(f"Output folder is not a directory: {path}")
    for path in files:
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Output already exists: {path}")
    return PluginOutputPlan(output, tuple(files))
