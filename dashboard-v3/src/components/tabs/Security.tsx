/**
 * Security tab — alarm mode, locks, cameras, recent entries.
 *
 * Wires:
 *   - sensor.ura_security_coordinator_security_armed_state — alarm mode
 *   - sensor.ura_security_coordinator_security_open_entries — open count
 *   - sensor.ura_security_coordinator_security_authorized_guests
 *   - sensor.ura_security_coordinator_security_expected_arrivals
 *   - sensor.ura_security_coordinator_security_anomaly — anomaly badge
 *   - sensor.ura_security_coordinator_security_compliance — % compliance
 *   - sensor.ura_security_coordinator_security_last_lock_sweep — timestamp
 *   - binary_sensor.ura_security_coordinator_security_alert — active alert
 *   - useCoordinatorSummary for security coord status (green/orange/red)
 *
 * Deferred (no clean cross-install entity):
 *   - Per-lock entity wiring (would need install-specific lock entity_ids;
 *     URA exposes aggregate counts not individual locks). Static tile per
 *     standard lock left as visual scaffolding.
 *   - Camera live tiles — left as static visual scaffolding; live MJPEG
 *     streams in an iframe are out of scope this cycle.
 *   - Arm/disarm pill buttons (read-only — no SECURITY_SET_ARMED service yet).
 */
import {
  useUraSensorState,
  useUraSensorInt,
  useUraSensorFloat,
  formatRelativeTime,
} from "../../data/useUraSensor";
import {
  statusToCardClass,
  statusToBadge,
  num,
} from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

const ARMED_STATE_SENSOR =
  "sensor.ura_security_coordinator_security_armed_state";
const OPEN_ENTRIES_SENSOR =
  "sensor.ura_security_coordinator_security_open_entries";
const AUTHORIZED_GUESTS_SENSOR =
  "sensor.ura_security_coordinator_security_authorized_guests";
const EXPECTED_ARRIVALS_SENSOR =
  "sensor.ura_security_coordinator_security_expected_arrivals";
const SECURITY_ANOMALY_SENSOR =
  "sensor.ura_security_coordinator_security_anomaly";
const COMPLIANCE_SENSOR =
  "sensor.ura_security_coordinator_security_compliance";
const LAST_LOCK_SWEEP_SENSOR =
  "sensor.ura_security_coordinator_security_last_lock_sweep";
const SECURITY_ALERT_SENSOR =
  "binary_sensor.ura_security_coordinator_security_alert";

function formatArmedState(s: string | null): string {
  if (!s || s === "unknown" || s === "unavailable") return "—";
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ");
}

export function Security() {
  const armed = useUraSensorState(ARMED_STATE_SENSOR);
  const openEntries = useUraSensorInt(OPEN_ENTRIES_SENSOR);
  const authorizedGuests = useUraSensorState(AUTHORIZED_GUESTS_SENSOR);
  const expectedArrivals = useUraSensorInt(EXPECTED_ARRIVALS_SENSOR);
  const securityAnomaly = useUraSensorState(SECURITY_ANOMALY_SENSOR);
  const compliance = useUraSensorFloat(COMPLIANCE_SENSOR);
  const lastSweep = useUraSensorState(LAST_LOCK_SWEEP_SENSOR);
  const securityAlert = useUraSensorState(SECURITY_ALERT_SENSOR);

  const summary = useCoordinatorSummary();
  const secStatus = summary.attrs?.status_per_coordinator?.security;
  const secStatusName = secStatus?.status ?? "nominal";
  const cardClass = statusToCardClass(secStatusName);
  const badge = statusToBadge(secStatusName);

  const armedRaw = typeof armed.state === "string" ? armed.state : null;
  const isAlert = securityAlert.state === "on";

  return (
    <section className="tab active" data-tab="security">
      <header className="page-header">
        <div>
          <h1 className="page-title">Security</h1>
          <div className="page-subtitle">
            {formatArmedState(armedRaw)} ·{" "}
            {num(openEntries.value)} open entries · anomaly{" "}
            {typeof securityAnomaly.state === "string"
              ? securityAnomaly.state
              : "—"}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn">
            <svg className="icon">
              <use href="#lc-bell" />
            </svg>{" "}
            Events
          </button>
        </div>
      </header>

      {/* Controls bar — alarm modes + auto-arm toggles READ-ONLY */}
      <div className="controls-bar">
        <div className="knob span-4">
          <div className="knob-label">
            Alarm mode <span className={`badge ${badge.cls}`}>{badge.label}</span>
          </div>
          <div className="pill-group" style={{ width: "100%" }}>
            <button
              className={armedRaw === "disarmed" ? "active" : ""}
              style={{ flex: 1 }}
              disabled
            >
              Off
            </button>
            <button
              className={armedRaw === "armed_home" ? "active" : ""}
              style={{ flex: 1 }}
              disabled
            >
              Home
            </button>
            <button
              className={armedRaw === "armed_night" ? "active" : ""}
              style={{ flex: 1 }}
              disabled
            >
              Night
            </button>
            <button
              className={armedRaw === "armed_away" ? "active" : ""}
              style={{ flex: 1 }}
              disabled
            >
              Away
            </button>
          </div>
          <div className="card-sub">
            Live read-only · service-wiring deferred to next cycle
          </div>
        </div>
        <div className="knob span-2">
          <div className="knob-label">Auto-arm on leave</div>
          <div className="row" style={{ gap: "var(--space-sm)" }}>
            <label className="toggle">
              <input type="checkbox" defaultChecked readOnly />
              <span className="toggle-slot" />
            </label>
            <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
              2m delay
            </span>
          </div>
          <div className="card-sub">When census drops to 0</div>
        </div>
        <div className="knob span-2">
          <div className="knob-label">Auto-arm at sleep</div>
          <div className="row" style={{ gap: "var(--space-sm)" }}>
            <label className="toggle">
              <input type="checkbox" defaultChecked readOnly />
              <span className="toggle-slot" />
            </label>
            <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
              → Night
            </span>
          </div>
          <div className="card-sub">Triggers on house_state=sleep</div>
        </div>
        <div className="knob span-2">
          <div className="knob-label">Lock-after-motion</div>
          <div className="knob-value tabular">
            5{" "}
            <span
              className="dim"
              style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
            >
              min
            </span>
          </div>
          <div className="knob-action">
            <input
              type="range"
              min={0}
              max={30}
              value={5}
              className="slider"
              readOnly
            />
          </div>
        </div>
        <div className="knob span-2">
          <div className="knob-label">Compliance</div>
          <div className="knob-value tabular">
            {num(compliance.value, "%")}
          </div>
          <div className="card-sub">Locks/entries vs policy</div>
        </div>
      </div>

      {/* Hero KPI tiles */}
      <div className="grid">
        <div className={`card col-3 ${cardClass}`}>
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-shield" />
            </svg>
            Alarm
          </div>
          <div className="card-value sm">{formatArmedState(armedRaw)}</div>
          <div className="card-sub">
            URA security coordinator · {secStatusName}
          </div>
        </div>
        <div
          className={`card col-3 ${
            openEntries.value === 0 ? "status-green" : "status-yellow"
          }`}
        >
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-lock" />
            </svg>
            Open entries
          </div>
          <div className="card-value tabular">{num(openEntries.value)}</div>
          <div className="card-sub">
            last sweep {formatRelativeTime(lastSweep.state ?? null)}
          </div>
        </div>
        <div className="card col-3 status-green">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-users" />
            </svg>
            Authorized guests
          </div>
          <div className="card-value sm">
            {typeof authorizedGuests.state === "string"
              ? authorizedGuests.state
              : "—"}
          </div>
          <div className="card-sub">
            {num(expectedArrivals.value)} expected arrivals
          </div>
        </div>
        <div
          className={`card col-3 ${
            isAlert ? "status-red" : "status-green"
          }`}
        >
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-bell" />
            </svg>
            Alert state
          </div>
          <div className="card-value sm">{isAlert ? "Active" : "Clear"}</div>
          <div className="card-sub">
            {isAlert
              ? "security alert sensor is on"
              : "no active security alert"}
          </div>
        </div>
      </div>

      {/* Cameras section — left as static scaffolding; live streams out of scope */}
      <div className="section-head">
        <h2>Cameras</h2>
      </div>
      <div className="grid">
        <div className="card col-12">
          <div
            className="row"
            style={{ gap: "var(--space-sm)", alignItems: "center" }}
          >
            <svg className="icon-lg">
              <use href="#lc-video" />
            </svg>
            <div>
              <div className="card-title">Live camera tiles deferred</div>
              <div className="card-sub">
                MJPEG streams embedded in the dashboard iframe are out of
                scope this cycle. Use the HA camera dashboard for live
                feeds; this surface will return when a per-camera
                snapshot+motion-event aggregator ships.
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Locks — scaffolding only; per-lock entity wiring deferred */}
      <div className="section-head">
        <h2>Locks &amp; entries</h2>
      </div>
      <div className="grid">
        <div className="card col-6">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-lock" />
              </svg>{" "}
              Aggregate
            </div>
          </div>
          <div className="card-row">
            <span>Open entries</span>
            <span className="tabular">{num(openEntries.value)}</span>
          </div>
          <div className="card-row">
            <span>Last lock sweep</span>
            <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
              {formatRelativeTime(lastSweep.state ?? null)}
            </span>
          </div>
          <div className="card-row">
            <span>Compliance</span>
            <span className="tabular">{num(compliance.value, "%")}</span>
          </div>
        </div>
        <div className="card col-6">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-shield" />
              </svg>{" "}
              Anomaly
            </div>
            <span className={`badge ${badge.cls}`}>{badge.label}</span>
          </div>
          <div className="card-row">
            <span>Security anomaly</span>
            <span>
              {typeof securityAnomaly.state === "string"
                ? securityAnomaly.state
                : "—"}
            </span>
          </div>
          <div className="card-row">
            <span>Active alert</span>
            <span>{isAlert ? "Yes" : "No"}</span>
          </div>
          <div className="card-sub">
            Detailed per-lock surfaces will return when URA exposes a
            per-lock list. For now, refer to HA's lock dashboard.
          </div>
        </div>
      </div>
    </section>
  );
}
