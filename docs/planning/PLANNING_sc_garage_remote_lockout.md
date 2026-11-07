# PLANNING — Security Coordinator: lock regime + garage remote lockout (+ gated operator auto-open trial)

**Card:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (operator picked option B, 2026-11-07; decisions recorded in the card field `operator_2026_11_07_decisions`).
**Rev:** 2 (2026-11-07). Rev 1 = commit ea4bc6a8. Rev 2 folds the operator decisions: arming and locks are separate concerns; Vacation (not Away) engages; rev1 recommendations accepted; NEW gated deliverable: operator-only fast-approach auto-open.
**Tier:** Phase 1 (lock regime + lockout) = Tier 2, operator-elevated to the Tier 2-DB three-review protocol. Phase 2 (auto-open) = **Tier 3**, shipped as its own release. See §11.
**Status:** plan, not reviewed. No code written.

Operator intent (unchanged): the opener "remote lockout" stops the outside keypad and car remotes being guessed or bypassed. "3 AM entries from red eyes. Don't want family to be locked out." New (2026-11-07): "Separate arming from locks: arming = security system + alarms; locks = a reasonable locking regime that does not need the alarm armed." And: on a fast (vehicular) approach by the operator, release the lockout and open the garage, as an operator-only trial behind its own toggle.

Mandatory reads done for rev 2: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete, all 835 lines, including the §10 corrections ledger) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (complete). No ledger claim is re-asserted. Relevant ledger items honoured: #13 (Bermuda `home` with `area: null` is stale, not a room fix), #23 (location in no-room branches comes from `person.<x>.state`), #27 (dead BLE fleet reads `not_home`, not unavailable). HVAC is not touched.

---

## 1. Institutional context verified

### 1.1 Live facts (read 2026-11-07 for rev 1; not re-read for rev 2, no HA access in this pass)

| Fact | Value |
|---|---|
| Lockout entities | `lock.konnected_f0f5bd523b00_lock` (Garage A, Konnected blaQ); `lock.ratgdov25i_dbfe2a_lock_remotes` (Garage B, ratgdo 2.5i). `locked` = lockout ON. |
| Doors | `cover.konnected_f0f5bd523b00_garage_door` (A), `cover.ratgdov25i_dbfe2a_door` (B) |
| SC config (CM entry) | `security_lock_entities = [lock.doorlock_kwikset_zwave_frontentry]`; `security_garage_entities = [both covers]`; `security_lock_check_interval = 60`; `security_auto_follow = false`; armed `disarmed`; observation off |
| CM sleep window | 22 → 06 |
| HA zones | only `zone.home`, radius 150 m |
| Persons | `person.oji_udezue` (app GPS + BLE IRK + bermuda), `person.ezinne`, `person.ziri` (single tracker), `person.jaya` (BLE only), `person.wall_kiosk` (no trackers, excluded) |
| Car | `lock.2025_cx_90_phev_preferred_lock` exists. Whether a car `device_tracker` exists is UNKNOWN (D0 Q8). |
| HA `proximity` integration | UNKNOWN whether configured (D0 Q3). No URA code reads `proximity.*` or `direction_of_travel` (grep of the integration: 0 hits). |

### 1.2 REUSE-or-BUILD per piece

Rev 1 table stands (house-state signal `security.py:1086`; `SIGNAL_PERSON_ARRIVING` `:2107`; geofence listener `:1987-2050`; `ServiceCallAction` via `evaluate()` `:801-833`; observation gate `:825-831`; decision/activity log `:1399-1430`; policy record `:1434-1457`; compliance read-back `:1804-1813`; unavailable dedup `:1735-1752`; hazard egress `:2051-2104`; optimizer veto on `lock.*` `:1904`). Rev 2 additions:

| Piece | Verdict | Evidence |
|---|---|---|
| Lock-regime component | **NEW** (small module) | No lock-policy owner exists: door-lock writes are spread over the periodic sweep `_evaluate_lock_check` (`security.py:1678`), lockdown `_generate_lockdown_actions` (`:1642`, called at `:1043`, `:1578`), and hazard egress (`:2084`). |
| House-state feed to the regime | EXTEND `_on_house_state_changed_signal` | Today it returns before queueing when auto-follow is off (`security.py:1104-1105`). The regime feed goes BEFORE that return; the arming path after it is unchanged. |
| Person listener for the regime | EXTEND `_handle_person_state_change` | Returns on DISARMED first (`security.py:2015`). The regime dispatch goes BEFORE that return; the sanction-checker code after it is unchanged. One listener, two consumers. |
| Vacation detection | REUSE `HouseState.VACATION` | `house_state.py:67`; VACATION → only ARRIVING / AWAY (`house_state.py:122-125`); not inferred (manual override), consistent with the operator's "Vacation is manual". |
| Approach signal: HA `proximity` | NEW consumer of an HA-side entity (no URA prior art, grep above) | Config-first: an HA integration the operator configures; URA only reads it. D0 decides if it is usable. |
| Approach signal: approach zone | NEW consumer of an HA zone (operator adds it) | Rev 1 Q1, accepted. |
| Garage open service | **NEW writer** of `cover.open_cover` | Today the only `open_cover` caller in `domain_coordinators/` is `hvac_covers.py` (blinds). SC never opens a garage door. This is the risk centre of Phase 2. |
| Auto-open shadow log | REUSE `decision_logger.log_decision` + `activity_logger.log` | `security.py:1399-1430`. No new table (non-goal). |
| Auto-open NM | REUSE NM path | `security.py:1377-1394` |

Greps run (rev 2, on top of rev 1's): `grep -n "_evaluate_lock_check\|_generate_lockdown_actions\|_HOUSE_STATE_TO_ARMED\|_handle_person_state_change\|open_cover" domain_coordinators/security.py`; `grep -rln open_cover domain_coordinators/` (→ `hvac_covers.py` only); `grep -rn "proximity\.\|direction_of_travel\|cx_90"` over the integration (0 code hits); `grep -n VACATION house_state.py presence.py`. Kanban adjacency: no auto-open / approach card exists; NEW.

### 1.3 Config-First check

- **Phase 1:** no setting does it (rev 1 §1.3). HA automation (option A) would; the operator chose B.
- **Phase 2:** two HA-side config actions are prerequisites and are NOT code: the approach zone (§4.4) and, if D0 says it helps, an HA `proximity` entry. A plain HA automation could also do auto-open; it is rejected for the same reason as option A plus one more: the shadow period, single-open-per-arrival bookkeeping and audit trail are the safety case, and an automation would carry none of them.

---

## 2. Marginal-benefit decomposition

### 2.1 Phase 1 (B vs A) — unchanged from rev 1

B's margin over a three-trigger HA automation is thin in behaviour and real in observability and failure handling (decision log, observation mode, read-back, NM on failure, hazard release). Built at its smallest: edge-triggered, no periodic enforcement, no DB.

### 2.2 Phase 2: auto-open vs release-only (stated plainly)

**What release-only already gives the operator at 3 AM:** the lockout is released on arrival, so the car remote works. He presses the remote as he does today.

**What auto-open adds over release-only:** not pressing the remote, and the door being up a few seconds earlier. That is the whole benefit. On a phone-GPS arrival it is a convenience, measured in seconds, a few times a week.

**What auto-open adds in risk ingredients:**
1. **A new writer that moves a physical barrier OPEN.** Every other SC actuation makes the house more closed. A false open leaves the house open, possibly at 3 AM with everyone asleep and nobody to notice.
2. **It depends on a phone's GPS stream** (cadence, accuracy, iOS region-event timing), which URA does not control and which D0 has not yet measured.
3. **Synthetic inference of intent** ("approaching fast" means "about to arrive") from noisy samples. Drive-bys, a route that passes near home, a passenger phone, or a GPS jump can all look like an approach.
4. **A rare-fire path** that is hard to observe organically: real operator arrivals, a few per week.
5. **Restart / timing seams** (approach mid-restart, debounce windows, one-open-per-arrival bookkeeping): the state-machine × time seam where URA's worst bug families have lived.

The containment in §6.3 (toggle, allowlist, shadow period, sleep sub-toggle, open-without-entry timer, audit) is evidence of that risk, not a discount on it.

**Verdict.** On pure margins, release-only wins: auto-open buys seconds of convenience and adds the first "make the house more open" actuator in SC. The operator has asked for it as a trial, so this plan builds it, but: (a) behind its own toggle, default OFF; (b) only after D0 passes its gates; (c) shadow mode first, with a numeric bar to leave it; (d) as a separate Tier-3 release, so Phase 1 ships and proves itself without waiting for it. If D0 or the shadow period fails, Phase 2 parks and Phase 1 still delivers the stated goal (no family lock-out).

---

## 3. Architecture: separate arming from locks

### 3.1 The split

- **Arming** = the alarm posture (`ArmedState`, `handle_arm` / `handle_disarm` `security.py:2153-2191`, auto-follow map `_HOUSE_STATE_TO_ARMED` `:180-186`, sanction checker, alerts). It decides whether to alarm.
- **Lock regime** = what should be locked or held, keyed on house state and arrivals, and running whether or not the alarm is armed. New module `domain_coordinators/security_lock_regime.py`, class `LockRegimeController`, owned by `SecurityCoordinator`. This cycle it owns exactly one policy: **garage remote lockouts**. It is the named home for door-lock policy later.

Rev 1 called this "GarageLockoutController". Rev 2 renames it and gives it a policy table so a second policy (door locks) can be added without restructuring. Only the lockout policy is populated now.

### 3.2 What moves, what stays, what is carded

| Item | This cycle | Why |
|---|---|---|
| Garage lockout policy | **NEW, in the regime** | The cycle's goal. |
| House-state input to locks | **Moves**: the regime is fed before the auto-follow short-circuit (`security.py:1104`) | This is the coupling rev 1 audited as weak: lock behaviour must not depend on `security_auto_follow`. |
| Person-arrival input to locks | **Moves**: the regime is fed before the DISARMED return (`security.py:2015`) | Same coupling, on the arrival side. |
| Arming map, auto-follow, `handle_arm/disarm`, sanction checker | **Stays** | Arming is the alarm concern; unchanged and byte-identical. |
| Periodic sweep `_evaluate_lock_check` (door re-lock + garage auto-close) | **Stays** in place this cycle | It is already armed-independent; moving it is behaviour-neutral churn with a regression surface. **Carded** `SC-LOCK-REGIME-DOOR-LOCKS-1`: migrate door-lock policy (sweep, a house-state-aware schedule instead of "re-lock everything hourly") into the regime. |
| Sweep's garage auto-close (closes any open garage every sweep, armed-independent, `:1705-1723`) | **Stays**, carded `SC-SWEEP-CLOSES-OPEN-GARAGE-1` | Pre-existing; interacts with Phase 2 (§6.3, an auto-opened door may be closed by the sweep). Not fixed here. |
| Lockdown on alert `_generate_lockdown_actions` | **Stays** (arming/alert concern) | Lockouts not added (non-goal). |
| Hazard egress unlock (`:2051-2104`) | **Extended**: also releases lockouts (rev 1 D4) | Life safety. |
| `ArmedState` remains weak (SLEEP/HOME unmapped, auto-follow off) | **Carded** `SC-ARMING-ALARM-ONLY-1` (decide whether auto-follow is kept, re-scoped to alarm-only, or retired) | Out of scope; the lock regime no longer depends on it, so it can be decided on its own. |

### 3.3 Lockouts stay out of the sweeps

Lockout entities live in their own CONF list and are never in `security_lock_entities` (the periodic sweep and lockdown iterate only `_lock_entities`, `security.py:1648`, `:1685`). The options-flow validator rejects overlap (rev 1 D1, kept).

---

## 4. Producer and consumer checks

### 4.1 "A resident is arriving" (release, Phase 1) — rev 1 §4.1 stands

Producers P1 (`person.<x>` → `home`), P2 (`SIGNAL_PERSON_ARRIVING` source `ble`, ≥ 15 min away), P3 (geofence via Presence, suppressed under Presence observation), P4 (camera face, sparse). Rev 2 adds **P5: `person.<x>` enters the approach zone** (operator adds it, §4.4), the early signal rev 1 lacked. Release on the earliest of P1-P5 for any of the four residents. The HA app / dashboard can always open the door while the lockout is on (recovery path).

Consumer: `LockRegimeController` only (trust: release).

### 4.2 House state — rev 1 §4.2 stands

SLEEP engages. **VACATION engages** (manual state; VACATION → ARRIVING / AWAY only, `house_state.py:122-125`). **AWAY does not engage** (operator: Away is frequent). Known health issues (false AWAY flaps, sticky SLEEP) are harmless for the lockout now: AWAY no longer engages; sticky SLEEP is bounded by the 07:00 backstop.

### 4.3 Lockout entity state — rev 1 §4.3 stands (state on the opener, survives restart UNVERIFIED, D0 Q10).

### 4.4 Operator fast approach (the Phase 2 trust value) — PRODUCER CHECK

Candidate producers, all UNVERIFIED for this house until D0:

| # | Signal | What it is | Expected weakness |
|---|---|---|---|
| A1 | `person.oji_udezue` / phone tracker enters `zone.<approach>` | iOS Companion region event (or a GPS fix inside the radius) | iOS region events can lag; passive-zone behaviour on iOS unverified (below) |
| A2 | HA `proximity` entity for `zone.home` tracking the operator: distance + `direction_of_travel` (`towards` / `away_from` / `stationary` / `arrived`) | Derived from successive tracker fixes | Only as fresh as the fixes; `towards` from two fixes can be noise |
| A3 | Phone `device_tracker` attributes: `gps_accuracy`, `latitude/longitude`, `speed` (if the app reports it), `source_type`, `last_updated` | Raw fixes | Cadence in the last 2 km unknown; `speed` may be absent or -1 on iOS |
| A4 | CX-90 car integration (`lock.2025_cx_90_phev_preferred_lock`; a car `device_tracker` if one exists) | Cloud telematics | Likely minutes of latency; corroborator at best |
| A5 | Bermuda / BLE: operator phone heard by a garage-side scanner | Local radio | Arrives at the driveway, probably too late to lead the door, but a strong "really here" corroborator |
| A6 | `zone.home` enter (150 m) | Region / fix | 10-20 s of driving before the door; late |

**Derived value:** `fast_approach(arrival_episode)` = operator was genuinely away, then entered the approach zone, moving toward home at vehicular speed, with good GPS accuracy, inside a short window. Its arithmetic (speed from successive fixes vs `speed` attribute vs `proximity` distance deltas) is chosen by D0, not here.

**Approach zone — what I need from the operator (HA config, not code):**
- One zone centred on the house, radius **1500 m** (in the 1-2 km range asked). At 50 km/h that is ~100 s of lead; at 30 km/h ~180 s.
- Name `zone.home_approach` (exact id matters; the plan reads it via a CONF field, so any id works).
- **Passive: open question.** A non-passive zone changes `person.state` to the zone name while inside the ring. URA readers treat a non-`home` named zone in places (e.g. `_handle_person_state_change` `not_home → zone`, `security.py:2037`); a person who lives inside 1.5 km of their own commute (a shop, school run) would read "Home Approach" instead of `not_home` for long periods, and every `person.state` consumer would see it. A **passive** zone avoids that, but whether the iOS Companion app still reports region events for passive zones is UNVERIFIED. D0 Q2 checks; until then: **non-passive is NOT recommended**; ask the operator to create it passive and D0 measures whether enter events arrive.
- Also D0 Q3: whether an HA `proximity` entry (zone.home, tracked = `person.oji_udezue`, tolerance ~50 m) exists or should be added.

**Consumers:** the auto-open decision (trust: OPEN a door) and, as a by-product, early lockout release (P5). Display: shadow-log rows and diagnostic attributes.

---

## 5. Falsifiable invariants

### 5.1 Restated precisely (rev 1's "URA never opens a garage door" is narrowed, not dropped)

- **INV-1 (no open outside the auto-open path):** No code added by this cycle other than `AutoOpenController._fire_open()` calls `cover.open_cover`, `cover.toggle`, `cover.set_cover_position` or any service that can move a garage door up. The lock regime (Phase 1) and the existing sweep / lockdown / hazard paths never open a door. Falsify: any other reachable call to a cover-raising service on either garage cover.
- **INV-1A (auto-open is fully gated):** `_fire_open()` issues `cover.open_cover` on door D only if ALL hold at fire time (re-checked after the last `await`): auto-open toggle ON; SC not in observation mode; auto-open shadow switch OFF; the arriving person is in the auto-open allowlist (default `[person.oji_udezue]`); `fast_approach` is true for a fresh arrival episode; that episode has not already produced an open; D reads `closed` (not `open`, `opening`, `unavailable`); house is not VACATION unless the arriving person is the operator (always true under the default allowlist, kept explicit for a widened allowlist); house is not SLEEP unless the sleep sub-toggle is ON; the operator's BLE / person state did not already read `home` for longer than the debounce before the decision (he is already home, so this is not an arrival). Falsify: any reachable state in which an open is issued with one of these false, or two opens are issued for one arrival episode.
- **INV-1B (no remote close, this cycle):** No code added by this cycle calls `cover.close_cover` on a garage door. (The pre-existing sweep does; carded, unchanged.)
- **INV-2 (family release):** While the lockout feature is enabled and SC is not in observation mode, for any of the four residents R, within `GARAGE_LOCKOUT_RELEASE_MAX_S` (5 s) of the first arrival input for R (P1-P5), `lock.unlock` is issued to every available lockout entity reading `locked`, regardless of who engaged it. Falsify: any reachable state (SLEEP, VACATION, mid-debounce, re-engage timer pending, after restart, auto-open toggle in any position) in which an arrival input does not produce the unlock. **Auto-open never weakens INV-2:** the release happens on the same edge whether or not an open follows, and an auto-open path failure (exception, gate false) must not skip the release.
- **INV-3 (no re-engage on top of a resident):** rev 1 INV-3 unchanged.
- **INV-4 (morning):** a SLEEP-engaged lockout is released at the earliest of SLEEP → WAKING / HOME_*, or 07:00 (`sleep_end_hour` 6 + 60 min). **VACATION-engaged lockouts are not released by the clock or by wake** (hold until arrival). Falsify with a stuck SLEEP; and with VACATION at 07:00 (must stay locked).
- **INV-5 (edge-only):** rev 1 unchanged.
- **INV-6 (AWAY inert):** a transition into AWAY never engages a lockout. Falsify: any path where house AWAY produces `lock.lock` on a lockout entity.

### 5.2 Fail-safe directions

- Lockout: **released** (rev 1 §5 stands: boot never engages; recent arrival at boot releases; unavailable skipped with dedup; read-back + one retry + HIGH NM; kill switch OFF RELEASES both lockouts — operator decision 2026-11-07 'Release on off', superseding rev 1/2 'leave as is').
- Auto-open: **closed / no action.** Any doubt (missing attribute, stale fix, restart, exception, unavailable door) = no open. The lockout release still happens, so the remote works.

---

## 6. Design

### 6.1 Lock regime — lockout policy (Phase 1)

State in memory only: `reason: none | sleep | vacation`, timer handles, `last_action`.

| Trigger | Condition | Action |
|---|---|---|
| house_state → SLEEP | enabled | engage, reason=sleep |
| house_state → VACATION | enabled | engage, reason=vacation |
| house_state → AWAY | — | **nothing** (INV-6) |
| house_state SLEEP → WAKING / HOME_* | reason == sleep | release |
| clock 07:00 (`sleep_end_hour` + backstop) | reason == sleep | release (not for reason == vacation) |
| resident arrival P1-P5 | any lockout reads `locked` | release (any engager); if reason == sleep and in night window, schedule re-engage per INV-3; if reason == vacation, clear reason (no re-engage: the house is no longer on vacation in practice; operator ends the manual state) |
| re-engage timer | both doors closed, house SLEEP, before `sleep_end_hour` | engage, reason=sleep |
| safety hazard critical | `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS` | release (direct call, like egress) |
| setup | rev 1 §5 boot rule | read, maybe release; never engage |

Actions are `ServiceCallAction` returned from `evaluate()` for intent source `lock_regime`, so observation mode and CM resolution apply. Idempotent per entity; decision + activity log; policy record `security.lock_regime.garage_lockout`; read-back.

### 6.2 Auto-open (Phase 2) — `AutoOpenController` in `domain_coordinators/security_auto_open.py`

Separate module so INV-1 is checkable by file: it is the only file in the integration allowed to emit a cover-raising service for a garage.

**Arrival episode.** An episode opens when the operator has been genuinely away (person state not `home` AND BLE not resolving him home for ≥ `AUTO_OPEN_MIN_AWAY_MIN`, 15, matching `_min_away_minutes`) and the first approach signal arrives. It closes on: an open fired, the operator reading `home` + BLE-at-home for `AUTO_OPEN_EPISODE_CLOSE_S`, the episode timing out (`AUTO_OPEN_EPISODE_MAX_S`), or the operator leaving the approach zone outward. **At most one open per episode** (episode id stamped on fire; second fire is a no-op and logged).

**Decision (fast_approach), provisional, finalised by D0:**
1. Approach-zone enter (A1) or proximity distance ≤ zone radius (A2);
2. Direction toward home: proximity `direction_of_travel == towards`, or distance strictly decreasing over ≥ 2 fixes;
3. Vehicular: speed ≥ `AUTO_OPEN_MIN_SPEED_KMH` (20) from fix deltas or the `speed` attribute, whichever D0 shows is real;
4. Quality: `gps_accuracy` ≤ `AUTO_OPEN_MAX_GPS_ACCURACY_M` (50) on the deciding fixes, fix age ≤ `AUTO_OPEN_MAX_FIX_AGE_S` (60);
5. Debounce: the conditions hold across ≥ 2 consecutive fixes, or one fix plus zone enter, within `AUTO_OPEN_DEBOUNCE_S`;
6. Timing: fire when predicted arrival is within `AUTO_OPEN_LEAD_S` of the door (or simply on `zone.home` enter if D0 shows that A1/A2 leads are too variable; D0 decides between "fire on approach" and "fire on home-ring enter with approach as the pre-condition"). The second form is safer (the 150 m ring is the operator's driveway) and loses only ~10 s; it is the **proposed default** unless D0 shows the home-ring enter arrives after the car is at the door.
7. Optional corroborators (D0 decides if any is reliable enough to REQUIRE): car tracker near home (A4), BLE garage scanner (A5).

**Gates at fire time:** INV-1A list. Always issued after the lockout release on the same episode (release first; open only once the release read-back passed or the lockout was already unlocked; otherwise the open would be refused by the opener anyway, and the HIGH release NM covers it).

**Which door:** `CONF_SECURITY_AUTO_OPEN_COVER` (single entity). **Proposed default: the door D0 shows the operator's arrivals open most often** (≥ 80 % of his vehicular arrivals in the window). Operator question Q-A1.

**Sleep:** the 3 AM red-eye is the motivating case, and also the worst case for a false open (nobody awake to notice). Decision: **auto-open in SLEEP is behind its own sub-toggle `switch.ura_security_coordinator_auto_open_in_sleep`, default OFF.** Shadow decisions are logged in SLEEP regardless, so the data needed to turn it on accrues. Justification: in SLEEP the lockout release still happens, so the remote works; the only loss with the sub-toggle off is the button press. The operator turns it on after the shadow data shows zero false opens at night.

**Vacation:** VACATION blocks auto-open unless the arriving person is the operator (the allowlist already guarantees this; the gate stays explicit for a later widened allowlist).

**Open-without-entry timer.** After an auto-open, if no entry evidence (door → `closed` after the car is in, a garage / mudroom motion sensor, the operator's BLE resolving to an interior room) within `AUTO_OPEN_NO_ENTRY_S` (180): **HIGH NM** "Garage A was opened for your arrival 3 min ago and no entry was seen. Tap to close, or check the camera." **No auto-close in the trial.** Reason: closing a door remotely when no one is watching it is an obstruction hazard (child, pet, object under the door). Openers have photo-eye reversal, but URA cannot verify the eyes are clear or working, and unattended remote close is exactly the case the opener's own warning flash/beep exists for (whether the blaQ / ratgdo flash-and-beep before a remote close on these models: UNVERIFIED). Auto-close is parked (§9). Note the interaction: the existing sweep (`security.py:1705-1723`) WILL close an open garage on its next pass (up to 60 min later); that is pre-existing behaviour, carded `SC-SWEEP-CLOSES-OPEN-GARAGE-1`, and the NM text must not promise the door stays open.

**Notification on every auto-open** (MEDIUM): "Garage A opened for Oji's arrival (approach 1.4 km, 42 km/h, GPS ±12 m)." Every shadow would-open also gets an activity-log row; NM for shadow decisions is a knob (default ON during shadow so the operator can tell true from false in the moment).

**Audit logging.** Every decision (would-open, open, blocked + the gate that blocked, episode open/close) writes `decision_logger.log_decision` with the full input vector (fix times, distances, speeds, accuracy, zone events, house state, toggles) and an activity row. This is the shadow evaluation dataset; no new table.

**Observation mode first (shadow).** `switch.ura_security_coordinator_auto_open_shadow`, default **ON** when the feature ships. In shadow, the whole decision runs and logs "would open D at T" but never calls the service. Leaving shadow is an operator action, gated on the shadow bar in §8 D7.

**HA restart mid-approach.** Episode state is in memory only and is not restored. After setup, auto-open is inert until (a) SC boot settle completes and (b) a NEW approach-zone enter or two fresh post-boot fixes satisfy the full decision. An approach already in progress when HA restarts therefore usually produces no open (fail closed); the lockout boot rule still releases for a recent arrival, so the remote works. Never open on a restored or pre-boot state.

**Kill:** auto-open toggle OFF = no decision runs (shadow included). Turning it off mid-episode cancels the episode; it never closes a door.

---

## 7. Knobs (every number)

| Knob | Default | Rung | Why / kill semantics |
|---|---|---|---|
| `CONF_SECURITY_GARAGE_LOCKOUT_ENABLED` | off at ship | 3 Switch `switch.ura_security_coordinator_garage_lockout` | Phase 1 kill; turning it OFF issues one `lock.unlock` on both lockouts (skipping unavailable ones, read-back + one retry, HIGH NM on failure), then no further lockout writes. Operator decision 2026-11-07: 'Release on off' |
| `CONF_SECURITY_LOCKOUT_ENTITIES` | the two lockout locks | 2 (CM options, domain=lock) | Validator rejects overlap with `security_lock_entities` |
| `CONF_SECURITY_LOCKOUT_RESIDENTS` | empty = the four persons with trackers | 2 | Operator-accepted: all four; `wall_kiosk` excluded |
| `CONF_SECURITY_LOCKOUT_APPROACH_ZONE` | empty | 2 (entity selector domain=zone) | P5 early release + Phase 2 A1; empty = no approach input |
| ~~`CONF_SECURITY_LOCKOUT_ON_AWAY`~~ | removed | — | Operator: Away never engages; Vacation always does. No knob (one fewer config combination). |
| `GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN` | 60 (07:00) | 3 Number | Operator-accepted; 0 = release at `sleep_end_hour` |
| `GARAGE_LOCKOUT_REENGAGE_DELAY_S` | 900 | 3 Number | 0 = never re-engage after an arrival |
| `GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S` | 600 | 1 | Restart safety, review-only |
| `GARAGE_LOCKOUT_READBACK_S` | 20 | 1 | Protocol window |
| `GARAGE_LOCKOUT_RELEASE_MAX_S` | 5 | 1 | Test oracle |
| `CONF_SECURITY_AUTO_OPEN_ENABLED` | **off** | 3 Switch `switch.ura_security_coordinator_auto_open` | Phase 2 kill; OFF = no decisions at all |
| auto-open shadow | **on** | 3 Switch `..._auto_open_shadow` | ON = decide + log, never act |
| auto-open in sleep | **off** | 3 Switch `..._auto_open_in_sleep` | OFF = no act in SLEEP (shadow still logs) |
| `CONF_SECURITY_AUTO_OPEN_PERSONS` | `[person.oji_udezue]` | 2 | Allowlist; empty = feature inert |
| `CONF_SECURITY_AUTO_OPEN_COVER` | per D0 / Q-A1 | 2 | Single door |
| `CONF_SECURITY_AUTO_OPEN_PROXIMITY_ENTITY` | empty | 2 | Optional A2 input |
| `AUTO_OPEN_MIN_AWAY_MIN` | 15 | 1 | Matches `_min_away_minutes`; review-only (anti-false-open) |
| `AUTO_OPEN_MIN_SPEED_KMH` | 20 (D0 sets) | 1 | Discriminator: review-only by design, so a live tweak can't loosen the safety gate |
| `AUTO_OPEN_MAX_GPS_ACCURACY_M` | 50 (D0 sets) | 1 | same |
| `AUTO_OPEN_MAX_FIX_AGE_S` | 60 (D0 sets) | 1 | same |
| `AUTO_OPEN_DEBOUNCE_S` | 90 (D0 sets) | 1 | same |
| `AUTO_OPEN_LEAD_S` | D0 sets | 1 | same; unused if the home-ring-enter form is chosen |
| `AUTO_OPEN_EPISODE_MAX_S` | 900 | 1 | Episode bound |
| `AUTO_OPEN_EPISODE_CLOSE_S` | 120 | 1 | Episode close debounce |
| `AUTO_OPEN_NO_ENTRY_S` | 180 | 3 Number | Operator tunes the nag; 0 = no no-entry NM (not recommended) |

All anti-false-open discriminators are rung 1 on purpose: changing them should require a reviewed change, not a dashboard slider.

---

## 8. Deliverables

### Phase 1 — lock regime + lockout (Tier 2-DB protocol)

#### D0: Measure (read-only probe, go/no-go gate for D3 lead and ALL of Phase 2)

One script over the HA recorder (keeps ~7 days) plus the URA DB (`house_state_log`, person / transition rows, which go back further). Questions in §8.1; thresholds in §8.2. Report in §13.
- **Verify:** §13 filled with N, per-signal availability and lead distributions, the replayed false-positive count.
- **Discriminates:** a positive lead with zero replay FPs means Phase 2 is buildable; any replay FP or a negative median lead means Phase 2 parks (Phase 1 still ships). A "looks plausible" design would not tell these apart.

#### D1: Config + kill switch
As rev 1 minus `_ON_AWAY`, plus `CONF_SECURITY_LOCKOUT_APPROACH_ZONE`. Kill switch semantics (operator 2026-11-07, 'Release on off'): ON→OFF releases both lockouts once, then the regime stops writing; OFF at boot (restore) does NOT issue writes (only an operator edge releases). Tests: `test_lockout_config_roundtrip`, `test_lockout_entities_overlap_rejected`, `test_lockout_switch_restores`, `test_kill_switch_off_releases_both`, `test_kill_switch_off_skips_unavailable`, `test_kill_switch_restore_off_no_write`. Live: fields present; switch present.

#### D2: Lock regime + engage / morning / vacation
`LockRegimeController` with §6.1, fed from `_on_house_state_changed_signal` BEFORE the auto-follow return.
- **Verify:** SLEEP → both `lock.lock`; VACATION → both `lock.lock`; AWAY → nothing; SLEEP → HOME_DAY → unlock; stuck SLEEP → unlock at 07:00; VACATION at 07:00 → still locked.
- **Discriminates:** `test_vacation_not_released_by_backstop` fails if the backstop keys on "any URA engage" instead of reason; `test_away_never_engages` fails if AWAY is left in the engage set; `test_regime_runs_with_auto_follow_off` fails if the feed is placed after the `:1104` return.
- **Test:** `test_sleep_engages_both`, `test_vacation_engages_both`, `test_away_never_engages`, `test_wake_releases_sleep_engaged`, `test_backstop_releases_stuck_sleep`, `test_vacation_not_released_by_backstop`, `test_vacation_not_released_by_wake`, `test_regime_runs_with_auto_follow_off`, `test_arming_path_unchanged_byte_identical`, `test_manual_unlock_not_reasserted`, `test_no_engage_when_disabled`, `test_observation_mode_records_would`.
- **Live:** tonight at SLEEP both lockouts `locked` with `last_action.trigger = house_state:sleep`; next morning `unlocked` with `house_state:waking` or `backstop`.

#### D3: Arrival release (P1-P5) + re-engage
Regime dispatch placed in `_handle_person_state_change` BEFORE the DISARMED return; `_handle_person_arriving_signal` branch; approach-zone enter (P5).
- **Verify:** lockout engaged (URA or manual) + resident `not_home → home` → unlock ≤ 5 s; `unknown → home` releases; approach-zone enter releases; `wall_kiosk` never releases; VACATION-engaged + arrival → unlock and no re-engage.
- **Discriminates:** run each with SC DISARMED (the live state) so a branch placed after the `:2015` return fails.
- **Test:** rev 1 list + `test_release_while_disarmed`, `test_approach_zone_enter_releases`, `test_vacation_arrival_releases_no_reengage`.
- **Live:** one controlled test with the operator (rev 1 D3).

#### D4: Fail-safes — rev 1 D4 unchanged, plus `test_regime_never_emits_cover_service` (INV-1 for Phase 1: drive every regime edge, assert no `cover.*` action).

#### D5: Diagnostics + docs
Attributes on `sensor.ura_security_coordinator_security_armed_state`: `lock_regime_garage_lockout_{enabled,reason,last_action,reengage_at}` (`_unrecorded_attributes` if they churn). Update `docs/Coordinator/SECURITY_COORDINATOR.md` (new "Lock regime vs arming" section) and the presence doc §1 consumer table (new consumer of `SIGNAL_PERSON_ARRIVING`, `person.*`, the approach zone).

#### D5b: Keypad physical test (operator, before enabling — accepted)
With each lockout ON, try the outside wireless keypad and a car remote on each door. Record in §13. **Gate:** if a keypad still opens a door with its lockout ON, the lockout does not deliver the stated goal for that door; the feature can still ship (remotes are blocked) but the README must say so.

### Phase 2 — operator auto-open trial (Tier 3, separate release, only if D0 passes)

#### D6: `AutoOpenController` (shadow-capable)
§6.2 in full; config + three switches; decision log.
- **Verify:** a replayed real arrival (fixture built BY HAND from one D0 arrival, committed) produces exactly one would-open at the expected fix; a replayed drive-by and a replayed "passenger in another car" produce none; restart mid-approach produces none; second fire in an episode is a no-op.
- **Discriminates:** fixtures from real recorder rows, not synthetic happy paths, so a speed or accuracy rule that only passes clean data fails on the drive-by fixture.
- **Test:** `test_single_open_per_episode`, `test_no_open_when_toggle_off`, `test_shadow_logs_never_acts`, `test_no_open_non_allowlisted_person`, `test_no_open_in_sleep_unless_subtoggle`, `test_no_open_in_vacation_non_operator`, `test_no_open_when_door_not_closed`, `test_no_open_when_already_home`, `test_no_open_after_restart_mid_approach`, `test_no_open_on_stale_fix`, `test_no_open_poor_gps_accuracy`, `test_driveby_fixture_no_open`, `test_release_happens_even_if_open_path_raises` (INV-2), `test_only_auto_open_module_emits_cover_open` (INV-1, drives every SC path), `test_no_entry_timer_notifies_no_close` (INV-1B), `test_every_open_notifies`.
- **Live:** with shadow ON, the operator's next real arrival writes a would-open decision row with the input vector.

#### D7: Shadow period → act (operator gate, not a calendar)
Leave shadow only when the shadow log shows: ≥ 10 operator vehicular arrivals with a would-open; **0 would-opens not followed by the operator's real garage open / entry within 5 min**; recall ≥ 90 % (would-open on ≥ 90 % of his real vehicular arrivals). Evaluated by one query over `decision_log` when the count is reached, not by watching. If a single false would-open appears, the rule is fixed (rung-1 change, reviewed) and the count restarts. A code trip-wire: any would-open (shadow or act) with no entry within `AUTO_OPEN_NO_ENTRY_S` writes an anomaly row wired to NM.
- **Live:** first act-mode open notifies, entry seen, no no-entry NM.

### 8.1 D0 probe questions

1. **Operator vehicular arrivals:** in the recorder window, list every return of `person.oji_udezue` after ≥ 15 min away, and for each the first garage cover `opening` (A or B) within 10 min. N? Which door, how often (sets Q-A1)?
2. **Approach zone:** once the operator adds it, do zone enter events / `person` state changes for it appear? Passive vs not: does a passive zone produce any recorder-visible signal on iOS? (If the zone is added after D0 runs, D0 re-runs Q2 after ≥ 3 real arrivals.)
3. **Proximity:** does a `proximity` config entry exist? If added, what cadence do distance / `direction_of_travel` update at in the last 2 km, and how often does `towards` appear before the garage opens?
4. **Phone tracker attributes:** on the operator's phone `device_tracker`: is `speed` present and real (not -1 / absent)? `gps_accuracy` distribution in the last 2 km? `source_type`? Fix interval in the last 2 km (median / p90)?
5. **Lead times:** for each arrival, time from each signal (zone.home enter, approach enter, first `towards`, first fix ≤ 1.5 km, first BLE garage-scanner sighting, car tracker home) to the garage `opening` event. Median / p10 / p90 per signal.
6. **False-positive replay:** run the provisional `fast_approach` rule over ALL operator fixes in the window. How many would-opens are not followed by a garage open within 5 min (drive-bys, errands nearby, GPS jumps)?
7. **Non-operator contamination:** did any arrival-shaped event come from the operator's phone while he was a passenger / not driving to the garage (e.g. dropped off at the front)? (Operator annotation needed for flagged events.)
8. **CX-90:** does the car integration expose a `device_tracker` or location sensor? Update latency vs the garage open?
9. **BLE:** time from the first Bermuda sighting of the operator's IRK at any scanner to the garage open; which scanner hears him first (is there one garage-side)? Respect ledger #13 (`home` with `area: null` is stale, not a fix).
10. **Lockout state persistence:** did both lockout entities keep their state across the last HA restart (rev 1 Q)?
11. **Night arrivals:** of all residents' arrivals, how many fell in 22:00-06:00? (Sizes the sleep sub-toggle value and the rare-fire problem.)

### 8.2 Go / no-go thresholds

| Gate | Threshold | If missed |
|---|---|---|
| G1 sample size | N ≥ 8 operator vehicular arrivals in the window | Phase 2 build waits; ship Phase 1; re-run D0 when N is reached (or ship D6 shadow-only as the measurement, operator choice Q-A3) |
| G2 lead of the chosen trigger before garage `opening` | median ≥ 20 s AND p10 ≥ 5 s (home-ring form); median ≥ 60 s (approach form) | Fall back to the home-ring form; if that fails too, park Phase 2 (the operator is at the door before any signal) |
| G3 fix quality in the last 2 km | `gps_accuracy` ≤ 50 m on ≥ 90 % of fixes; fix interval p90 ≤ 60 s | Park Phase 2 (decision would rest on stale/fuzzy fixes) |
| G4 replay false positives | **0** would-opens without a real garage open within 5 min | Tighten the rule and re-replay; if no rule reaches 0 FP with recall ≥ 80 %, park Phase 2 |
| G5 replay recall | ≥ 80 % of real vehicular arrivals produce a would-open | Same as G4 |
| G6 Phase 1 early release (P5) | approach enter precedes garage `opening` on ≥ 80 % of arrivals | P5 still shipped (harmless), but the README states remotes may still be locked on arrival for the rest; the HA app remains the recovery path |
| G7 keypad (D5b) | lockout blocks the keypad on each door | Ship with README caveat for that door |

---

## 9. Non-goals and parked

- No remote garage close by any new code (INV-1B). Auto-close after the no-entry timer: **parked**; revive only if (a) the opener's own pre-close warning (flash/beep) is verified on both models and (b) the operator asks after the trial.
- Pre-existing sweep garage auto-close not changed (carded `SC-SWEEP-CLOSES-OPEN-GARAGE-1`).
- Door-lock policy not migrated into the regime (carded `SC-LOCK-REGIME-DOOR-LOCKS-1`).
- Arming / auto-follow unchanged (carded `SC-ARMING-ALARM-ONLY-1`).
- Lockouts not in `security_lock_entities` or `_generate_lockdown_actions`.
- AWAY never engages.
- No face-identity gating; no guests.
- Auto-open for family members other than the operator: **parked**; revive after D7 passes and the operator asks.
- Auto-open on foot or bicycle: non-goal (vehicular only).
- No DB schema or new table.
- Parked from rev 1: periodic enforcement; per-door separate lockout policies.

## 10. Reviewer focus

### Phase 1 (three framing-disjoint passes, Tier 2-DB protocol)
- **A — Correctness + edge cases:** §6.1 edges against `VALID_TRANSITIONS` (SLEEP → AWAY with reason sleep; VACATION → AWAY must not release; VACATION → ARRIVING), reason bookkeeping, AWAY inert, idempotence, resident resolution, INV-1 for the regime.
- **B — Async / lifecycle / arming-vs-locks separation:** the regime feed placed before both early returns (`:1104`, `:2015`) without changing the arming or sanction paths (byte-identical on the arming side); timers on teardown; restart at night; arrival vs re-engage vs backstop races; Presence vs SC observation.
- **C — Test authority by per-site mutation:** neuter each release site (person-listener branch, arrival signal, approach zone, house-state release, backstop, hazard) and the VACATION engage one at a time; a named test must fail each time.

### Phase 2 (Tier 3: four passes)
- **A — local correctness:** episode bookkeeping, speed/accuracy arithmetic, units (m vs km, km/h vs m/s), fix-age math, the gate list.
- **B — integration / lifecycle:** restart mid-approach, toggle flips mid-episode, release-before-open ordering, `await` re-check of every gate, interaction with the sweep closing the door.
- **C — mutation:** each INV-1A gate neutered one at a time (allowlist, shadow, sleep sub-toggle, door-closed, one-per-episode, already-home, fix age, accuracy); each must turn a named test red.
- **D — adversarial completeness:** state INV-1/INV-1A falsifiably and break it with legal-config repros: widened allowlist + VACATION; sleep sub-toggle ON + stale fix at 03:00; two phones of one person (iPad lesson, presence §3); approach zone made non-passive; proximity entity pointing at the wrong person; toggle ON while shadow switch restored `unavailable` after restart (RestoreEntity unavailable → which way does it read? must read as shadow ON); any second path to `cover.open_cover` anywhere in the integration.

## 11. Tier

- **Phase 1:** Tier 2 by scope (new small module, config, switch, no DB), operator-elevated to the Tier 2-DB three-review protocol: a security actuator with a family-lockout failure mode and cross-coordinator inputs. Not Tier 3: no shared primitive changes, and the HA-app recovery path bounds the failure.
- **Phase 2 (auto-open): recommend Tier 3.** Triggers: it is safety-impacting (a wrong path leaves the house open, possibly at night), the failure mode is "one missed gate" across many conditions (Bug Class #53 shape), and it is the first SC writer that makes the house more open. Tier 3 adds the D pass, config-extreme tests (allowlist × VACATION × sleep sub-toggle × shadow), orchestrator re-grep of every `cover.open_cover` site plus a real mutation before ship, and an operator checkpoint before deploy. Two plan reviews (completeness + adversarial build-prediction) before D6 is dispatched.

## 12. Operator questions

Answered (2026-11-07): approach zone yes; hold-until-arrival yes (now: Vacation only); keypad physical test before relying on it; kill switch OFF releases both lockouts (changed 2026-11-07 from 'keeps state'); all four residents; 07:00 backstop; Away does not engage; Vacation engages until a resident arrives; auto-open trial for the operator only behind its own toggle.

Open:
- **Q-A1. Which door for auto-open?** Proposed: the one D0 shows your arrivals use most (≥ 80 %). If you already know (the CX-90's bay), say which.
- **Q-A2. Approach zone: passive?** Proposed: create `zone.home_approach`, centre = house, radius 1500 m, **passive**, so it does not change everyone's `person` state on errands. D0 then checks whether the iPhone still reports entering it. If passive gives no signal, we decide then whether non-passive is worth its side effects.
- **Q-A3. If D0 has too few arrivals (G1), ship D6 in shadow-only as the measurement?** Proposed: yes; shadow mode cannot open anything.
- **Q-A4. Sleep sub-toggle:** OK that auto-open stays off at night until the shadow log shows zero false opens at night? (The lockout release still happens at night, so your remote works.)
- **Q-A5. No-entry NM at 3 min, no auto-close:** OK? Note the existing hourly sweep will still close an open garage on its next pass (pre-existing, carded).
- **Q-A6. HA `proximity`:** add a proximity entry (zone.home, tracking you) so D0 can measure it? It is an HA setting, no URA code.

## 13. D0 results

(pending)


## Operator answers to Phase 2 questions (2026-11-07)
Operator: 'I thought I answered those questions?' — taken as acceptance of the planner recommendations, as for rev 1:
- Q-A1 door: the bay D0 shows the operator uses on >=80% of arrivals.
- Q-A2 approach zone: `zone.home_approach`, 1500 m, passive; created at D0.
- Q-A3 too few arrivals: ship Phase 2 in shadow-only to collect data.
- Q-A4 Sleep: auto-open stays off at night until the shadow log shows zero false night opens.
- Q-A5 after auto-open: HIGH notice at 180 s, no auto-close.
- Q-A6 proximity: add an HA `proximity` entry (home, operator) at D0.
