"""Output template helpers shared by folder and ORC inputs."""


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
