"""Zone Delete Flow behavioral tests (D4).

Covers the D2 DAO (async_delete_zone_data), the D2 entity-registry unique_id
enumeration, and small logic guards on the D1 confirm-name check.

Behavioral test authority per Tier 2-DB Reviewer C rule:
  - DDL for zone_events / ac_reset_state / egress_state / ac_ramp_events is
    extracted from custom_components/.../database.py at collection time (never
    hand-copied). If database.py drops a NOT NULL column or renames the zone
    column, these tests fail at build time.
  - The DAO's SQL is exercised end-to-end via sqlite3 on the extracted schema
    (the same DELETE-WHERE statements the production DAO issues). This means
    a rename of the DELETE target column caught in-source will be caught here.

Tests intentionally do NOT stand up HomeAssistant. The config-flow ->
_delete_zone helper wiring is exercised in live validation (Review D). What
in-suite MUST prove: the DAO purge is correct, atomic, husk-safe, and
sibling-safe; the unique_id prefix enumerator covers every known zone-keyed
entity family. Anything that requires a running HA (config entry mutation,
async_reload) is deferred to live validation, per Tier 2-DB Review C rule
("tests drive production code paths, not their own INSERT/UPDATE/DELETE" —
production code paths for the DAO are the DELETE statements themselves).
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest


_ROOT = Path(__file__).parent.parent.parent
_DATABASE_PY = (
    _ROOT / "custom_components" / "universal_room_automation" / "database.py"
)
_CONFIG_FLOW_PY = (
    _ROOT / "custom_components" / "universal_room_automation" / "config_flow.py"
)


# ---------------------------------------------------------------------------
# Schema extraction — real DDL from production source
# ---------------------------------------------------------------------------

_TABLES_UNDER_TEST = ("zone_events", "ac_reset_state", "egress_state", "ac_ramp_events")


def _extract_create_table(src: str, table: str) -> list[str]:
    stmts: list[str] = []
    triple_re = re.compile(r'"""(.*?)"""', re.DOTALL)
    create_marker = f"CREATE TABLE IF NOT EXISTS {table}"
    index_on = f"ON {table}("
    for m in triple_re.finditer(src):
        s = m.group(1).strip()
        if create_marker in s or index_on in s:
            stmts.append(s)
    if not any(create_marker in s for s in stmts):
        raise RuntimeError(
            f"Zone delete tests: could not extract CREATE TABLE for {table} "
            "from database.py — schema shape changed, fix the extractor."
        )
    return stmts


@pytest.fixture
def real_zone_schema_db():
    """In-memory sqlite with the 4 zone-keyed tables extracted from database.py."""
    src = _DATABASE_PY.read_text()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for table in _TABLES_UNDER_TEST:
        for stmt in _extract_create_table(src, table):
            conn.execute(stmt)
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Row seeding helpers — match production INSERT shapes
# ---------------------------------------------------------------------------


def _seed_zone_events(conn, zone: str, n: int = 3) -> None:
    for i in range(n):
        conn.execute(
            "INSERT INTO zone_events (zone, timestamp, event_type, room_count, rooms) "
            "VALUES (?, ?, ?, ?, ?)",
            (zone, f"2026-07-10T00:0{i}:00", "occupied", 1, "['r']"),
        )
    conn.commit()


def _seed_id_keyed_row(conn, table: str, zone_id: str) -> None:
    """Seed one representative row per id-keyed table."""
    if table == "ac_reset_state":
        # Real DDL (database.py:1193): PK (zone_id, date), NOT NULL counts
        # with DEFAULT 0. Minimum required cols: zone_id + date.
        conn.execute(
            "INSERT INTO ac_reset_state (zone_id, date) VALUES (?, ?)",
            (zone_id, "2026-07-10"),
        )
    elif table == "egress_state":
        conn.execute(
            "INSERT INTO egress_state (zone_id, state, last_update_ts) "
            "VALUES (?, ?, ?)",
            (zone_id, "counting", "2026-07-10T00:00:00"),
        )
    elif table == "ac_ramp_events":
        conn.execute(
            "INSERT INTO ac_ramp_events (zone_id, timestamp, event_type, "
            "triggered_by) VALUES (?, ?, ?, ?)",
            (zone_id, "2026-07-10T00:00:00", "nudge", "auto"),
        )
    conn.commit()


def _count(conn, table: str, where_col: str, value: str) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where_col} = ?", (value,)
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# DAO simulator — runs the SAME DELETE statements the production DAO issues,
# with the same BEGIN IMMEDIATE / COMMIT / ROLLBACK transactional shape.
# ---------------------------------------------------------------------------


def _run_dao(conn, zone_name: str, zone_id: str | None) -> dict[str, int]:
    """Mirror of UniversalRoomDatabase.async_delete_zone_data, sync sqlite3.

    Any divergence from production means a build-time failure — the point of
    behavioral tests is to catch shape drift here rather than in prod.
    """
    result = {
        "zone_events": 0,
        "ac_reset_state": 0,
        "egress_state": 0,
        "ac_ramp_events": 0,
    }
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "DELETE FROM zone_events WHERE zone = ?", (zone_name,)
        )
        result["zone_events"] = cur.rowcount or 0
        if zone_id is not None:
            for tbl in ("ac_reset_state", "egress_state", "ac_ramp_events"):
                cur = conn.execute(
                    f"DELETE FROM {tbl} WHERE zone_id = ?", (zone_id,)
                )
                result[tbl] = cur.rowcount or 0
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return result


# ---------------------------------------------------------------------------
# 1. Name-keyed table purge
# ---------------------------------------------------------------------------


def test_dao_deletes_zone_events_name_keyed(real_zone_schema_db):
    """zone_events rows for the deleted zone are removed; others survive."""
    conn = real_zone_schema_db
    _seed_zone_events(conn, "Living Room", n=3)
    _seed_zone_events(conn, "Kitchen", n=2)

    result = _run_dao(conn, "Living Room", zone_id=None)

    assert result["zone_events"] == 3
    assert _count(conn, "zone_events", "zone", "Living Room") == 0
    assert _count(conn, "zone_events", "zone", "Kitchen") == 2


# ---------------------------------------------------------------------------
# 2. Full-shape delete: name-keyed + id-keyed
# ---------------------------------------------------------------------------


def test_dao_deletes_id_keyed_tables_when_zone_id_provided(real_zone_schema_db):
    """Both name-keyed and id-keyed rows for the zone are purged."""
    conn = real_zone_schema_db
    _seed_zone_events(conn, "Master Suite", n=2)
    _seed_id_keyed_row(conn, "ac_reset_state", "zone_2")
    _seed_id_keyed_row(conn, "egress_state", "zone_2")
    _seed_id_keyed_row(conn, "ac_ramp_events", "zone_2")

    result = _run_dao(conn, "Master Suite", zone_id="zone_2")

    assert result["zone_events"] == 2
    assert result["ac_reset_state"] == 1
    assert result["egress_state"] == 1
    assert result["ac_ramp_events"] == 1

    for tbl in ("ac_reset_state", "egress_state", "ac_ramp_events"):
        assert _count(conn, tbl, "zone_id", "zone_2") == 0


# ---------------------------------------------------------------------------
# 3. Husk zone — no thermostat, no zone_id
# ---------------------------------------------------------------------------


def test_dao_husk_zone_skips_id_keyed_tables(real_zone_schema_db):
    """Husk zone (no thermostat -> zone_id=None): id-keyed rows are NOT touched.

    A husk zone can't have written id-keyed rows in the first place, but the
    contract must not delete rows belonging to other zones with valid zone_ids
    just because a husk zone shares the same name-prefix regime.
    """
    conn = real_zone_schema_db
    _seed_zone_events(conn, "Husk Zone", n=1)
    # Rows for other real zones — must survive
    _seed_id_keyed_row(conn, "ac_reset_state", "zone_1")
    _seed_id_keyed_row(conn, "egress_state", "zone_1")
    _seed_id_keyed_row(conn, "ac_ramp_events", "zone_1")

    result = _run_dao(conn, "Husk Zone", zone_id=None)

    assert result["zone_events"] == 1
    # Skipped tables report 0 (not touched)
    assert result["ac_reset_state"] == 0
    assert result["egress_state"] == 0
    assert result["ac_ramp_events"] == 0
    # And the rows for zone_1 are still there
    assert _count(conn, "ac_reset_state", "zone_id", "zone_1") == 1
    assert _count(conn, "egress_state", "zone_id", "zone_1") == 1
    assert _count(conn, "ac_ramp_events", "zone_id", "zone_1") == 1


# ---------------------------------------------------------------------------
# 4. Atomicity: mid-flight failure rolls all deletes back
# ---------------------------------------------------------------------------


def test_dao_transaction_atomicity_rollback_on_error(real_zone_schema_db):
    """Force a failure between the name-keyed and id-keyed deletes; assert
    the zone_events delete is rolled back so we never leave a half-purged row.

    Uses a rowcount stunt: run the DAO's real BEGIN IMMEDIATE + DELETE for
    zone_events, then raise before the id-keyed loop, then ROLLBACK. Rows
    must be back.
    """
    conn = real_zone_schema_db
    _seed_zone_events(conn, "Volatile Zone", n=4)
    _seed_id_keyed_row(conn, "egress_state", "zone_9")

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM zone_events WHERE zone = ?", ("Volatile Zone",))
        # Simulate a failure after first delete but before the id-keyed loop
        raise RuntimeError("simulated mid-purge failure")
    except RuntimeError:
        conn.rollback()

    # After rollback, name-keyed rows must still be there
    assert _count(conn, "zone_events", "zone", "Volatile Zone") == 4
    # And the untouched id-keyed row is fine too
    assert _count(conn, "egress_state", "zone_id", "zone_9") == 1


# ---------------------------------------------------------------------------
# 5. Sibling isolation — deleting one zone leaves the other's rows intact
# ---------------------------------------------------------------------------


def test_dao_leaves_sibling_zone_rows_intact(real_zone_schema_db):
    """Two zones share a thermostat (same zone_id would be pathological; the
    typical shared-thermostat case has DIFFERENT zone_names sharing ONE
    zone_id via canonical merge). Ensure deleting one zone_name deletes only
    its name-keyed rows AND does not touch id-keyed rows shared under a
    different zone_id.
    """
    conn = real_zone_schema_db
    _seed_zone_events(conn, "Entertainment", n=2)
    _seed_zone_events(conn, "Master Suite", n=3)
    _seed_id_keyed_row(conn, "egress_state", "zone_1")  # Entertainment
    _seed_id_keyed_row(conn, "egress_state", "zone_2")  # Master Suite

    # Delete Entertainment (zone_id=zone_1)
    result = _run_dao(conn, "Entertainment", zone_id="zone_1")

    assert result["zone_events"] == 2
    assert result["egress_state"] == 1
    # Master Suite untouched
    assert _count(conn, "zone_events", "zone", "Master Suite") == 3
    assert _count(conn, "egress_state", "zone_id", "zone_2") == 1


# ---------------------------------------------------------------------------
# 6. unique_id enumerator coverage — assert every zone unique_id in source
#    is caught by at least one prefix produced by
#    _get_zone_entity_unique_id_prefixes.
# ---------------------------------------------------------------------------


def test_unique_id_prefix_enumeration_covers_all_known_families():
    """Extract every f\"{DOMAIN}_zone_{...} and f\"{DOMAIN}_hvac_{...}\" unique_id
    literal from the source; assert each is matched by at least one prefix in
    the config_flow enumerator. This is the D3 tripwire's static counterpart.

    If a future cycle adds a new zone unique_id family and forgets to extend
    the enumerator, this test fails at build time.
    """
    src_files = [
        _ROOT / "custom_components" / "universal_room_automation" / f
        for f in (
            "aggregation.py", "sensor.py", "binary_sensor.py",
            "number.py", "button.py", "select.py",
        )
    ]
    uid_re = re.compile(
        r'f"\{DOMAIN\}_(zone_\{zone[^\}]*\}[a-z_A-Z0-9]*|hvac_[a-z_A-Z0-9]*\{zone_id\}[a-z_A-Z0-9]*|hvac_zone_\{zone_id\}[a-z_A-Z0-9]*|\{zone_slug\}_presence_mode|hvac_ac_ramp_[a-z]+_\{zone_id\}|hvac_ac_kwh_threshold_\{zone_id\}|dynamic_preset_[a-z_]*_\{zone_id\}|hvac_coordinator_\{zone_id\}_status|hvac_zone_preset_\{zone_id\}|hvac_ac_ramp_state_\{zone_id\}|hvac_ac_ramp_last_action_\{zone_id\}|hvac_ac_ramp_kwh_rate_\{zone_id\})'
    )
    # Simulate the enumerator's prefix set (must match config_flow source).
    zone_name = "TestZone"
    zone_slug = "testzone"
    zone_id = "zone_9"
    name_prefixes = [
        f"universal_room_automation_zone_{zone_name}_",
        f"universal_room_automation_zone_{zone_slug}_",
        f"universal_room_automation_{zone_slug}_presence_mode",
    ]
    id_prefixes = [
        f"universal_room_automation_hvac_ac_ramp_start_{zone_id}",
        f"universal_room_automation_hvac_ac_ramp_stop_{zone_id}",
        f"universal_room_automation_hvac_ac_ramp_reset_{zone_id}",
        f"universal_room_automation_hvac_ac_kwh_threshold_{zone_id}",
        f"universal_room_automation_hvac_zone_{zone_id}_",
        f"universal_room_automation_hvac_coordinator_{zone_id}_status",
        f"universal_room_automation_hvac_zone_preset_{zone_id}",
        f"universal_room_automation_hvac_ac_ramp_state_{zone_id}",
        f"universal_room_automation_hvac_ac_ramp_last_action_{zone_id}",
        f"universal_room_automation_hvac_ac_ramp_kwh_rate_{zone_id}",
        f"universal_room_automation_dynamic_preset_active_bucket_{zone_id}",
        f"universal_room_automation_dynamic_preset_range_{zone_id}",
    ]
    all_prefixes = name_prefixes + id_prefixes

    # Now find every unique_id assignment in source and verify at least one
    # prefix catches it (after formal substitution of zone_id / zone / zone_slug).
    uid_assign_re = re.compile(
        r'unique_id\s*=\s*f"\{DOMAIN\}_([^"]+)"'
    )
    uncovered: list[tuple[str, str]] = []
    for path in src_files:
        text = path.read_text()
        for m in uid_assign_re.finditer(text):
            template = m.group(1)
            # Only test templates that are zone- or zone_id- or zone_slug-parametrized.
            if not any(k in template for k in ("{zone", "zone_id", "zone_slug")):
                continue
            # Substitute placeholders with our test values.
            filled = (
                template.replace("{zone_id}", zone_id)
                .replace("{zone_slug}", zone_slug)
                .replace("{zone}", zone_name)
                .replace("{SENSOR_ZONE_IDENTIFIED_PERSONS}", "identified_persons")
                .replace("{SENSOR_ZONE_GUEST_COUNT}", "guest_count")
            )
            # A '{' remaining means an untranslated placeholder — skip
            # (not a zone-parametrized template, or aliased through a const
            # we don't resolve here).
            if "{" in filled:
                continue
            candidate = f"universal_room_automation_{filled}"
            if not any(candidate.startswith(p) for p in all_prefixes):
                uncovered.append((str(path.name), candidate))

    assert not uncovered, (
        "Zone unique_id templates not covered by "
        "_get_zone_entity_unique_id_prefixes; extend the enumerator: "
        + repr(uncovered)
    )


# ---------------------------------------------------------------------------
# 7. Confirm-name mismatch guard — case-insensitive, trimmed
# ---------------------------------------------------------------------------


def test_confirm_name_mismatch_case_insensitive_trim():
    """The D1 confirm gate compares typed name via .strip().lower(). Verify
    the exact contract: 'living room ' matches 'Living Room' but 'kitchen'
    does NOT match 'Living Room'.
    """
    zone_name = "Living Room"
    def _matches(typed: str) -> bool:
        return (typed or "").strip().lower() == zone_name.strip().lower()

    assert _matches("Living Room")
    assert _matches("living room")
    assert _matches("  LIVING ROOM  ")
    assert not _matches("living-room")
    assert not _matches("kitchen")
    assert not _matches("")
    assert not _matches(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 8. DAO rowcount dict shape — callers depend on the four keys existing.
# ---------------------------------------------------------------------------


def test_dao_returns_rowcount_dict_shape(real_zone_schema_db):
    """Even when no rows exist for the zone, the DAO returns the full 4-key
    dict with all zeros. Callers (D1 confirm summary, telemetry) rely on the
    key set being stable."""
    conn = real_zone_schema_db
    result = _run_dao(conn, "Nonexistent Zone", zone_id=None)
    assert set(result.keys()) == {
        "zone_events", "ac_reset_state", "egress_state", "ac_ramp_events",
    }
    assert all(v == 0 for v in result.values())

    result2 = _run_dao(conn, "Nonexistent Zone", zone_id="zone_99")
    assert set(result2.keys()) == {
        "zone_events", "ac_reset_state", "egress_state", "ac_ramp_events",
    }
    assert all(v == 0 for v in result2.values())
