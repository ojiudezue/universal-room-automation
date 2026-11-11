"""FORM-TEXT-PLAIN-PASS-1 (ships with FORM-CONDITIONAL-FIELDS-1 D3).

Acceptance criteria from docs/planning/AUDIT_form_text_plain_pass.md §4
(rev 2). Field sets come from the REAL rendered step schemas (both flows,
descending into sections), so a field that renders with no label — the
raw key in the UI — fails here.
"""
from __future__ import annotations

import re

import pytest

import _forms_harness as h

_RENDERED = h.render_all()
_STRINGS = h.load_strings()

# Fields with a label but deliberately no helper text. Empty today; add a
# (flow, step, key) with a comment if one is ever accepted.
_NO_HELP_ALLOWLIST: frozenset = frozenset()

# Dynamic keys built per entity / per zone at render time cannot carry a
# translation; the step's own option labels name them.
_DYNAMIC = re.compile(r"__|^radar_|^caps_kind")


def _cases():
    out = []
    for (flow, step), fields in sorted(_RENDERED.items()):
        for key, section in sorted(fields.items(), key=lambda kv: kv[0]):
            if _DYNAMIC.search(key):
                continue
            out.append((flow, step, section, key))
    return out


_CASES = _cases()


def test_render_covers_the_flows():
    assert len(_RENDERED) >= 70
    assert len(_CASES) >= 600


@pytest.mark.parametrize("rel", h.STRING_FILES)
def test_every_form_field_has_label(rel):
    blob = _STRINGS[rel]
    missing = []
    for flow, step, section, key in _CASES:
        label, _ = h.label_of(blob, flow, step, key, section)
        if not label or label == key:
            missing.append((flow, step, section, key))
    assert not missing, missing


@pytest.mark.parametrize("rel", h.STRING_FILES)
def test_every_form_field_has_description(rel):
    blob = _STRINGS[rel]
    missing = []
    for flow, step, section, key in _CASES:
        if (flow, step, key) in _NO_HELP_ALLOWLIST:
            continue
        label, desc = h.label_of(blob, flow, step, key, section)
        if label and not desc:
            missing.append((flow, step, section, key))
    assert not missing, missing


def test_strings_and_en_equal_for_every_step():
    """Value parity (keys AND values) for every config/options step."""
    s, e = _STRINGS["strings.json"], _STRINGS["translations/en.json"]
    for flow in ("config", "options"):
        assert s[flow]["step"] == e[flow]["step"], flow


# --- denylist ------------------------------------------------------------------

# (flow, step, key) rows the signed-off audit table rewrote.
_AUDITED = {
    ("options", "coordinator_presence", k) for k in (
        "sleep_start_hour", "sleep_end_hour", "guest_mode_persistence_seconds",
        "guest_mode_require_confidence", "lost_away_grace_min",
        "lost_away_sleep_exempt", "presence_anomaly_sensitivity",
        "fan_recheck_enabled", "fan_recheck_arm_delay_s", "fan_recheck_spindown_s",
        "fan_recheck_window_s", "fan_recheck_cooldown_s", "fan_recheck_max_per_hour",
        "fan_recheck_hvac_suppress_s", "fan_recheck_mmwave_history_ticks",
        "fan_recheck_family_scaling_enabled")
} | {
    (f, "devices", k) for f in ("config", "options") for k in (
        "room_fan_recheck_enabled", "fan_recheck_l2_allowed",
        "fan_recheck_trust_sensors_ok")
} | {
    ("options", "basic_setup", "room_guest_occupancy_threshold_min"),
    ("options", "basic_setup", "room_is_guest_room"),
    ("options", "camera_census", "main_entry_door"),
    ("options", "coordinator_safety", "safety_anomaly_sensitivity"),
    ("options", "coordinator_security", "security_anomaly_sensitivity"),
    ("options", "coordinator_music_following", "music_anomaly_sensitivity"),
    ("options", "coordinator_hvac_settings", "hvac_anomaly_sensitivity"),
    ("options", "coordinator_hvac_settings", "hvac_ac_night_start_hhmm"),
    ("options", "coordinator_hvac_settings", "hvac_arrester_immune_persons"),
    ("options", "coordinator_hvac_settings", "hvac_carrier_stale_require_blind_corroboration"),
    ("options", "coordinator_hvac_settings", "sleep_fan_on_temp_f"),
    ("options", "coordinator_hvac_settings", "hvac_cover_open_temp"),
    ("options", "coordinator_hvac_settings", "hvac_cover_entities"),
    ("options", "coordinator_notifications_volume", "stuck_sensor_exclusion_enabled"),
    ("options", "coordinator_notifications_volume", "nm_a1_tripped_breaker_route_nm"),
    ("options", "coordinator_notifications_volume", "stuck_signal_nm_enabled"),
    ("options", "coordinator_optimization", "optimizer_kill_switch"),
    ("options", "sensors", "sensor_capabilities_json"),
}
_BANNED_WORDS = ("hysteresis", "debounce", "provenance", "substrate", "tier",
                 "failsafe", "kill-switch", "kill switch", "master", "Mode-2")
_TICKET = re.compile(r"[A-Z]+-[A-Z0-9-]+-\d")
_TEXT_PASS_STEPS = {(f, s) for f, s, _ in _AUDITED}


@pytest.mark.parametrize("rel", h.STRING_FILES)
def test_form_text_denylist(rel):
    blob = _STRINGS[rel]
    bad = []
    for flow, step, key in sorted(_AUDITED):
        section = _RENDERED[(flow, step)].get(key)
        label, desc = h.label_of(blob, flow, step, key, section)
        assert label, (flow, step, key)
        for word in _BANNED_WORDS:
            for txt in (label, desc or ""):
                if re.search(r"\b" + re.escape(word) + r"\b", txt, re.I):
                    bad.append((step, key, word))
    # No ticket ids / engineering notes in any helper text of a step the
    # text pass touched.
    for flow, step in sorted(_TEXT_PASS_STEPS):
        st = blob[flow]["step"][step]
        blocks = [st] + [s for s in (st.get("sections") or {}).values() if isinstance(s, dict)]
        for b in blocks:
            for key, txt in (b.get("data_description") or {}).items():
                if _TICKET.search(txt) or re.search(r"\brung\b|Mode-2|kill-switch", txt):
                    bad.append((step, key, txt[:60]))
    assert not bad, bad


# --- discriminating old-claim pins (audit §4) ---------------------------------

def _desc(rel, flow, step, key):
    section = _RENDERED[(flow, step)].get(key)
    return h.label_of(_STRINGS[rel], flow, step, key, section)[1]


@pytest.mark.parametrize("rel", h.STRING_FILES)
def test_wrong_claims_are_gone(rel):
    pres = _STRINGS[rel]["options"]["step"]["coordinator_presence"]
    # P3: the field is removed and the step no longer claims geofence trackers.
    assert "geofence_entities" not in pres.get("data", {})
    assert "geofence" not in pres["description"].lower()
    assert "Settings → People" in pres["description"]
    # P4 / P5: neither knob turns on Guest mode.
    assert "enters Guest mode" not in _desc(rel, "options", "coordinator_presence",
                                            "guest_mode_persistence_seconds")
    assert "trigger Guest mode" not in _desc(rel, "options", "coordinator_presence",
                                             "guest_mode_require_confidence")
    assert "does not turn on Guest mode" in _desc(rel, "options", "coordinator_presence",
                                                  "guest_mode_require_confidence")
    # R4: the room threshold shows a visitor; Guest mode needs a day and a night.
    r4 = _desc(rel, "options", "basic_setup", "room_guest_occupancy_threshold_min")
    assert "Guest Mode is triggered" not in r4 and "a day and a night" in r4
    # R12: no arrival-estimate claim for a field with no reader.
    assert "arrival estimates" not in _desc(rel, "options", "camera_census", "main_entry_door")
    # C11: covers are added on top of the HVAC-zone rooms' covers.
    c11 = _desc(rel, "options", "coordinator_hvac_settings", "hvac_cover_entities")
    assert "auto-discovered" not in c11 and "Empty = use each room's covers" not in c11
    assert "on top of the covers in HVAC-zone rooms" in c11
    # P6: the grace is skipped once cameras and rooms read empty.
    assert "unless the cameras and every room have read empty" in _desc(
        rel, "options", "coordinator_presence", "lost_away_grace_min")


@pytest.mark.parametrize("rel", h.STRING_FILES)
def test_dead_strings_removed(rel):
    blob = _STRINGS[rel]
    assert "automation_behavior" not in blob["options"]["step"]       # Z6
    cb = blob["config"]["step"]["cover_behavior"]["data"]
    for k in ("close_time", "close_timing_mode", "entry_cover_action",
              "open_time_end", "open_time_start", "open_timing_mode"):  # Z5
        assert k not in cb, k
    sc = blob["config"]["step"]["sensors_confirm"]["data"]
    assert "mmwave_sensors" not in sc and "door_sensors" not in sc      # R6b / R13
    assert sc["presence_sensors"] == "Presence sensors"
    assert sc["door_sensor"] == "Door sensor"
