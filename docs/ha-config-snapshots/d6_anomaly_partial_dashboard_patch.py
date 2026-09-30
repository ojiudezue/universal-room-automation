#!/usr/bin/env python3
"""D6 — `partial` off the anomalies lists, onto the Health "Coordinators" hero.

Cycle: HVAC-ANOMALY-BLIND-1 residual A (PLANNING_anomaly_detector_blind_metrics.md
§5 D6, REV 2.1 + operator rulings 2026-09-29). NOT applied by the builder — the
orchestrator applies it at deploy time, AFTER the code ships, following the
plan's 5-step procedure:

  1. Back up live `ura-v8` and `ura-v7` (ha_config_get_dashboard) verbatim to
     docs/ha-config-snapshots/lovelace_ura_v8_backup_<date>_pre_d6.json /
     ..._v7_..._pre_d6.json and COMMIT both before any write. Keep each read's
     `config_hash`.
  2. Write with `patch` / `python_transform` + that `config_hash`. NEVER
     `config=` (replaces the whole dashboard; would drop the 00:53 v8 cards).
  3. Cards are located BY CONTENT and asserted before any edit (the `test`
     ops below; the Python transform raises on any mismatch).
  4. The hero label is APPENDED to (the `mem …` + accuracy segments stay).
  5. Re-read both, run `verify` against the pre-D6 backups: the ONLY allowed
     differences are the v8 exclude entry, the v7 exclude entry and the v8
     hero `label`. Anything else → restore from backup (fresh hash) and stop.

Operator ruling 2026-09-29: the optional "also exclude `learning`" op is
DROPPED — `learning` stays visible on the anomalies list, because after this
cycle it only appears while a metric is genuinely collecting. D6 excludes
only `partial`.

UNVERIFIED (builder could not reach ha-mcp from the build sandbox): the exact
calling contract of `ha_config_set_dashboard`'s `python_transform` mode. The
pure functions below take and return the dashboard `config` dict; adapt the
wrapper to the tool's contract. The RFC 6902 op lists are provided for the
`patch` mode; their pointers were read from live storage on 2026-09-29 and
MUST be re-confirmed by the `test` ops (they fail closed if a card moved).

Offline self-check (read-only; runs the transforms in memory and verifies):
  python3 docs/ha-config-snapshots/d6_anomaly_partial_dashboard_patch.py \
      selftest <v8_config_or_storage.json> <v7_config_or_storage.json>
Post-write verification:
  python3 docs/ha-config-snapshots/d6_anomaly_partial_dashboard_patch.py \
      verify v8 <pre_d6_backup.json> <post_write.json>
  python3 docs/ha-config-snapshots/d6_anomaly_partial_dashboard_patch.py \
      verify v7 <pre_d6_backup.json> <post_write.json>
"""
from __future__ import annotations

import copy
import json
import sys

PARTIAL_EXCLUDE = {"state": "partial"}

V8_URL_PATH = "ura-v8"
V7_URL_PATH = "ura-v7"

# --- exact live content, read 2026-09-29 (lovelace.ura_v8 mtime 00:53) -------

V8_ANOMALIES_POINTER = "/views/6/sections/3/cards/1"
V8_ANOMALIES_EXCLUDE_BEFORE = [
    {"state": "nominal"},
    {"state": "normal"},
    {"state": "unavailable"},
    {"state": "unknown"},
    {"state": "none"},
]

V8_HERO_POINTER = "/views/6/sections/1/cards/0"
V8_HERO_ENTITY = "sensor.ura_coordinator_manager_coordinator_summary"
V8_HERO_LABEL_BEFORE = (
    "[[[ var b=states['sensor.ura_coordinator_manager_bayesian_prediction_accuracy']; "
    "var ba=(b && !isNaN(parseFloat(b.state))) ? ' · guess accuracy '"
    "+Math.round(parseFloat(b.state)*100)+'%' : ''; "
    "return 'mem '+(states['sensor.ura_coordinator_manager_memory_usage']||{}).state+ba; ]]]"
)
_OLD_RETURN = "return 'mem '+(states['sensor.ura_coordinator_manager_memory_usage']||{}).state+ba;"
# Declared before the return; the return keeps its expression and appends one
# segment. Plain words per the label style guide. Guards a null entity.
_PARTIAL_DECL = (
    "var s=(entity && entity.attributes && entity.attributes.status_per_coordinator)||{}; "
    "var p=Object.keys(s).filter(function(k){return (s[k]||{}).coverage==='partial';}); "
    "var partialSeg=p.length?' · partial: '+p.join(', '):''; "
)
_NEW_RETURN = (
    "return 'mem '+(states['sensor.ura_coordinator_manager_memory_usage']||{}).state"
    "+ba+partialSeg;"
)
V8_HERO_LABEL_AFTER = V8_HERO_LABEL_BEFORE.replace(
    _OLD_RETURN, _PARTIAL_DECL + _NEW_RETURN,
)

V7_TEMPLATE_POINTER = "/decluttering_templates/ura_anomaly_list/card"
V7_ANOMALIES_EXCLUDE_BEFORE = [
    {"state": "nominal"},
    {"state": "unavailable"},
    {"state": "unknown"},
]

# --- RFC 6902 op lists (for the `patch` mode) ------------------------------

V8_PATCH_OPS = [
    {"op": "test", "path": f"{V8_ANOMALIES_POINTER}/type", "value": "custom:auto-entities"},
    {"op": "test", "path": f"{V8_ANOMALIES_POINTER}/card/title", "value": "URA Anomalies"},
    {"op": "test", "path": f"{V8_ANOMALIES_POINTER}/filter/exclude",
     "value": V8_ANOMALIES_EXCLUDE_BEFORE},
    {"op": "add", "path": f"{V8_ANOMALIES_POINTER}/filter/exclude/-", "value": PARTIAL_EXCLUDE},
    {"op": "test", "path": f"{V8_HERO_POINTER}/type", "value": "custom:button-card"},
    {"op": "test", "path": f"{V8_HERO_POINTER}/name", "value": "Coordinators"},
    {"op": "test", "path": f"{V8_HERO_POINTER}/entity", "value": V8_HERO_ENTITY},
    {"op": "test", "path": f"{V8_HERO_POINTER}/label", "value": V8_HERO_LABEL_BEFORE},
    {"op": "replace", "path": f"{V8_HERO_POINTER}/label", "value": V8_HERO_LABEL_AFTER},
]

V7_PATCH_OPS = [
    {"op": "test", "path": f"{V7_TEMPLATE_POINTER}/type", "value": "custom:auto-entities"},
    {"op": "test", "path": f"{V7_TEMPLATE_POINTER}/filter/exclude",
     "value": V7_ANOMALIES_EXCLUDE_BEFORE},
    {"op": "add", "path": f"{V7_TEMPLATE_POINTER}/filter/exclude/-", "value": PARTIAL_EXCLUDE},
]


# --- content-located transforms (python_transform mode) --------------------

class D6Mismatch(RuntimeError):
    """Live content differs from what D6 was written against — stop."""


def _walk(node, path=""):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}/{i}")


def _only(matches, what):
    if len(matches) != 1:
        raise D6Mismatch(f"{what}: expected exactly 1 match, found {len(matches)}")
    return matches[0]


def _unwrap(doc):
    """Accept a raw `.storage` file, a {config: …} read result, or a config."""
    if isinstance(doc, dict) and "data" in doc and isinstance(doc["data"], dict) \
            and "config" in doc["data"]:
        return doc["data"]["config"]
    if isinstance(doc, dict) and "config" in doc and isinstance(doc["config"], dict) \
            and "views" in doc["config"]:
        return doc["config"]
    return doc


def transform_v8(config: dict) -> dict:
    cfg = copy.deepcopy(config)
    anomalies = _only(
        [n for _p, n in _walk(cfg)
         if n.get("type") == "custom:auto-entities"
         and isinstance(n.get("card"), dict) and n["card"].get("title") == "URA Anomalies"],
        "v8 'URA Anomalies' auto-entities card",
    )
    exclude = anomalies.get("filter", {}).get("exclude")
    if exclude != V8_ANOMALIES_EXCLUDE_BEFORE:
        raise D6Mismatch(f"v8 anomalies exclude changed: {exclude!r}")
    exclude.append(dict(PARTIAL_EXCLUDE))

    hero = _only(
        [n for _p, n in _walk(cfg)
         if n.get("type") == "custom:button-card" and n.get("name") == "Coordinators"
         and n.get("entity") == V8_HERO_ENTITY],
        "v8 'Coordinators' hero button-card",
    )
    if hero.get("label") != V8_HERO_LABEL_BEFORE:
        raise D6Mismatch(f"v8 hero label changed: {hero.get('label')!r}")
    if hero["label"].count(_OLD_RETURN) != 1:
        raise D6Mismatch("v8 hero label: return expression not found exactly once")
    hero["label"] = V8_HERO_LABEL_AFTER
    return cfg


def transform_v7(config: dict) -> dict:
    cfg = copy.deepcopy(config)
    tmpl = (cfg.get("decluttering_templates") or {}).get("ura_anomaly_list")
    if not isinstance(tmpl, dict) or not isinstance(tmpl.get("card"), dict):
        raise D6Mismatch("v7 decluttering template ura_anomaly_list/card missing")
    card = tmpl["card"]
    if card.get("type") != "custom:auto-entities":
        raise D6Mismatch(f"v7 template card type changed: {card.get('type')!r}")
    exclude = card.get("filter", {}).get("exclude")
    if exclude != V7_ANOMALIES_EXCLUDE_BEFORE:
        raise D6Mismatch(f"v7 anomalies exclude changed: {exclude!r}")
    exclude.append(dict(PARTIAL_EXCLUDE))
    return cfg


# --- semantic diff verifier (step 5) ----------------------------------------

def _diff(a, b, path=""):
    if type(a) is not type(b):
        return [path or "/"]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}/{k}")
            else:
                out.extend(_diff(a[k], b[k], f"{path}/{k}"))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            common = min(len(a), len(b))
            out = []
            for i in range(common):
                out.extend(_diff(a[i], b[i], f"{path}/{i}"))
            out.extend(f"{path}/{i}" for i in range(common, max(len(a), len(b))))
            return out
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_diff(x, y, f"{path}/{i}"))
        return out
    return [] if a == b else [path or "/"]


def _find_path(config, pred):
    return _only([p for p, n in _walk(config) if pred(n)], "locate")


def verify(which: str, before: dict, after: dict) -> list[str]:
    """Return the differing JSON pointers; raise D6Mismatch if any is not one
    of the allowed D6 changes or the changed values are not exactly D6's."""
    before, after = _unwrap(before), _unwrap(after)
    diffs = _diff(before, after)
    if which == "v8":
        anom = _find_path(before, lambda n: n.get("type") == "custom:auto-entities"
                          and isinstance(n.get("card"), dict)
                          and n["card"].get("title") == "URA Anomalies")
        hero = _find_path(before, lambda n: n.get("type") == "custom:button-card"
                          and n.get("name") == "Coordinators"
                          and n.get("entity") == V8_HERO_ENTITY)
        allowed = {f"{anom}/filter/exclude/{len(V8_ANOMALIES_EXCLUDE_BEFORE)}",
                   f"{hero}/label"}
        expected = transform_v8(before)
    elif which == "v7":
        allowed = {f"{V7_TEMPLATE_POINTER}/filter/exclude/{len(V7_ANOMALIES_EXCLUDE_BEFORE)}"}
        expected = transform_v7(before)
    else:
        raise ValueError(which)
    extra = [d for d in diffs if d not in allowed]
    missing = [a for a in allowed if a not in diffs]
    if extra or missing:
        raise D6Mismatch(f"{which}: unexpected diffs {extra}, missing {missing}")
    if _diff(expected, after):
        raise D6Mismatch(f"{which}: changed values differ from D6's: {_diff(expected, after)}")
    return diffs


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return _unwrap(json.load(fh))


def main(argv):
    if len(argv) >= 3 and argv[0] == "selftest":
        v8, v7 = _load(argv[1]), _load(argv[2])
        d8 = verify("v8", v8, transform_v8(v8))
        d7 = verify("v7", v7, transform_v7(v7))
        print("v8 diffs:", d8)
        print("v7 diffs:", d7)
        print(f"SELFTEST OK: {len(d8) + len(d7)} changes (expected 3)")
        return 0 if len(d8) + len(d7) == 3 else 1
    if len(argv) == 4 and argv[0] == "verify":
        diffs = verify(argv[1], _load(argv[2]), _load(argv[3]))
        print(f"VERIFY OK ({argv[1]}): {diffs}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
