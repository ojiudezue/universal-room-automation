/**
 * Presence tab — React port of presence.html (P6 light styled).
 *
 * The Presence Coordinator's surface area is per-person tracking + house-state
 * + census. URA exposes:
 *   - `sensor.universal_room_automation_{person}_location` — current room name
 *   - `sensor.universal_room_automation_{person}_likely_next_room` — prediction
 *   - `sensor.universal_room_automation_{person}_previous_seen` — ISO timestamp
 *   - `sensor.universal_room_automation_{person}_current_path` — recent rooms
 *   - `sensor.universal_room_automation_persons_in_house` — int
 *   - `sensor.universal_room_automation_identified_persons_in_house` — int
 *   - `sensor.universal_room_automation_unidentified_persons_in_house` — int
 *   - `sensor.universal_room_automation_total_persons_on_property` — int
 *   - `sensor.universal_room_automation_person_tracking_status` — "1/4 home"
 *   - `sensor.universal_room_automation_persons_entered_today` — int
 *   - `sensor.universal_room_automation_persons_exited_today` — int
 *   - `sensor.universal_room_automation_zones_with_motion` — int + zone list
 *   - `sensor.ura_presence_coordinator_presence_house_state` — house state
 *   - `sensor.ura_presence_coordinator_house_state_confidence` — float 0-1
 *
 * People in the install (per binary_sensor.universal_room_automation_*_phone_left_behind
 * and *_location sensors): Oji, Ezinne, Jaya, Ziri.
 *
 * DEFERRED:
 *   - BLE / camera / motion source breakdown (Bermuda RSSI, per-camera last
 *     detection): would require listing N device-tracker entities outside
 *     URA's namespace. Renders static placeholder section.
 *   - "Music following per-room" toggles: URA exposes
 *     `sensor.universal_room_automation_music_following_health` (state="idle")
 *     but not per-room enablement. Read-only static fragment.
 *   - "Override location" buttons: service-call wiring deferred.
 */
import { useUraSensorInt, useUraSensorState, useUraSensorFloat } from "../../data/useUraSensor";
import { num, statusToBadge, formatClockTime } from "../../data/statusColors";
import { useCoordinatorSummary } from "../../data/useCoordinatorSummary";

const PERSONS_IN_HOUSE = "sensor.universal_room_automation_persons_in_house";
const IDENTIFIED_PERSONS = "sensor.universal_room_automation_identified_persons_in_house";
const UNIDENTIFIED_PERSONS = "sensor.universal_room_automation_unidentified_persons_in_house";
const TOTAL_ON_PROPERTY = "sensor.universal_room_automation_total_persons_on_property";
const PERSONS_ON_EXTERIOR = "sensor.universal_room_automation_persons_on_property_exterior";
const PERSON_TRACKING_STATUS = "sensor.universal_room_automation_person_tracking_status";
const PERSONS_ENTERED_TODAY = "sensor.universal_room_automation_persons_entered_today";
const PERSONS_EXITED_TODAY = "sensor.universal_room_automation_persons_exited_today";
const ZONES_WITH_MOTION = "sensor.universal_room_automation_zones_with_motion";
const PRESENCE_HOUSE_STATE = "sensor.ura_presence_coordinator_presence_house_state";
const HOUSE_STATE_CONFIDENCE = "sensor.ura_presence_coordinator_house_state_confidence";
const PRESENCE_COMPLIANCE = "sensor.ura_presence_coordinator_presence_compliance";
const PRESENCE_ANOMALY = "sensor.ura_presence_coordinator_presence_anomaly";
const MUSIC_FOLLOWING_HEALTH = "sensor.universal_room_automation_music_following_health";
const GUEST_MODE = "binary_sensor.ura_presence_coordinator_guest_mode";
const HOUSE_OCCUPIED = "binary_sensor.ura_presence_coordinator_house_occupied";

// People in install. Discovered via the entity registry's *_location pattern.
// The phone_left_behind and _location sensors confirm: Oji, Ezinne, Jaya, Ziri.
// If a future install onboards a person, add them here — URA doesn't surface
// the canonical person list on a coordinator attribute today (DEFERRED).
const PEOPLE: Array<{ slug: string; display: string; initial: string; color: string }> = [
  { slug: "oji_udezue", display: "Oji", initial: "O", color: "linear-gradient(135deg,#42A5F5,#1E88E5)" },
  { slug: "ezinne", display: "Ezinne", initial: "E", color: "linear-gradient(135deg,#EC407A,#C2185B)" },
  { slug: "jaya", display: "Jaya", initial: "J", color: "linear-gradient(135deg,#66BB6A,#388E3C)" },
  { slug: "ziri", display: "Ziri", initial: "Z", color: "linear-gradient(135deg,#FFA726,#F57C00)" },
];

interface ZonesWithMotionAttrs {
  zones?: string[];
  window_minutes?: number;
}

/** Person card. Reads location + next-room + prev-seen sensors. */
function PersonCard(person: typeof PEOPLE[number]) {
  const location = useUraSensorState(
    `sensor.universal_room_automation_${person.slug}_location`,
  );
  const nextRoom = useUraSensorState(
    `sensor.universal_room_automation_${person.slug}_likely_next_room`,
  );
  const prevSeen = useUraSensorState(
    `sensor.universal_room_automation_${person.slug}_previous_seen`,
  );
  const path = useUraSensorState(
    `sensor.universal_room_automation_${person.slug}_current_path`,
  );

  const locState = location.unavailable || !location.state ? null : location.state;
  const isHome = locState != null && locState !== "Away" && locState !== "unknown";
  const cardCls = isHome ? "status-green" : "status-yellow";
  const valueColor = isHome ? "var(--status-green)" : "var(--status-yellow)";
  const dotCls = isHome ? "green live" : "yellow";

  return (
    <div className={`card col-3 ${cardCls}`.trim()}>
      <div className="row" style={{ gap: "var(--space-sm)" }}>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: "var(--radius-full)",
            background: person.color,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 600,
            fontSize: "var(--text-lg)",
            color: "white",
          }}
        >
          {person.initial}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontWeight: 600,
              color: "var(--text-secondary)",
              fontSize: "var(--text-sm)",
            }}
          >
            {person.display}
          </div>
          <div
            style={{
              fontWeight: 700,
              fontSize: "var(--text-lg)",
              color: valueColor,
              lineHeight: 1.1,
              marginTop: 2,
            }}
          >
            {locState ?? "—"}{" "}
            <span
              className="dim"
              style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
            >
              · {formatClockTime(prevSeen.state)}
            </span>
          </div>
        </div>
        <span className={`dot ${dotCls}`}></span>
      </div>
      <div className="card-row">
        <span>Likely next</span>
        <span>
          <span className="badge accent">
            {nextRoom.state ?? "—"}
          </span>
        </span>
      </div>
      <div className="card-row">
        <span>Last seen</span>
        <span className="dim">{formatClockTime(prevSeen.state)}</span>
      </div>
      {path.state && path.state !== "away" && (
        <div className="card-row">
          <span>Path</span>
          <span className="dim" style={{ maxWidth: "60%", textAlign: "right" }}>
            {path.state}
          </span>
        </div>
      )}
      <div className="card-controls">
        <button className="btn sm" type="button">
          Override location{" "}
          <svg className="icon-sm">
            <use href="#lc-chevron-down" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/** Read-only top controls bar. */
function ControlsBar({
  guestModeOn,
  musicHealth,
}: {
  guestModeOn: boolean;
  musicHealth: string | null;
}) {
  return (
    <div className="controls-bar">
      <div className="knob span-3">
        <div className="knob-label">
          Music following{" "}
          <span className="badge green">{musicHealth ?? "—"}</span>
        </div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" defaultChecked readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            master enable (deferred)
          </span>
        </div>
        <div className="knob-action">
          <button className="btn sm" type="button">
            Per-room{" "}
            <svg className="icon-sm">
              <use href="#lc-chevron-down" />
            </svg>
          </button>
        </div>
      </div>
      <div className="knob span-3">
        <div className="knob-label">BLE confidence floor</div>
        <div className="knob-value tabular">
          75{" "}
          <span
            className="dim"
            style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
          >
            % · -60 dBm
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={40}
            max={95}
            defaultValue={75}
            className="slider"
            readOnly
          />
        </div>
        <div className="card-sub">Below this, ignore BLE alone</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Transition smoothing</div>
        <div className="knob-value tabular">
          8{" "}
          <span
            className="dim"
            style={{ fontWeight: 400, fontSize: "var(--text-sm)" }}
          >
            sec
          </span>
        </div>
        <div className="knob-action">
          <input
            type="range"
            min={0}
            max={30}
            defaultValue={8}
            className="slider"
            readOnly
          />
        </div>
        <div className="card-sub">Debounce for room change</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Census mode</div>
        <div className="pill-group" style={{ width: "100%" }}>
          <button style={{ flex: 1 }} type="button">
            Strict
          </button>
          <button className="active" style={{ flex: 1 }} type="button">
            Lenient
          </button>
        </div>
        <div className="card-sub">Lenient keeps known-present 5m</div>
      </div>
      <div className="knob span-2">
        <div className="knob-label">Guest mode</div>
        <div className="row" style={{ gap: "var(--space-sm)" }}>
          <label className="toggle">
            <input type="checkbox" checked={guestModeOn} readOnly />
            <span className="toggle-slot"></span>
          </label>
          <span className="dim" style={{ fontSize: "var(--text-sm)" }}>
            {guestModeOn ? "active" : "off"}
          </span>
        </div>
        <div className="card-sub">Unknown faces → guest count</div>
      </div>
    </div>
  );
}

export function Presence() {
  const summary = useCoordinatorSummary();
  const presStatus = summary.attrs?.status_per_coordinator?.presence;
  const badge = statusToBadge(presStatus?.status);

  const personsInHouse = useUraSensorInt(PERSONS_IN_HOUSE);
  const identified = useUraSensorInt(IDENTIFIED_PERSONS);
  const unidentified = useUraSensorInt(UNIDENTIFIED_PERSONS);
  const totalProperty = useUraSensorInt(TOTAL_ON_PROPERTY);
  const exterior = useUraSensorInt(PERSONS_ON_EXTERIOR);
  const trackingStatus = useUraSensorState(PERSON_TRACKING_STATUS);
  const enteredToday = useUraSensorInt(PERSONS_ENTERED_TODAY);
  const exitedToday = useUraSensorInt(PERSONS_EXITED_TODAY);
  const zonesMotion = useUraSensorInt(ZONES_WITH_MOTION);
  const zonesMotionAttrs = useUraSensorState(ZONES_WITH_MOTION);
  const presenceHouseState = useUraSensorState(PRESENCE_HOUSE_STATE);
  const houseConfidence = useUraSensorFloat(HOUSE_STATE_CONFIDENCE);
  const compliance = useUraSensorFloat(PRESENCE_COMPLIANCE);
  const anomaly = useUraSensorState(PRESENCE_ANOMALY);
  const musicHealth = useUraSensorState(MUSIC_FOLLOWING_HEALTH);
  const guestMode = useUraSensorState(GUEST_MODE);
  const houseOccupied = useUraSensorState(HOUSE_OCCUPIED);

  const zonesList = (zonesMotionAttrs.attributes as ZonesWithMotionAttrs | null)?.zones ?? [];
  const guestModeOn = guestMode.state === "on";
  const musicHealthState =
    musicHealth.unavailable || !musicHealth.state ? null : musicHealth.state;

  return (
    <section className="tab active" data-tab="presence">
      <header className="page-header">
        <div>
          <h1 className="page-title">Presence</h1>
          <div className="page-subtitle">
            Fusion: BLE + cameras + motion + radar · {trackingStatus.state ?? "—"}
            {houseOccupied.state === "on" && " · house occupied"}
          </div>
        </div>
        <div className="page-actions">
          <span className={`badge ${badge.cls} lg`.trim()}>
            PC · {badge.label}
          </span>
        </div>
      </header>

      <ControlsBar guestModeOn={guestModeOn} musicHealth={musicHealthState} />

      <div className="grid">
        {PEOPLE.map((p) => (
          <PersonCard key={p.slug} {...p} />
        ))}
      </div>

      <div className="section-head">
        <h2>House aggregates</h2>
      </div>
      <div className="grid">
        <div className="card col-3">
          <div className="card-title">In house</div>
          <div className="card-value tabular">{num(personsInHouse.value)}</div>
          <div className="card-sub">
            {identified.value ?? "—"} identified ·{" "}
            {unidentified.value ?? "—"} unknown
          </div>
        </div>
        <div className="card col-3">
          <div className="card-title">On property</div>
          <div className="card-value tabular">{num(totalProperty.value)}</div>
          <div className="card-sub">
            {exterior.value ?? "—"} exterior · {personsInHouse.value ?? "—"} interior
          </div>
        </div>
        <div className="card col-3">
          <div className="card-title">Today flows</div>
          <div className="card-value tabular">
            +{num(enteredToday.value)} / −{num(exitedToday.value)}
          </div>
          <div className="card-sub">entered / exited</div>
        </div>
        <div className="card col-3 status-blue">
          <div className="card-title">
            <svg className="icon-sm">
              <use href="#lc-sparkles" />
            </svg>
            House state
          </div>
          <div className="card-row">
            <span>Current</span>
            <span>
              <strong>{presenceHouseState.state ?? "—"}</strong>
            </span>
          </div>
          <div className="card-row">
            <span>Confidence</span>
            <span className="tabular">
              {houseConfidence.value == null
                ? "—"
                : `${Math.round(houseConfidence.value * 100)}%`}
            </span>
          </div>
          <div className="card-row">
            <span>Anomaly</span>
            <span className="dim">{anomaly.state ?? "—"}</span>
          </div>
        </div>
      </div>

      <div className="section-head">
        <h2>Activity</h2>
      </div>
      <div className="grid">
        <div className="card col-4">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-eye" />
              </svg>
              Zones with motion
            </div>
            <span className="badge accent">{zonesMotion.value ?? "—"}</span>
          </div>
          {zonesList.length === 0 ? (
            <div className="card-sub">No motion in any zone</div>
          ) : (
            zonesList.map((z) => (
              <div className="card-row" key={z}>
                <span>{z}</span>
                <span>
                  <span className="badge green">active</span>
                </span>
              </div>
            ))
          )}
        </div>
        <div className="card col-4">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-activity" />
              </svg>
              Presence coordinator
            </div>
            <span className={`badge ${badge.cls}`.trim()}>{badge.label}</span>
          </div>
          <div className="card-row">
            <span>Compliance</span>
            <span className="tabular">
              {compliance.value == null ? "—" : `${compliance.value.toFixed(0)}%`}
            </span>
          </div>
          <div className="card-row">
            <span>Active anomalies</span>
            <span className="tabular">
              {num(presStatus?.active_anomalies ?? null)}
            </span>
          </div>
          <div className="card-row">
            <span>Enabled</span>
            <span>
              <span className={`badge ${presStatus?.enabled ? "green" : ""}`.trim()}>
                {presStatus?.enabled ? "yes" : "no"}
              </span>
            </span>
          </div>
        </div>
        <div className="card col-4">
          <div className="card-head">
            <div className="card-title">
              <svg className="icon-sm">
                <use href="#lc-music" />
              </svg>
              Music following
            </div>
            <span className="badge">{musicHealthState ?? "—"}</span>
          </div>
          <div className="card-sub">
            Per-room enablement matrix — entity surface deferred
          </div>
        </div>
      </div>
    </section>
  );
}
