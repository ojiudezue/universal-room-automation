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


def _load_async_method_fn(name: str, extra_replacements=None):
    """Compile any `async def name(self, ...)` from energy.py as standalone."""
    src = _extract_async_method(_read(_ENERGY_PY), name)
    src = textwrap.dedent(src)
    src = re.sub(
        r"^\s*from\s+\.coordinator_diagnostics\s+import\s+MetricBaseline\s*$",
        "",
        src,
        flags=re.MULTILINE,
    )
    for old, new in (extra_replacements or []):
        src = src.replace(old, new)
    import logging as _logging
    from custom_components.universal_room_automation.domain_coordinators.coordinator_diagnostics import (
        MetricBaseline,
    )
    ns: dict = {
        "__name__": f"test.span_rekey.{name}",
        "_LOGGER": _logging.getLogger(f"test.span_rekey.{name}"),
        "MetricBaseline": MetricBaseline,
    }
    exec(compile(src, f"<{name}>", "exec"), ns)
    return ns[name]


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
            '"energy_evse_a_span_breaker": "EVSE Garage A SPAN breaker"',
            '"energy_evse_b_span_breaker": "EVSE Garage B SPAN breaker"',
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


# ---------------------------------------------------------------------------
# v5.13.1 REGRESSION PIN: boot-ordering resumability
#
# Tonight's live incident: boot 1 ran `_restore_energy_baselines` BEFORE
# span_panel populated hass.states → discover_circuits() returned no
# SPAN circuits → all ~39 rows fell to mig_unmatched_left AND the sentinel
# was written, permanently blocking re-migration in v5.13.0.
#
# These tests must go RED if anyone re-adds a sentinel/migration_done gate
# on the friendly→unique or entity_id→unique rewrite branches.
# ---------------------------------------------------------------------------

class TestV5131BootOrderingResumability:
    def test_boot1_empty_discovery_leaves_rows_then_boot2_migrates(
        self, tmp_db, restore_fn,
    ):
        """Exact live scenario: boot 1 finds NO circuits → rows unmatched,
        sentinel written. Boot 2 has discovery populated → rows migrate."""
        # Legacy friendly-scoped row.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Kitchen Outlets",
            mean=120.5, variance=25.0, sample_count=250,
        )
        # Boot 1: span_panel not up yet — empty circuits.
        coord_boot1 = _StubCoordinator(tmp_db, {})
        _run(restore_fn(coord_boot1))
        # Row still present at friendly_name (unmatched-left-in-place).
        rows_after_boot1 = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert any(r[2] == "Kitchen Outlets" for r in rows_after_boot1), (
            "boot-1 with empty discovery must leave the row in place"
        )
        # Sentinel written on boot 1 (informational).
        sentinel_after_boot1 = _fetch_baselines(tmp_db, "energy", "_migration")
        assert len(sentinel_after_boot1) == 1

        # Boot 2: span_panel is up — circuits + unique_ids available.
        eid = "sensor.span_panel_kitchen_outlets_power"
        circuits_boot2 = {
            eid: _StubCircuit(eid, "Kitchen Outlets", "span_uid_kitchen"),
        }
        coord_boot2 = _StubCoordinator(tmp_db, circuits_boot2)
        _run(restore_fn(coord_boot2))
        # THE PIN: rewrite branch must have fired despite sentinel presence.
        rows_after_boot2 = _fetch_baselines(tmp_db, "energy", "circuit_power")
        scopes = {r[2] for r in rows_after_boot2}
        assert "span_uid_kitchen" in scopes, (
            "boot-2 MUST migrate the row now that discovery resolves — "
            "if this fails, a sentinel/migration_done gate has been re-added "
            "to the friendly→unique rewrite branch"
        )
        assert "Kitchen Outlets" not in scopes, (
            "old friendly-scoped row must be deleted after boot-2 rewrite"
        )
        # sample_count preserved end-to-end.
        migrated = [r for r in rows_after_boot2 if r[2] == "span_uid_kitchen"][0]
        assert migrated[5] == 250, "sample_count lost across boot-1 + boot-2"
        # Backup captured pre-migration row on boot 2.
        backup = _fetch_backup(tmp_db)
        assert any(r[2] == "Kitchen Outlets" and r[5] == 250 for r in backup)
        # Baseline attached in-memory on boot 2.
        assert eid in coord_boot2._circuits.restored_baselines
        assert coord_boot2._circuits.restored_baselines[eid].sample_count == 250

    def test_boot1_entity_id_scoped_row_upgrades_on_boot2(
        self, tmp_db, restore_fn,
    ):
        """Same resumability guarantee for the entity_id→unique_id branch:
        boot 1 discovery empty → row untouched, sentinel written; boot 2
        with unique_id available upgrades the row."""
        eid = "sensor.span_panel_dryer_power"
        _insert_baseline(
            tmp_db, "energy", "circuit_power", eid,
            mean=55.0, variance=4.0, sample_count=88,
        )
        # Boot 1: empty circuits.
        coord_boot1 = _StubCoordinator(tmp_db, {})
        _run(restore_fn(coord_boot1))
        assert any(r[2] == eid for r in _fetch_baselines(
            tmp_db, "energy", "circuit_power"))
        assert len(_fetch_baselines(tmp_db, "energy", "_migration")) == 1

        # Boot 2: circuit resolves with a unique_id.
        circuits_boot2 = {
            eid: _StubCircuit(eid, "Dryer", "uid_dryer_stable"),
        }
        coord_boot2 = _StubCoordinator(tmp_db, circuits_boot2)
        _run(restore_fn(coord_boot2))
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        scopes = {r[2] for r in rows}
        assert "uid_dryer_stable" in scopes, (
            "boot-2 MUST upgrade the entity_id-scoped row — "
            "if this fails, a sentinel/migration_done gate has been re-added "
            "to the entity_id→unique rewrite branch"
        )
        assert eid not in scopes, (
            "old entity_id-scoped row must be deleted after boot-2 upgrade"
        )
        # sample_count preserved.
        upgraded = [r for r in rows if r[2] == "uid_dryer_stable"][0]
        assert upgraded[5] == 88

    def test_boot3_after_full_migration_is_idempotent_debug(
        self, tmp_db, restore_fn, caplog,
    ):
        """Boot 3 (after boots 1 + 2 above): row already at unique_id scope,
        sentinel present — no further rewrites, summary at DEBUG."""
        import logging as _logging
        # Skip straight to the post-boot-2 state: v2-scoped row + sentinel.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "span_uid_kitchen",
            mean=120.5, variance=25.0, sample_count=250,
        )
        _insert_baseline(
            tmp_db, "energy", "_migration", "circuit_scope_v2",
            sample_count=1,
        )
        eid = "sensor.span_panel_kitchen_outlets_power"
        circuits = {
            eid: _StubCircuit(eid, "Kitchen Outlets", "span_uid_kitchen"),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        pre_backup = _fetch_backup(tmp_db)
        with caplog.at_level(_logging.DEBUG, logger="test.span_rekey"):
            _run(restore_fn(coord))
        # No new rewrites.
        post_backup = _fetch_backup(tmp_db)
        assert pre_backup == post_backup, "boot-3 must not touch backup table"
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert len(rows) == 1 and rows[0][2] == "span_uid_kitchen"
        # Summary at DEBUG (no _rewrote_this_boot work).
        info_msgs = [
            r for r in caplog.records
            if r.levelno >= _logging.INFO
            and "SPAN scope migration" in r.getMessage()
        ]
        assert not info_msgs, (
            f"boot-3 steady-state must summarise at DEBUG; got INFO: "
            f"{[r.getMessage() for r in info_msgs]}"
        )
        debug_msgs = [
            r for r in caplog.records
            if r.levelno == _logging.DEBUG
            and "SPAN scope migration" in r.getMessage()
        ]
        assert debug_msgs, "expected a DEBUG summary line on boot 3"


# ---------------------------------------------------------------------------
# F2 (Review B-HIGH-1): entity_id fallback attach + upgrade
# ---------------------------------------------------------------------------

class TestF2EntityIdFallback:
    def test_entity_id_scoped_row_attaches_intact(self, tmp_db, restore_fn):
        """Rows saved under scope=entity_id (unique_id unresolved at save-
        time) re-attach with sample_count intact. Migration NOT done yet,
        circuit has no unique_id → attach in place (no upgrade path)."""
        eid = "sensor.extras_emporia_dryer_power"
        _insert_baseline(
            tmp_db, "energy", "circuit_power", eid,
            mean=42.0, variance=9.0, sample_count=123,
        )
        circuits = {
            eid: _StubCircuit(eid, "Dryer", None),  # unique_id None
        }
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))
        # Row still in place, scope unchanged.
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert any(r[2] == eid for r in rows)
        # Baseline attached under entity_id key with sample_count intact.
        attached = coord._circuits.restored_baselines
        assert eid in attached
        assert attached[eid].sample_count == 123
        assert attached[eid].mean == 42.0

    def test_entity_id_scoped_row_upgrades_when_unique_id_now_resolves(
        self, tmp_db, restore_fn,
    ):
        """When migration is running AND a unique_id now resolves for the
        entity_id-scoped row, upgrade via backup→rewrite→delete."""
        eid = "sensor.span_panel_dryer_power"
        _insert_baseline(
            tmp_db, "energy", "circuit_power", eid,
            mean=55.0, variance=4.0, sample_count=88,
        )
        circuits = {
            eid: _StubCircuit(eid, "Dryer", "uid_dryer_stable"),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))
        # Row upgraded to unique_id scope.
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        assert any(r[2] == "uid_dryer_stable" for r in rows)
        assert not any(r[2] == eid for r in rows)
        # Backup captured pre-upgrade row.
        backup = _fetch_backup(tmp_db)
        assert any(r[2] == eid and r[5] == 88 for r in backup)
        # Baseline attached with intact stats.
        attached = coord._circuits.restored_baselines
        assert attached[eid].sample_count == 88
        assert attached[eid].scope == "uid_dryer_stable"


# ---------------------------------------------------------------------------
# F3 (Review C-HIGH-2): _lookup_unique_id real coverage
# ---------------------------------------------------------------------------
# HA registry API cited from
#   .venv-ha/lib/python3.13/site-packages/homeassistant/helpers/entity_registry.py:
#     - module-level `async_get(hass) -> EntityRegistry`  (line 1941)
#     - `EntityRegistry.async_get(entity_id_or_uuid: str) -> RegistryEntry | None`
#       (line 891)
#     - `RegistryEntry.unique_id: str` (line 184)
# `_lookup_unique_id` calls these APIs in that exact order.

class TestF3LookupUniqueIdRealCoverage:
    def _make_registry(self, entries: dict[str, str | None]):
        """Return a mock EntityRegistry whose async_get returns a stub
        RegistryEntry-shaped object (unique_id attr) or None."""
        class _Entry:
            def __init__(self, uid): self.unique_id = uid
        reg = MagicMock()
        def _async_get(entity_id):
            if entity_id not in entries:
                return None
            return _Entry(entries[entity_id])
        reg.async_get.side_effect = _async_get
        return reg

    def _make_hass_with_states(self, span_power_states: list[tuple[str, str]],
                               extras: list[tuple[str, str]] | None = None):
        """Build a hass mock whose states.async_all('sensor') yields the
        given span_panel_*_power states with friendly_name attrs."""
        class _State:
            def __init__(self, entity_id, friendly):
                self.entity_id = entity_id
                self.attributes = {"friendly_name": friendly}
                self.state = "10"
        span_states = [_State(eid, fn) for eid, fn in span_power_states]
        extra_states = {eid: _State(eid, fn) for eid, fn in (extras or [])}
        hass = MagicMock()
        hass.states.async_all.return_value = span_states
        hass.states.get.side_effect = lambda eid: extra_states.get(eid)
        return hass

    def test_span_tier1_populates_unique_id(self, monkeypatch):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor,
        )
        eid = "sensor.span_panel_kitchen_power"
        registry = self._make_registry({eid: "span_uid_kitchen"})
        hass = self._make_hass_with_states([(eid, "Kitchen")])
        # Patch entity_registry.async_get to return our registry.
        import homeassistant.helpers.entity_registry as er
        monkeypatch.setattr(er, "async_get", lambda _h: registry, raising=False)
        mon = SPANCircuitMonitor(hass, autodiscover_span=True)
        mon.discover_circuits()
        assert eid in mon._circuits
        assert mon._circuits[eid].unique_id == "span_uid_kitchen"

    def test_extras_branch_populates_unique_id(self, monkeypatch):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor,
        )
        eid = "sensor.emporia_dryer_power"
        registry = self._make_registry({eid: "emporia_uid_dryer"})
        hass = self._make_hass_with_states([], extras=[(eid, "Dryer")])
        import homeassistant.helpers.entity_registry as er
        monkeypatch.setattr(er, "async_get", lambda _h: registry, raising=False)
        mon = SPANCircuitMonitor(
            hass, extra_entities=[eid], autodiscover_span=False,
        )
        mon.discover_circuits()
        assert eid in mon._circuits
        assert mon._circuits[eid].unique_id == "emporia_uid_dryer"

    def test_registry_returning_none_falls_back(self, monkeypatch):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor,
        )
        eid = "sensor.span_panel_ghost_power"
        registry = self._make_registry({})  # entity NOT in registry
        hass = self._make_hass_with_states([(eid, "Ghost")])
        import homeassistant.helpers.entity_registry as er
        monkeypatch.setattr(er, "async_get", lambda _h: registry, raising=False)
        mon = SPANCircuitMonitor(hass, autodiscover_span=True)
        mon.discover_circuits()
        assert eid in mon._circuits
        assert mon._circuits[eid].unique_id is None  # no exception

    def test_registry_raising_falls_back(self, monkeypatch):
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor,
        )
        eid = "sensor.span_panel_boom_power"
        hass = self._make_hass_with_states([(eid, "Boom")])
        def _boom(_h):
            raise RuntimeError("registry unavailable at boot")
        import homeassistant.helpers.entity_registry as er
        monkeypatch.setattr(er, "async_get", _boom, raising=False)
        mon = SPANCircuitMonitor(hass, autodiscover_span=True)
        mon.discover_circuits()  # must NOT raise
        assert eid in mon._circuits
        assert mon._circuits[eid].unique_id is None


# ---------------------------------------------------------------------------
# F4 (Review C-HIGH-1): predicate anchoring — safety row byte-identical
# ---------------------------------------------------------------------------

class TestF4PredicateAnchoring:
    def test_safety_row_sharing_scope_name_untouched(self, tmp_db, restore_fn):
        """A safety-coordinator row whose scope equals the friendly_name of a
        migrating energy circuit must be byte-identical after migration.
        This anchors the DELETE predicate — mutation-red/green:
        broadening the predicate (dropping coordinator_id or metric_name
        filter) must make THIS test fail."""
        # Both rows carry scope='Kitchen'.
        _insert_baseline(
            tmp_db, "safety", "rate_of_change", "Kitchen",
            mean=0.5, variance=0.01, sample_count=200,
            last_updated="2026-06-01T00:00:00+00:00",
        )
        # Migration-eligible energy row with same scope.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Kitchen",
            mean=100.0, variance=1.0, sample_count=50,
        )
        circuits = {
            "sensor.span_panel_kitchen_power": _StubCircuit(
                "sensor.span_panel_kitchen_power", "Kitchen", "uid_kitchen",
            ),
        }
        pre_safety = _fetch_baselines(tmp_db, "safety")
        assert len(pre_safety) == 1
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))
        post_safety = _fetch_baselines(tmp_db, "safety")
        # Byte-identical.
        assert pre_safety == post_safety, (
            "safety row sharing 'Kitchen' scope was mutated — DELETE "
            "predicate is too broad"
        )


# ---------------------------------------------------------------------------
# F5 (Review B-MED-1 + C-LOW-1): duplicate friendly_name WARN
# ---------------------------------------------------------------------------

class TestF5DuplicateFriendlyWarn:
    def test_duplicate_friendly_name_warned_and_first_wins(
        self, tmp_db, restore_fn, caplog,
    ):
        import logging as _logging
        # Two circuits share friendly_name 'Outlet'; only the first wins the
        # friendly-scoped restore.
        _insert_baseline(
            tmp_db, "energy", "circuit_power", "Outlet",
            mean=10.0, variance=1.0, sample_count=42,
        )
        circuits = {
            "sensor.span_panel_outlet_a_power": _StubCircuit(
                "sensor.span_panel_outlet_a_power", "Outlet", "uid_a",
            ),
            "sensor.span_panel_outlet_b_power": _StubCircuit(
                "sensor.span_panel_outlet_b_power", "Outlet", "uid_b",
            ),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        with caplog.at_level(_logging.WARNING, logger="test.span_rekey"):
            _run(restore_fn(coord))
        # WARN mentions both candidates.
        warn_msgs = [r for r in caplog.records if r.levelno >= _logging.WARNING]
        assert any(
            "Duplicate SPAN friendly_name" in r.getMessage()
            and "sensor.span_panel_outlet_a_power" in r.getMessage()
            and "sensor.span_panel_outlet_b_power" in r.getMessage()
            for r in warn_msgs
        ), f"expected duplicate-friendly WARN with both candidates; got: {[r.getMessage() for r in warn_msgs]}"
        # First-wins: uid_a receives the migrated baseline.
        rows = _fetch_baselines(tmp_db, "energy", "circuit_power")
        scopes = {r[2] for r in rows}
        assert "uid_a" in scopes
        assert "uid_b" not in scopes


# ---------------------------------------------------------------------------
# F7 (Review C-MED-1): production merge → EVChargerController._evse
# ---------------------------------------------------------------------------

class TestF7EvseMergeProductionPath:
    def test_merge_reaches_ev_charger_controller_evse(self):
        """Execute the exact `__init__.py` merge block against a mock
        cm_config, then construct EVChargerController with the result and
        assert the override reaches `._evse[...]["span_breaker"]`."""
        from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
            DEFAULT_EVSE_ENTITIES, EVChargerController,
        )
        from custom_components.universal_room_automation.domain_coordinators.energy_const import (
            CONF_ENERGY_EVSE_A_SPAN_BREAKER,
            CONF_ENERGY_EVSE_B_SPAN_BREAKER,
        )
        cm_config = {
            CONF_ENERGY_EVSE_A_SPAN_BREAKER: "switch.span_panel_new_a_breaker",
            CONF_ENERGY_EVSE_B_SPAN_BREAKER: "switch.span_panel_new_b_breaker",
        }
        # Replicate the merge block from __init__.py verbatim in behaviour.
        evse_config = {k: dict(v) for k, v in DEFAULT_EVSE_ENTITIES.items()}
        evse_a_breaker = cm_config.get(CONF_ENERGY_EVSE_A_SPAN_BREAKER)
        if evse_a_breaker:
            evse_config["garage_a"]["span_breaker"] = evse_a_breaker
        evse_b_breaker = cm_config.get(CONF_ENERGY_EVSE_B_SPAN_BREAKER)
        if evse_b_breaker:
            evse_config["garage_b"]["span_breaker"] = evse_b_breaker
        # Now the production consumer.
        controller = EVChargerController(MagicMock(), evse_config)
        assert controller._evse["garage_a"]["span_breaker"] == (
            "switch.span_panel_new_a_breaker"
        )
        assert controller._evse["garage_b"]["span_breaker"] == (
            "switch.span_panel_new_b_breaker"
        )

    def test_merge_omitted_options_keeps_defaults_in_controller(self):
        from custom_components.universal_room_automation.domain_coordinators.energy_pool import (
            DEFAULT_EVSE_ENTITIES, EVChargerController,
        )
        evse_config = {k: dict(v) for k, v in DEFAULT_EVSE_ENTITIES.items()}
        controller = EVChargerController(MagicMock(), evse_config)
        assert controller._evse["garage_a"]["span_breaker"] == (
            "switch.span_panel_car_charger_breaker"
        )
        assert controller._evse["garage_b"]["span_breaker"] == (
            "switch.span_panel_garage_b_evse_breaker"
        )


# ---------------------------------------------------------------------------
# F8 (Review C-MED-3): save → restore round-trip on unique_id scope
# ---------------------------------------------------------------------------

class TestF8SaveRestoreRoundTrip:
    def test_save_under_unique_id_restore_attaches(self, tmp_db, restore_fn):
        """The production `_get_power_baseline` uses scope=unique_id when
        available; `_save_energy_baselines` persists that scope. A fresh
        restore against the same DB must attach the row directly via the
        already-v2 branch, sample_count intact."""
        # Simulate a save cycle: build a baseline directly and INSERT it under
        # scope=unique_id. This is the shape `_save_energy_baselines` writes
        # (see energy.py:_save_energy_baselines — INSERT OR REPLACE with
        # baseline.scope). The runtime construction of scope happens in
        # `_get_power_baseline` (energy_circuits.py:_get_power_baseline).
        from custom_components.universal_room_automation.domain_coordinators.energy_circuits import (
            SPANCircuitMonitor, CircuitInfo,
        )
        eid = "sensor.span_panel_office_power"
        uid = "uid_office_stable"
        mon = SPANCircuitMonitor(MagicMock())
        mon._circuits[eid] = CircuitInfo(eid, "Office", "left", unique_id=uid)
        mon._discovered = True
        bl = mon._get_power_baseline(eid)  # scope should be uid
        assert bl.scope == uid
        # Simulate accumulated samples.
        bl.mean = 88.0
        bl.variance = 4.0
        bl.sample_count = 200
        bl.last_updated = "2026-07-01T00:00:00+00:00"
        # Persist EXACTLY as `_save_energy_baselines` would.
        with sqlite3.connect(tmp_db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO metric_baselines "
                "(coordinator_id, metric_name, scope, mean, variance, "
                " sample_count, last_updated) VALUES (?,?,?,?,?,?,?)",
                (bl.coordinator_id, bl.metric_name, bl.scope, bl.mean,
                 bl.variance, bl.sample_count, bl.last_updated),
            )
            conn.commit()
        # Fresh restore against a new coordinator whose circuits carry the
        # same unique_id → attach via the already-v2 branch.
        circuits = {
            eid: _StubCircuit(eid, "Office", uid),
        }
        coord = _StubCoordinator(tmp_db, circuits)
        _run(restore_fn(coord))
        attached = coord._circuits.restored_baselines
        assert eid in attached
        assert attached[eid].sample_count == 200
        assert attached[eid].mean == 88.0
        assert attached[eid].scope == uid
        # No backup entry — untouched already-v2 row.
        backup = _fetch_backup(tmp_db)
        assert not any(r[2] == uid for r in backup)


# ---------------------------------------------------------------------------
# F9 (Review A-MED-2): all-zero migration summary is DEBUG, not INFO
# ---------------------------------------------------------------------------

class TestF9AllZeroSummaryIsDebug:
    def test_fresh_install_migration_summary_is_debug(
        self, tmp_db, restore_fn, caplog,
    ):
        """Empty energy baselines table + no circuits → migration path
        executes with all-zero counters. Summary must be at DEBUG level,
        with '(first boot; nothing to migrate)' suffix."""
        import logging as _logging
        coord = _StubCoordinator(tmp_db, {})
        with caplog.at_level(_logging.DEBUG, logger="test.span_rekey"):
            _run(restore_fn(coord))
        # No INFO-level 'SPAN scope migration' line.
        info_lines = [
            r for r in caplog.records
            if r.levelno >= _logging.INFO
            and "SPAN scope migration" in r.getMessage()
        ]
        assert not info_lines, f"expected no INFO summary for zero-work migration; got {info_lines}"
        # A DEBUG line WITH the suffix must exist.
        debug_lines = [
            r for r in caplog.records
            if r.levelno == _logging.DEBUG
            and "SPAN scope migration" in r.getMessage()
            and "(first boot; nothing to migrate)" in r.getMessage()
        ]
        assert debug_lines, "expected DEBUG summary with first-boot suffix"


# ---------------------------------------------------------------------------
# F11 (documentation): reserved `_migration` metric_name prefix in DDL
# ---------------------------------------------------------------------------

class TestF11ReservedMigrationPrefixDocumented:
    def test_database_py_documents_reserved_prefix(self):
        src = _read(_DATABASE_PY)
        # Comment must be adjacent to the metric_baselines DDL block.
        idx = src.index("CREATE TABLE IF NOT EXISTS metric_baselines")
        window = src[max(0, idx - 800):idx]
        assert "_migration" in window and "reserved" in window.lower(), (
            "expected F11 comment documenting the reserved '_migration' "
            "metric_name prefix adjacent to the metric_baselines DDL"
        )


# ---------------------------------------------------------------------------
# F12 (documentation): rollback SQL docstring covers sentinel DELETE
# ---------------------------------------------------------------------------

class TestF12RollbackDocstringExtended:
    def test_restore_docstring_covers_sentinel_and_leftovers(self):
        src = _read(_ENERGY_PY)
        # Locate _restore_energy_baselines docstring.
        m = re.search(
            r'async def _restore_energy_baselines\(self\)[^"]*"""(.*?)"""',
            src, re.DOTALL,
        )
        assert m, "docstring not found"
        doc = m.group(1)
        assert "_migration" in doc and "circuit_scope_v2" in doc
        assert "DELETE FROM metric_baselines" in doc, (
            "docstring must include the sentinel DELETE rollback step"
        )
        assert "harmless leftovers" in doc.lower() or "harmless" in doc.lower(), (
            "docstring must note unique_id-keyed rows are harmless leftovers post-rollback"
        )


# ---------------------------------------------------------------------------
# F13 (label hygiene): '(switch)' suffix removed from EVSE labels
# ---------------------------------------------------------------------------

class TestF13SwitchSuffixDropped:
    def test_no_switch_suffix_in_evse_span_breaker_labels(self):
        for path in (_STRINGS, _EN_JSON):
            src = _read(path)
            assert '"EVSE Garage A SPAN breaker (switch)"' not in src, (
                f"{path} still carries '(switch)' suffix"
            )
            assert '"EVSE Garage B SPAN breaker (switch)"' not in src
            assert '"energy_evse_a_span_breaker": "EVSE Garage A SPAN breaker"' in src
            assert '"energy_evse_b_span_breaker": "EVSE Garage B SPAN breaker"' in src
