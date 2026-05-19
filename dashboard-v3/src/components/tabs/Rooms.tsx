/**
 * Rooms tab — React port of rooms.html (P6 light styled). Largest tab —
 * one card per onboarded room.
 *
 * ROOM DISCOVERY (per CLAUDE.md "don't hardcode 19 room names" rule):
 *   The authoritative room registry is the `room_energies` attribute on
 *   `sensor.universal_room_automation_rooms_energy_total`. It exposes a dict
 *   keyed by room display-name → kWh-today. Live install reports 14 rooms.
 *   The static mockup grouped rooms by "zone" (Main / Master / Kids / Guest
 *   / Outdoor) — that grouping isn't directly available on URA's
 *   `rooms_energy_total` payload, but `sensor.universal_room_automation_rooms_occupied`
 *   does expose `per_zone_breakdown` (Master Suite, Entertainment, Upstairs).
 *   We render rooms in a single grid for v1; zone-grouping is DEFERRED until
 *   a `room_zone_map` attribute surfaces on the registry sensor.
 *
 * Patterns inherited from HVAC.tsx / Diagnostics.tsx — same one-hook-per-card
 * shape, same "—" placeholder contract, controls read-only.
 *
 * DEFERRED:
 *   - Zone grouping headers ("Main Living · 5 rooms"): need a room→zone map
 *     URA doesn't yet emit. Single grid for now.
 *   - Light count per room: no `sensor.{room}_lights_on_count` aggregator.
 *   - Per-room temperature: rooms expose energy but not temperature on a
 *     URA-aggregator entity. We surface the room's `binary_sensor.{slug}_occupied`
 *     state and energy attribution only.
 *   - Setpoint stepper / lights toggle / overflow menu: read-only.
 *   - Filter pills (Zone filter / Show only / Sort): read-only.
 */
import { useUraSensorState, useUraSensorInt } from "../../data/useUraSensor";

const ROOMS_REGISTRY_SENSOR =
  "sensor.universal_room_automation_rooms_energy_total";
const ROOMS_OCCUPIED_SENSOR =
  "sensor.universal_room_automation_rooms_occupied";

interface RoomEnergiesAttrs {
  room_energies?: Record<string, number>;
  room_count?: number;
}

interface RoomsOccupiedAttrs {
  rooms?: string[];
  per_zone_breakdown?: Record<string, number>;
}

/**
 * Convert a room display-name to the HA entity_id slug. URA's convention is
 * lower-snake-case (e.g. "Living Room" → "living_room"). This is the same
 * slug logic used by HA's `slugify`. We don't import the upstream helper;
 * a small regex is enough for ASCII room names URA emits.
 */
function roomSlug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/**
 * Per-room card. Reads `binary_sensor.{slug}_occupied` for the live occupancy
 * indicator. Energy attribution comes from the registry attrs prop (avoid
 * re-hooking per-room when the parent already has the dict).
 *
 * NOTE on hook-call counts: this component issues exactly one hook call per
 * mounted card. With 14 rooms that's 14 subscriptions — well within hakit's
 * per-tab budget. If a future install grows to 50+ rooms we should evaluate
 * batching, but for now per-card is consistent with the rest of the dash.
 */
function RoomCard({
  name,
  energyKwhToday,
  isOccupied,
}: {
  name: string;
  energyKwhToday: number | null;
  isOccupied: boolean;
}) {
  const slug = roomSlug(name);
  const occSensor = useUraSensorState(`binary_sensor.${slug}_occupied`);
  // Prefer the live binary_sensor when available; fall back to the
  // rooms_occupied.attrs.rooms list (passed via isOccupied) when the
  // per-room sensor isn't present (some rooms in the registry may not have
  // an occupancy detector, e.g. Stair Closet).
  const liveOccupied =
    occSensor.unavailable || occSensor.state == null
      ? isOccupied
      : occSensor.state === "on";

  const cardCls = liveOccupied ? "status-green" : "";
  const dotCls = liveOccupied ? "green live" : "grey";

  return (
    <div className={`room-card col-3 ${cardCls}`.trim()}>
      <div className="room-card-head">
        <span className={`dot ${dotCls}`}></span>
        <span className="room-card-title">{name}</span>
        {liveOccupied && <span className="badge green">live</span>}
      </div>
      <div className="room-card-meta">
        <span>
          <svg className="icon-sm">
            <use href="#lc-bulb" />
          </svg>
          —/—
        </span>
        <span className="dim">
          {energyKwhToday == null ? "—" : `${energyKwhToday.toFixed(2)} kWh`}
        </span>
      </div>
      <div className="room-card-controls">
        <button className="btn sm icon" type="button">
          <svg className="icon-sm">
            <use href="#lc-bulb" />
          </svg>
        </button>
        <button className="btn sm icon" type="button">
          <svg className="icon-sm">
            <use href="#lc-minus" />
          </svg>
        </button>
        <span
          className="dim tabular"
          style={{
            fontSize: "var(--text-sm)",
            alignSelf: "center",
            padding: "0 4px",
          }}
        >
          —°
        </span>
        <button className="btn sm icon" type="button">
          <svg className="icon-sm">
            <use href="#lc-plus" />
          </svg>
        </button>
        <button className="btn sm icon" type="button">
          <svg className="icon-sm">
            <use href="#lc-more" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/** Read-only top controls bar. */
function ControlsBar() {
  return (
    <div className="controls-bar">
      <div className="knob span-3">
        <div className="knob-label">Zone filter</div>
        <div
          className="pill-group"
          style={{ width: "100%", flexWrap: "wrap" }}
        >
          <button className="active" style={{ flex: 1 }} type="button">
            All
          </button>
          <button style={{ flex: 1 }} type="button">
            Main
          </button>
          <button style={{ flex: 1 }} type="button">
            Master
          </button>
          <button style={{ flex: 1 }} type="button">
            Kids
          </button>
          <button style={{ flex: 1 }} type="button">
            Guest
          </button>
          <button style={{ flex: 1 }} type="button">
            Outdoor
          </button>
        </div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">Show only</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className="active" style={{ flex: 1 }} type="button">
            All
          </button>
          <button style={{ flex: 1 }} type="button">
            Occupied
          </button>
          <button style={{ flex: 1 }} type="button">
            Lights on
          </button>
          <button style={{ flex: 1 }} type="button">
            Climate
          </button>
        </div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">Sort by</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button className="active" style={{ flex: 1 }} type="button">
            Zone
          </button>
          <button style={{ flex: 1 }} type="button">
            Occupancy
          </button>
          <button style={{ flex: 1 }} type="button">
            Temp
          </button>
          <button style={{ flex: 1 }} type="button">
            Name
          </button>
        </div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">Bulk actions</div>
        <div
          className="knob-action"
          style={{ marginTop: 0, flexWrap: "wrap" }}
        >
          <button className="btn sm" type="button">
            Lights off · filtered
          </button>
          <button className="btn sm" type="button">
            Setback · filtered
          </button>
        </div>
      </div>
    </div>
  );
}

export function Rooms() {
  const registry = useUraSensorState(ROOMS_REGISTRY_SENSOR);
  const occupied = useUraSensorState(ROOMS_OCCUPIED_SENSOR);
  const occupiedCount = useUraSensorInt(ROOMS_OCCUPIED_SENSOR);

  const regAttrs = (registry.attributes ?? null) as RoomEnergiesAttrs | null;
  const occAttrs = (occupied.attributes ?? null) as RoomsOccupiedAttrs | null;

  const rooms = regAttrs?.room_energies
    ? Object.entries(regAttrs.room_energies)
    : [];
  const occupiedSet = new Set(occAttrs?.rooms ?? []);

  // Sort: occupied rooms first, then alphabetical
  const sorted = [...rooms].sort((a, b) => {
    const aOcc = occupiedSet.has(a[0]) ? 1 : 0;
    const bOcc = occupiedSet.has(b[0]) ? 1 : 0;
    if (aOcc !== bOcc) return bOcc - aOcc;
    return a[0].localeCompare(b[0]);
  });

  return (
    <section className="tab active" data-tab="rooms">
      <header className="page-header">
        <div>
          <h1 className="page-title">Rooms</h1>
          <div className="page-subtitle">
            {regAttrs?.room_count ?? rooms.length} rooms · auto-onboarded
            {occupiedCount.value != null && (
              <> · {occupiedCount.value} currently occupied</>
            )}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn" type="button">
            <svg className="icon">
              <use href="#lc-plus" />
            </svg>{" "}
            Onboard room
          </button>
        </div>
      </header>

      <ControlsBar />

      {rooms.length === 0 ? (
        <div className="card col-12">
          <div className="card-sub">
            {registry.loading
              ? "Loading room registry…"
              : "No rooms reported by rooms_energy_total — awaiting first aggregation cycle."}
          </div>
        </div>
      ) : (
        <>
          <div className="section-head">
            <h2>
              All rooms <span className="dim">· sorted occupied → name</span>
            </h2>
          </div>
          <div className="grid">
            {sorted.map(([name, kwh]) => (
              <RoomCard
                key={name}
                name={name}
                energyKwhToday={typeof kwh === "number" ? kwh : null}
                isOccupied={occupiedSet.has(name)}
              />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
