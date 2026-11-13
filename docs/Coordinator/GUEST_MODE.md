# Guest mode — operator manual

**Applies to:** v5.108.0 (GUEST-MODE-SPLIT-VISITORS-1, branch `feature/guest-mode-split` @ `ec5e5f8f`, NOT deployed).
**Canonical code:** `domain_coordinators/presence.py` (`_compose_guest_gate`, `_refresh_guest_stay`,
`_update_visitors_present`, `async_guest_left`), `const.py` knob block (`GUEST_NIGHT_STAY_RULE_ENABLED` onward).
**Siblings:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §2 step 3 and §7 (mechanics, corrections #29-#32),
`IDENTITY_FUSION_CAMERAS_MANUAL.md` §6 (identity side), plan `docs/planning/PLANNING_guest_mode_split_2026_11.md`,
README `docs/readmes/README_v5.108.0.md`. Code at the cited lines wins over this page; fix this page in the same
commit when they disagree.

---

## 1. What GUEST means now

There are two separate ideas.

| Signal | Meaning | Bar | Drives anything? |
|---|---|---|---|
| **House state GUEST** | A guest is **staying** (has slept here). | High: a guest-room night plus that room's day before. | Yes, see §6. |
| **`binary_sensor.ura_presence_coordinator_visitors_present`** | Someone the house does not know is here **right now**, or a stay is on. | Low. | No. Display only (§7). |

Before v5.108.0 one signal did both jobs: GUEST came on whenever a non-resident sat 30 minutes in a guest room. In the
October stay that fired 35 times on 16 of 21 days and covered only 2 of 21 nights. Measured on the live DB
(`house_state_log`, 2026-09-20 → 11-09): 36 GUEST episodes, 18.7 h in total, never more than 4.3 h a day. Under the new
rule the October replay is GUEST by day on 18 of 21 stay days, which is roughly 10x the daytime GUEST hours and close to
zero GUEST hours at night. That shift is the whole blast radius; every consumer in §6 is judged against it.

What the house does during a stay:

- **Arrival day:** HOME_* (no night yet). `visitors_present` shows the guest.
- **Day 2 onward, after waking:** HOME_DAY → GUEST.
- **At the sleep-window start (22:00 here):** GUEST → HOME_NIGHT (after the 300 s GUEST exit hold), then SLEEP.
- **Morning:** SLEEP → WAKING → HOME_DAY → GUEST.
- **End:** after min(2, n) empty nights in a row (n = qualifying nights so far), or the **Guest left** button.

Everyone leaving still sends the house to AWAY: the AWAY branches run before the GUEST branch in `infer()`, and
`VALID_TRANSITIONS[GUEST]` includes AWAY (`house_state.py:116-121`).

## 2. Entry and exit rules

A once-a-morning walk over the URA database (`_refresh_guest_stay`) recomputes the stay latch from scratch, so a
restart gives the same answer.

**Night fraction.** For each of the last `GUEST_STAY_REPLAY_NIGHTS` completed nights and each designated guest room
(`room_is_guest_room` on the room entry; live: Guest Bedroom 1, Guest Bedroom 2), the walk takes the share of the
**house** sleep window (CM options `sleep_start_hour` / `sleep_end_hour`, live 22 → 6, not the per-room sleep hours)
during which the room was occupied (`occupancy_events`), minus time a resident was located there by Bluetooth
(`person_visits`, ± `GUEST_KNOWN_STICKY_S`). A night **qualifies** at ≥ `GUEST_NIGHT_MIN_FRACTION`.

**Entry.** The latch turns on at an **entry-qualified** night: the night qualifies AND the same room was occupied for
≥ `GUEST_STAY_DAY_MIN_FRACTION` of its day window (local `GUEST_STAY_DAY_START_HOUR`:00 → the night start, at least
1 h), with at least `GUEST_STAY_ENTRY_NIGHTS` qualifying nights in the last `GUEST_STAY_LOOKBACK_NIGHTS`.

**Exit.** Off after min(`GUEST_STAY_EXIT_MAX_NIGHTS`, n) straight non-qualifying nights. A one-night visit ends after
one empty night; any longer stay after two.

**Knobs.** All rung 1 (module constants in `const.py`, read as `const.X` at call time; changing one is a reviewed code
change because each decides house-state entry). Values on `ec5e5f8f`:

| Knob | Value | Meaning / kill semantics |
|---|---|---|
| `GUEST_NIGHT_STAY_RULE_ENABLED` | True | **Kill switch.** False = the old 30-min guest-room gate enters GUEST again (byte-identical, golden-tested); no DB walk. |
| `GUEST_NIGHT_MIN_FRACTION` | 0.25 | Night share needed. Fitted to the replay plateau 0.20-0.30. |
| `GUEST_STAY_DAY_MIN_FRACTION` | 0.10 | Day share needed, same room. 0 = day test off. Above ~0.21 the October stay is never entered. |
| `GUEST_STAY_DAY_START_HOUR` | 10 | Day window start (local). |
| `GUEST_STAY_DAY_BEFORE_NIGHT` | True | False = the day after the night also counts. |
| `GUEST_STAY_ENTRY_NIGHTS` | 1 | Second-night guard. 2 = no single-night entries (costs 2 stay days in the replay). Clamped 1..lookback. |
| `GUEST_STAY_LOOKBACK_NIGHTS` | 3 | Entry count window. |
| `GUEST_STAY_EXIT_SCALES_WITH_STAY` | True | False = fixed exit after `LOOKBACK` empty nights (rev 5). |
| `GUEST_STAY_EXIT_MAX_NIGHTS` | 2 | Most empty nights before a stay ends (operator ruling 2026-11-09). |
| `GUEST_STAY_REENTRY_GRACE_DAYS` | 7 | §3. 0 = off. |
| `GUEST_STAY_REPLAY_NIGHTS` | 35 | Nights walked (clamped ≥ trip-wire days + lookback). |
| `GUEST_STAY_ERROR_RETRY_S` | 900 | DB error → retry after 15 min; the last good answer is kept meanwhile (off if none since boot). |
| `GUEST_STAY_LONG_NM_DAYS` | 28 | Trip-wire: one HIGH stuck-signal NM (`kind=guest_stay_long`) if a stay lasts longer. 0 = off. |
| `VISITORS_CAM_LEG_ENABLED` | True | False = `visitors_present` never turns on from cameras. |

Rung 3 (live switch): **Guest Detection** (`switch.ura_presence_coordinator_guest_detection`). OFF = no GUEST entry from
presence, the stay is treated as off, `visitors_present` follows GUEST only. The manual house-state override select
(`select.py`) can still pin GUEST.

## 3. Re-entry grace

For `GUEST_STAY_REENTRY_GRACE_DAYS` (7) days after a stay ends **by empty nights**, ONE qualifying night in any guest room
re-enters GUEST, with no day test and bypassing `GUEST_STAY_ENTRY_NIGHTS`. It covers a guest who is away a couple of
nights and comes back (October: away 10-13/10-14, back 10-15 → GUEST 10-16). A stay entered by grace keeps the original
stay's end as its anchor and opens no new grace, so the window never runs past 7 days from the last normally-entered
stay. A **Guest left** button exit opens no grace.

## 4. The "Guest left" button

`button.ura_presence_coordinator_guest_left` (Presence Coordinator device). Pressing it:

1. clears the stay latch and records the press time in RAM and in the HA Store `universal_room_automation.guest_left`
   (survives restarts; a failed read is retried on the next walk, a failed save is retried once);
2. runs one inference (trigger `guest_left_button`) that skips the 300 s GUEST exit hold once, so the house goes
   GUEST → HOME_* now (unless the house entered GUEST less than 300 s ago; the next tick then exits);
3. from then on, only nights that **start after the press** can enter a stay; earlier nights count toward neither entry
   nor exit length, so the same stay cannot re-latch the next morning.

Use it when a guest leaves early; otherwise the stay ends by itself after one or two empty nights.

## 5. Night yield

With the stay rule on, GUEST holds only outside the house sleep hours (`_compose_guest_gate`: stay latch AND NOT
`_is_sleep_hour`). At `sleep_start_hour` inference proposes GUEST → HOME_NIGHT; the S9 guest-exit hold keeps GUEST for
300 s, then HOME_NIGHT, then SLEEP after the HOME_NIGHT dwell (120 s). There is still no GUEST → SLEEP edge in the state
machine (Presence §10 #29 stays true). Consequences: every night-keyed behaviour (NM quiet hours, sleep lighting, music
night suppression, HVAC night tails, fan night trust, wall-panel force-off) now runs on stay nights, where the old
overnight GUEST skipped all of them.

## 6. Lock regime interaction (garage remote lockouts)

Toggle `security_lockout_engage_on_guest_sleep` (CM options, default True). On a stay night:

- 22:00: the guest-night clock sees GUEST and **locks** (`REASON_GUEST_NIGHT`).
- ~22:05: GUEST → HOME_NIGHT inside the sleep window while the reason is `guest_night` does **not** release; the regime
  records `guest_yield_hold` (`security_lock_regime.on_house_state_changed`, INV-LOCK-1).
- SLEEP: reason becomes `sleep`; the engage is a no-op on locks already locked.
- WAKING / HOME_DAY / HOME_EVENING / a resident arrival / the backstop release as usual. ARRIVING does NOT release
  (LOCK-RELEASE-ON-ARRIVING, branch `feature/lock-release-arriving`, NOT deployed): it is body evidence with no identity.
  Once the episode has seen ARRIVING (the taint), the GUEST -> HOME_* guest exit and every other HOME_* edge are held
  too (`arriving_hold`) until WAKING, a resident's own arrival edge, the backstop, an operator override or the switch.
- A manual override GUEST → HOME_NIGHT inside the window is held too (the regime cannot tell it from the yield).

Pinned by `test_sc_garage_lockout.py::test_lock_once_at_guest_clock_no_unlock_on_yield` and
`::test_lock_held_if_home_night_until_morning`.

## 7. Who reads GUEST — full consumer table

Independent repo-wide grep (2026-11-09, review E) plus the live `automations.yaml` and dashboards. "Before" = the 30-min
guest-room gate (short daytime episodes, sometimes held overnight). "Now" = all day for the length of a stay, never at
night.

| # | Consumer | file:line | Trust? | Before | Now |
|---|---|---|---|---|---|
| 1 | HVAC preset map guest → `home` | `hvac_const.py:1293` | trust | `home` while GUEST, incl. overnight | `home` by day (same as HOME_DAY); nights get `sleep` via SLEEP |
| 2 | HVAC evidence clock / back-fill / D5 transit filter / fast-exit timers only in `home_day`/`home_evening` | `hvac_const.py:1097`; `hvac_zones.py:932-949`, `:1482-1485`; `hvac.py:5871`, `:6107-6110` | trust | short GUEST spells ran the legacy (pre-v5.103.20) path | every zone runs the legacy path all day for the whole stay: slower exits (no exit timer, waits for the 5-min tick), no away-edge transit filter. More comfort, a little more energy. See review E M1 |
| 3 | HVAC night tail (`sleep`/`waking`) and fan night trust (`home_night`/`sleep`/`waking`) | `hvac_const.py:1082`, `:1067` | trust | skipped on overnight-GUEST nights | applies on stay nights (improvement) |
| 4 | Arrester hold-preserving states | `hvac_const.py:229` | trust | a GUEST edge kept immune holds | same, now two GUEST edges a day |
| 5 | Dynamic preset per-zone offset reset under GUEST | `dynamic_preset.py:860-863` | trust | rare | zones with `zone_dynamic_preset_reset_offset_guest` lose their offset by day for the whole stay (live: Back Hallway offset 1.0 → 0; Upstairs offset 0, no effect) |
| 6 | Security auto-follow guest → ARMED_HOME | `security.py:183`, `:1251` | trust (arming) | — | inert live (`security_auto_follow` False). If enabled: a HIGH "armed_home" NM every stay morning after WAKING disarms |
| 7 | SC lock regime (GUEST in sleep window) | `security_lock_regime.py:764-791`, `:803-823`, `:1424` | trust (lock) | overnight GUEST locked via guest clock | lock once at 22:00, held across the yield (§6) |
| 8 | NM exterior-person contextual severity in GUEST | `const.py` `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` guest branch; consumer `perimeter_alert.py` `_severity_for_current_house_state` | trust (severity) | MEDIUM during short spells and overnight GUEST (night de-escalated from CRITICAL) | daytime of a stay: MEDIUM, EXCEPT two cases kept at HIGH (review E-M2, operator approved 2026-11-09): a perimeter "circling" track, and a person at an egress (door) camera with no resident home. Knob `NM_HAZARD_EXTERIOR_PERSON_GUEST_KEEP_HIGH` (rung 1, True; False = all MEDIUM). Everything else stays MEDIUM, which reaches no channel under the live NM config (companion is HIGH+). Nights now CRITICAL (improvement) |
| 9 | NM quiet hours (`sleep`/`home_night`) | `notification_manager.py:4643` | trust (delivery) | overnight GUEST = no quiet hours | stay nights are quiet (improvement) |
| 10 | Bayesian learning suppressed in GUEST | `__init__.py:3274-3279`, `bayesian_predictor.py:547` | trust (learning) | paused during short spells | paused by day for the stay; resumes each night (guest nights are learned) |
| 11 | Optimizer prediction-accuracy finding skipped while learning is suppressed | `optimization.py:4142-4150` | display (advisory) | rare | no accuracy finding by day during a stay |
| 12 | Room occupancy anomaly suppressed in GUEST | `binary_sensor.py:3446`, `:3616-3633` | display | suppressed during visits | suppressed by day during a stay; daytime visits and stay nights are no longer suppressed |
| 13 | Zone-aggregator non-sleep veto states (Layer 3 / Pattern C) include `guest` | `aggregation.py:4871-4874`; `presence.py:2227-2229` | trust (zone status) | — | unchanged semantics; nights go to Layer 2 (SLEEP) |
| 14 | Room tier house-SLEEP lighting / night lights | `automation.py:1265`, `:1280` | trust (lighting) | skipped on overnight-GUEST nights | applies on stay nights |
| 15 | Music following sleep / night suppression | `music_following.py:678-700` | trust (media) | bypassed on overnight-GUEST nights | applies on stay nights |
| 16 | Optimizer security-posture finding (`away`/`home_night`/`sleep`) | `optimization.py:3944` | display | skipped overnight GUEST | runs on stay nights |
| 17 | Memory family guest → home | `memory_facade.py:279` | display | — | unchanged |
| 18 | Routine forecaster GUEST passthrough | `routine_forecaster.py:101-105` | display | — | learns two GUEST edges a day during stays |
| 19 | Room automation chain trigger `house_state_guest` | `coordinator.py:1013`; `const.py:4197-4200` | trust (user rules) | — | fires every stay morning; no live chain uses it (checked `core.config_entries`) |
| 20 | `binary_sensor.ura_presence_coordinator_guest_mode` | `binary_sensor.py:2418-2452` | display | on during spells | on by day during a stay |
| 21 | House-state sensor `guest_reason`, `guest_stay_*` | `sensor.py:5836`; `presence.py:7171-7182` | display | `guest_room:<room>` = GUEST | `night_stay:<rooms>` during a stay; `guest_room:<room>` = a visitor in a guest room |
| 22 | Transition confidence 0.9/0.95 when GUEST entry coincides with the room gate | `presence.py:7788-7789` | display | the GUEST entry path | only when a stay entry happens while the 30-min gate is also armed; otherwise 0.8 |
| 23 | Live HA automation: wall-panel brightness `guest: 80` | `/config/automations.yaml` (not in repo) | cosmetic | panels at 80 % and never force-off on overnight GUEST | by day only; stay nights force panels off at SLEEP |
| 24 | Dashboard v3 Presence tab "Guest mode — Unknown faces → guest count" | `dashboard-v3/src/components/tabs/Presence.tsx:264-274` | display | label already stale (since GUEST-CENSUS D2) | stale; should read "Guest staying" |
| 25 | `preset_overrides` predicate `house_state == 'guest'` | `preset_overrides.py:147-148` | none | dead: no producer of `guest_mode` overrides (`build_guest_mode_overrides` deleted, `:241-247`) | dead (the plan's §3.3 row calling this "HVAC Custom Preset Ranges" is wrong; `switch.ura_hvac_coordinator_guest_mode_actuation` is Custom Preset Ranges and does not read house state GUEST) |

Option lists, not readers: `HOUSE_STATE_OVERRIDE_OPTIONS` (`const.py:3740`), the `set_house_state` service schema
(`__init__.py:6250`), `HOUSE_STATE_TRIGGER_VALUES` (`const.py:4197`). Census guest counts (`unidentified_count`,
`ZoneGuestCountSensor`) do not read house state.

## 8. `visitors_present`

`binary_sensor.ura_presence_coordinator_visitors_present` (unique id `universal_room_automation_visitors_present`),
evaluated each presence tick by `_update_visitors_present`. On = house GUEST OR any leg:

| Leg | Source | Evaluated in | Measured noise with no visitors |
|---|---|---|---|
| `room` | 30-min guest-room gate (`_guest_room_gate_armed`) | HOME_* and GUEST | 1 qualifying run in 22 post-stay days |
| `cam` | Path A: unidentified people on camera ≥ 5 min (`_guest_gate_armed`) | HOME_* only | 2.41 fires/day post-stay (median 6 min, longest 219 min); 3 in 7 days 11-02..11-08 |
| `stay` | the stay latch (masked by Guest Detection) | any state | — |

Attributes: `legs` (unrecorded), `since` (last off → on edge, UTC).

**What it drives: nothing.** No URA code reads it (grep on `ec5e5f8f`: only the entity reads `_visitors_*`); no live
automation or dashboard references it yet.

**What it could drive later** (none is built; each needs its own card and the measure-first gate):

| Candidate | Value | Risk | Fit today? |
|---|---|---|---|
| Perimeter / door alert de-escalation | low; GUEST already covers stays | a false `cam` flash softens a real alert; violates the identity doctrine direction (de-escalate only at ≥ 0.9 confidence) | No |
| "Unknown person inside" security posture | potentially high | the same `cam` flashes would raise false intruder posture ~0.4-2.4 times a day; residents without BLE look unknown | No; needs a corroborated leg |
| Lighting / hospitality scene | modest | a false flash turns on a scene in an empty room | Only on the `room` or `stay` legs |
| Music | low | — | No |
| HVAC comfort | low; zone occupancy already drives HVAC | — | No |
| Census guest count | none; it is downstream of the census | circular | No |
| Notification suppression (e.g. doorbell chime, "person detected") | modest | suppressing on a false flash hides a real event | No |

The camera leg is not fit to drive anything that acts: its post-stay false-flash rate (0.4-2.4 a day) is the same order as
real visits. The `room` and `stay` legs are clean enough for cosmetic or comfort uses.

**Old 30-min gate consumers.** Before v5.108.0 the 30-min gate fed GUEST, so every GUEST consumer in §7 reacted to a
30-minute daytime visit. Now a visit only lights `visitors_present`. Nothing is stranded in the sense of a broken reader:
no consumer reads the gate directly (`guest_reason` and `visitors_present` are display). What changed for a daytime visit
with no stay: Bayesian learning is no longer paused, the occupancy-anomaly sensor is no longer suppressed, the exterior-person
severity follows HOME_DAY (LOW with a resident home, HIGH with none) instead of MEDIUM, and the HVAC evidence clock keeps
running. All are acceptable; the alert change is in the stricter direction.

## 9. Known limits

- **One fitted stay.** Every threshold was fitted on one real stay (October 09-28 → 10-16) plus pre-stay noise. Treat the
  values as provisional; the README live-validation row L5 is the discriminator for the next real stay.
- **Guest Bedroom 2 has no BLE scanner.** Residents in GB2 are never subtracted, so a resident who spends a day and one
  night there enters GUEST. Mitigation knob: `GUEST_STAY_ENTRY_NIGHTS` 2. A scanner can only remove resident time.
- **Guests have no IRK.** Nothing identifies a guest; BLE only subtracts residents. Identity is sensor-only.
- **Cameras did not help.** D0 measured the two-leg (room AND camera) design's recall on the October stay at 1 of 16
  days, and the camera leg fires 0.4-2.4 times a day with nobody visiting. Cameras and faces never enter GUEST; the
  camera leg feeds only `visitors_present`. WiFi is read nowhere (operator decision).
- **No GUEST on the arrival day** (parked). `visitors_present` covers it.
- **Phantom guest-room holds count.** GB1 / GB2 have no fan-immune witness; a fan- or stuck-radar hold reads as a guest
  night. The 28-day trip-wire is the backstop (max night fraction 0.02 over 10-18..11-08, so not occurring now).
- **During a stay** the house-wide HVAC legacy path (§7 row 2) and the daytime alert de-escalation (§7 row 8) apply to
  the whole house, not only the guest's zone.

## 10. Open items

| Item | Status |
|---|---|
| **GUEST uses the pre-v5.103.20 occupancy path** (review E-M1; §7 row 2). In GUEST every HVAC zone runs without the evidence clock, release back-fill, fast-exit timer or D5 away-edge transit filter (`hvac_const.py:1097` `HVAC_EVIDENCE_RULE_STATES` lists only `home_day` / `home_evening`). Comfort-safe (holds, not drops); energy cost only. | OPEN, not changed in v5.108.0 (operator: do not change HVAC in this cycle). Candidate fix: add `guest` to `HVAC_EVIDENCE_RULE_STATES` under an HVAC Tier 2 review. |
