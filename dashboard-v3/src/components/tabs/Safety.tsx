/**
 * Safety tab — React port of safety.html (P6 light styled).
 *
 * Safety Coordinator surface area:
 *   - `sensor.ura_safety_coordinator_safety_status` — overall ("advisory" / "nominal" / "alert")
 *   - `sensor.ura_safety_coordinator_safety_active_hazards` — int
 *   - `sensor.ura_safety_coordinator_safety_active_cooldowns` — "N recent"
 *   - `sensor.ura_safety_coordinator_safety_events_summary` — int + last_event_at attr
 *   - `sensor.ura_safety_coordinator_safety_affected_rooms` — comma-joined string
 *   - `sensor.ura_safety_coordinator_safety_compliance` — float %
 *   - `sensor.ura_safety_coordinator_safety_anomaly` — "nominal" / "learning" / "alert"
 *   - `sensor.ura_safety_coordinator_safety_diagnostics` — "ok" / "degraded"
 *   - `binary_sensor.ura_safety_coordinator_safety_alert` — bool
 *   - `binary_sensor.ura_safety_coordinator_safety_air_quality` — bool
 *   - `binary_sensor.ura_safety_coordinator_safety_water_leak` — bool
 *   - `switch.ura_safety_coordinator_enabled`
 *   - `switch.ura_safety_coordinator_safety_observation_mode`
 *
 * DEFERRED:
 *   - Per-detector cards (Kitchen / Hallway / Garage smoke + CO + battery):
 *     these are HA-native sensors outside URA's namespace (Z-Wave / Zigbee
 *     smoke detectors). Surfacing them needs an install-specific entity
 *     mapping; deferred until URA adds a `detectors_inventory` attribute.
 *   - Recent safety events timeline: backed by activity_log (D1 returns
 *     COUNT not rows). Renders headline-only placeholder.
 *   - Auto-call sequence / emergency contacts: stored in coordinator config
 *     not entities. Read-only placeholder.
 *   - Freeze threshold / hazard severity floor / auto-shutoff toggles: knobs
 *     are read-only.
 */
import {
  useUraSensorInt,
  useUraSensorState,
  useUraSensorFloat,
} from "../../data/useUraSensor";
import { num, statusToBadge } from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

const SAFETY_STATUS = "sensor.ura_safety_coordinator_safety_status";
const SAFETY_ACTIVE_HAZARDS = "sensor.ura_safety_coordinator_safety_active_hazards";
const SAFETY_AFFECTED_ROOMS = "sensor.ura_safety_coordinator_safety_affected_rooms";
const SAFETY_ACTIVE_COOLDOWNS = "sensor.ura_safety_coordinator_safety_active_cooldowns";
const SAFETY_EVENTS_SUMMARY = "sensor.ura_safety_coordinator_safety_events_summary";
const SAFETY_COMPLIANCE = "sensor.ura_safety_coordinator_safety_compliance";
const SAFETY_ANOMALY = "sensor.ura_safety_coordinator_safety_anomaly";
const SAFETY_DIAGNOSTICS = "sensor.ura_safety_coordinator_safety_diagnostics";
const SAFETY_ALERT = "binary_sensor.ura_safety_coordinator_safety_alert";
const SAFETY_AIR_QUALITY = "binary_sensor.ura_safety_coordinator_safety_air_quality";
const SAFETY_WATER_LEAK = "binary_sensor.ura_safety_coordinator_safety_water_leak";
const SAFETY_ENABLED = "switch.ura_safety_coordinator_enabled";
const SAFETY_OBSERVATION = "switch.ura_safety_coordinator_safety_observation_mode";

interface EventsSummaryAttrs {
  auto_dismissed_count?: number;
  last_event_at?: string;
  window_hours?: number;
}

/** Safety status string → card modifier. */
function safetyCardCls(status: string | null): string {
  switch (status) {
    case "nominal":
      return "status-green";
    case "advisory":
      return "status-yellow";
    case "alert":
      return "status-red";
    case "critical":
      return "status-red";
    default:
      return "";
  }
}

/** Read-only top controls bar. */
function ControlsBar() {
  return (
    <div className="controls-bar">
      <div className="knob span-3">
        <div className="knob-label">
          Safety routines <span className="badge green">all armed</span>
        </div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className="active" style={{ flex: 1 }} type="button">
            All armed
          </button>
          <button style={{ flex: 1 }} type="button">
            Day only
          </button>
          <button style={{ flex: 1 }} type="button">
            Disabled
          </button>
        </div>
        <div className="card-sub">Auto-respond to fire / leak / freeze</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">
          Auto water shutoff <span className="badge accent">URA</span>
        </div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            on leak detected
          </span>
        </div>
        <div className="card-sub">Triggers main valve close</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Auto-lock on fire</div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            unlocks all doors
          </span>
        </div>
        <div className="card-sub">Egress for occupants</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Freeze threshold</div>
        <div className="knob-value tabular">
          38°{" "}
          <span
            className="dim"
            style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
          >
            F
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={30}
            max={50}
            defaultValue={38}
            className="slider"
            readOnly
          />
        </div>
        <div className="card-sub">Indoor &lt; this = WARN</div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">
          Hazard severity floor <span className="badge accent">3</span>
        </div>
        <div className="knob-value">
          ALERT{" "}
          <span className="badge" style={{ fontSize: "var(--text-xs)" }}>
            always notify ≥
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={0}
            max={4}
            defaultValue={3}
            className="slider"
            readOnly
          />
        </div>
        <div className="card-sub">Anomaly emit threshold (DEFERRED — read-only)</div>
      </div>
    </div>
  );
}

export function Safety() {
  const summary = useCoordinatorSummary();
  const sumStatus = summary.attrs?.status_per_coordinator?.safety;

  const status = useUraSensorState(SAFETY_STATUS);
  const hazards = useUraSensorInt(SAFETY_ACTIVE_HAZARDS);
  const affectedRooms = useUraSensorState(SAFETY_AFFECTED_ROOMS);
  const cooldowns = useUraSensorState(SAFETY_ACTIVE_COOLDOWNS);
  const events = useUraSensorInt(SAFETY_EVENTS_SUMMARY);
  const eventsAttrs = useUraSensorState(SAFETY_EVENTS_SUMMARY);
  const compliance = useUraSensorFloat(SAFETY_COMPLIANCE);
  const anomaly = useUraSensorState(SAFETY_ANOMALY);
  const diagnostics = useUraSensorState(SAFETY_DIAGNOSTICS);
  const alertOn = useUraSensorState(SAFETY_ALERT);
  const aq = useUraSensorState(SAFETY_AIR_QUALITY);
  const leak = useUraSensorState(SAFETY_WATER_LEAK);
  const enabled = useUraSensorState(SAFETY_ENABLED);
  const observation = useUraSensorState(SAFETY_OBSERVATION);

  const statusState = status.unavailable || !status.state ? null : status.state;
  const cardCls = safetyCardCls(statusState);
  const headerBadge = sumStatus ? statusToBadge(sumStatus.status) : statusToBadge(statusState ?? undefined);
  const eventsSummary =
    (eventsAttrs.attributes ?? null) as EventsSummaryAttrs | null;

  const aqOn = aq.state === "on";
  const leakOn = leak.state === "on";
  const alertActive = alertOn.state === "on";

  return (
    <section className="tab active" data-tab="safety">
      <header className="page-header">
        <div>
          <h1 className="page-title">Safety</h1>
          <div className="page-subtitle">
            {hazards.value ?? "—"} active hazards · {events.value ?? "—"} events
            (last 24h){" "}
            {diagnostics.state && diagnostics.state !== "ok" && (
              <span className="badge yellow">diag: {diagnostics.state}</span>
            )}
          </div>
        </div>
        <div className="page-actions">
          <span className={`badge ${headerBadge.cls} lg`.trim()}>
            <svg className="icon-sm">
              <use href="#lc-shield" />
            </svg>
            {headerBadge.label}
          </span>
        </div>
      </header>

      <ControlsBar />

      {/* Hero KPI */}
      <div className="grid">
        <div className={`card col-3 ${cardCls}`.trim()}>
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-shield" />
            </svg>
            Active hazards
          </div>
          <div className="card-value tabular">{num(hazards.value)}</div>
          <div className="card-sub">
            {affectedRooms.state && affectedRooms.state !== "none"
              ? `affected: ${affectedRooms.state}`
              : "no affected rooms"}
          </div>
        </div>
        <div className="card col-3 status-green">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-check" />
            </svg>
            Detector summary
          </div>
          <div className="card-value sm">
            {alertActive ? (
              <span className="badge red">ALERT</span>
            ) : (
              <span className="badge green">clear</span>
            )}
          </div>
          <div className="card-sub">
            air quality:{" "}
            {aqOn ? (
              <span className="badge red">flag</span>
            ) : (
              <span className="badge green">ok</span>
            )}{" "}
            · water leak:{" "}
            {leakOn ? (
              <span className="badge red">flag</span>
            ) : (
              <span className="badge green">dry</span>
            )}
          </div>
        </div>
        <div className="card col-3">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-bell" />
            </svg>
            Events (24h)
          </div>
          <div className="card-value tabular">{num(events.value)}</div>
          <div className="card-sub">
            {eventsSummary?.auto_dismissed_count != null
              ? `${eventsSummary.auto_dismissed_count} auto-dismissed`
              : "—"}{" "}
            · cooldowns: {cooldowns.state ?? "—"}
          </div>
        </div>
        <div className="card col-3 strong">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-brain" />
            </svg>
            URA intent
          </div>
          <div
            className="card-sub"
            style={{
              marginTop: "var(--space-xs)",
              fontSize: "var(--text-sm)",
              color: "var(--text-primary)",
            }}
          >
            <span className={`badge ${headerBadge.cls}`.trim()}>
              {headerBadge.label}
            </span>{" "}
            · compliance{" "}
            {compliance.value == null
              ? "—"
              : `${compliance.value.toFixed(0)}%`}
          </div>
          <div className="card-sub">
            anomaly: {anomaly.state ?? "—"} · diagnostics: {diagnostics.state ?? "—"}
          </div>
        </div>
      </div>

      <div className="section-head">
        <h2>Coordinator controls</h2>
      </div>
      <div className="grid">
        <div className="card col-6">
          <div className="card-head">
            <div className="card-title">Safety coordinator</div>
            <span className={`badge ${headerBadge.cls}`.trim()}>
              {headerBadge.label}
            </span>
          </div>
          <div className="card-row">
            <span>Status</span>
            <span>
              <strong>{statusState ?? "—"}</strong>
            </span>
          </div>
          <div className="card-row">
            <span>Active anomalies</span>
            <span className="tabular">
              {num(sumStatus?.active_anomalies ?? null)}
            </span>
          </div>
          <div className="card-row">
            <span>Enabled</span>
            <span>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={enabled.state === "on"}
                  readOnly
                />
                <span className="toggle-slot"></span>
              </label>
            </span>
          </div>
          <div className="card-row">
            <span>Observation mode</span>
            <span>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={observation.state === "on"}
                  readOnly
                />
                <span className="toggle-slot"></span>
              </label>
            </span>
          </div>
          <div className="card-sub">
            Switch wiring deferred — display reflects current entity state only.
          </div>
        </div>
        <div className="card col-6">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-activity" />
              </svg>
              Detector breakdown (deferred)
            </div>
            <span className="badge">—</span>
          </div>
          <div className="card-sub">
            Per-detector cards (smoke / CO / leak / freeze, per room) need a
            detectors_inventory attribute on Safety Coordinator. Surfacing the
            install's Z-Wave / Zigbee detector entities is install-specific —
            outside v5.0 scope. See Safety.tsx header.
          </div>
        </div>
      </div>

      <div className="section-head">
        <h2>Recent safety events</h2>
      </div>
      <div className="card col-12">
        <div className="card-row">
          <span>
            Events (24h window):{" "}
            <strong className="tabular">{num(events.value)}</strong>
          </span>
          <span className="dim">
            last event: {eventsSummary?.last_event_at ?? "—"}
          </span>
        </div>
        <div className="card-sub" style={{ marginTop: "var(--space-xs)" }}>
          Timeline rendering of activity_log rows deferred — D1 sensor returns
          a count, not a row list. Aggregator sensor in roadmap.
        </div>
      </div>
    </section>
  );
}
