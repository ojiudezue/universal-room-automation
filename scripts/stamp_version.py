#!/usr/bin/env python3
"""Stamp version across all URA source files.

Reads VERSION from const.py and updates:
1. Header comments in all .py files (first 5 lines)
2. manifest.json version field
"""

import json
import re
import sys
from pathlib import Path

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "universal_room_automation"
CONST_FILE = COMPONENT_DIR / "const.py"
MANIFEST_FILE = COMPONENT_DIR / "manifest.json"

HEADER_PATTERN = re.compile(
    r"(# Universal Room Automation v)\d+\.\d+\.\d+(?:\.\d+)*"
)


def get_version() -> str:
    """Read VERSION from const.py."""
    for line in CONST_FILE.read_text().splitlines():
        match = re.search(r'VERSION.*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    print("ERROR: Could not find VERSION in const.py", file=sys.stderr)
    sys.exit(1)


def stamp_py_files(version: str) -> int:
    """Update header comment in .py files. Returns count of files updated."""
    updated = 0
    for py_file in sorted(COMPONENT_DIR.glob("*.py")):
        lines = py_file.read_text().splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines[:5]):
            new_line = HEADER_PATTERN.sub(rf"\g<1>{version}", line)
            if new_line != line:
                lines[i] = new_line
                changed = True
        if changed:
            py_file.write_text("".join(lines))
            print(f"  Updated: {py_file.name}")
            updated += 1
    return updated


def stamp_manifest(version: str) -> None:
    """Update manifest.json version field."""
    data = json.loads(MANIFEST_FILE.read_text())
    old = data.get("version")
    if old != version:
        data["version"] = version
        MANIFEST_FILE.write_text(json.dumps(data, indent=2) + "\n")
        print(f"  Updated: manifest.json ({old} -> {version})")
    else:
        print(f"  manifest.json already at {version}")


def main() -> None:
    version = get_version()
    print(f"Stamping version {version}")
    print()

    print("Python files:")
    count = stamp_py_files(version)
    if count == 0:
        print("  (no headers to update)")
    print()

    print("Manifest:")
    stamp_manifest(version)
    print()
    print("Done.")


if __name__ == "__main__":
    main()
