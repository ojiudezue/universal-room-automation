"""NM Cycle A A7 — preserved-signal regression fixture.

Cycle A demotes / dedups / gates a set of NOISE classes. This test locks
in that the SIGNAL classes still emit at their prior severity — a change
in this file's assertions is a review-required deliberate change to a
household-hazard notification.

Signals under regression contract:
  1. Water leak (safety.py binary WATER_LEAK) — Hazard emits at severity
     from binary_hazard classification.
  2. Envoy write-verify CRITICAL — energy_write_verify.py fires
     `_send_nm_alert` with severity="critical" on write-verify failure.
  3. AC Reset FAILED — hvac_override.py fires `_send_nm_alert` with
     severity="critical" after 2 retries can't restore mode.
  4. Envoy Offline — energy.py fires `_send_nm_alert` with severity="high"
     after 3 consecutive missed cycles.

Two-tier approach:
  - Source-anchored regression (this file): asserts the exact `severity=`
    literal at each emit call site is unchanged. Cheap; catches a stray
    edit demoting a real hazard.
  - Behavioral emit path (`test_notification_manager.py` and family):
    exercises `nm.async_notify` end-to-end. Cycle A's Cycle-B safe-word
    fixture will layer per-severity behavior on top; this file's job is
    the demotion tripwire.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CC = REPO_ROOT / "custom_components" / "universal_room_automation" / "domain_coordinators"


def _read(name: str) -> str:
    return (CC / name).read_text(encoding="utf-8")


def test_ac_reset_failed_still_critical():
    """hvac_override.py: `AC Reset FAILED` alert must remain severity=critical."""
    src = _read("hvac_override.py")
    # Locate the AC Reset FAILED alert block; assert the severity literal
    # inside it is "critical". Any change downgrading this is a real
    # household hazard — bug class QC #21 (Severity demotion under refactor).
    m = re.search(
        r'title=f?"AC Reset FAILED[^"]*"[\s\S]{0,600}?severity="([a-z]+)"',
        src,
    )
    assert m is not None, "AC Reset FAILED emit block not found in hvac_override.py"
    assert m.group(1) == "critical", (
        f"AC Reset FAILED severity drifted: expected 'critical', got '{m.group(1)}'"
    )


def test_envoy_offline_still_high():
    """energy.py: `Envoy Offline` alert must remain severity=high."""
    src = _read("energy.py")
    m = re.search(
        r'title="Envoy Offline"[\s\S]{0,600}?severity="([a-z]+)"',
        src,
    )
    assert m is not None, "Envoy Offline emit block not found in energy.py"
    assert m.group(1) == "high", (
        f"Envoy Offline severity drifted: expected 'high', got '{m.group(1)}'"
    )


def test_envoy_write_verify_critical_site_present():
    """energy_write_verify.py: NM alert bridge must still exist.

    Write-verify emits vary by failure class; the invariant is that at
    least one call to `_send_nm_alert` with severity="critical" is
    reachable from write-verify. Cycle A does not touch this path.
    """
    src = _read("energy_write_verify.py")
    # There must be a live send-bridge and a critical severity in the file.
    assert "_send_nm_alert" in src, (
        "energy_write_verify.py lost its NM alert bridge"
    )
    assert re.search(r'severity\s*=\s*"critical"', src) or \
        re.search(r"Severity\.CRITICAL", src), (
        "energy_write_verify.py no longer references a CRITICAL emit"
    )


def test_water_leak_binary_still_maps_to_water_leak_hazard():
    """safety.py: water_leak sensor must still map to HazardType.WATER_LEAK.

    Cycle A A4 outdoor exclusion touches `_handle_humidity` only, not the
    binary WATER_LEAK path. This test locks in that room- and global-config
    water_leak sensors continue to enroll in `_binary_sensors` under the
    WATER_LEAK hazard type (severity emerges from binary classification
    downstream — the mapping is the invariant).
    """
    src = _read("safety.py")
    assert re.search(
        r"CONF_WATER_LEAK_SENSOR[\s\S]{0,400}?"
        r"_binary_sensors\[leak_id\]\s*=\s*HazardType\.WATER_LEAK",
        src,
    ), "Room-config water_leak → WATER_LEAK mapping broken"
    assert re.search(
        r"CONF_GLOBAL_LEAK_SENSORS:\s*\(HazardType\.WATER_LEAK",
        src,
    ), "Global-config water_leak → WATER_LEAK mapping broken"


def test_a5_blocklist_does_not_capture_signal_entities():
    """A5 discovery blocklist must not include any real-hazard sensor.

    Guards against a future edit adding a legitimate smoke/leak/CO sensor
    to the blocklist by mistake.
    """
    # Const import chain drags homeassistant — read the source directly.
    src = (REPO_ROOT / "custom_components" / "universal_room_automation" / "const.py").read_text()
    m = re.search(
        r"DEFAULT_SAFETY_DISCOVERY_BLOCKLIST\s*:\s*Final\s*=\s*\(([\s\S]*?)\)",
        src,
    )
    assert m is not None, "DEFAULT_SAFETY_DISCOVERY_BLOCKLIST tuple not found"
    entries = re.findall(r'"([^"]+)"', m.group(1))
    banned_substrings = ("_smoke", "_leak", "_water_leak", "_carbon_monoxide", "_co_")
    for eid in entries:
        for bad in banned_substrings:
            assert bad not in eid.lower(), (
                f"A5 blocklist contains a signal-shaped entity_id: {eid!r} "
                f"(matched {bad!r}). Review carefully — the blocklist is for "
                f"NON-signal noise, not real hazards."
            )


def test_a1_tripped_breaker_still_emits_anomaly_event():
    """A1 demotes NM route but preserves the AnomalyEvent emit.

    Dashboards / analytics still see tripped-breaker events; only the phone
    page is suppressed by default. This test guards against a future edit
    that also removes the AnomalyEvent (which would blind the anomaly
    dashboards to real trips).
    """
    src = _read("energy.py")
    # The _emit_circuit_anomaly_event call must still fire for the anomaly loop.
    assert "_emit_circuit_anomaly_event(anomaly)" in src, (
        "A1: anomaly-event emit for tripped_breaker was removed alongside "
        "the NM demote — this leaves no signal for the anomaly dashboards."
    )
