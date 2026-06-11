from __future__ import annotations

from collections.abc import Mapping

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def replace_placeholders(value: str, variables: Mapping[str, str | None]) -> str:
    result = value
    for name, replacement in variables.items():
        if replacement is not None:
            result = result.replace(f"${name}", replacement)
    return result


def apply_dir_tree(value: str, dir_tree: str | None, default_dir_tree: str) -> str:
    if dir_tree:
        return value.replace("$dir_tree", dir_tree)
    return value.replace("/$dir_tree", default_dir_tree)
