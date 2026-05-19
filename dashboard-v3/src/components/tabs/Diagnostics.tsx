/**
 * Diagnostics tab — first React port of the v4 P6 dashboard fragment.
 *
 * This sets the PATTERN for the remaining 9 tabs:
 *   1. CSS classes from p6-shared.css are preserved verbatim (page-header,
 *      controls-bar, card.col-N, status-{green,orange,red}, badge, timeline).
 *      Visual parity must hold against docs/dashboard-prototypes/v4/p6-light-styled.html.
 *   2. Each piece of data flows from its own `useUraSensor*` call. Don't batch.
 *   3. Loading / unavailable states render the same DOM structure with "—"
 *      placeholders — no layout shift when the WebSocket finishes its initial fetch.
 *   4. Status colors are DRIVEN by data via `status_per_coordinator[coord].status`,
 *      not hardcoded per coordinator.
 *   5. Static fragments stay around at tabs-shell/*.html as visual reference.
 *
 * DEFERRED for follow-up cycles:
 *   - Controls-bar knobs (anomaly floor, routine floor, observation mode,
 *     telemetry toggles): rendered read-only. Wiring requires backing
 *     Number/Switch entities that don't exist yet (config-flow-options today,
 *     not runtime entities). The user explicitly wants "finished visually
 *     first" — service-call wiring is a separate cycle.
 *   - Automation health card: no HA-side automation success-rate sensors exist
 *     yet. Renders all "—".
 *   - System card uptime / write queue: no entities. Renders "—".
 *   - Logs / Reload / Acknowledge / VACUUM / Restart buttons: visual only.
 *   - DB size sensor is currently a known-broken upstream sensor (renders
 *     whatever state arrives, including "unknown").
 */
import { Fragment } from "react";
import {
  useUraSensorInt,
  useUraSensorFloat,
  useUraSensorAttrs,
  useUraSensorState,
} from "../../data/useUraSensor";
import {
  statusToCardClass,
  statusToBadge,
  num,
  formatClockTime,
} from "../../data/statusColors";
import type {
  PerCoordinatorStatus,
  SummaryAttrs,
} from "../../data/useCoordinatorSummary";
import { COORDINATOR_SUMMARY_SENSOR } from "../../data/useCoordinatorSummary";

type CoordinatorKey = "presence" | "hvac" | "energy" | "safety" | "security";

interface CoordinatorCardDef {
  key: CoordinatorKey;
  label: string;
}

const COORDINATORS: CoordinatorCardDef[] = [
  { key: "presence", label: "Presence" },
  { key: "hvac", label: "HVAC" },
  { key: "energy", label: "Energy" },
  { key: "safety", label: "Safety" },
  { key: "security", label: "Security" },
];

const DB_SIZE_SENSOR = "sensor.ura_coordinator_manager_db_size";

function sensorId(coord: CoordinatorKey, suffix: string): string {
  return `sensor.ura_coordinator_manager_${coord}_${suffix}`;
}

/** Per-coordinator card. Each card owns its own hook calls. */
function CoordinatorCard({
  def,
  summaryStatus,
}: {
  def: CoordinatorCardDef;
  summaryStatus: PerCoordinatorStatus | undefined;
}) {
  const decisions = useUraSensorInt(sensorId(def.key, "decisions_today"));
  const override = useUraSensorInt(sensorId(def.key, "override_frequency"));
  const compliance = useUraSensorInt(sensorId(def.key, "compliance_rate"));
  const lastDecision = useUraSensorState(sensorId(def.key, "last_decision"));

  const cardCls = statusToCardClass(summaryStatus?.status);
  const badge = statusToBadge(summaryStatus?.status);

  const overrideText = num(override.value);
  // ALERT if override frequency is anomalous high. Use coordinator-level
  // anomaly flag from summary (active_anomalies > 0) rather than re-deriving
  // the z-score here.
  const overrideAlert =
    (summaryStatus?.active_anomalies ?? 0) > 0 &&
    (summaryStatus?.status === "alert" || summaryStatus?.status === "critical");

  return (
    <div className={`card col-4 ${cardCls}`.trim()}>
      <div className="card-head">
        <div className="card-title">{def.label}</div>
        <span className={`badge ${badge.cls}`.trim()}>{badge.label}</span>
      </div>
      <div className="card-row">
        <span>Decisions today</span>
        <span className="tabular">{overrideText === "—" && decisions.value == null ? "—" : num(decisions.value)}</span>
      </div>
      <div className="card-row">
        <span>Last decision</span>
        <span className="dim">{formatClockTime(lastDecision.state)}</span>
      </div>
      <div className="card-row">
        <span>Compliance</span>
        <span className="tabular">
          {compliance.value == null ? "—" : `${compliance.value}%`}
        </span>
      </div>
      <div className="card-row">
        <span>Override freq</span>
        <span
          className="tabular"
          style={overrideAlert ? { color: "var(--status-red)" } : undefined}
        >
          {overrideText === "—" ? "—" : `${overrideText} / day`}
          {overrideAlert && (
            <>
              {" "}
              <span className="badge red">ALERT</span>
            </>
          )}
        </span>
      </div>
      <div className="card-controls">
        <label className="row" style={{ gap: 6, fontSize: "var(--text-xs)", flex: 1 }}>
          <span>Enabled</span>
          <span className="spacer"></span>
          <span className="toggle">
            {/* read-only toggle — backing service wiring deferred */}
            <input type="checkbox" checked={summaryStatus?.enabled ?? false} readOnly />
            <span className="toggle-slot"></span>
          </span>
        </label>
        <button className="btn sm" type="button">
          Restart
        </button>
      </div>
    </div>
  );
}

/** Decision-stream timeline — derived from each coordinator's last_decision sensor. */
function DecisionStream() {
  const presence = useUraSensorState(sensorId("presence", "last_decision"));
  const hvac = useUraSensorState(sensorId("hvac", "last_decision"));
  const energy = useUraSensorState(sensorId("energy", "last_decision"));
  const safety = useUraSensorState(sensorId("safety", "last_decision"));
  const security = useUraSensorState(sensorId("security", "last_decision"));

  type Row = { coord: string; ts: string | null; attrs: Record<string, unknown> | null };
  const rows: Row[] = [
    { coord: "Presence", ts: presence.state, attrs: presence.attributes },
    { coord: "HVAC", ts: hvac.state, attrs: hvac.attributes },
    { coord: "Energy", ts: energy.state, attrs: energy.attributes },
    { coord: "Safety", ts: safety.state, attrs: safety.attributes },
    { coord: "Security", ts: security.state, attrs: security.attributes },
  ];

  // Sort by timestamp desc; rows with null/unparseable ts sink to the bottom.
  const ranked = rows
    .map((r) => ({ ...r, parsed: r.ts ? Date.parse(r.ts) : NaN }))
    .sort((a, b) => {
      const aValid = !Number.isNaN(a.parsed);
      const bValid = !Number.isNaN(b.parsed);
      if (aValid && bValid) return b.parsed - a.parsed;
      if (aValid) return -1;
      if (bValid) return 1;
      return 0;
    })
    .slice(0, 5);

  const validCount = ranked.filter((r) => !Number.isNaN(r.parsed)).length;

  return (
    <div className="card col-8">
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-brain" />
          </svg>
          Decisions stream · last 30 min
        </div>
        <span className="badge accent">{validCount} events</span>
      </div>
      <div className="timeline">
        {ranked.map((r, i) => {
          const reason =
            (r.attrs && typeof r.attrs["reason"] === "string"
              ? (r.attrs["reason"] as string)
              : null) ?? "";
          const headline =
            (r.attrs && typeof r.attrs["headline"] === "string"
              ? (r.attrs["headline"] as string)
              : null) ?? "—";
          return (
            <div className="timeline-row" key={`${r.coord}-${i}`}>
              <div className="timeline-time">{formatClockTime(r.ts)}</div>
              <div className="timeline-body">
                <div className="timeline-headline">
                  <span className="badge accent">{r.coord}</span> {headline}
                </div>
                {reason && <div className="timeline-reason">{reason}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Top anomalies strip. Hidden when no coordinator reports active anomalies. */
function ActiveAnomalies({ statusMap }: { statusMap: Record<string, PerCoordinatorStatus> | undefined }) {
  if (!statusMap) return null;
  const offenders = Object.entries(statusMap).filter(
    ([, v]) => (v?.active_anomalies ?? 0) > 0,
  );
  if (offenders.length === 0) return null;

  const totalCount = offenders.reduce((acc, [, v]) => acc + (v.active_anomalies ?? 0), 0);

  return (
    <div className="grid">
      <div className="card col-12 status-red">
        <div className="card-head">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-alert" />
            </svg>
            Active anomalies · {totalCount}
          </div>
          <div className="row" style={{ gap: "var(--space-xs)" }}>
            <button className="btn sm" type="button">
              Floor: ALERT
            </button>
            <button className="btn sm" type="button">
              Acknowledge all
            </button>
          </div>
        </div>
        <div className="timeline">
          {offenders.map(([coord, info]) => {
            const badge = statusToBadge(info.status);
            return (
              <div className="timeline-row" key={coord}>
                <div className="timeline-time">—</div>
                <div className="timeline-body">
                  <div className="timeline-headline">
                    <span className={`badge ${badge.cls}`.trim()}>
                      {badge.label.toUpperCase()}
                    </span>{" "}
                    {coord} · {info.active_anomalies} active
                  </div>
                  <div className="timeline-reason">
                    Coordinator anomaly detector flagged {info.active_anomalies} signal
                    {info.active_anomalies === 1 ? "" : "s"}.
                  </div>
                </div>
                <button className="btn sm" type="button">
                  Ack
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * Read-only controls bar. See file header DEFERRED section.
 * Markup mirrors diagnostics.html verbatim.
 */
function ControlsBar() {
  return (
    <div className="controls-bar">
      <div className="knob span-3">
        <div className="knob-label">
          Anomaly floor{" "}
          <svg className="icon-sm dim">
            <use href="#lc-alert" />
          </svg>
        </div>
        <div className="knob-value">
          ALERT <span className="badge accent">3</span>
        </div>
        <div className="knob-action">
          <input type="range" min={0} max={4} defaultValue={3} className="slider" readOnly />
        </div>
        <div className="card-sub">
          INFO · WARN · ADVISORY · <strong>ALERT</strong> · CRITICAL
        </div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">Routine awareness floor</div>
        <div className="knob-value">
          ALERT <span className="badge accent">3</span>
        </div>
        <div className="knob-action">
          <input type="range" min={0} max={4} defaultValue={3} className="slider" readOnly />
        </div>
        <div className="card-sub">Only emit routine events ≥ this severity</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">DB maintenance</div>
        <div
          className="knob-action"
          style={{ marginTop: 0, flexDirection: "column", alignItems: "stretch" }}
        >
          <button className="btn sm" type="button">
            Run VACUUM
          </button>
          <button className="btn sm" type="button">
            Prune retention
          </button>
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Observation mode (all)</div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            URA records, no act
          </span>
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Telemetry</div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            decision log
          </span>
        </div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            anomaly log
          </span>
        </div>
      </div>
    </div>
  );
}

/** System info card (lower-right of the coordinator grid). */
function SystemCard({ summary }: { summary: SummaryAttrs | null }) {
  const dbSize = useUraSensorFloat(DB_SIZE_SENSOR);
  const dbSizeText = dbSize.value == null ? "—" : `${dbSize.value.toFixed(0)} MB`;
  const registered = summary?.coordinators_registered ?? null;
  const active = summary?.coordinators_active ?? null;

  return (
    <div className="card col-4">
      <div className="card-head">
        <div className="card-title">System</div>
        <span className="badge">info</span>
      </div>
      <div className="card-row">
        <span>Version</span>
        <span className="mono">v5.0</span>
      </div>
      <div className="card-row">
        <span>Coordinators</span>
        <span className="tabular mono">
          {active == null || registered == null ? "—" : `${active}/${registered}`}
        </span>
      </div>
      <div className="card-row">
        <span>DB size</span>
        <span className="tabular">{dbSizeText}</span>
      </div>
      <div className="card-row">
        <span>Uptime</span>
        <span className="tabular">—</span>
      </div>
      <div className="card-row">
        <span>Write queue</span>
        <span className="tabular">—</span>
      </div>
    </div>
  );
}

/** Placeholder automation-health card (no backing data — see DEFERRED). */
function AutomationHealth() {
  return (
    <div className="card col-4">
      <div className="card-head">
        <div className="card-title">Automation health</div>
        <span className="badge">—</span>
      </div>
      <div className="card-row">
        <span>Runs today</span>
        <span className="tabular">—</span>
      </div>
      <div className="card-row">
        <span>Failed</span>
        <span className="tabular">—</span>
      </div>
      <div className="card-row">
        <span>Last error</span>
        <span className="dim">—</span>
      </div>
      <div className="card-row">
        <span>Avg exec</span>
        <span className="tabular">—</span>
      </div>
      <div className="card-row">
        <span>P95 exec</span>
        <span className="tabular">—</span>
      </div>
      <div className="card-controls">
        <button className="btn sm" type="button">
          View logs
        </button>
      </div>
    </div>
  );
}

export function Diagnostics() {
  const summary = useUraSensorAttrs<SummaryAttrs>(COORDINATOR_SUMMARY_SENSOR);
  const summaryAttrs = summary.attrs;
  const statusMap = summaryAttrs?.status_per_coordinator;
  const coordRegistered = summaryAttrs?.coordinators_registered;

  return (
    <section className="tab active" data-tab="diagnostics">
      <header className="page-header">
        <div>
          <h1 className="page-title">Diagnostics</h1>
          <div className="page-subtitle">
            URA Dashboard v5.0
            {coordRegistered != null && (
              <Fragment> · {coordRegistered}/5 coordinators</Fragment>
            )}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn" type="button">
            <svg className="icon">
              <use href="#lc-activity" />
            </svg>{" "}
            Logs
          </button>
          <button className="btn" type="button">
            <svg className="icon">
              <use href="#lc-settings" />
            </svg>{" "}
            Reload
          </button>
        </div>
      </header>

      <ControlsBar />

      <ActiveAnomalies statusMap={statusMap} />

      <div className="section-head">
        <h2>Coordinators</h2>
      </div>
      <div className="grid">
        {COORDINATORS.map((def) => (
          <CoordinatorCard
            key={def.key}
            def={def}
            summaryStatus={statusMap?.[def.key]}
          />
        ))}
        <SystemCard summary={summaryAttrs} />
      </div>

      <div className="grid" style={{ marginTop: "var(--space-lg)" }}>
        <DecisionStream />
        <AutomationHealth />
      </div>
    </section>
  );
}
