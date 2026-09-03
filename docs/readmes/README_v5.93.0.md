# v5.93.0 — Per-room BLE-hold cap (bounds phone-only "phantom" occupancy)

**Card:** `BLE-BLEED-EXTEND-SLEEP-1`
**Tier:** 2-DB+ (2 plan-reviews + 3 framing-disjoint build-reviews + 2 focused re-reviews + 2 fix-ups + orchestrator verify). MINOR — new per-room operator capability + a new autonomous behavior.
**Merge:** `feature/ble-hold-cap` → develop.

## Problem

A phone left in a room could keep that room `occupied` for hours via BLE alone, with **no body signal** — measured: the Master Bathroom held occupied for a continuous **7.3 h** (22:53→06:14) from a phone in the adjacent bedroom, `occupancy_source=ble`, zero motion/mmWave. This skews humidity-fan runtime, HVAC presence, and occupancy analytics. The existing max-active failsafe never caught it because leg (ii) of the P24 invariant *deliberately* exempts BLE-sourced occupancy.

## Solution — an opt-in, per-room BLE-hold cap

A per-room toggle bounds how long BLE **alone** can sustain occupancy after the last real body signal. When the cap is exceeded, the BLE extend is refused (the room goes vacant; self-heals on any real motion).

- **`CONF_BLE_HOLD_CAP_ENABLED`** — per-room toggle, config-flow + options-flow, room-type-aware **schema default** (mirrors the `CONF_WET_ROOM` pattern — bathrooms/closets default ON, everything else OFF). Applied at the **read site** (`_get_config(..., ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(room_type, False))`) so all ~40 existing rooms activate immediately with no migration.
- **`BLE_HOLD_CAP_DURATIONS`** — module const, room_type→seconds. Operator-set **120 min** for bathroom + closet + default.
- **Anchor = BLE-hold-start, not session start.** The cap measures `now - _ble_only_hold_since` — time the hold has been BLE-*only* since the last real corroboration — not whole-session duration. So a genuinely-present occupant who moved recently is never evicted; only a truly body-less BLE hold is capped. The anchor resets on **every** real-presence path: Tier-1 (motion/mmWave/occupancy), the camera override, and all vacancy-finalize sites.
- Distinct NM (`kind="ble_hold_cap"`) with an honest diagnosis (per-day latch, no collision with the P24 failsafe).

**No-eviction by construction:** bathrooms/closets are the only default-ON types, and the six no-PIR rooms (Master/Jaya bedroom, studies, living/game rooms) are all bedroom/common/study types → default OFF. Sleepers are never capped.

## Reviews

2 plan-reviews (Rev 3 blanket→FIX, Rev 4 config-application→FIX, Rev 5 SHIP). 3 framing-disjoint build-reviews (A/B SHIP, C FIX-REQUIRED — hollow anchors). Fix pass → focused re-review found a real **HIGH** (camera override + vacancy-finalize didn't reset the BLE-only anchor → a camera-visible person could be false-evicted when the camera flickered off with BLE still present) → fix-up 2 reset the anchor at all 6 `_became_occupied_time` sites + camera, with 3 new reset-mutation anchors (all RED-on-neuter). Orchestrator grep-verified 7 anchor clears cover all reset paths. 21 cycle tests; per-site mutation drills RED for the anchor read, the NM wire-in, the dict lookup, and the 3 reset sites.

### Acceptance criteria
- **Verify:** a bathroom/closet reads cap-ON by default (no options edit); bedrooms/common areas cap-OFF.
- **Verify:** a BLE-only hold exceeding 120 min in a cap-ON room is refused (room→vacant); a room with any Tier-1 firing this tick is never evaluated by the cap; a recently-moving occupant is never evicted.
- **Live:** the Master Bathroom no longer shows multi-hour `occupancy_source=ble` holds with no body signal; a real bath/soak (motion within the window) is unaffected.

### Known caveats (by design)
- **B1 — cap clock resets on restart.** `_ble_only_hold_since` is not persisted (fail-open on None preserves the BLE-WARM-CREATE-1 restart pin), so a phantom hold spanning HA reloads shorter than the cap will not be capped. Acceptable — reloads are rare and the phantom re-caps on the next continuous window.
- **B5 — humidity-runtime edge is bounded + non-actuating** (a cap refusal can nudge the presence-runtime window; it only holds an already-on fan, never starts one).

## Pre-deploy gate
py_compile clean; no conflict markers; 21 cycle tests pass; full-suite name-diff vs develop = (recorded below).

## Validated 2026-09-03 (post-restart)

| Criterion | Observed evidence | Result |
|---|---|---|
| Clean boot, coordinators healthy | Post-11:31 restart: `sensor.ura_presence_coordinator_presence_house_state` = `away` (fresh 11:33:53); `binary_sensor.master_bathroom_occupied` = `off` (fresh 11:33:50). URA loaded. | **PASS** |
| No new URA errors post-restart | `error_log` ERROR scan: every URA error predates the 11:31 restart — the 47 "Error adding entity None" (last 10:18, the pre-v5.92.3 window), the setup-cancelled (08:45), and the boot job-listener-removal errors (08:43) are all from earlier windows in the rolling buffer. **Zero** new URA ERRORs after the v5.93.0 restart. | **PASS** |
| via_device fix still holds | No new "Error adding entity None" post-restart — v5.93.0 did not reintroduce `via_device`. | **PASS** |
| Cap ships default-ON for bath/closet | Config-level (read-site default via `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT`); code merged + verified (7 anchor-reset sites, 0 via_device). Behavior is event-driven. | **Code PASS; live = organic** |

**Organic discriminator (per `--revisit`):** a recorder watch — confirm NO continuous `occupancy_source=ble` hold exceeding 120 min in a cap-ON room (Master Bathroom in particular: the 7.3h body-less shape must not recur), and a real bath/soak with motion in-window is unaffected. Dispose by querying `binary_sensor.master_bathroom_occupied` + `sensor.master_bathroom_occupancy_source` history over the next few days.

**Boot transient noted + dismissed:** "Unable to remove unknown job listener" for several coordinators' `_on_ha_started` callbacks (08:43 window, pre-v5.93.0) — a boot-lifecycle cleanup pattern (onetime listener already auto-removed after firing), not v5.93.0-introduced; relates to the parked `UNLOAD-SYMMETRY-TASK-HYGIENE-1`.
