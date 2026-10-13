"""EC-HOUSE-ENTITY-DEFAULTS-1 (Rev 5 + fix-up) — acceptance tests.

G1  no house-specific entity ids in code (only the pin table).
G2  role-keyed options; an operator edit reloads so it takes effect.
G3  this house is byte-identical (the one-shot pin + reload-safe write).

Runs against the REAL integration package (real HA from .venv-ha). Run this
file in its own pytest process (it imports the real
``custom_components.universal_room_automation`` package).
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import custom_components.universal_room_automation as ura
from custom_components.universal_room_automation.const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
)
from custom_components.universal_room_automation.domain_coordinators import (
    energy_const as ec_const,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PKG = _REPO_ROOT / "custom_components" / "universal_room_automation"
_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "phalanx_options_pre_migration.json"
)

# ---------------------------------------------------------------------------
# G1 — no house literal anywhere in the integration except the pin table.
# ---------------------------------------------------------------------------

# Hand-authored house tokens (this house's serials / device names). Oracle is
# independent of the production table.
_HOUSE_TOKENS = (
    "phalanxmadrone", "482348004678", "482543015950", "garagealeftfront",
    "2325624", "pentair_", "iq_battery_hacs", "iq_gateway_hacs",
    "solcast_pv_forecast", "garage_a_", "garage_b_", "switch.garage_a",
    "switch.garage_b", "span_panel_car_charger", "span_panel_garage_b",
    "span_panel_current_power", "mains_vue_3",
    "enphase_cloud_last_successful_update",
)


def _house_literals_outside_role_table() -> list[str]:
    hits: list[str] = []
    for path in sorted(_PKG.rglob("*.py")):
        tree = ast.parse(path.read_text())
        docstrings: set[int] = set()
        allowed: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(
                getattr(node.body[0], "value", None), ast.Constant,
            ):
                docstrings.add(id(node.body[0].value))
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if getattr(tgt, "id", None) == "EC_ROLE_KEY_DEFAULTS":
                    for sub in ast.walk(node.value):
                        allowed.add(id(sub))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and id(node) not in allowed
                and "." in node.value
                and " " not in node.value
                and any(t in node.value for t in _HOUSE_TOKENS)
            ):
                hits.append(f"{path.relative_to(_PKG)}:{node.lineno}: {node.value}")
    return hits


def test_default_literals_contain_no_house_entity_ids() -> None:
    hits = _house_literals_outside_role_table()
    assert hits == [], "house entity ids outside EC_ROLE_KEY_DEFAULTS:\n" + "\n".join(hits)


def test_former_defaults_are_empty() -> None:
    from custom_components.universal_room_automation.domain_coordinators import (
        energy_circuits, energy_pool,
    )
    for name in (
        "DEFAULT_STORAGE_MODE_ENTITY", "DEFAULT_RESERVE_SOC_ENTITY",
        "DEFAULT_GRID_ENABLED_ENTITY", "DEFAULT_CHARGE_FROM_GRID_ENTITY",
        "DEFAULT_SOLCAST_TODAY_ENTITY", "DEFAULT_SOLCAST_TOMORROW_ENTITY",
        "DEFAULT_SOLCAST_REMAINING_ENTITY", "DEFAULT_SOLCAST_PEAK_ENTITY",
        "DEFAULT_SOLCAST_PEAK_TIME_ENTITY", "DEFAULT_SOLCAST_DAY_3_ENTITY",
        "DEFAULT_WEATHER_ENTITY", "DEFAULT_EVSE_GARAGE_A_POWER_ENTITY",
        "DEFAULT_EVSE_GARAGE_B_POWER_ENTITY", "DEFAULT_CLOUD_RESERVE_ORACLE_ENTITY",
        "DEFAULT_CLOUD_CHARGE_FROM_GRID_ORACLE_ENTITY",
        "DEFAULT_CLOUD_STORAGE_MODE_ORACLE_ENTITY",
        "DEFAULT_CLOUD_BATTERY_SOC_FALLBACK_ENTITY",
        "DEFAULT_CLOUD_LAST_SUCCESS_ENTITY", "DEFAULT_SOLAR_FOLLOW_GRID_ENTITY",
        "DEFAULT_SOLAR_FOLLOW_GRID_FALLBACK_ENTITY",
    ):
        assert getattr(ec_const, name) is None, name
    assert ec_const.DEFAULT_L1_CHARGER_ENTITIES == []
    assert energy_pool.DEFAULT_EVSE_ENTITIES == {}
    for name in (
        "DEFAULT_POOL_VSF_SPEED_ENTITY", "DEFAULT_SPA_VSF_SPEED_ENTITY",
        "DEFAULT_POOL_PUMP_POWER_ENTITY", "DEFAULT_POOL_INFINITY_EDGE_ENTITY",
        "DEFAULT_POOL_HEATER_ENTITY",
    ):
        assert getattr(energy_pool, name) is None, name
    assert energy_circuits.DEFAULT_GENERATOR_STATUS_ENTITY is None


# ---------------------------------------------------------------------------
# G3 — pin migration.
# ---------------------------------------------------------------------------


class _StubEntityRegistry:
    def __init__(self, present_ids: set[str]) -> None:
        self._present = set(present_ids)

    def async_get(self, entity_id):
        return SimpleNamespace(entity_id=entity_id) if entity_id in self._present else None


def _all_role_ids() -> set[str]:
    out: set[str] = set()
    for v in ec_const.EC_ROLE_KEY_DEFAULTS.values():
        out.update(v if isinstance(v, list) else [v])
    return out


def _cm_entry(options: dict) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="cm-test",
        title="URA: Coordinator Manager",
        data={CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER},
        options=dict(options),
    )


class _ConfigEntries:
    """hass.config_entries stand-in. ``eager_listener`` reproduces HA's
    eager-start update-listener scheduling (config_entries.py
    `_async_save_and_notify` -> `hass.async_create_task(..., eager_start=True)`):
    the listener runs synchronously inside async_update_entry."""

    def __init__(self, hass, eager_listener=None, entries=()) -> None:
        self._hass = hass
        self._eager_listener = eager_listener
        self.updates: list[dict] = []
        self.async_reload = MagicMock(name="async_reload")
        self._entries = list(entries) or [_parent_entry()]

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_update_entry(self, entry, *, options):
        entry.options = dict(options)
        self.updates.append(dict(options))
        if self._eager_listener is not None:
            _drive_eager(self._eager_listener(self._hass, entry))
        return True


def _parent_entry(master_on: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="parent-integ",
        data={CONF_ENTRY_TYPE: "integration", "domain_coordinators_enabled": master_on},
        options={},
    )


def _drive_eager(coro) -> None:
    try:
        coro.send(None)
    except StopIteration:
        return
    coro.close()
    raise AssertionError("listener suspended — eager drive incomplete")


def _hass_with_snapshot(entry_id: str | None, snapshot: dict | None):
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    if entry_id is not None:
        hass.data[DOMAIN]["cm_last_applied_options"] = {entry_id: dict(snapshot or {})}
    hass.async_create_task = MagicMock(
        side_effect=lambda coro, *a, **k: getattr(coro, "close", lambda: None)(),
    )
    return hass


def _pre_options() -> dict:
    return {
        k: v for k, v in json.loads(_FIXTURE_PATH.read_text()).items()
        if not k.startswith("_")
    }


@pytest.mark.asyncio
async def test_bootstrap_pins_phalanx_shape_options_byte_identical() -> None:
    """For every role key: post == live value if set, else the former default.
    Expected values are the literal pre-change resolution, hand-written."""
    pre = _pre_options()
    hass = _hass_with_snapshot(None, None)
    hass.config_entries = _ConfigEntries(hass)
    cm = _cm_entry(pre)
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(_all_role_ids()),
    ):
        assert await ura._bootstrap_pin_ec_defaults_once(hass, cm) is True
    post = cm.options
    # Hand-written oracle of what this house resolved BEFORE the change
    # (live option where set, otherwise the old code default).
    expected = {
        "energy_storage_mode_entity": "select.enpower_482348004678_storage_mode",
        "energy_reserve_soc_entity": "number.enpower_482348004678_reserve_battery_level",
        "energy_grid_enabled_entity": "switch.enpower_482348004678_grid_enabled",
        "energy_charge_from_grid_entity": "switch.enpower_482348004678_charge_from_grid",
        "energy_solcast_today_entity": "sensor.solcast_pv_forecast_forecast_today",
        "energy_solcast_tomorrow_entity": "sensor.solcast_pv_forecast_forecast_tomorrow",
        "energy_solcast_remaining_entity": "sensor.solcast_pv_forecast_forecast_remaining_today",
        "energy_solcast_day_3_entity": "sensor.solcast_pv_forecast_forecast_day_3",
        "energy_weather_entity": "weather.phalanxmadrone",
        "energy_evse_a_entity": "sensor.garage_a_power_minute_average",
        "energy_evse_b_entity": "sensor.garage_b_power_minute_average",
        "energy_l1_charger_entities": [
            "switch.smartplug_moes_wifi_garagealeftfront_socket_1",
            "switch.smartplug_moes_wifi_garagealeftfront_socket_2",
        ],
        "energy_cloud_reserve_oracle_entity": "number.iq_battery_hacs_battery_reserve",
        "energy_cloud_charge_from_grid_oracle_entity": "switch.iq_battery_hacs_charge_battery_from_grid",
        "energy_cloud_storage_mode_oracle_entity": "select.iq_gateway_hacs_system_profile",
        "energy_cloud_battery_soc_fallback_entity": "sensor.iq_battery_hacs_battery_overall_charge",
        "energy_solar_follow_grid_entity": "sensor.mains_vue_3_power_minute_average",
        "energy_solar_follow_grid_fallback_entity": "sensor.envoy_stream_grid_power",
        "energy_evse_a_switch_entity": "switch.garage_a",
        "energy_evse_a_energy_today_entity": "sensor.garage_a_energy_today",
        "energy_evse_a_energy_month_entity": "sensor.garage_a_energy_this_month",
        "energy_evse_a_span_breaker": "switch.span_panel_car_charger_breaker",
        "energy_evse_a_current_limit_entity": "number.garage_a_evse_emporia_wifi_garagea_current_limit",
        "energy_evse_b_switch_entity": "switch.garage_b",
        "energy_evse_b_energy_today_entity": "sensor.garage_b_energy_today",
        "energy_evse_b_energy_month_entity": "sensor.garage_b_energy_this_month",
        "energy_evse_b_span_breaker": "switch.span_panel_garage_b_evse_breaker",
        "energy_evse_b_current_limit_entity": "number.garage_b_evse_emporia_wifi_garageb_current_limit",
        "energy_dp_span_r1_entity": "sensor.span_panel_current_power",
        "energy_dp_span_r2_entity": "sensor.span_panel_current_power_2",
        "energy_cloud_last_success_entity": "sensor.enphase_cloud_last_successful_update",
        "energy_pool_speed_entity": "number.pentair_pool_variable_speed_pump_1_speed",
        "energy_pool_power_entity": "sensor.pentair_pool_variable_speed_pump_1_power",
        "energy_generator_entity": "sensor.generac_2325624_status_2",
    }
    assert set(expected) == set(ec_const.EC_ROLE_KEY_DEFAULTS)
    for k, v in expected.items():
        assert post[k] == v, k
    # Non-role keys untouched.
    assert post["energy_envoy_entity"] == pre["energy_envoy_entity"]
    assert post["_ec_defaults_pinned"] is True
    assert post["_ec_defaults_pinned_version"] == "ec-house-entity-defaults-1-rev5"


@pytest.mark.asyncio
async def test_bootstrap_skips_absent_from_registry() -> None:
    hass = _hass_with_snapshot(None, None)
    hass.config_entries = _ConfigEntries(hass)
    cm = _cm_entry({})
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(set()),
    ):
        assert await ura._bootstrap_pin_ec_defaults_once(hass, cm) is True
    for key in ec_const.EC_ROLE_KEY_DEFAULTS:
        assert key not in cm.options, key
    assert cm.options["_ec_defaults_pinned"] is True


@pytest.mark.asyncio
async def test_bootstrap_pins_only_registered_subset() -> None:
    hass = _hass_with_snapshot(None, None)
    hass.config_entries = _ConfigEntries(hass)
    cm = _cm_entry({})
    present = {"switch.garage_a", "switch.smartplug_moes_wifi_garagealeftfront_socket_3"}
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(present),
    ):
        await ura._bootstrap_pin_ec_defaults_once(hass, cm)
    pinned = {k: v for k, v in cm.options.items() if not k.startswith("_")}
    assert pinned == {
        "energy_evse_a_switch_entity": "switch.garage_a",
        "energy_l1_charger_entities": [
            "switch.smartplug_moes_wifi_garagealeftfront_socket_3",
        ],
    }


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent() -> None:
    hass = _hass_with_snapshot(None, None)
    hass.config_entries = _ConfigEntries(hass)
    cm = _cm_entry({"_ec_defaults_pinned": True})
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(_all_role_ids()),
    ):
        assert await ura._bootstrap_pin_ec_defaults_once(hass, cm) is False
    assert hass.config_entries.updates == []


# ---------------------------------------------------------------------------
# Reload behaviour (G2 + G3).
# ---------------------------------------------------------------------------


def test_role_keys_are_not_reload_suppressed_but_pin_flags_are() -> None:
    for key in ec_const.EC_ROLE_KEY_SET:
        assert key not in ura.OPTIONS_RELOAD_SUPPRESS_KEYS, key
    for flag in (
        ura.EC_DEFAULTS_PINNED_FLAG,
        ura.EC_DEFAULTS_PINNED_VERSION_FLAG,
        ura.EC_DEFAULTS_PINNED_AT_FLAG,
    ):
        assert flag in ura.OPTIONS_RELOAD_SUPPRESS_KEYS, flag
        assert flag in ura._NO_LIVE_ATTR_KEYS, flag


@pytest.mark.asyncio
async def test_pin_write_through_real_listener_does_not_reload_eager() -> None:
    """(a) The pin's write, seen by the REAL CM update listener running
    eagerly inside async_update_entry (HA semantics), must not reload."""
    pre = _pre_options()
    cm = _cm_entry(pre)
    hass = _hass_with_snapshot(cm.entry_id, pre)
    hass.config_entries = _ConfigEntries(hass, eager_listener=ura._async_update_listener)
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(_all_role_ids()),
    ):
        assert await ura._bootstrap_pin_ec_defaults_once(hass, cm) is True
    assert "energy_storage_mode_entity" in cm.options  # really pinned role keys
    hass.config_entries.async_reload.assert_not_called()
    assert hass.data[DOMAIN]["cm_last_applied_options"][cm.entry_id] == cm.options


@pytest.mark.asyncio
async def test_pin_write_through_real_listener_does_not_reload_deferred() -> None:
    """Same, with the listener run AFTER async_update_entry returns."""
    pre = _pre_options()
    cm = _cm_entry(pre)
    hass = _hass_with_snapshot(cm.entry_id, pre)
    hass.config_entries = _ConfigEntries(hass)
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(_all_role_ids()),
    ):
        await ura._bootstrap_pin_ec_defaults_once(hass, cm)
    await ura._async_update_listener(hass, cm)
    hass.config_entries.async_reload.assert_not_called()


async def _listen(before: dict, after: dict, *, master_on: bool = True, manager=None):
    """Run the REAL CM update listener for a save of ``after`` over a
    snapshot of ``before``; return the hass (async_reload is a mock)."""
    cm = _cm_entry(before)
    hass = _hass_with_snapshot(cm.entry_id, before)
    hass.config_entries = _ConfigEntries(
        hass, entries=[_parent_entry(master_on), cm],
    )
    if manager is not None:
        hass.data[DOMAIN]["coordinator_manager"] = manager
    cm.options = dict(after)
    await ura._async_update_listener(hass, cm)
    return hass


@pytest.mark.asyncio
async def test_role_key_change_schedules_exactly_one_parent_reload() -> None:
    """(a, part 1) one role-key change → ONE reload, of the PARENT entry
    (the EnergyCoordinator is built in the parent's setup; a CM reload
    would not pick the change up)."""
    before = _pre_options()
    hass = await _listen(
        before, {**before, "energy_evse_a_switch_entity": "switch.new_charger_a"},
    )
    hass.config_entries.async_reload.assert_called_once_with("parent-integ")


@pytest.mark.asyncio
async def test_legacy_entity_mapping_change_schedules_parent_reload() -> None:
    """Older construction-time mapping (solar sensor) behaves the same."""
    before = _pre_options()
    hass = await _listen(before, {**before, "energy_solar_entity": "sensor.new_solar"})
    hass.config_entries.async_reload.assert_called_once_with("parent-integ")


@pytest.mark.asyncio
async def test_role_key_change_with_master_off_does_not_reload() -> None:
    before = _pre_options()
    hass = await _listen(
        before, {**before, "energy_evse_a_switch_entity": "switch.new"}, master_on=False,
    )
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.asyncio
async def test_change_and_revert_before_save_does_not_reload() -> None:
    """(b) operator edits a field then sets it back: the SAVED value equals
    the snapshot → no change → no reload."""
    before = _pre_options()
    hass = await _listen(before, dict(before))
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.asyncio
async def test_save_unchanged_does_not_reload() -> None:
    """(c) saving the form unchanged (fresh dict, list copied) → no reload."""
    before = _pre_options()
    after = {k: (list(v) if isinstance(v, list) else v) for k, v in before.items()}
    hass = await _listen(before, after)
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.asyncio
async def test_none_empty_missing_equivalent_does_not_reload() -> None:
    """(e) None ↔ "" ↔ missing on a mapping key is not a change."""
    before = {**_pre_options(), "energy_solar_entity": None}
    hass = await _listen(before, {**before, "energy_solar_entity": ""})
    hass.config_entries.async_reload.assert_not_called()
    hass = await _listen(before, {k: v for k, v in before.items() if k != "energy_solar_entity"})
    hass.config_entries.async_reload.assert_not_called()


@pytest.mark.asyncio
async def test_setter_dispatch_key_applies_live_without_reload() -> None:
    """(d) a live-applied energy knob (_EC_SETTER_DISPATCH) → no reload of
    any entry; the coordinator's setter receives the new value."""
    energy = MagicMock(name="energy_coordinator")
    manager = SimpleNamespace(coordinators={"energy": energy})
    before = _pre_options()
    hass = await _listen(
        before, {**before, "energy_peak_buffer_target": 85}, manager=manager,
    )
    hass.config_entries.async_reload.assert_not_called()
    energy.set_peak_buffer_target.assert_called_once_with(85)


# ---------------------------------------------------------------------------
# Repair-issue scanner.
# ---------------------------------------------------------------------------


def _scan_hass(registered: set[str], unavailable: set[str] = frozenset()):
    hass = MagicMock()

    def _get(eid):
        if eid in unavailable:
            return SimpleNamespace(state="unavailable")
        if eid in registered:
            return SimpleNamespace(state="on")
        return None

    hass.states.get.side_effect = _get
    return hass


def _scan(hass, entry, strikes, registered):
    created, deleted = [], []
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=_StubEntityRegistry(registered),
    ), patch(
        "homeassistant.helpers.issue_registry.async_create_issue",
        side_effect=lambda *a, **k: created.append((a[2], k)),
    ), patch(
        "homeassistant.helpers.issue_registry.async_delete_issue",
        side_effect=lambda _h, _d, issue_id: deleted.append(issue_id),
    ):
        ura._scan_ec_role_entities(hass, entry, strikes)
    return created, deleted


def test_scan_needs_two_consecutive_bad_scans() -> None:
    entry = _cm_entry({"energy_storage_mode_entity": "select.does_not_exist"})
    hass = _scan_hass(set())
    strikes: dict = {}
    created, _ = _scan(hass, entry, strikes, set())
    assert created == []
    created, _ = _scan(hass, entry, strikes, set())
    assert [c[0] for c in created] == ["ec_role_entity_energy_storage_mode_entity"]
    assert created[0][1]["translation_placeholders"] == {
        "key": "energy_storage_mode_entity",
        "entity_id": "select.does_not_exist",
        "problem": "not_in_registry",
    }


def test_scan_unavailable_entity_raises_after_two_scans() -> None:
    eid = "sensor.solar_forecast_today"
    entry = _cm_entry({"energy_solcast_today_entity": eid})
    hass = _scan_hass({eid}, {eid})
    strikes: dict = {}
    _scan(hass, entry, strikes, {eid})
    created, _ = _scan(hass, entry, strikes, {eid})
    assert created[0][1]["translation_placeholders"]["problem"] == "unavailable"


def test_scan_recovery_resets_strikes_and_deletes_issue() -> None:
    bad = _cm_entry({"energy_storage_mode_entity": "select.x"})
    strikes: dict = {}
    _scan(_scan_hass(set()), bad, strikes, set())
    _, deleted = _scan(_scan_hass({"select.x"}), bad, strikes, {"select.x"})
    assert "ec_role_entity_energy_storage_mode_entity" in deleted
    created, _ = _scan(_scan_hass(set()), bad, strikes, set())
    assert created == []  # strike count restarted after the healthy scan


def test_scan_deletes_issue_when_key_becomes_unset() -> None:
    strikes = {"energy_storage_mode_entity": 5}
    _, deleted = _scan(_scan_hass(set()), _cm_entry({}), strikes, set())
    assert "ec_role_entity_energy_storage_mode_entity" in deleted
    assert "energy_storage_mode_entity" not in strikes


def test_scan_owned_by_creating_entry_and_waits_for_started() -> None:
    hass = MagicMock()
    cm = _cm_entry({"energy_storage_mode_entity": "select.x"})
    hass.config_entries.async_get_entry.return_value = cm
    owner = MagicMock(name="integration_entry")
    started_cbs: list = []
    interval_calls: list = []
    scans: list = []
    with patch(
        "homeassistant.helpers.start.async_at_started",
        side_effect=lambda h, cb: started_cbs.append(cb) or "unsub_started",
    ), patch.object(
        ura, "async_track_time_interval",
        side_effect=lambda h, cb, iv: interval_calls.append((cb, iv)) or "unsub_interval",
    ), patch.object(
        ura, "_scan_ec_role_entities",
        side_effect=lambda h, e, s: scans.append(e.entry_id),
    ):
        ura._start_ec_role_scan(hass, owner, cm.entry_id)
        assert scans == []  # nothing before HA has started
        assert interval_calls == []
        assert len(started_cbs) == 1
        started_cbs[0](hass)
        assert scans == ["cm-test"]
        assert interval_calls[0][1].total_seconds() == 3600
        interval_calls[0][0](None)
        assert scans == ["cm-test", "cm-test"]
    registered = [c.args[0] for c in owner.async_on_unload.call_args_list]
    assert registered == ["unsub_started", "unsub_interval"]


# ---------------------------------------------------------------------------
# EVSE config builder (replaces the former DEFAULT_EVSE_ENTITIES table).
# ---------------------------------------------------------------------------


def test_build_evse_config_phalanx_equals_former_table() -> None:
    pinned = copy.deepcopy(ec_const.EC_ROLE_KEY_DEFAULTS)
    assert ura._build_evse_config_from_options(pinned) == {
        "garage_a": {
            "switch": "switch.garage_a",
            "power": "sensor.garage_a_power_minute_average",
            "energy_today": "sensor.garage_a_energy_today",
            "energy_month": "sensor.garage_a_energy_this_month",
            "span_breaker": "switch.span_panel_car_charger_breaker",
            "current_limit": "number.garage_a_evse_emporia_wifi_garagea_current_limit",
        },
        "garage_b": {
            "switch": "switch.garage_b",
            "power": "sensor.garage_b_power_minute_average",
            "energy_today": "sensor.garage_b_energy_today",
            "energy_month": "sensor.garage_b_energy_this_month",
            "span_breaker": "switch.span_panel_garage_b_evse_breaker",
            "current_limit": "number.garage_b_evse_emporia_wifi_garageb_current_limit",
        },
    }


def test_build_evse_config_override_and_partial() -> None:
    assert ura._build_evse_config_from_options({
        "energy_evse_a_span_breaker": "switch.renamed_breaker",
        "energy_evse_a_switch_entity": "switch.my_charger",
    }) == {"garage_a": {"switch": "switch.my_charger", "span_breaker": "switch.renamed_breaker"}}


def test_build_evse_config_empty_on_second_install() -> None:
    assert ura._build_evse_config_from_options({}) == {}


# ---------------------------------------------------------------------------
# Options reach the coordinator (edits take effect after the reload).
# ---------------------------------------------------------------------------


def _energy_coord(entity_config: dict):
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_entries = lambda *_a, **_k: []
    return EnergyCoordinator(
        hass=hass, reserve_soc=20, decision_interval=10,
        entity_config=entity_config, tou_engine=MagicMock(name="tou_engine"),
    )


def test_pool_roles_flow_from_options_into_optimizer() -> None:
    coord = _energy_coord({
        "energy_pool_speed_entity": "number.my_pool_speed",
        "energy_pool_power_entity": "sensor.my_pool_power",
    })
    assert coord._pool._speed_entity == "number.my_pool_speed"
    assert coord._pool._power_entity == "sensor.my_pool_power"


def test_cloud_last_success_role_reaches_battery_entity_map() -> None:
    coord = _energy_coord({"energy_cloud_last_success_entity": "sensor.my_cloud_stamp"})
    assert coord._battery._entities["cloud_last_success"] == "sensor.my_cloud_stamp"


# ---------------------------------------------------------------------------
# None-safe readers on a second install.
# ---------------------------------------------------------------------------


def _strict_hass():
    hass = MagicMock()

    def _get(eid):
        assert eid, f"states.get called with {eid!r}"
        return None

    hass.states.get.side_effect = _get
    return hass


def test_pool_readers_none_when_unconfigured() -> None:
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        PoolOptimizer,
    )
    pool = PoolOptimizer(_strict_hass())
    assert pool.current_speed is None
    assert pool.current_power is None


def test_generator_status_unavailable_when_unconfigured() -> None:
    from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
        GeneratorMonitor,
    )
    assert GeneratorMonitor(_strict_hass()).status == "unavailable"


def test_forecast_temperature_none_when_unconfigured() -> None:
    from custom_components.universal_room_automation.domain_coordinators.energy_forecast import (
        DailyEnergyPredictor,
    )
    assert DailyEnergyPredictor(_strict_hass())._get_current_temperature() is None


# ---------------------------------------------------------------------------
# l1_charger_active reads the CONFIGURED plug list.
# ---------------------------------------------------------------------------


def _l1_active(plugs: list[str], on: set[str]) -> bool:
    from custom_components.universal_room_automation.domain_coordinators.energy import (
        EnergyCoordinator,
    )
    from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
        SmartPlugController,
    )
    hass = MagicMock()
    hass.states.get.side_effect = lambda eid: SimpleNamespace(
        state="on" if eid in on else "off",
    )
    shell = SimpleNamespace(hass=hass, _smart_plugs=SmartPlugController(hass, plug_entities=plugs))
    return EnergyCoordinator.l1_charger_active.fget(shell)


def test_l1_charger_active_true_when_configured_plug_on() -> None:
    assert _l1_active(["switch.plug_1", "switch.plug_2"], {"switch.plug_2"}) is True


def test_l1_charger_active_false_when_no_plug_configured() -> None:
    # A plug that is ON but NOT configured must not count.
    assert _l1_active([], {"switch.smartplug_moes_wifi_garagealeftfront_socket_3"}) is False


# ---------------------------------------------------------------------------
# Relabels (friendly names; entity_id / unique_id unchanged).
# ---------------------------------------------------------------------------


def test_relabel_battery_gateway_status_sensor() -> None:
    from custom_components.universal_room_automation.sensor import EnergyEnvoyStatusSensor
    s = EnergyEnvoyStatusSensor(MagicMock(), MagicMock())
    assert s._attr_name == "Battery gateway status"
    assert s._attr_unique_id == "universal_room_automation_energy_envoy_status"


def test_relabel_battery_gateway_online_binary_sensor() -> None:
    from custom_components.universal_room_automation.binary_sensor import (
        EnergyEnvoyAvailableBinarySensor,
    )
    s = EnergyEnvoyAvailableBinarySensor(MagicMock(), MagicMock())
    assert s._attr_name == "Battery gateway online"
    assert s._attr_unique_id == "universal_room_automation_energy_envoy_available"


# ---------------------------------------------------------------------------
# Wire-in anchor: the REAL integration-entry setup (async_setup_entry) calls
# the pin, starts the role scan owned by the integration entry, and builds the
# EnergyCoordinator's EVSE config from the role-keyed CM options.
# ---------------------------------------------------------------------------


# A full integration-entry setup with no unload leaves the integration's own
# timers/DB writer running; those are not under test here.
@pytest.mark.parametrize("expected_lingering_tasks", [True])
@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_integration_setup_wires_pin_scan_and_evse_builder() -> None:
    from unittest.mock import AsyncMock

    from runtime_harness import StubConfigEntry, StubHass, make_coordinator_manager_entry

    from custom_components.universal_room_automation import coordinator_gate
    from custom_components.universal_room_automation.const import (
        CONF_DOMAIN_COORDINATORS_ENABLED,
        ENTRY_TYPE_INTEGRATION,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as energy_mod,
    )

    class _Entry(StubConfigEntry):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.unloads: list = []

        def async_on_unload(self, func):
            self.unloads.append(func)

    cm = make_coordinator_manager_entry(options={
        "energy_evse_a_switch_entity": "switch.my_charger_a",
        "energy_evse_b_span_breaker": "switch.my_breaker_b",
    })
    integ = _Entry(
        "integ", ENTRY_TYPE_INTEGRATION,
        data={CONF_DOMAIN_COORDINATORS_ENABLED: True},
    )
    hass = StubHass(config_entries=[cm, integ])
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)

    calls: list = []

    async def _pin(h, entry):
        calls.append(("pin", entry.entry_id))
        return False

    def _scan(h, owner, cm_entry_id):
        calls.append(("scan", owner.entry_id, cm_entry_id))

    real_builder = ura._build_evse_config_from_options

    def _builder(cm_config):
        out = real_builder(cm_config)
        calls.append(("evse", out))
        return out

    ec_cls = MagicMock(name="EnergyCoordinator")
    with patch.object(ura, "_bootstrap_pin_ec_defaults_once", _pin), patch.object(
        ura, "_start_ec_role_scan", _scan,
    ), patch.object(ura, "_build_evse_config_from_options", _builder), patch.object(
        coordinator_gate, "coordinators_to_register", lambda *a, **k: {"energy"},
    ), patch.object(energy_mod, "EnergyCoordinator", ec_cls):
        try:
            assert await ura.async_setup_entry(hass, integ) is True
        finally:
            # Setup starts the loop-stall watchdog thread; stop it.
            from custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog import (
                uninstall,
            )
            uninstall(hass)

    expected_evse = {
        "garage_a": {"switch": "switch.my_charger_a"},
        "garage_b": {"span_breaker": "switch.my_breaker_b"},
    }
    assert ("pin", "coordinator_manager_entry") in calls
    assert ("scan", "integ", "coordinator_manager_entry") in calls
    assert ("evse", expected_evse) in calls
    assert ec_cls.call_args.kwargs["evse_config"] == expected_evse


@pytest.mark.parametrize("expected_lingering_tasks", [True])
@pytest.mark.parametrize("expected_lingering_timers", [True])
@pytest.mark.asyncio
async def test_role_key_edit_reload_rebuilds_coordinator_with_new_entity() -> None:
    """(a, part 2) the save schedules ONE parent reload; performing that
    reload (the real parent setup) builds the EnergyCoordinator with the NEW
    entity, read from the saved options."""
    from unittest.mock import AsyncMock

    from runtime_harness import StubConfigEntry, StubHass, make_coordinator_manager_entry

    from custom_components.universal_room_automation import coordinator_gate
    from custom_components.universal_room_automation.const import (
        CONF_DOMAIN_COORDINATORS_ENABLED,
        ENTRY_TYPE_INTEGRATION,
    )
    from custom_components.universal_room_automation.domain_coordinators import (
        energy as energy_mod,
    )

    class _Entry(StubConfigEntry):
        def async_on_unload(self, func):
            pass

    before = {
        "energy_evse_a_switch_entity": "switch.old_charger_a",
        "energy_storage_mode_entity": "select.old_battery_mode",
        "_ec_defaults_pinned": True,
    }
    cm = make_coordinator_manager_entry(options=dict(before))
    integ = _Entry(
        "integ", ENTRY_TYPE_INTEGRATION,
        data={CONF_DOMAIN_COORDINATORS_ENABLED: True},
    )
    hass = StubHass(config_entries=[cm, integ])
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_reload = AsyncMock(name="async_reload")
    hass.data.setdefault(DOMAIN, {})["cm_last_applied_options"] = {cm.entry_id: dict(before)}

    # Operator saves a new charger switch + battery-mode entity.
    cm.options = {
        **before,
        "energy_evse_a_switch_entity": "switch.new_charger_a",
        "energy_storage_mode_entity": "select.new_battery_mode",
    }
    await ura._async_update_listener(hass, cm)
    hass.config_entries.async_reload.assert_called_once_with("integ")

    # Perform that reload: the parent entry's real setup.
    ec_cls = MagicMock(name="EnergyCoordinator")
    with patch.object(
        coordinator_gate, "coordinators_to_register", lambda *a, **k: {"energy"},
    ), patch.object(energy_mod, "EnergyCoordinator", ec_cls), patch.object(
        ura, "_start_ec_role_scan", lambda *a, **k: None,
    ):
        try:
            assert await ura.async_setup_entry(hass, integ) is True
        finally:
            from custom_components.universal_room_automation.domain_coordinators._loop_stall_watchdog import (
                uninstall,
            )
            uninstall(hass)
    kwargs = ec_cls.call_args.kwargs
    assert kwargs["evse_config"] == {"garage_a": {"switch": "switch.new_charger_a"}}
    assert kwargs["entity_config"]["energy_storage_mode_entity"] == "select.new_battery_mode"
