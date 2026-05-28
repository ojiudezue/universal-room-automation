/**
 * House tab — whole-home roll-up. Smaller than Home tab; shows aggregate
 * KPI tiles + zone summaries. Drill-down buttons link to Zones / Rooms.
 *
 * Wires:
 *   - coordinator_summary attrs for house_state, coordinators count
 *   - zones_with_motion for activity tile
 *   - whole_house_power / whole_house_cost_today / hvac_system_demand
 *   - useCoordinatorSummary for status_per_coordinator (per-zone health proxy)
 *
 * Deferred (no backing entity yet):
 *   - Lights-on aggregate (would need a new aggregator)
 *   - Outside temperature (need weather entity wiring)
 *   - Per-zone room counts (URA zones are user-configured; not a clean N/total)
 *   - Quick-action scene buttons (read-only — controls-bar pattern)
 */
import {
  useUraSensorFloat,
  useUraSensorInt,
  useUraSensorAttrs,
} from "../../data/useUraSensor";
import { num } from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

const ZONES_WITH_MOTION_SENSOR =
  "sensor.universal_room_automation_zones_with_motion";
const WHOLE_HOUSE_POWER_SENSOR =
  "sensor.universal_room_automation_whole_house_power";
const WHOLE_HOUSE_COST_SENSOR =
  "sensor.universal_room_automation_whole_house_cost_today";
const HVAC_SYSTEM_DEMAND_SENSOR =
  "sensor.universal_room_automation_hvac_system_demand";
// VERIFIED 2026-05-19: state = "home_day"
// (Currently read via summary.attrs.house_state; constant kept for future
// direct-sensor wiring if we drop the summary indirection.)
// const HOUSE_STATE_SENSOR = "sensor.universal_room_automation_house_state";

interface ZonesWithMotionAttrs {
  zones?: string[];
  window_minutes?: number;
}

interface HvacSystemDemandAttrs {
  active_zones?: string[];
  active_count?: number;
  total_zones?: number;
  load_bucket?: string;
}

function formatHouseState(s: string | null): string {
  if (!s || s === "unknown" || s === "unavailable") return "—";
  // home_day → "Home (day)" — readable label
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function House() {
  const summary = useCoordinatorSummary();
  const houseStateRaw = summary.attrs?.house_state;
  const coordinatorsActive = summary.attrs?.coordinators_active ?? null;
  const coordinatorsRegistered =
    summary.attrs?.coordinators_registered ?? null;

  const motion = useUraSensorInt(ZONES_WITH_MOTION_SENSOR);
  const motionAttrs = useUraSensorAttrs<ZonesWithMotionAttrs>(
    ZONES_WITH_MOTION_SENSOR,
  );
  const power = useUraSensorFloat(WHOLE_HOUSE_POWER_SENSOR);
  const costToday = useUraSensorFloat(WHOLE_HOUSE_COST_SENSOR);

  const hvacDemand = useUraSensorInt(HVAC_SYSTEM_DEMAND_SENSOR);
  const hvacAttrs = useUraSensorAttrs<HvacSystemDemandAttrs>(
    HVAC_SYSTEM_DEMAND_SENSOR,
  );

  return (
    <section className="tab active" data-tab="house">
      <header className="page-header">
        <div>
          <h1 className="page-title">House</h1>
          <div className="page-subtitle">
            Whole-home roll-up · drill to Zones or Rooms for detail
          </div>
        </div>
        <div className="page-actions">
          <button className="btn">
            <svg className="icon">
              <use href="#lc-plus" />
            </svg>{" "}
            Onboard room
          </button>
        </div>
      </header>

      {/* Controls bar — read-only knobs (see Diagnostics deferred-section) */}
      <div className="controls-bar">
        <div className="knob span-4">
          <div className="knob-label">Whole-house quick</div>
          <div
            className="knob-action"
            style={{ marginTop: 0, flexWrap: "wrap" }}
          >
            <button className="btn" disabled>
              All lights off
            </button>
            <button className="btn" disabled>
              Evening scene
            </button>
            <button className="btn" disabled>
              Bed scene
            </button>
            <button className="btn" disabled>
              Movie scene
            </button>
          </div>
        </div>
        <div className="knob span-4">
          <div className="knob-label">House climate setpoint</div>
          <div
            className="row"
            style={{ gap: "var(--space-xs)", alignItems: "center" }}
          >
            <button className="btn icon" disabled>
              <svg className="icon-sm">
                <use href="#lc-minus" />
              </svg>
            </button>
            <div
              className="knob-value tabular"
              style={{ flex: 1, textAlign: "center" }}
            >
              —
            </div>
            <button className="btn icon" disabled>
              <svg className="icon-sm">
                <use href="#lc-plus" />
              </svg>
            </button>
          </div>
          <div className="card-sub">
            All zones · setpoint not yet wired to a service
          </div>
        </div>
        <div className="knob span-4">
          <div className="knob-label">Drill into</div>
          <div
            className="knob-action"
            style={{ marginTop: 0, flexWrap: "wrap" }}
          >
            <button className="btn">
              Zones{" "}
              <svg className="icon-sm">
                <use href="#lc-chevron-right" />
              </svg>
            </button>
            <button className="btn">
              Rooms{" "}
              <svg className="icon-sm">
                <use href="#lc-chevron-right" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Whole-house KPI tiles */}
      <div className="grid">
        <div className="card col-3">
          <div className="card-title">House state</div>
          <div className="card-value sm tabular">
            {formatHouseState(houseStateRaw ?? null)}
          </div>
          <div className="card-sub">
            {num(coordinatorsActive)} / {num(coordinatorsRegistered)}{" "}
            coordinators active
          </div>
        </div>
        <div className="card col-3">
          <div className="card-title">Power</div>
          <div className="card-value tabular">
            {num(power.value)}
            <span className="card-unit">kW</span>
          </div>
          <div className="card-sub">whole-house live draw</div>
        </div>
        <div className="card col-3">
          <div className="card-title">Cost today</div>
          <div className="card-value tabular">
            ${num(costToday.value)}
          </div>
          <div className="card-sub">since local midnight</div>
        </div>
        <div className="card col-3">
          <div className="card-title">Activity ({motionAttrs.attrs?.window_minutes ?? 5} min)</div>
          <div className="card-value tabular">{num(motion.value)}</div>
          <div className="card-sub">
            zones with motion · {motionAttrs.attrs?.zones?.length ?? 0} active
          </div>
        </div>
      </div>

      {/* HVAC zone roll-up */}
      <div className="section-head">
        <h2>HVAC zones</h2>
      </div>
      <div className="grid">
        <div className="card col-6 status-green">
          <div className="card-head">
            <div className="row" style={{ gap: "var(--space-xs)" }}>
              <span className="dot green live" />
              <strong>System demand</strong>
            </div>
            <span className="badge accent">
              {hvacAttrs.attrs?.load_bucket ?? "—"}
            </span>
          </div>
          <div className="card-row">
            <span>Active zones</span>
            <span className="tabular">
              {hvacAttrs.attrs?.active_count ?? "—"} /{" "}
              {hvacAttrs.attrs?.total_zones ?? "—"}
            </span>
          </div>
          <div className="card-row">
            <span>Demand</span>
            <span className="tabular">
              {num(hvacDemand.value, "%")}
            </span>
          </div>
          <div className="card-row">
            <span>Calling</span>
            <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
              {hvacAttrs.attrs?.active_zones?.join(", ") || "none"}
            </span>
          </div>
        </div>
        <div className="card col-6">
          <div className="card-head">
            <div className="row" style={{ gap: "var(--space-xs)" }}>
              <span className="dot grey" />
              <strong>Motion (live)</strong>
            </div>
            <span className="badge">
              {motionAttrs.attrs?.window_minutes ?? 5}m window
            </span>
          </div>
          <div className="card-row">
            <span>Zones</span>
            <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
              {motionAttrs.attrs?.zones?.join(", ") || "—"}
            </span>
          </div>
          <div className="card-sub">
            Live signal across all rooms · drill to Rooms for per-room idle time
          </div>
        </div>
      </div>
    </section>
  );
}
