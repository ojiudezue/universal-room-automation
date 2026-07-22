#!/usr/bin/env python3
"""Deploy-time entity-registry rename script for NM entities.

NM Cycle C-2 (2026-07-22, D3) — see AUDIT_nm_rename_impact.md for the
verdict that this must be a deploy-time script rather than a code-side
change. This script is NOT wired into scripts/deploy.sh.

Usage — from the HA host, dry-run BY DEFAULT:

    ssh ha "python3 -" < scripts/rename_nm_entities.py           # dry-run
    ssh ha "python3 -" < scripts/rename_nm_entities.py --apply   # write

Idempotent: re-running does nothing if entity_ids are already canonical.
The script prints a rename plan first, requires interactive confirmation
before applying, and writes an audit log to
`/config/nm_rename_audit_<timestamp>.log` so the operator can trace what
was changed.

CAUTION: renaming an entity_id changes the recorder time-series key.
Dashboards / automations / blueprints / the URA-PWA that reference the
OLD entity_id will break silently until patched. Coordinate the
dashboard patches BEFORE running this with --apply.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys

# Canonical prefix map. If a live entity_id starts with the LHS but not
# the RHS, propose renaming its suffix onto the RHS.
_CANONICAL_PREFIXES: dict[str, str] = {
    # Row #7 in the audit — the umbrella sensor.
    "sensor.ura_notification_manager": "sensor.ura_nm_summary",
    # Add future non-conformant slugs here as they surface.
}

# Domain filter — only touch entities whose unique_id starts with these.
# Guards against a bug in the pattern accidentally matching a
# non-URA entity that happens to share a slug prefix.
_URA_UNIQUE_ID_PREFIX = "universal_room_automation_nm_"


def _load_registry(config_root: pathlib.Path) -> list[dict]:
    """Return the entity registry list from .storage/core.entity_registry."""
    reg_path = config_root / ".storage" / "core.entity_registry"
    if not reg_path.exists():
        raise SystemExit(
            f"entity registry not found at {reg_path}; is --config right?"
        )
    with reg_path.open() as fh:
        blob = json.load(fh)
    return blob["data"]["entities"]


def _plan(entities: list[dict]) -> list[tuple[str, str, str]]:
    """Return list of (unique_id, old_entity_id, new_entity_id) to rename."""
    plan: list[tuple[str, str, str]] = []
    for e in entities:
        uid = e.get("unique_id", "")
        old = e.get("entity_id", "")
        if not uid.startswith(_URA_UNIQUE_ID_PREFIX):
            continue
        # Exact-slug rename map.
        if old in _CANONICAL_PREFIXES:
            new = _CANONICAL_PREFIXES[old]
            if new != old:
                plan.append((uid, old, new))
    return plan


def _print_plan(plan: list[tuple[str, str, str]]) -> None:
    if not plan:
        print("No renames needed — registry is already canonical.")
        return
    print(f"Proposed renames ({len(plan)}):")
    for uid, old, new in plan:
        print(f"  {old:<50} -> {new}")


def _apply(config_root: pathlib.Path,
           plan: list[tuple[str, str, str]]) -> pathlib.Path:
    """Write the mutated registry back and emit an audit log."""
    reg_path = config_root / ".storage" / "core.entity_registry"
    with reg_path.open() as fh:
        blob = json.load(fh)
    old_by_uid = {(e.get("unique_id") or ""): e for e in blob["data"]["entities"]}
    audit_lines: list[str] = []
    for uid, old, new in plan:
        entry = old_by_uid.get(uid)
        if entry is None:
            audit_lines.append(f"SKIP  {uid}: no entry found")
            continue
        if entry.get("entity_id") != old:
            audit_lines.append(
                f"SKIP  {uid}: entity_id already changed "
                f"({entry.get('entity_id')})"
            )
            continue
        entry["entity_id"] = new
        audit_lines.append(f"OK    {uid}: {old} -> {new}")
    # Backup before write.
    backup = reg_path.with_suffix(
        f".backup_nm_rename_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    backup.write_text(reg_path.read_text())
    reg_path.write_text(json.dumps(blob, indent=2))
    # Audit log.
    audit_path = config_root / (
        f"nm_rename_audit_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    audit_path.write_text("\n".join(audit_lines) + "\n")
    return audit_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="/config",
                    help="HA config root (default: /config)")
    ap.add_argument("--apply", action="store_true",
                    help="Write changes to the registry. Default is dry-run.")
    args = ap.parse_args()
    root = pathlib.Path(args.config)
    entities = _load_registry(root)
    plan = _plan(entities)
    _print_plan(plan)
    if not plan:
        return 0
    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write changes.")
        print("REMINDER: restart HA after applying to pick up new entity_ids,")
        print("and patch dashboards / automations / PWA referencing the old ids.")
        return 0
    confirm = input("\nType 'RENAME' to proceed: ")
    if confirm.strip() != "RENAME":
        print("Aborted; no changes written.")
        return 1
    audit = _apply(root, plan)
    print(f"\nApplied. Audit log: {audit}")
    print("Restart Home Assistant to pick up the new entity_ids.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
