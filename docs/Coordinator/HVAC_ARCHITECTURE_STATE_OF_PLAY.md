# HVAC — Architecture State of Play (READ FIRST)

**Status:** forensic snapshot of `develop` @`5072deaaf` (2026-09-26 ~02:30 CDT) + live HA reads the same night.
**W1-A Stage A SHIPPED v5.103.16 2026-09-26 (behaviour-neutral write governance; live-validated, `docs/readmes/README_v5.103.16.md`) — see §4.1 (new `emit_set_hvac_mode` funnel), §4.3 (`climate_write` ledger row).
**W1-B SHIPPED v5.103.18 2026-09-27 — the S1 "Don't fight manual" guard (v3.8.0) is REPLACED by the four-gate rule in §9e (person-protected hold / arrester grace-compromise / arrester disabled / live borrow); borrow returns are presets-only; immune holds + TAO persist across restart and reload; the arrester defers to live borrows at timer fire; the excursion kill switch is retired. Precedence rulings D13/D48/D49/D50/D52 in §9e. Read §9e before anything in §6, §7 or §9.1.** Plan `docs/planning/PLANNING_hvac_w1b_thermostat_definition.md` (decisions 1-52), README `docs/readmes/README_v5.103.18.md`.
**v5.103.19 (built 2026-09-27, `feature/hvac-night-tail-follows-sleep`) — D8 night tail-holds follow house Sleep/Waking (`HVAC_NIGHT_HOLD_STATES`), no longer `home_night`; `FAN_TRUST_STATES` untouched. See §3.1 / §3.3.** Plan `docs/planning/PLANNING_hvac_night_tail_follows_sleep.md` (B only; C parked).
**v5.103.20 (built 2026-09-28, `feature/hvac-fast-occupancy-response`, NOT deployed — Tier 3 checkpoint pending) — HVAC FAST OCCUPANCY RESPONSE: (D1) HVAC's own EVIDENCE release clock in `home_day`/`home_evening` (`ROOM_TYPE_HVAC_HOLD` re-valued per operator rulings R1/R2: closet/infra 60, generic/utility/media/garage 120, bath/common 180, bedroom 240; counted from the room's last evidence, NOT the lighting timeout) with the v5.103.19 machine kept as a SHADOW on the frozen `ROOM_TYPE_HVAC_TAIL_LEGACY` (night = shadow OR evidence; `home_night`/`guest`/`arriving`/`away` byte-identical); (D2) event-driven ZONE-SCOPED fast runs on room-refresh evidence (entry) and an exact-release exit timer (release + grace + 2 s), kill switch `switch.ura_hvac_coordinator_31_fast_room_response`; (D5) entry TRANSIT FILTER on the away→home edge driven by knob 47 (default 1 min; the v4.2.2 lighting-session dwell is RETIRED) with a pending-arm preset hold. **Fix-up round 1 (2026-09-28, operator rulings R4–R8/O2):** pending-hold spell capped at `HVAC_PENDING_HOLD_CAP_S` 600 s (`pending_hold_capped` row); the same-room return window is knob 52 `52 · Return Window (min)` (default 10 per post-GO ruling R9 — only the part above the 5-min grace protects; 0 = off); the quick-return alarm is shown to users as "Early return alert" (R10); per-room "Skip entry wait" (climate step); fast ENTRY runs in ALL house states (outcome unchanged, arrives faster); the shadow night tail is NOT carried across a night→evidence crossing (D-M2 overruled). Plan `docs/planning/PLANNING_hvac_fast_occupancy_response.md` REV 7 + §18 fix-up 1; README `docs/readmes/README_v5.103.20.md`. §2 / §3.1 / §3.2 / §8 / §9.5 / §9c / §9d updated below.**
**v5.103.23 (built 2026-09-29, `feature/hvac-w1-w2-finish`, NOT deployed — Tier 2-DB + 4th D review) — HVAC W1/W2 finish.**
- **Part A, "the person interrupts; we end and revert":**
  - A person's change within a manual hold is now detected: `classify_manual_setpoint_change`, both states `heat_cool`, changed legs only, compared with URA's last 4 `set_temperature` values from a read-only record in `emit_set_temperature` (ruling Q1).
  - A person's change ends a live BANKING / PREHEAT / ownerless COMPROMISE borrow with NO write (`human_interrupt`, restore_ok None) and supersedes an arrester episode in flight. It re-dispatches against ONE reference preset per case (a pre-arrival pre-cool uses the house's ARRIVAL target — Q7, fix-up 1: sleep in sleep/waking, else home).
  - A latch blocks S12/S13 begins until the zone leaves manual (Q3).
  - S4 never pins `manual`; the boot audit never pins a NUDGE `manual` (D6).
- **Part B:**
  - Pre-arrival pre-cool borrows (`caller_site S12_pre_arrival`) end before S1 on HVAC arrival / timeout / interrupt / ZI off / max age.
  - One write, from the baseline; the foreign-row guard applies at S12 and S13.
  - Knob 35 `Pre-Arrival Window (min)`, 5–110.
- **Part C:** C3 only — the stuck-occupancy clock is not reset while a room reloads.
- Plan `docs/planning/PLANNING_hvac_w1_w2_finish.md` REV 2 + Builder notes; README `docs/readmes/README_v5.103.23.md`.
- §3.2 / §4.2 / §6 / §7 / §9.4 / §9e / §10 C28–C29 updated below.
- **Fix-up round 1 (2026-09-29):**
  - Q7 is now the ARRIVAL target (Home unless the house sleeps; never Away).
  - The latch is persisted (`__interrupt_latch`) and survives unavailable flaps.
  - The compromise post-write race is closed.
  - Pre-arrival: spent-episode bound, HVAC-off / master-off / removed-zone ends.
  - See §9e and review record `docs/reviews/code-review/v5.103.23_hvac_w1_w2_finish.md`.
- **Fix-up round 2 (2026-09-29):**
  - The latch discharge is LEVEL-triggered (any readable named non-manual state, incl. the first event after boot), checked every full pass; latches of unmapped thermostats are pruned.
  - A person-interrupted or master-off pre-arrival also spends the arrival episode.
  - An ended pre-arrival always takes the arrival reference, even over an in-flight episode (incl. the startup audit).
**v5.103.24 (built 2026-09-29, `feature/hvac-batch-d`, NOT deployed — Tier 2) — Batch D.** README `docs/readmes/README_v5.103.24.md`.
- **Fan Mode (operator ruling option C):** one per-room `select.<room>_fan_mode` (`room_fan_mode` in the room entry's options: Follow thermostat / Room temperature / Off) feeds `const.fan_owner` (hvac / room / None). It is the ONE rule for every HVAC-tier fan writer (FanController sites, zone vacancy sweep, pre-arrival fans), the room tier and the fan recheck. It replaces "Enable HVAC-Managed Fans" + "Comfort Fan Control" (one-time migration; legacy keys readable one release). See §4.2b.
- **Unreadable thermostat:** the heat_cool enforcer (B1) and S1 do not write while the climate entity is `unavailable` / `unknown`. There is one INFO line and one `climate_write_held_unreadable` row per outage episode (§4.2).
- **INFO-1 (ruling B):** a nudge whose underlying non-nudge borrow a person ended (D13 + D-L3) restores the zone's CURRENT S1 target preset (the arrival target for a pre-arrival), presets only; S6 is skipped (§4.2, §9e).
- **Folded in:** HVAC-ARRESTER-EPISODE-CANCELS-AC-RESET-RESTORE-1 (§7).

**2026-09-28 (`feature/hvac-labels-and-timer-attrs`, not deployed) — display-only: zone `away_due_at` (§3.2), arrester `grace_until` / `compromise_until` (§7); label renames "Wait for Presence" / "Compliance Presence Wait" / "Weather Adjust Delay/Margin" (no behaviour change, §8).**
**Scope:** everything URA does with the thermostats — decide, write, borrow/return, read back — and the occupancy
model that drives it. Covers releases v5.103.0 → v5.103.18.
**Owner rule:** the operator (2026-09-26): *"every agent used in the rest of the arc reads [this] first completely
before doing a damned thing — to prevent drift and avoid compaction-driven errors."*

---

## 0. How to use this doc

1. **Read it completely before planning, building, reviewing or diagnosing anything in the HVAC arc.** Planners cite
   it in "Institutional context verified"; reviewers check plans against §4–§9 and the §10 corrections ledger.
2. **Precedence.** For the areas it covers, this doc supersedes: the 2026-01 `HVAC_COORDINATOR_DESIGN.md`, the operator
   `HVAC_COORDINATOR_MANUAL.md`, `HVAC_COORDINATOR_DESIGN_EXTENSION_2026_09.md`, planning docs, READMEs, card text and
   memory files — *except* where current code says otherwise. **Code at the cited file:line is the only authority;**
   if code and this doc disagree, the code wins and this doc is wrong — fix it in the same turn.
3. **Every claim here is cited** (file:line on `develop`, commit, or a dated live measurement). Lines marked
   **UNVERIFIED** were not proven; do not build on them without verifying.
4. **Update discipline.** Any HVAC ship, correction, or refuted claim updates this doc in the same commit (bump the
   header snapshot). A correction goes into §10 — never delete the wrong claim, record it with its refutation.
5. Paths: `hvac*.py` = `custom_components/universal_room_automation/domain_coordinators/`. `ha_carrier` =
   `/config/custom_components/ha_carrier/` (Samba: `/Users/okosisi/ha-config/custom_components/ha_carrier/`), v2.28.4.

---

## 1. One-page summary — the system as it runs TODAY (2026-09-26)

- **Hardware:** 3 Bryant/Carrier Infinity zones via `ha_carrier` (cloud + websocket):
  `climate.thermostat_bryant_wifi_studyb_zone_1` (zone_1 "Entertainment + Master Suite", 4-ton),
  `climate.up_hallway_zone_2` (zone_2 "Upstairs", 3-ton), `climate.back_hallway_zone_3` (zone_3 "Back Hallway", 3-ton).
  `ha_carrier` option **`infinite_holds: True`** (live config entry) → every hold URA or a human places, *including
  `manual`*, never expires on the thermostat (`climate.py:383-396`).
- **Decision loop:** one decision cycle every **5 min** (`HVAC_DECISION_TICK`, `hvac_const.py:13`). Extra cycles only on
  house-state change, pre-arrival, boot-settle release. **Room occupancy does NOT trigger a cycle** (§2).
- **Control intent:** drive zones by **named presets** (home / away / sleep / wake / vacation) whose setpoints are the
  Bryant comfort profiles; raw setpoints only for sanctioned *borrows* (nudge, compromise, banking, preheat, egress).
- **Occupancy:** HVAC has its **own** occupancy (`RoomCondition.hvac_occupied`, v5.103.7) with per-room-type tail-holds,
  hallway circulation exclusion, zone rollup `any_room_hvac_occupied`, and a shared retreat gate
  `conditioning_retreat_ok` = *established AND fused-empty* (reset-only backstop). Night retreat of empty zones at the
  **preset** layer is LIVE; the **setpoint** layer (D9 compose-away / Custom Preset Ranges) is DORMANT
  (`switch.ura_hvac_coordinator_guest_mode_actuation` = off).
- **Biggest live defect (measured §9.1, corrected C20):** after a URA borrow returns, a genuine manual hold appears on the
  Carrier side (both status and config feeds read manual) at URA's own values; URA books it as a human override at zero
  delta, the arrester declines, S1 locks itself out, and `infinite_holds` keeps it — 1.5–11 h strands. Most likely
  cause: the return's raw setpoint write + a discarded/reverted named pin (UNVERIFIED).
- **Observability gap:** `ura_activity_log` records preset writes but **never** `set_temperature` or `set_hvac_mode`;
  borrow/nudge writes live only in `ac_ramp_events` / `hvac_excursion_events` / INFO logs (§4.3). This gap caused a
  wrong exoneration of URA (§10).
- **Shipped 2026-09-26:** v5.103.15 live-room establishment (merge `a961d8870`, release v5.103.15; live validation 4 PASS / 2 pending — `docs/readmes/README_v5.103.15.md`).
- **Approved arc (§11):** W1 thermostat-definition abstraction (per-BRAND strategy) → W2 occupancy truth → W3 energy
  HVAC → W4 closure.

---

## 2. Decision loop & timing (verified)

| Trigger | Site | Notes |
|---|---|---|
| Periodic tick, 5 min | `hvac.py:1356-1360` `async_track_time_interval(..., HVAC_DECISION_TICK)`; const `hvac_const.py:13` | "rung-1 module const, cloud API call-rate bound — change requires review" |
| Initial cycle at start | `hvac.py:1363` | |
| Boot-settle release kick (1 s) | `hvac.py:1539-1547` `async_call_later(..., 1, self._async_decision_cycle)` | only when boot-settle suppressed ≥1 cycle |
| House-state change | `hvac.py:3260` (`_handle_house_state_changed`, subscribed `hvac.py:1140`; lines re-verified 2026-09-26 after v5.103.16) | |
| Pre-arrival | `hvac.py:4186` (`_handle_person_arriving`, subscribed `hvac.py:1196`) | |
| **Room HVAC-evidence change (v5.103.20 D2)** | `hvac.py` `_on_room_refresh` (a `DataUpdateCoordinator.async_add_listener` on every ROOM coordinator, attached at `async_setup` via `_setup_fast_path_listeners`; lifecycle via `SIGNAL_ROOM_ENTRY_LIFECYCLE`) → `_async_zone_fast_run(zone, "fast_entry")` — ZONE-SCOPED (`update_room_conditions(zone_ids={Z})` + `_apply_house_state_presets(zone_filter={Z})`), serialised on `_decision_cycle_lock`, 60 s per-zone limiter (exempt when the last S1 write was `away`), write ceiling 6/h + runaway 30/h → tick-only until local midnight. **Exit**: per-zone `async_call_later` at `zone_release_at + grace + 2 s` → `fast_exit` (one-shot per `(zone, release)`). Kill switch `31 · Fast Room Response` — OFF stops the fast path ONLY (runs + exit timers); D1/D5/back-fill/nudge seed stay on the tick. Fast ENTRY runs in EVERY house state (ruling R7: the run computes the periodic outcome for that state — same outcome, sooner); exit timers only in evidence/night states. Before v5.103.20 there was NO occupancy trigger (dispatcher subscriptions are only HOUSE_STATE, ENERGY_CONSTRAINT, PERSON_ARRIVING, SAFETY_HAZARD, ZM_ZONES_UPDATED). |

Consequences:
- **Entry latency (UPDATED v5.103.20):** a fast run starts within `HVAC_FAST_PATH_SLA_S` (45 s) of the room's evidence refresh (usually < 5 s). With knob 47 = 1 an away-edge entry waits 60 s of persisted evidence first (D5, §9d). HISTORICAL (C18, before v5.103.20): 5–10 min — the first tick that saw occupancy also started the LIGHTING dwell clock (`current_session_start`) and skipped; dwell 0 (operator 2026-09-26) made it "wait for the next tick". The lighting-session dwell skip is now RETIRED (knob 47 drives D5).
- The **occupancy fast path was DESIGNED, never built**: commit `82620357a` names `HVAC_DECISION_TICK=5min` as "a hard
  floor on fast-in ... needs event-driven path"; `HVAC-SUPPLE-SEQUENCE-1` step 5 lists it as conditional. It lives in W2.
- Carrier cloud refresh after a write takes **42–79 s** (`hvac_override.py:147-150`); arrester temp-suppression is
  **15 s for temperature writes** (`SUPPRESS_TTL_SECONDS`, `hvac_override.py:133`, raised 5 -> 15 by HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1, 2026-09-26; measured Carrier echo lag 5.3-7.5 s, human-manual floor > 60 s) and **120 s for preset writes** (`SUPPRESS_TTL_SECONDS_PRESET`) — see C17, C23 — URA's own write echoes that arrive later than the window are still booked as overrides.

---

## 3. Occupancy model — room → zone → retreat

### 3.1 Room producer (`hvac_zones.py`, `ZoneManager.update_room_conditions`)
| Piece | Site | Live? |
|---|---|---|
| `RoomCondition.hvac_occupied` sibling of `.occupied` (lighting signal NOT swapped) | producer loop, `_hvac_seen.add` at `hvac_zones.py:988` | LIVE (v5.103.7) |
| Per-room-type EVIDENCE hold (day) `ROOM_TYPE_HVAC_HOLD` (v5.103.20) | `const.py` — closet/infra 60 s, generic/utility/media/garage 120, bathroom/common 180, bedroom 240, **hallway 0**; counted from the room's LAST HVAC EVIDENCE (`coordinator.get_last_hvac_evidence_time`, the ONE stamp `_stamp_hvac_evidence` in `_async_update_data`: sensors / grace-hold / camera+BLE override verdict / Override Occupied; fan-demoted, failsafe and fan-recheck sources never stamp) — ONLY in `home_day`/`home_evening` (`HVAC_EVIDENCE_RULE_STATES`); OR-ed with the shadow in `sleep`/`waking`. The SHADOW (v5.103.19 machine, `_shadow_hvac_occupied`) still runs on every pass on the frozen `ROOM_TYPE_HVAC_TAIL_LEGACY` (bedroom 60, media 120, all else 60, hallway 0) and alone owns `_hvac_armed`/`_hvac_prev_state_occupied`/`_hvac_tail_until` | LIVE (v5.103.20 build) |
| Night tail-hold `ROOM_TYPE_HVAC_HOLD_NIGHT` (D8) | `const.py:1230-1242` — bedroom/media **30 min**, common 15, generic/bath/garage/utility 10, closet/infra 5, hallway 0. **Selected only in house `sleep` / `waking`** (`HVAC_NIGHT_HOLD_STATES`, `hvac_const.py`, v5.103.19 HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1); `home_night` (21:00 → Sleep) uses the DAY table. Before v5.103.19 it keyed on `FAN_TRUST_STATES` (incl. `home_night`), which is unchanged for fans/D7 | LIVE |
| Per-room override knobs `CONF_HVAC_VACANCY_HOLD[_NIGHT]`, night ≥ day clamp | `_effective_hvac_hold_seconds` `hvac_zones.py:977` (method; producer caller via `_compute_hvac_occupied`, `house_state` handed off at `hvac_zones.py:743`); display caller `binary_sensor.py:894` (`hvac_vacancy_hold_s` attr) | LIVE (v5.103.8 made them config-flow fields) |
| Hallway circulation exclusion (`hvac_occupied` always False, still marked seen) | `hvac_zones.py:650-665` (`arm_source="hallway_excluded"`) | LIVE — 7 hallways, 0 `on` rows in 7 d (v5.103.7 README write-back) |
| Coordinator-absent room → synthetic `RoomCondition(occupied=False, hvac_occupied=False)` | `hvac_zones.py:616-641` | pre-existing (Bug Class #43). **Hazard:** a reloading room reads "empty" (§9.4) |
| Per-room diagnostic `binary_sensor.<room>_<room>_hvac_occupied` (~43, doubled slug) with `established` attr | `binary_sensor.py:745`, `:911-916` | LIVE (v5.103.8) |

### 3.2 Zone rollup & retreat gate
| Piece | Site | Semantics |
|---|---|---|
| `zone.any_room_hvac_occupied` (fused) | producer; exposed `hvac_zones.py:751` on `sensor.ura_hvac_coordinator_zone_{n}_status` | OR over rooms' `hvac_occupied` |
| `away_due_at` attr (2026-09-28, HVAC-PUBLISH-ZONE-AWAY-DUE-AND-ARRESTER-TIMERS-1) | `hvac_zones.py` `_away_due_at_attr` → `zone_away_due_at(zone, grace)` = live `zone_release_at` + the LIVE grace the sensor passes in (`HVACCoordinator._exit_grace_seconds`: knob 48, or 49 under coast/shed); on `sensor.ura_hvac_coordinator_zone_{n}_status` | DISPLAY ONLY (no decision reads it). Due time of the exit (None once passed or while occupied), ISO local. "Occupied" includes a room still in its hold tail; also None when the release is unknown/unbounded. Equals the exit-timer due minus its 2 s slack |
| `is_zone_hvac_established(zone_id)` | `hvac_zones.py:1043` (all at `:1083`) | **v5.103.15 (live):** no transient (loading) room, ≥1 live room, and every live room LOADED + coordinator-present + seen; excluded rooms (disabled / SETUP_ERROR / MIGRATION_ERROR / SETUP_RETRY / removed / transient ≥ 300 s, sticky until LOADED) count toward nothing. Replaced the round-5 `all(zone.rooms)` revert `f88f4bc84` |
| `conditioning_retreat_ok(zone)` | `hvac_zones.py:1085`; delegate `HVACCoordinator._zone_conditioning_retreat_ok` `hvac.py:3830` | **established AND fused-empty**; person-trust only covers the *unestablished* post-reload gap (**reset-only backstop**, operator round-4 decision 2026-09-17). Never raises; fail-closed |
| Consumers of the gate | row-1 preset flip `hvac.py:2013`; D7 night-trust `hvac.py:2403`; D9 compose-away `hvac.py:2966`; F4 row-10 arrester comfort-delay **direct** `hvac_override.py:2319` (tri-state guard `:2304-2340`, raw fallback `:2336`) | all trust decisions |
| Consumers of establishment directly | `conditioning_retreat_ok` (`hvac_zones.py:1112`); `binary_sensor.py:914` (display) | `hvac.py:3820-3826 _is_zone_hvac_established` has **zero callers** (dead) |
| Readers that BYPASS the gate (read fused signal raw) | Lines re-verified 2026-09-29 on the W1/W2-finish branch: D5 energy-shed occupancy defer `hvac.py` ~2940-3000 (ledger `energy_shed_cap_deferred_occupied` ~2979); D6 stale failsafe `hvac.py` ~2755-2800 + `presence.py:2147-2159` (Source 4; Source 1 `:2098-2122`); `hvac_predict.py:583` (pre-cool F8), pre-heat F9 in `_execute_pre_heat`; `hvac_zones.py` ~964-985 `continuous_occupied_since` — **v5.103.23 C3: its reset is skipped while the zone is transient-blocked** (the back-fill in the same `else` is unchanged) | see §9.4 (carded `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`; C1/C2/C4 PARKED, plan Appendix A) |
| Zone entry dwell → **D5 ENTRY TRANSIT FILTER (v5.103.20)** | knob 47 `number.ura_hvac_coordinator_zone_entry_dwell` ("Entry wait", default **1** min, live value stays 0 until set — checkpoint) now drives `hvac_zones._d5_update`: in `home_day`/`home_evening`, a room in a zone whose last APPLIED S1 write was `away` (`_zone_away_edge`, not pre-arrival) arms only after W = 60 s of persisted evidence (episodes join across gaps ≤ min(hold, W)); while a room is pending and the zone is otherwise HVAC-empty S1 HOLDS the preset (`_pending_arm_hold_write`, a mirror of the row-1 transient hold; ledger `preset_change_suppressed` reason `pending_arm_hold`, one row per spell); a room that re-enters within the **Return Window** (knob 52 `number.ura_hvac_coordinator_52_return_window_min`, default 10 min per R9, 0 = off — fix-up 1 ruling R5) of a real evidence release (ev + hold, after an arm whose evidence spanned ≥ W) re-arms at once; a room with **"Skip entry wait"** (room options, climate step, ruling R6) never waits; a pending-hold spell is capped at `max(HVAC_PENDING_HOLD_CAP_S = 600 s, W + J)` (ruling R4 / fix-up 2 D-L2 — only chains of never-persisting episodes are cut; one `pending_hold_capped` row per spell; the spell closes on any tick whose S1 block is skipped). Knob 52 is ALSO on the HVAC settings form as "Return window (minutes)" (fix-up 2) The v4.2.2 LIGHTING-session dwell skip (`current_session_start`, the DENOMINATION DEFECT noted 2026-09-26) is **RETIRED** | LIVE (v5.103.20 build); card HVAC-ENTRY-DWELL-ROOM-CLOCK-1 folded |
| Vacancy grace | knob 48 `number.ura_hvac_coordinator_48_zone_vacancy_delay_minutes` = **5** live (2026-09-27 `.storage`; const default 15, `hvac_const.py`); knob 49 energy-saving = **5**. v5.103.20: on a fused-empty pass in evidence/night states `last_occupied_time` is BACK-FILLED to the exact release instant (max armed-room release), so the grace counts from the release; the exit timer fires at release + grace + 2 s | LIVE (verified 2026-09-27). Sizing probe `scripts/probes/hvac_vacancy_grace_probe.py` |

### 3.3 Live vs dormant
| Layer | State | Gate |
|---|---|---|
| Preset-layer retreat (row-1), incl. **night** retreat of empty zones | **LIVE** | `conditioning_retreat_ok` |
| D7 night-trust suppression (zone_persons home) — only when zone NOT cleared to retreat | **LIVE** | `hvac.py:2403` |
| D8 night tail-hold | **LIVE** — house `sleep` / `waking` only (v5.103.19) | `const.py:1230`; selector `hvac_zones.py` `_effective_hvac_hold_seconds` |
| D9 compose-away (Custom Preset Ranges setpoint layer), F2 throttle bypass, F4 | **DORMANT** — `switch.ura_hvac_coordinator_guest_mode_actuation` = off (13/13 recorded states 09-18→25); gate `hvac.py:2867` | blocked on `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` + `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` |

---

## 4. Thermostat I/O — writes, funnels, logging, reads

### 4.1 Funnels (`hvac_setpoint.py`)
| Funnel | Site | What it adds |
|---|---|---|
| `emit_set_temperature` | `hvac_setpoint.py:223-279` | freeze / comfort-delay gate, site/zone/reason plumbing. **Logs nothing durable** (only a `comfort_delay_deferred_write` row when a gate defers, `:108-159`) |
| `emit_set_preset_mode` | `hvac_setpoint.py:282-410` | **resume-then-pin** (v5.103.2): if the entity lists `resume` in `preset_modes` and `hold_activity == "manual"`, send `resume` then pin, with one retry (`:317-410`); capability check not vendor check (`:199-212`). D6 reason capture (`zone_id`+`reason` kwargs). Logs nothing durable itself |
| `emit_set_hvac_mode` | `hvac_setpoint.py` (W1-A Stage A, shipped v5.103.16) | Behaviour-neutral: NO gate, NO transform; required kwargs `site` / `zone_id` / `reason` / `blocking` (F3, F10); optional `excursion_id` forwarded from borrow tokens. Schedules ONE `climate_write` row per attempted wire call. Migrated the 7 raw sites (B1–B7). |

### 4.2 Write sites (verified by Explore audit 2026-09-25 against develop; spot-checked)
| Site | Verb(s) | Via funnel | Durable record |
|---|---|---|---|
| S1 house-state/occupancy preset `hvac.py:2674` | preset (+hidden resume) | yes | **`ura_activity_log` `preset_change`** (`hvac.py:2716-2748`), lockout `preset_change_locked_out` (`:2504-2519`) once per episode. **v5.103.24:** held while the zone's climate entity reads `unavailable`/`unknown` (`_climate_unreadable`, `hvac.py` ~3552; live state, not the cached `ZoneState`) |
| heat_cool enforcer `hvac.py:1926-1938` (B1, funnelled since W1-A) | hvac_mode | **no** | INFO only. **v5.103.24:** held while the climate entity reads `unavailable`/`unknown` (`hvac.py` ~2578; `HVAC_CLIMATE_UNREADABLE_STATES`, `hvac_const.py` ~513). One INFO + one `ura_activity_log` `climate_write_held_unreadable` row per outage EPISODE (opened on the first unreadable read, closed on the first readable one); the next readable tick writes as normal. Guard at the two sites, NOT in the funnels (W1-B constraint) |
| S10 DPM custom ranges `hvac.py:3046` | setpoints | yes | INFO only (dormant) |
| S3 arrester compromise `hvac_override.py:3393` | setpoints | yes | `hvac_excursion_events` |
| S4 arrester revert `_revert_override` (B4 mode + S4 preset) | mode + preset | yes (W1-A) | `hvac_excursion_events`. **v5.103.23 D2d:** the preset is the compromise snapshot only when it is NAMED, else the episode's `original_preset`; neither named → S4 skipped (`revert_no_named_preset`, restore_ok None). A task whose episode a person superseded stands down (generation check at start and before S4) |
| AC hard reset off/restore/retry/preset `hvac_override.py:3888/4006/4041/4113` | mode + preset | mode **no** | `ac_ramp_events` |
| **S5 soft-nudge start** `hvac_override.py:4423` | setpoints (+`nudge_size` to high) | yes | `ac_ramp_events` `nudge_started` |
| **S6/S7 nudge restore** `hvac_override.py:4595` (setpoints, no zone_id/reason) then `:4640` (preset, blocking) | setpoints then preset | yes | `ac_ramp_events` `nudge_restored` + settled verdict. **v5.103.24 (INFO-1, ruling B):** when a person's change ENDED the non-nudge borrow this nudge ran on top of (D13 + D-L3; recorded in `_handle_climate_change`, `_nudge_restore_reference`), S6 is SKIPPED and S7 pins the zone's CURRENT S1 target preset (`_resolve_reference(zone, None)`), or the ARRIVAL target for an `S12_pre_arrival` borrow (Q7). Presets only; reasons `soft_nudge_restore_s1_target` / `soft_nudge_restore_arrival_target`; no resolvable reference → no write. The record is dropped at the next nudge start and at teardown. S8/S9 unchanged |
| S8 cancel-nudge (button) `hvac_override.py:5815/5841` | setpoints + preset | yes | `ac_ramp_events` |
| S9 boot ramp audit `hvac_override.py:6221/6245` | setpoints + preset | yes | `ac_ramp_events` |
| Excursion lease-expiry auto-return `hvac_excursion.py:667` | preset | yes | non-nudge kinds only |
| S11 banking release `_release_banked_zones`; S12 pre-cool `_execute_zone_pre_cool` (begin, then `climate_write` site `S12_pre_cool`); S13 pre-heat `_execute_pre_heat` / `_return_preheat` | setpoints + preset | yes | `hvac_excursion_events`. **v5.103.23:** a pre-arrival S12 begins with `caller_site='S12_pre_arrival'`, writes ONCE from the baseline, and is ended by `async_end_pre_arrival_borrows` (triggers `pre_arrival_{arrived,timeout,interrupted,inactive,max_age}`, presets-only, no `_last_emitted_range` write). S11/S12/S13 write nothing for a returned token or a latched zone; S12/S13 never write over another live row (D4b) |
| Egress pause/resume `hvac_egress.py:683/779/795` | mode + preset | mode **no** | `hvac_excursion_events` |
| Optimizer `optimization.py:3546` (shadow by default) | any | — | `actuated` row, no entity_id |

### 4.2b Comfort fans — who owns them (v5.103.24, Batch D, operator ruling option C)
One per-room **Fan Mode** (`select.<room>_fan_mode`, key `room_fan_mode` in the room entry's options; reload-suppressed) feeds `const.fan_owner` — the ONE rule for every fan writer. Humidity/exhaust fans are out of scope (always room tier).

| Fan Mode | owner | HVAC tier (`hvac_fans` temp / sleep-onset / `turn_off_all_managed`; `hvac.py` zone sweep + pre-arrival fan off; `hvac_predict` pre-arrival fan on) | room tier (`automation` temp path, `actuator_reconciler`) | fan recheck (presence) |
|---|---|---|---|---|
| Follow thermostat (only offered in an HVAC zone) | `hvac` | runs it | stands down while HVAC runs the room; else runs it as Room temperature | yes |
| Room temperature | `room` | never | runs it | yes (FanController write registry; snapshot = physical state) |
| Off | None | never | never | never |

- `_room_fans` keeps every HVAC-zone fan room registered; it is the recheck's write registry.
- Every HVAC-tier write reads the Fan Mode LIVE at actuation (chokepoint `_set_fan_state` + per-site gates).
- Leaving Follow thermostat RELEASES tracking and never turns the fan off.
- Not gated: the smoke/CO safety stop.
- The legacy toggles (`hvac_coordination_enabled`, `fan_control_enabled`) were migrated once per room and stay readable for one release.
- Before v5.103.24 the HVAC tier read neither toggle. That is how a guest's fan (Guest Bedroom 2, 2026-09-28) was switched on at sleep onset.

### 4.3 Logging coverage — the answer to "do we record everything?": **YES post W1-A Stage A** (feature branch; ships next)

W1-A Stage A (behaviour-neutral) adds ONE `climate_write` row per attempted wire call in
`ura_activity_log` (action = `climate_write`, importance = `notable` → 30-d retention;
bypasses `ActivityLogger` dedup / signal / bus event per F4 so two identical writes 1 s
apart land as two rows). Row carries: `verb` / `site` / `zone_id` / `entity_id` / `reason`
/ `blocking` / `wire_ok` / `exc` / `excursion_id` / `values_before` (`preset_mode`,
`hold_activity`, setpoints, mode — captured SYNCHRONOUSLY before the wire await, F6) /
`values_after` (exact `service_data` sent, F12) / `ts_issued` / `ts_returned`. AI-rule
refusal expanded from 3 verbs to ALL `climate` services (D5-b). `optimization.py` shadow
climate actions remain OUT via `DYNAMIC_DOMAIN_ALLOWLIST` (reviewed escape, carded for
later). AST completeness lint (`test_hvac_climate_write_funnel_completeness.py`) enforces
no raw `climate` service call outside `hvac_setpoint.py`.

Pre-W1-A picture (for the reader tracing an older strand):

| Question | Where to look |
|---|---|
| Did URA change a preset? | `ura_activity_log` action `preset_change` (+ `preset_change_locked_out`, `override_detected`) |
| Did URA write setpoints / nudge / reset? | **`ac_ramp_events`** (nudge/reset kinds; 30-day retention `database.py:8526`) — zone_1 had 1,827 rows since 08-26 |
| Did a non-nudge borrow run/return? | `hvac_excursion_events` (nudge kinds excluded `hvac_excursion.py:1009`) |
| Did URA change hvac_mode? | INFO log only (not kept — log level WARNING) |
| Who changed the thermostat (recorder context)? | **Cannot tell** — every change, URA or human, arrives via the integration with no user/parent context (measured 2026-09-25) |
| Is `override_detected` proof of a human? | **No** — URA's own late echoes are booked as overrides (§2, §9.1) |

### 4.4 Read model — what URA believes about the thermostat
URA reads `preset_mode`, `target_temp_high/low`, `hold_activity` off the climate entity. `hold_activity` is read only by
resume-then-pin (`hvac_setpoint.py:171-222`, explicitly "NOT authoritative for anything else"). **Everything else —
lockout, arrester, S1 — trusts `preset_mode`**, which is the lagging field (§5).

---

## 5. Carrier/Bryant behaviour (verified in `ha_carrier` v2.28.4 source + live traces)

| Fact | Source |
|---|---|
| `preset_mode` = the **STATUS** feed's current activity (`_preset_mode` → `current_status_activity`) | `climate.py:158-172`, `:247` |
| The status feed's setpoints "go stale" — refreshed only by the periodic full poll; websocket keeps temperature current | integration comment `climate.py:222-229` |
| Displayed setpoints = the activity the **status** names (`setpoint_source = self._current_activity()`) → a stale "manual" status shows the **manual profile's** last-written setpoints (e.g. the nudge's 78/70) | `climate.py:230-240` |
| `hold_activity` = the **CONFIG** feed (`_config_zone.hold_activity`), updated promptly on writes | `climate.py:261-269` |
| `set_preset_mode(p)` → `set_config_hold(activity=p, hold_until)`; locally sets hold + status optimistically | `climate.py:418-438` |
| `set_preset_mode("resume")` → `resume_schedule`, then forced refresh | `climate.py:405-416` |
| `set_temperature(...)` → rewrites the **MANUAL activity profile** setpoints **and** sets `hold=MANUAL` | `climate.py:467-537` |
| `hold_until` = `None` (infinite) when `infinite_holds` option is True — **live: True** | `climate.py:383-396`; config entry options |
| **Upstream service** `ha_carrier.set_activity_setpoint` (NOT a local patch — added upstream by #427, Evan Weaver, 2026-08-31, `4d833486`; ships in v2.28.4 installed via HACS from `dahlb/ha_carrier` @285f915, so HACS updates keep it; the in-file word "PATCH" is the upstream author's): edits the CURRENT activity's setpoints **in place, no hold** (`set_config_activity`), does not touch hold/status activity. URA does not use it (candidate for W1: a no-hold nudge — but it mutates the named comfort profile itself, so an interrupted nudge leaves the profile changed; W1 must own restore/verification). Related upstream #408 (`c3b1ec07`, 2026-07-04): "read climate set points from config activity, not stale status" — the origin of the setpoint-vs-preset source split in §5 | `climate.py:91-103`, `:539-600` |
| `manual` is in `preset_modes` on all 3 zones (restoring `manual` is legal) | `PLANNING_hvac_governed_excursion.md` rev-6 note (live-verified 2026-08-21) |
| After a borrow returns, a later poll can deliver `preset_mode=manual` while `hold_activity` = home/sleep, sometimes with stale nudge setpoints; lasts until a vacancy/away write | recorder traces 09-21 12:53, 09-22 01:19, 09-24 19:57, 09-25 14:22 (§9.1). **Whether the physical thermostat was in manual: UNVERIFIED** |
| Remaining Bryant schedule on zone_1: one daily **6 AM Home 70–76** (operator screenshot 2026-09-25); others removed **2026-09-20 11:39 CDT** (dated from `next_activity_time` in recorder). Zones 2/3 still run 4-entry schedules (06/08/17-18/22). With infinite holds, a schedule only acts when no hold is active | recorder `next_activity_time` |
| Code comment "the operator does not use the Bryant schedule" (`hvac_setpoint.py:164-167`) | **SUPERSEDED 2026-09-26** — comment corrected in code. **WORKING ASSUMPTION (operator 2026-09-26):** Bryant schedules still exist (zone_1 reduced to one 06:00 Home entry; zones 2/3 untouched for now); intent is to reduce them so ONLY URA controls. Until then `resume` briefly hands a zone to a live vendor schedule before a pin lands — §10 C12 |

---

## 6. Borrow / excursion primitive + nudge / AC ramp

| Fact | Site |
|---|---|
| Primitive: `begin_excursion` snapshots pre-preset + pre-setpoints, persists `hvac_excursion_state` row | `hvac_excursion.py:766` |
| `return_excursion` is **bookkeeping only** — drops row, logs outcome, surfaces restore failure (`[GOVERNED BORROW RESTORE FAILED]` + per-episode NM latch). **It performs NO wire writes: each call site emits its own (a) set_temperature → (b) set_preset_mode → (c) set_hvac_mode** | `hvac_excursion.py:871-1040` (docstring `:886-888`) |
| Kinds: NUDGE, COMPROMISE, BANKING, PREHEAT, EGRESS_PAUSE (`HARD_RESET_PRESET_ASSERT` deliberately absent) | `hvac_excursion.py:94-104` |
| **Interruptible by a person (v5.103.23, ruling 2026-09-28):** BANKING (energy and pre-arrival), PREHEAT, and an OWNERLESS COMPROMISE row (no timer, token or in-flight apply) end on a person's change with NO write (`return_excursion(trigger="human_interrupt", restore_ok=None)`); an owned compromise is superseded by the arrester (D2c). NUDGE is not (D13) and EGRESS_PAUSE is not (Q2). Pure reads added to the primitive: `live_token_for(zone)` and `ExcursionToken.returned` — nothing else in `begin_excursion` / `return_excursion` changed | `hvac_override.py` `_handle_climate_change` D2 block; `hvac_excursion.py` `live_token_for` |
| Lease gate **stripped** (rev-6, 4× DO-NOT-SHIP: a stuck lease with no discharge is worse than the lockout it replaced) — do not rebuild it as designed. **2026-09-27:** its stated reason was that the S1 manual guard "protects [borrows] TODAY". With that guard superseded (§9e), W1-B replaces it with ONE S1-side READ of the existing borrow registry (`_row_present_and_fresh`, `hvac_excursion.py:562`), whose discharge is the row's own `stale_ts` bound + sweep + boot audit — no new lease, no change to borrow code | `PLANNING_hvac_governed_excursion.md` rev-6 banner; §9e |
| Boot audit clears NUDGE/BANKING rows (NUDGE restores snapshot preset first — **except a `manual` snapshot, v5.103.23 D6 / C29**) | `async_startup_excursion_audit` |
| **Excursion kill switch (`excursion_primitive_enabled`, v5.88.0 back-out "Restore thermostats after temporary changes") — RETIRED 2026-09-27 (W1-B decision 51, operator: "retire the knob; borrow records always written; no special case")** | Deleted from `hvac_excursion.py` / `hvac_const.py` / `hvac.py` / `__init__.py` / `config_flow.py` / `strings.json` / `en.json`; `primitive_enabled` attr dropped from the borrows sensor. Why: under §9e gate (e) reads the borrow row as the ONE borrow predicate; a begin-only kill switch produced no-row borrows S1 could not see (PREHEAT / pre-arrival), and the v5.88.0 back-out it existed for is no longer needed (single install, no back-compat) |
| Soft nudge: `check_ac_reset` each cycle (`hvac.py:1745`); start S5 raises `target_high += nudge_size` (live **1.5 °F**) for `nudge_duration` (live **2 min**; const default 5); restore S6 raw setpoints → S7 snapshot preset (unconditional, blocking); settled verdict at `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 180` (`hvac_const.py:672`) | `hvac_override.py:4339-4440`, `:4580-4650` |
| Nudge cadence ~25 min (hold + 240 s eval delay + samples) — matches observed overnight/midday rhythm | `hvac_const.py:665`; live eval delay 240 |
| Nudge runs only if ramp master ON (live options `hvac_ac_ramp_master_enabled: True`; const default False `hvac_const.py:571`), `switch.ura_hvac_coordinator_26_ac_nudge` ON (live), zone has `ac_load_sensor`, cooling, at/below setpoint, kWh above per-zone threshold (live zone_1 1.5, zones 2/3 2.2) | `hvac_override.py:3677-3845`; live numbers |
| Hard reset (mode off→on) budgets: live day 2 / night 2 / daily limit 2 / min interval 30 min | live numbers |
| Operator policy: **nudges stay ON** (2026-09-25) | chat |

---

## 7. Arrester, lockout, hold knobs — why nothing reclaims a zero-delta manual

**Arrester ↔ AC-reset interplay (fix/arrester-episode-keeps-ac-reset-restore, folded into v5.103.24 Batch D; line numbers below re-verified on `feature/hvac-batch-d`):** a new governed arrester episode (the three `_cancel_arrester_timers` call sites `hvac_override.py` ~2606 startup-audit stale-override branch, ~4261 `_handle_severe_override`, ~4335 `_handle_normal_override`) no longer cancels a pending AC hard-reset RESTORE timer (`_reset_timers`). The cancel helper (`_cancel_arrester_timers`, `hvac_override.py` ~7940) now scopes to grace + compromise only, mirroring `_defer_arrester_to_borrow` (~4152). Rationale: cancelling the reset restore inside the Carrier lag window after the reset's `off` write left the zone stranded off — the B1 heat_cool enforcer (`hvac.py` ~2578) would re-assert heat_cool within ~one `HVAC_DECISION_TICK` (5 min) plus Carrier lag, so pre-fix bound was ~5 min + lag on the periodic path (not indefinite, but well past the intended ~1 min restore). Legitimate `_reset_timers` cancel sites (teardown ~2667-2669, `ac_reset_enabled` setter ~3342-3353, fire-time pop in `_restore_after_reset` ~5223) still cancel it directly and are unaffected. Corollary: the reset's success-branch preset restore in `_verify_restore` (`hvac_override.py` ~5254; defer guard ~5367) now DEFERS the preset write when an arrester episode is armed on the zone (`_override_active` / `_grace_timers` / `_compromise_timers`) — the arrester's own revert owns the preset in that case; mode/setpoint restore already succeeded. `preset_restore_ok` column stays NULL on the deferred row; combined `restore_ok` reads True (mode-only success). Folded in after Batch B (v5.103.23) with no textual conflict; the same three callers (no new ones).



| Mechanism | Site | Effect on a manual hold sitting at the preset's own setpoints |
|---|---|---|
| S1 refuses to write a preset over `manual`: "Don't fight manual — that's the arrester's job" — **SUPERSEDED 2026-09-27 (§9e); REPLACED in v5.103.18 (2026-09-27)** | `hvac_preset.py:212-217`; S1 logs `preset_change_locked_out` `hvac.py:2484-2539`; only bypass = forced vacancy/runtime away `:2481-2483` | locked out until the zone leaves manual |
| Arrester reverts only if setpoints moved ≥ `OVERRIDE_NORMAL_DELTA` 1 °F (severe 3 °F); +1 °F under coast | `hvac_const.py:531-532`; `_handle_climate_change` | delta ≈ 0 → "within tolerance" → no revert |
| **Within-manual detection (v5.103.23 D1):** a change while ALREADY in manual is booked only when both states are `heat_cool`, all four legs are numeric, a leg changed, and no changed leg matches (±0.5 °F, inclusive) one of URA's last 4 `set_temperature` values for the entity (RAM record in `emit_set_temperature`, boot-seeded from rehydrated rows). Delta is measured on the CHANGED legs against ONE reference preset: A (BANKING/PREHEAT ended: the named pre-borrow preset; a pre-arrival pre-cool uses the house's ARRIVAL target `pre_arrival_reference_preset`, Q7), B (episode in flight: its original preset), C (plain / ownerless compromise: the house S1 target); a plain transition is unchanged. No resolvable reference → booked, not dispatched | `classify_manual_setpoint_change`; `_transition_is_human`; resolver registered by `HVACCoordinator` (`set_baseline_resolver`) | the arrester now also acts on a person fine-tuning an existing manual hold |
| Operator-immune hold (`CONF_HVAC_ARRESTER_IMMUNE_PERSONS`) sunset: next_activity / durable house state / 4 h | `hvac_const.py:189-198`; `hvac_override.py:713-811` | sunset hands back to the arrester — does NOT clear the hold (`:727-729`) |
| Temp Arrester Override switch (live off), max 6 h | `hvac_const.py:205`; `switch.py:2429-2468` | same — hands back only |
| Arrester timer end times (2026-09-28, display only) | `get_arrester_detail()["zones"][<zone name>]` `grace_until` / `compromise_until` (ISO local or None), stamped at the four arm sites (startup audit, severe, normal grace; compromise) via `_stamp_timer_end`; published only while the zone is still in `_grace_timers` / `_compromise_timers`, so every cancel/fire path retires them. After a restart `compromise_until` reads None even while a rehydrated COMPROMISE borrow row is live — there is no arrester timer then (the row is closed by the lease-expiry sweep, C26) | no decision reads them |
| Comfort Grace (live **20 min**; default 30) | `hvac_const.py:452-456` | grant expiry writes nothing (`hvac_override.py:2694-2716`) |
| Suppression windows: temp 15 s (raised from 5 by HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1, 2026-09-26) / preset 120 s vs Carrier observed 42–79 s (schedule: 30-min poll + 5-min post-write guard, C16) | `hvac_override.py:133`, `:173`; preset-window pass-through `:2468-2482` | URA's own late echo → `override_detected` — for kind="temp" only past 15 s, but for kind="preset" the mid-window passthrough books a fresh transition INTO `manual` at ANY time inside the 120 s window (the restore-echo residual, W1-B problem 1) |
| **Net (HISTORICAL — before v5.103.18):** no timeout releases the lockout; a URA-caused or stale `manual` at zero delta is **never reclaimed** except by a forced-away write. **Root cause (2026-09-27):** the guard assumed the arrester handles every manual, but the arrester declines URA-caused manuals at ~zero delta — so nobody owns them. W1-B fixes this at S1 (§9e) | — | operator 2026-09-25: *"Without that knob, why would we not override? arrester is an override."* |

---

## 8. Live switches & knob values (recorder latest non-unavailable, 2026-09-26 ~02:00)

| Entity / option | Value |
|---|---|
| `switch.ura_hvac_coordinator_enabled` / `_zone_intelligence` / `_zone_sweep` / `_override_arrester` | on / on / on / on |
| `switch.ura_hvac_coordinator_hvac_observation_mode` | off |
| `switch.ura_hvac_coordinator_guest_mode_actuation` (D9 / Custom Preset Ranges) | **off** |
| `switch.ura_hvac_coordinator_26_ac_nudge` / `_ac_reset` / `_ac_ramp_down_energy_aware`; option `hvac_ac_ramp_master_enabled` | on / on / on; True |
| `switch.ura_hvac_coordinator_temp_arrester_override` | off |
| `switch.ura_hvac_coordinator_hvac_d5_duty_cycle_enable`; D5 coast / shed / window | on; 75 % / 50 % / 20 min |
| `switch.ura_hvac_coordinator_hvac_consensus_defer_gate` (display name **"Wait for Presence"** since 2026-09-28; was "HVAC Consensus Defer Gate"; entity_id / unique_id unchanged) / `_pre_arrival_conditioning` / `_hvac_pre_conditioning` | on / on / on |
| `number.ura_hvac_coordinator_zone_entry_dwell` | **0** live (2026-09-27 `.storage`; v5.103.20 default 1 = D5 transit filter, checkpoint item) |
| vacancy delay / energy-saving vacancy delay / max zone occupied time | **5 / 5** min (2026-09-27 `.storage`) / 4 h |
| comfort grace / comfort SOC floor | 20 min / 85 % |
| nudge size / duration / eval delay / daily backstop | 1.5 °F / 2 min / 240 s / 40 |
| `select.ura_hvac_ac_gate4_predicate_mode` | live |
| `ha_carrier` `infinite_holds` | **True** |

---

## 9. Known defects / open problems — ranked by measured harm

**9.1 Self-lockout after a borrow returns (largest measured).** zone_1, 130 h after the 09-20 11:39 schedule removal
(recorder + `ac_ramp_events`, 2026-09-25): 88 entries into manual. Nudge-start n=48 median **2.0 min** (always exits to
home/sleep); nudge-restore n=15 median **5.1 min**; together 2.9 h — **the borrow works**. Long holds: 4 strands after a
*successful* return (09-21 12:53 **448 min**, 09-22 01:19 **661 min**, 09-24 19:57 **273 min**, 09-25 14:22 **88 min**)
— **CORRECTED 2026-09-26 (C20):** in every strand the CONFIG feed (`hold_activity`) ALSO reads `manual` — same second as
the status in 3 of 5, within 5 min in the other 2 — and stays manual for hours (09-22 strand: 410/417 samples
manual/manual). These are **genuine manual holds on the Carrier side created right after URA's own borrow return**, NOT a
status-lag misread. URA books each as `override_detected` at ~zero delta (09-24/25 logged "76->76"), the arrester declines,
S1 logs `preset_change_locked_out`, and `infinite_holds` keeps it. 1 failed restore (09-20 17:33, `restore_ok=0`, 115 min);
2 human step-downs (74/68, ~2 h, no URA event). Leading hypothesis (UNVERIFIED): the return's raw setpoint write creates
an anonymous manual hold, and the following named pin is discarded or reverted (a named pin over an anonymous hold is
discarded unless `resume` clears it first; the funnel decides whether to resume from `hold_activity`, which may not yet
reflect the just-written manual hold; ha_carrier's shared post-write guard can be wiped early — C16). Fix direction (W1-B):
**presets-only returns** (a return never creates a manual hold), and ~~a manual hold that appears right after URA's own write
at URA's written values is **URA-owned by provenance** → reclaim~~ (**provenance DROPPED 2026-09-27** — replaced by the S1
guard replacement in §9e, which reclaims any manual unless a person-protection hold, arrester grace/compromise, a disabled
arrester, or a live borrow says otherwise). The "trust config
`hold_activity`" coherence rule is WITHDRAWN — its premise is false for these strands.

**9.2 URA cannot see its own setpoint/mode writes** (§4.3) — made every diagnosis on this surface fragile.

**9.3 Night still-sleeper lost by radar (Jaya, zone_2).** 09-24 02:47 and 09-25 02:09 zone_2 retreated with Jaya home:
her phone (`sensor.iphone_jaya_area`, Bermuda) stationary in-suite all night. **Sequence corrected 2026-09-26 (C19):**
URA marked the room VACANT first (09-24 01:25:53, 09-25 01:31:18 — `ura_activity_log`), and only THEN turned
`fan.fanswitch_treat_wifi_jayabedroom` off because the room was vacant (01:31:03 "(vacant, 83°F)", 01:36:38) — the fan
was a consequence, not the trigger. The radars simply lost a still sleeper. Night gaps 32.6 / 45.9 / 54.4 min vs the
30-min D8 hold; probe (7.8 nights, `scripts/probes/hvac_night_sleeper_probe.py`) found only Jaya's room affected, 13/13
stationary-in-suite episodes returned (max 55.6 min), 0/9 genuine exits stationary. **Fix path: per-room
`hvac_vacancy_hold_night` knob for Jaya Bedroom (awaiting operator approval); code build parked.** Zigbee radar
**unavailable since 2026-09-25 19:32**; `sensor.seeedstudio_mmwave_kit_047d34_existence_energy` unavailable both nights.
Card `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`. Constraint: zone-scoped only, never "anyone home".
**Refined 2026-09-29 (C27):** the room did not go vacant because a radar lost a still sleeper. `binary_sensor.jaya_3_presence`
(Seeed) follows `fan.fanswitch_treat_wifi_jayabedroom`: its on-edges land 15–20 s after the fan's (09-24 20:06:15→20:06:32,
02:40:05→02:40:21, 02:56:57→02:57:10), so while the fan runs the radar reports the fan, not Jaya. On 09-24 it read on
continuously 21:22:23→01:37:12. URA's stuck-sensor rule (`coordinator.py:364`, `_stuck_sensor_hours = 4.0`, a hard-coded
literal with no knob) then excludes a sensor that has been on for 4 h, which is 01:22. The room goes vacant at 01:31:18, URA turns
the fan off at 01:36:38 because the room is vacant, and the radar drops 34 s later. The 09-25 night follows the same shape
(probe `scripts/probes/hvac_room_return_probe_raw.py`, report `docs/planning/AUDIT_hvac_hold_sizing_raw_2026_09_29.md`,
9 stuck exclusions in 7 days). So the radar never held her; a longer night hold only masks the gap, and the real fix is the
sensor (re-aim/tune/replace it so it does not see the fan). The 5400 s night hold still covers the observed gaps (≤ 69 min).

**9.4 Readers that act on a reloading room's synthetic "empty"** (pre-existing; reviewers B+D of v5.103.15): D5 coast
defer `hvac.py:2271-2289` can force an occupied zone away for one tick (and retreat an all-dead zone under coast); D6
Source-4 count `presence.py:2147-2159`; `continuous_occupied_since` reset `hvac_zones.py` ~981 — **FIXED v5.103.23 (C3, not reset while transient-blocked)**; the other readers PARKED with an evaluable revival trigger (plan W1/W2 finish Appendix A). Card
`HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`.

**9.5 Hot entry latency** — RESOLVED by v5.103.20 D2 (fast runs within 45 s of the room's evidence; ≤ 105 s on an away edge with knob 47 = 1). HISTORICAL: 5–10 min (§2, C18): first observing tick started dwell and skipped; no occupancy-triggered cycle existed.

**9.6 Broken-room gate** — develop's `all(zone.rooms)` lets one disabled/failed room block its zone from ever retreating
(round-5 orchestrator override of the operator's round-4 rule). FIXED v5.103.15 (shipped 2026-09-26).

**9.7 Custom Preset Ranges blocked** by two write-governance defects (unconditional throttle bypass; restore writers
don't update `_last_emitted_range` `hvac.py:521`).

**9.8 Smaller:** v5.103.7 README INV-2 latency oracle inconclusive; v5.103.3 boot preset-restore path unexercised;
v5.103.14 main criteria unexercised; zone rooms frozen at discovery (added-room not counted until restart).

---

**9.7 Zone 1 away never confirmed by the status feed — URA re-writes away every 10 min** (found 2026-09-26 during
v5.103.15 validation; pre-existing on v5.103.14). 08:54–12:49 CDT: ~46 home↔away flips on
`climate.thermostat_bryant_wifi_studyb_zone_1`. `decision_log` shows only URA `away` writes (`vacant_past_grace`, house
away) on the tick; `hold_activity` (CONFIG feed) = `away` continuously; `preset_mode` (STATUS feed) = `home` with home
setpoints except for the ~5–8 min post-write guard window (C21). Mirror image of the C20 manual strands: the two feeds
disagree and URA trusts the status feed. **Physical truth = AWAY (verified 13:10):** operator app shows "Holding Away
68–80, Idle"; blower_rpm 0 from 08:57 for 4 h while zone temp rose 76→80 °F (a real home/76 would have cooled). The
status-feed `home` readings are false; harm is write churn only (~57 writes/day). `hvac_action`/`conditioning` on this
entity are useless (cooling on every row). Schedule change will not fix it. **Integration reload 13:20:02 (operator) did NOT fix it:** the first FRESH read after the reload (13:20:03) was
`preset_mode=home` 70–76 with `hold_activity=away`, and the flap resumed (away 13:23 → home 13:29 → away 13:32 → home 13:39).
So the false `home` comes from the Carrier cloud STATUS payload itself, not a stale HA copy. **BUT see C22: `hold_activity`
is NOT universally right either — do not hard-code it as the confirmation oracle.** Card `HVAC-ZONE1-MANUAL-OSCILLATION-1` `finding_2026_09_26_away_feed_split`; decision belongs to W1-B
(which feed confirms a write).

## 9b. Operator decisions & facts recorded 2026-09-26 (binding)

| Topic | Decision / fact | Source |
|---|---|---|
| Failed / disabled / removed room (live-room gate, v5.103.15) | **Option (a):** the room does not count toward any decision — it acts as if it is not defined in URA; the zone decides on its remaining live rooms immediately (no extra vacancy grace). "Failed" = the ROOM config entry is disabled, SETUP_ERROR / MIGRATION_ERROR / SETUP_RETRY, stuck loading/unloading > 300 s, or deleted. A failed SENSOR inside a running room is NOT this (that is W2 night-trust). | operator: "The room does not count to decisions and acts like its not defined in URA." |
| Bryant schedules | Still present (zone_1 reduced to 06:00 Home; zones 2/3 untouched). Working assumption: reduce them so only URA controls. | operator 2026-09-26 |
| AC ramp | ON (`hvac_ac_ramp_master_enabled: True` live); nudges stay ON. | operator 2026-09-26: "AC RAMP is on"; "We're not turning off nudges" |
| `ha_carrier.set_activity_setpoint` | Upstream feature #427, not local; account for it in W1 design. | GitHub `dahlb/ha_carrier` history, verified 2026-09-26 |

### 9c. Room Override Occupied / Override Vacant vs HVAC occupancy (NOT previously considered — operator 2026-09-26)
Per-room switches `switch.<room>_override_occupied` / `_override_vacant` (`switch.py:4935-5010`, mutually exclusive, RestoreEntity — they SURVIVE restarts). Consumer: room coordinator only (`coordinator.py:2884-2890`, applied at `:4791-4811`) — sets `data[STATE_OCCUPIED]` True/False with `occupancy_source="override"`. HVAC reads that same value (`hvac_zones.py:647` `data.get("occupied")`) into the D1 producer (`_compute_hvac_occupied`, `hvac_zones.py:966-1035`). Consequences (code-derived; not yet live-tested):
- **Override Occupied → HVAC-occupied** on the rising edge, EXCEPT hallway-typed rooms: circulation exclusion forces `hvac_occupied=False` regardless (`hvac_zones.py:~655-665`), so forcing a hallway occupied does nothing for HVAC.
- **Override Vacant is NOT immediate for HVAC:** it is a falling edge, so the per-room-type **tail-hold** arms (`_effective_hvac_hold_seconds`, D8 night hold for bedrooms) and the zone keeps conditioning for the tail + vacancy grace (10 min live) + up to one 5-min tick.
- Because the switches restore across restarts, a forgotten Override Occupied holds its zone occupied indefinitely; whether the D6 stale-occupancy failsafe (8 h) then forces `away` against an explicit operator override is UNVERIFIED — check before W2.
- **DECIDED 2026-09-26 — LEAVE AS IS** (operator: "Leave it as is but document in state of play for HVAC so it surfaces"). Overrides are NOT a hard HVAC input: Override Vacant still rides the per-room tail-hold + vacancy grace + tick; Override Occupied is still ignored for hallway rooms. Anyone reasoning about "why did the zone keep cooling after I forced the room vacant" starts here. Revisit only on an operator ask. **v5.103.20 update:** Override Vacant is NO HVAC EVIDENCE — in `home_day`/`home_evening` the room releases at last evidence + hold (no lighting timeout ride); Override Occupied IS evidence (except hallways).

### 9d. W2 occupancy fast path — scope decided 2026-09-26
Operator: "The HVAC signaling from rooms that is more immediate I expect to shave the 5m tick only for now." Scope: a room/zone HVAC-occupancy change triggers a (rate-limited, per-zone) decision cycle so HVAC no longer waits up to one `HVAC_DECISION_TICK` (5 min). NOTHING ELSE changes in that cycle — no dwell change (entry dwell stays 2 min), no hold/grace/tail change, no new retreat semantics, no override semantics. Rate limit exists because the 5-min tick is a Carrier cloud call-rate bound (`hvac_const.py:11-13`). **BUILT v5.103.20 (REV 7 of `PLANNING_hvac_fast_occupancy_response.md`): zone-scoped fast runs on room evidence + exact-release exit timers + D5 transit filter; INV-1 (fast run == periodic outcome for Z within 45 s), INV-2 (no early vacancy away), INV-3 (exit once at release + G), INV-4 (zone scope), INV-5 (shadow untouched), INV-D5 (an unpersisted away-edge episode never writes home while the house stays in an evidence state). Scope grew beyond "shave the tick" by operator rulings R1–R3.**

### 9e. S1 manual guard SUPERSEDED — decided 2026-09-27 (binding)

**The old rule.** `should_change_preset` (`hvac_preset.py:202-217`, v3.8.0, 2026-03-07): if the zone reads `manual`, S1 never writes a preset — "Don't fight manual — that's the arrester's job." Written before borrows existed and before we knew a raw setpoint write comes back from Carrier as a `manual` hold.

**Why it is wrong now.** Operator 2026-09-27: *"Its outdated design. We know a lot more. We didn't even know borrows would come back as manual then."* Measured consequences: every URA-caused manual (borrow returns, nudge echoes, compromises) locked S1 out, because the arrester declines manuals at ~zero delta (§7) — nobody owned them (§9.1 strands 88–661 min; 22/22 echo lockouts, v5.103.17). The guard also became an UNDOCUMENTED dependency: it was the only thing stopping S1 from writing over live borrows, which is why the governed-excursion lease gate was stripped as "zero value" (2026-08-21).

**The replacement (W1-B REV 5, Alt A, `PLANNING_hvac_w1b_thermostat_definition.md` §5.P1).** S1 takes a zone out of `manual` to its target preset UNLESS one of four gates holds for that zone:
- **(a/b) person-protected hold:** Temp Arrester Override switch ON, OR any immune-person hold active (generalised over all immune persons).
- **(c) arrester grace / compromise** in flight for the zone (`_override_active` / `_compromise_timers`).
- **(d) arrester DISABLED ("passive mode"):** `switch.ura_hvac_coordinator_override_arrester` OFF — the arrester still books `override_detected` (`mode=passive`) but never reverts (`hvac_override.py:2897`, `:3172-3186`; README_v3.9.0), so S1 must keep respecting manual. Operator normally runs the arrester ON.
- **(e) live borrow row** for the zone (`hvac_excursion._row_present_and_fresh`, all five kinds), bounded by the row's own `stale_ts` (duration + `EXCURSION_LEASE_SLACK_S`). Verified: every nudge/compromise timer is preceded by its `begin_excursion`, so the row covers the whole timer window.

**Operator constraint:** the rule lives ONLY at the S1 decision site (plus the arrester's existing detection path reading gate (e) for the nudge-wins booking). Nothing added to borrow code (`begin_excursion` / `return_excursion`) or to the `emit_*` funnels; resume-then-pin is a Carrier quirk and stays.

**What it makes unnecessary:** W1-B provenance / URA-owned-manual machinery + strand gate (dropped); the separate BORROW_LOCK (collapsed into gate (e)); former problem 4 (TAO/immune sunset reclaim — closed free: gate (a/b) drops, S1 reclaims next tick); after live validation — ~~`hvac_excursion.py:629-650` HIGH-1 skip + parked D3 (DELETE)~~ **REFUTED 2026-09-28 (C26): the skip is live and stays (now `_auto_return`, `hvac_excursion.py` ~686); D3 has no code**, lockout ledger → `preset_change_deferred` (KEEP+WIRE), cards HVAC-PRESET-LOCKOUT-ESCAPE-1 + HVAC-ZONE1-MANUAL-OSCILLATION-1 (close). Cost: ~160 extra Carrier writes/day (nudge-return reclaims via resume-then-pin), covered by 120 s preset-kind suppression.

**Precedence rulings (operator, 2026-09-27, W1-B ledger):** D13 nudges win over a human change during the nudge; D48 borrow STARTS (nudge, pre-cool, pre-heat, pre-arrival, compromise) proceed even when a zone is person-protected — *"URA has more information and should win"*; D49 vacancy-away bypass waits for (a/b) and (e) only (it does defer during a compromise because `_compromise_timers` is a gate-(e) source); D50 an immune person wins over a live compromise; D51 excursion kill switch retired; D52 hard reset gated only on (a/b). Gate (e) as shipped = fresh registry row OR `_nudge_restore_timers` / `_nudge_in_flight` / `_compromise_timers` (token dicts and predictor/egress leftovers are NOT evidence — they outlived their borrow). The arrester re-checks (a/b), gate (e) and egress pause when its grace/compromise timer FIRES and stands down with one `arrester_deferred_to_borrow` row.

**Ruling 2026-09-28 "The person interrupts. We end and revert." (v5.103.23, plan `PLANNING_hvac_w1_w2_finish.md`).**
- A person's change (D1 within-manual, or a transition INTO manual whose changed legs match no recent URA write) ENDS a live BANKING / PREHEAT / ownerless COMPROMISE borrow with no write, BEFORE the precedence ladder, so the `borrow_active` rung no longer applies to them. EGRESS still books `borrow_active` (Q2).
- **D13 kept:** a live nudge still wins and is not ended.
  - Fix-up 1 (D-L3): a NON-NUDGE borrow under a live nudge is still ended `human_interrupt`, and the zone is latched.
  - **v5.103.24 (INFO-1, operator ruling "B"):** when that nudge restores, it does NOT write back its snapshot (taken on top of the ended borrow). S6 is skipped and S7 pins the zone's current S1 target preset, or the ARRIVAL target for an interrupted pre-arrival (Q7). See §4.2 S6/S7.
- **D48 narrowed (Q3):** after an interrupt, no S12/S13 begins on the zone until it leaves manual, and S11 never writes over a latched zone (fix-up 1, D-L1).
  - **Discharge (fix-up 2, N1 — LEVEL-triggered; replaces the fix-up-1 edge rule):** one predicate, `OverrideArrester._latch_state_discharges` (`hvac_override.py`): the state is readable (not unavailable / unknown / missing) AND `preset_mode` is non-empty and not `manual`. It is applied (i) at the TOP of `_handle_climate_change` to every event's new state, whatever the old state, BEFORE the `old_state is None` return; (ii) every full decision pass (`latch_level_check`, called in `_run_decision_cycle` before the D3 reconciliation); (iii) at boot restore. An unavailable/unknown flap or an empty preset keeps it; a manual → named → manual status flicker still discharges it (accepted, L5).
  - **Backstop (fix-up 1, D-M2):** the latch is PERSISTED in the `_zone_state_store` side-key `__interrupt_latch` — saved on set, discharge and prune, and in the shutdown snapshot. At boot it is restored unless the entity reads a discharging state (kept while missing / unreadable / empty preset).
  - **Prune (fix-up 2, N5):** latches for thermostats no longer mapped to any zone are dropped at boot restore and on the Zone Manager's zones-updated signal (`_handle_zm_zones_updated` → `prune_interrupt_latch`, which persists). Skipped while the zone map is empty (boot before discovery).
- **Compromise in flight:** superseded — grace/compromise timers cancelled (AC-reset timers kept), generation bumped, own row released `human_interrupt`, and the change re-dispatched against the episode's original preset. `_apply_compromise` / `_revert_override` tasks stand down on a generation change.
- **Compromise supersede (fix-up 1):** re-checked after the S3 write await. A superseded compromise closes its row and arms no timer. Stood-down tasks drop their own timer handle. The startup-audit revert is a recorded, generation-aware episode. Disabling the arrester bumps every zone's generation.
- **One reference preset per case; Q7 (fix-up 1 ruling "Home for pre-arrivals"):** a pre-arrival interrupt uses the house's ARRIVAL target — `pre_arrival_reference_preset` (`hvac_const.py`): sleep in sleep/waking, else home; never away/vacation. Other kinds keep the named pre-borrow preset (H3).
  - **Precedence (fix-up 2, N4):** an ended `S12_pre_arrival` token takes the arrival reference FIRST, even when an arrester episode is in flight (case B — including the startup-audit episode, whose original preset may be `away`). Order in `_handle_climate_change`: ended pre-arrival → case B episode → case A energy BANKING/PREHEAT → case C.
- **Pre-arrival lifetime (fix-up 1):**
  - A max-age end turns the zone's pre-arrival fans off and SPENDS the arrival episode (`_pre_arrival_spent`, via `HVACCoordinator._spend_pre_arrival_episode`). No new pre-cool starts until HVAC arrival or a whole window with no trigger; each repeat trigger inside the window refreshes the spent time. ZI off → on inside the window does not re-begin.
  - **Fix-up 2:** the episode is also spent when a person's change ended the pre-arrival (`interrupted` clear, N2 — so after S4 pins Home and discharges the latch, a repeat trigger does not start a second pre-cool) and when pre-conditioning master OFF released it (D-L7 release, N3).
  - **Fix-up 3 (D2-1):** also spent when the person's change lands inside `begin_excursion`'s DB save — the M1 exit of `_execute_zone_pre_cool` spends a `pre_arrival` episode (the token was never stored, so the interrupted clear cannot see it). Accepted LOWs (review record Round 3): L5 early discharge on a discarded pin (`HVAC-WRITE-CONFIRMATION-ORACLE-1`); Q7 reference not kept across a restart mid-grace; shutdown-save race on `__interrupt_latch`.
  - The HVAC coordinator switched off, ZI off, or pre-conditioning master OFF each end the borrow `pre_arrival_inactive` (never `lease_expiry`).
  - A removed zone or a missing baseline closes the row with no write.
- **Q4 kept:** an empty zone is still sent Away by S1.
- **D2f:** disabling the arrester releases owned compromise rows.

**Doc hygiene:** every plan/design doc/README that cites the old guard as design intent carries a `SUPERSEDED 2026-09-27` banner pointing here. Do not re-derive designs from them.

**BUILD STATUS — W1-B SHIPPED v5.103.18 2026-09-27** (built on `feature/hvac-w1b-thermostat-definition`; 4 Tier-3 reviews + 3 fix-up rounds with re-reviews; decisions 1-52; live validation in README_v5.103.18). Historical build note follows: What the branch changes (code wins over this note once merged): `hvac_preset.py` `should_change_preset(..., zone_id=)` + `manual_guard_verdict` (four gates, fail-closed when unwired); `hvac.py` S1 site (vacancy bypass respects (a/b)+(e); `preset_change_locked_out` → `preset_change_deferred` with `gate_snapshot`; `suppress(kind="preset")`; `manual_class` + `gate_snapshot` on S1's `preset_change` row — the `climate_write` funnel payload is untouched; `_zones_written_this_cycle` reset at cycle ENTRY; `s1_reclaim_rate_high` NM at >3/30 min; S1 writes via `hvac_strategy.Strategy.hold_preset`); `hvac_override.py` `_handle_climate_change` single `override_detected` row post-delta with `delta_f`/`gated_reason`/`gate_snapshot` (precedence nudge_win → borrow_active → immune_stamp → temp_arrester_override → comfort_grant → passive_mode), `last_detection_for`, immune-hold + TAO persistence via `_zone_state_store` side-keys `__immune_holds` / `__tao_state` (no new table), TAO restored at boot iff `now < expires_at` (decision 46; `expires_at = started + COMFORT_OVERRIDE_MAX_S` — the plan's `HVAC_ARRESTER_OVERRIDE_MAX_S` name does not exist), same-tick nudge skip; D2.4 presets-only returns at the 5 setpoint sites (S6/S8/S9/S11/S13; raw setpoint only for a HUMAN_MANUAL snapshot, reason prefix `human_manual_`); `hvac_excursion.py` gained ONLY the pure reads `is_borrow_active` / `excursion_id_for`; compromise default + UI max 30/120 → 15 with clamp-on-read. Gate (e) no-row fallbacks verified per kind: NUDGE `_nudge_restore_timers`/`_nudge_in_flight`; COMPROMISE `_compromise_timers`; BANKING `_last_precool_zones` (prune-discharged, superset); EGRESS `is_paused`; PREHEAT had NO no-row signal when the excursion kill switch was OFF — **resolved by D51 (kill switch retired, every begin records a row) and D47 (gate (e) = fresh row OR the arrester's self-discharging `_nudge_restore_timers` / `_nudge_in_flight` / `_compromise_timers`; token / predictor / egress fallbacks dropped because their leftovers outlive the row).** Fix-up round 1 also: D48 borrow starts win over person protection (not gated on a/b); D49 vacancy bypass ignores (c)/(d); D50 immune person wins over a live compromise; TAO saved before arrester teardown; restart marker NM worded from the boot decision; `manual_class ∈ {sub_delta_human, zero_delta_ura, gated_human, unknown}`; startup audit never reverts under a live borrow.

## 10. CORRECTIONS LEDGER — claims that were WRONG (do not re-assert)

| # | Wrong claim (when) | Truth | Evidence |
|---|---|---|---|
| C1 | "zone_1's manual is not URA — URA only writes preset_change there" (09-17 MEASURED; repeated 09-25) | `ura_activity_log` never records `set_temperature`; the soft-nudge borrow writes setpoints, logged only in `ac_ramp_events` | §4.3; Explore audit 2026-09-25; 09-25 09:45:14 nudge_started → 09:45:15 manual 78/70 |
| C2 | "the Bryant schedule reclaim is THE cause of zone_1 manual" (09-17) | One writer: removal (09-20 11:39) cut manual 44 % → 26 %; the long strands are the §9.1 post-return lockout | §5, §9.1 |
| C3 | "the nudge is the dominant writer" (09-25, by count) | Dominant by COUNT (~70/88) but brief (2–5 min) and self-restoring; the TIME is in post-return strands | §9.1 |
| C4 | "night retreat of empty zones is built but switched off" (09-25) | Preset-layer night retreat is LIVE since v5.103.7; only the setpoint layer (D9) is dormant | §3.3; `hvac.py:3830` |
| C5 | "night-protection breadth is an open operator policy call; currently anyone-home keeps every empty zone at comfort" (09-25) | Operator decided RESET-ONLY in round 4 (09-17); shipped in v5.103.7 | `conditioning_retreat_ok`; card `ROUND4_DECISIONS_2026_09_17` |
| C6 | "broken room: raise an alert rather than loosen the rule" / round-5 `all(zone.rooms)` as the safe gate | The operator's round-4 rule was live-room scoping; round 4 built it wrongly as `any()`; round 5 (orchestrator) overrode the operator instead of fixing it | `f88f4bc84`; card `HVAC-DEGRADED-ROOM-TRIPWIRE-1` |
| C7 | "the mode-change funnel was gated on identifying zone_1's writer, which is now done" (09-25) | Writer was not identified then; the gate was lifted because the zone_1 problem is preset/setpoint-side | card `HVAC-SETHVACMODE-CHOKEPOINT-1` |
| C8 | "HVAC reacts to occupancy on a 1-min tick / bypasses the 5-min tick" (operator recollection 09-26) | 5-min tick; no occupancy-triggered cycle; the fast path was designed (`82620357a`) not built | §2 |
| C9 | "step-4-B (conditioning demand) is unshipped; night-trust fails review" (09-17 handoff memo) | Shipped v5.103.7 (daytime debounce LIVE, setpoint corrector DORMANT) with reset-only backstop | README v5.103.7; `f88f4bc84` |
| C10 | "HVAC decisions run on ~5-min tick" was stated earlier as an assumption, then verified | Verified correct — kept here so it is not re-litigated | §2 |
| C11 | "v5.103.7 set zone entry dwell to 0" (plan D5) | Migration rewrote only an exact 3; install stored 5.0 → dwell stayed 5 until operator set 2 (09-26) | `__init__.py:785-800`; README v5.103.7 write-back row 2 FAIL |
| C12 | Code comment "operator does not use the Bryant schedule" (SUPERSEDED + corrected in code 2026-09-26) | Schedules existed until 09-20; a 6 AM Home entry remains on zone_1; zones 2/3 still scheduled | `hvac_setpoint.py:164-167` vs §5 |
| C13 | "the borrow return writes setpoints then preset" (framed as the primitive's behaviour, 09-25) | The primitive writes nothing; each SITE writes (a)→(b)→(c) itself — the ordering lives in N copies | `hvac_excursion.py:886-888` |
| C14 | Enphase/"stream SOC 52 untrustworthy" and similar non-HVAC corrections | See energy docs / `project_session_pickup_2026_09_23` | — |

---

| C15 | "The installed ha_carrier is locally PATCHED (set_activity_setpoint); a HACS update would wipe it" (fork report + orchestrator, 2026-09-26) | It is upstream code: PR #427 (Evan Weaver, 2026-08-31), in v2.28.4 as installed from `dahlb/ha_carrier`; the file's "PATCH" comment is upstream's own wording | `gh api repos/dahlb/ha_carrier` history; HACS record `.storage/hacs.repositories` |

| C16 | "Carrier refresh is 42-79 s" (used as if it were the integration's schedule) | That is URA's *observed* effective window. ha_carrier's schedule is `DEFAULT_UPDATE_INTERVAL_MINUTES=30`, full reconcile every 120 min, and a **5-min post-write guard** that, when a websocket message reverts a written zone, overwrites HA's LOCAL copy (status activity + setpoints; never `hold_activity`) back to the written values — it sends NOTHING to the cloud (`_reassert_control` docstring: "Does not read the API"), so it MASKS a cloud revert in HA for up to 5 min; a full read ends every guard ("A full read is authoritative", `carrier_data_update_coordinator.py:430-432`) (`ha_carrier/const.py:46-59`, `carrier_data_update_coordinator.py:168-296`). How that guard composes with URA's 5-s suppression and with back-to-back nudge/restore writes is UNVERIFIED and a candidate strand mechanism — see `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §9 | source, verified 2026-09-26 |

| C17 | "Arrester suppression is only 5 s" (§2/§7, and copied into the W1-B plan) | Two windows: `SUPPRESS_TTL_SECONDS = 5` for temperature writes (kept short on purpose for human detection) and `SUPPRESS_TTL_SECONDS_PRESET = 120` for preset writes | `hvac_override.py:129`, `:141-146`, `:153` (W1-B build-prediction review, verified 2026-09-26) |

| C18 | "Hot entry takes up to one tick + dwell, ~7 min" | 5–10 min: the observing tick starts the dwell clock and always skips; the preset write lands on the next tick | `hvac_zones.py:786`, `hvac.py:2438-2451` (W2-1 plan review, verified 2026-09-26; lines refreshed after v5.103.16) |

| C19 | "Jaya's radar dropped because the fan switched off" (09-25 session) | URA marked the room vacant FIRST (01:25:53 / 01:31:18), then turned the fan off because it was vacant; the radars lost a still sleeper | `ura_activity_log` Jaya Bedroom rows (W2-2 plan review, verified 2026-09-26) |

| C20 | "Zone 1 strands = URA trusting a status-lagged `manual` while `hold_activity` names a preset" (entry 144, §9.1, 2026-09-25/26) | In all 5 strands `hold_activity` is ALSO `manual` (same second in 3/5, ≤5 min in 2/5) and stays manual for hours — real Carrier-side manual holds created right after URA's return; the status/config coherence rule is withdrawn | recorder zone_1 preset_mode + hold_activity across 09-20/21/22/24/25 strands (verified 2026-09-26 after the W1-B completeness review showed hold_activity authority was unproven in source) |

| C21 | "Carrier re-applies any write the cloud reverts, for 5 min" (orchestrator, 2026-09-26) | The guard rewrites only HA's local copy of status activity + setpoints (not `hold_activity`) and sends nothing to the cloud — it hides a cloud revert from HA for up to 5 min, which fits strands becoming visible 5–14 min after URA's return | `carrier_data_update_coordinator.py:162-296, 430-432` (verified 2026-09-26) |

**C22 (2026-09-26 afternoon) — WRONG: "URA must confirm Bryant writes from `hold_activity`."** Physical-evidence probe
(`scripts/probes/carrier_feed_truth_episodes.py`, 7 d, 3 zones; blower/temperature vs the two feeds' cooling setpoints,
2 °F differential guard), pooled decisive minutes: named-vs-named disagreement (zone_1 status home / hold away): device
followed HOLD 85 vs STATUS 5. Status=`manual`: zone_2 (a human set cool 70 at 00:45 on 09-26, arrester logged the
override) followed STATUS 506 vs HOLD 4 — `hold_activity` read `sleep` for 8.5 h while the zone cooled to 71–74 °F;
zone_1 (post-borrow manual strands) followed HOLD 21 vs STATUS 1. Neither feed is always right. Candidate rule (n=1 per
case, NOT proven): trust `hold_activity` unless a genuine human override is detected, then trust the status payload.
This is W1-B D0 input; a controlled operator app-change test is requested.

**C23 (2026-09-26 evening) — WRONG: parts of C22.** (a) "`hold_activity` is right on named-vs-named": 155 of zone_1's 165
`(home, away)` minutes had `hold_until==''` = ha_carrier's OPTIMISTIC LOCAL copy of URA's write (`climate.py:431-433`), not a
cloud value (`None`); the device was physically away, but the hold feed was echoing URA, not independently confirming.
(b) "a human set cool 70 at 00:45": the human set 70 at **19:17 CDT 09-25** (both feeds `manual`, agreeing, 5.5 h); the
disagreement began 00:45 CDT when the cloud `hold_activity` flipped to `sleep` in the same second as a URA zone_3 write —
co-occurrence, causation UNVERIFIED. (c) NEW MECHANISM: 24/52 `override_detected` rows since 09-19 are Carrier's echo of
URA's own nudge, 5.3–7.5 s after the write (past the 5 s temp suppression, `hvac_override.py:133`/`:2440-2450`), shown as
a whole-degree value; 22 of 24 followed by a lockout — card `HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1`.
**FIXED for nudge-start / compromise / pre-cool echoes (~28 of ~35, operator-approved
simplest fix, build 2026-09-26):** `SUPPRESS_TTL_SECONDS` raised **5 -> 15 s**
(`hvac_override.py:133`), 2x the measured 7.5 s max echo lag, still far below the
> 60 s genuine-human-manual floor and Carrier's 42-79 s cloud refresh. Residuals
-> **W1-B problem 1**: restore echoes under kind="preset" (mid-window passthrough
books a fresh transition INTO `manual`), late echoes > 15 s under kind="temp",
and post-restore manual strands (§9.1). The value-matched last-write record from
the plan is part of W1-B. Accepted trade-off: a human preset -> manual within
15 s of a URA temp write (kind="temp") is not booked.

**C24 (2026-09-26 night) — WRONG: "HVAC occupancy is a separate, FASTER clock; a transit drops ~1 min after the person
leaves."** `_compute_hvac_occupied` (`hvac_zones.py:1048-1123`) *"rides grace-held STATE_OCCUPIED + per-room tail. Kind is NOT
consulted"*; its input is the room's lighting `data.get("occupied")` (`:717`). HVAC occupancy decouples hallways (excluded),
release tails and the zone trust gate — but it ARMS on the lighting rising edge and HOLDS through the lighting occupancy
timeout (~300 s typical) + tail. So a 10 s transit keeps a room HVAC-occupied ~5 min + tail. WHY (step-4-B plan
`PLANNING_hvac_zone_conditioning_demand.md:30,:119`, CRIT-1): reading raw kinds live would drop a still/sleeping body on a
radar blip → retreat on an occupied room; transit was handled only by hallway exclusion; *"within-room kind discrimination
is Stage B, deferred"* — the operator's intended faster HVAC clock is that unbuilt Stage B. A CRIT-1-safe Stage B consults
raw evidence ONLY at the arming edge (arm iff raw presence persisted ≥ N s), keeping the robust hold after arming.

**C25 (2026-09-27) — WRONG DESIGN PREMISE: "S1 must not fight `manual` — that's the arrester's job" (v3.8.0,
`hvac_preset.py:202-217`), and its downstream corollaries "fighting an operator-set manual is the arrester's job, not the
excursion's" (`hvac_predict.py:1559-1560`) and "the lease gate has zero value because the manual lockout protects
borrows" (`hvac_excursion.py:6-16`).** The arrester only handles manuals it books as a genuine human change at ≥ 1 °F
delta; URA-caused manuals (borrow returns, echoes, compromises) fall through, so the guard locked URA out of its own zones
(§9.1). And "protects borrows" meant the guard was an undocumented safety dependency. SUPERSEDED by §9e; do not cite the
old guard as design intent, and do not remove it without the four §9e gates.

**C26 (2026-09-28) — WRONG: "after W1-B live validation, delete the `hvac_excursion.py` HIGH-1 manual-skip + parked D3
(now dead)" (§9e, W1-B plan §5.P2, README_v5.103.18, card disposition).** The skip in `_auto_return` (`pre_preset in
(None, "", "manual")` → no preset write, `restore_ok=None`) is LIVE: `pre_preset` is the unfiltered `preset_mode` snapshot at
`begin_excursion`; COMPROMISE borrows begin while the human override holds the zone in `manual`; after a restart the boot
audit rehydrates the COMPROMISE row, the arrester's in-memory compromise timer is gone and its startup audit stands down
under the live row (gate (e)), so the lease-expiry sweep reaches `_auto_return` with `pre_preset="manual"`. Deleting the
skip would WRITE preset `manual` (or `None`) to the thermostat. What W1-B actually superseded is only the docstring's "nothing
recovers the zone from manual — D3's job" (S1 now reclaims); docstring corrected. "Parked D3" has no code in the HVAC
modules — only the `(D3 recovery parked)` log text. Pinned by `test_hvac_excursion_d1_auto_release.py`
(`test_auto_return_skips_preset_when_pre_preset_{manual,none,empty}`). NOT deleted.

**C27 (2026-09-29) — INCOMPLETE: C19's "the radars simply lost a still sleeper" (§9.3).** The Seeed radar
`binary_sensor.jaya_3_presence` tracks the bedroom fan (on-edges 15–20 s after the fan's), so it never sensed Jaya. It was
removed by the hard-coded 4 h stuck-sensor rule (`coordinator.py:364`) about 4 h after its last on-edge (09-24: on 21:22:23 → excluded
≈01:22 → vacant 01:31:18 → fan off 01:36:38 → radar off 01:37:12). C19's ordering (vacant before fan-off) stands; its
cause does not. Evidence: HA recorder state history for both entities, 09-23→09-25 and 09-28 (verified 2026-09-29),
`AUDIT_hvac_hold_sizing_raw_2026_09_29.md`.

**C28 (2026-09-29, P5 of the W1/W2-finish plan) — WRONG: "the S4 revert must use the compromise token's snapshot preset" (F2 fix comment, `_revert_override`).** The compromise begins while the person's override holds the zone in `manual`, so the snapshot is usually `manual`. S4 then pinned `manual` — 4 `climate_write` rows on zone_1 between 09-28 03:51Z and 09-29 01:11Z. Fixed in v5.103.23 D2d: the snapshot is used only when NAMED, else the episode's `original_preset`; neither named → no S4.

**C29 (2026-09-29, Batch A LOW-4, code-verified) — WRONG: "the boot audit's NUDGE preset restore always repairs the zone" (§6 F1 note, `async_startup_excursion_audit`).** A NUDGE can begin on a zone already in `manual` (D48/D52: `check_ac_reset` checks only `_override_active`; the force-nudge button checks no preset), so its snapshot can be `manual`, and the audit pinned it — re-creating the lockout. 0 such rows were seen in the 09-26 → 09-29 window; the fix is from code. Fixed in v5.103.23 D6: a `manual` snapshot is skipped (`startup_audit_nudge_preset_restore_skipped_manual`) and the row is still cleared. The old test `test_F1_boot_audit_manual_snapshot_writes_manual_back` was superseded.

## 11. The approved arc (operator-approved 2026-09-26: "The workstreams are approved. Recard.")

| Seq | Workstream / step | Problems (§9) | Tier / gate |
|---|---|---|---|
| 0 | **v5.103.15 live-room establishment** (SHIPPED 2026-09-26) — establishment over rooms actually running: excluded = disabled / SETUP_ERROR / MIGRATION_ERROR / SETUP_RETRY; transient (loading) rooms BLOCK; live rooms must be LOADED + coordinator-present + seen; all-dead zone never retreats. Plan `docs/planning/PLANNING_hvac_live_room_establishment.md` REV 2 | 9.6 | Tier 2-DB + mandatory D; fix-up pending (reviewers B/D: failed-room sticky exclusion, hold preset while transient-blocked & fused-empty, deleted-room exclusion, NM `location`, UTC grace clock) |
| 1 | **W1-A Thermostat I/O governance, behaviour-neutral:** all 3 verbs through funnels (add `emit_set_hvac_mode`, migrate the 7 raw sites); ONE durable row per actual write (verb, zone, site, values, reason) | 9.2, part of 9.1 | Tier 2-DB |
| 2 | **W1-B Thermostat definition (per-BRAND strategy)** — **SHIPPED v5.103.18 2026-09-27.** **REV 5 scope (2026-09-27, commit `3ed9afda1`):** problem 1 = presets-only returns + **S1 manual-guard replacement (§9e, four gates)** — provenance, reclaim delay and kill switch DROPPED; problem 2 = borrows protected by gate (e) (registry row, `stale_ts` cap), **nudge wins** over a human change during the nudge (ruling 13), compromise UI max 15 min (ruling 14); problem 3 (per-brand definition + generic default). Problem 4 (TAO/immune-expiry reclaim) CLOSED by §9e; problem 6 (which feed confirms a write) DECOUPLED to `HVAC-WRITE-CONFIRMATION-ORACLE-1`. The withdrawn rule "manual counts as human only when CONFIG `hold_activity == manual`" (C20/C23) is NOT used. Plan `docs/planning/PLANNING_hvac_w1b_thermostat_definition.md`; nudge-start echoes fixed separately (v5.103.17) | 9.1, 9.5 | Tier 3; operator GO through deploy unless unexpected |
| 3 | Measure one clean day on the W1-A write log: stranded-manual minutes by cause, before/after | — | read-only |
| 4 | **W2 Occupancy truth:** night still-sleeper hold (in-suite stationary BLE + radar micro-blips extend the hold; zone-scoped), Jaya radar repair (physical), occupancy-triggered decision cycle (fast path, `82620357a`), hot entry, reloading-room placeholder readers, guest-as-zone-person | 9.3, 9.4, 9.5 | Tier 2-DB each |
| 5 | Enable Custom Preset Ranges (D9) once W1-B removed its blockers | 9.7 | Tier 2 |
| 6 | **W3 Energy-aware HVAC:** pre-cool window TOU-derived, D5 re-ground on ODU Var %, equipment-health telemetry | — | as ranked |
| 7 | **W4 Closure:** parked residuals (`HVAC-ROLLOVER-DURABLE-DATE-ORDERING-1`, `ANOMALY-SAVE-BASELINES-DICT-MUTATION-1`), README write-backs, card disposal, update this doc | — | — |

Operator constraints carried into every step: match occupancy **in the zone**, never "anyone home"; nudges stay ON;
per-brand behaviour discovered in detail but exposed through a simple generic interface; no corners cut
(tier protocol, framing-disjoint reviews, per-site mutation drills, orchestrator hand-check of any Opus-5 output —
agents now pinned to `claude-opus-5-5`).

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **Borrow / excursion** | A sanctioned temporary raw-setpoint write that must be returned to a snapshot (`begin_excursion` / `return_excursion`). "Borrow" is the operator-facing name |
| **Kinds** | NUDGE, COMPROMISE, BANKING, PREHEAT, EGRESS_PAUSE (`hvac_excursion.py:94-104`) |
| **S1..S14** | Write-site ids from the governed-excursion / preset-contract plans: S1 house-state/occupancy preset; S3 arrester compromise; S4 arrester revert; S5 nudge start; S6/S7 nudge restore (setpoints/preset); S8 cancel-nudge; S9 boot ramp audit; S10 DPM custom ranges; S11 banking release; S12 pre-cool; S13 pre-heat; S14 off-phase ceiling (**removed** v5.103.3) |
| **D1..D9** (conditioning-demand cycle) | D1 room `hvac_occupied` + circulation exclusion; D5 retire zone dwell; D7 night-trust guard on fused signal; D8 night tail-hold; D9 DPM compose-away (dormant). Not to be confused with **D5 energy-shed cap** (duty-cycle, v5.103.9) |
| **row-1 / row-4 / row-10** | Rows of the zone decision table: row-1 preset-flip retreat (`hvac.py:2013`); row-4 D6 stale failsafe; row-10 arrester comfort-delay (`hvac_override.py:2304-2340`) |
| **Established** | Zone has been observed by the HVAC producer such that retreat may be trusted (`is_zone_hvac_established`) |
| **Fused** | `zone.any_room_hvac_occupied`, the OR of rooms' `hvac_occupied` |
| **Tail-hold** | Per-room time a just-emptied room keeps `hvac_occupied` (§3.1) |
| **Reset-only backstop** | Person-trust protects only an *unestablished* zone (post-reload gap); once established, occupancy alone decides |
| **Lockout** | S1 refusing to write a preset while the zone reads `manual` (`preset_change_locked_out`) |
| **Arrester** | `OverrideArrester` — detects manual holds, reverts/compromises by delta, owns nudge/AC reset |
| **Resume-then-pin** | v5.103.2 funnel behaviour: send Carrier `resume` to clear an anonymous `manual` hold, then pin the named preset |
| **Anonymous hold** | `hold_activity == "manual"` — what any raw setpoint write leaves on Carrier |
| **Status vs config feed** | `ha_carrier`: status (polled, lags) drives `preset_mode`; config (prompt) drives `hold_activity` |
