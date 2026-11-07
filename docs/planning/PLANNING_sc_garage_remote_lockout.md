# PLANNING — Security Coordinator: garage remote lockout (A + B)

**Card:** GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 (operator picked option B, 2026-11-07).
**Tier:** 2-DB review protocol (three framing-disjoint reviews), operator-elevated. See §11.
**Status:** plan, not reviewed. No code written.

Operator intent: the opener "remote lockout" stops the outside keypad and car remotes from being guessed or bypassed. "The SC does not have this concept." Build on existing SC concepts unless they are weak. Include Garage B. "3 AM entries from red eyes. Don't want family to be locked out."

Mandatory reads done for this plan: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete, all 835 lines, including the §10 corrections ledger) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (complete). No claim in either ledger is re-asserted here. `IDENTITY_FUSION_CAMERAS_MANUAL.md` was grepped for arrival/garage sections only (§3 coverage, ARRIVAL-DEPARTURE-NOTIFY-1); this plan does not consume face identity (see §4.3). HVAC is not touched.

---

## 1. Institutional context verified

### 1.1 Live facts (read 2026-11-07, `ha_eval_template` + `.storage/core.config_entries`)

| Fact | Value |
|---|---|
| Lockout entities | `lock.konnected_f0f5bd523b00_lock` (Garage A, Konnected blaQ) = unlocked; `lock.ratgdov25i_dbfe2a_lock_remotes` (Garage B, ratgdo 2.5i) = unlocked. `locked` = lockout ON. |
| Doors | `cover.konnected_f0f5bd523b00_garage_door`, `cover.ratgdov25i_dbfe2a_door` = closed |
| SC config (CM entry) | `security_lock_entities = [lock.doorlock_kwikset_zwave_frontentry]` only; `security_garage_entities = [both covers]`; `security_lock_check_interval = 60`; `security_auto_follow = false`; armed state `disarmed`; observation mode off |
| CM sleep window | `sleep_start_hour = 22`, `sleep_end_hour = 6` (CM entry) |
| HA zones | only `zone.home`, radius **150 m** |
| Persons | `person.oji_udezue` (GPS app + BLE IRK + bermuda + 2 non-phone trackers), `person.ezinne`, `person.ziri` (single tracker), `person.jaya` (BLE only, no GPS), `person.wall_kiosk` (no trackers, must be excluded) |

### 1.2 REUSE-or-BUILD per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Night signal | REUSE `SIGNAL_HOUSE_STATE_CHANGED`, SC already subscribes | `security.py:756-762` → `_on_house_state_changed_signal` `:1086` |
| Morning backstop hour | REUSE `CONF_SLEEP_END_HOUR` / `DEFAULT_SLEEP_END_HOUR = 6` | `const.py:3389-3392` (CM-entry value live = 6) |
| Arrival signal (BLE / geofence / face) | REUSE `SIGNAL_PERSON_ARRIVING`, SC already subscribes | `security.py:738-745` → `_handle_person_arriving_signal` `:2107`; producers `presence.py:5130-5150` (geofence), `person_coordinator.py:1100-1135` (BLE return), `presence.py:5460-5475` (camera face) |
| Direct person-state listener | EXTEND SC's existing `_setup_geofence_listener` | `security.py:1987-2007`; today its handler returns early when DISARMED (`:2015`), so it needs a new branch, not a new listener |
| Resident set | REUSE `CONF_TRACKED_PERSONS` | `const.py:173`. Need the builder to confirm where it is stored and read (person coordinator); if it is not reachable from SC, fall back to all `person.*` with ≥1 device_tracker (excludes `wall_kiosk`). |
| Actuation path | REUSE `ServiceCallAction` via `manager.queue_intent` → `evaluate()` | `security.py:801-833`; batch window 100 ms (`manager.py:50`), so the queue adds ≤ 0.1 s |
| Observation-mode gate | REUSE `evaluate()` blanket suppression | `security.py:825-831` |
| Kill-switch entity pattern | REUSE SC switch family (`switch.ura_security_coordinator_*`) | e.g. `delegate_lights_to_nm`, observation mode (live) |
| Decision / activity log | REUSE `decision_logger.log_decision` + `activity_logger.log` as in `_fire_state_driven_arming` | `security.py:1399-1430` |
| House-policy diagnostic | REUSE `_publish_policy_action` → `record_state_driven_action` | `security.py:1434-1457` (new policy key `security.garage_lockout`) |
| Compliance read-back | REUSE `compliance_tracker.schedule_check(device_type="lock")` | `security.py:1804-1813` |
| Unavailable NM dedup | REUSE `CONF_LOCK_UNAVAILABLE_DEDUP_S` / `nm_cycle_a_knob` | `security.py:1735-1752`, `const.py:4699` |
| Hazard egress | EXTEND `_handle_safety_hazard` (also release lockouts) | `security.py:2051-2104`, gated by `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS` (`const.py:4172`) |
| Optimizer veto | already covers `lock.*` | `security.py:1904-1906`, nothing to do |
| `CONF_SECURITY_LOCKOUT_ENTITIES` | **NEW** | grep `lockout\|lock_remotes\|remote_lock` over the integration: only HVAC AC lockout hits (`database.py:1809-8997`). No garage lockout concept anywhere. |
| Lockout state machine | **NEW** (small) | nothing equivalent in `domain_coordinators/*` |
| Lockout diagnostic sensor | **NEW**, or attributes on the existing `sensor.ura_security_coordinator_security_armed_state` (preferred: attributes, no new entity) | |

Greps run: `grep -rn "SIGNAL_PERSON_ARRIVING"`, `grep -rn "lockout\|lock_remotes\|remote_lock"`, `grep -n "CONF_SECURITY_\|CONF_GARAGE\|CONF_LOCK_" const.py`, `grep -n "sleep_end_hour\|CONF_TRACKED_PERSONS" const.py`, the `security.py` symbol map. Plans grepped for `garage|lockout`: no prior lockout plan (hits are EV / census garage corroborator, unrelated). Memory bodies grepped for `garage`: EV/charging and census only; nothing on lockout. Security design doc `docs/Coordinator/SECURITY_COORDINATOR.md` read for locks/garage: aspirational v1 design (Q2 "Lock integration" open), no lockout.

### 1.3 Config-First check

- **No existing setting does this.** The SC has no lockout field. The only actuator on these entities today is the dashboard tile and "Lock all".
- **Option A (HA automation)** would do it with three triggers. The operator chose B. §2 prices the margin.
- **Operator-side config action that helps either option:** add a larger HA zone (e.g. `zone.near_home`, ~1-2 km) so a phone reports approach before reaching the 150 m home ring. That is an HA setting, not code, and it is the single biggest lever on the 3 AM risk (§4.1). Open question Q1.

---

## 2. Marginal-benefit decomposition (B vs A)

The simple version (A, one HA automation) captures most of the value: lock at bedtime, unlock at 6, unlock when a person goes `home`. What B adds:

1. **It reads URA's house state, not a clock or HA `person.state` alone.** Engage on house SLEEP/AWAY, release on wake. Real but modest: house SLEEP is itself time-windowed (22→06).
2. **Three arrival producers, not one.** BLE return and camera face arrive through `SIGNAL_PERSON_ARRIVING`; for Jaya (BLE-only, no GPS) the person entity is BLE-driven anyway. Moderate value.
3. **Hazard release, observation mode, decision log, compliance read-back, NM on failure.** These are the real margin: an A automation fails silently.
4. **It is part of SC, so the operator's "SC does not have this concept" gap closes.** Product value, not risk reduction.

Marginal risk ingredients B introduces: a new writer to a security actuator; cross-coordinator state (house state + presence + person coordinator); a rare-fire path (3 AM arrival, a few times a year) that is hard to observe organically; HA restart during the night. Containment below (§5, §6) is evidence of that risk.

**Verdict:** B's margin is thin in pure behaviour and real in observability and failure handling. The operator chose B, so this plan builds B at its smallest: edge-triggered only, no periodic enforcement, no new state persisted to the DB. The fancier variants are parked in §9.

---

## 3. Mini-audit of the SC concepts this touches

| # | Concept | Verdict | Why (evidence) | This cycle |
|---|---|---|---|---|
| 1 | Armed state (`ArmedState`, `handle_arm/disarm`) | **Weak** | Live `disarmed`, auto-follow off; `_HOUSE_STATE_TO_ARMED` deliberately leaves SLEEP / HOME_* unmapped (`security.py:175-186`). Arming never fires at night in this house. | **Work around:** do not key the lockout on armed state. Key on house state directly. |
| 2 | House-state subscription + debounce + manual-hold (`_on_house_state_changed_signal`, `_handle_house_state_intent`, `_fire_state_driven_arming`) | **Sound** | Re-checks gates at fire time, teardown flag, debounce collapses flaps (`security.py:1086-1432`). But the bridge returns early when auto-follow is off (`:1104`), so the lockout cannot ride it as is. | **Extend:** the signal handler also feeds the lockout path, independent of `_auto_follow_house_state`. Reuse the fire-time re-check pattern. |
| 3 | Periodic lock sweep (`_evaluate_lock_check`) | **Flawed for this use** | Locks every `unlocked` entity in `security_lock_entities` every sweep, all day (`:1685-1703`). Adding lockouts to that list would re-engage them every 60 min, including mornings and after an arrival release. Separately, it closes any OPEN garage door every sweep, armed-independent (`:1705-1723`): a door left open while unloading gets closed by URA. | **Work around:** lockouts get their own CONF list and are never in `security_lock_entities`. **Card** the garage auto-close (out of scope, pre-existing; candidate `SC-SWEEP-CLOSES-OPEN-GARAGE-1`). |
| 4 | Lockdown actions (`_generate_lockdown_actions`) | **Sound** | Locks doors and closes garages on alert (`:1642-1672`). Does not open anything. | Leave alone. Lockouts are not added here (non-goal). |
| 5 | Geofence listener (`_handle_person_state_change`) | **Weak** | Only active when armed (`:2015`); only `not_home → home` and `not_home → zone` (`:2028`, `:2037`), so `unknown/unavailable → home` (boot, tracker flap) is missed; reads raw `person.state`. | **Extend** with a lockout branch that runs regardless of armed state and accepts any non-`home` → `home`. |
| 6 | `SIGNAL_PERSON_ARRIVING` handler | **Sound with caveats** | Handler gated on SC enabled + SC observation (`:2113-2117`). All three producers are suppressed under **Presence** observation mode (`presence.py:5133`, `person_coordinator.py:1118`), BLE return only fires after ≥ `_min_away_minutes` away (`person_coordinator.py:1100`, 15 min), geofence only on a `home` edge. | **Reuse** as one of two arrival inputs; never the only one (§4.1). |
| 7 | Safety-hazard egress unlock | **Sound** | Config-gated, fire/smoke/CO critical only (`:2078-2097`). Calls services directly, bypassing `evaluate()`; acceptable for life safety. | **Extend** to also release lockouts (a fire crew or a fleeing family can then use remotes/keypad). |
| 8 | Observation mode | **Sound** | Blanket suppression of returned actions (`:825-831`). | Reuse. Lockout engage AND release go through `evaluate()`; observation records "would". |
| 9 | Optimizer veto on `lock.*` | **Sound** | `:1904` | Nothing to do. |
| 10 | Unavailable-lock NM with dedup | **Sound** | `:1725-1771` | Reuse the knob for lockout-entity unavailability. |
| 11 | Notifications for SC actions | **Sound** | NM via `hass.data[DOMAIN]["notification_manager"]` (`:1377-1394`) | Reuse; release failures are HIGH. |

---

## 4. Producer and consumer checks

### 4.1 "A resident is arriving" (the load-bearing value)

**Producers.**
- (P1) HA `person.<x>` → `home`. HA's person entity follows the freshest tracker (`PRESENCE §3`, freshest-GPS note). For Oji/Ezinne/Ziri this is mostly the Companion app GPS geofence on the 150 m `zone.home`. For Jaya it is BLE only. Latency: iOS region-enter events often arrive within seconds to a minute or two; UNVERIFIED for this house. **Failure modes:** phone dead or in low-power mode; app geofence late; car remote pressed at the driveway before the phone reports `home` (the 150 m ring is about 10-20 s of driving at residential speed).
- (P2) `SIGNAL_PERSON_ARRIVING` source `ble` (`person_coordinator.py:1100-1135`): fires when Bermuda resolves a room for a person who was away ≥ 15 min. Requires a scanner to hear the phone, usually from inside or at the garage. **Failure modes:** later than P1 for a driver; suppressed by Presence observation mode; does not fire for a short absence.
- (P3) `SIGNAL_PERSON_ARRIVING` source `geofence` — the same edge as P1, routed through Presence (`presence.py:5130-5150`). Redundant with P1 except it is suppressed under Presence observation.
- (P4) `SIGNAL_PERSON_ARRIVING` source `camera_face` (`presence.py:5460-5475`). Door/garage face coverage is sparse (IDENTITY manual §3, line ~133). Treat as a bonus input, never relied on.

**Dependency health:** P1 depends on the Companion app and HA's person entity (healthy for Oji per PRESENCE §3; Ziri has a single tracker; Jaya has no GPS). P2 depends on the Bermuda fleet (Active Proxy Count guard, PRESENCE §3).

**Consequence for design.** No producer reliably fires before the car remote is pressed at 3 AM. The plan therefore does not rely on arrival release alone:
1. Release on the **earliest** of P1-P4 for any resident.
2. The recovery path that always works: **the HA app / dashboard can open the door while lockout is ON** (live fact: HA still controls the opener). The release-failed and arrival-blocked NMs say so explicitly.
3. Operator config lever (Q1): a larger approach zone turns P1 into an early signal. With it, release fires minutes before the driveway.
4. Measure-before-build (D0) quantifies P1/P2 lead time on real past arrivals.

**Consumers.** Only the new lockout state machine (trust decision: release). No display consumer beyond the diagnostic attributes.

### 4.2 Night / morning (house state)

**Producer:** `PresenceCoordinator` house-state inference, `SIGNAL_HOUSE_STATE_CHANGED` (PRESENCE §2). SLEEP = people present AND sleep hours (CM 22→06). WAKING/HOME_DAY follow. AWAY/VACATION per the α/β/nobody-home ladder. Restored across restart (`house_state.py:33-54`, 1800 s staleness).

**Known health issues (from the PRESENCE ledger, not re-litigated):** false AWAY flaps with untracked occupants (§9 HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1); SLEEP held by raw occupancy past morning (trip-wire `sleep_raw_hold`). Both are acceptable for the lockout direction: a false AWAY engages the lockout (safe direction, released by arrival); a sticky SLEEP keeps it on past 6 AM, so a clock backstop is required (D2).

**Consumers:** the lockout engage/release edges (trust). Existing SC arming consumer unchanged.

### 4.3 Lockout entity state

**Producer:** the opener integrations (Konnected blaQ ESPHome, ratgdo ESPHome). The lock state is held on the opener; it survives an HA restart (UNVERIFIED; D0 checks the recorder across the last HA restart). Consumers: the state machine reads it before acting (idempotence) and after (read-back).

---

## 5. Falsifiable invariants and fail-safe direction

- **INV-1 (no open):** No code path added or changed by this cycle calls `cover.open_cover`, `cover.toggle` or any service that moves a garage door. Falsify: any `cover.*` call reachable from a lockout function.
- **INV-2 (family release):** While the feature is enabled and SC is not in observation mode, for any resident R, within `GARAGE_LOCKOUT_RELEASE_MAX_S` (5 s) of the first arrival input for R (P1-P4), a `lock.unlock` is issued to every available lockout entity that reads `locked`, regardless of who engaged it (URA, dashboard, "Lock all"). Falsify: any reachable state (house SLEEP, AWAY, VACATION, mid-debounce, manual hold, re-engage timer pending, after restart) in which an arrival input does not produce the unlock.
- **INV-3 (no re-engage on top of a resident):** After an arrival release, URA does not engage again until both doors are closed and `GARAGE_LOCKOUT_REENGAGE_DELAY_S` has passed, and never in the morning window.
- **INV-4 (morning):** An URA-engaged lockout is released at the earliest of: house leaves SLEEP to WAKING/HOME_*; the backstop clock `sleep_end_hour + GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN`. Falsify with a stuck SLEEP.
- **INV-5 (edge-only):** URA writes a lockout only on an edge (engage edge, release edge, re-engage timer, hazard). There is no periodic enforcement, so a manual change stays until the next edge.

**Fail-safe direction: released.** Being locked out at 3 AM is worse than a keypad being guessable for a few hours. Concretely:
- Arrival detection fails: the lockout stays on; the resident opens via the HA app; URA sends no "blocked" signal because it cannot know. Mitigated by Q1 zone and by the NM at engage time naming the app as the way in.
- HA restarts at night: on setup, SC reads the lockout state and does nothing to engage. If any resident's `person.state` became `home` within `GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S` before setup (from `last_changed`), release. Arrivals during the outage itself are missed (HA could not open anyway). After the boot settle, normal edges resume; a restart never engages.
- Lockout entity unavailable: skip it, NM via the existing dedup; never retry-loop.
- Unlock call fails or read-back still `locked` after `GARAGE_LOCKOUT_READBACK_S`: one retry, then HIGH NM "Garage remotes still locked; open from the HA app."
- Feature kill switch OFF: URA never writes a lockout. Existing state is left as is (not force-released, to avoid surprising the operator mid-night). Q4.

---

## 6. Design (smallest viable)

New module `domain_coordinators/security_garage_lockout.py`, one class `GarageLockoutController` owned by `SecurityCoordinator` (keeps `security.py`, 2520 lines, from growing). State held in memory only:

```
reason: none | sleep | away            # why URA engaged (None = URA did not)
reengage_unsub, morning_unsub           # timer handles
last_action: {action, trigger, person, at, result}   # diagnostic
```

Edges:
| Trigger | Condition | Action |
|---|---|---|
| house_state → SLEEP | enabled | engage, reason=sleep |
| house_state → AWAY / VACATION | enabled AND `CONF_SECURITY_LOCKOUT_ON_AWAY` | engage, reason=away |
| house_state SLEEP → WAKING / HOME_* | reason == sleep | release |
| house_state AWAY/VACATION → ARRIVING / HOME_* / GUEST | reason == away | release |
| clock `sleep_end_hour + backstop` | reason == sleep | release |
| resident arrival (P1-P4) | any lockout reads `locked` | release (any engager); schedule re-engage if in night window and house still SLEEP |
| re-engage timer | both doors closed, house SLEEP, before `sleep_end_hour` | engage, reason=sleep |
| safety hazard critical | `CONF_SECURITY_ON_HAZARD_UNLOCK_EGRESS` | release (direct call, like the egress path) |
| setup | see §5 | read, maybe release; never engage |

Engage/release are `ServiceCallAction(service="lock.lock"/"lock.unlock")` returned from `evaluate()` for a new intent source `garage_lockout`, so observation mode and CM resolution apply. Each act: skip entities already in target state (idempotent), log decision + activity, publish `security.garage_lockout` policy record, schedule read-back.

Arrival debounce: a single arrival releases once; P1 and P2 for the same person within 60 s collapse (same release, second is a no-op by idempotence, no extra logic needed).

Engage NM (LOW, once per night): "Garage remotes locked for the night. Arriving residents unlock them automatically; the HA app can always open the door."

---

## 7. Knobs (every number)

| Knob | Default | Rung | Why / kill semantics |
|---|---|---|---|
| `CONF_SECURITY_GARAGE_LOCKOUT_ENABLED` | off at ship, operator turns on | 3 (Switch `switch.ura_security_coordinator_garage_lockout`) | Feature kill switch; OFF = URA never writes a lockout |
| `CONF_SECURITY_LOCKOUT_ENTITIES` | the two lockout locks | 2 (CM options flow, entity selector domain=lock) | Per-deployment structure. Must reject overlap with `security_lock_entities` (validator) |
| `CONF_SECURITY_LOCKOUT_ON_AWAY` | True | 2 | Whether AWAY/VACATION also engages (Q2) |
| `CONF_SECURITY_LOCKOUT_RESIDENTS` | empty = tracked persons / persons with trackers | 2 | Who counts as family for release |
| `GARAGE_LOCKOUT_MORNING_BACKSTOP_MIN` | 60 (i.e. 07:00) | 3 (Number) | Stuck-SLEEP backstop; operator may tune; 0 = release exactly at sleep_end_hour |
| `GARAGE_LOCKOUT_REENGAGE_DELAY_S` | 900 | 3 (Number) | Time after an arrival before re-locking; 0 = never re-engage after an arrival |
| `GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S` | 600 | 1 (module const) | Restart safety window; review-only |
| `GARAGE_LOCKOUT_READBACK_S` | 20 | 1 | Protocol window |
| `GARAGE_LOCKOUT_RELEASE_MAX_S` | 5 | 1 | Invariant bound (test oracle, not a timer) |
| `sleep_end_hour` | 6 (live) | REUSED, 2 | Existing CM field |

---

## 8. Deliverables

### D0: Measure arrival lead time (read-only probe, go/no-go gate)
Over the recorder (≥7 days) and URA DB `house_state_log` / person rows: for each resident return after ≥ 15 min away, compute (a) `person.<x>` → home time, (b) the garage cover's first `opening` within 10 min, (c) BLE-return arrival time if logged. Report the distribution of (b − a). Also check whether both lockout entities kept their state across the last HA restart, and whether the ratgdo lockout blocks the wireless keypad (operator physical test, Q3).
- **Verify:** report in this doc §12 with N arrivals and median/p90 lead.
- **Gate:** if p90 lead < 0 (door opens before person→home) on > 20 % of arrivals, Q1 (approach zone) becomes a precondition for enabling, and the engage NM wording becomes mandatory.
- **Discriminates:** lead > 0 means arrival release works as designed; lead < 0 means residents would hit a locked remote, which a "looks fine" deploy would not show.

### D1: Config + kill switch
`CONF_SECURITY_LOCKOUT_ENTITIES`, `_ON_AWAY`, `_RESIDENTS` in CM options (security step), Switch entity with RestoreEntity, validator rejecting overlap with `security_lock_entities`.
- **Test:** `test_lockout_config_roundtrip`, `test_lockout_entities_overlap_rejected`, `test_lockout_switch_restores`.
- **Live:** options flow shows the field; switch present.

### D2: Engage / morning release state machine
`GarageLockoutController` with the edges in §6, wired from `_on_house_state_changed_signal` (independent of auto-follow) and a `async_track_time_change` at the backstop hour.
- **Verify:** house SLEEP → both `lock.lock`; house HOME_DAY from SLEEP → both `lock.unlock`; stuck SLEEP → unlock at backstop.
- **Discriminates:** an unlocked lockout at 07:01 after a stuck SLEEP passes; the same test with the backstop deleted fails.
- **Test:** `test_sleep_engages_both`, `test_wake_releases_sleep_engaged`, `test_backstop_releases_stuck_sleep`, `test_away_engages_when_knob_on`, `test_away_noop_when_knob_off`, `test_manual_unlock_not_reasserted` (INV-5), `test_no_engage_when_disabled`, `test_observation_mode_records_would`.
- **Live:** tonight at house SLEEP, both lockouts `locked`, `last_action.trigger = house_state:sleep`; next morning `unlocked` with trigger `house_state:waking` or `backstop`.

### D3: Arrival release + re-engage
Extend `_handle_person_state_change` with a lockout branch (any non-home → home, armed-independent) and `_handle_person_arriving_signal` with a lockout branch. Re-engage timer per INV-3.
- **Verify:** with lockout engaged (by URA or manually), resident `not_home → home` → unlock within 5 s; `unknown → home` also releases; `wall_kiosk` never releases; re-lock after 900 s only if both doors closed and still SLEEP.
- **Discriminates:** test with house SLEEP AND house AWAY AND lockout engaged by a direct `lock.lock` (not URA), so a release keyed on `reason` alone fails.
- **Test:** `test_arrival_releases_any_engager`, `test_arrival_from_unknown_releases`, `test_arrival_signal_ble_releases`, `test_non_resident_no_release`, `test_reengage_waits_for_doors_closed`, `test_no_reengage_after_sleep_end`, `test_presence_observation_still_releases_via_person_listener` (P1 path survives Presence observation).
- **Live:** one controlled test with the operator: lockout ON, toggle a resident's phone away/home (or a real return) and read `last_action` + the lock's recorder history.

### D4: Fail-safes
Boot rule (§5), read-back + one retry + HIGH NM, unavailable skip with existing dedup, hazard release.
- **Test:** `test_boot_never_engages`, `test_boot_recent_arrival_releases`, `test_readback_failure_notifies_high`, `test_unavailable_lockout_skipped`, `test_hazard_releases_lockouts`, `test_no_cover_service_anywhere` (INV-1: assert no `cover.*` service in any lockout action, plus a source grep in CI is not enough; the test drives every edge and inspects emitted actions).
- **Live:** after the deploy restart, log shows "garage lockout: boot read, no engage".

### D5: Diagnostics + docs
Attributes on `sensor.ura_security_coordinator_security_armed_state`: `garage_lockout_enabled`, `garage_lockout_reason`, `garage_lockout_last_action`, `garage_lockout_reengage_at`. Mark them `_unrecorded_attributes` if they churn. Update `docs/Coordinator/SECURITY_COORDINATOR.md` with a lockout section, and the presence doc §1 consumer table (new consumer of `SIGNAL_PERSON_ARRIVING` and `person.*`).
- **Live:** attributes populated after the first edge.

---

## 9. Non-goals and parked

- Never opens or closes a garage door. The existing sweep auto-close (audit #3) is not changed here; carded.
- No change to arming / auto-follow mapping; no SLEEP → ARMED_HOME mapping.
- Lockouts not added to `security_lock_entities` or `_generate_lockdown_actions`.
- No identity (face) gating; no guest handling (a guest without a tracker is not "family" and must use the app/wall button).
- No dashboard changes (done).
- No DB schema or new table.
- **Parked:** pre-emptive release on approach using distance/`proximity` integration (revive if D0 shows negative lead even with an approach zone); periodic enforcement (revive if manual unlocks are being forgotten overnight); per-door separate policies.

## 10. Reviewer focus (three framing-disjoint passes)

- **A — Correctness + edge cases:** every edge in §6 against house-state VALID_TRANSITIONS (SLEEP → AWAY, GUEST paths), the `reason` bookkeeping, idempotence, resident resolution, INV-1 by driving all edges.
- **B — Async / lifecycle / cross-coordinator:** timer cleanup on teardown, restart at night (boot rule), races between arrival and the re-engage timer and the morning timer, Presence observation vs SC observation, the bridge no longer short-circuiting on auto-follow without changing arming.
- **C — Test authority by per-site mutation:** neuter each release site (person listener branch, signal branch, house-state release, backstop, hazard) one at a time and confirm a named test fails; config round-trip + switch restore.

## 11. Tier

Behaviour scope alone is Tier 2 (new capability, ~2 files + config + switch, no DB). Operator-elevated to the Tier 2-DB three-review protocol under the standing regression-prone policy: it is a security actuator with a family-lockout failure mode and cross-coordinator inputs (presence, person coordinator, house state). Not Tier 3: no shared primitive is changed, and the failure mode is bounded by the always-available HA-app recovery path.

## 12. Open questions (operator)

- **Q1.** Add an approach zone (e.g. 1-2 km `zone.near_home`) so arrival release fires before the driveway? If yes, D3 releases on entering it too.
- **Q2.** Should AWAY/VACATION also engage the lockout (default proposed: yes), and should an AWAY-engaged lockout also release at 6 AM or hold until someone arrives (proposed: hold until arrival)?
- **Q3.** Physical test: with Garage B's "Lock remotes" on, does the outside wireless keypad still open the door? Same for Garage A. If the keypad still works, the lockout does not deliver the stated goal for that door.
- **Q4.** When the kill switch is turned OFF at night, leave current lockout state as is (proposed) or release?
- **Q5.** Who is "family" for release: all four people with trackers (proposed), or a subset? Guests without trackers will need the app/wall button.
- **Q6.** Morning backstop 07:00 (proposed) acceptable?

## 13. D0 results

(pending)
