"""Extract the names int the [project.optional-dependencies] section of a pyproject.toml file.

Provides for optional exclude list via --exclude=test doc.

Usage:
    python scripts/extract_dependencies.py  --exclude doc test
"""

import re
import argparse
from pathlib import Path


def extract_dependency_groups(toml_file_path, exclude=None):
    """Parsy pyproject.toml and return option dependency group names."""
    if exclude is None:
        exclude = []

    with open(toml_file_path, "r") as f:
        toml_content = f.read()

    # Find the optional-dependencies section
    match = re.search(r"\[project.optional-dependencies\](.*?)\n\n", toml_content, re.DOTALL)
    if not match:
        return []

    # Extract group names
    dependencies_section = match.group(1)
    group_names = re.findall(r"^\s*(\w+)\s*=", dependencies_section, re.MULTILINE)

    # Exclude specified groups
    return [group for group in group_names if group not in exclude]


def main():
    """Set and extract some default parameters from the command line."""
    default_toml_path = Path(__file__).parent.parent / "pyproject.toml"

    parser = argparse.ArgumentParser(description="Extract dependency group names from a pyproject.toml file.")
    parser.add_argument(
        "file",
        nargs="?",
        default=str(default_toml_path),
        help="Path to the pyproject.toml file (default: ../pyproject.toml).",
    )
    parser.add_argument(
        "--exclude", nargs="*", default=[], help="List of groups to exclude (e.g., --exclude doc test)."
    )
    args = parser.parse_args()

    groups = extract_dependency_groups(args.file, exclude=args.exclude)
    print(f"[{','.join(groups)}]")


if __name__ == "__main__":
    main()
