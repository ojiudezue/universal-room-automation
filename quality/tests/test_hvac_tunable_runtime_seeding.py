"""HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 — deterministic seed at CM setup.

The 14 HVAC factory tunable Numbers used to display the operator's
configured value while the coordinator ran the module DEFAULT until
some later write pushed the value across (per the card evidence: 6/943
nudges landed on the 300s default because ``Number.async_added_to_hass``
lost the boot race against sub-controller construction).

The fix: at CM setup, immediately after
``coordinator_manager.register_coordinator(hvac)``, iterate
``_HVAC_TUNABLE_DISPATCH`` and setattr each runtime field from
``cm_config``. Reusing the same dispatch table used by
``_apply_in_place`` so a 15th tunable added there inherits the seeding
for free.

These tests are the wire-in anchor: they fail if the helper is
detached from the CM setup path, and they fail if the helper stops
actually writing the runtime field.
"""
from __future__ import annotations

import ast
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "custom_components" / "universal_room_automation"
INIT_SRC_PATH = PKG / "__init__.py"
INIT_SRC = INIT_SRC_PATH.read_text()


# ---------------------------------------------------------------------------
# Helper extraction: pull just the seed function + dispatch out of __init__.py
# without importing the whole HA integration (which needs a live hass).
# ---------------------------------------------------------------------------

def _load_seed_helper():
    """Extract the seed helper + its dispatch table into an isolated module.

    We parse __init__.py's AST, keep only:
      - _HVAC_TUNABLE_DISPATCH (module dict)
      - _seed_hvac_runtime_tunables_from_options (function)

    Then exec into a namespace with a minimal `_LOGGER` shim. This
    exercises the REAL production function body, not a re-implementation.
    """
    tree = ast.parse(INIT_SRC)
    kept: list[ast.stmt] = []
    for node in tree.body:
        is_dispatch = (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_HVAC_TUNABLE_DISPATCH"
        ) or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "_HVAC_TUNABLE_DISPATCH"
                for t in node.targets
            )
        )
        if is_dispatch:
            # Rewrite tuple RHS to string keys so we don't need to
            # resolve every CONF_HVAC_* import — the dispatch keys are
            # used only by the seed function to look up in cm_config,
            # and cm_config in the test is under our control.
            kept.append(
                ast.parse(
                    "_HVAC_TUNABLE_DISPATCH = {\n"
                    "    'k_cover_close_delta':   ('_cover_controller',  '_occupied_close_delta',      float),\n"
                    "    'k_cover_close_temp':    ('_cover_controller',  '_cover_close_temp',          float),\n"
                    "    'k_cover_open_temp':     ('_cover_controller',  '_cover_open_temp',           float),\n"
                    "    'k_cover_override_hrs':  ('_cover_controller',  '_cover_override_hours',      float),\n"
                    "    'k_solar_bank_floor':    ('_predictor',         '_solar_bank_floor',          float),\n"
                    "    'k_fan_activation':      ('_fan_controller',    '_activation_delta',          float),\n"
                    "    'k_fan_hyst':            ('_fan_controller',    '_deactivation_delta',        float),\n"
                    "    'k_nudge_size':          ('_override_arrester', '_nudge_size_f',              float),\n"
                    "    'k_nudge_duration':      ('_override_arrester', '_nudge_duration_min',        int),\n"
                    "    'k_nudge_eval_delay':    ('_override_arrester', '_nudge_eval_delay_s',        int),\n"
                    "    'k_sustained_samples':   ('_override_arrester', '_sustained_samples',         int),\n"
                    "    'k_detection_gate':      ('_override_arrester', '_detection_time_gate_min',   int),\n"
                    "    'k_hard_reset_limit':    ('_override_arrester', '_hard_reset_daily_limit',    int),\n"
                    "    'k_hard_reset_int':      ('_override_arrester', '_hard_reset_min_interval_min', int),\n"
                    "}"
                ).body[0]
            )
        elif (
            isinstance(node, ast.FunctionDef)
            and node.name == "_seed_hvac_runtime_tunables_from_options"
        ):
            kept.append(node)
    assert kept, "expected _seed_hvac_runtime_tunables_from_options in __init__.py"
    module = ast.Module(body=kept, type_ignores=[])
    ns: dict = {"_LOGGER": types.SimpleNamespace(
        debug=lambda *a, **kw: None,
        info=lambda *a, **kw: None,
    )}
    exec(compile(module, "<seed_extract>", "exec"), ns)
    return ns


class _StubSub:
    """Mimics a sub-controller with module-default runtime fields."""
    def __init__(self, **defaults):
        for k, v in defaults.items():
            setattr(self, k, v)


class _StubHVAC:
    """Mimics HVACCoordinator with the four sub-controllers exposed as attrs."""
    def __init__(self, *, missing_arrester: bool = False):
        self._cover_controller = _StubSub(
            _occupied_close_delta=2.0,
            _cover_close_temp=85.0,
            _cover_open_temp=80.0,
            _cover_override_hours=2.0,
        )
        self._predictor = _StubSub(_solar_bank_floor=72.0)
        self._fan_controller = _StubSub(
            _activation_delta=2.0,
            _deactivation_delta=1.5,
        )
        if not missing_arrester:
            self._override_arrester = _StubSub(
                _nudge_size_f=1.5,
                _nudge_duration_min=5,          # DEFAULT_HVAC_AC_NUDGE_DURATION
                _nudge_eval_delay_s=600,
                _sustained_samples=3,
                _detection_time_gate_min=10,
                _hard_reset_daily_limit=3,
                _hard_reset_min_interval_min=30,
            )


# ---------------------------------------------------------------------------
# Behavioral: seed writes options into runtime fields, defaults preserved
# when option absent, missing sub-controller is a silent no-op.
# ---------------------------------------------------------------------------

def test_seed_helper_writes_options_into_runtime_fields():
    ns = _load_seed_helper()
    hvac = _StubHVAC()
    cm_options = {
        "k_nudge_duration": 2,      # operator value, DEFAULT=5 — the card's scenario
        "k_nudge_eval_delay": 240,
        "k_cover_close_temp": 88.0,
    }
    ns["_seed_hvac_runtime_tunables_from_options"](hvac, cm_options)

    # Configured values applied
    assert hvac._override_arrester._nudge_duration_min == 2
    assert hvac._override_arrester._nudge_eval_delay_s == 240
    assert hvac._cover_controller._cover_close_temp == 88.0
    # Cast honoured (int, not float)
    assert isinstance(hvac._override_arrester._nudge_duration_min, int)
    # Absent option => default preserved
    assert hvac._override_arrester._nudge_size_f == 1.5
    assert hvac._predictor._solar_bank_floor == 72.0


def test_seed_helper_absent_options_leaves_defaults_intact():
    ns = _load_seed_helper()
    hvac = _StubHVAC()
    # Empty options: byte-identical behaviour to pre-fix (all defaults kept).
    ns["_seed_hvac_runtime_tunables_from_options"](hvac, {})
    assert hvac._override_arrester._nudge_duration_min == 5   # DEFAULT
    assert hvac._override_arrester._nudge_eval_delay_s == 600
    assert hvac._cover_controller._cover_close_temp == 85.0


def test_seed_helper_missing_sub_controller_is_noop():
    ns = _load_seed_helper()
    hvac = _StubHVAC(missing_arrester=True)
    # Should not raise; arrester keys silently skipped, others still applied.
    ns["_seed_hvac_runtime_tunables_from_options"](
        hvac, {"k_nudge_duration": 2, "k_cover_close_temp": 88.0}
    )
    assert not hasattr(hvac, "_override_arrester")
    assert hvac._cover_controller._cover_close_temp == 88.0


# ---------------------------------------------------------------------------
# Wire-in anchor: the seed call MUST live in async_setup_entry, adjacent to
# `coordinator_manager.register_coordinator(hvac)`. Detached = defect
# regressed. This is the mutation-drill target.
# ---------------------------------------------------------------------------

def _find_async_setup_entry(tree: ast.Module) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry":
            return node
    raise AssertionError("async_setup_entry not found in __init__.py")


def test_seed_call_site_wired_into_async_setup_entry():
    """The seed helper must be CALLED inside async_setup_entry with the
    just-constructed `hvac` and CM options — not merely defined. Removing
    the call site (the mutation drill) fails this test."""
    tree = ast.parse(INIT_SRC)
    fn = _find_async_setup_entry(tree)

    hits: list[ast.Call] = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_seed_hvac_runtime_tunables_from_options"
        ):
            hits.append(node)

    assert hits, (
        "HVAC-TUNABLE-RUNTIME-NOT-SEEDED-1 wire-in missing: "
        "_seed_hvac_runtime_tunables_from_options is not called inside "
        "async_setup_entry. The 14 factory tunables will run the module "
        "DEFAULT after restart until a write pushes each value across."
    )
    call = hits[0]
    # First arg must be the freshly-registered `hvac` coordinator; second
    # must be the CM options dict (`cm_config`). Guards against a future
    # refactor that reorders or swaps args in a way that silently seeds
    # the wrong thing.
    assert len(call.args) == 2, "seed call must pass (hvac, cm_config)"
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "hvac"
    assert isinstance(call.args[1], ast.Name) and call.args[1].id == "cm_config"


# ---------------------------------------------------------------------------
# Zone-arm sweep + wire-in: the ONE per-zone Number that writes to
# ZoneState (`_hvac_zone_kwh_threshold_factory` -> `zone.kwh_rate_threshold`)
# persists via RestoreEntity, not entry.options, so it needs a second seed
# helper called AFTER `coordinator_manager.async_start()` (ordering required:
# `HVACCoordinator.async_setup` runs `async_discover_zones()` first).
# ---------------------------------------------------------------------------

NUMBER_SRC_PATH = PKG / "number.py"
NUMBER_SRC = NUMBER_SRC_PATH.read_text()


def test_sweep_only_one_zone_targeted_number_in_number_py():
    """Sweep for every Number in number.py that writes to a ZoneState
    field (`zone.<attr> = ...`), so a future per-zone Number added
    downstream doesn't quietly land on a third uncovered path.

    Current known targets: exactly ONE — `zone.kwh_rate_threshold` at
    number.py:2550 inside `_HVACZoneKwhThresholdNumber._push_to_zone`.
    If this test starts failing, either add the new key to the zone
    seed helper OR justify the exclusion in a comment on the new site.
    """
    import re
    hits = [
        (i + 1, line.strip())
        for i, line in enumerate(NUMBER_SRC.splitlines())
        if re.search(r"\bzone\.[a-zA-Z_][a-zA-Z_0-9]*\s*=", line)
        and "==" not in line
    ]
    assert hits, "sweep regex did not find any zone.<attr> = write; check regex"
    # Filter to actual writes (skip the docstring / comparison contexts).
    real_writes = [h for h in hits if "kwh_rate_threshold" in h[1]]
    assert real_writes, f"expected zone.kwh_rate_threshold write; got {hits}"
    # The invariant: only ONE known zone-target key today.
    keys = {h[1].split("zone.")[1].split(" ")[0].split("=")[0].strip() for h in hits}
    assert keys == {"kwh_rate_threshold"}, (
        f"NEW zone-targeted Number detected: {keys - {'kwh_rate_threshold'}}. "
        "Add it to `_seed_hvac_zone_kwh_thresholds_from_restore` in "
        "__init__.py (or explicitly justify skipping) so a boot race can't "
        "leave it on the dataclass default."
    )


def test_zone_seed_call_site_wired_after_async_start():
    """The zone seed helper MUST be awaited inside async_setup_entry
    AFTER `coordinator_manager.async_start()` — before that call,
    `zone_manager.zones` is empty (populated by async_discover_zones
    which runs inside async_start), so the seed would silently no-op."""
    tree = ast.parse(INIT_SRC)
    fn = _find_async_setup_entry(tree)

    call_line: int | None = None
    async_start_line: int | None = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            # `coordinator_manager.async_start()`
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "async_start"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "coordinator_manager"
            ):
                async_start_line = node.lineno
            # `_seed_hvac_zone_kwh_thresholds_from_restore(hass, ...)`
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "_seed_hvac_zone_kwh_thresholds_from_restore"
            ):
                call_line = node.lineno

    assert call_line is not None, (
        "Zone-arm wire-in missing: "
        "_seed_hvac_zone_kwh_thresholds_from_restore is not called inside "
        "async_setup_entry. Per-zone AC kWh threshold will fall back to "
        "the ZoneState dataclass default (0.8) on any boot race — the "
        "UNSAFE direction (more nudges, more manual-preset risk)."
    )
    assert async_start_line is not None, "async_start() call not found"
    assert call_line > async_start_line, (
        f"Zone seed call at line {call_line} must run AFTER "
        f"coordinator_manager.async_start() at line {async_start_line} — "
        "zones are populated by async_discover_zones() which runs inside "
        "async_start; calling the seed first would find no zones."
    )


# ---------------------------------------------------------------------------
# Behavioral: extract the zone-seed helper into an isolated namespace and
# exercise it against a fake ZoneManager + fake RestoreStateData.
# ---------------------------------------------------------------------------

def _load_zone_seed_helper():
    tree = ast.parse(INIT_SRC)
    fn: ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_seed_hvac_zone_kwh_thresholds_from_restore"
        ):
            fn = node
            break
    assert fn is not None, "zone seed helper not found"
    module = ast.Module(body=[fn], type_ignores=[])
    ns: dict = {
        "_LOGGER": types.SimpleNamespace(
            debug=lambda *a, **kw: None,
            info=lambda *a, **kw: None,
        ),
        "DOMAIN": "universal_room_automation",
    }
    exec(compile(module, "<zone_seed_extract>", "exec"), ns)
    return ns


class _StubZoneState:
    def __init__(self, climate_entity, default=0.8):
        self.climate_entity = climate_entity
        self.kwh_rate_threshold = default


class _StubZM:
    def __init__(self, zones):
        self.zones = zones


class _StubHVACForZone:
    def __init__(self, zones):
        self._zone_manager = _StubZM(zones)


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_zone_seed_writes_restored_value_into_zonestate(monkeypatch):
    ns = _load_zone_seed_helper()
    zones = {
        "zone_1": _StubZoneState("climate.zone_1"),
        "zone_2": _StubZoneState("climate.zone_2"),
    }
    hvac = _StubHVACForZone(zones)

    # Fake HA surfaces the helper reaches through dynamic imports.
    stored_state = types.SimpleNamespace(
        state=types.SimpleNamespace(state="1.30"),
    )
    fake_restore_data = types.SimpleNamespace(
        last_states={
            "number.ura_zone_1": stored_state,
            "number.ura_zone_2": types.SimpleNamespace(
                state=types.SimpleNamespace(state="not-a-number"),
            ),
        },
    )

    class _FakeRestoreDataCls:
        @staticmethod
        async def async_get_instance(_hass):
            return fake_restore_data

    class _FakeEntReg:
        def async_get_entity_id(self, domain, platform, unique_id):
            # Map unique_id -> entity_id for both zones so we exercise
            # the numeric + non-numeric branches.
            if "zone_1" in unique_id:
                return "number.ura_zone_1"
            if "zone_2" in unique_id:
                return "number.ura_zone_2"
            return None

    fake_er_mod = types.SimpleNamespace(async_get=lambda _hass: _FakeEntReg())
    fake_restore_mod = types.SimpleNamespace(RestoreStateData=_FakeRestoreDataCls)
    fake_hvac_zones_mod = types.SimpleNamespace(
        iter_canonical_hvac_zones=lambda _hass: [
            {"zone_id": "zone_1", "climate_entity": "climate.zone_1"},
            {"zone_id": "zone_2", "climate_entity": "climate.zone_2"},
        ],
    )

    import sys
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.restore_state", fake_restore_mod,
    )
    # helper does `from homeassistant.helpers import entity_registry as er`
    fake_helpers_pkg = types.ModuleType("homeassistant.helpers")
    fake_helpers_pkg.entity_registry = fake_er_mod
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", fake_helpers_pkg)
    monkeypatch.setitem(
        sys.modules,
        "homeassistant.helpers.entity_registry",
        fake_er_mod,
    )
    # helper does `from .domain_coordinators.hvac_zones import ...`
    monkeypatch.setitem(
        sys.modules,
        "custom_components.universal_room_automation.domain_coordinators.hvac_zones",
        fake_hvac_zones_mod,
    )

    # The helper's relative import `from .domain_coordinators.hvac_zones ...`
    # needs a package context. Re-exec into a package-flavoured namespace.
    ns["__package__"] = "custom_components.universal_room_automation"

    _run(ns["_seed_hvac_zone_kwh_thresholds_from_restore"](hass=object(), hvac=hvac))

    # zone_1 restored to 1.30 (operator value); zone_2 stays at default
    # (0.8) because the restored state was non-numeric.
    assert zones["zone_1"].kwh_rate_threshold == 1.30
    assert zones["zone_2"].kwh_rate_threshold == 0.8


def test_zone_seed_noop_when_zones_empty(monkeypatch):
    ns = _load_zone_seed_helper()
    hvac = _StubHVACForZone({})
    # Even if the imports would succeed, empty zones exits early.
    _run(ns["_seed_hvac_zone_kwh_thresholds_from_restore"](hass=object(), hvac=hvac))
    # No exception, no side-effect — this is the pre-async_start / no-AC-zones
    # posture.
