# PLANNING — HVAC readers that treat a reloading room as "empty"

**Card:** `HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1` (workstream `HVAC-W2-OCCUPANCY-TRUTH`, status `planned`, approval `unreviewed`)
**Author:** ura-planner, 2026-09-27. Snapshot `develop` @`e873d1abe` (v5.103.18 shipped).
**Status:** PLAN, gated on the D0 measurement probe. No build until D0 reports.
**Tier:** Tier 2-DB (three framing-disjoint reviews) plus ONE plan review before build. See §7.

---

## 0. Institutional context verified

**State of play read completely:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, all 470 lines, including §9e (the W1-B four-gate rule) and the §10 corrections ledger C1–C25. Nothing in this plan re-asserts a §10 claim. The plan respects C24: HVAC occupancy rides lighting `STATE_OCCUPIED` plus a tail. It is not a separate, faster clock.

**Stale citations in the state-of-play doc** (the code wins; the orchestrator should fix these in the commit that lands this plan):

| Doc says | Code today |
|---|---|
| §3.1 placeholder `hvac_zones.py:616-641` | `hvac_zones.py:680-711` |
| §3.2 / §9.4 D5 defer `hvac.py:2271-2289` | `hvac.py:2643-2719` |
| §3.2 D6 `hvac.py:2063` | `hvac.py:2437-2446` (row-4) |
| §3.2 / §9.4 `continuous_occupied_since` `hvac_zones.py:746-754` | `hvac_zones.py:771-779` |
| §3.2 pre-heat `hvac_predict.py:1386` | `hvac_predict.py:1420-1424` |
| §3.2 dead delegate `hvac.py:3820-3826` | `hvac.py:4437-4446` (still zero callers) |
| §8 entry dwell = **2** | §2 says it is **0** (operator 2026-09-26 evening). The doc contradicts itself; read the live value before relying on it |

**Greps run** (production code, tests excluded): `any_room_hvac_occupied|any_room_occupied|continuous_occupied_since|is_zone_hvac_established|conditioning_retreat_ok|_coordinator_absent`, `room_conditions|zone_presence_state|occupied_rooms|\.hvac_occupied`, `check_zone_occupancy_confidence|is_zone_transient_blocked|_zone_conditioning_retreat_ok(`, `preset_change_reason =`, `_unrecorded_attributes`. The results are in §2.

**Prior plans and READMEs:** `PLANNING_hvac_live_room_establishment.md` REV 2 (grepped for transient and reload semantics, the mutation table and the test names) and `README_v5.103.15.md`. The README's live row 2 says *"`transient_rooms` was never observed non-empty — rooms loaded before the first sampled state"*. That README also documents the D5 exception this plan narrows: *"D5 shed/coast force-away still write"*.

**Memory:** `project_reload_storm_refuted_restart_storm_live` (2026-09-19). It says the "URA reloads ~5x/night" storm was REFUTED: restarts and URA setups matched 1:1, with zero restart-free setups after 09-16. The live problem is whole-HA restarts (8 on 09-18). This bears directly on §5: room reloads may be rare, and restarts may be the real trigger.

**Code read end-to-end for scope:** `hvac_zones.py` (ZoneState `:100-217`, producer `:590-788`, zone attrs `:790-894`, snapshot `:896-969`, classifier `:1150-1288`, helpers `:1325-1558`); `hvac.py` (setup `:1048-1273`, decision cycle entry `:1583-1607` and `:1923-1929`, `_apply_house_state_presets` `:2270-2920`, reason ladder `:3032-3086`, D9 `:3465-3524`, pre-arrival expiry `:4624-4649`, delegates `:4437-4463`, `_compute_zone_presence_states` `:4775-4820`); `presence.py:2057-2161`; `hvac_override.py:2470-2564` and `:2685-2723`; `hvac_predict.py:440-679`, `:1235-1264`, `:1400-1440`; `hvac_fans.py:740-777` and `:970-1007`; `hvac_egress.py:505-528`; `optimization.py:2395-2454`; `energy.py:8486-8509`; `binary_sensor.py:795-823`; `database.py:1352-1363`; `scripts/probes/hvac_vacancy_grace_probe.py` (the recorder access pattern).

### REUSE-or-BUILD verdict per piece

| Piece | Verdict | Symbol |
|---|---|---|
| "Zone may retreat" predicate for D5 | **REUSE** | `HVACCoordinator._zone_conditioning_retreat_ok` `hvac.py:4448` → `ZoneManager.conditioning_retreat_ok` `hvac_zones.py:1522` |
| "A room in this zone is reloading" predicate for D6, the occupancy clock and the row-11 grant | **REUSE** | `ZoneManager.is_zone_transient_blocked` `hvac_zones.py:1420` (already used by the row-1 hold `hvac.py:2366-2374` and the D9 hold `hvac.py:3504-3511`) |
| Per-tick transient flag inside `_apply_house_state_presets` | **REUSE** | the local `_transient_blocked_row1` `hvac.py:2370`, computed before D6 and D5 in the same `if zi:` block |
| Time bound on every deferral | **REUSE** | `HVAC_LIVE_ROOM_TRANSIENT_GRACE_S = 300` `hvac_const.py:938`: a room that stays transient past it becomes EXCLUDED (`hvac_zones.py:1250-1258`) |
| D5 defer ledger row | **REUSE + EXTEND** | the existing episode-gated `preset_change_suppressed` row `hvac.py:2673-2709`; one new detail key, `defer_basis` |
| Measurement probe | **NEW** (read-only script) | no probe measures room reloads; the nearest is `hvac_vacancy_grace_probe.py`, whose access pattern it copies |
| New constants, knobs, signals, sensors | **none** | — |

---

## 1. Producer check: where the "empty" comes from

- **Placeholder producer:** `ZoneManager.update_room_conditions`, `hvac_zones.py:680-711`. When `hass.data[DOMAIN][entry_id]` has no room coordinator, the room gets a synthetic `RoomCondition(occupied=False, hvac_occupied=False, …)`. The placeholder still carries window state and the egress flag, which is the Bug Class #43 fix. The room is also added to `_coordinator_absent_this_pass` (`:686`).
- **Room classification**, `_classify_all_rooms` `:1150-1288`, runs once per pass before the zone loop (`:664`):
  - LIVE = the entry is LOADED.
  - TRANSIENT = NOT_LOADED, SETUP_IN_PROGRESS, UNLOAD_IN_PROGRESS, FAILED_UNLOAD, or an unknown state. After 300 s a transient room becomes EXCLUDED.
  - EXCLUDED = disabled, SETUP_ERROR, MIGRATION_ERROR, SETUP_RETRY (sticky), or the entry was removed.
- **Fused zone signals** (`:172-188`): `any_room_hvac_occupied` and `any_room_occupied` are plain ORs over `room_conditions`. A placeholder contributes False to both.
- **When the placeholder is correct and when it is not.** For an EXCLUDED room, False is correct: operator option (a) says the room counts toward nothing. For a TRANSIENT room, and for a LIVE room whose coordinator is missing, False is a lie. That lie is this card's subject.
- **The v5.103.15 gate:** `is_zone_hvac_established` `:1445-1520` returns False if any room is transient. `conditioning_retreat_ok` `:1522-1558` = established AND fused-empty, and fails closed.
- **When the producer runs:** every 5-min tick (`hvac.py:1925`), and once at CM setup (`hvac.py:1270`). The setup pass comes **right after** `restore_state_snapshot` (`hvac.py:1061`) and **before** boot-settle releases. If a zone's rooms are not LOADED yet on that setup pass, the pass sees placeholders. This matters for D3; see §5 P3.

## 2. Consumer map: every reader of room or zone occupancy in HVAC and related paths

Legend: **ROUTES** = goes through `conditioning_retreat_ok` or `is_zone_transient_blocked`. **BYPASS** = reads the raw fused or per-room value. **Trust** = drives a write or a decision. **Display** = sensor or attribute only.

| # | Reader | file:line | Reads | Routing | Kind | What a reloading room's placeholder causes | Scope |
|---|---|---|---|---|---|---|---|
| R1 | Row-1 retreat plus transient hold | `hvac.py:2339-2404` | `_zone_conditioning_retreat_ok`, `is_zone_transient_blocked` | ROUTES | Trust | Nothing: no retreat, and the write is held | covered by v5.103.15 |
| R2 | **D5 coast occupancy defer** | `hvac.py:2643-2719` | raw `any_room_hvac_occupied` | **BYPASS** | Trust | With EC coast, `runtime_exceeded`, a non-sleep house state and a zone whose only HVAC-occupied room is reloading: fused is False, so D5 skips its defer and writes **`away`** (reason `energy_shed_cap_reached`, `:3040`). It also **clears the row-1 hold** (`:2719`), which undoes the v5.103.15 protection. The next tick writes `home` again, a flap costing 2 Carrier writes. If every room in the zone is dead, coast retreats it, although the operator rule says an all-dead zone never retreats | **D1** |
| R3 | **D6 stale-occupancy failsafe** | `hvac.py:2437-2507` + `presence.py:2098-2159` | fused (entry test), then `check_zone_occupancy_confidence` | **BYPASS** | Trust | The zone must already be continuously HVAC-occupied for more than `max_occupancy_hours` (4 h live), outside sleep. A reloading room loses **Source 1** (its coordinator's `_last_motion_time` is missing, `presence.py:2109-2117`; **the card missed this**) and **Source 4** (the placeholder has `.occupied=False`, `:2152-2157`). `confirmed` drops below the threshold, so D6 forces **`away`** (reason `stale_occupancy`), sweeps the lights if lighting reads empty, and sends a stuck-signal NM (`:2513-2519`) | **D2** |
| R4 | **`continuous_occupied_since` write** | `hvac_zones.py:771-779` | raw `any_room_hvac_occupied` | **BYPASS** | Trust (feeds R3 and R14) | If the reloading room was the zone's only HVAC-occupied room, the clock **resets to None** and restarts after the reload. On a live reload this delays D6 (the safe direction). **At boot the setup pass (`hvac.py:1270`) may throw away the restored snapshot value on every HA restart, which would disarm the 4 h stuck-sensor failsafe for good under a restart storm. UNVERIFIED; D0 P3 tests it** | **D3** |
| R5 | `last_occupied_time` write | `hvac_zones.py:771-773` | raw fused | bypass | Trust input to R1 | It stops refreshing during the placeholder but is never reset. R1 is gated anyway | no action |
| R6 | D7 night-trust | `hvac.py:2780-2784` | `_zone_conditioning_retreat_ok` | ROUTES | Trust | Nothing | covered |
| R7 | D9 compose-away (dormant) | `hvac.py:3498-3518` | transient hold + retreat gate | ROUTES | Trust | Nothing | covered |
| R8 | Row-10 `comfort_delay_active` | `hvac_override.py:2525-2552` | `conditioning_retreat_ok` (tri-state) | ROUTES | Trust | Nothing: keeps deferring | covered |
| R9 | **Row-11 comfort-grace grant** | `hvac_override.py:2702-2722` | lighting `any_room_occupied` (lighting on purpose, D-MED-1) | **BYPASS** (**card missed**) | Trust | A person changes the thermostat by hand while the zone's only lighting-occupied room is a placeholder from the last tick. There is **no grant**, so the arrester skips comfort grace and handles the change by delta (revert or compromise), which is hostile to that person | **D4** |
| R10 | Pre-cool F8 | `hvac_predict.py:583-595` | raw fused | bypass | Trust (borrow start) | The zone is skipped for **one tick**; `_should_energy_precool` is re-checked every tick. No wrong write | non-goal |
| R11 | Pre-heat F9 | `hvac_predict.py:1420-1424` | raw fused | bypass (**card missed**) | Trust (borrow start) | Pre-heat fires **once a day** (`_pre_heat_triggered_today`, `:660-667`, window 05:00–06:00). A zone skipped on that tick **misses pre-heat for the day**. Only in winter, and only if a reload lands on that one tick | non-goal (see §9 revisit trigger) |
| R12 | Pre-arrival clear | `hvac.py:4633-4640` | lighting fused | bypass | Trust | The clear is delayed until the next tick or the timeout, so conditioning continues (the safe direction) | non-goal |
| R13 | Entry dwell / `current_session_start` | `hvac_zones.py:783-788`, `hvac.py:2738-2748` | lighting fused | bypass | Trust | The session clock restarts. Harmless while dwell is 0 (the guard `dwell_minutes > 0`). The dwell clock itself belongs to card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` | non-goal |
| R14 | Optimizer stuck-occupancy advisory | `optimization.py:2410-2441` | `continuous_occupied_since` | via R4 | Advisory | Fires later. **Fixed by D3** | via D3 |
| R15 | `zone_presence_state` | `hvac.py:4807-4820` → `sensor.py:13712-13753`, `hvac.py:5523-5527` | raw fused | bypass | Display | Shows "vacant" or "away" for a tick | non-goal |
| R16 | Room fans (temp, sleep onset) | `hvac_fans.py:755-761`, `:986-1001` | per-room `.occupied` / `.temperature` | bypass | Trust | The placeholder is the reloading room's **own** fan, with `temperature=None`. The temp-fan path needs a non-None temperature (`:774`) and sleep onset gets `room_temp=None`, so both skip. Nothing wrong is written | non-goal |
| R17 | Pre-arrival fans | `hvac_predict.py:1238-1252` | room coordinator | skips the absent room | Trust | Skipped | non-goal |
| R18 | Egress window | `hvac_egress.py:519-527` | `window_state` / `is_egress_window` | the placeholder carries both | Trust | Correct by design (Bug Class #43) | n/a |
| R19 | Per-room `hvac_occupied` sensor, `established` attr, zone status attrs, ledger details | `binary_sensor.py:805-823`, `:919`; `hvac_zones.py:817-834`; `hvac.py:2706`, `:2897`, `:3247` | raw | bypass | Display | A one-tick display flicker | non-goal |
| R20 | EC occupancy counts | `energy.py:8486-8509` | **presence** zone trackers, not the HVAC ZoneManager | n/a | Telemetry | Outside this producer | out of scope |

**Dead code noted:** the delegate `hvac.py:4437 _is_zone_hvac_established` has no callers. Bucket: KEEP + DOCUMENT. Not touched here.

## 3. Config-first check

No setting fixes this, and none is proposed.

- Every lever that suppresses the symptom kills a feature: the D5 switch `switch.ura_hvac_coordinator_hvac_d5_duty_cycle_enable`, a very large max-zone-occupied-time (which disables D6), and the Zone Intelligence switch (which disables D1/D5/D6 entirely).
- `HVAC_LIVE_ROOM_TRANSIENT_GRACE_S` is a rung-1 constant and not the defect.
- Telling the operator not to edit room options during coast is not a fix.

## 4. The fix: four small consumer changes, reusing the existing gate

All four are consumer-side changes. The v5.103.15 gate and helpers are **not modified**.

### D1 — D5 coast defers whenever retreat is not authorized
At `hvac.py:2657-2661`, replace the defer condition `_row2054_fused` with `not _retreat_ok`. `_retreat_ok` comes from the row-1 call at `:2339`: store it in a local that is **hoisted to the loop top** next to `_row1_hold_write` (`:2307-2309`, the round-3 zi-off UnboundLocalError lesson). **Do not call the helper a second time.**
- **Behaviour change, exactly one cell:** a zone that is **unestablished and fused-empty, under coast (not shed)** now DEFERS instead of writing `away`. Every other case is byte-identical: established+empty still goes away; occupied still defers; **shed still forces away and still clears the row-1 hold**.
- **Operator-visible ruling:** this narrows the v5.103.15 README's "D5 shed/coast force-away still write" to **shed only**. Record it in the README.
- **Ledger:** the existing `preset_change_suppressed` row keeps reason `energy_shed_cap_deferred_occupied`. It gains `details.defer_basis` ∈ {`"occupied"`, `"room_reloading"`, `"unestablished"`}. Precedence: fused → occupied; else `_transient_blocked_row1` → room_reloading; else unestablished. `defer_basis` joins the episode key at `:2673-2676`. The description becomes `f"{zone.zone_name} D5 forced-away suppressed (coast + {basis_text})"`, where basis_text is `occupied` / `room reloading` / `zone not confirmed`.
- **Fail direction:** `_zone_conditioning_retreat_ok` fails closed, so an exception means defer under coast. That is acceptable because shed is unaffected.

### D2 — D6 skips its verdict while a room in the zone is reloading
At `hvac.py:2440-2446`, add the conjunct `and not _transient_blocked_row1`. While it holds, D6 neither resets the timer nor forces away. It logs one DEBUG line and **no NM**.
- **No change to `presence.py`.** The card's proposal to make Source-4 exclude absent rooms does not work: taking the room out of the count does not bring back its lost confirmation, and Source 1 would still miss it. `check_zone_occupancy_confidence` has exactly one caller (`hvac.py:2459`).
- **Discharge:** the deferral is bounded by the 300 s grace. After that the room becomes EXCLUDED, and D6 then judges only the remaining rooms, per operator option (a).

### D3 — the occupancy clock is not reset while a room in the zone is reloading
At `hvac_zones.py:777-779`, the reset branch becomes `elif not self.is_zone_transient_blocked(zone.zone_id): zone.continuous_occupied_since = None`. Classification has already run for this pass (`:664`), so the snapshot is consistent. The set branch is unchanged.
- **Discharge:** the same 300 s grace. On a boot pass where the rooms are still NOT_LOADED or SETUP_IN_PROGRESS, the restored snapshot value (at most 4 h old, `:934`) survives until the first real pass.
- **Rejected alternative:** gating the reset on "unestablished". An all-dead zone would then keep a stale clock forever, and D6 or the optimizer advisory would fire the moment a room revived.

### D4 — the row-11 grace grant counts a reloading room as possibly occupied
At `hvac_override.py:2718`: `occupied = bool(any_room_occupied) or _tb`, where `_tb = zm.is_zone_transient_blocked(zone_id)`.
- Accept `_tb` only if it `is True` or `is False` (the MagicMock lesson at `:2535-2539`). Anything else counts as False, which keeps today's behaviour.
- Row-11 stays on the lighting denomination (D-MED-1). It only gains the reload case.

**Line-count estimate:** about 40 production lines, plus tests.

### Known residual (accepted, same as v5.103.15)
A room whose entry is **LOADED but whose coordinator is missing** is classified LIVE, not transient. D2, D3 and D4 do not cover it, just as the row-1 and D9 holds do not. D1 does cover it through establishment. It is rare: the coordinator is published before LOADED (`PLANNING_hvac_live_room_establishment.md` REV 2 cites `__init__.py:4959-4962`). Revisit only if the D0 P1 probe counts `coordinator_absent_rooms` sightings with an empty `transient_rooms`.

## 5. D0 — measure before building (the gate)

**NEW read-only script:** `scripts/probes/hvac_reloading_room_probe.py`. Run it once:
`ssh ha "python3 - --days 14" < scripts/probes/hvac_reloading_room_probe.py`
It opens the recorder read-only as `file:/config/home-assistant_v2.db?mode=ro`, following the `hvac_vacancy_grace_probe.py` pattern, and the URA DB read-only at `/config/universal_room_automation/data/universal_room_automation.db`.

| Id | Question | Query |
|---|---|---|
| P0 | Restart ledger | `events` with `event_type` in (`homeassistant_start`, `homeassistant_started`) over 14 d: count per day and timestamps |
| P1 | How often does HVAC see a reloading room on a tick? (since v5.103.15, 2026-09-26) | States of `sensor.ura_hvac_coordinator_zone_{1,2,3}_status` joined to `state_attributes`. Count samples with non-empty `transient_rooms` or `coordinator_absent_rooms`. Classify each as **boot** (inside [start − 60 s, start + 900 s]) or **live** |
| P2 | How often do rooms reload, over the longer window? | Room-reload proxy: for every `binary_sensor.%_hvac_occupied` in `states_meta`, count transitions into `unavailable` **outside** restart windows, with episode duration. Estimate tick exposure as Σ min(1, duration / 300 s). **Self-check first:** confirm that restart windows produce `unavailable` rows on these entities. If they do not, print "proxy blind" and rely on P1 only. Do not assume the proxy works |
| P3 | Does a restart wipe the occupancy clock? (the D3 boot hazard) | For each restart, per zone: the last `continuous_occupied_hours` and `any_room_hvac_occupied` before stop, and the first values after start. **BOOT-RESET** = before > 0, after = 0, occupied both sides. Report n(BOOT-RESET) / n(occupied-across-restart) |
| P4 | Exposure of D5 and D6 (URA DB) | `ura_activity_log` over 14 d, `coordinator='hvac'`: count of `preset_change` rows whose `details_json` reason is `energy_shed_cap_reached` (split by `constraint_mode`) or `stale_occupancy`; `preset_change_suppressed` rows with reason `energy_shed_cap_deferred_occupied` or `transient_room_hold` |

**Go / no-go:**

| Deliverable | Build if | Otherwise |
|---|---|---|
| **D3** | P3 BOOT-RESET ≥ 1, **or** live reloads on a tick (P1 live + P2 estimate) ≥ 1 per week | Park it with the revival trigger "P3 > 0" |
| **D1** | Live reloads on a tick ≥ 1 per week **and** P4 shows ≥ 1 coast `energy_shed_cap_reached` away per week | Park it |
| **D2, D4** | Build only alongside D1 or D3, because the marginal review cost is small once the cycle is open | Park them if both D1 and D3 are parked |
| **All four** | — | If every gate fails, **PARK the whole card** with the triggers in §9. That is a clean result, not a failure |

**Expected outcome, stated as a hypothesis for the probe to test.** v5.103.15 live row 2 never saw a transient room, and the 09-19 memory found zero restart-free URA setups. So the live-reload gates will probably fail. Only P3 is likely to justify a build, which would make this a D3-only cycle.

## 6. Falsifiable invariant

> **INV-PLACEHOLDER.** On any decision tick where zone Z contains a room classified TRANSIENT:
> (a) no `away` preset write to Z carries reason `stale_occupancy`, or reason `energy_shed_cap_reached` with `constraint_mode != "shed"`;
> (b) if fused HVAC occupancy is False, `Z.continuous_occupied_since` after the pass equals its value before the pass;
> (c) a manual thermostat change on Z is never refused comfort grace for want of lighting occupancy.
>
> **Carve-outs, as today:** house-state away and vacation, and EC shed.

**How it is falsified live:** a `preset_change` row with new_preset=`away` and one of the (a) reasons, whose zone status sample at that timestamp shows non-empty `transient_rooms`.

**How it is falsified in-suite:** the §8 tests. Each fails when its site is mutated.

## 7. Tier

**Tier 2-DB: three framing-disjoint reviews, one plan review before build, then live validation and a README write-back.**

- **Why not Tier 1:** these are decision-logic changes on a cost-and-comfort path (D5 energy shed, D6 failsafe). They also touch precedence with the v5.103.15 row-1 hold and with shed dominance. The standing policy says regression-prone work gets three framings.
- **Why not Tier 3:** no shared primitive changes. The gate and helpers stay byte-identical; only four consumers change, and the invariant surface is the fully enumerated §2 table.
- **Suggested review framings:**
  - A = correctness and the single-cell behaviour change (D1 truth table, D3 set/reset asymmetry).
  - B = precedence and no-flap (D5 × row-1 hold × shed; D6 × timer; the boot pass at `hvac.py:1270`; the 300 s discharge).
  - C = test authority through real per-site source mutation.
- **If D0 parks D1, D2 and D4, leaving D3 only:** Tier 1 plus a second reviewer, per the autonomous-Tier-1 rule. D3 feeds a failsafe, so one reviewer is too few.

## 8. Acceptance criteria

### D1 — D5 coast defer
- **Test:** `test_d5_coast_defers_when_zone_has_reloading_room`. Coast, `runtime_exceeded`, home_evening, zone = [Office (only occupant) TRANSIENT placeholder, Study LIVE empty]. Assert no `away` write, `_row1_hold_write` still True, and one `preset_change_suppressed` row with `defer_basis="room_reloading"`. **Mutation:** restore `_row2054_fused` as the defer predicate and this test must go red. (This is Reviewer D's F3 repro.)
- **Test:** `test_d5_coast_all_dead_zone_defers` (`defer_basis="unestablished"`).
- **Test (positive twin):** `test_d5_coast_established_empty_zone_still_forces_away`, byte-identical to today.
- **Test:** `test_d5_shed_with_reloading_room_still_forces_away_and_clears_hold`. Shed dominance is preserved.
- **Test:** `test_d5_retreat_ok_local_hoisted_zi_off_no_unboundlocal`. Drive the real `_apply_house_state_presets` with Zone Intelligence OFF and **no exception-swallowing drive helper** (the round-2 lesson).
- **Live:** on the next coast episode, every new D5 `preset_change_suppressed` row carries `defer_basis`, and no `energy_shed_cap_reached` away with `constraint_mode="coast"` coincides with a non-empty `transient_rooms`. **Discriminates:** before the fix, that coincidence yields an away row; after it, a suppressed row.

### D2 — D6 deferral
- **Test:** `test_d6_skips_verdict_while_room_reloading`. Continuous for more than 4 h, a 2-room zone, one room TRANSIENT, presence confidence below threshold. Assert: no `away`, `continuous_occupied_since` unchanged, no `fire_stuck_signal` task. **Mutation:** drop the conjunct and the test goes red.
- **Test:** `test_d6_resumes_after_room_excluded_past_grace`. At 301 s the room is EXCLUDED and D6 runs on the remaining rooms.
- **Live:** in-suite only. A reload that lands on a tick while a zone has been continuously occupied for 4 h cannot be staged safely.

### D3 — occupancy clock
- **Test:** `test_continuous_clock_not_reset_while_room_reloading`, which exercises the real `update_room_conditions` with a real `ConfigEntryState`. **Mutation:** restore the unconditional reset and the test goes red.
- **Test:** `test_continuous_clock_resets_after_room_excluded` (the 300 s discharge).
- **Test:** `test_boot_pass_keeps_restored_continuous_clock`. Call `restore_state_snapshot`, then run `update_room_conditions` with the zone's rooms in SETUP_IN_PROGRESS. The restored value must survive.
- **Live (only if P3 > 0):** after the next HA restart, for every zone that is HVAC-occupied on both sides of it, `continuous_occupied_hours` on `sensor.ura_hvac_coordinator_zone_{n}_status` at the first sample after start is ≥ the last sample before stop. **Discriminates:** 0 means the defect is still present; ≥ the prior value means the fix works. This is the one criterion the restart storm makes observable.

### D4 — row-11 grant
- **Test:** `test_row11_grants_grace_when_only_occupied_room_reloading`. **Mutation:** revert to the lighting-only read and the test goes red.
- **Test:** `test_row11_magicmock_zone_manager_keeps_legacy_behaviour`.
- **Live:** in-suite only.

### Whole cycle
- **Test:** the suite name-diff against `pre-review-v<version>` shows no new failures.
- **Live:** no ERROR or WARNING from `hvac.py`, `hvac_zones.py` or `hvac_override.py` in the 30 min after restart. Zone status attrs render (`transient_rooms` key present).

## 9. Non-goals

- **Not changing** `conditioning_retreat_ok`, `is_zone_hvac_established`, `is_zone_transient_blocked`, the classifier, or the 300 s grace.
- **No change** to `presence.check_zone_occupancy_confidence`.
- **Pre-cool F8 (R10), pre-arrival clear (R12), dwell clock (R13), `zone_presence_state` (R15), room fans (R16), display readers (R19), EC counts (R20)** stay out of scope, for the reasons given in §2.
- **Pre-heat F9 (R11)** stays out of scope. **Revisit trigger:** winter season, and P2 shows reloads in the 05:00–06:00 window.
- **The LOADED-but-coordinator-absent residual** (§4) stays out of scope.
- **`zone.rooms` frozen at discovery** (card evidence bullet 4, Reviewer D F7) is a different defect with a different fix: re-running discovery. It stays in state-of-play §9.8 and needs its own card if pursued.
- **The whole-HA restart storm itself** belongs to card `HA-CORE-RESTART-STORM-1`.
- **Not adding** an occupancy-triggered decision cycle (W2-1 fast path).
- **Not preserving** a reloading room's last real occupancy value, e.g. by carrying the pre-reload `hvac_occupied` into the placeholder. That would be a second mechanism, and the operator asked for the v5.103.15 gate to be reused.

## 10. Knobs and labels

**No knob, config field or entity is added.** All deferrals are bounded by the existing rung-1 constant `HVAC_LIVE_ROOM_TRANSIENT_GRACE_S` (300 s, `hvac_const.py:938`). Changing it requires review, because it is the reload-safety window.

The only new operator-visible text is the D5 ledger description, in plain words:
- `"<Zone> D5 forced-away suppressed (coast + occupied)"` (unchanged)
- `"<Zone> D5 forced-away suppressed (coast + room reloading)"`
- `"<Zone> D5 forced-away suppressed (coast + zone not confirmed)"`

## 11. Card corrections (for the orchestrator to fold into the card)

1. **The D6 fix in the card's `next` field is wrong:** "Source-4 excludes coordinator-absent rooms" does not bring back the lost confirmation, and Source 1 (motion) also misses the reloading room. The correct fix is to skip D6 at the HVAC call site while the zone is transient-blocked.
2. **The card missed readers:** Source 1 of D6, the row-11 comfort-grace grant (`hvac_override.py:2718`), and the once-a-day pre-heat gate (`hvac_predict.py:1420`).
3. **The D5 behaviour was a v5.103.15 design choice, not an oversight:** fix-up item 2 made D5 force-away clear the row-1 hold deliberately (`hvac.py:2712-2719`, README "D5 shed/coast force-away still write"). D1 narrows that to shed only. The README must record it.
4. **The card's premise that reloads cause this is unproven.** Restarts, not room reloads, are the likely live trigger, and they reach a HVAC decision only through the setup-time producer pass (R4). The value case depends on D0 P3.
5. The card's line numbers are stale (§0 table).
