/**
 * Zones tab — React port of zones.html (P6 light styled).
 *
 * The Zones tab is the house-level HVAC-zone breakdown. Each zone card maps
 * 1:1 with a `sensor.ura_hvac_coordinator_zone_{N}_status` entity (rich
 * attributes per ZoneStatusAttrs in HVAC.tsx). Whereas HVAC.tsx renders the
 * thermal-control face of a zone, Zones.tsx renders the spatial / occupancy
 * roll-up face — rooms, occupants, lights — and a "View rooms" callback into
 * the Rooms tab.
 *
 * Patterns inherited from HVAC.tsx / Diagnostics.tsx — same one-hook-per-card
 * shape, same "—" placeholder contract, controls read-only.
 *
 * DEFERRED:
 *   - Lights-on-per-zone: no zone-level lights aggregator exists. We render
 *     "—". A per-zone lights count would need a new sensor (out of scope).
 *   - Sort by / filter pills: read-only.
 *   - Outdoor zone (last card in mockup): no HVAC zone sensor backs "outdoor"
 *     today — it would be a weather aggregator card. Rendered with TODO.
 *   - data-tab-target="rooms" cross-tab navigation: routing seam is in
 *     TabShell.tsx; Zones doesn't manipulate the active tab itself yet.
 */
import { useUraSensorState, useUraSensorInt } from "../../data/useUraSensor";
import { statusToCardClass, statusToBadge, num } from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

const MAX_ZONES = 5;

const HVAC_SYSTEM_DEMAND = "sensor.universal_room_automation_hvac_system_demand";
// Verified live 2026-05-19: state="3", attrs.rooms list, attrs.per_zone_breakdown.
const ROOMS_OCCUPIED_SENSOR =
  "sensor.universal_room_automation_rooms_occupied";

interface ZoneStatusAttrs {
  zone_id?: string;
  climate_entity?: string;
  preset_mode?: string;
  hvac_action?: string;
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
  zone_presence_state?: string;
  runtime_exceeded?: boolean;
  runtime_duty_cycle_pct?: number;
  continuous_occupied_hours?: number;
}

interface ZonePresetAttrs {
  zone_name?: string;
  hvac_action?: string;
  preset_mode?: string;
  target_temp_high?: number;
  target_temp_low?: number;
  current_temperature?: number;
}

interface RoomsOccupiedAttrs {
  rooms?: string[];
  per_zone_breakdown?: Record<string, number>;
}

interface HvacSystemDemandAttrs {
  active_zones?: string[];
  active_count?: number;
  total_zones?: number;
  load_bucket?: string;
}

/** Compact friendly preset → badge tuple. */
function presetBadge(preset: string | undefined): { label: string; cls: string } {
  switch (preset) {
    case "home":
      return { label: "normal · cooling", cls: "green" };
    case "away":
      return { label: "setback", cls: "" };
    case "sleep":
      return { label: "sleep", cls: "blue" };
    case "eco":
      return { label: "eco · coast", cls: "yellow" };
    default:
      return { label: preset ?? "—", cls: "" };
  }
}

/** Zone card — occupancy + climate + room list. */
function ZoneCard({ index }: { index: number }) {
  const status = useUraSensorState(`sensor.ura_hvac_coordinator_zone_${index}_status`);
  const preset = useUraSensorState(
    `sensor.ura_hvac_coordinator_hvac_zone_preset_zone_${index}`,
  );

  if (
    status.unavailable &&
    preset.unavailable &&
    !status.loading &&
    !preset.loading
  ) {
    return null;
  }

  const attrs = (status.attributes ?? null) as ZoneStatusAttrs | null;
  const presetAttrs = (preset.attributes ?? null) as ZonePresetAttrs | null;
  const zoneName = presetAttrs?.zone_name ?? `Zone ${index}`;

  const occupiedRooms = attrs?.occupied_rooms ?? [];
  const roomCount = attrs?.room_count ?? null;
  const occupiedCount = occupiedRooms.length;

  const current = attrs?.current_temperature ?? presetAttrs?.current_temperature ?? null;
  const targetCool = attrs?.target_temp_high ?? presetAttrs?.target_temp_high ?? null;
  const targetHeat = attrs?.target_temp_low ?? presetAttrs?.target_temp_low ?? null;
  const target =
    attrs?.hvac_action === "heating" ? targetHeat : targetCool ?? targetHeat;
  const avgTemp = attrs?.avg_temperature ?? null;

  const pBadge = presetBadge(attrs?.preset_mode ?? presetAttrs?.preset_mode);
  const cardCls =
    attrs?.hvac_action === "cooling" || attrs?.hvac_action === "heating"
      ? "status-green"
      : attrs?.runtime_exceeded
        ? "status-yellow"
        : "";

  return (
    <div className={`card col-6 ${cardCls}`.trim()}>
      <div className="card-head">
        <div
          className="row"
          style={{ gap: "var(--space-xs)", fontSize: "var(--text-lg)" }}
        >
          <span
            className={`dot ${
              attrs?.zone_presence_state === "occupied" ? "green live" : "grey"
            }`}
          ></span>
          <strong>{zoneName}</strong>
        </div>
        <span className={`badge ${pBadge.cls}`.trim()}>{pBadge.label}</span>
      </div>
      <div className="row" style={{ gap: "var(--space-md)", padding: "var(--space-xs) 0" }}>
        <div>
          <div className="card-value sm tabular">
            {roomCount == null ? "—" : `${occupiedCount} / ${roomCount}`}
          </div>
          <div className="card-sub">occupied</div>
        </div>
        <div>
          <div className="card-value sm tabular">
            {(avgTemp ?? current) == null
              ? "—"
              : `${Math.round((avgTemp ?? current) as number)}°`}
          </div>
          <div className="card-sub">
            avg · set {target == null ? "—" : `${Math.round(target)}°`}
          </div>
        </div>
        <div>
          <div className="card-value sm tabular">—</div>
          <div className="card-sub">lights on (deferred)</div>
        </div>
        <div style={{ flex: 1 }}></div>
      </div>
      <div className="card-row">
        <span>Rooms</span>
        <span className="dim">
          {occupiedRooms.length > 0 ? occupiedRooms.join(" · ") : "—"}
        </span>
      </div>
      {attrs?.zone_persons && attrs.zone_persons.length > 0 && (
        <div className="card-row">
          <span>Persons</span>
          <span className="dim">{attrs.zone_persons.join(", ")}</span>
        </div>
      )}
      <div className="card-row">
        <span>Duty cycle</span>
        <span className="tabular">
          {attrs?.runtime_duty_cycle_pct == null
            ? "—"
            : `${attrs.runtime_duty_cycle_pct}%`}
        </span>
      </div>
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
        <button className="btn sm" type="button">
          All lights off
        </button>
        <button className="btn sm" type="button">
          Open rooms{" "}
          <svg className="icon-sm">
            <use href="#lc-chevron-right" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/** Read-only controls bar. */
function ControlsBar() {
  return (
    <div className="controls-bar">
      <div className="knob span-4">
        <div className="knob-label">Sort by</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className="active" style={{ flex: 1 }} type="button">
            Occupancy
          </button>
          <button style={{ flex: 1 }} type="button">
            Lights on
          </button>
          <button style={{ flex: 1 }} type="button">
            Demand
          </button>
          <button style={{ flex: 1 }} type="button">
            Name
          </button>
        </div>
      </div>
      <div className="knob span-4">
        <div className="knob-label">Show zones</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className="active" style={{ flex: 1 }} type="button">
            All
          </button>
          <button style={{ flex: 1 }} type="button">
            Indoor
          </button>
          <button style={{ flex: 1 }} type="button">
            Active
          </button>
        </div>
      </div>
      <div className="knob span-4">
        <div className="knob-label">Whole-house</div>
        <div
          className="knob-action"
          style={{ marginTop: 0, flexWrap: "wrap" }}
        >
          <button className="btn" type="button">
            All lights off
          </button>
          <button className="btn" type="button">
            Setback all
          </button>
        </div>
      </div>
    </div>
  );
}

/** Outdoor placeholder card — see DEFERRED. */
function OutdoorCard() {
  return (
    <div className="card col-12">
      <div className="card-head">
        <div
          className="row"
          style={{ gap: "var(--space-xs)", fontSize: "var(--text-lg)" }}
        >
          <span className="dot grey"></span>
          <strong>Outdoor</strong>
        </div>
        <span className="badge">— (deferred)</span>
      </div>
      <div className="card-sub">
        Weather + outdoor-lights aggregator not yet implemented · TODO(entity-id)
      </div>
    </div>
  );
}

export function Zones() {
  const summary = useCoordinatorSummary();
  const hvacStatus = summary.attrs?.status_per_coordinator?.hvac;
  const badge = statusToBadge(hvacStatus?.status);
  const cardCls = statusToCardClass(hvacStatus?.status);

  const demandAttrs = useUraSensorState(HVAC_SYSTEM_DEMAND);
  const systemDemandAttrs =
    (demandAttrs.attributes ?? null) as HvacSystemDemandAttrs | null;
  const totalZones = systemDemandAttrs?.total_zones ?? null;

  const roomsOccCount = useUraSensorInt(ROOMS_OCCUPIED_SENSOR);
  const roomsOccAttrs = useUraSensorState(ROOMS_OCCUPIED_SENSOR);
  const occAttrs =
    (roomsOccAttrs.attributes ?? null) as RoomsOccupiedAttrs | null;

  return (
    <section className="tab active" data-tab="zones">
      <header className="page-header">
        <div>
          <h1 className="page-title">Zones</h1>
          <div className="page-subtitle">
            {num(totalZones)} zones · tap a zone to filter Rooms tab
            {roomsOccCount.value != null && (
              <> · {roomsOccCount.value} rooms occupied</>
            )}
          </div>
        </div>
        <div className="page-actions">
          <span className={`badge ${badge.cls}`.trim()}>HC · {badge.label}</span>
          <button className="btn sm" type="button">
            All rooms{" "}
            <svg className="icon-sm">
              <use href="#lc-chevron-right" />
            </svg>
          </button>
        </div>
      </header>

      <ControlsBar />

      <div className={`grid ${cardCls}`.trim()}>
        {Array.from({ length: MAX_ZONES }, (_, i) => i + 1).map((idx) => (
          <ZoneCard key={idx} index={idx} />
        ))}
        <OutdoorCard />
      </div>

      {occAttrs?.per_zone_breakdown && (
        <>
          <div className="section-head">
            <h2>Live per-zone occupancy</h2>
          </div>
          <div className="grid">
            {Object.entries(occAttrs.per_zone_breakdown).map(([zone, n]) => (
              <div className="card col-4" key={zone}>
                <div className="card-row">
                  <strong>{zone}</strong>
                  <span className="tabular">{n} occupied</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
