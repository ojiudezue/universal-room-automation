# CRITIQUE — Music Following audit + plan (`PLANNING_audit_music_following.md`)

**Author:** ura-planner (critique pass)
**Date:** 2026-07-10
**Base plan:** `docs/planning/PLANNING_audit_music_following.md` (2026-07-02, 8 days old)
**Base HEAD:** develop @ v5.9.0

---

## 1. Institutional-context section audit

The plan's "Institutional context verified" section is present and largely well-formed (files surveyed with line ranges, grep results with file:line, prior planning docs / memory / design docs enumerated). It satisfies the CLAUDE.md mandate.

Verified re-greps at current HEAD:

- `music_following.py` still 1063 lines (matches plan).
- `domain_coordinators/music_following.py` still 586 lines (matches plan).
- `transitions.py:231` ping-pong suppression — CONFIRMED. `_is_ping_pong` → suppressed transitions skip `_notify_listeners`; MF never sees them (transitions.py:229-242).
- MF constant surface in `const.py` at claimed line numbers — verified (const.py:1164 header, CONF_MF_* still at L1167-1173, CONF_MUSIC_ON_{HAZARD,ARRIVAL,SECURITY}_* at L1537-1539 — note plan cited L1524-1526; drift is +13 lines but constants unchanged).
- `__init__.py:1902-1915` still initializes MF pre-CM and enables for all tracked persons (verified L1902-1915 at current HEAD).
- Coordinator device grouping already exists: `_music_following_device_info()` in `sensor.py:5873-5886`, `identifiers={(DOMAIN, "music_following_coordinator")}`, name `URA: Music Following Coordinator`. Four MF sensors already attach: `MusicFollowingHealthSensor` (sensor.py:5887), `MusicFollowingAnomalySensor` (6020), `MusicFollowingTransfersTodaySensor` (6093), `MusicFollowingActiveRoomsSensor` (6165), plus `MusicFollowingLastTransferSensor` (referenced sensor.py:215). Switch entity registers Music Following Coordinator device in `switch.py:191`. **Plan omission:** the device layer is already correct — this should be called out in D0 as REUSED (no device work needed for the current sensors; only NEW sensors need to inherit `_music_following_device_info()`).

**Gaps in the plan's institutional section (must be added before build):**

1. **No cite of `SIGNAL_HOUSE_STATE_CHANGED` availability** — required for D2. Verified live at `domain_coordinators/signals.py:12` (`SIGNAL_HOUSE_STATE_CHANGED = "ura_house_state_changed"`) with payload defined signals.py:175, and consumers already in `hvac.py`, `presence.py`, `routine_forecaster.py`, `switch.py`, `sensor.py`, `coordinator.py`. D2 is REUSED signal, NEW subscriber — plan should mark it.
2. **No cite of `OccupancySubstrate` API** — required for D3. Class lives at `domain_coordinators/occupancy_substrate.py`, consumers in `presence.py`, `hvac.py`, `hvac_zones.py`, `hvac_predict.py`, `binary_sensor.py`, `automation.py`. D3 must cite the exact predicate it will call before build.
3. **v5.7.2 actuator-visibility scope** — plan cites the 2026-07-01 memory but does not verify what `UnavailableEntitiesSensor` actually covers. Verified at `sensor.py:1640-1646`: `_ACTUATOR_LIST_KEYS = ("lights", "night_lights", "alert_lights", "fans", "humidity_fans", "covers")` and `_ACTUATOR_SINGLE_KEYS = ("climate_entity",)`. **`room_media_player` is NOT included.** D1's claim that the sensor "extends" to media_player is accurate as a fix direction, but the plan understates the scope: this is a NEW actuator role in an existing sensor's classifier, and `room_media_player` today lives under `entry.data` per-room but is not in either _ACTUATOR_* tuple — the fix is a 1-tuple extension plus verifying its role attribution ("actuator" category).
4. **Backlog memo `docs/BACKLOG.md`** contains a "media_player actuator visibility" line item (matches the memory 2026-07-01 gap) — plan should acknowledge D1 partially closes that backlog item.

---

## 2. Findings re-validation at HEAD (v5.9.0)

| ID | Plan severity | Still valid? | Notes |
|---|---|---|---|
| C1 silent-actuator | HIGH | **YES** | `music_following.py:325-330` only checks `not to_player` (missing lookup), not `to_state.state in unavailable/unknown`. Source `from_state.state != STATE_PLAYING` gate at L343 protects source, but target-side pre-flight is truly absent. Winner rule L351 requires `to_state and to_state.state == STATE_PLAYING` — if `to_state is None` we FALL THROUGH into `_transfer_media`. Confirmed. |
| C2 vestigial `ping_pong_suppressed` | HIGH | **YES** | `music_following.py:131` declares the counter; grep of `music_following.py` for `ping_pong_suppressed +=` / `_record_stat("ping_pong` = 0 hits. `transitions.py:231-238` suppresses BEFORE `_notify_listeners` — MF's counter is unreachable. Bug Class #53 subclass. |
| C3 lock TOCTOU | HIGH | **PARTIAL** | The `.locked()` check + `async with` at L279-286 does exist. The plan's analysis is correct but overstated: the "harmless — would just proceed" case is the actual behavior; the real hazard is stale-transition-through-queued-lock, which the plan does capture. Downgrade to MEDIUM but keep the stale-transition remediation. |
| C4 leak on teardown | MEDIUM | **YES** | `domain_coordinators/music_following.py:558-576` (`async_teardown`) cancels `_pending_tasks`, saves anomaly baselines, nulls `_music_following` — but does NOT call anything on the standalone MF: `_cleanup_tasks` / `_saved_volumes` / `_active_groups` are not touched. `MusicFollowing` has NO `async_teardown`. |
| C5 enable-for-person stale on reload | MEDIUM | **YES** | `__init__.py:1913-1915` runs at initial setup only; no update-listener re-syncs `_enabled_persons`. Standalone MF is preserved across CM reload. |
| C6 alphabetical picker | MEDIUM | **YES** | `music_following.py:638-640`. Comment even says "no platform preference". |
| C7 arrival stub | MEDIUM | **YES** | `domain_coordinators/music_following.py:449-492`. Log-only regardless of toggle state. Truth-in-advertising bug is real. |
| C8 class-attr mutation | LOW | **YES** | `music_following.py:92` class-level `MIN_CONFIDENCE`; coord mutates at L121. Confirmed. Instance shadowing is fine functionally; the fragility is stylistic. |
| C9 divergent task tracking | LOW | **YES** | Standalone: `_cleanup_tasks: list` (L120), O(n) discard (L497). Coord: `_pending_tasks: set`. |
| C10 no restart persistence | LOW | **YES** | Cooldown state RAM-only. |
| C11 day-boundary | LOW | **YES** | L174 `dt_util.now().strftime("%Y-%m-%d")` — timezone-correct but untested. |
| L1 sleep/night gating | HIGH | **YES + STRONG** | No subscriber to `SIGNAL_HOUSE_STATE_CHANGED` in either MF file. `HouseState.SLEEP` / `HouseState.HOME_NIGHT` exist (`house_state.py:29-30`). This is the highest-impact livability gap and easy to wire cleanly. |
| L2 guest-in-source-room | HIGH | **YES** | No source-room occupancy check anywhere in `_execute_transfer`. `OccupancySubstrate` is available as a domain coordinator (verified). |
| L3 volume calibration | HIGH | **YES** | Cross-platform generic copies raw `volume_level` at `music_following.py:993-1002`. No scale factor. |
| L4 verify latency | MEDIUM | **YES** | `_verify_transfer` at L426-461 always sleeps `TRANSFER_VERIFY_DELAY_SECONDS`, including on the `_transfer_same_platform_join` path. Plan is correct that the join path is instant. |
| L5 TTS collision | MEDIUM | **YES**, but no `SIGNAL_TTS_STARTING` exists yet — grep shows 0 hits. Plan already flags this as "to-be-defined". D10 is genuinely deferred until the signal exists; keep as design-only. |
| L6 per-person DND switch | MEDIUM | **YES** | No `switch.music_following_<person>` in switch.py grep. |
| L7 multi-person conflict | LOW | **YES** | Lock is global, no per-person queues. |
| L8 skip-reason invisibility | LOW | **YES** | `get_diagnostic_data` (L204-222) does not include `last_skip_reason` / `last_skip_from_room`. |
| L9 per-pair ping-pong | LOW | **YES** | `PING_PONG_WINDOW_SECONDS` is global const. |

**No finding was invalidated by intervening cycles** (v5.7.2, v5.8.x, v5.9.0). C1's silent-actuator visibility partially benefits from the v5.7.2 pattern (`UnavailableEntitiesSensor`) but requires an explicit media_player extension — the plan's D1 correctly proposes this.

---

## 3. Cross-tier consumption / emission enumeration (operator directive #1)

The audit is coordinator-local. Rooms → Zones → House cross-cutting touchpoints MF should consume or coordinate with:

### Signals MF DOES consume (verified)
- `TransitionDetector` callback → `_on_person_transition` (event, not dispatcher signal). Primary path.
- `SIGNAL_SAFETY_HAZARD` → `_handle_safety_hazard` (coord L406).
- `SIGNAL_SECURITY_EVENT` → `_handle_security_event` (coord L495).
- `SIGNAL_PERSON_ARRIVING` → `_handle_person_arriving` (stub — C7).
- `SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE` → dispatched OUTward from `_on_transfer_outcome` (coord L313).

### Signals MF SHOULD consume but does NOT (gaps)
1. **`SIGNAL_HOUSE_STATE_CHANGED`** — required for D2 sleep/night gating. Producers: `house_state.py`. Consumers today: hvac, presence, routine_forecaster, switch, sensor, coordinator. MF absent.
2. **Room-tier occupancy predicate** — required for D3 guest guard. `OccupancySubstrate` at `domain_coordinators/occupancy_substrate.py`. Would be read (not signal-subscribed) inside `_execute_transfer` between source-playing check (L343) and winner rule (L351).
3. **Sleep-state person-trust (v4.7.13)** — MF has no analog. During SLEEP the room-tier occupancy will still show occupancy on other paths; MF should trust that (or short-circuit before it matters via D2). Explicit cite only needed if D2 is not deployed.
4. **`SIGNAL_EGRESS_STATE`** (from v4.7.8) — window-open → egress hold. If a room's egress hold pauses HVAC, does music follow into a room with an open window? Probably fine, but the coordinator should log a diagnostic when transferring into an egress-active room.
5. **BLE / person_coordinator** — MF DOES read `person_coordinator.data[person_id]["closest_distance"]` at `music_following.py:263-268`. Cite in D0 design doc as a REUSED cross-coordinator read.

### Signals MF emits
- `SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE` (only). No downstream consumers write back to MF today. Adequate for now.

### Room / Zone tier interactions
- MF asks `_get_room_player(room_name)` — walks room config → zone config → HA area → naming convention (`music_following.py:569-676`). This is the ONLY room-tier read. It does not consult the ZoneManager for "which room is currently the primary music room per zone." L9 (per-pair ping-pong) hints at needing zone-pair overrides — verified no such surface.
- Zone-tier `zone_player_mode` (fallback vs override) IS consulted (L601). Good.

### House-tier interactions
- **None today**. MF is coordinator-priority 30 (lowest), does not participate in the house-state decision. This is architecturally correct BUT means MF is invisible to house-state observers and cannot request suppression from HouseStateMachine. D2's approach (MF-local subscribe + gate) is correct — do not push MF into HouseStateMachine.

**Missing tier from the plan:** the plan does not enumerate egress interaction (item 4 above). Add as a design note in D0.

---

## 4. Livable labels audit (operator directive #2)

Reviewed strings.json:1183, `sensor.py:5873-5886`, `switch.py:191-195`, `const.py` MF fields, `config_flow.py:5467`+ (Music Following Coordinator step) for operator legibility.

Findings:

1. **`CONF_MF_HIGH_CONFIDENCE_DISTANCE`** — internal-mechanics naming. Operator does not know what "high confidence distance" is or that it's a BLE-scanner distance in feet. Rename UI label to "BLE proximity threshold (ft)" with helper "Only transfer music when the person's closest BLE scanner is within this range." Constant name can stay; UI label + translation is the fix. Prior art: v4.7.6.1 "Labels + Helper Text" cycle.
2. **`CONF_MF_POSITION_OFFSET`** — leaks the ms-offset implementation. UI label "Cross-platform seek offset (seconds)" + helper explaining "compensates for network latency during cross-platform transfers."
3. **`CONF_MF_UNJOIN_DELAY`** — "unjoin" is protocol jargon. UI label "Source speaker release delay (seconds)" + helper.
4. **`CONF_MF_PING_PONG_WINDOW`** — leaks internal algorithm name. UI label "Return-trip suppression window (seconds)" + helper "Suppress the return leg when someone briefly walks away and comes back."
5. **`CONF_MF_VERIFY_DELAY`** — acceptable but could be "Post-transfer verification delay (seconds)".
6. **Existing entity names good:** `Music Following Health`, `Music Following Anomaly`, `Music Following Transfers Today`, `Music Following Active Rooms`, `Music Following Last Transfer` — all pass legibility.
7. **`CONF_MUSIC_ON_ARRIVAL_START`** — dangerous label if C7 stub is not fixed: implies functional behavior. Either implement (D9 option a) or DELETE THE OPTION from options-flow (D9 option b). Do NOT leave the toggle visible if it does nothing.
8. **NEW additions from plan — label directives:**
   - `CONF_MF_SLEEP_SUPPRESS` → label "Do not transfer music while sleeping" (not "Sleep suppress").
   - `CONF_MF_NIGHT_SUPPRESS_MODE` → label "Night-mode transfer policy" with options "off" / "own bedroom only" / "block all" (avoid `dwell_only` jargon).
   - `room_media_volume_scale` → label "Speaker loudness calibration (0.5-1.5)" with helper "Adjust if this room's speaker is noticeably louder/quieter than others at the same volume level."

**Add a new deliverable D0.5 — Labels + Helper Text pass** for MF surface. Scoped identically to v4.7.6.1 prior art. Tier 1.

---

## 5. Device grouping (operator directive #3)

Already correct: all five MF diagnostic sensors + the CM switch entity attach to `URA: Music Following Coordinator` device via `_music_following_device_info()` (`sensor.py:5873`). Analogous to DPM sensors moved to HVAC Coordinator device in v4.7.7.

**No device changes needed for existing sensors.** New sensors from this plan MUST inherit `_music_following_device_info()`:
- D1 last-skip-reason attributes → add to existing `MusicFollowingLastTransferSensor` (sensor.py:215) — do NOT create a new entity.
- D5 per-person switches → NEW switches. **Question: which device?** Two valid choices — Music Following Coordinator device (co-locates with the feature) OR the Person device (co-locates with the person). Prior art: `switch.py` already puts the MF coordinator enable-switch on the coordinator device. **Recommend: Person device** — the switch is a per-person preference; putting it on the coordinator device forces 5 switches into one device card with no context. Cite prior art in D0 design doc; if no Person device exists yet, put on Music Following Coordinator device and note the future migration.
- D11 per-room volume-scale → this is a room-level knob, attach to the ROOM device (same as `room_media_player`). Do NOT put on the MF coordinator device.

---

## 6. Observability + controls (operator directive #4)

Design the full observability story rather than per-bug patches.

### Sensors / attributes surface (post-plan)
Existing sensors (5 on MF Coord device): Health, Anomaly, Transfers Today, Active Rooms, Last Transfer.

**Recommended state after this cycle (no new sensors, extended attrs):**

| Sensor | Attributes to add |
|---|---|
| `MusicFollowingLastTransferSensor` | `last_skip_reason`, `last_skip_from_room`, `last_skip_to_room`, `last_skip_time` (D1, D8) |
| `MusicFollowingHealthSensor` | `sleep_suppressed_today`, `source_has_others_today`, `target_unavailable_today`, `stale_transition_today` (D1, D2, D3, D6). Extend `_TRANSFER_KEYS` visibility. |
| `MusicFollowingActiveRoomsSensor` | already covers `_active_groups`. No change. |
| `MusicFollowingAnomalySensor` | no change; anomaly detector already wired for both metrics. |

**Do NOT add a `sensor.music_following_last_skip_reason` (plan D1 hedges with "or extend `_last_transfer_result`").** Prefer attribute extension on existing sensor — fewer entities, HA UX best practice.

### Controls surface

| Control | Type | Device | Purpose | Deliverable |
|---|---|---|---|---|
| MF Coordinator enabled | Switch entity (exists) | MF Coord | Master enable | REUSED |
| MF anomaly sensitivity | Select entity (via CONF_MUSIC_ANOMALY_SENSITIVITY, exists in options-flow) | MF Coord | Anomaly tuning | REUSED |
| MF timing knobs (cooldown / ping-pong window / verify delay / unjoin delay / position offset / min confidence / BLE distance) | **config-flow FIELDS** (not Number entities), per CLAUDE.md "Number Fields = Form Fields" | (options-flow only) | Advanced tuning | REUSED |
| MF sleep-suppress | **config-flow FIELD** (bool) | (options-flow only) | Sleep gate | NEW (D2) |
| MF night-suppress mode | **config-flow FIELD** (select) | (options-flow only) | Night gate | NEW (D2) |
| Per-person MF follow | Switch entity (RestoreEntity) | Person device (preferred) or MF Coord | DND per person | NEW (D5) |
| Per-room speaker loudness calibration | **config-flow FIELD** (float 0.5-1.5) in room options-flow | (room options-flow) | Cross-platform vol normalization | NEW (D11) |

**Rationale for Number-Field vs Number-Entity:** Timing knobs / gates / calibration values are set once and rarely adjusted. Per-person DND is a runtime user-toggleable state — Switch entity is appropriate. Aligns with the "Number Fields = Form Fields" feedback (2026-06-02).

---

## 7. Tier classification

Per CLAUDE.md standing policy (Tier 2-DB three framing-disjoint reviews for all regression-prone work), MF touches: presence signals, house-state, media actuation, and cross-coordinator gates (safety/security/arrival). Justification for elevation:

- **Trust-hierarchy ripple**: house-state ↔ MF, presence ↔ MF (via TransitionDetector), occupancy-substrate ↔ MF.
- **Actuation on shared devices** (media_player) where a wrong path = user-visible failure (music disappears / blasts wrong speaker).
- **Cross-coordinator signal-subscription lifecycle** — subscribing to `SIGNAL_HOUSE_STATE_CHANGED` at coord level is a Bug Class #50 (substrate sub clobbering) risk if not done inside the standard `_unsub_listeners` pattern already used at L181-205.

**Recommended tier per deliverable:**

| Deliverable | Tier |
|---|---|
| D0 (design doc) | Tier 1 |
| D0.5 (labels + helper text) | Tier 1 |
| D1 (silent-actuator visibility) | Tier 1 hotfix — small blast radius, additive |
| D2 (sleep + night gating) | **Tier 2-DB** — house-state ripple |
| D3 (guest-in-source guard) | **Tier 2-DB** — presence/occupancy ripple |
| D4 (ping-pong counter + same-room stat) | Tier 1 |
| D5 (per-person switches) | Tier 1 |
| D6 (concurrency + staleness + reload) | **Tier 2-DB** — lock semantics + reload symmetry |
| D7 (target picker platform-preference) | Tier 1 |
| D8 (skip-reason attribute surface) | Tier 1 (bundle with D1) |
| D9 (arrival-stub decision) | Tier 1 (deprecation-only) |
| D10 (TTS coordination) | **DEFER** — depends on non-existent signal |
| D11 (per-room volume calibration) | Tier 1 |
| D12 (verify-delay conditional) | Tier 1 |

### Falsifiable invariant for Tier 2-DB reviews (extended from plan)

Plan states: *"MF SHALL NOT modify source volume, call `unjoin`, or call `play_media`/`join`/`transfer_queue` if the resulting user experience is 'music disappears from source without appearing at target.'"* — **keep this**.

Add second invariant for D2/D3:

> **During `HouseState.SLEEP`, or when the source room has another identified/unidentified occupant besides the transitioning person, MF SHALL NOT call any actuation service on any media_player.**

Reviewer D (adversarial completeness) must state and try to falsify BOTH invariants across every reachable code path (including boot-storm, config-reload, options-update mid-transfer).

---

## 8. Revised build order

Plan sequenced D0 → D1 → D4+D8 → D2 → D3 → (D5, D7, D11, D12) → D6 → D9 → (D10 deferred). Revise as follows:

1. **D0** design doc + **D0.5 labels/helper text pass** (bundle — Tier 1).
2. **D1** silent-actuator visibility (adds `room_media_player` to `_ACTUATOR_SINGLE_KEYS` at `sensor.py:1646`; adds `target_unavailable` stat + pre-flight guard) — **Tier 1 hotfix, do first for correctness win**.
3. **D4** ping-pong counter + same-room stat + **D8** skip-reason attributes — bundle Tier 1, tiny.
4. **D2** sleep + night gating — Tier 2-DB, highest livability value.
5. **D6** concurrency + reload symmetry rework — Tier 2-DB (do before D3 because D3 introduces additional predicate reads inside `_execute_transfer` that would collide with unfixed lock semantics).
6. **D3** guest-in-source-room guard — Tier 2-DB.
7. **D9** arrival-stub decision (recommend option b: remove CONF, log DEBUG only). Tier 1.
8. **D5** per-person Switch entities — Tier 1. Attach to Person device.
9. **D7** target picker platform-preference — Tier 1.
10. **D11** per-room volume calibration — Tier 1, room-config-flow field.
11. **D12** verify-delay conditional — Tier 1.
12. **D10** TTS coordination — dropped from cycle; file as backlog.

### Additions to the plan

- **D0.5 Labels + helper text pass** — as detailed in §4.
- **D3.5 Egress-state diagnostic** — when transferring into a room with active egress hold, log INFO. No suppression; just visibility. Bundle with D8.

### Drops from the plan

- **D10 TTS coordination** — drop from build (retain in backlog). Depends on a signal that does not exist; building the signal is a separate cycle.

---

## 9. Acceptance criteria review for top deliverables

Plan's acceptance criteria are generally testable. Enhancements:

### D1
- **Add:** `Live` — before deploy, snapshot `sensor.ura_music_following_transfers_today` value; post-deploy after intentionally turning off master bedroom Sonos and walking kitchen→master, verify value did NOT increment AND health sensor shows `target_unavailable_today=1`.
- **Add:** verify `sensor.<room>_unavailable_entities` for master bedroom shows the Sonos in `unavailable_actuators`.

### D2
- **Add:** invariant test — mock `SIGNAL_HOUSE_STATE_CHANGED` to SLEEP, fire a transition, assert zero service calls to `media_player.*`.
- **Add:** Live — overnight scan: `grep "Starting transfer" home-assistant.log` between sleep_start and sleep_end must return zero lines.
- **Add:** reload-symmetry test — CM options reload flipping `CONF_MF_SLEEP_SUPPRESS` off then on must not leak subscriptions (Bug Class #50 guard).

### D3
- **Add:** cite the exact `OccupancySubstrate` API to be called before build (plan says "reuse … predicate" without naming it).
- **Add:** covered by test: solo-occupant transition still transfers.

### D6
- **Add:** per plan's own guidance, three framing-disjoint reviews. Framings recommended: A = lock semantics + stat correctness; B = reload/teardown symmetry + `MusicFollowing.async_teardown()` ordering; C = interaction with D2/D3 predicates (do gate reads happen INSIDE or OUTSIDE the lock?).

---

## 10. Biggest risks (adversarial completeness pre-pass)

1. **Bug Class #50 recurrence.** D2's `SIGNAL_HOUSE_STATE_CHANGED` subscription MUST use the existing `self._unsub_listeners.append(async_dispatcher_connect(...))` pattern at coord L181-205. Any codepath that rebuilds subscriptions periodically (as the substrate did) will clobber MF's sub. Add explicit test.
2. **Reload-symmetry: D2 gate state.** `CONF_MF_SLEEP_SUPPRESS` and `CONF_MF_NIGHT_SUPPRESS_MODE` will live in the CM entry options. On reload, the coordinator is re-instantiated but the standalone `MusicFollowing` singleton is preserved (C5). New gate values must reach the standalone class — either push into `_music_following` at setup, or read live via a callback. Prefer the setup-push pattern used at coord L121-122; add a re-push on options-update.
3. **D5 restore hazard.** Bug Class #52 (RestoreEntity `unavailable` → OFF coercion) — the per-person switch must guard against restoring `unavailable` as OFF. Plan mentions this correctly; keep the guard in review checklist.
4. **D3 predicate under lock.** If D3 reads `OccupancySubstrate` INSIDE the transfer lock, and substrate reads block on presence-coord state, a slow substrate can serialize all transitions. Test that predicate reads are non-blocking property reads, not awaits into `presence_coordinator.data`.
5. **D2 transition edges (state flap).** House-state can flap SLEEP → HOME_NIGHT → SLEEP during a partner-walks-to-bathroom scenario at 3am. MF must not act on the transient HOME_NIGHT window if it's <N seconds. Bug Class #45 (state-flap in aggregators). Add a debounce or trust `HouseStateMachine`'s own minimum-dwell (verified at `house_state.py:93` — `HouseState.SLEEP: 600` = 10 min minimum).
6. **D1 blast radius on room device unavailable-sensor.** Adding `room_media_player` to `_ACTUATOR_SINGLE_KEYS` means every room now reports it in `unavailable_entities` when the media_player is dead — that flips `sensor.<room>_unavailable_entities` non-zero for rooms with a dead speaker but healthy lights. Notification-Manager may trigger on the delta. Coordinate with NM and add release-note guidance.

---

## 11. Files affected (revised, absolute paths)

- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/music_following.py` — D1, D3, D4, D6, D7, D11, D12
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/domain_coordinators/music_following.py` — D1, D2, D5, D6, D8, D9
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/const.py` — D2 (2 new CONF), D9 (deprecation), D11 (1 new CONF)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/config_flow.py` — D2, D9, D11 (room-level), D0.5 labels
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/switch.py` — D5 (per-person switches)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/sensor.py` — D1 (`_ACTUATOR_SINGLE_KEYS` at L1646; `MusicFollowingLastTransferSensor` attribute extension L215; `MusicFollowingHealthSensor` attribute extension)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/transitions.py` — D4 (ping-pong hook back into MF)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/__init__.py` — D6 (options-flow update listener)
- `/Users/okosisi/Code/universal-room-automation/custom_components/universal_room_automation/strings.json` + `translations/en.json` — D0.5
- `/Users/okosisi/Code/universal-room-automation/quality/tests/test_music_following.py` + `test_music_following_coordinator.py` — every deliverable
- `/Users/okosisi/Code/universal-room-automation/docs/Coordinator/MUSIC_FOLLOWING.md` — D0 (NEW)
- `/Users/okosisi/Code/universal-room-automation/docs/QUALITY_CONTEXT.md` — add subclass note under #53 for MF ping-pong counter

---

## 12. Verdict

Plan is **structurally sound and worth building** with the revisions above. All 20 findings still valid at HEAD; the plan is not stale. Three revisions gate go-ahead:

1. Add missing institutional cites (§1 gaps 1-4).
2. Split D0 into D0 (design doc) + D0.5 (labels + helper text) — visible operator win, small.
3. Adopt revised build order (§8) — do D6 before D3 to reduce lock-semantics collision risk.

Once done, D1+D4+D8+D0.5 can ship as a Tier-1 hotfix bundle within days; D2, D3, D6 each get full Tier 2-DB three framing-disjoint reviews per standing policy.
