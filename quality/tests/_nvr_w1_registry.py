"""Live-shape registry for NVR-WITNESS W1 resolver tests.

Built from ``fixtures/nvr_w1_live_registry_shape.json`` (extracted read-only
from the live HA ``core.device_registry`` + ``core.entity_registry`` on
2026-11-13: every device that owns a ``camera.*`` entity or carries a camera
integration identifier, with its camera / person / face / count / switch /
event entities). Devices keep ``name``, ``name_by_user``, ``identifiers`` and
``connections`` exactly as the registry stores them.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

FIXTURE = Path(__file__).parent / "fixtures" / "nvr_w1_live_registry_shape.json"
GOLDEN = Path(__file__).parent / "fixtures" / "nvr_w1_resolver_golden_develop.json"
FAMILIES = ("person", "vehicle", "animal")


class _ER:
    def __init__(self, ents):
        self.entities = {e.entity_id: e for e in ents}

    def async_get(self, eid):
        return self.entities.get(eid)


class _DR:
    def __init__(self, devs):
        self.devices = {d.id: d for d in devs}

    def async_get(self, did):
        return self.devices.get(did)


def _dev(d: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=d["id"], name=d.get("name"), name_by_user=d.get("name_by_user"),
        identifiers={tuple(i) for i in (d.get("identifiers") or [])},
        connections={tuple(c) for c in (d.get("connections") or [])},
        area_id=None, model=d.get("model"),
    )


def _ent(e: dict) -> SimpleNamespace:
    eid = e["entity_id"]
    return SimpleNamespace(
        entity_id=eid, platform=e.get("platform"), device_id=e.get("device_id"),
        disabled_by=e.get("disabled_by"), unique_id=e.get("unique_id"),
        config_entry_id=e.get("config_entry_id"), domain=eid.split(".", 1)[0],
        area_id=None,
    )


def registries(mutate=None):
    """(entity_registry, device_registry). ``mutate(devs, ents)`` may edit the
    raw dict lists first (e.g. rename a device)."""
    fx = json.loads(FIXTURE.read_text())
    devs, ents = fx["devices"], fx["entities"]
    if mutate is not None:
        mutate(devs, ents)
    return _ER([_ent(e) for e in ents]), _DR([_dev(d) for d in devs])


def camera_entities(er) -> list[str]:
    return sorted(e.entity_id for e in er.entities.values()
                  if e.domain == "camera" and e.disabled_by is None)


def _fusion(f) -> dict:
    d = asdict(f)
    d.pop("discovered_at", None)  # wall-clock stamp, not resolver output
    return d


def snapshot(resolver_mod, er, dr) -> dict:
    """Every resolver surface the W1 callers consume, per enabled camera."""
    r = resolver_mod.CameraResolver(er, dr)
    out: dict = {}
    for cam in camera_entities(er):
        decl = r.resolve_operator_declaration([cam])
        fusions, reason, owner = r.resolve_pick_to_fusions(cam, lambda _e: None)
        legs = {}
        for fam in FAMILIES:
            try:
                legs[fam] = [asdict(x) for x in r.resolve_detection_legs(cam, fam)]
            except Exception as exc:  # noqa: BLE001
                legs[fam] = f"error:{type(exc).__name__}"
        out[cam] = {
            "decl": [{"key": resolver_mod.canonical_camera_key(f), **_fusion(f)} for f in decl],
            "pick": {"fusions": [_fusion(f) for f in fusions], "reason": reason, "owner": owner},
            "legs": legs,
        }
    return json.loads(json.dumps(out, sort_keys=True))
