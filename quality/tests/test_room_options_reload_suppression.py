"""Tests for ROOM-entry options-flow reload suppression.

Cycle: ROOM-CONFIG-SAVE-FULL-RELOAD-STALL-1 (Tier 2-DB).
Plan: docs/planning/PLANNING_room_config_reload_suppression.md
Scope: D0 (setup seeding + unload cleanup) + D1 (allowlist extension
       — LIVE HVAC vacancy-hold keys only) + D2 (log-once dedup).

Style: source-AST + light-mock, matching ``test_cm_reload_suppression.py``.
Behavioral drive of the full listener is deferred to live-validation
(README write-back) and the Tier 2-DB Reviewer C mutation drill; the
tests below anchor:

- **D0**: ``_seed_room_last_applied_options`` exists, is called from
  ROOM setup BEFORE ``entry.add_update_listener``, and unload pops the
  snapshot. Neutering the seed (source-mutation drill) MUST fail
  ``test_seed_room_last_applied_options_called_in_room_setup``.
- **D1**: ``_ROOM_SUPPRESS_KEYS`` includes the six proven-LIVE keys
  (comfort_temp_min/max, comfort_humidity_max, zone, fan_control_enabled,
  humidity_fan_control_enabled, hvac_vacancy_hold, hvac_vacancy_hold_night)
  and NOT the humidity-fan REFRESHED/EXCLUDED cluster.
- **D2**: OccupancySubstrate holds per-instance log-once sets for the
  two ``_discover_entity_map`` config-shape WARNs; both warning sites
  gate on those sets before logging.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC = (PKG / "__init__.py").read_text()
SUBSTRATE_SRC = (
    PKG / "domain_coordinators" / "occupancy_substrate.py"
).read_text()
CONST_SRC = (PKG / "const.py").read_text()


# ---------------------------------------------------------------------------
# D0 — setup seeding + unload cleanup
# ---------------------------------------------------------------------------


def test_seed_room_helper_defined():
    """The seed helper must exist as a top-level function."""
    assert re.search(
        r"^def _seed_room_last_applied_options\(",
        INIT_SRC, re.MULTILINE,
    ), "_seed_room_last_applied_options helper is missing"


def test_seed_room_helper_writes_to_room_last_applied_options():
    """Helper must write into hass.data[DOMAIN]['room_last_applied_options']."""
    m = re.search(
        r"def _seed_room_last_applied_options\(.*?\n(.*?)(?=\n\ndef |\nasync def )",
        INIT_SRC, re.DOTALL,
    )
    assert m, "helper body not found"
    body = m.group(1)
    assert '"room_last_applied_options"' in body
    assert "snapshots[entry.entry_id] = dict(entry.options)" in body


def test_seed_room_last_applied_options_called_in_room_setup():
    """The seed MUST be invoked in ROOM setup BEFORE add_update_listener.

    Source-mutation drill (Reviewer C): commenting out the
    ``_seed_room_last_applied_options(hass, entry)`` call MUST fail this
    test — proves the wire-up is load-bearing.
    """
    # Locate the ROOM setup wire-up region: everything after the CM
    # branch returns, up to the async_forward_entry_setups call.
    # Simpler discriminator: the specific seeding + listener registration
    # must appear in this exact order.
    seed_pat = r"_seed_room_last_applied_options\(hass, entry\)"
    listener_pat = (
        r"entry\.async_on_unload\(entry\.add_update_listener\("
        r"_async_update_listener\)\)"
    )
    seed_matches = [m.start() for m in re.finditer(seed_pat, INIT_SRC)]
    listener_matches = [m.start() for m in re.finditer(listener_pat, INIT_SRC)]
    assert seed_matches, "_seed_room_last_applied_options call missing"
    assert listener_matches, "add_update_listener registration missing"
    # At least one seed call must precede at least one listener
    # registration (the ROOM setup path).
    assert any(s < l for s in seed_matches for l in listener_matches), (
        "_seed_room_last_applied_options must be called BEFORE "
        "entry.add_update_listener registration in the ROOM setup path"
    )


def test_room_unload_pops_snapshot():
    """Unload must pop the room's snapshot to avoid stale ghosts."""
    assert re.search(
        r'"room_last_applied_options",\s*\{\},?\s*\)\s*\.pop\(entry\.entry_id,\s*None\)',
        INIT_SRC,
    ), (
        "async_unload_entry ROOM branch must pop entry_id from "
        "room_last_applied_options"
    )


# ---------------------------------------------------------------------------
# D1 — allowlist membership
# ---------------------------------------------------------------------------


def _extract_room_suppress_body() -> str:
    m = re.search(
        r"_ROOM_SUPPRESS_KEYS:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)",
        INIT_SRC, re.DOTALL,
    )
    assert m, "_ROOM_SUPPRESS_KEYS block not found"
    return m.group(1)


@pytest.mark.parametrize("alias", [
    "_CONF_COMFORT_TEMP_MIN",
    "_CONF_COMFORT_TEMP_MAX",
    "_CONF_COMFORT_HUMIDITY_MAX",
    "CONF_ZONE",
    "_CONF_FAN_CONTROL_ENABLED",
    "_CONF_HUMIDITY_FAN_CONTROL_ENABLED",
    # D1 additions (proven LIVE via _effective_hvac_hold_seconds call-
    # parameter path — plan §D1 CORRECTION).
    "_CONF_HVAC_VACANCY_HOLD",
    "_CONF_HVAC_VACANCY_HOLD_NIGHT",
])
def test_room_suppress_keys_contains(alias: str) -> None:
    body = _extract_room_suppress_body()
    assert alias in body, f"{alias} missing from _ROOM_SUPPRESS_KEYS"


@pytest.mark.parametrize("alias", [
    # EXCLUDED per honest D1 posture — cached / unaudited consumer sites.
    # A humidity-fan threshold value (min-over-sites = REFRESHED, coverage-
    # proof not shipped this cycle) MUST NOT sneak into the allowlist.
    "_CONF_HUMIDITY_FAN_THRESHOLD",
    "_CONF_TARGET_TEMP_HEAT",
    "_CONF_TARGET_TEMP_COOL",
    "_CONF_CLIMATE_ENTITY",
])
def test_room_suppress_keys_does_not_contain_excluded(alias: str) -> None:
    body = _extract_room_suppress_body()
    assert alias not in body, (
        f"{alias} MUST NOT be in _ROOM_SUPPRESS_KEYS — not audited "
        "LIVE this cycle (plan §D1 EXCLUDED-by-default)"
    )


def test_hvac_vacancy_hold_conf_strings_match_const_source():
    """Guard against a rename drift — the two D1-added CONFs must map
    to the same string values referenced by the LIVE consumer sites
    (binary_sensor.py:870-884, hvac_zones.py:553-594)."""
    def extract(name: str) -> str:
        m = re.search(
            rf"^{name}:\s*Final\s*=\s*\"([^\"]+)\"",
            CONST_SRC, re.MULTILINE,
        )
        assert m, f"{name} not found in const.py"
        return m.group(1)

    assert extract("CONF_HVAC_VACANCY_HOLD") == "hvac_vacancy_hold"
    assert extract("CONF_HVAC_VACANCY_HOLD_NIGHT") == "hvac_vacancy_hold_night"


# ---------------------------------------------------------------------------
# D2 — log-once dedup for occupancy_substrate WARNs
# ---------------------------------------------------------------------------


def test_substrate_defines_warn_dedup_sets():
    """OccupancySubstrate.__init__ must initialize both dedup sets."""
    assert "self._warned_multi_conf: set = set()" in SUBSTRATE_SRC
    assert "self._warned_cross_room: set = set()" in SUBSTRATE_SRC


def test_substrate_multi_conf_warn_gated_on_dedup_set():
    """The multi-CONF-lists WARN must be inside an
    ``if _dk not in self._warned_multi_conf:`` guard."""
    # Find the WARN call and its preceding guard.
    idx = SUBSTRATE_SRC.find(
        '"OccupancySubstrate: entity %s appears in "'
    )
    assert idx != -1, "multi-CONF WARN string not found"
    preceding = SUBSTRATE_SRC[max(0, idx - 400):idx]
    assert "if _dk not in self._warned_multi_conf:" in preceding, (
        "multi-CONF WARN must be gated by the _warned_multi_conf dedup set"
    )


def test_substrate_cross_room_warn_gated_on_dedup_set():
    """The cross-room-claim WARN must be inside an
    ``if _dk not in self._warned_cross_room:`` guard."""
    idx = SUBSTRATE_SRC.find(
        '"OccupancySubstrate: entity %s claimed by multiple "'
    )
    assert idx != -1, "cross-room WARN string not found"
    preceding = SUBSTRATE_SRC[max(0, idx - 400):idx]
    assert "if _dk not in self._warned_cross_room:" in preceding, (
        "cross-room WARN must be gated by the _warned_cross_room dedup set"
    )


# ---------------------------------------------------------------------------
# INV-B — substrate fast-path no-diff return is preserved
# ---------------------------------------------------------------------------


def test_substrate_no_diff_fast_path_preserved():
    """The suppressed path leans on the fast-path return at
    occupancy_substrate.py:~442 — any regression here would falsify INV-B."""
    assert re.search(
        r"if not added and not removed and not reclassified:",
        SUBSTRATE_SRC,
    ), "OccupancySubstrate no-diff fast-path guard is missing"
