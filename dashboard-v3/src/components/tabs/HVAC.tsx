/**
 * HVAC tab — React port of hvac.html (P6 light styled).
 *
 * Patterns inherited from Diagnostics.tsx / Home.tsx / Energy.tsx (see those
 * file headers for the full convention list). Notably:
 *   - one hook per entity, no batching
 *   - "—" placeholder for null / unavailable / loading
 *   - status colors driven from `sensor.ura_hvac_coordinator_zone_N_status`
 *     attrs (hvac_action, zone_presence_state) — never hardcoded
 *   - Lucide SVG <use href="#lc-..."/> preserved verbatim
 *   - All controls (setpoint stepper, mode pill-group, system mode, sliders,
 *     URA-mode toggles) render READ-ONLY — service-call wiring is a separate
 *     cycle (consistent with Diagnostics' controls bar)
 *
 * ZONE DISCOVERY (per CLAUDE.md "don't hardcode 19 room names" rule):
 *   The HVAC coordinator exposes `sensor.ura_hvac_coordinator_zone_{N}_status`
 *   sensors. The static fragment showed 5 zones (Main Living, Master, Kids,
 *   Guest, plus a Hazard guard card). The live install has 3 active zones
 *   per `hvac_system_demand.attributes.total_zones`. We render ALL zone
 *   sensors found in the registry — the unused zone_1/2/3 slots collapse
 *   gracefully when their state is "unavailable".
 *
 *   For v5.0 ship: probe zone_1..zone_5 (matches the per-zone preset sensor
 *   naming `hvac_zone_preset_zone_1..5`). If a zone is missing its preset/
 *   status sensor materialises as unavailable, the card just shows "—" and
 *   no false data leaks in.
 *
 * DEFERRED for follow-up cycles:
 *   - House setpoint stepper: no `climate.house_house_setpoint` aggregator
 *     exists. We surface a read-only "—°" placeholder.
 *   - "Today runtime / est cost / kWh": HVAC runtime sensors don't aggregate
 *     into a daily metric yet; renders "—".
 *   - URA intent chips (pre-cool/coast): would need a structured per-zone
 *     `intent` attr on the status sensor that isn't there yet. Renders the
 *     observable `hvac_action` only.
 *   - Hazard-guard limits / comfort weight / setback economy / routine
 *     awareness influence / min severity: pulled from coordinator config —
 *     no entities, so renders static labels with TODO markers.
 *   - Pre-cool likelihood: sensor exists
 *     (sensor.ura_hvac_coordinator_hvac_pre_cool_likelihood, integer %) —
 *     surfaced in the URA intent card.
 */
import {
  useUraSensorInt,
  useUraSensorFloat,
  useUraSensorState,
} from "../../data/useUraSensor";
import {
  statusToCardClass,
  statusToBadge,
  num,
} from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

// ─── Entity IDs ──────────────────────────────────────────────────────────────
// VERIFIED 2026-05-19 against live HA: state = "67", attrs include
// active_zones, active_count, total_zones, load_bucket.
const HVAC_SYSTEM_DEMAND = "sensor.universal_room_automation_hvac_system_demand";
// VERIFIED: state = "cooling" | "heating" | "off".
const HVAC_DIRECTION = "sensor.universal_room_automation_hvac_direction";
// VERIFIED: integer 0-100 (pre-cool probability).
const HVAC_PRE_COOL_LIKELIHOOD =
  "sensor.ura_hvac_coordinator_hvac_pre_cool_likelihood";
// VERIFIED: state = "idle" | "arming" | "running".
const HVAC_PRE_ARRIVAL_STATUS =
  "sensor.ura_hvac_coordinator_hvac_pre_arrival_status";
// VERIFIED: state = "monitoring" | "engaged".
const HVAC_ARRESTER_STATUS =
  "sensor.ura_hvac_coordinator_hvac_arrester_status";
// VERIFIED: state = "low" | "elevated" | "high".
const HVAC_COMFORT_RISK = "sensor.ura_hvac_coordinator_hvac_comfort_risk";
// Aggregator weighted avg (climate_delta = abs delta vs setpoint, F).
// VERIFIED 2026-05-19: state="23.2" (degF).
const CLIMATE_DELTA = "sensor.universal_room_automation_climate_delta";
// Outside-vs-inside temp delta. VERIFIED: state="-9.0".
const TEMP_DELTA_OUTSIDE = "sensor.universal_room_automation_temp_delta_outside";

// We probe up to 5 zones — the install has 3 today, the extras unmaterialise
// cleanly. If a future install grows beyond 5, bump this and the per-zone
// preset sensor probe in tandem.
const MAX_ZONES = 5;

interface ZoneStatusAttrs {
  zone_id?: string;
  climate_entity?: string;
  preset_mode?: string;
  hvac_action?: string; // "cooling" | "heating" | "idle" | "off"
  current_temperature?: number;
  current_humidity?: number;
  target_temp_high?: number;
  target_temp_low?: number;
  any_room_occupied?: boolean;
  occupied_rooms?: string[];
  avg_temperature?: number;
  avg_humidity?: number;
  room_count?: number;
  override_count_today?: number;
  ac_reset_count_today?: number;
  zone_persons?: string[];
  zone_cameras?: string[];
  camera_face_arrivals_today?: number;
  zone_presence_state?: string;
  vacancy_sweep_done?: boolean;
  vacancy_sweep_enabled?: boolean;
  runtime_exceeded?: boolean;
  runtime_duty_cycle_pct?: number;
  continuous_occupied_hours?: number;
}

interface HvacSystemDemandAttrs {
  active_zones?: string[];
  active_count?: number;
  total_zones?: number;
  load_bucket?: string;
}

/** Map preset_mode / zone_presence_state to a visual modifier class. */
function zoneCardCls(attrs: ZoneStatusAttrs | null): string {
  if (!attrs) return "";
  const action = attrs.hvac_action;
  const presence = attrs.zone_presence_state;
  if (action === "cooling" || action === "heating") return "status-green";
  if (presence === "occupied") return "status-green";
  if (attrs.runtime_exceeded) return "status-yellow";
  if (presence === "vacant" || presence === "away") return "";
  return "";
}

/** Friendly badge for the per-zone action label. */
function zoneActionBadge(attrs: ZoneStatusAttrs | null): { label: string; cls: string } {
  if (!attrs) return { label: "—", cls: "" };
  const action = attrs.hvac_action;
  if (action === "cooling") return { label: "cooling", cls: "accent" };
  if (action === "heating") return { label: "heating", cls: "accent" };
  if (action === "off") return { label: "off", cls: "" };
  if (action === "idle") return { label: "idle", cls: "" };
  return { label: action ?? "—", cls: "" };
}

/** Friendly badge for preset_mode (home/away/sleep/etc). */
function zonePresetBadge(attrs: ZoneStatusAttrs | null): { label: string; cls: string } {
  if (!attrs) return { label: "—", cls: "" };
  const p = attrs.preset_mode;
  if (p === "home") return { label: "home", cls: "green" };
  if (p === "away") return { label: "away", cls: "" };
  if (p === "sleep") return { label: "sleep", cls: "blue" };
  if (p === "eco") return { label: "eco", cls: "yellow" };
  return { label: p ?? "—", cls: "" };
}

/**
 * Per-zone card. Owns its hook calls. The zone "name" comes from the preset
 * sensor's `zone_name` attribute (e.g. "Entertainment + Master Suite") so we
 * don't hardcode against the static-mockup's "Main Living / Master / Kids".
 */
function ZoneCard({ index }: { index: number }) {
  const statusEntity = `sensor.ura_hvac_coordinator_zone_${index}_status`;
  const presetEntity = `sensor.ura_hvac_coordinator_hvac_zone_preset_zone_${index}`;

  const status = useUraSensorState(statusEntity);
  const preset = useUraSensorState(presetEntity);

  // Hide the card entirely if BOTH sensors are unavailable — keeps the grid
  // from rendering empty placeholders for zones that don't exist in this
  // install.
  if (status.unavailable && preset.unavailable && !status.loading && !preset.loading) {
    return null;
  }

  const attrs = (status.attributes ?? null) as ZoneStatusAttrs | null;
  const presetAttrs = (preset.attributes ?? null) as ZoneStatusAttrs | null;
  // Zone name lives on the preset sensor's attrs (verified live 2026-05-19).
  // Fall back to a generic "Zone N" placeholder when neither is materialised.
  const zoneName =
    (presetAttrs && typeof (presetAttrs as Record<string, unknown>)["zone_name"] === "string"
      ? ((presetAttrs as Record<string, unknown>)["zone_name"] as string)
      : null) ?? `Zone ${index}`;

  const cardCls = zoneCardCls(attrs);
  const presetBadge = zonePresetBadge(attrs ?? presetAttrs);
  const actionBadge = zoneActionBadge(attrs);

  const current = attrs?.current_temperature ?? presetAttrs?.current_temperature ?? null;
  // The thermostat exposes both target_temp_high and target_temp_low; in
  // cool mode we display the high (cooling setpoint); in heat mode the low.
  const targetCool = attrs?.target_temp_high ?? presetAttrs?.target_temp_high ?? null;
  const targetHeat = attrs?.target_temp_low ?? presetAttrs?.target_temp_low ?? null;
  const target =
    attrs?.hvac_action === "heating" ? targetHeat : targetCool ?? targetHeat;

  const occupiedRooms = attrs?.occupied_rooms ?? [];
  const occupiedLabel = occupiedRooms.length > 0 ? occupiedRooms.join(", ") : "—";
  const dutyCycle = attrs?.runtime_duty_cycle_pct ?? null;
  const dutyColor =
    dutyCycle == null
      ? undefined
      : dutyCycle > 80
        ? "var(--status-red)"
        : dutyCycle > 60
          ? "var(--status-yellow)"
          : "var(--status-green)";

  return (
    <div className={`card col-4 ${cardCls}`.trim()}>
      <div className="card-head">
        <div className="row" style={{ gap: "var(--space-xs)" }}>
          <span
            className={`dot ${
              attrs?.zone_presence_state === "occupied" ? "green live" : "grey"
            }`}
          ></span>
          <strong>{zoneName}</strong>
        </div>
        <span className={`badge ${presetBadge.cls}`.trim()}>{presetBadge.label}</span>
      </div>
      <div
        className="row"
        style={{
          gap: "var(--space-md)",
          padding: "var(--space-xs) 0",
          alignItems: "flex-start",
        }}
      >
        <div>
          <div className="card-value tabular">
            {current == null ? "—" : `${Math.round(current)}°`}
          </div>
          <div className="card-sub">current</div>
        </div>
        <div style={{ flex: 1, textAlign: "right" }}>
          <div className="card-value sm tabular">
            {target == null ? "—" : `${Math.round(target)}°`}
          </div>
          <div className="card-sub">target · {attrs?.hvac_action ?? "—"}</div>
        </div>
      </div>
      <div className="card-row">
        <span>Action</span>
        <span>
          <span className={`badge ${actionBadge.cls}`.trim()}>{actionBadge.label}</span>
        </span>
      </div>
      <div className="card-row">
        <span>Occupied rooms</span>
        <span className="dim">{occupiedLabel}</span>
      </div>
      {dutyCycle != null && (
        <div className="card-row">
          <span>Duty cycle</span>
          <span className="tabular" style={dutyColor ? { color: dutyColor } : undefined}>
            {dutyCycle}%
          </span>
        </div>
      )}
      <div className="card-row">
        <span>Override / day</span>
        <span className="tabular">
          {attrs?.override_count_today == null ? "—" : attrs.override_count_today}
        </span>
      </div>
      {/* Read-only setpoint controls — see file header DEFERRED. */}
      <div className="card-controls">
        <button className="btn sm icon" type="button">
          <svg className="icon-sm">
            <use href="#lc-minus" />
          </svg>
        </button>
        <span
          className="tabular"
          style={{
            fontSize: "var(--text-md)",
            fontWeight: 600,
            alignSelf: "center",
            padding: "0 4px",
          }}
        >
          {target == null ? "—" : `${Math.round(target)}°`}
        </span>
        <button className="btn sm icon" type="button">
          <svg className="icon-sm">
            <use href="#lc-plus" />
          </svg>
        </button>
        <div className="pill-group" style={{ marginLeft: "auto" }}>
          <button className={attrs?.hvac_action === "cooling" ? "active" : ""}>
            Cool
          </button>
          <button className={attrs?.hvac_action === "heating" ? "active" : ""}>
            Heat
          </button>
          <button>Auto</button>
        </div>
      </div>
    </div>
  );
}

/** House aggregate KPI strip. */
function HouseAggregate({
  demand,
  demandAttrs,
  preCoolPct,
  outsideDelta,
}: {
  demand: number | null;
  demandAttrs: HvacSystemDemandAttrs | null;
  preCoolPct: number | null;
  outsideDelta: number | null;
}) {
  // Demand-driven gauge color: heavy (>70) = orange; otherwise green.
  const demandColorCls =
    demand == null ? "" : demand > 70 ? "orange" : demand > 40 ? "yellow" : "";

  return (
    <div className="grid">
      <div className="card col-3">
        <div className="card-title">House climate delta</div>
        <div className="card-value tabular">
          {/* climate_delta is reported in degF; cast as °F absolute drift */}
          {outsideDelta == null ? "—" : `${outsideDelta.toFixed(1)}°`}
          <span className="card-unit">F</span>
        </div>
        <div className="card-sub">vs outside · — comfort score deferred</div>
      </div>
      <div className="card col-3">
        <div className="card-title">System demand</div>
        <div className="card-value tabular">
          {num(demand)}
          <span className="card-unit">%</span>
        </div>
        <div className="gauge-track">
          <div
            className={`gauge-fill ${demandColorCls}`.trim()}
            style={{ width: `${demand ?? 0}%` }}
          ></div>
        </div>
        <div className="card-sub">
          {demandAttrs?.active_count == null || demandAttrs?.total_zones == null
            ? "—"
            : `${demandAttrs.active_count}/${demandAttrs.total_zones} zones · ${demandAttrs.load_bucket ?? ""}`}
        </div>
      </div>
      <div className="card col-3">
        <div className="card-title">Active zones</div>
        <div className="card-value sm">
          {demandAttrs?.active_zones && demandAttrs.active_zones.length > 0
            ? demandAttrs.active_zones.join(" · ")
            : "—"}
        </div>
        <div className="card-sub">Bucket: {demandAttrs?.load_bucket ?? "—"}</div>
      </div>
      <div className="card col-3 status-blue">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-sparkles" />
          </svg>
          URA intent
        </div>
        <div className="row" style={{ gap: "var(--space-xs)", marginTop: "var(--space-xs)" }}>
          <span className="badge blue">pre-cool likelihood {num(preCoolPct, "%")}</span>
        </div>
        <div className="card-sub">
          Solar/forecast intent surfacing deferred — see HVAC.tsx
        </div>
      </div>
    </div>
  );
}

/** Hazard guard / advanced read-only card. Pulls arrester + comfort risk sensors. */
function HazardGuardCard() {
  const arrester = useUraSensorState(HVAC_ARRESTER_STATUS);
  const comfort = useUraSensorState(HVAC_COMFORT_RISK);
  const preArrival = useUraSensorState(HVAC_PRE_ARRIVAL_STATUS);
  // Arrester state → badge cls.
  const arrLabel = arrester.unavailable || !arrester.state ? "—" : arrester.state;
  const arrCls =
    arrester.state === "monitoring"
      ? "green"
      : arrester.state === "engaged"
        ? "yellow"
        : "";
  const comfortLabel = comfort.unavailable || !comfort.state ? "—" : comfort.state;
  const comfortCls =
    comfort.state === "low"
      ? "green"
      : comfort.state === "elevated"
        ? "yellow"
        : comfort.state === "high"
          ? "red"
          : "";

  return (
    <div className="card col-6">
      <div className="card-head">
        <div className="card-title">
          <svg className="icon-sm">
            <use href="#lc-alert" />
          </svg>
          Hazard guard &amp; advanced
        </div>
        <span className={`badge ${arrCls}`.trim()}>{arrLabel}</span>
      </div>
      <div className="card-row">
        <span>Arrester status</span>
        <span>
          <span className={`badge ${arrCls}`.trim()}>{arrLabel}</span>
        </span>
      </div>
      <div className="card-row">
        <span>Comfort risk</span>
        <span>
          <span className={`badge ${comfortCls}`.trim()}>{comfortLabel}</span>
        </span>
      </div>
      <div className="card-row">
        <span>Pre-arrival</span>
        <span className="dim">{preArrival.state ?? "—"}</span>
      </div>
      <div className="card-row">
        <span>Hot-zone temp limit</span>
        <span className="tabular dim">—°F</span>
      </div>
      <div className="card-row">
        <span>Cold-zone temp limit</span>
        <span className="tabular dim">—°F</span>
      </div>
      <div className="card-row">
        <span>Comfort weight (mode)</span>
        <span className="dim">— (entity TBD)</span>
      </div>
      <div className="card-row">
        <span>Min daily HVAC severity</span>
        <span>
          <span className="badge accent">ALERT (3)</span>
        </span>
      </div>
      <div className="card-sub" style={{ marginTop: "var(--space-xs)" }}>
        Hazard limits / comfort weights surfaced from coordinator config — Number
        entities for these knobs not yet exposed (DEFERRED).
      </div>
    </div>
  );
}

/** Read-only top controls bar — see file header DEFERRED. */
function ControlsBar({ direction }: { direction: string | null }) {
  const isCool = direction === "cooling";
  const isHeat = direction === "heating";
  return (
    <div className="controls-bar">
      <div className="knob span-3">
        <div className="knob-label">System mode</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className={isCool ? "active" : ""} style={{ flex: 1 }} type="button">
            Cool
          </button>
          <button className={isHeat ? "active" : ""} style={{ flex: 1 }} type="button">
            Heat
          </button>
          <button style={{ flex: 1 }} type="button">
            Auto
          </button>
          <button style={{ flex: 1 }} type="button">
            Off
          </button>
        </div>
        <div className="card-sub">Override per-zone in cards below</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">House setpoint</div>
        <div
          className="row"
          style={{ gap: "var(--space-xs)", alignItems: "center" }}
        >
          <button className="btn icon" type="button">
            <svg className="icon-sm">
              <use href="#lc-minus" />
            </svg>
          </button>
          <div
            className="knob-value tabular"
            style={{ flex: 1, textAlign: "center" }}
          >
            —°
          </div>
          <button className="btn icon" type="button">
            <svg className="icon-sm">
              <use href="#lc-plus" />
            </svg>
          </button>
        </div>
        <div className="card-sub">House setpoint aggregator deferred</div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">
          Pre-cool aggressiveness <span className="badge accent">URA</span>
        </div>
        <div className="knob-value">Balanced</div>
        <div className="knob-action">
          <input
            type="range"
            min={0}
            max={3}
            defaultValue={2}
            className="slider"
            readOnly
          />
        </div>
        <div className="card-sub">
          Passive · Conservative · <strong>Balanced</strong> · Aggressive
        </div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Coast threshold</div>
        <div className="knob-value tabular">
          45{" "}
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
            min={15}
            max={120}
            defaultValue={45}
            className="slider"
            readOnly
          />
        </div>
        <div className="card-sub">Predicted-vacancy lookahead</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">URA modes</div>
        <div className="card-row">
          <span style={{ fontSize: "var(--text-xs)" }}>Arrester</span>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
        </div>
        <div className="card-row">
          <span style={{ fontSize: "var(--text-xs)" }}>Observation</span>
          <label className="toggle">
            <input type="checkbox" readOnly />
            <span className="toggle-slot"></span>
          </label>
        </div>
        <div className="card-row">
          <span style={{ fontSize: "var(--text-xs)" }}>Pre-cool</span>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
        </div>
      </div>
    </div>
  );
}

export function HVAC() {
  const summary = useCoordinatorSummary();
  const hvacStatus = summary.attrs?.status_per_coordinator?.hvac;
  const headerBadge = statusToBadge(hvacStatus?.status);
  const headerCls = statusToCardClass(hvacStatus?.status);

  const demand = useUraSensorInt(HVAC_SYSTEM_DEMAND);
  const demandAttrs = useUraSensorState(HVAC_SYSTEM_DEMAND);
  const direction = useUraSensorState(HVAC_DIRECTION);
  const preCool = useUraSensorInt(HVAC_PRE_COOL_LIKELIHOOD);
  const outsideDelta = useUraSensorFloat(TEMP_DELTA_OUTSIDE);
  // Climate-delta is reported by aggregator (unused for KPI right now — kept
  // wired so future card can show it without re-touching this file).
  void useUraSensorFloat(CLIMATE_DELTA);

  const systemDemandAttrs =
    (demandAttrs.attributes ?? null) as HvacSystemDemandAttrs | null;
  const totalZones = systemDemandAttrs?.total_zones ?? null;
  const activeCount = systemDemandAttrs?.active_count ?? null;
  const dirState = direction.unavailable || !direction.state ? null : direction.state;

  return (
    <section className="tab active" data-tab="hvac">
      <header className="page-header">
        <div>
          <h1 className="page-title">HVAC</h1>
          <div className="page-subtitle">
            {totalZones == null ? "—" : `${totalZones} zones`} · {dirState ?? "—"} mode
            {demand.value != null && ` · system demand ${demand.value}%`}
          </div>
        </div>
        <div className="page-actions">
          <span className={`badge ${headerBadge.cls} lg`.trim()}>
            HC · {headerBadge.label}
          </span>
        </div>
      </header>

      <ControlsBar direction={dirState} />

      <HouseAggregate
        demand={demand.value}
        demandAttrs={systemDemandAttrs}
        preCoolPct={preCool.value}
        outsideDelta={outsideDelta.value}
      />

      <div className="section-head">
        <h2>Zones {activeCount != null ? `· ${activeCount} active` : ""}</h2>
      </div>
      <div className={`grid ${headerCls}`.trim()}>
        {Array.from({ length: MAX_ZONES }, (_, i) => i + 1).map((idx) => (
          <ZoneCard key={idx} index={idx} />
        ))}
        <HazardGuardCard />
      </div>
    </section>
  );
}
