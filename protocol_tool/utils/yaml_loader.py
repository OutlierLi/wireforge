"""Safe YAML loading with include support."""

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file and return the parsed dict.

    Raises FileNotFoundError if the file doesn't exist.
    Raises yaml.YAMLError if the file is malformed.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        return {}
    return data


def load_yaml_multi(path: str | Path) -> list[dict[str, Any]]:
    """Load a YAML file that may contain multiple documents."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))
    return [d for d in docs if d is not None]


def glob_yaml(directory: str | Path, pattern: str = "**/*.yaml") -> list[Path]:
    """Find all YAML files matching a glob pattern under a directory."""
    directory = Path(directory)
    if not directory.exists():
        return []
    return sorted(directory.glob(pattern))


def load_yaml_dir(directory: str | Path, pattern: str = "**/*.yaml") -> list[dict[str, Any]]:
    """Load all YAML files matching a glob pattern under a directory.

    Returns a list of (relative_path, data) tuples.
    """
    results = []
    for filepath in glob_yaml(directory, pattern):
        data = load_yaml(filepath)
        if data:
            results.append(data)
    return results
