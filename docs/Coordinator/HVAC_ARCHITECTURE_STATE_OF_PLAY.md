# HVAC — Architecture State of Play (READ FIRST)

**Status:** forensic snapshot of `develop` @`5072deaaf` (2026-09-26 ~02:30 CDT) + live HA reads the same night.
**Scope:** everything URA does with the thermostats — decide, write, borrow/return, read back — and the occupancy
model that drives it. Covers releases v5.103.0 → v5.103.14 and the in-flight v5.103.15 branch.
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
- **Biggest live defect (measured §9.1):** after a borrow returns correctly, `ha_carrier` later reports a
  status-lagged `preset_mode=manual` (sometimes with stale nudge setpoints); URA books it as a human override,
  the arrester declines (zero delta), S1 locks itself out, and — with infinite holds — the zone strands 1.5–11 h.
- **Observability gap:** `ura_activity_log` records preset writes but **never** `set_temperature` or `set_hvac_mode`;
  borrow/nudge writes live only in `ac_ramp_events` / `hvac_excursion_events` / INFO logs (§4.3). This gap caused a
  wrong exoneration of URA (§10).
- **In flight:** v5.103.15 live-room establishment (`feature/hvac-live-room-establishment`, reviews in progress).
- **Approved arc (§11):** W1 thermostat-definition abstraction (per-BRAND strategy) → W2 occupancy truth → W3 energy
  HVAC → W4 closure.

---

## 2. Decision loop & timing (verified)

| Trigger | Site | Notes |
|---|---|---|
| Periodic tick, 5 min | `hvac.py:1356-1360` `async_track_time_interval(..., HVAC_DECISION_TICK)`; const `hvac_const.py:13` | "rung-1 module const, cloud API call-rate bound — change requires review" |
| Initial cycle at start | `hvac.py:1363` | |
| Boot-settle release kick (1 s) | `hvac.py:1539-1547` `async_call_later(..., 1, self._async_decision_cycle)` | only when boot-settle suppressed ≥1 cycle |
| House-state change | `hvac.py:3131` (`_handle_house_state_changed`, subscribed `hvac.py:1131`) | |
| Pre-arrival | `hvac.py:4002` (`_handle_person_arriving`, subscribed `hvac.py:1187`) | |
| **Room / zone occupancy change** | **none** | Dispatcher subscriptions are only HOUSE_STATE, ENERGY_CONSTRAINT, PERSON_ARRIVING, SAFETY_HAZARD, ZM_ZONES_UPDATED (`hvac.py:1131-1213`). The only state listeners are climate entities (arrester `hvac_override.py:1996`, short-cycle `hvac.py:4232`) and covers. |

Consequences:
- **Entry latency = up to one 5-min tick + zone entry dwell (live 2 min).** A hot-room entry can take ~7 min to act.
- The **occupancy fast path was DESIGNED, never built**: commit `82620357a` names `HVAC_DECISION_TICK=5min` as "a hard
  floor on fast-in ... needs event-driven path"; `HVAC-SUPPLE-SEQUENCE-1` step 5 lists it as conditional. It lives in W2.
- Carrier cloud refresh after a write takes **42–79 s** (`hvac_override.py:147-150`); arrester temp-suppression is
  only **5 s** (`hvac_override.py:129`) — URA's own write echoes that arrive later are booked as overrides.

---

## 3. Occupancy model — room → zone → retreat

### 3.1 Room producer (`hvac_zones.py`, `ZoneManager.update_room_conditions`)
| Piece | Site | Live? |
|---|---|---|
| `RoomCondition.hvac_occupied` sibling of `.occupied` (lighting signal NOT swapped) | producer loop, `_hvac_seen.add` at `hvac_zones.py:988` | LIVE (v5.103.7) |
| Per-room-type tail-hold (day) `ROOM_TYPE_HVAC_HOLD` | `const.py:1219-1224` — bedroom 60 s, media 120 s, common 60 s, **hallway 0** | LIVE |
| Night tail-hold `ROOM_TYPE_HVAC_HOLD_NIGHT` (D8) | `const.py:1230-1242` — bedroom/media **30 min**, common 15, generic/bath/garage/utility 10, closet/infra 5, hallway 0 | LIVE |
| Per-room override knobs `CONF_HVAC_VACANCY_HOLD[_NIGHT]`, night ≥ day clamp | `_effective_hvac_hold_seconds` `hvac_zones.py:894` | LIVE (v5.103.8 made them config-flow fields) |
| Hallway circulation exclusion (`hvac_occupied` always False, still marked seen) | `hvac_zones.py:650-665` (`arm_source="hallway_excluded"`) | LIVE — 7 hallways, 0 `on` rows in 7 d (v5.103.7 README write-back) |
| Coordinator-absent room → synthetic `RoomCondition(occupied=False, hvac_occupied=False)` | `hvac_zones.py:616-641` | pre-existing (Bug Class #43). **Hazard:** a reloading room reads "empty" (§9.4) |
| Per-room diagnostic `binary_sensor.<room>_<room>_hvac_occupied` (~43, doubled slug) with `established` attr | `binary_sensor.py:745`, `:911-916` | LIVE (v5.103.8) |

### 3.2 Zone rollup & retreat gate
| Piece | Site | Semantics |
|---|---|---|
| `zone.any_room_hvac_occupied` (fused) | producer; exposed `hvac_zones.py:751` on `sensor.ura_hvac_coordinator_zone_{n}_status` | OR over rooms' `hvac_occupied` |
| `is_zone_hvac_established(zone_id)` | `hvac_zones.py:1043` (all at `:1083`) | develop: **every room in `zone.rooms` in `_hvac_seen`** (round-5 revert `f88f4bc84`). v5.103.15 branch changes this (§11 W2, §10) |
| `conditioning_retreat_ok(zone)` | `hvac_zones.py:1085`; delegate `HVACCoordinator._zone_conditioning_retreat_ok` `hvac.py:3830` | **established AND fused-empty**; person-trust only covers the *unestablished* post-reload gap (**reset-only backstop**, operator round-4 decision 2026-09-17). Never raises; fail-closed |
| Consumers of the gate | row-1 preset flip `hvac.py:2013`; D7 night-trust `hvac.py:2403`; D9 compose-away `hvac.py:2966`; F4 row-10 arrester comfort-delay **direct** `hvac_override.py:2319` (tri-state guard `:2304-2340`, raw fallback `:2336`) | all trust decisions |
| Consumers of establishment directly | `conditioning_retreat_ok` (`hvac_zones.py:1112`); `binary_sensor.py:914` (display) | `hvac.py:3820-3826 _is_zone_hvac_established` has **zero callers** (dead) |
| Readers that BYPASS the gate (read fused signal raw) | D5 energy-shed occupancy defer `hvac.py:2271-2289`; D6 stale failsafe `hvac.py:2063` + `presence.py:2148-2157`; `hvac.py:2739-2741` ledger, `:4190-4191` presence display; `hvac_predict.py:583` (pre-cool F8), `:1386` (pre-heat F9); `hvac_zones.py:746-754` `continuous_occupied_since` | see §9.4 (carded `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`) |
| Zone entry dwell | `hvac.py:2355-2368` — skips preset change while a zone's **lighting** session (`zone.any_room_occupied`, `current_session_start`) is younger than dwell; not for pre-arrival; not when target is away | **LIVE value 2 min** (operator 2026-09-26; stored option `hvac_zone_entry_dwell: 2`). v5.103.7 D5 meant default 0 but only migrated an exact 3; install had 5 |
| Vacancy grace | option `hvac_vacancy_grace_minutes: 10` (const default 15, `hvac_const.py:374`); constrained `5` | LIVE |

### 3.3 Live vs dormant
| Layer | State | Gate |
|---|---|---|
| Preset-layer retreat (row-1), incl. **night** retreat of empty zones | **LIVE** | `conditioning_retreat_ok` |
| D7 night-trust suppression (zone_persons home) — only when zone NOT cleared to retreat | **LIVE** | `hvac.py:2403` |
| D8 night tail-hold | **LIVE** | `const.py:1230` |
| D9 compose-away (Custom Preset Ranges setpoint layer), F2 throttle bypass, F4 | **DORMANT** — `switch.ura_hvac_coordinator_guest_mode_actuation` = off (13/13 recorded states 09-18→25); gate `hvac.py:2867` | blocked on `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` + `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` |

---

## 4. Thermostat I/O — writes, funnels, logging, reads

### 4.1 Funnels (`hvac_setpoint.py`)
| Funnel | Site | What it adds |
|---|---|---|
| `emit_set_temperature` | `hvac_setpoint.py:223-279` | freeze / comfort-delay gate, site/zone/reason plumbing. **Logs nothing durable** (only a `comfort_delay_deferred_write` row when a gate defers, `:108-159`) |
| `emit_set_preset_mode` | `hvac_setpoint.py:282-410` | **resume-then-pin** (v5.103.2): if the entity lists `resume` in `preset_modes` and `hold_activity == "manual"`, send `resume` then pin, with one retry (`:317-410`); capability check not vendor check (`:199-212`). D6 reason capture (`zone_id`+`reason` kwargs). Logs nothing durable itself |
| `emit_set_hvac_mode` | **does not exist** | 7 raw `set_hvac_mode` sites bypass (card `HVAC-SETHVACMODE-CHOKEPOINT-1`) |

### 4.2 Write sites (verified by Explore audit 2026-09-25 against develop; spot-checked)
| Site | Verb(s) | Via funnel | Durable record |
|---|---|---|---|
| S1 house-state/occupancy preset `hvac.py:2674` | preset (+hidden resume) | yes | **`ura_activity_log` `preset_change`** (`hvac.py:2716-2748`), lockout `preset_change_locked_out` (`:2504-2519`) once per episode |
| heat_cool enforcer `hvac.py:1926-1938` | hvac_mode | **no** | INFO only |
| S10 DPM custom ranges `hvac.py:3046` | setpoints | yes | INFO only (dormant) |
| S3 arrester compromise `hvac_override.py:3393` | setpoints | yes | `hvac_excursion_events` |
| S4 arrester revert `hvac_override.py:3519/3547` | mode + preset | mode **no** | `hvac_excursion_events` |
| AC hard reset off/restore/retry/preset `hvac_override.py:3888/4006/4041/4113` | mode + preset | mode **no** | `ac_ramp_events` |
| **S5 soft-nudge start** `hvac_override.py:4423` | setpoints (+`nudge_size` to high) | yes | `ac_ramp_events` `nudge_started` |
| **S6/S7 nudge restore** `hvac_override.py:4595` (setpoints, no zone_id/reason) then `:4640` (preset, blocking) | setpoints then preset | yes | `ac_ramp_events` `nudge_restored` + settled verdict |
| S8 cancel-nudge (button) `hvac_override.py:5815/5841` | setpoints + preset | yes | `ac_ramp_events` |
| S9 boot ramp audit `hvac_override.py:6221/6245` | setpoints + preset | yes | `ac_ramp_events` |
| Excursion lease-expiry auto-return `hvac_excursion.py:667` | preset | yes | non-nudge kinds only |
| S11 banking release `hvac_predict.py:979/1040`; S12 pre-cool `:1160`; S13 pre-heat `:1448/1511/1560` | setpoints + preset | yes | `hvac_excursion_events` |
| Egress pause/resume `hvac_egress.py:683/779/795` | mode + preset | mode **no** | `hvac_excursion_events` |
| Optimizer `optimization.py:3546` (shadow by default) | any | — | `actuated` row, no entity_id |

### 4.3 Logging coverage — the answer to "do we record everything?": **NO**
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
| **Local PATCH** service `ha_carrier.set_activity_setpoint`: edits the CURRENT activity's setpoints **in place, no hold** (`set_config_activity`), does not touch hold/status activity | `climate.py:91-103`, `:539-600`, `services.yaml`; files dated **2026-09-24 21:48**. **Provenance UNVERIFIED** (not in URA git history); **URA does not use it** (0 references). Caveat: it mutates the named profile (e.g. "home") itself |
| `manual` is in `preset_modes` on all 3 zones (restoring `manual` is legal) | `PLANNING_hvac_governed_excursion.md` rev-6 note (live-verified 2026-08-21) |
| After a borrow returns, a later poll can deliver `preset_mode=manual` while `hold_activity` = home/sleep, sometimes with stale nudge setpoints; lasts until a vacancy/away write | recorder traces 09-21 12:53, 09-22 01:19, 09-24 19:57, 09-25 14:22 (§9.1). **Whether the physical thermostat was in manual: UNVERIFIED** |
| Remaining Bryant schedule on zone_1: one daily **6 AM Home 70–76** (operator screenshot 2026-09-25); others removed **2026-09-20 11:39 CDT** (dated from `next_activity_time` in recorder). Zones 2/3 still run 4-entry schedules (06/08/17-18/22). With infinite holds, a schedule only acts when no hold is active | recorder `next_activity_time` |
| Code comment "the operator does not use the Bryant schedule" (`hvac_setpoint.py:164-167`) | **WRONG** as of 09-20 (schedules existed; a 6 AM entry remains) — §10 |

---

## 6. Borrow / excursion primitive + nudge / AC ramp

| Fact | Site |
|---|---|
| Primitive: `begin_excursion` snapshots pre-preset + pre-setpoints, persists `hvac_excursion_state` row | `hvac_excursion.py:766` |
| `return_excursion` is **bookkeeping only** — drops row, logs outcome, surfaces restore failure (`[GOVERNED BORROW RESTORE FAILED]` + per-episode NM latch). **It performs NO wire writes: each call site emits its own (a) set_temperature → (b) set_preset_mode → (c) set_hvac_mode** | `hvac_excursion.py:871-1040` (docstring `:886-888`) |
| Kinds: NUDGE, COMPROMISE, BANKING, PREHEAT, EGRESS_PAUSE (`HARD_RESET_PRESET_ASSERT` deliberately absent) | `hvac_excursion.py:94-104` |
| Lease gate **stripped** (rev-6, 4× DO-NOT-SHIP: a stuck lease with no discharge is worse than the lockout it replaced) — do not rebuild it as designed | `PLANNING_hvac_governed_excursion.md` rev-6 banner |
| Boot audit clears NUDGE/BANKING rows (NUDGE restores snapshot preset first) | `hvac_excursion.py:175+` (`async_startup_excursion_audit`) |
| Soft nudge: `check_ac_reset` each cycle (`hvac.py:1745`); start S5 raises `target_high += nudge_size` (live **1.5 °F**) for `nudge_duration` (live **2 min**; const default 5); restore S6 raw setpoints → S7 snapshot preset (unconditional, blocking); settled verdict at `AC_NUDGE_RESTORE_SETTLE_DELAY_S = 180` (`hvac_const.py:672`) | `hvac_override.py:4339-4440`, `:4580-4650` |
| Nudge cadence ~25 min (hold + 240 s eval delay + samples) — matches observed overnight/midday rhythm | `hvac_const.py:665`; live eval delay 240 |
| Nudge runs only if ramp master ON (live options `hvac_ac_ramp_master_enabled: True`; const default False `hvac_const.py:571`), `switch.ura_hvac_coordinator_26_ac_nudge` ON (live), zone has `ac_load_sensor`, cooling, at/below setpoint, kWh above per-zone threshold (live zone_1 1.5, zones 2/3 2.2) | `hvac_override.py:3677-3845`; live numbers |
| Hard reset (mode off→on) budgets: live day 2 / night 2 / daily limit 2 / min interval 30 min | live numbers |
| Operator policy: **nudges stay ON** (2026-09-25) | chat |

---

## 7. Arrester, lockout, hold knobs — why nothing reclaims a zero-delta manual

| Mechanism | Site | Effect on a manual hold sitting at the preset's own setpoints |
|---|---|---|
| S1 refuses to write a preset over `manual`: "Don't fight manual — that's the arrester's job" | `hvac_preset.py:212-217`; S1 logs `preset_change_locked_out` `hvac.py:2484-2539`; only bypass = forced vacancy/runtime away `:2481-2483` | locked out until the zone leaves manual |
| Arrester reverts only if setpoints moved ≥ `OVERRIDE_NORMAL_DELTA` 1 °F (severe 3 °F); +1 °F under coast | `hvac_const.py:531-532`; `hvac_override.py:3187-3203` | delta ≈ 0 → "within tolerance" → no revert |
| Operator-immune hold (`CONF_HVAC_ARRESTER_IMMUNE_PERSONS`) sunset: next_activity / durable house state / 4 h | `hvac_const.py:189-198`; `hvac_override.py:713-811` | sunset hands back to the arrester — does NOT clear the hold (`:727-729`) |
| Temp Arrester Override switch (live off), max 6 h | `hvac_const.py:205`; `switch.py:2429-2468` | same — hands back only |
| Comfort Grace (live **20 min**; default 30) | `hvac_const.py:452-456` | grant expiry writes nothing (`hvac_override.py:2694-2716`) |
| Suppression windows: temp 5 s vs Carrier refresh 42–79 s | `hvac_override.py:129`, `:147-150`; preset-window pass-through `:2455-2466` | URA's own late echo → `override_detected` |
| **Net:** no timeout releases the lockout; a URA-caused or stale `manual` at zero delta is **never reclaimed** except by a forced-away write | — | operator 2026-09-25: *"Without that knob, why would we not override? arrester is an override."* |

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
| `switch.ura_hvac_coordinator_hvac_consensus_defer_gate` / `_pre_arrival_conditioning` / `_hvac_pre_conditioning` | on / on / on |
| `number.ura_hvac_coordinator_zone_entry_dwell` | **2** (set 2026-09-26 02:58Z) |
| vacancy delay / energy-saving vacancy delay / max zone occupied time | 10 / 5 min / 4 h |
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
— each shows `preset_mode=manual` with `hold_activity` = home/sleep and stale or unchanged setpoints, booked as
`override_detected` (09-24/25 logged "76->76"), then `preset_change_locked_out`; 1 failed restore (09-20 17:33,
`restore_ok=0`, 115 min); 2 human step-downs (74/68, ~2 h, no URA event). Mechanism = §5 status-vs-config split + §7
lockout + infinite holds. Fix direction (W1): presets-only returns; manual counts as human only if CONFIG
`hold_activity == manual`; URA-owned/stale holds reclaimable.

**9.2 URA cannot see its own setpoint/mode writes** (§4.3) — made every diagnosis on this surface fragile.

**9.3 Night still-sleeper lost by radar (Jaya, zone_2).** 09-24 02:47 and 09-25 02:09 zone_2 retreated with Jaya home:
her phone (`sensor.iphone_jaya_area`, Bermuda) stationary in-suite all night; `fan.fanswitch_treat_wifi_jayabedroom`
off at 01:31 / 01:36 → `binary_sensor.jaya_3_presence` off one minute later → only micro-blips on
`binary_sensor.mmwave_zigbee_jayabedroom_presence` → gaps > 30-min D8 hold. Zigbee radar **unavailable since
2026-09-25 19:32**; `sensor.seeedstudio_mmwave_kit_047d34_existence_energy` unavailable both nights. Card
`HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1` (trigger fired). Constraint: zone-scoped only, never "anyone home".

**9.4 Readers that act on a reloading room's synthetic "empty"** (pre-existing; reviewers B+D of v5.103.15): D5 coast
defer `hvac.py:2271-2289` can force an occupied zone away for one tick (and retreat an all-dead zone under coast); D6
Source-4 count `presence.py:2148-2157`; `continuous_occupied_since` reset `hvac_zones.py:746-754`. Card
`HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1`.

**9.5 Hot entry latency** — 5-min tick + dwell (§2). No occupancy-triggered cycle exists.

**9.6 Broken-room gate** — develop's `all(zone.rooms)` lets one disabled/failed room block its zone from ever retreating
(round-5 orchestrator override of the operator's round-4 rule). Fix in flight v5.103.15 (§11).

**9.7 Custom Preset Ranges blocked** by two write-governance defects (unconditional throttle bypass; restore writers
don't update `_last_emitted_range` `hvac.py:521`).

**9.8 Smaller:** v5.103.7 README INV-2 latency oracle inconclusive; v5.103.3 boot preset-restore path unexercised;
v5.103.14 main criteria unexercised; zone rooms frozen at discovery (added-room not counted until restart).

---

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
| C12 | Code comment "operator does not use the Bryant schedule" | Schedules existed until 09-20; a 6 AM Home entry remains on zone_1; zones 2/3 still scheduled | `hvac_setpoint.py:164-167` vs §5 |
| C13 | "the borrow return writes setpoints then preset" (framed as the primitive's behaviour, 09-25) | The primitive writes nothing; each SITE writes (a)→(b)→(c) itself — the ordering lives in N copies | `hvac_excursion.py:886-888` |
| C14 | Enphase/"stream SOC 52 untrustworthy" and similar non-HVAC corrections | See energy docs / `project_session_pickup_2026_09_23` | — |

---

## 11. The approved arc (operator-approved 2026-09-26: "The workstreams are approved. Recard.")

| Seq | Workstream / step | Problems (§9) | Tier / gate |
|---|---|---|---|
| 0 | **v5.103.15 live-room establishment** (in review) — establishment over rooms actually running: excluded = disabled / SETUP_ERROR / MIGRATION_ERROR / SETUP_RETRY; transient (loading) rooms BLOCK; live rooms must be LOADED + coordinator-present + seen; all-dead zone never retreats. Plan `docs/planning/PLANNING_hvac_live_room_establishment.md` REV 2 | 9.6 | Tier 2-DB + mandatory D; fix-up pending (reviewers B/D: failed-room sticky exclusion, hold preset while transient-blocked & fused-empty, deleted-room exclusion, NM `location`, UTC grace clock) |
| 1 | **W1-A Thermostat I/O governance, behaviour-neutral:** all 3 verbs through funnels (add `emit_set_hvac_mode`, migrate the 7 raw sites); ONE durable row per actual write (verb, zone, site, values, reason) | 9.2, part of 9.1 | Tier 2-DB |
| 2 | **W1-B Thermostat definition (per-BRAND strategy):** a simple generic interface — how to *hold a named preset*, *borrow & return*, *read the observed hold* — with the brand's behaviour **discovered and defined in detail** (Carrier/Bryant first: resume-then-pin; presets-only returns for EVERY borrow kind; manual counts as human only when CONFIG `hold_activity == manual`; URA-owned/stale holds reclaimable; knob timeouts actually release; funnel skips no-op writes and owns `_last_emitted_range`). Generic default = direct pin; **Nest strategy only when a Nest is available to test.** Runtime state stays per thermostat ENTITY (it already is: `_last_emitted_range` `hvac.py:521`, `_suppressed_until` `hvac_override.py:235`, `_nudge_pre_preset` `:262`, `_override_active` `:205`, excursion `_rows` `hvac_excursion.py:201` — all keyed by zone_id/entity); **no per-zone handle class is needed** — one definition per brand + existing per-entity state. Evaluate the local `set_activity_setpoint` no-hold patch (§5) as a nudge write that creates no hold — provenance must be verified first | 9.1, 9.7 blockers | **Tier 3** — operator go required |
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
