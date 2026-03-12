"""Database for Universal Room Automation."""
#
# Universal Room Automation v3.10.5
# Build: 2026-01-04
# File: database.py
# v3.3.1.2: Added WAL mode and busy_timeout to fix 'database is locked' errors
# v3.3.1: Added Optional import
#

import logging
import os
import statistics
from datetime import datetime, timedelta
from typing import Any, Optional

import aiosqlite

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DATABASE_DIR,
    DATABASE_NAME,
    MIN_DATA_DAYS_PREDICTION,
)

_LOGGER = logging.getLogger(__name__)


class UniversalRoomDatabase:
    """Manage SQLite database for room automation."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the database."""
        self.hass = hass
        db_dir = hass.config.path(DATABASE_DIR)
        os.makedirs(db_dir, exist_ok=True)
        self.db_file = os.path.join(db_dir, DATABASE_NAME)
        _LOGGER.info("Database file: %s", self.db_file)

    async def initialize(self) -> bool:
        """Initialize database schema."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                # Enable WAL mode for better concurrency (prevents "database is locked")
                await db.execute("PRAGMA journal_mode=WAL")
                await db.execute("PRAGMA busy_timeout=30000")
                
                # Occupancy events table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS occupancy_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        event_type TEXT NOT NULL,
                        trigger_source TEXT,
                        duration INTEGER
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_occupancy_room_time
                    ON occupancy_events(room_id, timestamp)
                """)

                # Environmental data table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS environmental_data (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        temperature REAL,
                        humidity REAL,
                        illuminance REAL,
                        occupied BOOLEAN
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_env_room_time
                    ON environmental_data(room_id, timestamp)
                """)

                # Energy snapshots table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS energy_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        power_watts REAL,
                        occupied BOOLEAN,
                        lights_on INTEGER,
                        fans_on INTEGER,
                        switches_on INTEGER,
                        covers_open INTEGER
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_energy_room_time
                    ON energy_snapshots(room_id, timestamp)
                """)

                # v3.1.0: External conditions table (weather, solar)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS external_conditions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        outside_temp REAL,
                        outside_humidity REAL,
                        weather_condition TEXT,
                        solar_production REAL,
                        forecast_high REAL,
                        forecast_low REAL,
                        occupied_room_count INTEGER,
                        occupied_zone_count INTEGER
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_external_time
                    ON external_conditions(timestamp)
                """)

                # v3.1.0: Zone events table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS zone_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        zone TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        event_type TEXT NOT NULL,
                        room_count INTEGER,
                        rooms TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_zone_time
                    ON zone_events(zone, timestamp)
                """)

                # v3.1.6: Energy history table for predictions
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS energy_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        -- Energy flows (kWh)
                        solar_production REAL,
                        solar_export REAL,
                        grid_import REAL,
                        grid_import_2 REAL,
                        battery_level REAL,
                        whole_house_energy REAL,
                        rooms_energy_total REAL,
                        -- Context for correlation
                        outside_temp REAL,
                        outside_humidity REAL,
                        house_avg_temp REAL,
                        house_avg_humidity REAL,
                        temp_delta_outside REAL,
                        humidity_delta_outside REAL,
                        rooms_occupied INTEGER,
                        -- Temporal
                        day_of_week INTEGER,
                        hour_of_day INTEGER,
                        is_weekend BOOLEAN,
                        UNIQUE(timestamp)
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_energy_history_time
                    ON energy_history(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_energy_history_dow_hour
                    ON energy_history(day_of_week, hour_of_day)
                """)

                # v3.2.0: Person tracking tables
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS person_visits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        person_id TEXT NOT NULL,
                        room_id TEXT NOT NULL,
                        entry_time DATETIME NOT NULL,
                        exit_time DATETIME,
                        duration_seconds INTEGER,
                        confidence REAL,
                        detection_method TEXT,
                        transition_from TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_person_visits_person_time
                    ON person_visits(person_id, entry_time)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_person_visits_room_time
                    ON person_visits(room_id, entry_time)
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS person_presence_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        person_id TEXT NOT NULL,
                        room_id TEXT,
                        confidence REAL,
                        method TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_person_snapshots_time
                    ON person_presence_snapshots(timestamp, person_id)
                """)

                # v3.3.0: Room transitions table for pattern learning
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS room_transitions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        person_id TEXT NOT NULL,
                        from_room TEXT NOT NULL,
                        to_room TEXT NOT NULL,
                        timestamp DATETIME NOT NULL,
                        duration_seconds INTEGER NOT NULL,
                        path_type TEXT NOT NULL,
                        confidence REAL,
                        via_room TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transitions_person
                    ON room_transitions(person_id, timestamp DESC)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transitions_rooms
                    ON room_transitions(from_room, to_room, timestamp DESC)
                """)

                await db.execute("""
                    CREATE TABLE IF NOT EXISTS unknown_devices (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        device_id TEXT NOT NULL,
                        first_seen DATETIME NOT NULL,
                        last_seen DATETIME NOT NULL,
                        room_id TEXT,
                        confidence REAL,
                        UNIQUE(device_id)
                    )
                """)

                # v3.5.0: Census snapshots table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS census_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        zone TEXT NOT NULL,
                        identified_count INTEGER NOT NULL,
                        identified_persons TEXT,
                        unidentified_count INTEGER NOT NULL,
                        total_persons INTEGER NOT NULL,
                        confidence TEXT,
                        source_agreement TEXT,
                        frigate_count INTEGER,
                        unifi_count INTEGER,
                        UNIQUE(timestamp, zone)
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_census_timestamp
                    ON census_snapshots(timestamp)
                """)

                # v3.5.2: person_entry_exit_events table
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS person_entry_exit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME NOT NULL,
                        person_id TEXT,
                        event_type TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        egress_camera TEXT NOT NULL,
                        confidence REAL NOT NULL
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_entry_exit_timestamp
                    ON person_entry_exit_events(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_entry_exit_person
                    ON person_entry_exit_events(person_id, timestamp)
                """)

                # v3.6.0: Decision logging for domain coordinators
                # v3.6.0-c0.4: Added scope column
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS decision_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        decision_type TEXT NOT NULL,
                        scope TEXT NOT NULL DEFAULT 'house',
                        situation_classified TEXT,
                        urgency INTEGER,
                        confidence REAL,
                        context_json TEXT NOT NULL,
                        action_json TEXT NOT NULL,
                        expected_savings_kwh REAL,
                        expected_cost_savings REAL,
                        expected_comfort_impact INTEGER,
                        constraints_published TEXT,
                        devices_commanded TEXT
                    )
                """)
                # v3.6.0-c2.9.1: Migrate scope column BEFORE creating indexes
                # For existing DBs created before c0.4, the scope column doesn't exist yet
                cursor = await db.execute("PRAGMA table_info(decision_log)")
                dl_columns = {row[1] for row in await cursor.fetchall()}
                if "scope" not in dl_columns:
                    await db.execute(
                        "ALTER TABLE decision_log ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"
                    )

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_decision_timestamp
                    ON decision_log(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_decision_coordinator
                    ON decision_log(coordinator_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_decision_scope
                    ON decision_log(scope)
                """)

                # v3.6.0: Compliance tracking for domain coordinators
                # v3.6.0-c0.4: Added scope column
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS compliance_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        decision_id INTEGER,
                        scope TEXT NOT NULL DEFAULT 'house',
                        device_type TEXT NOT NULL,
                        device_id TEXT NOT NULL,
                        commanded_state TEXT NOT NULL,
                        actual_state TEXT NOT NULL,
                        compliant BOOLEAN NOT NULL,
                        deviation_details TEXT,
                        override_detected BOOLEAN,
                        override_source TEXT,
                        override_duration_minutes INTEGER,
                        FOREIGN KEY (decision_id) REFERENCES decision_log(id)
                    )
                """)
                # v3.6.0-c2.9.1: Migrate scope column BEFORE creating indexes
                cursor = await db.execute("PRAGMA table_info(compliance_log)")
                cl_columns = {row[1] for row in await cursor.fetchall()}
                if "scope" not in cl_columns:
                    await db.execute(
                        "ALTER TABLE compliance_log ADD COLUMN scope TEXT NOT NULL DEFAULT 'house'"
                    )

                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_compliance_decision
                    ON compliance_log(decision_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_compliance_timestamp
                    ON compliance_log(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_compliance_scope
                    ON compliance_log(scope)
                """)

                # v3.6.0-c0.4: Anomaly log for coordinator diagnostics
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS anomaly_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        metric_name TEXT NOT NULL,
                        observed_value REAL NOT NULL,
                        expected_mean REAL NOT NULL,
                        expected_std REAL NOT NULL,
                        z_score REAL NOT NULL,
                        severity TEXT NOT NULL,
                        sample_size INTEGER NOT NULL,
                        house_state TEXT,
                        context_json TEXT,
                        resolved BOOLEAN NOT NULL DEFAULT 0,
                        resolution_notes TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anomaly_timestamp
                    ON anomaly_log(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anomaly_coordinator
                    ON anomaly_log(coordinator_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anomaly_scope
                    ON anomaly_log(scope)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_anomaly_severity
                    ON anomaly_log(severity)
                """)

                # v3.6.0-c0.4: Metric baselines for anomaly detection
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS metric_baselines (
                        coordinator_id TEXT NOT NULL,
                        metric_name TEXT NOT NULL,
                        scope TEXT NOT NULL,
                        mean REAL NOT NULL,
                        variance REAL NOT NULL,
                        sample_count INTEGER NOT NULL,
                        last_updated TEXT,
                        PRIMARY KEY (coordinator_id, metric_name, scope)
                    )
                """)

                # v3.6.0-c0.4: Outcome log for coordinator effectiveness
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS outcome_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        scope TEXT NOT NULL DEFAULT 'house',
                        period_start TEXT NOT NULL,
                        period_end TEXT NOT NULL,
                        decisions_in_period INTEGER,
                        compliance_rate REAL,
                        override_count INTEGER,
                        metrics_json TEXT NOT NULL
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_outcome_coordinator
                    ON outcome_log(coordinator_id)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_outcome_scope
                    ON outcome_log(scope)
                """)

                # v3.6.0-c0.4: Bayesian parameter beliefs
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS parameter_beliefs (
                        coordinator_id TEXT NOT NULL,
                        parameter_name TEXT NOT NULL,
                        mean REAL NOT NULL,
                        std REAL NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (coordinator_id, parameter_name)
                    )
                """)

                # v3.6.0-c0.4: Parameter change history
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS parameter_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        parameter_name TEXT NOT NULL,
                        old_value REAL,
                        new_value REAL NOT NULL,
                        reason TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_param_history
                    ON parameter_history(coordinator_id, parameter_name)
                """)

                # v3.6.29: Notification Manager log
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS notification_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        coordinator_id TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        hazard_type TEXT,
                        location TEXT,
                        person_id TEXT,
                        channel TEXT,
                        delivered INTEGER DEFAULT 0,
                        acknowledged INTEGER DEFAULT 0,
                        ack_time TEXT,
                        cooldown_expires TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_log_date
                    ON notification_log(timestamp)
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_log_pending
                    ON notification_log(person_id, delivered, severity)
                """)

                # v3.9.7 C4b: Notification inbound message log
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS notification_inbound (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        person_id TEXT,
                        channel TEXT NOT NULL,
                        raw_text TEXT NOT NULL,
                        parsed_command TEXT,
                        response_text TEXT,
                        alert_id INTEGER,
                        success INTEGER NOT NULL DEFAULT 0
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_notification_inbound_date
                    ON notification_inbound(timestamp)
                """)

                # v3.6.0: House state history
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS house_state_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        state TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        trigger TEXT,
                        previous_state TEXT
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_house_state_timestamp
                    ON house_state_log(timestamp)
                """)

                # v3.7.11: Daily energy billing snapshots
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS energy_daily (
                        date TEXT PRIMARY KEY,
                        import_kwh REAL NOT NULL DEFAULT 0,
                        export_kwh REAL NOT NULL DEFAULT 0,
                        import_cost REAL NOT NULL DEFAULT 0,
                        export_credit REAL NOT NULL DEFAULT 0,
                        net_cost REAL NOT NULL DEFAULT 0,
                        consumption_kwh REAL,
                        solar_production_kwh REAL
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_energy_daily_date
                    ON energy_daily(date DESC)
                """)

                await db.commit()

                # v3.5.2: PRAGMA-based migration — add columns to room_transitions if absent
                cursor = await db.execute("PRAGMA table_info(room_transitions)")
                columns = {row[1] for row in await cursor.fetchall()}

                if "validation_method" not in columns:
                    await db.execute(
                        "ALTER TABLE room_transitions ADD COLUMN validation_method TEXT"
                    )
                if "checkpoint_rooms" not in columns:
                    await db.execute(
                        "ALTER TABLE room_transitions ADD COLUMN checkpoint_rooms TEXT"
                    )
                await db.commit()

                # v3.9.12: Peak import history for load shedding auto-learning
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS energy_peak_import (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        seq INTEGER NOT NULL,
                        import_kw REAL NOT NULL
                    )
                """)
                await db.execute("""
                    CREATE INDEX IF NOT EXISTS idx_energy_peak_import_seq
                    ON energy_peak_import(seq ASC)
                """)
                await db.commit()

                # v3.7.12: Add accuracy + temperature columns to energy_daily
                cursor = await db.execute("PRAGMA table_info(energy_daily)")
                ed_columns = {row[1] for row in await cursor.fetchall()}
                for col, col_type in [
                    ("predicted_consumption_kwh", "REAL"),
                    ("avg_temperature", "REAL"),
                    ("prediction_error_pct", "REAL"),
                    ("adjustment_factor", "REAL"),
                ]:
                    if col not in ed_columns:
                        await db.execute(
                            f"ALTER TABLE energy_daily ADD COLUMN {col} {col_type}"
                        )
                await db.commit()

                _LOGGER.info("Database initialized successfully")
                return True
        except Exception as e:
            _LOGGER.error("Error initializing database: %s", e)
            return False

    async def log_occupancy_event(
        self,
        room_id: str,
        event_type: str,
        trigger_source: str | None = None,
        duration: int | None = None,
    ) -> None:
        """Log occupancy event."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO occupancy_events (room_id, timestamp, event_type, trigger_source, duration)
                    VALUES (?, ?, ?, ?, ?)
                """, (room_id, datetime.utcnow().isoformat(), event_type, trigger_source, duration))
                await db.commit()
                _LOGGER.debug("Logged occupancy event for room %s: %s (trigger=%s)", room_id, event_type, trigger_source)
        except Exception as e:
            _LOGGER.error("Error logging occupancy event: %s", e)

    async def log_environmental_data(self, room_id: str, data: dict[str, Any]) -> None:
        """Log environmental snapshot."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO environmental_data (room_id, timestamp, temperature, humidity, illuminance, occupied)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    room_id,
                    datetime.utcnow().isoformat(),
                    data.get('temperature'),
                    data.get('humidity'),
                    data.get('illuminance'),
                    data.get('occupied'),
                ))
                await db.commit()
                _LOGGER.debug("Logged environmental data for room %s: temp=%.1f, humidity=%.1f", 
                             room_id, data.get('temperature', 0), data.get('humidity', 0))
        except Exception as e:
            _LOGGER.error("Error logging environmental data: %s", e)

    async def log_energy_snapshot(self, room_id: str, data: dict[str, Any]) -> None:
        """Log energy snapshot."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO energy_snapshots (
                        room_id, timestamp, power_watts, occupied,
                        lights_on, fans_on, switches_on, covers_open
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    room_id,
                    datetime.utcnow().isoformat(),
                    data.get('power_watts'),
                    data.get('occupied'),
                    data.get('lights_on'),
                    data.get('fans_on'),
                    data.get('switches_on'),
                    data.get('covers_open'),
                ))
                await db.commit()
                _LOGGER.debug("Logged energy snapshot for room %s: power=%.1fW", room_id, data.get('power_watts', 0))
        except Exception as e:
            _LOGGER.error("Error logging energy snapshot: %s", e)

    async def log_external_conditions(self, data: dict[str, Any]) -> None:
        """Log external conditions snapshot (weather, solar, occupancy counts)."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO external_conditions (
                        timestamp, outside_temp, outside_humidity, weather_condition,
                        solar_production, forecast_high, forecast_low,
                        occupied_room_count, occupied_zone_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    data.get('outside_temp'),
                    data.get('outside_humidity'),
                    data.get('weather_condition'),
                    data.get('solar_production'),
                    data.get('forecast_high'),
                    data.get('forecast_low'),
                    data.get('occupied_room_count'),
                    data.get('occupied_zone_count'),
                ))
                await db.commit()
                _LOGGER.debug(
                    "Logged external conditions: temp=%.1f, rooms=%d, zones=%d",
                    data.get('outside_temp', 0),
                    data.get('occupied_room_count', 0),
                    data.get('occupied_zone_count', 0)
                )
        except Exception as e:
            _LOGGER.error("Error logging external conditions: %s", e)

    async def log_zone_event(
        self,
        zone: str,
        event_type: str,
        room_count: int = 0,
        rooms: list[str] | None = None,
    ) -> None:
        """Log zone occupancy event."""
        try:
            rooms_str = ",".join(rooms) if rooms else None
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO zone_events (zone, timestamp, event_type, room_count, rooms)
                    VALUES (?, ?, ?, ?, ?)
                """, (zone, datetime.utcnow().isoformat(), event_type, room_count, rooms_str))
                await db.commit()
                _LOGGER.debug("Logged zone event: %s -> %s (%d rooms)", zone, event_type, room_count)
        except Exception as e:
            _LOGGER.error("Error logging zone event: %s", e)

    # =========================================================================
    # v3.6.0: DOMAIN COORDINATOR DECISION LOGGING
    # =========================================================================

    async def log_coordinator_decision(
        self,
        coordinator_id: str,
        decision_type: str,
        context_json: str,
        action_json: str,
        situation_classified: str | None = None,
        urgency: int | None = None,
        confidence: float | None = None,
        expected_savings_kwh: float | None = None,
        expected_cost_savings: float | None = None,
        expected_comfort_impact: int | None = None,
        constraints_published: str | None = None,
        devices_commanded: str | None = None,
    ) -> int | None:
        """Log a coordinator decision. Returns the decision_log row id."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    INSERT INTO decision_log (
                        timestamp, coordinator_id, decision_type,
                        situation_classified, urgency, confidence,
                        context_json, action_json,
                        expected_savings_kwh, expected_cost_savings,
                        expected_comfort_impact, constraints_published,
                        devices_commanded
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    coordinator_id, decision_type,
                    situation_classified, urgency, confidence,
                    context_json, action_json,
                    expected_savings_kwh, expected_cost_savings,
                    expected_comfort_impact, constraints_published,
                    devices_commanded,
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error logging coordinator decision: %s", e)
            return None

    async def log_compliance_check(
        self,
        decision_id: int | None,
        device_type: str,
        device_id: str,
        commanded_state: str,
        actual_state: str,
        compliant: bool,
        deviation_details: str | None = None,
        override_detected: bool = False,
        override_source: str | None = None,
        override_duration_minutes: int | None = None,
        scope: str = "house",
    ) -> None:
        """Log a compliance check result."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO compliance_log (
                        timestamp, decision_id, scope, device_type, device_id,
                        commanded_state, actual_state, compliant,
                        deviation_details, override_detected,
                        override_source, override_duration_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    decision_id, scope, device_type, device_id,
                    commanded_state, actual_state, compliant,
                    deviation_details, override_detected,
                    override_source, override_duration_minutes,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error logging compliance check: %s", e)

    async def log_house_state_change(
        self,
        state: str,
        confidence: float,
        trigger: str | None = None,
        previous_state: str | None = None,
    ) -> None:
        """Log a house state transition."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO house_state_log (
                        timestamp, state, confidence, trigger, previous_state
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    state, confidence, trigger, previous_state,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error logging house state change: %s", e)

    # =========================================================================
    # v3.1.6: ENERGY HISTORY LOGGING AND QUERIES
    # =========================================================================

    async def log_energy_history(self, data: dict[str, Any]) -> None:
        """Log energy history snapshot for predictions (every 15 minutes)."""
        try:
            now = datetime.utcnow()
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO energy_history (
                        timestamp, solar_production, solar_export, grid_import, grid_import_2,
                        battery_level, whole_house_energy, rooms_energy_total,
                        outside_temp, outside_humidity, house_avg_temp, house_avg_humidity,
                        temp_delta_outside, humidity_delta_outside, rooms_occupied,
                        day_of_week, hour_of_day, is_weekend
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    now.isoformat(),
                    data.get('solar_production'),
                    data.get('solar_export'),
                    data.get('grid_import'),
                    data.get('grid_import_2'),
                    data.get('battery_level'),
                    data.get('whole_house_energy'),
                    data.get('rooms_energy_total'),
                    data.get('outside_temp'),
                    data.get('outside_humidity'),
                    data.get('house_avg_temp'),
                    data.get('house_avg_humidity'),
                    data.get('temp_delta_outside'),
                    data.get('humidity_delta_outside'),
                    data.get('rooms_occupied'),
                    now.weekday(),  # 0=Monday, 6=Sunday
                    now.hour,
                    now.weekday() >= 5,  # Saturday=5, Sunday=6
                ))
                await db.commit()
                _LOGGER.debug(
                    "Logged energy history: grid=%.2f kWh, solar_export=%.2f kWh",
                    data.get('grid_import', 0) or 0,
                    data.get('solar_export', 0) or 0
                )
        except Exception as e:
            _LOGGER.error("Error logging energy history: %s", e)

    async def get_days_of_energy_data(self) -> int:
        """Get number of days of energy history data available."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT MIN(timestamp), MAX(timestamp)
                    FROM energy_history
                """)
                row = await cursor.fetchone()
                if row and row[0] and row[1]:
                    min_date = datetime.fromisoformat(row[0])
                    max_date = datetime.fromisoformat(row[1])
                    return (max_date - min_date).days
                return 0
        except Exception as e:
            _LOGGER.error("Error getting days of energy data: %s", e)
            return 0

    async def get_energy_for_similar_days(
        self,
        day_of_week: int,
        temp_low: float,
        temp_high: float,
        limit: int = 10
    ) -> list[dict]:
        """Get energy data for similar days (same weekday, similar temperature)."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT 
                        DATE(timestamp) as date,
                        SUM(CASE WHEN grid_import IS NOT NULL THEN grid_import ELSE 0 END) as total_grid_import,
                        SUM(CASE WHEN solar_export IS NOT NULL THEN solar_export ELSE 0 END) as total_solar_export,
                        AVG(outside_temp) as avg_temp,
                        AVG(rooms_occupied) as avg_occupancy
                    FROM energy_history
                    WHERE day_of_week = ?
                    AND outside_temp BETWEEN ? AND ?
                    GROUP BY DATE(timestamp)
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (day_of_week, temp_low, temp_high, limit))
                
                rows = await cursor.fetchall()
                return [
                    {
                        'date': row[0],
                        'grid_import': row[1] or 0,
                        'solar_export': row[2] or 0,
                        'net_energy': (row[1] or 0) - (row[2] or 0),
                        'avg_temp': row[3],
                        'avg_occupancy': row[4],
                    }
                    for row in rows
                ]
        except Exception as e:
            _LOGGER.error("Error getting similar days energy data: %s", e)
            return []

    async def get_energy_for_date_range(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> dict[str, float]:
        """Get total energy values for a date range."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT 
                        SUM(CASE WHEN grid_import IS NOT NULL THEN grid_import ELSE 0 END) as total_grid_import,
                        SUM(CASE WHEN solar_export IS NOT NULL THEN solar_export ELSE 0 END) as total_solar_export,
                        SUM(CASE WHEN solar_production IS NOT NULL THEN solar_production ELSE 0 END) as total_solar_production,
                        AVG(outside_temp) as avg_temp,
                        AVG(rooms_occupied) as avg_occupancy,
                        COUNT(*) as record_count
                    FROM energy_history
                    WHERE timestamp BETWEEN ? AND ?
                """, (start_date.isoformat(), end_date.isoformat()))
                
                row = await cursor.fetchone()
                if row:
                    return {
                        'grid_import': row[0] or 0,
                        'solar_export': row[1] or 0,
                        'solar_production': row[2] or 0,
                        'net_energy': (row[0] or 0) - (row[1] or 0),
                        'avg_temp': row[3],
                        'avg_occupancy': row[4],
                        'record_count': row[5],
                    }
                return {'grid_import': 0, 'solar_export': 0, 'net_energy': 0}
        except Exception as e:
            _LOGGER.error("Error getting energy for date range: %s", e)
            return {'grid_import': 0, 'solar_export': 0, 'net_energy': 0}

    async def get_recent_weeks_energy(self, num_weeks: int = 4) -> list[dict]:
        """Get weekly energy totals for recent weeks."""
        try:
            results = []
            now = datetime.utcnow()
            
            for week_offset in range(num_weeks):
                # Calculate week start/end
                week_start = now - timedelta(days=now.weekday() + (week_offset * 7))
                week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
                week_end = week_start + timedelta(days=7)
                
                data = await self.get_energy_for_date_range(week_start, week_end)
                data['week_start'] = week_start.isoformat()
                data['week_end'] = week_end.isoformat()
                results.append(data)
            
            return results
        except Exception as e:
            _LOGGER.error("Error getting recent weeks energy: %s", e)
            return []

    async def get_recent_months_energy(self, num_months: int = 3) -> list[dict]:
        """Get monthly energy totals for recent months."""
        try:
            results = []
            now = datetime.utcnow()
            
            for month_offset in range(num_months):
                # Calculate month start/end
                year = now.year
                month = now.month - month_offset
                while month <= 0:
                    month += 12
                    year -= 1
                
                month_start = datetime(year, month, 1)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1)
                else:
                    month_end = datetime(year, month + 1, 1)
                
                data = await self.get_energy_for_date_range(month_start, month_end)
                data['month_start'] = month_start.isoformat()
                data['month_end'] = month_end.isoformat()
                results.append(data)
            
            return results
        except Exception as e:
            _LOGGER.error("Error getting recent months energy: %s", e)
            return []

    async def predict_energy(
        self,
        period: str,
        forecast_temp: float | None = None
    ) -> tuple[float | None, int]:
        """
        Predict energy needs for period.
        
        Args:
            period: "day", "week", or "month"
            forecast_temp: Expected average temperature for period
            
        Returns:
            Tuple of (predicted_kwh, confidence_percent) or (None, 0) if insufficient data
        """
        try:
            # Check data sufficiency
            days_of_data = await self.get_days_of_energy_data()
            if days_of_data < MIN_DATA_DAYS_PREDICTION:
                return (None, 0)
            
            now = datetime.utcnow()
            
            if period == "day":
                # Get similar days (same weekday, similar temp)
                temp_range = 10  # +/- 10 degrees
                if forecast_temp is None:
                    forecast_temp = 70  # Default assumption
                
                historical = await self.get_energy_for_similar_days(
                    day_of_week=now.weekday(),
                    temp_low=forecast_temp - temp_range,
                    temp_high=forecast_temp + temp_range,
                    limit=10
                )
                
                if len(historical) < 3:
                    # Not enough similar days, get any recent data
                    yesterday = now - timedelta(days=1)
                    week_ago = now - timedelta(days=7)
                    data = await self.get_energy_for_date_range(week_ago, yesterday)
                    if data.get('record_count', 0) > 0:
                        # Estimate daily from weekly average
                        daily_avg = data['net_energy'] / 7
                        return (round(daily_avg, 1), 40)  # Low confidence
                    return (None, 0)
                
                values = [h['net_energy'] for h in historical]
                
            elif period == "week":
                historical = await self.get_recent_weeks_energy(4)
                if len(historical) < 2:
                    return (None, 0)
                values = [h['net_energy'] for h in historical if h.get('record_count', 0) > 0]
                
            elif period == "month":
                historical = await self.get_recent_months_energy(3)
                if len(historical) < 2:
                    return (None, 0)
                values = [h['net_energy'] for h in historical if h.get('record_count', 0) > 0]
            
            else:
                return (None, 0)
            
            if not values or len(values) < 2:
                return (None, 0)
            
            # Calculate prediction
            predicted = statistics.mean(values)
            
            # Calculate confidence based on consistency (coefficient of variation)
            std_dev = statistics.stdev(values)
            cv = std_dev / abs(predicted) if predicted != 0 else 1
            confidence = max(0, min(100, int((1 - cv) * 100)))
            
            # Adjust confidence based on data quantity
            data_factor = min(1.0, days_of_data / 30)  # Full confidence at 30 days
            confidence = int(confidence * data_factor)
            
            return (round(predicted, 1), confidence)
            
        except Exception as e:
            _LOGGER.error("Error predicting energy: %s", e)
            return (None, 0)

    # =========================================================================
    # EXISTING QUERIES (unchanged)
    # =========================================================================

    async def get_external_conditions_history(self, hours: int = 24) -> list[dict]:
        """Get external conditions history for predictions."""
        try:
            cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT timestamp, outside_temp, outside_humidity, weather_condition,
                           solar_production, forecast_high, forecast_low,
                           occupied_room_count, occupied_zone_count
                    FROM external_conditions
                    WHERE timestamp > ?
                    ORDER BY timestamp ASC
                """, (cutoff,))
                rows = await cursor.fetchall()
                return [
                    {
                        'timestamp': row[0],
                        'outside_temp': row[1],
                        'outside_humidity': row[2],
                        'weather_condition': row[3],
                        'solar_production': row[4],
                        'forecast_high': row[5],
                        'forecast_low': row[6],
                        'occupied_room_count': row[7],
                        'occupied_zone_count': row[8],
                    }
                    for row in rows
                ]
        except Exception as e:
            _LOGGER.error("Error getting external conditions history: %s", e)
            return []

    async def get_recent_data(self, room_id: str, limit: int = 100) -> dict[str, list]:
        """Get recent data for export."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                # Get occupancy events
                cursor = await db.execute("""
                    SELECT timestamp, event_type, trigger_source, duration
                    FROM occupancy_events
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                occupancy_rows = await cursor.fetchall()
                
                # Get environmental data
                cursor = await db.execute("""
                    SELECT timestamp, temperature, humidity, illuminance, occupied
                    FROM environmental_data
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                env_rows = await cursor.fetchall()
                
                # Get energy snapshots
                cursor = await db.execute("""
                    SELECT timestamp, power_watts, occupied, lights_on, fans_on, switches_on, covers_open
                    FROM energy_snapshots
                    WHERE room_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (room_id, limit))
                energy_rows = await cursor.fetchall()
                
                return {
                    "occupancy": occupancy_rows,
                    "environmental": env_rows,
                    "energy": energy_rows
                }
        except Exception as e:
            _LOGGER.error("Error querying data for export: %s", e)
            return {"occupancy": [], "environmental": [], "energy": []}

    async def get_table_counts(self, room_id: str) -> dict[str, int]:
        """Get row counts for each table for a specific room."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                counts = {}
                
                cursor = await db.execute("SELECT COUNT(*) FROM occupancy_events WHERE room_id = ?", (room_id,))
                counts["occupancy_events"] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM environmental_data WHERE room_id = ?", (room_id,))
                counts["environmental_data"] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM energy_snapshots WHERE room_id = ?", (room_id,))
                counts["energy_snapshots"] = (await cursor.fetchone())[0]
                
                # v3.1.6: Add energy history count (global, not per-room)
                cursor = await db.execute("SELECT COUNT(*) FROM energy_history")
                counts["energy_history"] = (await cursor.fetchone())[0]
                
                return counts
        except Exception as e:
            _LOGGER.error("Error getting table counts: %s", e)
            return {"occupancy_events": 0, "environmental_data": 0, "energy_snapshots": 0, "energy_history": 0}

    # =========================================================================
    # PHASE 2: ENERGY QUERIES
    # =========================================================================

    async def get_energy_for_period(
        self, 
        room_id: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> float:
        """
        Calculate energy consumption for a time period.
        Integrates power readings over time (trapezoid rule).
        Returns kWh.
        """
        try:
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT timestamp, power_watts
                    FROM energy_snapshots
                    WHERE room_id = ? 
                    AND timestamp >= ? 
                    AND timestamp <= ?
                    ORDER BY timestamp ASC
                """, (room_id, start_time.isoformat(), end_time.isoformat()))
                
                rows = await cursor.fetchall()
                
                if len(rows) < 2:
                    return 0.0
                
                # Integrate power over time using trapezoid rule
                total_wh = 0.0
                for i in range(len(rows) - 1):
                    ts1 = datetime.fromisoformat(rows[i][0])
                    ts2 = datetime.fromisoformat(rows[i + 1][0])
                    power1 = rows[i][1] or 0
                    power2 = rows[i + 1][1] or 0
                    
                    # Time difference in hours
                    hours = (ts2 - ts1).total_seconds() / 3600
                    
                    # Average power * time = energy
                    avg_power = (power1 + power2) / 2
                    total_wh += avg_power * hours
                
                return total_wh / 1000  # Convert Wh to kWh
                
        except Exception as e:
            _LOGGER.error("Error calculating energy for period: %s", e)
            return 0.0

    # =========================================================================
    # PHASE 3: OCCUPANCY PREDICTION QUERIES
    # =========================================================================

    async def get_occupancy_percentage(self, room_id: str, days: int = 7) -> float | None:
        """
        Calculate percentage of time room was occupied over the last N days.
        Returns percentage (0-100) or None if insufficient data.
        """
        try:
            cutoff = dt_util.now() - timedelta(days=days)
            
            async with aiosqlite.connect(self.db_file) as db:
                # Get all entry/exit events in period
                cursor = await db.execute("""
                    SELECT timestamp, event_type, duration
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (room_id, cutoff.isoformat()))
                
                events = await cursor.fetchall()
                
                if not events:
                    return None
                
                # Calculate total occupied time
                total_occupied_seconds = 0
                current_entry_time = None
                
                for event in events:
                    timestamp = datetime.fromisoformat(event[0])
                    event_type = event[1]
                    duration = event[2]
                    
                    if event_type == "entry":
                        current_entry_time = timestamp
                    elif event_type == "exit" and duration:
                        total_occupied_seconds += duration
                
                # Calculate percentage
                total_period_seconds = days * 24 * 3600
                percentage = (total_occupied_seconds / total_period_seconds) * 100
                
                return min(100.0, max(0.0, percentage))
                
        except Exception as e:
            _LOGGER.error("Error calculating occupancy percentage: %s", e)
            return None

    async def get_peak_occupancy_hour(self, room_id: str, days: int = 7) -> int | None:
        """
        Find the hour of day (0-23) when room is most frequently occupied.
        Returns hour or None if insufficient data.
        """
        try:
            cutoff = dt_util.now() - timedelta(days=days)
            
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT timestamp
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND event_type = 'entry'
                    AND timestamp >= ?
                """, (room_id, cutoff.isoformat()))
                
                events = await cursor.fetchall()
                
                if not events:
                    return None
                
                # Count entries by hour
                hour_counts = [0] * 24
                for event in events:
                    timestamp = datetime.fromisoformat(event[0])
                    hour_counts[timestamp.hour] += 1
                
                # Find peak hour
                peak_hour = hour_counts.index(max(hour_counts))
                
                return peak_hour if max(hour_counts) > 0 else None
                
        except Exception as e:
            _LOGGER.error("Error finding peak occupancy hour: %s", e)
            return None

    async def get_next_occupancy_prediction(self, room_id: str) -> tuple[datetime, float] | None:
        """
        Predict next occupancy time based on recent patterns.
        Returns (predicted_time, confidence) or None if insufficient data.
        Confidence is 0-100.
        """
        try:
            # Get entry events for last 7 days
            cutoff = dt_util.now() - timedelta(days=7)
            
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    SELECT timestamp
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND event_type = 'entry'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (room_id, cutoff.isoformat()))
                
                events = await cursor.fetchall()
                
                if len(events) < 3:
                    return None
                
                now = dt_util.now()
                current_hour = now.hour
                current_weekday = now.weekday()
                
                # Group entries by hour and weekday
                hour_entries = {}
                for event in events:
                    timestamp = datetime.fromisoformat(event[0])
                    # Only consider future hours today or any hour on future days
                    if timestamp.weekday() == current_weekday and timestamp.hour > current_hour:
                        key = (timestamp.weekday(), timestamp.hour)
                        if key not in hour_entries:
                            hour_entries[key] = 0
                        hour_entries[key] += 1
                
                if not hour_entries:
                    # No entries later today, check tomorrow
                    tomorrow_weekday = (current_weekday + 1) % 7
                    for event in events:
                        timestamp = datetime.fromisoformat(event[0])
                        if timestamp.weekday() == tomorrow_weekday:
                            key = (timestamp.weekday(), timestamp.hour)
                            if key not in hour_entries:
                                hour_entries[key] = 0
                            hour_entries[key] += 1
                
                if not hour_entries:
                    return None
                
                # Find most common next entry time
                most_common = max(hour_entries.items(), key=lambda x: x[1])
                (pred_weekday, pred_hour), count = most_common
                
                # Calculate next occurrence of this weekday/hour
                days_ahead = (pred_weekday - current_weekday) % 7
                if days_ahead == 0 and pred_hour <= current_hour:
                    days_ahead = 7
                
                next_time = now.replace(hour=pred_hour, minute=0, second=0, microsecond=0)
                next_time += timedelta(days=days_ahead)
                
                # Confidence based on consistency (how many times vs total)
                confidence = min(100, (count / len(events)) * 100 * 7)  # Scale up for weekly pattern
                
                return (next_time, confidence)
                
        except Exception as e:
            _LOGGER.error("Error predicting next occupancy: %s", e)
            return None

    async def get_avg_time_to_comfort(self, room_id: str, days: int = 14) -> int | None:
        """
        Calculate average time (minutes) from occupancy to reaching comfort zone.
        This is for precool/preheat lead time calculation.
        Returns minutes or None if insufficient data.
        """
        try:
            cutoff = dt_util.now() - timedelta(days=days)
            
            async with aiosqlite.connect(self.db_file) as db:
                # Get occupancy events
                cursor = await db.execute("""
                    SELECT timestamp
                    FROM occupancy_events
                    WHERE room_id = ? 
                    AND event_type = 'entry'
                    AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (room_id, cutoff.isoformat()))
                
                entry_events = await cursor.fetchall()
                
                if not entry_events:
                    return None
                
                # For each entry, find when temperature reached comfort zone
                # Comfort zone defined in const.py: 68-76°F, 30-60% humidity
                times_to_comfort = []
                
                for entry in entry_events:
                    entry_time = datetime.fromisoformat(entry[0])
                    
                    # Get environmental data after entry
                    cursor = await db.execute("""
                        SELECT timestamp, temperature, humidity
                        FROM environmental_data
                        WHERE room_id = ?
                        AND timestamp >= ?
                        AND timestamp <= ?
                        AND temperature IS NOT NULL
                        ORDER BY timestamp ASC
                    """, (
                        room_id,
                        entry_time.isoformat(),
                        (entry_time + timedelta(hours=2)).isoformat()
                    ))
                    
                    env_data = await cursor.fetchall()
                    
                    # Find first reading in comfort zone
                    for reading in env_data:
                        timestamp = datetime.fromisoformat(reading[0])
                        temp = reading[1]
                        humidity = reading[2] or 50  # Default if None
                        
                        # Check if in comfort zone (68-76°F, 30-60%)
                        if 68 <= temp <= 76 and 30 <= humidity <= 60:
                            minutes = (timestamp - entry_time).total_seconds() / 60
                            times_to_comfort.append(minutes)
                            break
                
                if not times_to_comfort:
                    return None
                
                # Return average
                return int(sum(times_to_comfort) / len(times_to_comfort))
                
        except Exception as e:
            _LOGGER.error("Error calculating time to comfort: %s", e)
            return None

    # =========================================================================
    # v3.2.0: PERSON TRACKING METHODS
    # =========================================================================

    async def log_person_entry(
        self,
        person_id: str,
        room_id: str,
        confidence: float,
        detection_method: str,
        transition_from: str | None = None
    ) -> int:
        """Log person entering a room."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    INSERT INTO person_visits 
                    (person_id, room_id, entry_time, confidence, detection_method, transition_from)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    person_id,
                    room_id,
                    datetime.now(),
                    confidence,
                    detection_method,
                    transition_from
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Failed to log person entry: %s", e)
            return -1

    async def log_person_exit(
        self,
        visit_id: int,
        exit_time: datetime | None = None
    ) -> None:
        """Log person exiting a room."""
        try:
            if exit_time is None:
                exit_time = datetime.now()

            async with aiosqlite.connect(self.db_file) as db:
                # Update exit time and calculate duration
                await db.execute("""
                    UPDATE person_visits 
                    SET exit_time = ?,
                        duration_seconds = (
                            CAST((julianday(?) - julianday(entry_time)) * 86400 AS INTEGER)
                        )
                    WHERE id = ?
                """, (exit_time, exit_time, visit_id))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Failed to log person exit: %s", e)

    async def log_person_snapshot(
        self,
        person_id: str,
        room_id: str | None,
        confidence: float,
        method: str
    ) -> None:
        """Log periodic person presence snapshot."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO person_presence_snapshots 
                    (timestamp, person_id, room_id, confidence, method)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    datetime.now(),
                    person_id,
                    room_id,
                    confidence,
                    method
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Failed to log person snapshot: %s", e)

    async def get_person_last_location(self, person_id: str) -> dict[str, Any] | None:
        """Get person's last known location."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT room_id, entry_time, confidence, detection_method
                    FROM person_visits
                    WHERE person_id = ?
                    AND exit_time IS NULL
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, (person_id,))

                row = await cursor.fetchone()

                if row:
                    return {
                        'room_id': row['room_id'],
                        'entry_time': row['entry_time'],
                        'confidence': row['confidence'],
                        'method': row['detection_method']
                    }

                return None

        except Exception as e:
            _LOGGER.error("Failed to get person last location: %s", e)
            return None

    async def get_active_visit_id(self, person_id: str, room_id: str) -> int | None:
        """Get ID of person's active visit in room."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT id
                    FROM person_visits
                    WHERE person_id = ? 
                    AND room_id = ?
                    AND exit_time IS NULL
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, (person_id, room_id))

                row = await cursor.fetchone()

                if row:
                    return row['id']

                return None

        except Exception as e:
            _LOGGER.error("Failed to get active visit ID: %s", e)
            return None

    async def get_room_occupants(self, room_id: str) -> list[dict[str, Any]]:
        """Get list of people currently in room."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT person_id, entry_time, confidence, detection_method
                    FROM person_visits
                    WHERE room_id = ?
                    AND exit_time IS NULL
                    ORDER BY entry_time DESC
                """, (room_id,))

                rows = await cursor.fetchall()

                return [
                    {
                        'person_id': row['person_id'],
                        'entry_time': row['entry_time'],
                        'confidence': row['confidence'],
                        'method': row['detection_method']
                    }
                    for row in rows
                ]

        except Exception as e:
            _LOGGER.error("Failed to get room occupants: %s", e)
            return []

    async def log_unknown_device(
        self,
        device_id: str,
        room_id: str,
        confidence: float
    ) -> None:
        """Log unknown device detection (passive tracking)."""
        try:
            now = datetime.now()

            async with aiosqlite.connect(self.db_file) as db:
                # Insert or update
                await db.execute("""
                    INSERT INTO unknown_devices (device_id, first_seen, last_seen, room_id, confidence)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        last_seen = ?,
                        room_id = ?,
                        confidence = ?
                """, (device_id, now, now, room_id, confidence, now, room_id, confidence))

                await db.commit()
        except Exception as e:
            _LOGGER.error("Failed to log unknown device: %s", e)

    async def cleanup_person_data(self, retention_days: int) -> None:
        """Remove person tracking data older than retention period."""
        if retention_days == 0:
            return  # 0 = infinite retention

        try:
            cutoff_date = datetime.now() - timedelta(days=retention_days)

            async with aiosqlite.connect(self.db_file) as db:
                # Clean person visits
                await db.execute("""
                    DELETE FROM person_visits WHERE entry_time < ?
                """, (cutoff_date,))

                # Clean person snapshots
                await db.execute("""
                    DELETE FROM person_presence_snapshots WHERE timestamp < ?
                """, (cutoff_date,))

                # Clean old unknown devices
                await db.execute("""
                    DELETE FROM unknown_devices WHERE last_seen < ?
                """, (cutoff_date,))

                await db.commit()

                _LOGGER.debug("Cleaned person data older than %d days", retention_days)

        except Exception as e:
            _LOGGER.error("Failed to cleanup person data: %s", e)

    async def get_zone_last_occupant(
        self,
        zone_rooms: list[str]
    ) -> dict[str, Any] | None:
        """Get last occupant across multiple rooms in a zone.
        
        Args:
            zone_rooms: List of room IDs/names in the zone
            
        Returns:
            Dict with person_id, entry_time, room_id or None if no visits found
        """
        if not zone_rooms:
            return None
            
        try:
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                
                # Build query with parameterized placeholders
                placeholders = ','.join('?' * len(zone_rooms))
                cursor = await db.execute(f"""
                    SELECT person_id, entry_time, room_id
                    FROM person_visits
                    WHERE room_id IN ({placeholders})
                    ORDER BY entry_time DESC
                    LIMIT 1
                """, zone_rooms)
                
                row = await cursor.fetchone()
                
                if row:
                    return {
                        'person_id': row['person_id'],
                        'entry_time': row['entry_time'],
                        'room_id': row['room_id']
                    }
                
                return None
                
        except Exception as e:
            _LOGGER.error("Failed to get zone last occupant: %s", e)
            return None

    # v3.3.0: Room transition methods for pattern learning

    async def log_transition(
        self,
        person_id: str,
        from_room: str,
        to_room: str,
        timestamp: datetime,
        duration_seconds: int,
        path_type: str,
        confidence: float,
        via_room: Optional[str] = None
    ) -> None:
        """Log a room-to-room transition."""
        try:
            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT INTO room_transitions 
                    (person_id, from_room, to_room, timestamp, 
                     duration_seconds, path_type, confidence, via_room)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    person_id,
                    from_room,
                    to_room,
                    timestamp,
                    duration_seconds,
                    path_type,
                    confidence,
                    via_room
                ))
                await db.commit()
                
            _LOGGER.debug(
                "Transition logged to DB: %s %s → %s (%s, %ds)",
                person_id, from_room, to_room, path_type, duration_seconds
            )
        except Exception as e:
            _LOGGER.error("Failed to log transition: %s", e)

    async def get_transitions(
        self,
        person_id: str,
        days: int = 30,
        hours: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Get transitions for a person.
        
        Args:
            person_id: Person to query
            days: Days to look back (if hours not specified)
            hours: Hours to look back (overrides days if specified)
            
        Returns:
            List of transition dicts with keys:
                from_room, to_room, timestamp, duration_seconds,
                path_type, confidence, via_room
        """
        try:
            # Calculate cutoff
            if hours is not None:
                cutoff = datetime.now() - timedelta(hours=hours)
            else:
                cutoff = datetime.now() - timedelta(days=days)
            
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT 
                        from_room,
                        to_room,
                        timestamp,
                        duration_seconds,
                        path_type,
                        confidence,
                        via_room
                    FROM room_transitions
                    WHERE person_id = ?
                      AND timestamp >= ?
                    ORDER BY timestamp ASC
                """, (person_id, cutoff))
                
                rows = await cursor.fetchall()
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            _LOGGER.error("Failed to get transitions: %s", e)
            return []

    async def get_common_paths(
        self,
        person_id: str,
        days: int = 30,
        min_occurrences: int = 3
    ) -> list[dict[str, Any]]:
        """Get most common transition paths for a person.
        
        Returns:
            List of dicts with keys: from_room, to_room, count
        """
        try:
            cutoff = datetime.now() - timedelta(days=days)
            
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT 
                        from_room,
                        to_room,
                        COUNT(*) as count
                    FROM room_transitions
                    WHERE person_id = ?
                      AND timestamp >= ?
                    GROUP BY from_room, to_room
                    HAVING count >= ?
                    ORDER BY count DESC
                """, (person_id, cutoff, min_occurrences))
                
                rows = await cursor.fetchall()
                
                return [dict(row) for row in rows]
                
        except Exception as e:
            _LOGGER.error("Failed to get common paths: %s", e)
            return []

    # =========================================================================
    # v3.5.0: CENSUS SNAPSHOT METHODS
    # =========================================================================

    async def log_census(self, zone: str, result: Any) -> None:
        """Log a census snapshot for a single zone.

        Args:
            zone: "house" or "property"
            result: CensusZoneResult dataclass instance
        """
        try:
            import json
            identified_persons_json = (
                json.dumps(result.identified_persons)
                if result.identified_persons
                else None
            )
            timestamp = result.timestamp.isoformat() if result.timestamp else datetime.now().isoformat()

            async with aiosqlite.connect(self.db_file) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO census_snapshots (
                        timestamp, zone, identified_count, identified_persons,
                        unidentified_count, total_persons, confidence,
                        source_agreement, frigate_count, unifi_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp,
                    zone,
                    result.identified_count,
                    identified_persons_json,
                    result.unidentified_count,
                    result.total_persons,
                    result.confidence,
                    result.source_agreement,
                    result.frigate_count,
                    result.unifi_count,
                ))
                await db.commit()
                _LOGGER.debug(
                    "Census snapshot logged: zone=%s, total=%d, identified=%d, confidence=%s",
                    zone,
                    result.total_persons,
                    result.identified_count,
                    result.confidence,
                )
        except Exception as e:
            _LOGGER.error("Failed to log census snapshot: %s", e)

    async def get_census_history(self, hours: int = 24) -> list[dict[str, Any]]:
        """Get census history for the last N hours.

        Returns:
            List of dicts with census snapshot data ordered by timestamp ascending.
        """
        try:
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            async with aiosqlite.connect(self.db_file) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT
                        timestamp, zone, identified_count, identified_persons,
                        unidentified_count, total_persons, confidence,
                        source_agreement, frigate_count, unifi_count
                    FROM census_snapshots
                    WHERE timestamp > ?
                    ORDER BY timestamp ASC
                """, (cutoff,))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Failed to get census history: %s", e)
            return []

    async def cleanup_census(self, retention_days: int = 90) -> int:
        """Delete census snapshots older than retention_days.

        Returns:
            Number of rows deleted.
        """
        try:
            cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
            async with aiosqlite.connect(self.db_file) as db:
                cursor = await db.execute("""
                    DELETE FROM census_snapshots WHERE timestamp < ?
                """, (cutoff,))
                await db.commit()
                deleted = cursor.rowcount
                if deleted > 0:
                    _LOGGER.debug("Census cleanup: deleted %d snapshots older than %d days", deleted, retention_days)
                return deleted
        except Exception as e:
            _LOGGER.error("Failed to cleanup census snapshots: %s", e)
            return 0

    # =========================================================================
    # v3.5.2: TRANSIT VALIDATION METHODS
    # =========================================================================

    async def update_transition_validation(
        self,
        person_id: str,
        timestamp,
        new_confidence: float,
        validation_method: str,
        checkpoint_rooms: list,
    ) -> None:
        """Update confidence and validation metadata for a recorded transition."""
        import json
        try:
            ts_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("""
                    UPDATE room_transitions
                    SET confidence = ?,
                        validation_method = ?,
                        checkpoint_rooms = ?
                    WHERE person_id = ?
                      AND timestamp = ?
                """, (
                    new_confidence,
                    validation_method,
                    json.dumps(checkpoint_rooms),
                    person_id,
                    ts_str,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error updating transition validation: %s", e)

    async def log_entry_exit_event(
        self,
        person_id: Optional[str],
        event_type: str,
        direction: str,
        egress_camera: str,
        confidence: float,
    ) -> None:
        """Log a confirmed entry or exit event."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("""
                    INSERT INTO person_entry_exit_events
                        (timestamp, person_id, event_type, direction, egress_camera, confidence)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    person_id,
                    event_type,
                    direction,
                    egress_camera,
                    confidence,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error logging entry/exit event: %s", e)

    async def get_entry_exit_events_since(
        self,
        since,
        direction: str,
    ) -> list[dict]:
        """Return entry or exit events since the given datetime.

        Used by count sensors on startup to restore today's count from DB.
        Returns a list of dicts with keys: person_id, timestamp, egress_camera.
        """
        try:
            since_str = since.isoformat() if hasattr(since, "isoformat") else str(since)
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT person_id, timestamp, egress_camera
                    FROM person_entry_exit_events
                    WHERE timestamp >= ?
                      AND direction = ?
                    ORDER BY timestamp ASC
                """, (since_str, direction))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching entry/exit events: %s", e)
            return []

    # =========================================================================
    # v3.6.29: Notification Manager database methods
    # =========================================================================

    async def log_notification(
        self,
        coordinator_id: str,
        severity: str,
        title: str,
        message: str,
        hazard_type: str | None = None,
        location: str | None = None,
        person_id: str | None = None,
        channel: str | None = None,
        delivered: int = 1,
    ) -> int | None:
        """Log a notification to the database. Returns the row ID."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute("""
                    INSERT INTO notification_log
                    (timestamp, coordinator_id, severity, title, message,
                     hazard_type, location, person_id, channel, delivered)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    dt_util.utcnow().isoformat(),
                    coordinator_id, severity, title, message,
                    hazard_type, location, person_id, channel, delivered,
                ))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Failed to log notification: %s", e)
            return None

    async def get_notifications_today(self) -> list[dict]:
        """Get all delivered notifications from today."""
        try:
            today_start = dt_util.start_of_local_day().isoformat()
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE timestamp >= ? AND delivered > 0
                    ORDER BY timestamp DESC
                """, (today_start,))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching today's notifications: %s", e)
            return []

    async def get_last_notification(self) -> dict | None:
        """Get the most recent delivered notification."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE delivered > 0
                    ORDER BY timestamp DESC LIMIT 1
                """)
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            _LOGGER.error("Error fetching last notification: %s", e)
            return None

    async def get_pending_digest(self, person_id: str) -> list[dict]:
        """Get pending digest notifications for a person."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE person_id = ? AND delivered = 0
                      AND severity IN ('LOW', 'MEDIUM')
                    ORDER BY timestamp
                """, (person_id,))
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            _LOGGER.error("Error fetching pending digest: %s", e)
            return []

    async def mark_digest_delivered(self, person_id: str) -> None:
        """Mark all pending digest items as delivered for a person."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("""
                    UPDATE notification_log SET delivered = 2
                    WHERE person_id = ? AND delivered = 0
                      AND severity IN ('LOW', 'MEDIUM')
                """, (person_id,))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error marking digest delivered: %s", e)

    async def acknowledge_notification(self) -> None:
        """Acknowledge the most recent unacknowledged CRITICAL notification."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("""
                    UPDATE notification_log
                    SET acknowledged = 1, ack_time = ?
                    WHERE id = (
                        SELECT id FROM notification_log
                        WHERE acknowledged = 0 AND severity = 'CRITICAL'
                        ORDER BY timestamp DESC LIMIT 1
                    )
                """, (dt_util.utcnow().isoformat(),))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error acknowledging notification: %s", e)

    async def get_active_critical(self) -> dict | None:
        """Get the most recent unacknowledged CRITICAL notification."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE severity = 'CRITICAL' AND acknowledged = 0
                    ORDER BY timestamp DESC LIMIT 1
                """)
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            _LOGGER.error("Error fetching active critical: %s", e)
            return None

    async def get_active_cooldown(self) -> dict | None:
        """Get the active cooldown notification (acked but cooldown not expired)."""
        try:
            now = dt_util.utcnow().isoformat()
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_log
                    WHERE severity = 'CRITICAL' AND acknowledged = 1
                      AND cooldown_expires IS NOT NULL AND cooldown_expires > ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (now,))
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            _LOGGER.error("Error fetching active cooldown: %s", e)
            return None

    async def set_cooldown(self, notification_id: int, cooldown_expires: str) -> None:
        """Set the cooldown expiry for a notification."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("""
                    UPDATE notification_log SET cooldown_expires = ?
                    WHERE id = ?
                """, (cooldown_expires, notification_id))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error setting cooldown: %s", e)

    async def prune_notification_log(self, retention_days: int = 30) -> int:
        """Prune notifications older than retention_days. Returns rows deleted."""
        try:
            cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute("""
                    DELETE FROM notification_log WHERE timestamp < ?
                """, (cutoff,))
                await db.commit()
                return cursor.rowcount
        except Exception as e:
            _LOGGER.error("Error pruning notification log: %s", e)
            return 0

    # ====================================================================
    # v3.9.7 C4b: Notification Inbound
    # ====================================================================

    async def log_inbound(
        self,
        person_id: str | None,
        channel: str,
        raw_text: str,
        parsed_command: str | None,
        response_text: str | None,
        alert_id: int | None,
        success: bool,
    ) -> int | None:
        """Log an inbound message. Returns row ID."""
        try:
            now = dt_util.utcnow().isoformat()
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute("""
                    INSERT INTO notification_inbound
                    (timestamp, person_id, channel, raw_text, parsed_command,
                     response_text, alert_id, success)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (now, person_id, channel, raw_text, parsed_command,
                      response_text, alert_id, 1 if success else 0))
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            _LOGGER.error("Error logging inbound message: %s", e)
            return None

    async def prune_inbound_log(self, retention_days: int = 30) -> int:
        """Prune inbound messages older than retention_days. Returns rows deleted."""
        try:
            cutoff = (dt_util.utcnow() - timedelta(days=retention_days)).isoformat()
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute("""
                    DELETE FROM notification_inbound WHERE timestamp < ?
                """, (cutoff,))
                await db.commit()
                return cursor.rowcount
        except Exception as e:
            _LOGGER.error("Error pruning inbound log: %s", e)
            return 0

    async def get_inbound_today(self) -> list[dict]:
        """Get all inbound messages from today."""
        try:
            today_start = dt_util.start_of_local_day().isoformat()
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT * FROM notification_inbound
                    WHERE timestamp >= ?
                    ORDER BY timestamp DESC
                """, (today_start,))
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            _LOGGER.error("Error fetching inbound today: %s", e)
            return []

    # ====================================================================
    # v3.7.11: Energy Daily Billing Snapshots
    # ====================================================================

    async def log_energy_daily(
        self,
        date_str: str,
        import_kwh: float,
        export_kwh: float,
        import_cost: float,
        export_credit: float,
        net_cost: float,
        consumption_kwh: float | None = None,
        solar_production_kwh: float | None = None,
        predicted_consumption_kwh: float | None = None,
        avg_temperature: float | None = None,
        prediction_error_pct: float | None = None,
        adjustment_factor: float | None = None,
    ) -> None:
        """Save daily energy snapshot. Uses INSERT OR REPLACE for idempotency."""
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO energy_daily
                    (date, import_kwh, export_kwh, import_cost, export_credit,
                     net_cost, consumption_kwh, solar_production_kwh,
                     predicted_consumption_kwh, avg_temperature,
                     prediction_error_pct, adjustment_factor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date_str, import_kwh, export_kwh, import_cost,
                    export_credit, net_cost, consumption_kwh,
                    solar_production_kwh, predicted_consumption_kwh,
                    avg_temperature, prediction_error_pct, adjustment_factor,
                ))
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving energy daily snapshot: %s", e)

    async def get_energy_daily_for_cycle(
        self, cycle_start: str, cycle_end: str
    ) -> dict:
        """Sum energy_daily rows for a billing cycle date range.

        Returns dict with total import/export/cost and day count.
        """
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as days,
                        COALESCE(SUM(import_kwh), 0) as total_import,
                        COALESCE(SUM(export_kwh), 0) as total_export,
                        COALESCE(SUM(import_cost), 0) as total_import_cost,
                        COALESCE(SUM(export_credit), 0) as total_export_credit,
                        COALESCE(SUM(net_cost), 0) as total_net_cost
                    FROM energy_daily
                    WHERE date >= ? AND date < ?
                """, (cycle_start, cycle_end))
                row = await cursor.fetchone()
                if row:
                    return {
                        "days": row[0],
                        "import_kwh": row[1],
                        "export_kwh": row[2],
                        "import_cost": row[3],
                        "export_credit": row[4],
                        "net_cost": row[5],
                    }
                return {"days": 0, "import_kwh": 0, "export_kwh": 0,
                        "import_cost": 0, "export_credit": 0, "net_cost": 0}
        except Exception as e:
            _LOGGER.error("Error querying energy daily for cycle: %s", e)
            return {"days": 0, "import_kwh": 0, "export_kwh": 0,
                    "import_cost": 0, "export_credit": 0, "net_cost": 0}

    async def get_energy_daily_recent(self, days: int = 30) -> list[dict]:
        """Get recent energy_daily rows for accuracy restore + regression.

        Returns list of dicts with all columns, ordered by date ascending.
        """
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT date, consumption_kwh, predicted_consumption_kwh,
                           prediction_error_pct, adjustment_factor,
                           avg_temperature
                    FROM energy_daily
                    WHERE consumption_kwh IS NOT NULL
                    ORDER BY date DESC
                    LIMIT ?
                """, (days,))
                rows = await cursor.fetchall()
                return [dict(row) for row in reversed(rows)]
        except Exception as e:
            _LOGGER.error("Error querying recent energy daily: %s", e)
            return []

    async def get_energy_temp_pairs(self, min_days: int = 30) -> list[tuple]:
        """Get consumption-temperature pairs for regression fitting.

        Returns list of (consumption_kwh, avg_temperature) tuples.
        Only includes rows where both values are non-null.
        """
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute("""
                    SELECT consumption_kwh, avg_temperature
                    FROM energy_daily
                    WHERE consumption_kwh IS NOT NULL
                      AND avg_temperature IS NOT NULL
                    ORDER BY date DESC
                    LIMIT 90
                """)
                rows = await cursor.fetchall()
                if len(rows) >= min_days:
                    return [(row[0], row[1]) for row in rows]
                return []
        except Exception as e:
            _LOGGER.error("Error querying temp pairs: %s", e)
            return []

    # ── Peak import history (load shedding auto-learning) ──────────

    async def save_peak_import_history(self, readings: list[float]) -> None:
        """Persist peak import readings for load shedding auto-learning.

        Replaces all rows — called hourly from Energy Coordinator.
        Keeps at most 1500 readings (matches in-memory cap).
        The learned threshold is recomputed from readings on each cycle,
        so only the raw readings need persistence.
        """
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                await db.execute("DELETE FROM energy_peak_import")
                if readings:
                    await db.executemany(
                        "INSERT INTO energy_peak_import (seq, import_kw) VALUES (?, ?)",
                        [(i, r) for i, r in enumerate(readings)],
                    )
                await db.commit()
        except Exception as e:
            _LOGGER.error("Error saving peak import history: %s", e)

    async def get_peak_import_history(self) -> list[float]:
        """Restore peak import readings for load shedding auto-learning.

        Returns list of import_kw readings in original order.
        """
        try:
            async with aiosqlite.connect(self.db_file, timeout=30.0) as db:
                cursor = await db.execute(
                    "SELECT import_kw FROM energy_peak_import ORDER BY seq ASC"
                )
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            _LOGGER.error("Error restoring peak import history: %s", e)
            return []
