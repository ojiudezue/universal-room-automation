"""PERIMETER-SWITCH-LABELS-AND-FLOW-PARITY-1 (2026-11-13).

- Device names per the operator's decided list; entity_ids / unique_ids pinned.
- AI Person Check select shows Off / Watch only / On (values unchanged).
- New options-flow step ``perimeter_alert_filters`` with all five settings,
  merge-saved so switch-written values survive.
- "Lower Single-Sourced Alerts" (switch AND flow field) exists only when a
  camera has both a Frigate and a Protect leg (registry-based resolver).

Drives the real switch/select/config_flow/camera_resolver code.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from _room_menu_helpers import StubEntry, make_hass, run
from _forms_harness import frontend_submit
from custom_components.universal_room_automation import config_flow as cf
from custom_components.universal_room_automation import perimeter_fp_gates as gates
from custom_components.universal_room_automation import select as sel
from custom_components.universal_room_automation import switch as sw
from custom_components.universal_room_automation.camera_resolver import CameraResolver
from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_INTEGRATION,
)

PKG = Path(__file__).resolve().parents[2] / "custom_components" / "universal_room_automation"

# Hand-written oracle (operator decided_names 2026-11-13).
EXPECTED_SWITCHES = {
    "switch.ura_perimeter_zone_agreement_demote": (
        "universal_room_automation_perimeter_zone_agreement_demote", "Lower Road Alerts"),
    "switch.ura_perimeter_single_source_demote": (
        "universal_room_automation_perimeter_single_source_demote",
        "Lower Single-Sourced Alerts"),
    "switch.ura_perimeter_egress_known_xcorr_gate": (
        "universal_room_automation_perimeter_egress_known_xcorr_gate",
        "Unknown Person Door Alert"),
    "switch.ura_perimeter_identity_followup": (
        "universal_room_automation_perimeter_identity_followup", "Add Names to Alerts"),
}
SINGLE = "perimeter_single_source_demote"
FIVE = [
    "perimeter_zone_agreement_demote", SINGLE,
    "perimeter_egress_known_xcorr_gate", "perimeter_identity_followup",
    "perimeter_vlm_gate",
]


def _integration_entry(options=None):
    return StubEntry(data={CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION},
                     options=dict(options or {}), entry_id="house1")


def _setup_switches(monkeypatch, dual: bool) -> dict:
    monkeypatch.setattr(gates, "dual_nvr_present", lambda hass: dual)
    added: list = []
    hass = make_hass()
    run(sw.async_setup_entry(hass, _integration_entry(), lambda ents, *a, **k: added.extend(ents)))
    return {e.entity_id: e for e in added if e.entity_id}


# --- switches ----------------------------------------------------------------

def test_two_nvr_install_creates_all_four_switches_with_decided_names(monkeypatch):
    ents = _setup_switches(monkeypatch, dual=True)
    for eid, (uid, name) in EXPECTED_SWITCHES.items():
        assert eid in ents, eid
        assert ents[eid].unique_id == uid
        assert ents[eid].name == name


def test_one_nvr_install_has_no_single_sourced_switch(monkeypatch):
    ents = _setup_switches(monkeypatch, dual=False)
    assert "switch.ura_perimeter_single_source_demote" not in ents
    # The other three still exist, unchanged.
    for eid in EXPECTED_SWITCHES:
        if eid != "switch.ura_perimeter_single_source_demote":
            assert eid in ents, eid


def test_switch_translation_names_match_decided_names():
    for fname in ("strings.json", "translations/en.json"):
        d = json.loads((PKG / fname).read_text())["entity"]["switch"]
        for eid, (_uid, name) in EXPECTED_SWITCHES.items():
            key = eid.split(".", 1)[1].removeprefix("ura_")
            assert d[key]["name"] == name, (fname, key)


# --- select ------------------------------------------------------------------

def test_ai_person_check_select_name_id_and_option_labels():
    s = sel.PerimeterVlmGateSelect(make_hass(), _integration_entry())
    assert s.entity_id == "select.ura_perimeter_vlm_gate"
    assert s.unique_id == "universal_room_automation_perimeter_vlm_gate"
    assert s.name == "AI Person Check"
    assert s.translation_key == "perimeter_vlm_gate"
    assert s.options == ["off", "shadow", "enforce"]
    labels = {"off": "Off", "shadow": "Watch only", "enforce": "On"}
    for fname in ("strings.json", "translations/en.json"):
        d = json.loads((PKG / fname).read_text())
        assert d["entity"]["select"]["perimeter_vlm_gate"]["state"] == labels
        assert d["selector"]["perimeter_vlm_gate"]["options"] == labels


# --- options flow -------------------------------------------------------------

def _flow(monkeypatch, options, dual: bool):
    monkeypatch.setattr(gates, "dual_nvr_present", lambda hass: dual)
    entry = _integration_entry(options)
    flow = cf.UniversalRoomAutomationOptionsFlow(entry)
    flow.hass = make_hass()
    flow.context = {"show_advanced_options": False}
    return flow, entry


def _keys(result) -> list:
    return [str(getattr(m, "schema", m)) for m in result["data_schema"].schema]


def test_menu_lists_perimeter_alert_filters_with_label(monkeypatch):
    flow, _ = _flow(monkeypatch, {}, True)
    menu = run(flow.async_step_init())["menu_options"]
    assert "perimeter_alert_filters" in menu
    for fname in ("strings.json", "translations/en.json"):
        d = json.loads((PKG / fname).read_text())["options"]
        assert d["step"]["init"]["menu_options"]["perimeter_alert_filters"]
        step = d["step"]["perimeter_alert_filters"]
        assert set(step["data"]) == set(FIVE)
        assert set(step["data_description"]) == set(FIVE)


def test_two_nvr_flow_shows_all_five_and_round_trips(monkeypatch):
    flow, entry = _flow(monkeypatch, {"unrelated": 7}, dual=True)
    form = run(flow.async_step_perimeter_alert_filters())
    assert form["step_id"] == "perimeter_alert_filters"
    assert _keys(form) == FIVE
    sub = frontend_submit(form["data_schema"])
    # Factory defaults (literal oracle, const.py 2026-11-13).
    assert sub == {
        "perimeter_zone_agreement_demote": False, SINGLE: False,
        "perimeter_egress_known_xcorr_gate": True,
        "perimeter_identity_followup": True, "perimeter_vlm_gate": "off",
    }
    sub.update({SINGLE: True, "perimeter_vlm_gate": "shadow"})
    out = run(flow.async_step_perimeter_alert_filters(sub))
    assert out["data"]["unrelated"] == 7
    assert out["data"][SINGLE] is True
    assert out["data"]["perimeter_vlm_gate"] == "shadow"


def test_flow_preserves_switch_written_values(monkeypatch):
    """A value the device switch wrote is the form default, and an untouched
    save keeps it (merge pattern)."""
    switch_written = {
        "perimeter_identity_followup": False,
        "perimeter_zone_agreement_demote": True,
        SINGLE: True,
        "perimeter_vlm_gate": "enforce",
        "face_recognition_enabled": False,
    }
    flow, _ = _flow(monkeypatch, switch_written, dual=True)
    form = run(flow.async_step_perimeter_alert_filters())
    out = run(flow.async_step_perimeter_alert_filters(frontend_submit(form["data_schema"])))
    for k, v in switch_written.items():
        assert out["data"][k] == v, k


def test_one_nvr_flow_hides_single_sourced_and_never_writes_it(monkeypatch):
    flow, _ = _flow(monkeypatch, {SINGLE: True}, dual=False)
    form = run(flow.async_step_perimeter_alert_filters())
    assert SINGLE not in _keys(form)
    assert len(_keys(form)) == 4
    # Even if a stale client submits it, the hidden key is not written.
    sub = {**frontend_submit(form["data_schema"]), SINGLE: False}
    out = run(flow.async_step_perimeter_alert_filters(sub))
    assert out["data"][SINGLE] is True  # stored value untouched, not overwritten


def test_invalid_stored_vlm_value_falls_back_to_off(monkeypatch):
    flow, _ = _flow(monkeypatch, {"perimeter_vlm_gate": "bogus"}, dual=True)
    form = run(flow.async_step_perimeter_alert_filters())
    assert frontend_submit(form["data_schema"])["perimeter_vlm_gate"] == "off"


def test_all_five_keys_are_reload_suppressed():
    from _forms_harness import real_ura
    K = real_ura().INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS
    for k in FIVE:
        assert k in K, k


# --- resolver: registry-based dual-NVR detection -----------------------------

@dataclass
class FakeEntity:
    entity_id: str
    device_id: str | None = None
    platform: str = ""
    name: str = ""
    disabled_by: Any = None
    area_id: str | None = None

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass
class FakeDevice:
    id: str
    identifiers: set = field(default_factory=set)
    connections: set = field(default_factory=set)
    area_id: str | None = None


class FakeER:
    def __init__(self, entities):
        self.entities = {e.entity_id: e for e in entities}

    def async_get(self, eid):
        return self.entities.get(eid)


class FakeDR:
    def __init__(self, devices):
        self.devices = {d.id: d for d in devices}

    def async_get(self, did):
        return self.devices.get(did)


def _protect(stem="cam_x", did="dev_pr"):
    return ([FakeDevice(id=did, identifiers={("unifiprotect", f"pr-{stem}")})],
            [FakeEntity(f"camera.{stem}_high_resolution_channel", did, "unifiprotect"),
             FakeEntity(f"binary_sensor.{stem}_person_detected", did, "unifiprotect")])


def _frigate(stem="cam_x", did="dev_f"):
    return ([FakeDevice(id=did, identifiers={("frigate", f"host1:{stem}")})],
            [FakeEntity(f"camera.{stem}", did, "frigate"),
             FakeEntity(f"binary_sensor.{stem}_person_occupancy", did, "frigate")])


def _registries(*parts):
    devs, ents = [], []
    for d, e in parts:
        devs += d
        ents += e
    return FakeER(ents), FakeDR(devs)


def test_resolver_true_when_one_camera_has_frigate_and_protect():
    er, dr = _registries(_protect(), _frigate())
    assert CameraResolver(er, dr).has_frigate_and_protect_camera() is True


def test_resolver_false_for_protect_only_install():
    er, dr = _registries(_protect())
    assert CameraResolver(er, dr).has_frigate_and_protect_camera() is False


def test_resolver_false_for_frigate_only_install():
    er, dr = _registries(_frigate())
    assert CameraResolver(er, dr).has_frigate_and_protect_camera() is False


def test_resolver_false_when_the_two_systems_watch_different_cameras():
    er, dr = _registries(_protect("front_yard"), _frigate("back_alley"))
    assert CameraResolver(er, dr).has_frigate_and_protect_camera() is False


def test_dual_nvr_present_reads_the_ha_registries(monkeypatch):
    from homeassistant.helpers import device_registry, entity_registry
    er, dr = _registries(_protect(), _frigate())
    monkeypatch.setattr(entity_registry, "async_get", lambda hass: er)
    monkeypatch.setattr(device_registry, "async_get", lambda hass: dr)
    assert gates.dual_nvr_present(MagicMock()) is True
    er1, dr1 = _registries(_protect())
    monkeypatch.setattr(entity_registry, "async_get", lambda hass: er1)
    monkeypatch.setattr(device_registry, "async_get", lambda hass: dr1)
    assert gates.dual_nvr_present(MagicMock()) is False


def test_dual_nvr_present_false_on_registry_error(monkeypatch):
    from homeassistant.helpers import entity_registry

    def _boom(hass):
        raise RuntimeError("no registry")
    monkeypatch.setattr(entity_registry, "async_get", _boom)
    assert gates.dual_nvr_present(MagicMock()) is False
