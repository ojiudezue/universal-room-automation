"""Registry-not-names CI guard (card REGISTRY-NOT-NAMES-1; spec
``docs/planning/AUDIT_registry_not_names_sweep_2026_11_13.md`` §6 parts 1-3).

Operator rule (CLAUDE.md): never infer platform / NVR / device / person / room
from an entity-id string, suffix or slug. The engine
(``_registry_names_guard_engine``) is AST-only and imports no production
module. The real-tree scan is compared with
``quality/registry_not_names_allowlist.yaml`` as a RATCHET: a hit whose
``(file, qualname, rule)`` key is absent, or whose count exceeds
``max_count``, fails; a row that no longer hits, or hits fewer times than
``max_count``, also fails (lower or delete it), so the list only shrinks.

Parked, not enforced here: the ``counted-fallback`` counter-name check and
``migrate-by:`` expiry against board status (§6.2).

Detection limits (§6, last paragraph): strings built through ``str.format``,
``%``, ``+`` concatenation, ``"".join`` or a dict of lambdas are not seen;
dataflow is not followed (a suffix held in a local variable is missed unless it
is a module-level vocabulary constant); a vocabulary reached through an
attribute (``mod.SUFFIXES``) is not resolved. The raw real-tree total is a
floor, pinned below so a broken visitor cannot pass vacuously.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

import _registry_names_guard_engine as E

ALLOWLIST = Path(__file__).resolve().parents[1] / "registry_not_names_allowlist.yaml"
REASONS = {"own-entity", "ui-prefill", "counted-fallback", "pairing-resolver", "display"}
# Measured 2026-11-15 on develop 2fdf0a94: 209 raw hits over 118 keys.
RAW_HIT_FLOOR = 200

_REAL: dict | None = None
_ROWS: dict | None = None


def _real_tree() -> dict[str, str]:
    global _REAL
    if _REAL is None:
        _REAL = E.load_tree()
    return dict(_REAL)


def _rows() -> dict:
    global _ROWS
    if _ROWS is None:
        data = yaml.safe_load(ALLOWLIST.read_text())
        rows = {}
        for r in data["rows"]:
            key = (r["rule"], r["file"], r["qualname"])
            assert key not in rows, f"duplicate allowlist row {key}"
            rows[key] = r
        _ROWS = rows
    return _ROWS


def _rules(src: str) -> list[str]:
    return sorted(h.rule for h in E.scan_tree({"snippet.py": src}))


# ------------------------------------------------------------------ real tree
def test_real_tree_matches_allowlist_ratchet():
    problems = E.compare(E.scan_tree(_real_tree()), _rows())
    assert problems == [], "\n".join(problems)


def test_allowlist_rows_well_formed():
    for key, r in _rows().items():
        assert r["rule"] in E.RULES, key
        assert isinstance(r["max_count"], int) and r["max_count"] >= 1, key
        reason = r["reason"]
        assert reason in REASONS or (reason.startswith("migrate-by:") and len(reason) > 11), key
        assert r["owner"], key


def test_real_tree_raw_hit_floor_and_every_rule_fires():
    hits = E.scan_tree(_real_tree())
    assert len(hits) >= RAW_HIT_FLOOR, len(hits)
    fired = {h.rule for h in hits}
    assert fired == set(E.RULES), set(E.RULES) - fired


# ------------------------------------------------------- known-bad corpus (§5)
BAD = {
    # C1 transit_validator._count_platforms_fired
    "count_platforms": ('def f(entity_id):\n    if "_person_occupancy" in entity_id:\n        return "frigate"\n', ["N2_IN"]),
    # C1 perimeter_alert._leg_tag / zone legs `_zs.endswith("_2")`
    "leg_tag": ('def f(zs):\n    return "frigate2" if zs.endswith("_2") else "frigate"\n', ["N1_SUFFIX"]),
    # C1 camera_census `_person_detected` -> UNIFI
    "census_platform": ('def f(eid):\n    if eid.endswith(("_person_detected", "_person_occupancy")):\n        return 1\n', ["N1_SUFFIX"]),
    # C2 camera_census sibling probe
    "sibling_probe": ('def f(stem):\n    return f"binary_sensor.{stem}_person_detected"\n', ["N3_FSTR_ID"]),
    # C2 optimization `binary_sensor.{cam.split('.')[1]}_person_occupancy`
    "opt_split": ('def f(cam):\n    o = cam.split(".", 1)[1]\n    return o.replace("x", "")\n', ["N6_OBJID"]),
    # C2 _extract_camera_stem strips _N
    "stem_re": ('import re\ndef f(s):\n    return re.sub(r"_\\d+$", "", s)\n', ["N5_RE_SUFFIX"]),
    # C3 person_count fallback scan
    "person_count": ('def f(ents):\n    return [e for e in ents if e.endswith("_person_count")]\n', ["N1_SUFFIX"]),
    # C4 person_coordinator distance sensors by normalized name
    "bermuda_name": ('def f(name):\n    return name.lower().replace(" ", "_")\n', ["N4_SLUG"]),
    # C4 aggregation sensor.bermuda_{first}_
    "bermuda_prefix": ('def f(first):\n    return f"sensor.bermuda_{first}_"\n', ["N3_FSTR_ID"]),
    # C5 hvac_fans _read_room_occupied_state
    "room_occupied": ('def f(room):\n    return f"binary_sensor.{_slugify(room)}_occupied"\n', ["N3_FSTR_ID", "N4_SLUG"]),
    # C6 lock regime _person_for_sensor (split + endswith in one function)
    "lock_regime": ('def f(sensor_id, pid):\n    obj = pid.split(".", 1)[1]\n    return sensor_id.endswith(f"_{obj}_distance")\n', ["N6_OBJID"]),
    # C7 energy_circuits `"_2" in entity_id`
    "span_panel": ('def f(entity_id):\n    return "left" if "_2" in entity_id else "right"\n', ["N2_IN"]),
    # §6.1 vocabulary + helper indirection
    "vocab": ('_SUF = ("_person_detected", "_person_occupancy")\ndef f(e):\n    return _has_any_suffix(e, _SUF)\n',
              ["N7_VOCAB", "N7_VOCAB_USE"]),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_known_bad_snippet_is_flagged(name):
    src, expected = BAD[name]
    assert _rules(src) == sorted(expected)


def test_imported_vocabulary_is_followed_across_modules():
    tree = {
        "a.py": 'SUFFIXES = frozenset({"_person_detected", "_person_occupancy"})\n',
        "b.py": 'from .a import SUFFIXES\ndef g(e):\n    return e.endswith(SUFFIXES)\n',
    }
    keys = {h.key for h in E.scan_tree(tree)}
    assert ("N1_SUFFIX", "b.py", "g") in keys and ("N7_VOCAB", "a.py", "<module>") in keys


GOOD = {
    "domain_check": 'def f(eid):\n    return eid.split(".")[0] == "light"\n',
    "domain_startswith": 'def f(eid):\n    return eid.startswith("light.")\n',
    "own_domain_id": 'def f(x):\n    return f"sensor.{DOMAIN}_{x}"\n',
    "own_unique_id": 'def f(entry):\n    return f"{DOMAIN}_{entry.entry_id}_occupied"\n',
    "private_name": 'def f(n):\n    return n.startswith("_") or n.startswith("__")\n',
    "log_text": 'def f(x):\n    return f"Room {x}. done"\n',
    "objid_only": 'def f(eid):\n    return eid.split(".", 1)[1]\n',
    "lower_only": 'def f(s):\n    return s.lower().strip()\n',
    "single_suffix_tuple": '_ONE = ("_only",)\ndef f(e):\n    return g(e, _ONE)\n',
}


@pytest.mark.parametrize("name", sorted(GOOD))
def test_known_good_snippet_not_flagged(name):
    assert _rules(GOOD[name]) == []


# --------------------------------------------------------- in-memory drills
_DRILL = 'entity_id.endswith("_person_detected")'


def _insert_into(src: str, qualname: str) -> str:
    """Return ``src`` with one ``_DRILL`` statement prepended to the body of
    the def at ``qualname``."""
    tree = ast.parse(src)
    target = None
    for node, qual, _f in E._iter_scoped(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                ".".join(p for p in (qual, node.name) if p != "<module>") == qualname:
            target = node
            break
    assert target is not None, qualname
    first = target.body[0]
    lines = src.splitlines(keepends=True)
    pad = " " * first.col_offset
    lines.insert(first.lineno - 1, f"{pad}_drill = {_DRILL}\n")
    return "".join(lines)


def test_drill_new_guess_in_allowlisted_function_fails_ratchet():
    key = ("N1_SUFFIX", "perimeter_alert.py", "PerimeterAlertManager._is_frigate_person_entity")
    assert key in _rows()
    tree = _real_tree()
    tree[key[1]] = _insert_into(tree[key[1]], key[2])
    problems = E.compare(E.scan_tree(tree), _rows())
    assert len(problems) == 1 and problems[0].startswith("OVER ") and key[2] in problems[0], problems


def test_drill_new_guess_in_unlisted_function_fails_ratchet():
    rel, qual = "person_ids.py", None
    tree = _real_tree()
    listed = {(f, q) for (_r, f, q) in _rows()}
    for node, outer, _f in E._iter_scoped(ast.parse(tree[rel])):
        if isinstance(node, ast.FunctionDef):
            q = node.name if outer == "<module>" else f"{outer}.{node.name}"
            if (rel, q) not in listed:
                qual = q
                break
    assert qual is not None
    tree[rel] = _insert_into(tree[rel], qual)
    problems = E.compare(E.scan_tree(tree), _rows())
    assert problems == [f"NEW name guess ('N1_SUFFIX', '{rel}', '{qual}') x1: "
                        "resolve via the registry, or allowlist with a reason"], problems


def test_drill_removed_guess_flags_stale_row():
    rows = dict(_rows())
    fake = ("N1_SUFFIX", "person_ids.py", "no_such_function")
    rows[fake] = {"max_count": 1}
    problems = E.compare(E.scan_tree(_real_tree()), rows)
    assert problems == [f"STALE {fake}: no longer hits; delete the row"], problems


def test_drill_count_below_max_asks_to_lower():
    key = ("N1_SUFFIX", "perimeter_alert.py", "PerimeterAlertManager.async_setup._wire_camera")
    rows = dict(_rows())
    rows[key] = dict(rows[key], max_count=rows[key]["max_count"] + 1)
    problems = E.compare(E.scan_tree(_real_tree()), rows)
    assert len(problems) == 1 and problems[0].startswith("LOWER "), problems
