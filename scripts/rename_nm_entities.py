#!/usr/bin/env python3
"""Deploy-time entity-registry rename script for NM entities.

NM Cycle C-2 (2026-07-22, D3) — see AUDIT_nm_rename_impact.md. Rebuilt
in the C-2 fix-up (D-HIGH-1 / H-B1 / A1-A4 / L-B1) against the ACTUAL
live registry.

LIVE-REGISTRY REALITY (verified 2026-07-22 against
`/config/.storage/core.entity_registry`):

* There is NO umbrella `sensor.ura_notification_manager` entity — the
  original C-2 D3 script's exact-slug plan was a permanent no-op.
* All URA NM entities carry the *compound* prefix
  ``<domain>.ura_notification_manager_*`` where ``<domain>`` is one of
  ``sensor``, ``binary_sensor``, ``switch``, ``button``, ``number``.
* Their unique_ids DO NOT uniformly start with
  ``universal_room_automation_nm_`` — many carry the legacy
  ``universal_room_automation_notification_*`` prefix. The prior filter
  guaranteed a silent no-op even against real NM entities.

Rebuild: PREFIX-BASED rename. Any URA-platform entity whose
``entity_id`` starts with ``<domain>.ura_notification_manager_`` gets
its prefix shortened to ``<domain>.ura_nm_`` (readability parity with
other coordinator device-slugs). This is idempotent (re-running is a
no-op) and driven by the live registry, not a hand-authored slug map.

Usage — MUST be run from the HA host WITH HA STOPPED. Dry-run BY
DEFAULT:

    # 1. Stop HA first (e.g. `ha core stop` on OS installs).
    # 2. Run dry-run.
    python3 rename_nm_entities.py

    # 3. Re-run with --apply after reviewing the plan.
    python3 rename_nm_entities.py --apply

Guards:

* **STOP-HA-FIRST contract:** the script curls the HA API before
  applying and REFUSES to write while HA is reachable. Editing the
  entity registry live corrupts the in-memory copy on next write.
* **Target-collision guard:** if the new entity_id already exists in
  the registry (someone renamed manually), the script ABORTS and emits
  an audit line — never silently overwrites.
* **Backup file** written as
  ``<parent>/<name>.backup_nm_rename_<ts>`` (concatenated, NOT
  `Path.with_suffix` — the registry filename has no extension so
  `with_suffix` produces the wrong path).
* Interactive `RENAME` confirmation before write.

CAUTION: renaming an entity_id changes the recorder time-series key.
Dashboards / automations / blueprints / the URA-PWA that reference the
OLD entity_id will break silently until patched. Coordinate the
dashboard patches BEFORE running with --apply.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import socket
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen

# Prefix-based rename map (compound device-slug -> short slug).
# Comment matches code exactly: the LHS is a PREFIX (with trailing
# underscore), not an exact-slug candidate. We rename any entity_id
# beginning with `<domain>.<lhs>` to `<domain>.<rhs>` + the remaining
# suffix. Extend this map only after re-verifying against the live
# registry — see the module docstring.
_PREFIX_MAP: dict[str, str] = {
    "ura_notification_manager_": "ura_nm_",
}

# Domain filter — only touch entities owned by the URA integration.
_URA_PLATFORM = "universal_room_automation"

# HA API URL — used only for the STOP-HA-FIRST reachability check.
# Overridable via CLI in case the operator runs the script off-host.
_DEFAULT_HA_URL = "http://homeassistant.local:8123/"


def _load_registry(config_root: pathlib.Path) -> tuple[dict, list[dict]]:
    """Return (full_blob, entities_list) — full blob kept for round-trip write."""
    reg_path = config_root / ".storage" / "core.entity_registry"
    if not reg_path.exists():
        raise SystemExit(
            f"entity registry not found at {reg_path}; is --config right?"
        )
    with reg_path.open() as fh:
        blob = json.load(fh)
    return blob, blob["data"]["entities"]


def _new_entity_id(entity_id: str) -> str | None:
    """Return the new entity_id or None if no rename applies."""
    for domain_prefix, replacement in _PREFIX_MAP.items():
        # entity_id = "<domain>.<slug>"; the map keys are slug PREFIXES.
        try:
            dom, slug = entity_id.split(".", 1)
        except ValueError:
            return None
        if slug.startswith(domain_prefix):
            new_slug = replacement + slug[len(domain_prefix):]
            return f"{dom}.{new_slug}"
    return None


def _plan(
    entities: list[dict],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Return (rename_plan, collisions).

    plan: list of (unique_id, old_entity_id, new_entity_id).
    collisions: entity_ids that would collide with an existing entity —
    ABORT signal for --apply.
    """
    existing_ids = {e.get("entity_id") for e in entities}
    plan: list[tuple[str, str, str]] = []
    collisions: list[str] = []
    for e in entities:
        if e.get("platform") != _URA_PLATFORM:
            continue
        old = e.get("entity_id") or ""
        new = _new_entity_id(old)
        if new is None or new == old:
            continue
        if new in existing_ids:
            collisions.append(
                f"COLLISION {old} -> {new} (target already exists)"
            )
            continue
        plan.append((e.get("unique_id") or "", old, new))
    return plan, collisions


def _print_plan(
    plan: list[tuple[str, str, str]], collisions: list[str],
) -> None:
    if collisions:
        print("Target-entity_id collisions detected — script will refuse to apply:")
        for c in collisions:
            print(f"  {c}")
        print()
    if not plan:
        print("No renames needed — registry is already canonical.")
        return
    print(f"Proposed renames ({len(plan)}):")
    for _uid, old, new in plan:
        print(f"  {old:<70} -> {new}")


def _ha_reachable(base_url: str, timeout: float = 2.0) -> bool:
    """Return True iff HA appears to be up at `base_url` (any HTTP response)."""
    try:
        req = Request(base_url, method="GET")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            # Any HTTP response (200, 401, 403) means HA is answering.
            _ = resp.status
            return True
    except URLError:
        return False
    except (socket.timeout, ConnectionError, OSError):
        return False


def _apply(
    config_root: pathlib.Path,
    blob: dict,
    plan: list[tuple[str, str, str]],
) -> pathlib.Path:
    """Write the mutated registry back and emit an audit log."""
    reg_path = config_root / ".storage" / "core.entity_registry"
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
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    # Backup: concatenate name (registry filename has no extension so
    # `Path.with_suffix(".backup_...")` produces `.backup_...` next to
    # the file, which we happen to want — but the safer form is an
    # explicit sibling name so we don't depend on with_suffix semantics.
    backup = reg_path.parent / f"{reg_path.name}.backup_nm_rename_{ts}"
    backup.write_text(reg_path.read_text())
    reg_path.write_text(json.dumps(blob, indent=2))
    audit_path = config_root / f"nm_rename_audit_{ts}.log"
    audit_path.write_text("\n".join(audit_lines) + "\n")
    return audit_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="/config",
                    help="HA config root (default: /config)")
    ap.add_argument("--apply", action="store_true",
                    help="Write changes to the registry. Default is dry-run.")
    ap.add_argument("--ha-url", default=_DEFAULT_HA_URL,
                    help="HA base URL for the stop-first reachability check")
    ap.add_argument("--skip-ha-check", action="store_true",
                    help=(
                        "Skip the HA-reachability guard. ONLY use when the "
                        "check produces a false positive (e.g. running the "
                        "script from a host without name resolution)."
                    ))
    args = ap.parse_args()

    # Loud banner — the STOP-HA-FIRST contract is the highest-blast-
    # radius requirement here.
    print(
        "\n==========================================================\n"
        "  NM entity-registry rename (URA C-2 D3, fix-up rebuild)\n"
        "  STOP HOME ASSISTANT BEFORE APPLYING — editing the entity\n"
        "  registry while HA is live corrupts the in-memory copy on\n"
        "  next write.\n"
        "==========================================================\n"
    )

    root = pathlib.Path(args.config)
    blob, entities = _load_registry(root)
    plan, collisions = _plan(entities)
    _print_plan(plan, collisions)

    if collisions and args.apply:
        print("\nAborted: target-entity_id collisions found. Resolve manually.")
        return 2

    if not plan:
        return 0

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write changes.")
        print("REMINDER: restart HA after applying to pick up new entity_ids,")
        print("and patch dashboards / automations / PWA referencing the old ids.")
        return 0

    if not args.skip_ha_check and _ha_reachable(args.ha_url):
        print(
            f"\nRefused: Home Assistant is reachable at {args.ha_url}. Stop HA "
            "and re-run. Use --skip-ha-check ONLY if you know HA is stopped "
            "and the reachability probe is misleading."
        )
        return 3

    confirm = input("\nType 'RENAME' to proceed: ")
    if confirm.strip() != "RENAME":
        print("Aborted; no changes written.")
        return 1
    audit = _apply(root, blob, plan)
    print(f"\nApplied. Audit log: {audit}")
    print("Restart Home Assistant to pick up the new entity_ids.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
