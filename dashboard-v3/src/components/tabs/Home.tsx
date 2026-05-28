/**
 * Home tab — React port of home.html (P6 light styled).
 *
 * Home is the dashboard's overview surface — aggregates summary-level data
 * across all 5 coordinators without per-coordinator depth. Per-coordinator
 * detail lives on the Presence / HVAC / Energy / Security / Safety tabs.
 *
 * Patterns inherited from Diagnostics.tsx; see that file's header.
 *
 * DEFERRED for follow-up cycles:
 *   - Per-person presence cards (Oji / Ezinne / Jaya / Ziri): the underlying
 *     person tracker entity ids are install-specific (BLE/device_tracker
 *     per-person, custom slugs). Rendered as a placeholder grid with a
 *     TODO until those entities are surfaced as URA aggregator sensors.
 *   - Weather + outside temp: no URA weather entity exists. Static "—".
 *   - HVAC zone breakdown (Main / Master / Kids rows): would duplicate the
 *     HVAC tab's responsibility; the Home tab shows the comfort score only.
 *   - Routine awareness "next state" prediction + accuracy %: no aggregator
 *     sensor exists yet; reads what it can from house_state.
 *   - Security / lock / camera counts: no URA aggregator. Static.
 *   - Top knobs (House mode, Anomaly floor, Battery reserve, scenes, quick
 *     toggles): read-only — same justification as Diagnostics' controls bar.
 */
import {
  useUraSensorInt,
  useUraSensorFloat,
  useUraSensorState,
  useUraSensorAttrs,
} from "../../data/useUraSensor";
import {
  statusToCardClass,
  statusToBadge,
  num,
  formatClockTime,
} from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";
import type { PerCoordinatorStatus } from "../../data/useCoordinatorSummary";

// ─── Entity IDs ──────────────────────────────────────────────────────────────
// VERIFIED 2026-05-19 against live HA: state = "home_day".
// (URA also exposes sensor.ura_coordinator_manager_house_state — same value.)
const HOUSE_STATE_SENSOR = "sensor.universal_room_automation_house_state";
// ZoneMotionEventCountSensor — TELEMETRY_LAYER.md §Group C.
const ZONES_WITH_MOTION_SENSOR =
  "sensor.universal_room_automation_zones_with_motion";
// Aggregator sensor on parent device — see Energy.tsx comments for the slug.
// TODO(entity-id): verify against live HA.
const WHOLE_HOUSE_POWER_SENSOR =
  "sensor.universal_room_automation_whole_house_power";
const WHOLE_HOUSE_COST_SENSOR =
  "sensor.universal_room_automation_whole_house_cost_today";
const GRID_DEMAND_SENSOR =
  "sensor.universal_room_automation_energy_grid_demand";
// VERIFIED 2026-05-19 against live HA: state = "mid_peak".
const TOU_PERIOD_SENSOR = "sensor.ura_energy_coordinator_tou_period";

// VERIFIED 2026-05-19 against live HA (single-install per memory). State = 96.
const ENVOY_BATTERY_SOC = "sensor.envoy_482543015950_battery";

interface ZonesWithMotionAttrs {
  zones?: string[];
  window_minutes?: number;
}

interface GridDemandAttrs {
  grid_import_kw?: number;
  exporting?: boolean;
}

/** Compact status pill for a coordinator row in the system-overview card. */
function CoordinatorPill({
  label,
  status,
}: {
  label: string;
  status: PerCoordinatorStatus | undefined;
}) {
  const badge = statusToBadge(status?.status);
  return (
    <div className="card-row">
      <span>{label}</span>
      <span className={`badge ${badge.cls}`.trim()}>{badge.label}</span>
    </div>
  );
}

/** Status bar — at-a-glance house state strip beneath the controls bar. */
function StatusBar({
  houseState,
  zonesCount,
  zonesList,
  gridKw,
  gridExporting,
  houseKw,
  anomalyTotal,
}: {
  houseState: string | null;
  zonesCount: number | null;
  zonesList: string[];
  gridKw: number | null;
  gridExporting: boolean;
  /** Fallback when grid_demand is unavailable (no cap configured) — total
   *  house load from whole_house_power. Different metric from gridKw. */
  houseKw: number | null;
  anomalyTotal: number;
}) {
  const displayKw = gridKw ?? houseKw;
  const displayLabel =
    gridKw != null ? (gridExporting ? "exporting" : "from grid") : "house load";
  return (
    <div className="status-bar">
      <div className="status-bar-item">
        <span className="dot green live"></span>
        <strong>{houseState ?? "—"}</strong>
      </div>
      <div className="status-bar-divider"></div>
      <div className="status-bar-item">
        <svg className="icon-sm">
          <use href="#lc-users" />
        </svg>
        <strong>{num(zonesCount)}</strong>
        <span className="dim">
          zones with motion
          {zonesList.length > 0 ? ` · ${zonesList.slice(0, 3).join(", ")}` : ""}
        </span>
      </div>
      <div className="status-bar-divider"></div>
      <div className="status-bar-item">
        <svg className="icon-sm">
          <use href="#lc-zap" />
        </svg>
        <strong className="tabular">
          {displayKw == null
            ? "—"
            : gridKw != null && gridExporting
              ? `-${Math.abs(displayKw).toFixed(1)} kW`
              : `${displayKw.toFixed(1)} kW`}
        </strong>
        <span className="dim">{displayLabel}</span>
      </div>
      <div className="spacer"></div>
      {anomalyTotal > 0 && (
        <div className="status-bar-item">
          <span className="badge red">
            <svg className="icon-sm">
              <use href="#lc-alert" />
            </svg>
            {anomalyTotal} {anomalyTotal === 1 ? "anomaly" : "anomalies"}
          </span>
        </div>
      )}
    </div>
  );
}

/** Read-only knob row at the top of the Home tab. See DEFERRED. */
function ControlsBar({ houseState }: { houseState: string | null }) {
  const modes = ["home", "sleep", "away", "guest", "vacation"];
  return (
    <div className="controls-bar">
      <div className="knob span-4">
        <div className="knob-label">House mode</div>
        <div
          className="pill-group"
          role="tablist"
          aria-label="House mode"
          style={{ width: "100%" }}
        >
          {modes.map((m) => (
            <button
              key={m}
              type="button"
              className={houseState && houseState.toLowerCase().includes(m) ? "active" : ""}
              style={{ flex: 1, textTransform: "capitalize" }}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      <div className="knob span-2">
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
          <input
            type="range"
            min={0}
            max={4}
            defaultValue={3}
            className="slider"
            readOnly
          />
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">
          Battery reserve{" "}
          <svg className="icon-sm dim">
            <use href="#lc-battery" />
          </svg>
        </div>
        <div className="knob-value tabular">
          —{" "}
          <span
            className="dim"
            style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
          >
            %
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={10}
            max={80}
            defaultValue={25}
            className="slider"
            readOnly
          />
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Scenes</div>
        <div
          className="knob-action"
          style={{ marginTop: 0, flexWrap: "wrap" }}
        >
          <button className="btn sm" type="button">
            All off
          </button>
          <button className="btn sm" type="button">
            Evening
          </button>
          <button className="btn sm" type="button">
            Movie
          </button>
          <button className="btn sm" type="button">
            Bed
          </button>
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Quick toggles</div>
        <div className="card-row">
          <span>Notifications</span>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
        </div>
        <div className="card-row">
          <span>Do not disturb</span>
          <label className="toggle">
            <input type="checkbox" readOnly />
            <span className="toggle-slot"></span>
          </label>
        </div>
      </div>
    </div>
  );
}

/** URA Coordinators hero card — counts + latest decision summary. */
function UraBrainHero({
  registered,
  active,
  decisionsToday,
  statusPer,
}: {
  registered: number | null;
  active: number | null;
  decisionsToday: number | null;
  statusPer: Record<string, PerCoordinatorStatus> | undefined;
}) {
  const healthy = statusPer
    ? Object.values(statusPer).filter((s) => s.status === "nominal").length
    : null;
  const headerBadge =
    healthy == null || registered == null
      ? { label: "—", cls: "" }
      : healthy === registered
        ? { label: `${healthy}/${registered} healthy`, cls: "green" }
        : { label: `${healthy}/${registered} healthy`, cls: "orange" };

  // Reuse the same last_decision sensors Diagnostics' DecisionStream pulls;
  // pick the freshest across all five for the "Latest decision" row.
  const presence = useUraSensorState("sensor.ura_coordinator_manager_presence_last_decision");
  const hvac = useUraSensorState("sensor.ura_coordinator_manager_hvac_last_decision");
  const energy = useUraSensorState("sensor.ura_coordinator_manager_energy_last_decision");
  const safety = useUraSensorState("sensor.ura_coordinator_manager_safety_last_decision");
  const security = useUraSensorState("sensor.ura_coordinator_manager_security_last_decision");

  const candidates: Array<{ coord: string; ts: string | null; attrs: Record<string, unknown> | null }> = [
    { coord: "Presence", ts: presence.state, attrs: presence.attributes },
    { coord: "HVAC", ts: hvac.state, attrs: hvac.attributes },
    { coord: "Energy", ts: energy.state, attrs: energy.attributes },
    { coord: "Safety", ts: safety.state, attrs: safety.attributes },
    { coord: "Security", ts: security.state, attrs: security.attributes },
  ];
  const latest = candidates
    .map((c) => ({ ...c, parsed: c.ts ? Date.parse(c.ts) : NaN }))
    .filter((c) => !Number.isNaN(c.parsed))
    .sort((a, b) => b.parsed - a.parsed)[0];

  const latestHeadline =
    latest?.attrs && typeof latest.attrs["headline"] === "string"
      ? (latest.attrs["headline"] as string)
      : null;

  return (
    <div className="card col-6 strong">
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-brain" />
          </svg>
          URA Coordinators
        </div>
        <span className={`badge ${headerBadge.cls}`.trim()}>
          {headerBadge.label}
        </span>
      </div>
      <div className="row" style={{ gap: "var(--space-md)" }}>
        <div>
          <div className="card-value tabular">{num(decisionsToday)}</div>
          <div className="card-sub">decisions today</div>
        </div>
        <div
          style={{
            flex: 1,
            borderLeft: "1px solid var(--glass-border)",
            paddingLeft: "var(--space-md)",
          }}
        >
          <div className="card-sub" style={{ marginBottom: 4 }}>
            Coordinators{" "}
            <span className="dim">
              {active == null || registered == null
                ? "—"
                : `${active}/${registered} active`}
            </span>
          </div>
          <div className="row" style={{ gap: "var(--space-xs)" }}>
            <strong>
              {latest?.coord ?? "—"}
              {latestHeadline ? (
                <span className="dim"> · {latestHeadline}</span>
              ) : null}
            </strong>
          </div>
        </div>
      </div>
      <div
        className="card-row"
        style={{
          borderTop: "1px solid var(--glass-border)",
          paddingTop: "var(--space-sm)",
          marginTop: "var(--space-xs)",
        }}
      >
        <span className="dim">Latest decision · {formatClockTime(latest?.ts ?? null)}</span>
        <span>{latest?.coord ?? "—"}</span>
      </div>
    </div>
  );
}

/** Energy-now card (right-hand side of the hero row). */
function EnergyNowCard() {
  const gridDemand = useUraSensorAttrs<GridDemandAttrs>(GRID_DEMAND_SENSOR);
  const wholePower = useUraSensorFloat(WHOLE_HOUSE_POWER_SENSOR);
  const wholeCost = useUraSensorFloat(WHOLE_HOUSE_COST_SENSOR);
  const batterySoc = useUraSensorFloat(ENVOY_BATTERY_SOC);
  const tou = useUraSensorState(TOU_PERIOD_SENSOR);

  const gridKw = gridDemand.attrs?.grid_import_kw ?? null;
  const exporting = gridDemand.attrs?.exporting ?? false;
  // v5.0.4 fallback to whole_house_power (W → kW) when grid_demand is unavailable
  const houseKw =
    wholePower.value == null ? null : Math.round((wholePower.value / 1000) * 10) / 10;
  const displayKw = gridKw ?? houseKw;
  const displayLabel =
    gridKw != null ? (exporting ? "exporting" : "from grid") : "house load";
  const period = tou.unavailable || tou.state == null ? null : tou.state;
  const periodBadgeCls =
    period === "peak"
      ? "red"
      : period === "mid_peak"
        ? "yellow"
        : period === "off_peak"
          ? "green"
          : "";
  const periodLabel =
    period === "off_peak"
      ? "off-peak"
      : period === "mid_peak"
        ? "mid-peak"
        : period === "peak"
          ? "peak"
          : "—";

  const cardCls =
    gridKw == null ? "" : gridKw > 0.1 ? "status-orange" : "status-green";

  return (
    <div className={`card col-3 ${cardCls}`.trim()}>
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-zap" />
          </svg>
          Energy now
        </div>
        <span className={`badge ${periodBadgeCls}`.trim()}>{periodLabel}</span>
      </div>
      <div className="card-value tabular">
        {displayKw == null
          ? "—"
          : gridKw != null && exporting
            ? `-${Math.abs(displayKw).toFixed(1)}`
            : displayKw.toFixed(1)}
        <span className="card-unit">kW</span>
      </div>
      <div className="card-sub">{displayLabel}</div>
      <div className="card-row">
        <span>Battery</span>
        <span>
          <strong>{num(batterySoc.value, "%")}</strong>
        </span>
      </div>
      <div className="card-row">
        <span>Cost today</span>
        <span className="tabular">
          {wholeCost.value == null ? "—" : `$${wholeCost.value.toFixed(2)}`}
        </span>
      </div>
    </div>
  );
}

/** Active-anomalies card on the hero row — summary view. */
function AnomaliesCard({
  statusMap,
}: {
  statusMap: Record<string, PerCoordinatorStatus> | undefined;
}) {
  if (!statusMap) {
    return (
      <div className="card col-3">
        <div className="card-head">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-alert" />
            </svg>
            Anomalies
          </div>
          <span className="badge">—</span>
        </div>
        <div className="card-sub">Awaiting coordinator summary</div>
      </div>
    );
  }
  const offenders = Object.entries(statusMap).filter(
    ([, v]) => (v?.active_anomalies ?? 0) > 0,
  );
  if (offenders.length === 0) {
    return (
      <div className="card col-3 status-green">
        <div className="card-head">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-alert" />
            </svg>
            Anomalies
          </div>
          <span className="badge green">none</span>
        </div>
        <div className="card-sub">All coordinators nominal</div>
      </div>
    );
  }
  const total = offenders.reduce((acc, [, v]) => acc + (v.active_anomalies ?? 0), 0);
  const worst = offenders
    .map(([, v]) => v.status)
    .find((s) => s === "critical" || s === "alert") ?? "advisory";
  const cardCls = statusToCardClass(worst);
  const badge = statusToBadge(worst);

  return (
    <div className={`card col-3 ${cardCls}`.trim()}>
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-alert" />
          </svg>
          Anomalies
        </div>
        <span className={`badge ${badge.cls}`.trim()}>
          {total} active
        </span>
      </div>
      {offenders.slice(0, 3).map(([coord, info]) => {
        const b = statusToBadge(info.status);
        return (
          <div className="card-row" key={coord}>
            <span className={`badge ${b.cls}`.trim()}>{b.label.toUpperCase()}</span>
            <span className="dim">
              {coord} · {info.active_anomalies}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Compact 5-coordinator status overview. */
function CoordinatorOverview({
  statusMap,
}: {
  statusMap: Record<string, PerCoordinatorStatus> | undefined;
}) {
  const labels: Array<[string, string]> = [
    ["presence", "Presence"],
    ["hvac", "HVAC"],
    ["energy", "Energy"],
    ["safety", "Safety"],
    ["security", "Security"],
  ];
  return (
    <div className="card col-4">
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-brain" />
          </svg>
          Coordinator status
        </div>
        <span className="badge">5</span>
      </div>
      {labels.map(([key, label]) => (
        <CoordinatorPill key={key} label={label} status={statusMap?.[key]} />
      ))}
    </div>
  );
}

export function Home() {
  const summary = useCoordinatorSummary();
  const houseStateSensor = useUraSensorState(HOUSE_STATE_SENSOR);
  const zonesCount = useUraSensorInt(ZONES_WITH_MOTION_SENSOR);
  const zonesAttrs = useUraSensorAttrs<ZonesWithMotionAttrs>(ZONES_WITH_MOTION_SENSOR);
  const wholePower = useUraSensorFloat(WHOLE_HOUSE_POWER_SENSOR);
  const gridDemand = useUraSensorAttrs<GridDemandAttrs>(GRID_DEMAND_SENSOR);

  const summaryAttrs = summary.attrs;
  const statusMap = summaryAttrs?.status_per_coordinator;
  const houseState =
    houseStateSensor.unavailable || houseStateSensor.state == null
      ? (summaryAttrs?.house_state ?? null)
      : houseStateSensor.state;

  const anomalyTotal = statusMap
    ? Object.values(statusMap).reduce(
        (acc, v) => acc + (v.active_anomalies ?? 0),
        0,
      )
    : 0;

  const gridKw = gridDemand.attrs?.grid_import_kw ?? null;
  const exporting = gridDemand.attrs?.exporting ?? false;

  // Derive house power for the subtitle when available.
  // sensor.universal_room_automation_whole_house_power is in WATTS (per
  // the entity's unit_of_measurement attribute), so divide by 1000 to get kW.
  const houseKw =
    wholePower.value == null ? null : Math.round((wholePower.value / 1000) * 10) / 10;

  // v5.0.4 status-bar fallback: when sensor.energy_grid_demand is unavailable
  // (it requires _grid_import_cap_enabled in EC options — not always set),
  // surface whole_house_power as "house load" instead of rendering "—".
  // StatusBar handles this via its own displayKw/displayLabel locals; the
  // EnergyNowCard further down also reads gridKw / houseKw and applies its
  // own fallback so its kW value isn't "—" either.

  return (
    <section className="tab active" data-tab="home">
      <header className="page-header">
        <div>
          <h1 className="page-title">Home</h1>
          <div className="page-subtitle">
            {houseState ?? "—"}
            {houseKw != null && (
              <>
                {" "}· house load <strong className="tabular">{houseKw} kW</strong>
              </>
            )}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn" type="button">
            <svg className="icon">
              <use href="#lc-bell" />
            </svg>
          </button>
          <button className="btn" type="button">
            <svg className="icon">
              <use href="#lc-settings" />
            </svg>
          </button>
        </div>
      </header>

      <ControlsBar houseState={houseState} />

      <StatusBar
        houseState={houseState}
        zonesCount={zonesCount.value}
        zonesList={zonesAttrs.attrs?.zones ?? []}
        gridKw={gridKw}
        gridExporting={exporting}
        houseKw={houseKw}
        anomalyTotal={anomalyTotal}
      />

      <div className="grid">
        <UraBrainHero
          registered={summaryAttrs?.coordinators_registered ?? null}
          active={summaryAttrs?.coordinators_active ?? null}
          decisionsToday={summaryAttrs?.decisions_today ?? null}
          statusPer={statusMap}
        />
        <EnergyNowCard />
        <AnomaliesCard statusMap={statusMap} />
      </div>

      <div className="section-head">
        <h2>System quick reads</h2>
      </div>
      <div className="grid">
        <CoordinatorOverview statusMap={statusMap} />
        <div className="card col-4 status-blue">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-sparkles" />
              </svg>
              Routine awareness
            </div>
            <span className="badge">—</span>
          </div>
          <div className="card-row">
            <span>Next state</span>
            <span>
              <strong>—</strong>
            </span>
          </div>
          <div className="card-row">
            <span>Confidence</span>
            <span className="tabular">—</span>
          </div>
          <div className="card-sub">
            Next-state prediction sensor deferred (see Home.tsx)
          </div>
        </div>
        <div className="card col-4">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-shield" />
              </svg>
              Security
            </div>
            <span className="badge">—</span>
          </div>
          <div className="card-row">
            <span>Locks</span>
            <span>—</span>
          </div>
          <div className="card-row">
            <span>Cameras</span>
            <span>—</span>
          </div>
          <div className="card-sub">
            Security aggregator sensor deferred (see Home.tsx)
          </div>
        </div>
      </div>
    </section>
  );
}
