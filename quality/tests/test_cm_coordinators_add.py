"""CM-COORDINATORS-ADD-ONE-BY-ONE-1 Phase A + B.

Plan: docs/planning/PLANNING_cm_coordinators_add_one_by_one.md (incl. plan
review findings 1-7).

- One default table + one run gate (``coordinator_gate.coordinator_should_run``)
  used by every registration site, the Enabled switch, NM ``enabled`` and the
  music-following kill switch.
- New install: only Presence added/running; switches truthful.
- Existing install migration: freezes today's effective run state.
- CM options menu: Add a coordinator / Remove a coordinator / settings only
  for added coordinators; added only on save; remove keeps settings; first
  add turns the master on (single parent reload).
- Entitlement hook deny path (flow abort + runtime gate + repair issue).

The flow tests drive the production OptionsFlow methods through the shared
mocked-HA harness (test_cycle_b_config_flow). The run-gate / switch /
migration tests import the real modules.
"""
from __future__ import annotations

import ast
import asyncio
import importlib
import pathlib
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant.core")

_COMPONENT = (
    pathlib.Path(__file__).resolve().parents[2]
    / "custom_components" / "universal_room_automation"
)

from custom_components.universal_room_automation import (  # noqa: E402
    coordinator_gate as gate,
    entitlements,
)
from custom_components.universal_room_automation.const import (  # noqa: E402
    ADDABLE_COORDINATORS,
    CONF_COORDINATORS_ADDED,
    CONF_DOMAIN_COORDINATORS_ENABLED,
    CONF_ENTRY_TYPE,
    COORDINATOR_ENABLED_DEFAULTS,
    COORDINATOR_ENABLED_KEYS,
    COORDINATORS_ADDED_MIGRATION_DONE,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_INTEGRATION,
)
from custom_components.universal_room_automation.switch import (  # noqa: E402
    CoordinatorEnabledSwitch,
)

_cbcf = importlib.import_module("test_cycle_b_config_flow")
_cf = _cbcf._cf


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Entry:
    def __init__(self, entry_id, data, options=None):
        self.entry_id = entry_id
        self.data = data
        self.options = dict(options or {})
        self.title = entry_id


class _ConfigEntries:
    def __init__(self, entries):
        self._entries = entries
        self.updates: list[tuple[str, dict]] = []
        self.reloads: list[str] = []

    def async_entries(self, domain=None):
        return list(self._entries)

    def async_update_entry(self, entry, *, options=None, data=None):
        if options is not None:
            if dict(options) == entry.options:
                return False
            entry.options = dict(options)
            self.updates.append((entry.entry_id, dict(options)))
        return True

    def async_reload(self, entry_id):
        # Recorded at call time (the production code schedules it as a task).
        self.reloads.append(entry_id)
        return asyncio.sleep(0)


class _Hass:
    def __init__(self, entries):
        self.config_entries = _ConfigEntries(entries)
        self.data = {}
        self.tasks: list = []

    def async_create_task(self, coro, *a, **kw):
        self.tasks.append(coro)
        coro.close()


def _house(cm_options, master=True):
    parent = _Entry(
        "parent", {CONF_ENTRY_TYPE: ENTRY_TYPE_INTEGRATION},
        {CONF_DOMAIN_COORDINATORS_ENABLED: master},
    )
    cm = _Entry("cm", {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}, cm_options)
    return _Hass([parent, cm]), parent, cm


def _switch(hass, cm, cid):
    return CoordinatorEnabledSwitch(
        hass, cm, coordinator_id=cid, conf_key=COORDINATOR_ENABLED_KEYS[cid],
        name="x", icon="mdi:x", device_id=f"dev_{cid}", device_name="d",
        device_model="m",
    )


def _running(cm_options):
    """The set the registration gates would register (same helper)."""
    return {c for c in ADDABLE_COORDINATORS if gate.coordinator_should_run(cm_options, c)}


_OF_BASE = _cf.UniversalRoomAutomationOptionsFlow.__mro__[1]
if not hasattr(_OF_BASE, "async_abort"):
    # The shared mocked-HA harness base lacks async_abort; same shape as
    # its ConfigFlow fake.
    _OF_BASE.async_abort = lambda self, **kw: {"type": "abort", **kw}


def _options_flow(hass, cm):
    flow = _cf.UniversalRoomAutomationOptionsFlow.__new__(
        _cf.UniversalRoomAutomationOptionsFlow
    )
    flow._config_entry = cm
    flow._selected_zone_entry_id = None
    flow._pending_delete_rule_id = None
    flow.hass = hass
    return flow


# ---------------------------------------------------------------------------
# D1 — one default, one gate, every site
# ---------------------------------------------------------------------------


def test_defaults_table_covers_every_addable_coordinator():
    assert set(COORDINATOR_ENABLED_DEFAULTS) == set(ADDABLE_COORDINATORS)
    assert set(ADDABLE_COORDINATORS) <= set(COORDINATOR_ENABLED_KEYS)
    # Today's defaults (big modules + NM off).
    assert {c for c, v in COORDINATOR_ENABLED_DEFAULTS.items() if not v} == {
        "energy", "hvac", "notification_manager",
    }


def _gate_calls(path: pathlib.Path) -> list[str]:
    """coordinator ids passed to coordinator_should_run in a source file."""
    tree = ast.parse(path.read_text())
    ids = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None))
                == "coordinator_should_run"):
            arg = node.args[1]
            assert isinstance(arg, ast.Constant), "coordinator id must be a literal"
            ids.append(arg.value)
    return ids


def test_every_registration_gate_uses_the_one_helper():
    """All eight registration sites in __init__.py route through the helper,
    once each, and no gate reads its *_enabled key with an inline default."""
    src_path = _COMPONENT / "__init__.py"
    assert sorted(_gate_calls(src_path)) == sorted(ADDABLE_COORDINATORS)
    src = src_path.read_text()
    for key_const in (
        "CONF_PRESENCE_ENABLED", "CONF_SAFETY_ENABLED", "CONF_SECURITY_ENABLED",
        "CONF_MUSIC_FOLLOWING_COORDINATOR_ENABLED", "CONF_ENERGY_ENABLED",
        "CONF_APPLIANCE_COORDINATOR_ENABLED", "CONF_HVAC_ENABLED", "CONF_NM_ENABLED",
    ):
        assert f"cm_config.get({key_const}" not in src, key_const


def test_other_readers_use_the_helper():
    assert _gate_calls(_COMPONENT / "music_following.py") == ["music_following"]
    assert _gate_calls(
        _COMPONENT / "domain_coordinators" / "notification_manager.py"
    ) == ["notification_manager"]


@pytest.mark.parametrize("cid", ADDABLE_COORDINATORS)
def test_enabled_switch_default_matches_registration_default(cid):
    """Key absent (pre-migration install): the switch reads exactly what the
    registration gate decides — the Bug Class #63 split is closed."""
    hass, _parent, cm = _house({})
    sw = _switch(hass, cm, cid)
    assert sw.is_on is COORDINATOR_ENABLED_DEFAULTS[cid]
    assert sw.is_on == (cid in _running({}))


# ---------------------------------------------------------------------------
# D2 — fresh install + migration
# ---------------------------------------------------------------------------


def test_fresh_install_only_presence_runs_and_switches_truthful():
    opts = gate.new_install_cm_options()
    assert opts[CONF_COORDINATORS_ADDED] == ["presence"]
    assert opts[COORDINATORS_ADDED_MIGRATION_DONE] is True
    assert _running(opts) == {"presence"}
    hass, _parent, cm = _house(opts)
    for cid in ADDABLE_COORDINATORS:
        sw = _switch(hass, cm, cid)
        assert sw.is_on is (cid == "presence"), cid
        assert sw.available is (cid == "presence"), cid
        assert sw.extra_state_attributes == {"added": cid == "presence"}
    # Migration is a no-op on a fresh install (sentinel already set).
    assert _run(gate.async_migrate_coordinators_added(hass)) is False
    assert hass.config_entries.updates == []


def test_cm_entry_creation_seeds_options():
    """The CM entry create step passes the seed as entry options."""
    flow = _cbcf._make_config_flow()
    result = _run(flow.async_step_coordinator_manager_migration(
        {CONF_ENTRY_TYPE: ENTRY_TYPE_COORDINATOR_MANAGER}
    ))
    assert result["type"] == "create_entry"
    assert result["options"] == gate.new_install_cm_options()


@pytest.mark.parametrize("cm_options", [
    # Main-house shape: all keys explicit (mixed values).
    {
        "presence_coordinator_enabled": True,
        "safety_coordinator_enabled": True,
        "security_coordinator_enabled": False,
        "music_following_coordinator_enabled": True,
        "energy_coordinator_enabled": True,
        "appliance_coordinator_enabled": True,
        "hvac_coordinator_enabled": True,
        "notification_manager_enabled": True,
        "some_setting": 7,
    },
    # Mixed explicit / unset.
    {
        "safety_coordinator_enabled": False,
        "hvac_coordinator_enabled": True,
        "security_lock_entities": ["lock.front"],
    },
    # Pre-D1 install: nothing written.
    {},
])
def test_existing_install_migration_keeps_identical_run_set(cm_options):
    before = _running(cm_options)
    hass, parent, cm = _house(cm_options, master=False)
    assert _run(gate.async_migrate_coordinators_added(hass)) is True
    after_opts = cm.options
    assert _running(after_opts) == before
    assert set(after_opts[CONF_COORDINATORS_ADDED]) == before
    assert after_opts[COORDINATORS_ADDED_MIGRATION_DONE] is True
    # Every run key now explicit and equal to the effective state.
    for cid in ADDABLE_COORDINATORS:
        assert after_opts[COORDINATOR_ENABLED_KEYS[cid]] is (cid in before)
    # Other settings preserved.
    for k, v in cm_options.items():
        if k not in COORDINATOR_ENABLED_KEYS.values():
            assert after_opts[k] == v
    # Master switch untouched (runs regardless of it) and nothing reloaded.
    assert parent.options[CONF_DOMAIN_COORDINATORS_ENABLED] is False
    assert hass.config_entries.reloads == []
    # Second run is a no-op.
    n = len(hass.config_entries.updates)
    assert _run(gate.async_migrate_coordinators_added(hass)) is False
    assert len(hass.config_entries.updates) == n


def test_presence_absent_migration_unset_keys_keep_big_modules_off():
    hass, _parent, cm = _house({})
    _run(gate.async_migrate_coordinators_added(hass))
    assert set(cm.options[CONF_COORDINATORS_ADDED]) == {
        "presence", "safety", "security", "music_following", "appliance",
    }


def test_migration_runs_outside_master_gate():
    """Plan review finding 1: the migration call sits before the master gate
    in integration setup (it must run while the master switch is OFF)."""
    src = (_COMPONENT / "__init__.py").read_text()
    call = src.index("await async_migrate_coordinators_added(hass)")
    gate_line = src.index("if merged_config.get(CONF_DOMAIN_COORDINATORS_ENABLED, False):")
    ensure = src.index("await _ensure_coordinator_manager_entry(hass, entry)")
    assert ensure < call < gate_line


def test_reload_keeps_state():
    """State lives in CM options: a fresh switch object (as after a reload)
    reads the same values."""
    opts = gate.migrated_cm_options({"hvac_coordinator_enabled": True})
    hass, _parent, cm = _house(opts)
    first = {c: _switch(hass, cm, c).is_on for c in ADDABLE_COORDINATORS}
    second = {c: _switch(hass, cm, c).is_on for c in ADDABLE_COORDINATORS}
    assert first == second
    assert _running(cm.options) == {c for c, v in first.items() if v}


# ---------------------------------------------------------------------------
# D3 — CM menu add / remove
# ---------------------------------------------------------------------------


def _settings_steps(menu):
    return [m for m in menu if m.startswith("coordinator_") and m != "coordinator_optimization"]


def test_cm_menu_lists_only_added_coordinators():
    hass, _parent, cm = _house(gate.new_install_cm_options())
    result = _run(_options_flow(hass, cm).async_step_init())
    menu = result["menu_options"]
    assert menu[0] == "add_coordinator"
    assert _settings_steps(menu) == ["coordinator_presence"]
    assert "remove_coordinator" in menu
    assert menu[-2:] == ["signal_responses", "coordinator_optimization"]

    # All added -> no Add entry, every settings step present.
    all_on = gate.migrated_cm_options({})
    all_on[CONF_COORDINATORS_ADDED] = list(ADDABLE_COORDINATORS)
    hass, _parent, cm = _house(all_on)
    menu = _run(_options_flow(hass, cm).async_step_init())["menu_options"]
    assert "add_coordinator" not in menu
    assert "coordinator_hvac" in menu and "coordinator_notifications_routing" in menu


def test_add_menu_lists_not_added_only():
    hass, _parent, cm = _house(gate.new_install_cm_options())
    result = _run(_options_flow(hass, cm).async_step_add_coordinator())
    assert result["type"] == "menu"
    assert set(result["menu_options"]) == {
        f"addc_{c}" for c in ADDABLE_COORDINATORS if c != "presence"
    }
    assert result["menu_options"]["addc_hvac"] == "Climate (HVAC)"


def test_add_hvac_writes_added_and_enabled_on_submit_only():
    hass, parent, cm = _house(gate.new_install_cm_options(), master=True)
    flow = _options_flow(hass, cm)
    shown = _run(flow.async_step_addc_hvac())
    # Routed into the existing HVAC settings form; nothing written yet.
    assert shown["type"] == "form" and shown["step_id"] == "coordinator_hvac_settings"
    assert hass.config_entries.updates == []
    assert "hvac" not in cm.options[CONF_COORDINATORS_ADDED]

    # Abandoning the flow (a new flow instance) writes nothing.
    _run(_options_flow(hass, cm).async_step_init())
    assert hass.config_entries.updates == []

    # Saving the settings step completes the add.
    result = flow.async_create_entry(title="", data={**cm.options, "hvac_x": 1})
    assert result["type"] == "create_entry"
    assert cm.options["hvac_x"] == 1
    assert "hvac" in cm.options[CONF_COORDINATORS_ADDED]
    assert cm.options[COORDINATOR_ENABLED_KEYS["hvac"]] is True
    assert result["data"] == cm.options  # flow result = no-op rewrite
    assert gate.coordinator_should_run(cm.options, "hvac")
    assert _switch(hass, cm, "hvac").is_on and _switch(hass, cm, "hvac").available
    # Master already on: exactly one parent reload.
    assert hass.config_entries.reloads == ["parent"]


def test_add_confirm_coordinator():
    hass, _parent, cm = _house(gate.new_install_cm_options())
    flow = _options_flow(hass, cm)
    form = _run(flow.async_step_addc_appliance())
    assert form["step_id"] == "add_coordinator_confirm"
    assert form["description_placeholders"] == {"name": "Appliances"}
    _run(flow.async_step_add_coordinator_confirm({}))
    assert "appliance" in cm.options[CONF_COORDINATORS_ADDED]


def test_add_security_also_adds_presence():
    opts = gate.new_install_cm_options()
    opts[CONF_COORDINATORS_ADDED] = []
    opts[COORDINATOR_ENABLED_KEYS["presence"]] = False
    hass, _parent, cm = _house(opts)
    flow = _options_flow(hass, cm)
    _run(flow.async_step_addc_security())
    flow.async_create_entry(title="", data=dict(cm.options))
    assert set(cm.options[CONF_COORDINATORS_ADDED]) == {"security", "presence"}
    assert cm.options[COORDINATOR_ENABLED_KEYS["presence"]] is True


def test_add_first_coordinator_turns_on_master():
    hass, parent, cm = _house(gate.new_install_cm_options(), master=False)
    flow = _options_flow(hass, cm)
    _run(flow.async_step_addc_appliance())
    _run(flow.async_step_add_coordinator_confirm({}))
    assert parent.options[CONF_DOMAIN_COORDINATORS_ENABLED] is True
    # Turning the master on IS the reload (its update listener); no extra
    # explicit reload from the flow.
    assert hass.config_entries.reloads == []
    # CM options written before the master switch.
    assert [u[0] for u in hass.config_entries.updates] == ["cm", "parent"]


def test_remove_keeps_settings_and_readd_restores():
    opts = gate.migrated_cm_options({"hvac_coordinator_enabled": True})
    opts["hvac_sleep_offset"] = 3
    hass, parent, cm = _house(opts, master=True)
    flow = _options_flow(hass, cm)
    menu = _run(flow.async_step_remove_coordinator())
    assert "remc_hvac" in menu["menu_options"]
    form = _run(flow.async_step_remc_hvac())
    assert form["step_id"] == "remove_coordinator_confirm"
    _run(flow.async_step_remove_coordinator_confirm({}))
    assert "hvac" not in cm.options[CONF_COORDINATORS_ADDED]
    assert cm.options[COORDINATOR_ENABLED_KEYS["hvac"]] is False
    assert cm.options["hvac_sleep_offset"] == 3
    assert not gate.coordinator_should_run(cm.options, "hvac")
    assert _switch(hass, cm, "hvac").available is False
    assert hass.config_entries.reloads == ["parent"]
    assert parent.options[CONF_DOMAIN_COORDINATORS_ENABLED] is True

    # Re-add: settings still there, form defaults read them.
    flow2 = _options_flow(hass, cm)
    _run(flow2.async_step_addc_hvac())
    flow2.async_create_entry(title="", data=dict(cm.options))
    assert "hvac" in cm.options[CONF_COORDINATORS_ADDED]
    assert cm.options["hvac_sleep_offset"] == 3
    assert gate.coordinator_should_run(cm.options, "hvac")


def test_not_added_switch_turn_on_is_refused():
    hass, _parent, cm = _house(gate.new_install_cm_options())
    _run(_switch(hass, cm, "hvac").async_turn_on())
    assert hass.config_entries.updates == []
    assert hass.config_entries.reloads == []


def test_non_cm_create_entry_untouched():
    hass, _parent, cm = _house(gate.new_install_cm_options())
    flow = _options_flow(hass, cm)
    result = flow.async_create_entry(title="", data={"a": 1})
    assert result["data"] == {"a": 1}
    assert hass.config_entries.updates == []


# ---------------------------------------------------------------------------
# D4 — entitlement hook
# ---------------------------------------------------------------------------


def test_entitlement_allows_everything_today():
    for cid in ADDABLE_COORDINATORS:
        assert entitlements.can_use_coordinator(cid) == (True, None)


def test_entitlement_deny_path(monkeypatch):
    def _deny(cid):
        return (False, "Needs a plan") if cid == "hvac" else (True, None)

    monkeypatch.setattr(entitlements, "can_use_coordinator", _deny)
    monkeypatch.setattr(gate, "_DENIED_LOGGED", set())

    # Add menu aborts with the reason; nothing written.
    hass, _parent, cm = _house(gate.new_install_cm_options())
    result = _run(_options_flow(hass, cm).async_step_addc_hvac())
    assert result["type"] == "abort" and result["reason"] == "coordinator_not_allowed"
    assert result["description_placeholders"] == {"reason": "Needs a plan"}
    assert hass.config_entries.updates == []

    # Already-added HVAC (hand-edited options) is not registered and a repair
    # issue is raised.
    created = []
    from homeassistant.helpers import issue_registry as ir
    monkeypatch.setattr(ir, "async_create_issue", lambda *a, **kw: created.append((a, kw)))
    opts = gate.migrated_cm_options({"hvac_coordinator_enabled": True})
    fake_hass = SimpleNamespace()
    assert gate.coordinator_should_run(opts, "hvac", fake_hass) is False
    assert gate.coordinator_should_run(opts, "presence", fake_hass) is True
    assert len(created) == 1
    assert created[0][0][2] == "coordinator_not_entitled_hvac"
    assert created[0][1]["translation_key"] == "coordinator_not_entitled"
    # The switch tells the truth too.
    hass, _parent, cm = _house(opts)
    assert _switch(hass, cm, "hvac").is_on is False


def test_entitlement_called_from_exactly_two_places():
    hits = []
    for path in _COMPONENT.rglob("*.py"):
        if path.name == "entitlements.py":
            continue
        n = path.read_text().count("entitlements.can_use_coordinator(")
        hits += [path.name] * n
    assert sorted(hits) == ["config_flow.py", "coordinator_gate.py"]


def test_strings_present():
    import json
    for p in (_COMPONENT / "strings.json", _COMPONENT / "translations" / "en.json"):
        d = json.loads(p.read_text())
        st = d["options"]["step"]
        for k in ("add_coordinator", "remove_coordinator",
                  "add_coordinator_confirm", "remove_coordinator_confirm"):
            assert st[k]["title"], k
        assert st["init"]["menu_options"]["add_coordinator"].endswith("Add a coordinator")
        for k in ("nothing_to_add", "nothing_to_remove", "coordinator_not_allowed"):
            assert d["options"]["abort"][k]
        assert "coordinator_not_entitled" in d["issues"]
        assert "Add a coordinator" in d["config"]["abort"]["coordinator_use_options"]
