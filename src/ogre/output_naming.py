"""Output template helpers shared by folder and ORC inputs."""

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from dfir_ogre_common import OutputConfiguration


def expand_relative_path(template: str, relative_path: str, *, filename: bool) -> str:
    """Expand a logical parent path in one output field."""
    marker = "$relative_path"
    if marker not in template:
        return template

    if relative_path:
        rendered = template.replace(marker, relative_path.replace("\\", "/"))
    else:
        rendered = template
        while marker in rendered:
            position = rendered.index(marker)
            before = rendered[:position]
            after = rendered[position + len(marker) :]
            if after.startswith(("/", "\\", "_")):
                after = after[1:]
            elif before.endswith(("/", "\\", "_")):
                before = before[:-1]
            rendered = before + after

    if filename:
        return rendered.replace("/", "_").replace("\\", "_")
    return rendered


@dataclass
class _RegisteredOutput:
    output: OutputConfiguration
    source_key: str
    mapping_label: str
    output_name: str
    uses_relative_path: bool
    folder_key: str
    initial_name: str
    ordinal: int

    @property
    def pair(self) -> tuple[str, str]:
        return self.folder_key, self.initial_name


class OutputNameRegistry:
    """Disambiguate new relative-path output names across one planned run."""

    def __init__(self) -> None:
        self._entries: list[_RegisteredOutput] = []

    def register(
        self,
        output: OutputConfiguration,
        *,
        source_key: str,
        mapping_label: str,
        output_name: str,
        uses_relative_path: bool,
    ) -> None:
        self._entries.append(
            _RegisteredOutput(
                output,
                source_key,
                mapping_label,
                output_name,
                uses_relative_path,
                str(Path(output.output_folder).resolve(strict=False)),
                output.base_file_name,
                len(self._entries),
            )
        )

    def finalize(self) -> None:
        counts = Counter(entry.pair for entry in self._entries)
        reserved = set(counts)
        candidates = sorted(
            (
                entry
                for entry in self._entries
                if entry.uses_relative_path and counts[entry.pair] > 1
            ),
            key=lambda entry: (
                entry.source_key,
                entry.mapping_label,
                entry.output_name,
                entry.folder_key,
                entry.initial_name,
                entry.ordinal,
            ),
        )
        for entry in candidates:
            digest_input = "\0".join(
                (entry.source_key, entry.mapping_label, entry.output_name)
            )
            digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:10]
            stem = f"{entry.initial_name}__{digest}"
            name = stem
            number = 2
            while (entry.folder_key, name) in reserved:
                name = f"{stem}_{number}"
                number += 1
            entry.output.base_file_name = name
            reserved.add((entry.folder_key, name))
