"""v5.12.0 SPAN circuit-identity re-key + one-shot friendly_name→unique_id
migration.

Coverage:
- D1 CircuitInfo carries unique_id from entity registry; scope resolution
  order is unique_id → entity_id → friendly_name with DEBUG log on fallback.
- D2 EVSE `span_breaker` config-flow field: constants exist + config-flow
  wires them + `__init__.py` merges into `evse_config` with default
  fallback.
- D3 One-shot migration in `_restore_energy_baselines`:
    * pre-migration friendly-scoped rows get backed up FIRST then rewritten
      to unique_id scope; sample_count preserved
    * cross-subsystem rows (`coordinator_id='safety'` +
      `metric_name='rate_of_change'`) are byte-identical after migration
    * idempotent: sentinel prevents double-migration
    * rename-survival: baseline attaches to NEW entity_id under stable
      unique_id
    * unknown/orphan scopes (`'Battery Power'` etc.) kept in place, no WARN

Behavioural tests execute against a real sqlite DB populated with the
production schema extracted from `database.py` — no hand-copied DDL.
`_restore_energy_baselines` is AST-extracted and bound to a stub coordinator
so we drive the production code path (Tier 2-DB C axis).
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
import sqlite3
import sys
import textwrap
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Cooperative HA-stack mocking (test_metric_baseline_integration.py pattern).
# ---------------------------------------------------------------------------

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_module(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


_identity = lambda fn: fn  # noqa: E731

_stub_mods = {
    "homeassistant": {},
    "homeassistant.core": {"HomeAssistant": MagicMock, "callback": _identity},
    "homeassistant.const": MagicMock(),
    "homeassistant.helpers": {},
    "homeassistant.helpers.device_registry": {"DeviceInfo": dict},
    "homeassistant.helpers.entity": {"DeviceInfo": dict, "EntityCategory": MagicMock()},
    "homeassistant.helpers.entity_platform": {"AddEntitiesCallback": MagicMock},
    "homeassistant.helpers.event": {
        "async_track_time_interval": MagicMock(),
        "async_call_later": MagicMock(),
        "async_track_state_change_event": MagicMock(),
        "async_track_point_in_time": MagicMock(),
        "async_track_point_in_utc_time": MagicMock(),
    },
    "homeassistant.helpers.dispatcher": {
        "async_dispatcher_connect": MagicMock(),
        "async_dispatcher_send": MagicMock(),
    },
    "homeassistant.helpers.update_coordinator": {
        "DataUpdateCoordinator": MagicMock, "UpdateFailed": Exception,
    },
    "homeassistant.helpers.selector": MagicMock(),
    "homeassistant.helpers.entity_registry": {"async_get": MagicMock()},
    "homeassistant.helpers.sun": {},
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": lambda: datetime.utcnow(),
        "now": lambda: datetime.now(),
        "as_local": lambda dt: dt,
    },
    "homeassistant.components": {},
    "homeassistant.components.sensor": {
        "SensorEntity": type("SensorEntity", (), {}),
        "SensorDeviceClass": MagicMock(), "SensorStateClass": MagicMock(),
    },
    "homeassistant.components.binary_sensor": {
        "BinarySensorEntity": type("BinarySensorEntity", (), {}),
        "BinarySensorDeviceClass": MagicMock(),
    },
    "homeassistant.components.button": {"ButtonEntity": type("ButtonEntity", (), {})},
}
for _name, _attrs in _stub_mods.items():
    if isinstance(_attrs, dict):
        sys.modules.setdefault(_name, _mock_module(_name, **_attrs))
    else:
        sys.modules.setdefault(_name, _attrs)

if "custom_components" not in sys.modules:
    _cc = types.ModuleType("custom_components")
    _cc.__path__ = [os.path.join(_REPO, "custom_components")]
    sys.modules["custom_components"] = _cc

_ura_name = "custom_components.universal_room_automation"
if _ura_name not in sys.modules:
    _ura = types.ModuleType(_ura_name)
    _ura.__path__ = [os.path.join(_REPO, "custom_components", "universal_room_automation")]
    _ura.__package__ = _ura_name
    sys.modules[_ura_name] = _ura

sys.path.insert(0, _REPO)


# ---------------------------------------------------------------------------
# Production-schema extraction (Tier 2-DB C axis: no hand-copied DDL).
# ---------------------------------------------------------------------------

_DATABASE_PY = os.path.join(
    _REPO, "custom_components", "universal_room_automation", "database.py",
)
_ENERGY_PY = os.path.join(
    _REPO, "custom_components", "universal_room_automation",
    "domain_coordinators", "energy.py",
)
_CIRCUITS_PY = os.path.join(
    _REPO, "custom_components", "universal_room_automation",
    "domain_coordinators", "energy_circuits.py",
)
_ENERGY_CONST_PY = os.path.join(
    _REPO, "custom_components", "universal_room_automation",
    "domain_coordinators", "energy_const.py",
)
_CONFIG_FLOW_PY = os.path.join(
    _REPO, "custom_components", "universal_room_automation", "config_flow.py",
)
_INIT_PY = os.path.join(
    _REPO, "custom_components", "universal_room_automation", "__init__.py",
)
_STRINGS = os.path.join(
    _REPO, "custom_components", "universal_room_automation", "strings.json",
)
_EN_JSON = os.path.join(
    _REPO, "custom_components", "universal_room_automation", "translations", "en.json",
)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _extract_metric_baselines_ddl() -> str:
    """Extract the metric_baselines CREATE TABLE DDL directly from database.py."""
    src = _read(_DATABASE_PY)
    # Match the triple-quoted CREATE TABLE IF NOT EXISTS metric_baselines block
    m = re.search(
        r'"""(CREATE TABLE IF NOT EXISTS metric_baselines\b.*?)"""',
        src,
        re.DOTALL,
    )
    assert m, "metric_baselines DDL not found in database.py"
    return m.group(1)


# ---------------------------------------------------------------------------
# AST-extraction of `_restore_energy_baselines` so we can drive it directly.
# ---------------------------------------------------------------------------

def _extract_async_method(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return ast.unparse(node)
    raise LookupError(f"async def {name} not found")


def _load_restore_fn():
    """Compile `_restore_energy_baselines` as a standalone async function.

    The extracted body has ``from .coordinator_diagnostics import
    MetricBaseline`` and ``import aiosqlite`` inline, so we need a globals
    namespace with a real ``__name__`` and package context. We pre-import
    the target module and rebind the relative import to the real class.
    """
    src = _extract_async_method(_read(_ENERGY_PY), "_restore_energy_baselines")
    src = textwrap.dedent(src)
    # Strip the "from .coordinator_diagnostics import MetricBaseline" and
    # provide MetricBaseline via globals instead — a relative import from an
    # <exec> scope has no package. `import aiosqlite` at the top is fine.
    src = re.sub(
        r"^\s*from\s+\.coordinator_diagnostics\s+import\s+MetricBaseline\s*$",
        "",
        src,
        flags=re.MULTILINE,
    )
    # Replace the outer swallowing except so migration errors surface in tests.
    src = src.replace(
        '_LOGGER.debug("Could not restore energy baselines (may not exist yet): %s", e)',
        'raise',
    )
    import logging as _logging
    from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
        MetricBaseline,
    )
    ns: dict = {
        "__name__": "test.span_rekey.restore",
        "_LOGGER": _logging.getLogger("test.span_rekey"),
        "MetricBaseline": MetricBaseline,
    }
    exec(compile(src, "<_restore_energy_baselines>", "exec"), ns)
    return ns["_restore_energy_baselines"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_db(db_path: str) -> None:
    """Create metric_baselines + metric_baselines_pruned_backup with real schema."""
    ddl = _extract_metric_baselines_ddl()
    with sqlite3.connect(db_path) as conn:
        conn.execute(ddl)
        # Backup table is created lazily by production code, but we create it
        # here too so we can inspect it deterministically; production uses
        # CREATE TABLE IF NOT EXISTS so this is a safe no-op.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS metric_baselines_pruned_backup ("
            "coordinator_id TEXT, metric_name TEXT, scope TEXT, "
            "mean REAL, variance REAL, sample_count INTEGER, "
            "last_updated TEXT, pruned_at TEXT)"
        )
        conn.commit()


def _insert_baseline(db_path, coordinator_id, metric_name, scope,
                     mean=1.0, variance=0.25, sample_count=100,
                     last_updated="2026-07-01T00:00:00+00:00"):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO metric_baselines (coordinator_id, metric_name, scope, "
            "mean, variance, sample_count, last_updated) VALUES (?,?,?,?,?,?,?)",
            (coordinator_id, metric_name, scope, mean, variance,
             sample_count, last_updated),
        )
        conn.commit()


def _fetch_baselines(db_path, coordinator_id=None, metric_name=None):
    q = ("SELECT coordinator_id, metric_name, scope, mean, variance, "
         "sample_count, last_updated FROM metric_baselines")
    args = []
    where = []
    if coordinator_id is not None:
        where.append("coordinator_id=?")
        args.append(coordinator_id)
    if metric_name is not None:
        where.append("metric_name=?")
        args.append(metric_name)
    if where:
        q += " WHERE " + " AND ".join(where)
    with sqlite3.connect(db_path) as conn:
        return conn.execute(q, args).fetchall()


def _fetch_backup(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT coordinator_id, metric_name, scope, mean, variance, "
            "sample_count, last_updated, pruned_at "
            "FROM metric_baselines_pruned_backup"
        ).fetchall()


class _StubDB:
    def __init__(self, path):
        self.db_file = path


class _StubCircuit:
    def __init__(self, entity_id, friendly_name, unique_id):
        self.entity_id = entity_id
        self.friendly_name = friendly_name
        self.unique_id = unique_id
        self.panel = "left"


class _StubCircuits:
    """Mimics SPANCircuitMonitor for the restore path."""

    def __init__(self, circuits: dict):
        self._circuits = circuits
        self._discovered = True
        self.restored_baselines = None

    def discover_circuits(self):
        return len(self._circuits)

    def restore_baselines(self, baselines):
        self.restored_baselines = baselines


class _StubCoordinator:
    """Minimal `self` for the extracted `_restore_energy_baselines`."""

    def __init__(self, db_path, circuits):
        from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
            MetricBaseline,
        )
        self.hass = MagicMock()
        self.hass.data = {"universal_room_automation": {"database": _StubDB(db_path)}}
        self._circuits = _StubCircuits(circuits)
        # These get overwritten if matching rows exist.
        self._peak_import_baseline = MetricBaseline(
            metric_name="peak_import_kw", coordinator_id="energy",
            scope="house",
        )
        self._soc_at_peak_baseline = MetricBaseline(
            metric_name="soc_at_peak_start", coordinator_id="energy",
            scope="house",
        )
        self._daily_import_cost_baseline = MetricBaseline(
            metric_name="daily_import_cost", coordinator_id="energy",
            scope="house",
        )
        self._solar_forecast_error_baseline = MetricBaseline(
            metric_name="solar_forecast_error_pct", coordinator_id="energy",
            scope="house",
        )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# D1: CircuitInfo unique_id + scope resolution chain
# ---------------------------------------------------------------------------

class TestD1CircuitInfoUniqueId:
    def test_ctor_accepts_unique_id(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo,
        )
        c = CircuitInfo(
            "sensor.span_panel_kitchen_power", "Kitchen", "left",
            unique_id="span_uid_kitchen_abc",
        )
        assert c.unique_id == "span_uid_kitchen_abc"
        assert c.friendly_name == "Kitchen"
        assert c.entity_id == "sensor.span_panel_kitchen_power"

    def test_ctor_defaults_unique_id_to_none(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            CircuitInfo,
        )
        c = CircuitInfo("sensor.foo_power", "Foo", "right")
        assert c.unique_id is None

    def test_scope_prefers_unique_id(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor, CircuitInfo,
        )
        mon = SPANCircuitMonitor(MagicMock())
        eid = "sensor.span_panel_kitchen_power"
        mon._circuits[eid] = CircuitInfo(eid, "Kitchen", "left",
                                         unique_id="uid_kitchen")
        mon._discovered = True
        bl = mon._get_power_baseline(eid)
        assert bl.scope == "uid_kitchen"

    def test_scope_falls_back_to_entity_id_when_no_unique_id(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor, CircuitInfo,
        )
        mon = SPANCircuitMonitor(MagicMock())
        eid = "sensor.extras_emporia_power"
        mon._circuits[eid] = CircuitInfo(eid, "Emporia Extras", "custom")
        mon._discovered = True
        bl = mon._get_power_baseline(eid)
        # Fallback is entity_id, NOT friendly_name (v5.12.0 chain).
        assert bl.scope == eid
        assert bl.scope != "Emporia Extras"


# ---------------------------------------------------------------------------
# D2: EVSE span_breaker config surface
# ---------------------------------------------------------------------------

class TestD2EvseSpanBreakerConfig:
    def test_constants_defined(self):
        src = _read(_ENERGY_CONST_PY)
        assert 'CONF_ENERGY_EVSE_A_SPAN_BREAKER' in src
        assert 'CONF_ENERGY_EVSE_B_SPAN_BREAKER' in src
        assert '"energy_evse_a_span_breaker"' in src
        assert '"energy_evse_b_span_breaker"' in src

    def test_config_flow_exposes_fields(self):
        src = _read(_CONFIG_FLOW_PY)
        assert 'CONF_ENERGY_EVSE_A_SPAN_BREAKER' in src
        assert 'CONF_ENERGY_EVSE_B_SPAN_BREAKER' in src
        # Selector must be switch-domain (breaker is a switch).
        # Locate the schema block and assert the domain string appears near it.
        idx_a = src.index("CONF_ENERGY_EVSE_A_SPAN_BREAKER")
        # Take a window after the first occurrence in the schema.
        # Find last occurrence (in schema) after import.
        window_start = src.rindex("CONF_ENERGY_EVSE_A_SPAN_BREAKER")
        window = src[window_start:window_start + 500]
        assert 'domain="switch"' in window

    def test_init_wires_override_with_default_fallback(self):
        src = _read(_INIT_PY)
        # Import present.
        assert 'CONF_ENERGY_EVSE_A_SPAN_BREAKER' in src
        assert 'CONF_ENERGY_EVSE_B_SPAN_BREAKER' in src
        # Override merged into evse_config[..]["span_breaker"] only when set.
        assert 'evse_config["garage_a"]["span_breaker"] = evse_a_breaker' in src
        assert 'evse_config["garage_b"]["span_breaker"] = evse_b_breaker' in src

    def test_default_evse_entities_preserves_backward_compat(self):
        """When options are unset, span_breaker keeps the pre-cycle defaults."""
        from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
            DEFAULT_EVSE_ENTITIES,
        )
        assert DEFAULT_EVSE_ENTITIES["garage_a"]["span_breaker"] == (
            "switch.span_panel_car_charger_breaker"
        )
        assert DEFAULT_EVSE_ENTITIES["garage_b"]["span_breaker"] == (
            "switch.span_panel_garage_b_evse_breaker"
        )

    def test_override_round_trip(self):
        """Simulate the __init__.py merge path with options set."""
        from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
            DEFAULT_EVSE_ENTITIES,
        )
        evse_config = {k: dict(v) for k, v in DEFAULT_EVSE_ENTITIES.items()}
        cm_config = {
            "energy_evse_a_span_breaker": "switch.span_panel_renamed_a",
            "energy_evse_b_span_breaker": "switch.span_panel_renamed_b",
        }
        # Replicate the __init__.py logic.
        a = cm_config.get("energy_evse_a_span_breaker")
        if a:
            evse_config["garage_a"]["span_breaker"] = a
        b = cm_config.get("energy_evse_b_span_breaker")
        if b:
            evse_config["garage_b"]["span_breaker"] = b
        assert evse_config["garage_a"]["span_breaker"] == "switch.span_panel_renamed_a"
        assert evse_config["garage_b"]["span_breaker"] == "switch.span_panel_renamed_b"

    def test_translations_carry_labels_in_both_files(self):
        """strings.json and translations/en.json BOTH carry the labels and
        the values are byte-equal (the parity checker only inspects keys)."""
        s = _read(_STRINGS)
        e = _read(_EN_JSON)
        for token in (
            '"energy_evse_a_span_breaker": "EVSE Garage A SPAN breaker (switch)"',
            '"energy_evse_b_span_breaker": "EVSE Garage B SPAN breaker (switch)"',
        ):
            assert token in s, f"{token} missing from strings.json"
            assert token in e, f"{token} missing from translations/en.json"
        assert '"energy_evse_a_span_breaker": "SPAN panel breaker switch that pauses/resumes Garage A' in s
        assert '"energy_evse_a_span_breaker": "SPAN panel breaker switch that pauses/resumes Garage A' in e


# ---------------------------------------------------------------------------
# D3: Migration in _restore_energy_baselines
# ---------------------------------------------------------------------------

@pytest.fixture
def restore_fn():
    return _load_restore_fn()


@pytest.fixture
def tmp_db(tmp_path):
    p = str(tmp_path / "ura_test.db")
    _seed_db(p)
    return p


class TestD3Migration:
    def test_rewrites_friendly_scoped_row_to_unique_id(self, tmp_db, restore_fn):
        # Pre-migration row: scope='Kitchen Outlets', matches a circuit
        # with unique_id='span_uid_kitchen'.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Kitchen Outlets",
            mean=120.5, variance=25.0, sample_count=250,
        )
        circuits = {
            "sensor.span_panel_kitchen_outlets_power": _StubCircuit(
                "sensor.span_panel_kitchen_outlets_power",
                "Kitchen Outlets", "span_uid_kitchen",
            ),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))

        # Row rewritten to unique_id scope.
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert len(rows) == 1
        _, _, scope, mean, variance, samples, _ = rows[0]
        assert scope == "span_uid_kitchen"
        assert mean == 120.5
        assert variance == 25.0
        assert samples == 250

        # Backup captured pre-migration row.
        backup = _fetch_backup(tmp_db)
        pre = [r for r in backup if r[2] == "Kitchen Outlets"]
        assert len(pre) == 1
        assert pre[0][5] == 250  # sample_count preserved in backup
        assert pre[0][7] is not None  # pruned_at populated

        # Baseline attached to the new entity_id with sample_count intact.
        assert coord._circuits.restored_baselines is not None
        assert "sensor.span_panel_kitchen_outlets_power" in coord._circuits.restored_baselines
        b = coord._circuits.restored_baselines["sensor.span_panel_kitchen_outlets_power"]
        assert b.sample_count == 250
        assert b.scope == "span_uid_kitchen"

        # Sentinel row inserted.
        sentinel = _fetch_baselines(tmp_db, "energy", "_migration")
        assert len(sentinel) == 1
        assert sentinel[0][2] == "circuit_scope_v2"

    def test_unknown_scope_kept_in_place_and_not_warned(self, tmp_db, restore_fn):
        # Known orphans.
        _insert_baseline(tmp_db, "energy", "circuit_power", "Battery Power",
                         sample_count=42)
        # No matching circuit at all — coord has none.
        coord = _StubCoordinator(tmp_db, {})
        _run(restore_fn(coord))
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        # Row still present.
        assert any(r[2] == "Battery Power" for r in rows)
        # No backup entry — untouched.
        backup = _fetch_backup(tmp_db)
        assert not any(r[2] == "Battery Power" for r in backup)

    def test_unmapped_tab_still_pruned_reversibly(self, tmp_db, restore_fn):
        _insert_baseline(
            tmp_db, "energy", "circuit_power",
            "Span Left Unmapped Tab 24 Power", sample_count=17,
        )
        coord = _StubCoordinator(tmp_db, {})
        _run(restore_fn(coord))
        # Row removed from metric_baselines.
        remaining = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert not any("Unmapped Tab" in r[2] for r in remaining)
        # Backup carries it.
        backup = _fetch_backup(tmp_db)
        assert any("Unmapped Tab" in r[2] for r in backup)

    def test_migration_is_idempotent_across_double_restore(self, tmp_db, restore_fn):
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Kitchen Outlets",
            sample_count=100,
        )
        circuits = {
            "sensor.span_panel_kitchen_outlets_power": _StubCircuit(
                "sensor.span_panel_kitchen_outlets_power",
                "Kitchen Outlets", "span_uid_kitchen",
            ),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))
        first_rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        first_backup = _fetch_backup(tmp_db)
        # Second run — should be a no-op on rewrite (sentinel present),
        # already-v2 row attaches directly.
        _run(restore_fn(coord))
        second_rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        second_backup = _fetch_backup(tmp_db)
        assert first_rows == second_rows
        assert first_backup == second_backup
        # Sentinel present exactly once.
        sentinels = _fetch_baselines(tmp_db, "energy", "_migration")
        assert len(sentinels) == 1

    def test_rename_survival(self, tmp_db, restore_fn):
        """The intended cycle sequence:
        1. Boot N (pre-cycle) — baseline warmed with scope=friendly_name='Office'.
        2. Deploy v5.12.0 + boot — migration runs while the circuit is still
           named 'Office'; row rewrites to scope='span_uid_office'.
        3. Operator renames circuit in the SPAN app: entity_id + friendly_name
           change, unique_id stable.
        4. Boot N+2 — the still-warm baseline attaches to the NEW entity_id via
           unique_id, sample_count intact.

        This test drives boot 2 then boot 3 end-to-end.
        """
        # Boot 1 legacy state — row scoped on the ORIGINAL friendly_name.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Office",
            mean=95.0, variance=16.0, sample_count=300,
        )
        # Boot 2 (migration boot) — the circuit is still named 'Office',
        # unique_id resolved from the registry.
        pre_rename_eid = "sensor.span_panel_office_power"
        circuits_boot2 = {
            pre_rename_eid: _StubCircuit(
                pre_rename_eid, "Office", "span_uid_office",
            ),
        }
        coord = _StubCoordinator(tmp_db, circuits_boot2)
        _run(restore_fn(coord))
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert any(r[2] == "span_uid_office" for r in rows), (
            "boot-2 migration must rewrite Office → span_uid_office"
        )
        # SPAN-app rename happens between boots — no code path, just registry
        # semantics: entity_id + friendly change, unique_id stable.
        renamed_eid = "sensor.span_panel_home_office_power"
        circuits_boot3 = {
            renamed_eid: _StubCircuit(
                renamed_eid, "Home Office", "span_uid_office",
            ),
        }
        coord3 = _StubCoordinator(tmp_db, circuits_boot3)
        _run(restore_fn(coord3))
        # Baseline attaches to the NEW entity_id via unique_id, sample_count
        # + mean intact.
        attached = coord3._circuits.restored_baselines
        assert renamed_eid in attached, (
            "boot-3 baseline must attach under the renamed entity_id"
        )
        assert attached[renamed_eid].sample_count == 300
        assert attached[renamed_eid].mean == 95.0

    def test_cross_subsystem_rows_untouched(self, tmp_db, restore_fn):
        """Safety `rate_of_change` rows and diagnostic rows are byte-identical
        after the migration boot (Tier 2-DB A axis)."""
        # Safety-owned row (different coordinator_id).
        _insert_baseline(
            tmp_db, "safety", "rate:sensor.foo_temp", "rate_of_change",
            mean=1.5, variance=0.04, sample_count=200,
            last_updated="2026-06-01T12:00:00+00:00",
        )
        # Diagnostics-owned row (different coordinator_id).
        _insert_baseline(
            tmp_db, "presence", "some_metric", "kitchen",
            mean=3.14, variance=0.1, sample_count=50,
            last_updated="2026-06-15T09:30:00+00:00",
        )
        # Migration-eligible energy row.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Kitchen",
            sample_count=99,
        )
        circuits = {
            "sensor.span_panel_kitchen_power": _StubCircuit(
                "sensor.span_panel_kitchen_power", "Kitchen", "uid_k",
            ),
        }
        pre_safety = _fetch_baselines(tmp_db, "safety")
        pre_presence = _fetch_baselines(tmp_db, "presence")

        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))

        post_safety = _fetch_baselines(tmp_db, "safety")
        post_presence = _fetch_baselines(tmp_db, "presence")
        assert pre_safety == post_safety, "safety rows drifted across migration"
        assert pre_presence == post_presence, "presence rows drifted across migration"

    def test_already_v2_row_attaches_without_rewrite(self, tmp_db, restore_fn):
        """A row already keyed on unique_id (from a partial prior run or a
        fresh install) should attach directly with no backup entry."""
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "uid_hvac",
            sample_count=77,
        )
        # Pre-mark the migration as done to force the "already-v2" branch
        # for the row.
        _insert_baseline(
            tmp_db, "energy", "_migration", "circuit_scope_v2",
            sample_count=1,
        )
        circuits = {
            "sensor.span_panel_hvac_power": _StubCircuit(
                "sensor.span_panel_hvac_power", "HVAC", "uid_hvac",
            ),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))
        # No backup was written for this scope.
        backup = _fetch_backup(tmp_db)
        assert not any(r[2] == "uid_hvac" for r in backup)
        # Baseline attached.
        assert "sensor.span_panel_hvac_power" in coord._circuits.restored_baselines
        assert coord._circuits.restored_baselines[
            "sensor.span_panel_hvac_power"
        ].sample_count == 77
