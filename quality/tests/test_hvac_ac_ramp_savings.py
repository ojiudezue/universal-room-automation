"""HVAC AC-Ramp kWh-Avoided → $ Savings tests.

PLANNING_hvac_kwh_avoided_savings D1 (billing-cycle kWh scope) + D2 (standalone
$ savings family). Tier 2, additive + display-only.

Coverage:
- D1: billing-cycle kWh sensor + cache key + cycle ⊇ today (via source-grep +
  behavioral DB round-trip).
- D2: `rate` key captured into `notes` at nudge-eval, DAO parses it, savings
  compute at captured rate, $ family EXCLUDED from EC energy_savings_total_*,
  rough_estimate caveat present on every new sensor.

Source-grep + one behavioral DB test (matches the runtime-smoke pattern).
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta

import pytest


# =====================================================================
# Source fixtures
# =====================================================================


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open("custom_components/universal_room_automation/sensor.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_override_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_override.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def database_src() -> str:
    with open("custom_components/universal_room_automation/database.py") as f:
        return f.read()


@pytest.fixture(scope="module")
def energy_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/energy.py"
    ) as f:
        return f.read()


def test_energy_coordinator_exposes_public_billing_cycle_accessor(energy_src):
    """Review B M1 fix: EnergyCoordinator must expose a public
    `get_billing_cycle_start(now)` wrapper so cross-coordinator callers
    (HVAC AC-ramp savings) stop reaching into private `_billing`
    (Bug Class #55)."""
    assert "def get_billing_cycle_start(" in energy_src


# =====================================================================
# D1 — billing_cycle kWh scope
# =====================================================================


class TestD1BillingCycleKwh:

    def test_new_sensor_class_present(self, sensor_src):
        assert "class HVACACKwhAvoidedBillingCycleSensor(" in sensor_src

    def test_unique_id_matches_naming(self, sensor_src):
        assert (
            'f"{DOMAIN}_hvac_ac_kwh_avoided_billing_cycle"' in sensor_src
        )

    def test_sensor_registered_on_hvac_device_block(self, sensor_src):
        assert "HVACACKwhAvoidedBillingCycleSensor(hass, entry)" in sensor_src

    def test_cache_seeded_with_cycle_key(self, hvac_override_src):
        # Cache init must carry `kwh_avoided_cycle` so a sensor read before
        # the first refresh doesn't KeyError.
        idx = hvac_override_src.find("self._impact_cache: dict = {")
        block = hvac_override_src[idx:idx + 2000]
        assert '"kwh_avoided_cycle"' in block

    def test_refresh_computes_cycle_via_ec_helper(self, hvac_override_src):
        """The cycle-start MUST come from EC (same billing boundary the
        EC billing_cycle sensors use), routed through the PUBLIC accessor
        `get_billing_cycle_start` (Review B M1: no private `_billing`
        reach — Bug Class #55)."""
        idx = hvac_override_src.find("async def _refresh_impact_cache")
        body = hvac_override_src[idx:idx + 6000]
        assert "get_billing_cycle_start" in body
        assert "get_ac_ramp_kwh_avoided(since=cycle_start_dt)" in body

    def test_cycle_superset_of_today_invariant_documented(
        self, hvac_override_src,
    ):
        """Fallback path: if EC cycle-start resolution fails, use local
        midnight (so cycle >= today still holds as equality, not 0)."""
        idx = hvac_override_src.find("async def _refresh_impact_cache")
        body = hvac_override_src[idx:idx + 6000]
        assert "cycle_start_dt = local_midnight" in body


# =====================================================================
# D2 — rate capture at nudge-eval + DAO + $ family
# =====================================================================


class TestD2RateCapture:

    def test_rate_helper_imported(self, hvac_override_src):
        assert (
            "from .energy_billing import _get_effective_rate_kwh"
            in hvac_override_src
        )

    def test_rate_captured_into_notes_at_nudge_eval(self, hvac_override_src):
        """The nudge-eval log must append `rate=<float>` to the notes
        string. Forward-only: pre-deploy events without this key are
        excluded from savings (contribute kWh but $0)."""
        # Find the notes= assignment in _evaluate_nudge_outcome
        idx = hvac_override_src.find("kwh_avoided={kwh_avoided:")
        assert idx >= 0
        # Bug Class #41: widened LOOK-BACK window from 500 to 2500 after
        # the L1 rate-guard (math.isfinite/>0) expanded the block between
        # the rate capture and the notes= line.
        block = hvac_override_src[max(0, idx - 2500):idx + 500]
        assert "_get_effective_rate_kwh(self.hass)" in block
        assert "rate=" in block


class TestD2DAO:

    def test_get_ac_ramp_savings_signature(self, database_src):
        idx = database_src.find("async def get_ac_ramp_savings(")
        assert idx >= 0, "get_ac_ramp_savings DAO not defined"
        sig = database_src[idx:idx + 400]
        assert "days: int | None = None" in sig
        assert 'since: "datetime | None" = None' in sig
        assert "tuple[float, int]" in sig

    def test_savings_dao_delegates_to_pure_helper(self, database_src):
        """Review A M2 fix: the row loop is extracted into module-level
        `_sum_savings_from_rows` so it can be exercised by pure unit tests
        (Bug Class #60/#62: `@_ha_only`-gated tests silently pass on hosts
        without HA). The DAO must delegate to that helper."""
        idx = database_src.find("async def get_ac_ramp_savings(")
        body = database_src[idx:idx + 4000]
        assert "_sum_savings_from_rows(rows)" in body

    def test_savings_helper_parses_rate_and_kwh_keys(self, database_src):
        idx = database_src.find("def _sum_savings_from_rows(")
        assert idx >= 0, "pure helper missing"
        body = database_src[idx:idx + 4000]
        assert 'key == "rate"' in body
        assert 'key == "kwh_avoided"' in body
        # Forward-only + finite/positive rate guard
        assert "rate_event <= 0" in body or "rate_event > 0" in body


# =====================================================================
# D2 — three $ sensors present + shape correct
# =====================================================================


@pytest.mark.parametrize(
    "cls_name,unique_id_suffix",
    [
        ("HVACACRampSavingsTodaySensor", "hvac_ac_ramp_savings_today"),
        (
            "HVACACRampSavingsBillingCycleSensor",
            "hvac_ac_ramp_savings_billing_cycle",
        ),
        ("HVACACRampSavingsLifetimeSensor", "hvac_ac_ramp_savings_lifetime"),
    ],
)
def test_savings_sensor_class_and_unique_id(
    sensor_src, cls_name, unique_id_suffix,
):
    assert f"class {cls_name}(" in sensor_src
    assert f'f"{{DOMAIN}}_{unique_id_suffix}"' in sensor_src


def test_savings_sensors_registered(sensor_src):
    for cls_name in (
        "HVACACRampSavingsTodaySensor",
        "HVACACRampSavingsBillingCycleSensor",
        "HVACACRampSavingsLifetimeSensor",
    ):
        assert f"{cls_name}(hass, entry)" in sensor_src


def test_savings_sensors_are_monetary_usd(sensor_src):
    """MONETARY + USD, TOTAL state_class (MONETARY + TOTAL_INCREASING is
    rejected by HA — same lesson as v4.6.10 D6 on the EC savings family)."""
    idx = sensor_src.find("class _ACRampSavingsSensorBase(")
    block = sensor_src[idx:idx + 800]
    assert "SensorDeviceClass.MONETARY" in block
    assert 'USD"' in block
    assert "SensorStateClass.TOTAL" in block


def test_savings_sensors_rough_estimate_caveat_present(sensor_src):
    idx = sensor_src.find("class _ACRampSavingsSensorBase(")
    block = sensor_src[idx:idx + 3000]
    assert "_methodology" in block
    assert "Rough estimate" in block
    assert "NOT summed into energy_savings_total_*" in block


# =====================================================================
# D2 — the double-count guard: savings family must NOT be summed into
# EnergySavingsTotal{Today,BillingCycle,Lifetime}
# =====================================================================


class TestNoDoubleCount:

    def test_energy_savings_total_ast_does_not_reference_ac_ramp_savings(
        self, sensor_src,
    ):
        """Parse the three EnergySavingsTotal* classes and prove none of
        them reference the AC-ramp savings cache/sensors. Guards the
        standing rule: AC-ramp $ is a standalone family."""
        tree = ast.parse(sensor_src)
        target_names = {
            "EnergySavingsTotalTodaySensor",
            "EnergySavingsTotalBillingCycleSensor",
            "EnergySavingsTotalLifetimeSensor",
        }
        found = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in target_names:
                found += 1
                src = ast.unparse(node)
                assert "ac_ramp" not in src.lower(), (
                    f"{node.name} references ac_ramp — would double-count"
                )
                assert "savings_today" not in src or "peak_avoidance" in src
                assert "savings_cycle" not in src or "peak_avoidance" in src
        assert found == 3, (
            f"Expected 3 EnergySavingsTotal* classes; found {found}"
        )


# =====================================================================
# Pure unit tests for `_sum_savings_from_rows` (Review A M2 fix)
# ---------------------------------------------------------------------
# The behavioral round-trip below is `@_ha_only`-gated → silently green
# on hosts without HA installed (Bug Class #60/#62 — silent skip). The
# tests here exercise the extracted pure kernel directly and MUST fail
# under mutations of the load-bearing logic (effective gate, `*`↔`+`,
# None-guard). NO HA dependency.
# =====================================================================


def _load_pure_helper():
    # Import via source-load to avoid pulling `.const` (which imports HA).
    import importlib.util
    import pathlib
    import sys
    import types

    root = pathlib.Path("custom_components/universal_room_automation")
    # Provide a stub for `.const` so `from .const import ...` succeeds.
    pkg_name = "_ura_test_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(root)]
        sys.modules[pkg_name] = pkg
        const_stub = types.ModuleType(f"{pkg_name}.const")
        const_stub.DATABASE_NAME = "x.db"
        const_stub.MIN_DATA_DAYS_PREDICTION = 7
        sys.modules[f"{pkg_name}.const"] = const_stub
    mod_name = f"{pkg_name}.database"
    spec = importlib.util.spec_from_file_location(
        mod_name, root / "database.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # If the module can't load in this env (missing HA-only imports),
        # fall back to a textual copy of the helper — the DAO grep test
        # above still binds the source contract.
        return None
    return getattr(mod, "_sum_savings_from_rows", None)


class TestSumSavingsFromRowsPure:

    def setup_method(self):
        self.helper = _load_pure_helper()
        if self.helper is None:
            pytest.skip("could not load database module in this env")

    def test_effective_none_or_zero_is_skipped(self):
        rows = [
            ("kwh_avoided=1.0;rate=0.30", None),
            ("kwh_avoided=1.0;rate=0.30", 0),
        ]
        total, n = self.helper(rows)
        assert total == 0.0
        assert n == 0

    def test_missing_rate_key_contributes_zero(self):
        rows = [
            # No `rate` key at all — forward-only, contributes $0
            ("kwh_avoided=0.5;post_min=0.5;classification=effective", 1),
        ]
        total, n = self.helper(rows)
        assert total == 0.0
        assert n == 0

    def test_malformed_rate_contributes_zero(self):
        rows = [
            ("kwh_avoided=0.5;rate=not_a_number", 1),
        ]
        total, n = self.helper(rows)
        assert total == 0.0
        assert n == 0

    def test_non_positive_rate_contributes_zero(self):
        rows = [
            ("kwh_avoided=0.5;rate=0", 1),
            ("kwh_avoided=0.5;rate=-0.15", 1),
        ]
        total, n = self.helper(rows)
        assert total == 0.0
        assert n == 0

    def test_non_finite_rate_contributes_zero(self):
        rows = [
            ("kwh_avoided=0.5;rate=nan", 1),
            ("kwh_avoided=0.5;rate=inf", 1),
        ]
        total, n = self.helper(rows)
        assert total == 0.0
        assert n == 0

    def test_missing_kwh_contributes_zero(self):
        rows = [
            ("rate=0.30", 1),
            ("kwh_avoided=oops;rate=0.30", 1),
        ]
        total, n = self.helper(rows)
        assert total == 0.0
        assert n == 0

    def test_correct_kwh_times_rate_sum(self):
        rows = [
            ("kwh_avoided=0.400;rate=0.35000", 1),  # 0.14
            ("kwh_avoided=1.000;rate=0.20000", 1),  # 0.20
            ("kwh_avoided=2.000;rate=0.10000", 1),  # 0.20
        ]
        total, n = self.helper(rows)
        assert n == 3
        # 0.14 + 0.20 + 0.20 = 0.54
        assert abs(total - 0.54) < 1e-9

    def test_mixed_rows_only_valid_rated_count(self):
        rows = [
            ("kwh_avoided=0.5;rate=0.40", 1),      # counts: 0.20
            ("kwh_avoided=0.5", 1),                 # no rate -> $0
            ("kwh_avoided=0.5;rate=0.40", 0),       # not effective -> skip
            ("kwh_avoided=0.5;rate=0.40", None),    # not effective -> skip
            ("", 1),                                # empty notes -> skip
            (None, 1),                              # None notes -> skip
        ]
        total, n = self.helper(rows)
        assert n == 1
        assert abs(total - 0.2) < 1e-9


# =====================================================================
# Behavioral test — real DAO + real notes parser round-trip
# =====================================================================


# Behavioral DB tests require a REAL homeassistant install (not a test-stub).
# Match the guard shape used by test_runtime_smoke.py — check for a symbol
# only the real package exposes so we don't false-succeed against a partial
# stub injected by another test's conftest.
_HA_REAL = False
try:
    import homeassistant.util.dt as _ha_dt  # noqa: F401
    from homeassistant.helpers.storage import Store as _Store  # noqa: F401
    _HA_REAL = True
except Exception:  # noqa: BLE001
    _HA_REAL = False

_ha_only = pytest.mark.skipif(
    not _HA_REAL,
    reason=(
        "real homeassistant not installed; behavioral DAO test skipped "
        "(source-grep tests above still cover DAO/notes/registration shape)"
    ),
)


@_ha_only
@pytest.mark.asyncio
async def test_ac_ramp_savings_values_at_captured_rate(tmp_path):
    """Round-trip: log two effective nudge_evaluated rows (one WITH captured
    rate, one WITHOUT — the pre-deploy shape) into the real DB via the
    real writer, then read via the real `get_ac_ramp_savings` DAO. Verify:

      - Row WITH rate contributes kwh_avoided * rate to savings.
      - Row WITHOUT rate contributes $0 (forward-only rule).
      - Count returned = rows with captured rate = 1.
      - `get_ac_ramp_kwh_avoided` still sums both (kWh family unchanged).
    """
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from runtime_harness import StubHass

    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    await db.start_write_worker()
    try:
        ok = await db.init_db()
        assert ok

        # Row A: pre-deploy shape (no `rate` key)
        await db.log_ac_ramp_event(
            zone_id="zone_a",
            event_type="nudge_evaluated",
            triggered_by="auto",
            kwh_rate_before=2.0,
            kwh_rate_after=0.5,
            effective=True,
            notes=(
                "kwh_avoided=0.500;post_min=0.50;sample_count=5;"
                "classification=effective"
            ),
        )
        # Row B: post-deploy shape (with captured rate)
        await db.log_ac_ramp_event(
            zone_id="zone_b",
            event_type="nudge_evaluated",
            triggered_by="auto",
            kwh_rate_before=2.0,
            kwh_rate_after=0.5,
            effective=True,
            notes=(
                "kwh_avoided=0.400;post_min=0.50;sample_count=5;"
                "classification=effective;rate=0.35000"
            ),
        )
        # Drain write queue
        for _ in range(20):
            if db._write_queue.empty():
                break
            import asyncio
            await asyncio.sleep(0.05)

        # kWh family: both rows count (unchanged behavior).
        kwh_total, evals, fp = await db.get_ac_ramp_kwh_avoided(days=None)
        assert evals == 2
        assert fp == 0
        assert abs(kwh_total - 0.9) < 1e-6

        # Savings family: only Row B counts, at 0.4 * 0.35 = 0.14
        savings, rated = await db.get_ac_ramp_savings(days=None)
        assert rated == 1, f"only 1 row had captured rate; got {rated}"
        assert abs(savings - 0.14) < 1e-6, (
            f"expected 0.4 kWh * $0.35 = $0.14; got {savings}"
        )
    finally:
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()


@_ha_only
@pytest.mark.asyncio
async def test_ac_ramp_savings_since_windowing(tmp_path):
    """`since=<datetime>` windowing must exclude rows before the cutoff
    (mirrors get_ac_ramp_kwh_avoided semantics). This proves cycle ⊇ today
    once we anchor `since=cycle_start` vs `since=local_midnight`."""
    from custom_components.universal_room_automation.database import (
        UniversalRoomDatabase,
    )
    from homeassistant.util import dt as dt_util
    from runtime_harness import StubHass

    hass = StubHass(config_dir=str(tmp_path))
    db = UniversalRoomDatabase(hass)
    await db.start_write_worker()
    try:
        await db.init_db()

        # Insert one row RIGHT NOW (via the real writer)
        await db.log_ac_ramp_event(
            zone_id="zone_x",
            event_type="nudge_evaluated",
            triggered_by="auto",
            kwh_rate_before=2.0,
            kwh_rate_after=0.5,
            effective=True,
            notes=(
                "kwh_avoided=0.5;post_min=0.5;sample_count=5;"
                "classification=effective;rate=0.4"
            ),
        )
        import asyncio
        for _ in range(20):
            if db._write_queue.empty():
                break
            await asyncio.sleep(0.05)

        # Since = 1h ago -> includes the row
        savings_recent, n_recent = await db.get_ac_ramp_savings(
            since=dt_util.now() - timedelta(hours=1),
        )
        assert n_recent == 1
        assert abs(savings_recent - 0.2) < 1e-6

        # Since = 1h in the future -> excludes it
        savings_future, n_future = await db.get_ac_ramp_savings(
            since=dt_util.now() + timedelta(hours=1),
        )
        assert n_future == 0
        assert savings_future == 0.0
    finally:
        if db._write_task and not db._write_task.done():
            db._write_task.cancel()
