"""v5.21.0 fix-up (MED-A1) — BAEC config-flow round-trip tests.

Operator scope change 2026-07-17: the standalone `coordinator_baec` step
was folded into `async_step_coordinator_energy` as sibling `baec` +
`baec_advanced` sections. These tests:

  1. Drive `async_step_coordinator_energy` with a user_input carrying
     both BAEC sections. Assert the flat `energy_dp_*` keys land in
     `entry.options` with NO `baec` / `baec_advanced` residue.
  2. Assert every setter-backed BAEC key lands on the coordinator via
     `_EC_SETTER_DISPATCH` (round-trip proof).
  3. Assert pre-existing sibling-section keys (`inclement_advanced`,
     `cloud_verification`) in options are preserved when the operator
     submits ONLY BAEC changes (no clobber on merge).
  4. Fresh-install case: empty options → defaults ship OFF.

We piggyback on the `test_cycle_b_config_flow._load_config_flow` HA-mock
harness to compile config_flow without a live HA install.
"""

from __future__ import annotations

import importlib

_cbcf = importlib.import_module("test_cycle_b_config_flow")

UniversalRoomAutomationOptionsFlow = _cbcf.UniversalRoomAutomationOptionsFlow
_make_options_flow = _cbcf._make_options_flow
_FakeConfigEntry = _cbcf._FakeConfigEntry


import asyncio
import contextlib
import sys
import types


@contextlib.contextmanager
def _ha_mocks_injected():
    """Re-inject the HA-mock module tree AND a bare URA package stub
    for the DURATION of the async step. Runtime imports inside
    `async_step_coordinator_energy` (e.g. `from homeassistant.data_entry_flow
    import section` and `from .domain_coordinators.energy_const import ...`)
    fail otherwise because the harness restored sys.modules after compile
    and the URA package would otherwise attempt its full `__init__.py`
    (which pulls the real coordinator + HA).
    """
    import os
    ha_modules = _cbcf._build_ha_modules()
    # The harness's default `section` mock accepts only positional `opts`;
    # cloud_verification uses the `options=` kwarg. Patch to accept both.
    ha_modules["homeassistant.data_entry_flow"].section = (
        lambda schema, opts=None, **_kw: schema
    )

    _pkg = "custom_components.universal_room_automation"
    _COMPONENT_DIR = _cbcf._COMPONENT_DIR

    saved: dict = {}
    to_track = list(ha_modules.keys()) + [
        "custom_components", _pkg, f"{_pkg}.domain_coordinators",
    ]
    for name in to_track:
        if name in sys.modules:
            saved[name] = sys.modules[name]

    try:
        sys.modules.update(ha_modules)

        # Bare `custom_components` + URA package stub (no __init__ exec)
        # so `from .domain_coordinators.energy_const import ...` resolves
        # via package __path__ without executing the real URA __init__.py
        # (which imports `homeassistant.helpers.dispatcher` etc.).
        cc = types.ModuleType("custom_components")
        cc.__path__ = [os.path.join(_cbcf._REPO_ROOT, "custom_components")]
        sys.modules["custom_components"] = cc

        ura = types.ModuleType(_pkg)
        ura.__path__ = [_COMPONENT_DIR]
        ura.__package__ = _pkg
        sys.modules[_pkg] = ura

        dc = types.ModuleType(f"{_pkg}.domain_coordinators")
        dc.__path__ = [os.path.join(_COMPONENT_DIR, "domain_coordinators")]
        dc.__package__ = f"{_pkg}.domain_coordinators"
        sys.modules[f"{_pkg}.domain_coordinators"] = dc

        yield
    finally:
        for name in to_track:
            if name in saved:
                sys.modules[name] = saved[name]
            else:
                sys.modules.pop(name, None)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# BAEC key names (must match energy_const.py — production surface).
KEY_ENABLE = "energy_dp_enable"
KEY_MUST_START = "energy_dp_must_start_by_min"
KEY_EVAL_DELAY = "energy_dp_eval_delay_min"
KEY_MARGIN = "energy_dp_margin_min"
KEY_KWH_A = "energy_dp_needed_kwh_garage_a"
KEY_KWH_B = "energy_dp_needed_kwh_garage_b"
KEY_HLS = "energy_dp_house_load_source"


# ---------------------------------------------------------------------------
# 1 + 2 + 3: flatten-on-save + preserve-siblings on BAEC-only submission
# ---------------------------------------------------------------------------


def test_energy_step_flattens_baec_sections_and_preserves_siblings():
    """BAEC sections flatten to flat keys, siblings preserved."""
    # Seed options with pre-existing sibling-section keys (already flat, as
    # the inclement/cloud_verification flatten-on-save handlers have run
    # before). BAEC keys start unset.
    seed_options = {
        # Sibling: inclement_advanced (already flat)
        "inclement_partial_hold_reserve_floor": 50,
        # Sibling: cloud_verification (already flat)
        "energy_cloud_reserve_oracle_entity": "number.cloud_reserve",
        # A completely unrelated top-level key
        "energy_envoy_entity": "sensor.envoy",
    }
    flow = _make_options_flow(options=dict(seed_options))

    # Simulate a form submission carrying the two BAEC sections (as HA
    # delivers them) plus one un-nested top-level unrelated key.
    user_input = {
        # Envoy field intentionally omitted so the step's envoy validator
        # short-circuits (`submitted_envoy = ""`); we're testing flatten,
        # not envoy validation.
        "cloud_verification": {
            # v5.21.0 fix-up (SECOND OPERATOR ADDITION 2026-07-17) — D2
            # knobs live in this section alongside the oracle entities.
            "energy_soc_divergence_threshold_pp": 8,
            "energy_soc_divergence_dwell_min": 3,
            "energy_cloud_lag_alert_s": 900,
        },
        "baec": {
            KEY_ENABLE: True,
            KEY_MUST_START: 240,
        },
        "baec_advanced": {
            KEY_EVAL_DELAY: 10,
            KEY_MARGIN: 45,
            KEY_KWH_A: 20.0,
            KEY_KWH_B: 25.0,
            KEY_HLS: "live_span",
        },
    }
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input=user_input))

    # We expect create_entry (no envoy validation errors since we didn't
    # submit CONF_ENERGY_ENVOY_ENTITY as a new-value; passing the same
    # value should validate cleanly OR skip validation).
    assert result["type"] == "create_entry", result
    saved = result["data"]

    # (1) Flat energy_dp_* keys present with values from BOTH sections.
    assert saved[KEY_ENABLE] is True
    assert saved[KEY_MUST_START] == 240
    assert saved[KEY_EVAL_DELAY] == 10
    assert saved[KEY_MARGIN] == 45
    assert saved[KEY_KWH_A] == 20.0
    assert saved[KEY_KWH_B] == 25.0
    assert saved[KEY_HLS] == "live_span"

    # (2) NO section-nested residue.
    assert "baec" not in saved
    assert "baec_advanced" not in saved

    # (3) Siblings preserved.
    assert saved["inclement_partial_hold_reserve_floor"] == 50
    assert saved["energy_cloud_reserve_oracle_entity"] == "number.cloud_reserve"
    assert saved["energy_envoy_entity"] == "sensor.envoy"
    # cloud_verification section itself is popped (flattened).
    assert "cloud_verification" not in saved
    # D2 knob promotions land as flat top-level keys.
    assert saved["energy_soc_divergence_threshold_pp"] == 8
    assert saved["energy_soc_divergence_dwell_min"] == 3
    assert saved["energy_cloud_lag_alert_s"] == 900


# ---------------------------------------------------------------------------
# 2: setter round-trip via _EC_SETTER_DISPATCH
# ---------------------------------------------------------------------------


def test_setter_dispatch_routes_every_baec_key_to_coord():
    """Every BAEC key in `_EC_SETTER_DISPATCH` names an existing setter on
    the Energy Coordinator, and the enable key is included (post-fix)."""
    # Read the dispatch table by grepping the source — avoids importing
    # __init__.py (which pulls a full HA stack).
    import os
    _here = os.path.dirname(__file__)
    init_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "__init__.py",
    ))
    src = open(init_py).read()
    # Pull the dispatch block.
    start = src.index("_EC_SETTER_DISPATCH")
    end = src.index("}", start)
    block = src[start:end]

    # B-HIGH-1: enable key now dispatches.
    assert "_CONF_ENERGY_DP_ENABLE" in block
    assert '"set_dp_enabled"' in block

    # Every dp_* key in the block routes to a setter on EnergyCoordinator.
    for setter_name in (
        "set_dp_enabled", "set_dp_eval_delay_min", "set_dp_margin_min",
        "set_dp_must_start_by_min", "set_dp_needed_kwh_garage_a",
        "set_dp_needed_kwh_garage_b", "set_dp_house_load_source",
    ):
        assert f'"{setter_name}"' in block, setter_name

    # And each such setter exists in energy.py.
    energy_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    ))
    esrc = open(energy_py).read()
    for setter_name in (
        "set_dp_enabled", "set_dp_eval_delay_min", "set_dp_margin_min",
        "set_dp_must_start_by_min", "set_dp_needed_kwh_garage_a",
        "set_dp_needed_kwh_garage_b", "set_dp_house_load_source",
    ):
        assert f"def {setter_name}(" in esrc, setter_name


def test_dp_enable_removed_from_no_live_attr_keys():
    """B-HIGH-1: enable key is NOT in `_NO_LIVE_ATTR_KEYS` (was the bug)."""
    import os
    _here = os.path.dirname(__file__)
    init_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "__init__.py",
    ))
    src = open(init_py).read()
    start = src.index("_NO_LIVE_ATTR_KEYS")
    end = src.index("})", start)
    block = src[start:end]
    # Strip out comment lines so the historical mention (comment) doesn't
    # false-positive; membership check must be against the live tokens only.
    live = "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "_CONF_ENERGY_DP_ENABLE" not in live


# ---------------------------------------------------------------------------
# 4: fresh install → defaults ship OFF (no BAEC keys in options)
# ---------------------------------------------------------------------------


def test_fresh_install_default_off_ships_baec_disabled():
    """Fresh install: submitting the step with EMPTY baec sections
    persists no enable-True → BAEC ships OFF. Also verifies the source
    default sentinel (`CONF_DP_ENABLE` in energy_const.py) is False so
    a bare form submission leaves the coord `_dp_enabled` False.
    """
    # Source-level default: CONF_DP_ENABLE is the ship-OFF sentinel.
    import os
    _here = os.path.dirname(__file__)
    ec_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy_const.py",
    ))
    esrc = open(ec_py).read()
    # Find "CONF_DP_ENABLE = <val>" (module-constant default). Must be False.
    import re as _re
    m = _re.search(r"^CONF_DP_ENABLE\s*[:=][^\n]*=\s*(False|True)",
                   esrc, _re.MULTILINE)
    assert m is not None, "CONF_DP_ENABLE default sentinel not found"
    assert m.group(1) == "False", (
        "BAEC must ship OFF by default (fresh install). "
        f"Found CONF_DP_ENABLE = {m.group(1)}"
    )

    # Behavioral: submit with empty baec sections → flatten leaves no
    # energy_dp_enable set, so options fall through to the default.
    flow = _make_options_flow(options={})
    user_input = {"baec": {}, "baec_advanced": {}}
    with _ha_mocks_injected():
        result = _run(flow.async_step_coordinator_energy(user_input=user_input))
    assert result["type"] == "create_entry", result
    saved = result["data"]
    assert KEY_ENABLE not in saved  # nothing to persist → default (OFF)
    assert "baec" not in saved
    assert "baec_advanced" not in saved


# ---------------------------------------------------------------------------
# CM menu: standalone entry retired
# ---------------------------------------------------------------------------


def test_d2_setter_dispatch_registrations_and_setters_exist():
    """D2 detection keys wired through `_EC_SETTER_DISPATCH` +
    `OPTIONS_RELOAD_SUPPRESS_KEYS`; setters exist on EnergyCoordinator."""
    import os
    _here = os.path.dirname(__file__)
    init_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "__init__.py",
    ))
    src = open(init_py).read()
    disp_start = src.index("_EC_SETTER_DISPATCH")
    disp_end = src.index("}", disp_start)
    disp = src[disp_start:disp_end]
    for key_alias, setter in (
        ("_CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP", "set_soc_divergence_threshold_pp"),
        ("_CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN", "set_soc_divergence_dwell_min"),
        ("_CONF_ENERGY_CLOUD_LAG_ALERT_S", "set_cloud_lag_alert_s"),
    ):
        assert key_alias in disp, key_alias
        assert f'"{setter}"' in disp, setter

    supp_start = src.index("OPTIONS_RELOAD_SUPPRESS_KEYS")
    supp_end = src.index("})", supp_start)
    supp = src[supp_start:supp_end]
    for key_alias in (
        "_CONF_ENERGY_SOC_DIVERGENCE_THRESHOLD_PP",
        "_CONF_ENERGY_SOC_DIVERGENCE_DWELL_MIN",
        "_CONF_ENERGY_CLOUD_LAG_ALERT_S",
    ):
        assert key_alias in supp, key_alias

    energy_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators", "energy.py",
    ))
    esrc = open(energy_py).read()
    for setter in (
        "set_soc_divergence_threshold_pp",
        "set_soc_divergence_dwell_min",
        "set_cloud_lag_alert_s",
    ):
        assert f"def {setter}(" in esrc, setter


def test_d2_soc_divergence_kill_switch_via_options_backed_attr():
    """Drive the real `_evaluate_soc_divergence` method with an active
    divergence alert, then flip the options-backed attr to 0. The
    kill-switch path MUST clear the active alert (and the timers/deltas).

    This exercises the read-site migration end-to-end: the method reads
    `getattr(self, '_soc_divergence_threshold_pp', CONF_SOC_DIVERGENCE_THRESHOLD_PP)`
    — with the attr set to 0, the kill-switch branch fires regardless
    of the module constant.
    """
    import os
    import sys as _sys
    import types as _types
    from unittest.mock import MagicMock

    # We only need the method body; extract it into a lightweight test
    # namespace with the imports it uses.
    _here = os.path.dirname(__file__)
    eb_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "domain_coordinators",
        "energy_battery.py",
    ))
    src = open(eb_py).read()
    marker = "def _evaluate_soc_divergence("
    start = src.index(marker)
    # Grab from `def` through end of body — find the next top-level def.
    next_def = src.index("\n    def _evaluate_cloud_settings_lag(", start)
    method_src = src[start:next_def]
    # Dedent the method (leading 4 spaces) so we can exec at module scope.
    method_src = "\n".join(
        (ln[4:] if ln.startswith("    ") else ln)
        for ln in method_src.splitlines()
    )

    # Stub minimal imports the method body needs.
    fake_util = _types.ModuleType("homeassistant.util")
    fake_dt = _types.ModuleType("homeassistant.util.dt")
    from datetime import datetime, timezone
    fake_dt.utcnow = lambda: datetime.now(timezone.utc)
    fake_util.dt = fake_dt
    fake_ha = _types.ModuleType("homeassistant")
    fake_ha.util = fake_util
    saved = {
        n: _sys.modules.get(n)
        for n in ("homeassistant", "homeassistant.util", "homeassistant.util.dt")
    }
    _sys.modules["homeassistant"] = fake_ha
    _sys.modules["homeassistant.util"] = fake_util
    _sys.modules["homeassistant.util.dt"] = fake_dt
    try:
        # Provide a mock `.energy_const` import path for the method's
        # relative `from .energy_const import ...` — since we're exec'ing
        # standalone, patch by pre-loading a stub module under the
        # expected package name.
        pkg_name = "custom_components.universal_room_automation.domain_coordinators"
        # If the real one isn't loaded, load it directly.
        if pkg_name + ".energy_const" not in _sys.modules:
            import importlib.util as _iu
            ec_path = os.path.abspath(os.path.join(
                _here, "..", "..", "custom_components",
                "universal_room_automation", "domain_coordinators",
                "energy_const.py",
            ))
            # Package scaffolding
            for _p, _pth in [
                ("custom_components", os.path.abspath(os.path.join(
                    _here, "..", "..", "custom_components"))),
                ("custom_components.universal_room_automation", os.path.abspath(os.path.join(
                    _here, "..", "..", "custom_components",
                    "universal_room_automation"))),
                (pkg_name, os.path.abspath(os.path.join(
                    _here, "..", "..", "custom_components",
                    "universal_room_automation", "domain_coordinators"))),
            ]:
                if _p not in _sys.modules:
                    m = _types.ModuleType(_p)
                    m.__path__ = [_pth]
                    _sys.modules[_p] = m
            spec = _iu.spec_from_file_location(pkg_name + ".energy_const", ec_path)
            m = _iu.module_from_spec(spec)
            _sys.modules[pkg_name + ".energy_const"] = m
            spec.loader.exec_module(m)

        ns: dict = {"_LOGGER": MagicMock(), "Any": object}
        # The method uses `.energy_const` relative import; patch to
        # absolute by prefixing the exec-namespace's __package__.
        ns["__package__"] = pkg_name
        method_src_rewritten = method_src.replace(
            "from .energy_const import",
            f"from {pkg_name}.energy_const import",
        )
        exec(compile(method_src_rewritten, "<eval_soc_div>", "exec"), ns)
        _evaluate = ns["_evaluate_soc_divergence"]

        # Build a fake `self` with the fields the method touches.
        class _Fake:
            _d2_soc_div_above_first_at = None
            _d2_soc_div_below_first_at = None
            _d2_soc_div_last_delta = None
            _d2_soc_div_active = True   # simulate a standing active alert
            _soc_source_last = "envoy"
            _d2_soc_div_nm_date = None

            def __init__(self):
                pass

            def _read_cloud_soc_snapshot(self, now):
                return (60.0, 1.0)  # cloud SOC, age s

            def _fire_d2_nm(self, **kw):
                pass

        fake = _Fake()
        # PROMOTE via options-backed attr: kill-switch = 0.
        fake._soc_divergence_threshold_pp = 0

        # Run the method with a large real divergence (would fire if
        # detection weren't killed).
        _evaluate(fake, primary_soc=45.0, now=None)

        # Kill-switch invariant: active cleared, timers reset, delta reset.
        assert fake._d2_soc_div_active is False
        assert fake._d2_soc_div_above_first_at is None
        assert fake._d2_soc_div_below_first_at is None
        assert fake._d2_soc_div_last_delta is None
    finally:
        for n, v in saved.items():
            if v is None:
                _sys.modules.pop(n, None)
            else:
                _sys.modules[n] = v


def test_cm_menu_does_not_reference_coordinator_baec():
    """Operator scope change: `coordinator_baec` removed from CM menu."""
    import os
    _here = os.path.dirname(__file__)
    cf_py = os.path.abspath(os.path.join(
        _here, "..", "..", "custom_components",
        "universal_room_automation", "config_flow.py",
    ))
    src = open(cf_py).read()
    # No live menu entry.
    assert '"coordinator_baec",\n' not in src
    # And no active `async_step_coordinator_baec` method.
    assert "async def async_step_coordinator_baec(" not in src
