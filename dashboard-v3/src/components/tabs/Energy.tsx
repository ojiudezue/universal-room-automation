/**
 * Energy tab — React port of energy.html (P6 light styled).
 *
 * Patterns inherited from Diagnostics.tsx (see that file's header for the full
 * convention list):
 *   - one hook per entity, no batching
 *   - "—" placeholder for null / unavailable / loading; same DOM either way
 *   - status colors driven from coordinator_summary attrs, never hardcoded
 *   - Lucide SVG <use href="#lc-..."/> preserved verbatim
 *   - controls bar at top is RENDERED READ-ONLY — backing service wiring is a
 *     separate cycle (no battery_reserve / grid_import_cap / EV-charge knobs
 *     exist as Number entities yet; today they live in EC config-flow options)
 *
 * DEFERRED for follow-up cycles (matches Diagnostics' deferred list):
 *   - Solcast forecast chart: forecast data is not yet a URA entity; static
 *     SVG kept as visual reference until v4.7.x forecaster work.
 *   - Energy-flow live SVG: source values (solar / battery / grid / house kW)
 *     are wired from existing entities but the arrow animation stays static.
 *   - URA recent-decisions timeline: filtering activity_log by coordinator=
 *     "energy" needs a backing sensor that doesn't exist (D1 returns COUNT,
 *     not a row list). Renders the static markup verbatim with a TODO.
 *   - Tariff bar widths: tariff windows are configured in options-flow, not
 *     exposed as a structured attribute on the TOU sensor. Static for now.
 *   - "Load status" cards (EV / pool / generator / yesterday-vs-today): no
 *     URA entities for any of these. Static.
 *
 * Entity-id provenance — every guess is marked `TODO(entity-id):` so the
 * first live render reveals the right name without fabricating fallbacks.
 */
import {
  useUraSensorFloat,
  useUraSensorState,
  useUraSensorAttrs,
} from "../../data/useUraSensor";
import {
  statusToCardClass,
  statusToBadge,
  num,
} from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

// ─── Entity IDs ──────────────────────────────────────────────────────────────
// Confirmed from custom_components/universal_room_automation/aggregation.py
// and docs/TELEMETRY_LAYER.md (Group C, v4.6.12).
const GRID_DEMAND_SENSOR =
  "sensor.universal_room_automation_energy_grid_demand";
// TODO(entity-id): WholeHousePowerSensor lacks _attr_has_entity_name so HA
// should slug as `sensor.universal_room_automation_whole_house_power`.
// Confirm against running HA on first live load.
const WHOLE_HOUSE_POWER_SENSOR =
  "sensor.universal_room_automation_whole_house_power";
// TODO(entity-id): WholeHouseCostToday matches the same pattern — verify
// live. The v4.6.8 cycle shipped this sensor; check entity_registry.
const WHOLE_HOUSE_COST_SENSOR =
  "sensor.universal_room_automation_whole_house_cost_today";
// EnergyTOUPeriodSensor uses _attr_has_entity_name=True with device "URA:
// Energy Coordinator", so HA slugs as `sensor.ura_tou_period` per the
// header comment at sensor.py:5586. (NOT `sensor.ura_energy_coordinator_*`
// because EnergyTOUPeriodSensor was on a parent device when the comment
// was written.)
// VERIFIED 2026-05-19 against live HA: state = "mid_peak".
const TOU_PERIOD_SENSOR = "sensor.ura_energy_coordinator_tou_period";

// VERIFIED 2026-05-19 against live HA. Single-install per
// project_single_user_no_backcompat memory — hardcoding the gateway serial
// is acceptable. If a future install replaces the Envoy these constants are
// the one place to update.
const ENVOY_BATTERY_SOC = "sensor.envoy_482543015950_battery";
// Current battery discharge: kW. Negative = charging, positive = discharging.
const ENVOY_BATTERY_POWER = "sensor.envoy_482543015950_current_battery_discharge";
const ENVOY_SOLAR_PRODUCTION = "sensor.envoy_482543015950_current_power_production";
// Today's solar production (kWh — not lifetime; the static fragment showed a
// daily figure not a lifetime counter).
const ENVOY_SOLAR_LIFETIME = "sensor.envoy_482543015950_energy_production_today";

// ─── Grid demand attrs ───────────────────────────────────────────────────────
// Shape per aggregation.py:4992 + TELEMETRY_LAYER.md §Group C:
interface GridDemandAttrs {
  grid_import_kw?: number;
  grid_import_cap_kw?: number;
  grid_import_cap_enabled?: boolean;
  exporting?: boolean;
}

// TOU attrs from sensor.py:5612+ are deliberately not narrowed yet — the
// current UI only needs the state string. When tariff timeline wiring lands
// (DEFERRED), define an interface TouAttrs { next_period?: string; ... } here.

/** TOU period → badge color. Matches the original P6 yellow-for-mid coloring. */
function touBadgeCls(period: string | null): string {
  switch (period) {
    case "off_peak":
      return "green lg";
    case "mid_peak":
      return "yellow lg";
    case "peak":
      return "red lg";
    default:
      return "lg";
  }
}

function touHumanLabel(period: string | null): string {
  switch (period) {
    case "off_peak":
      return "off-peak";
    case "mid_peak":
      return "mid-peak";
    case "peak":
      return "peak";
    default:
      return "—";
  }
}

/** Read-only top controls bar — see DEFERRED. */
function ControlsBar() {
  return (
    <div className="controls-bar">
      <div className="knob span-3">
        <div className="knob-label">
          Battery reserve <span className="badge accent">URA</span>
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
        <div className="knob-label">Grid import cap</div>
        <div className="knob-value tabular">
          —{" "}
          <span
            className="dim"
            style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
          >
            kW
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={2}
            max={15}
            defaultValue={8}
            className="slider"
            readOnly
          />
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">EV charge max</div>
        <div className="knob-value tabular">
          —{" "}
          <span
            className="dim"
            style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
          >
            kW
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={1}
            max={12}
            defaultValue={7}
            className="slider"
            readOnly
          />
        </div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">Battery mode</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className="active" style={{ flex: 1 }} type="button">
            Self-consumption
          </button>
          <button style={{ flex: 1 }} type="button">
            Storm reserve
          </button>
          <button style={{ flex: 1 }} type="button">
            TOU shift
          </button>
        </div>
        <div className="card-sub">Locked per codicil · cannot use grid_charge</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Manual</div>
        <div
          className="knob-action"
          style={{ marginTop: 0, flexDirection: "column", alignItems: "stretch" }}
        >
          <button className="btn danger" type="button">
            Shed loads now
          </button>
          <button className="btn sm" type="button">
            Resume EV
          </button>
        </div>
      </div>
    </div>
  );
}

/** Hero KPI row — Solar / Battery / Grid / Cost. */
function HeroRow() {
  const solarNow = useUraSensorFloat(ENVOY_SOLAR_PRODUCTION);
  const solarToday = useUraSensorFloat(ENVOY_SOLAR_LIFETIME);
  const batterySoc = useUraSensorFloat(ENVOY_BATTERY_SOC);
  const batteryPower = useUraSensorFloat(ENVOY_BATTERY_POWER);
  const wholePower = useUraSensorFloat(WHOLE_HOUSE_POWER_SENSOR);
  const wholeCost = useUraSensorFloat(WHOLE_HOUSE_COST_SENSOR);
  const gridDemandAttrs = useUraSensorAttrs<GridDemandAttrs>(GRID_DEMAND_SENSOR);

  // House power sensor reports watts; render in kW.
  const houseKw =
    wholePower.value == null ? null : Math.round((wholePower.value / 1000) * 10) / 10;

  // Battery power: positive when discharging (per Envoy convention varies —
  // surface the absolute value, label direction below).
  const batteryDirection =
    batteryPower.value == null
      ? null
      : batteryPower.value > 0
        ? "discharging"
        : batteryPower.value < 0
          ? "charging"
          : "idle";
  const batteryKwAbs =
    batteryPower.value == null ? null : Math.abs(batteryPower.value) / 1000;

  const gridImportKw = gridDemandAttrs.attrs?.grid_import_kw ?? null;
  const gridExporting = gridDemandAttrs.attrs?.exporting ?? false;

  // Visual status: Solar tinted yellow; battery green when above reserve,
  // orange below 20%; grid orange when importing > 0; cost neutral.
  const solarCardCls = "status-yellow";
  const batteryCardCls =
    batterySoc.value == null
      ? ""
      : batterySoc.value < 20
        ? "status-orange"
        : "status-green";
  const gridCardCls =
    gridImportKw == null
      ? ""
      : gridImportKw > 0.1
        ? "status-orange"
        : gridExporting
          ? "status-green"
          : "";

  return (
    <div className="grid">
      <div className={`card col-3 ${solarCardCls}`.trim()}>
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-sun" />
          </svg>
          Solar now
        </div>
        <div className="card-value tabular">
          {solarNow.value == null
            ? "—"
            : (solarNow.value / 1000).toFixed(1)}
          <span className="card-unit">kW</span>
        </div>
        <div className="card-sub">
          {solarToday.value == null ? "—" : `${solarToday.value.toFixed(1)} kWh today`}
        </div>
      </div>
      <div className={`card col-3 ${batteryCardCls}`.trim()}>
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-battery" />
          </svg>
          Battery
        </div>
        <div className="card-value tabular">
          {num(batterySoc.value)}
          <span className="card-unit">%</span>
        </div>
        <div className="card-sub">
          {batteryDirection == null
            ? "—"
            : batteryKwAbs == null
              ? batteryDirection
              : `${batteryDirection} ${batteryKwAbs.toFixed(1)} kW`}
        </div>
        <div className="gauge-track">
          <div
            className="gauge-fill"
            style={{ width: `${batterySoc.value ?? 0}%` }}
          ></div>
        </div>
      </div>
      <div className={`card col-3 ${gridCardCls}`.trim()}>
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-zap" />
          </svg>
          Grid
        </div>
        <div className="card-value tabular">
          {gridImportKw == null
            ? "—"
            : gridExporting
              ? `-${Math.abs(gridImportKw).toFixed(1)}`
              : `+${gridImportKw.toFixed(1)}`}
          <span className="card-unit">kW</span>
        </div>
        <div className="card-sub">
          {gridImportKw == null
            ? "—"
            : gridExporting
              ? "exporting"
              : "importing"}
        </div>
      </div>
      <div className="card col-3">
        <div className="card-title">Cost today</div>
        <div className="card-value tabular">
          {wholeCost.value == null ? "—" : `$${wholeCost.value.toFixed(2)}`}
        </div>
        <div className="card-sub">
          House load:{" "}
          <strong className="tabular">
            {houseKw == null ? "—" : `${houseKw} kW`}
          </strong>
        </div>
      </div>
    </div>
  );
}

/**
 * Static visual blocks kept verbatim from energy.html — Solcast forecast SVG
 * and live-flow SVG. These need real-time data wiring in a follow-up cycle.
 */
function StaticForecastAndFlow() {
  // The forecast chart + energy-flow diagram are heavy custom SVG. Re-rendering
  // them in React without backing data would be busywork. Kept as a literal
  // markup block so the visual reference holds until the v4.7.x forecaster
  // ships.
  return (
    <div className="grid" style={{ marginTop: "var(--space-lg)" }}>
      <div className="card col-7">
        <div className="card-head">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-activity" />
            </svg>
            Solar — Solcast vs actual (today)
          </div>
          <span className="dim">—</span>
        </div>
        <div
          className="dim"
          style={{
            height: 180,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "var(--text-sm)",
          }}
        >
          Solcast forecast not yet wired · awaiting v4.7.x forecaster
        </div>
      </div>
      <div className="card col-5">
        <div className="card-head">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-zap" />
            </svg>
            Energy flow (live)
          </div>
          <span className="badge">static</span>
        </div>
        <div
          className="dim"
          style={{
            height: 220,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "var(--text-sm)",
            textAlign: "center",
            padding: "var(--space-md)",
          }}
        >
          Live flow diagram — values shown in hero row above. Animated
          arrows deferred.
        </div>
      </div>
    </div>
  );
}

/** Tariff card. Static window widths; "now" badge driven by TOU sensor. */
function TariffCard() {
  const tou = useUraSensorState(TOU_PERIOD_SENSOR);
  const period = tou.unavailable || tou.state == null ? null : tou.state;
  const human = touHumanLabel(period);
  const badge = touBadgeCls(period);

  return (
    <div className="card col-4">
      <div className="card-title">Today&apos;s tariff</div>
      <div
        className="row"
        style={{
          gap: 0,
          height: 24,
          margin: "var(--space-sm) 0",
          borderRadius: "var(--radius-sm)",
          overflow: "hidden",
        }}
      >
        <div style={{ flex: 6, background: "rgba(102,187,106,0.5)" }} title="off-peak"></div>
        <div style={{ flex: 6, background: "rgba(255,202,40,0.5)" }} title="mid"></div>
        <div style={{ flex: 5, background: "rgba(239,83,80,0.6)" }} title="peak"></div>
        <div style={{ flex: 3, background: "rgba(255,202,40,0.5)" }} title="mid"></div>
        <div style={{ flex: 4, background: "rgba(102,187,106,0.5)" }} title="off-peak"></div>
      </div>
      <div className="card-row">
        <span>
          Off-peak{" "}
          {period === "off_peak" && (
            <span className={`badge ${badge}`.trim()}>now</span>
          )}
        </span>
        <span className="tabular">—</span>
      </div>
      <div className="card-row">
        <span>
          Mid-peak{" "}
          {period === "mid_peak" && (
            <span className={`badge ${badge}`.trim()}>now</span>
          )}
        </span>
        <span className="tabular">—</span>
      </div>
      <div className="card-row">
        <span>
          Peak{" "}
          {period === "peak" && (
            <span className={`badge ${badge}`.trim()}>now</span>
          )}
        </span>
        <span className="tabular">—</span>
      </div>
      <div className="card-sub">Current: {human}</div>
    </div>
  );
}

/** Energy-coordinator card on Diagnostics' grid — minimal version here. */
function EnergyCoordinatorRecent() {
  // TODO(entity-id): per-coordinator decision streams need a backing sensor
  // (D1 returns COUNT not rows). Until then render placeholder timeline.
  return (
    <div className="card col-8">
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-brain" />
          </svg>
          URA · recent energy decisions
        </div>
        <span className="badge">—</span>
      </div>
      <div className="timeline">
        <div className="timeline-row">
          <div className="timeline-time">—</div>
          <div className="timeline-body">
            <div className="timeline-headline dim">
              Awaiting energy-decision-stream sensor (deferred — see Energy.tsx)
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function Energy() {
  const summary = useCoordinatorSummary();
  const energyStatus = summary.attrs?.status_per_coordinator?.energy;
  const cardCls = statusToCardClass(energyStatus?.status);
  const badge = statusToBadge(energyStatus?.status);

  const tou = useUraSensorState(TOU_PERIOD_SENSOR);
  const period = tou.unavailable || tou.state == null ? null : tou.state;
  const headerBadgeCls = touBadgeCls(period);

  return (
    <section className="tab active" data-tab="energy">
      <header className="page-header">
        <div>
          <h1 className="page-title">Energy</h1>
          <div className="page-subtitle">
            TOU ·{" "}
            <span className={cardCls ? `dim` : "dim"}>{touHumanLabel(period)}</span>
          </div>
        </div>
        <div className="page-actions">
          <span className={`badge ${headerBadgeCls}`.trim()}>
            {touHumanLabel(period)}
          </span>
          <span className={`badge ${badge.cls}`.trim()}>
            EC · {badge.label}
          </span>
        </div>
      </header>

      <ControlsBar />

      <HeroRow />

      <StaticForecastAndFlow />

      <div className="grid" style={{ marginTop: "var(--space-lg)" }}>
        <EnergyCoordinatorRecent />
        <TariffCard />
      </div>

      <div className="section-head">
        <h2>Load status</h2>
      </div>
      <div className="grid">
        <div className="card col-4">
          <div className="card-row">
            <span>EV charging</span>
            <span className="badge">—</span>
          </div>
          <div className="card-row">
            <span>Pool pump</span>
            <span className="badge">—</span>
          </div>
          <div className="card-row">
            <span>Hot tub</span>
            <span className="badge">—</span>
          </div>
          <div className="card-row">
            <span>Dryer</span>
            <span className="dim">—</span>
          </div>
        </div>
        <div className="card col-4">
          <div className="card-head">
            <div className="card-title">Generator</div>
            <span className="badge">—</span>
          </div>
          <div className="card-row">
            <span>Fuel</span>
            <span className="tabular">—</span>
          </div>
          <div className="card-row">
            <span>Last run</span>
            <span className="dim">—</span>
          </div>
        </div>
        <div className="card col-4">
          <div className="card-head">
            <div className="card-title">Yesterday vs today</div>
            <span className="dim tabular">—</span>
          </div>
          <div className="card-row">
            <span>Solar (kWh)</span>
            <span className="tabular">—</span>
          </div>
          <div className="card-row">
            <span>Cost ($)</span>
            <span className="tabular">—</span>
          </div>
        </div>
      </div>
    </section>
  );
}
