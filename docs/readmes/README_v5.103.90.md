# v5.103.90: Bluetooth leads home/away (GPS assistive) + EV toggle alarm no longer pages

| Cycle | Card | Tier | Deploy risk |
|---|---|---|---|
| Presence: GPS assistive, BLE leads | PERSON-BLE-WINS-OVER-STALE-GPS-1 (plan `docs/planning/PLANNING_presence_gps_assistive.md` rev 3) | 2, elevated to 3 framing-disjoint reviews + 2 plan-review rounds + consequence replay | MEDIUM (changes when an app user is marked away, and so when the house goes AWAY) |
| EV toggle tripwire diagnostic-only | EV-TOGGLE-TRIPWIRE-PEAK-BOUNDARY-1 | 1 | LOW (alarm-only) |

## 1. Presence: GPS is assistive, Bluetooth leads

### Problem
URA took HA's `person.<x>` = `home` at face value (`person_coordinator.py`, both `person.state == "home"` arms). HA's person entity prefers the companion-app GPS tracker, so a frozen GPS fix held an app user home for hours while both of their own BLE trackers read `not_home`. 10-17..10-24: 13 such segments for Oji (~19 h); on 10-24 the phone re-sent its 14:03 fix all day. Six trust readers also read `person.state` directly and saw the same frozen "home". Operator: "Ble should win always and app/gps should support if available"; users may disable location or deny iOS permission.

### Change (narrow; no new statuses, reasons or confidences)
- **Overrule gate** inside both `person.state == "home"` arms: the person goes down the existing away arm (`away_ble_silent_only`, 0.82) when ALL hold:
  - switch **BLE Leads Home/Away** (`switch.ura_presence_ble_leads_home_away`, default on) is on;
  - the BLE fleet is armed: Bermuda's active proxy count (registry unique_id `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT`) has read ≥ `BLE_LEADS_MIN_ACTIVE_PROXIES` (30) unbroken for `BLE_LEADS_ARM_S` (360 s); any dip or `unavailable` restarts it; empty at boot (restart guard); sensor missing → rule off;
  - no router tracker for the person reads `home`, and WiFi is not `not_home` (row 4 unchanged);
  - the person has ≥1 `bluetooth_le` tracker and every one reads `not_home`.
- GPS still hastens away (~30 s when the app reports) and still backs up home when BLE has no reading (unavailable/unknown/no BLE tracker). Missing GPS has no effect.
- **Trust readers** now use `person_state_for_trust` (URA view): aggregation zone person-home vetoes (sleep + non-sleep), `hvac.py` night-trust hold + main-row home persons, `hvac_fans.py` night hold, `hvac_zones.zone_has_home_person` (no production caller today). Edge-triggered readers and the camera-census face vetoes/latch stay on raw `person.state` (replay: the latch swap worsened false GUEST).
- **Pre-arrival:** an overrule arms pre-arrival only after 15 min away (same rule as the LOST path); the first overrule tick restarts the clock and clears a stale flag.
- Switch off = today's behaviour for every decision.

### Measured (plan D0, replay, plan review)
- Normal leave → house AWAY median 30 s (GPS). BLE-only departure now caught ~5–9 min after leaving (Bermuda 300 s timeout).
- Restart: app users' first BLE `home` within 360 s in 14/14 cases.
- 0 overnight episodes of a home resident BLE-silent ≥5 min.

### Accepted behaviour (operator 10-24, option A)
A resident home **without their phone** is marked away (same as the BLE-only kids today): possible false GUEST, or house AWAY if everyone else is out and they stay out of camera view ≥30 min. Garage guard rejected (last-heard area is the garage on every car departure). Kill switch: `switch.ura_presence_ble_leads_home_away`.

### Known limits
- L1: after a coordinator-manager reload the switch reads ON until its deferred restore lands (same window as the other presence kill switches).
- First 360 s after a restart/proxy dip: frozen GPS can still hold a person home (as before).

### Reviews
Plan review FIX-REQUIRED ×2 → fixed (fleet-down guard, direct readers, boot latch). Build reviews: A SHIP; B FIX (operator decision → A; B-M1 fixed); C 56/62 RED → 6 tests added, fix-up 17/17 RED. Orchestrator mutation of the gate → 26 RED. Records: `docs/reviews/code-review/plan_review_presence_gps_assistive.md`, `review_{A,B,C}_presence_gps_assistive.md`, `docs/planning/AUDIT_presence_gps_assistive_consequence_replay.md`.

## 2. EV toggle tripwire no longer pages
Operator 10-24: "I don't want to be paged at all about EV... the paging is diagnostic." `note_ev_toggle` still counts and writes the `ev_toggle_tripwire` anomaly row; the NM page is gated by `EV_TOGGLE_TRIPWIRE_NOTIFY_ENABLED = False` (energy_const.py, rung 1).

## Tests
Full name-diff vs develop: CLEAN (default 18,444 passed; URA_SOURCE_MUTATION=1 18,649 passed; D7 hygiene pass). New: `test_person_gps_assistive.py`, `test_person_gps_assistive_hvac.py`, tripwire tests in `test_ec_ev_toggle_tripwire.py`.

## Not done
- Daytime camera-face cross-check in the live re-run: waits on Frigate retraining (FRIGATE-FACE-MISLABEL-OJI-1).
- Companion-app location not sending for Oji: operator-side, not URA.

## Live acceptance criteria (prospective)
- `switch.ura_presence_ble_leads_home_away` exists, on, restored after restart.
- No ERROR from person_coordinator/presence after restart.
- After ≥360 s with proxies ≥30: Oji (away, GPS frozen home, BLE not_home) → `sensor.universal_room_automation_oji_udezue_location` = Away, `tracking_reason` `away_ble_silent_only`.
- Ezinne/Jaya at home stay Home; house state not AWAY while they are home.
- No `ev_toggle_tripwire` notification rows; anomaly rows may appear.
- 24 h one-shot: `scripts/probes/presence_gps_override_probe.py` re-run; zero overnight app-user away stamps while own BLE reads home; list any app-user away stamp 360–900 s after a restart.
