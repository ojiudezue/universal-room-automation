# v5.103.7 — HVAC zone conditioning demand: daytime debounce (LIVE) + preset-layer corrector (DORMANT behind guest_mode_actuation)

**Type:** Feature cycle (Tier 3 — trust-hierarchy edit; comfort + energy impacting).
**Reviews:** 4 framing-disjoint (round-1..4) + adversarial completeness pass + operator round-5 checkpoint. Adversarial returned SHIP-with-reframe — the risky setpoint-layer machinery (D9 compose-away, F2 throttle-bypass) is DORMANT live because `switch.ura_hvac_coordinator_guest_mode_actuation` is OFF.
**Card:** `HVAC-ZONE-CONDITIONING-DEMAND-1` (step-4 of `HVAC-SUPPLE-SEQUENCE-1`).

## Why

Zone 3 was flapping preset mode 56/day (2026-09-16) → 62/day (2026-09-17) — the corridor / mid-level hallway carried transit occupancy that landed the whole zone in "occupied" from a URA perspective, driving the thermostat between `home` and `away` all day. Root cause: the HVAC preset-flip retreat gate read the **lighting-fused** `zone.any_room_occupied` — which includes hallway crossings. A hallway crosser lit the zone as "occupied," delayed retreat past the vacancy grace, and the next tick flipped it back on the moment they left. Same signal choice defeated pre-cool banking + arrester comfort-delay in the same pattern.

The plan's falsifiable invariants (from `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` round-3-rev):

> **INV-1 (comfort / night safety):** a sleeping resident's own bedroom never falls to `away` overnight.
> **INV-2 (energy / promptness):** an empty zone retreats within one loop tick, even under night-trust states.

## What ships LIVE-ACTIVE (daytime preset-layer debounce)

These are active on the operator's live install without any switch flip.

- **D1 CIRCULATION EXCLUSION.** New `RoomCondition.hvac_occupied` sibling of `.occupied`. A per-room state machine rides grace-held `STATE_OCCUPIED` with a room-type-tuned tail-hold. Rooms whose `room_type == "hallway"` NEVER arm — transit is excluded from the HVAC-occupancy denomination by design. Kind is not consulted (kind-aware discrimination is deferred Stage B).
- **`RoomCondition.hvac_occupied` + `zone.any_room_hvac_occupied`** — the fused sibling. Originals unchanged; lighting/fan/cover surfaces continue to read the lighting-fused signal.
- **Row-1 (preset-flip retreat) reads the fused signal.** The retreat gate now gates on `_zone_conditioning_retreat_ok(zone)` (F3 shared helper) — retreat is authorized IFF zone is HVAC-ESTABLISHED AND fused-empty. Same helper is consumed by D7 (night-trust suppression) and F4 (arrester comfort-delay) so all three decision points use one oracle.
- **D7 night-trust guard** on the same fused signal — an empty zone retreats even under `FAN_TRUST_STATES`.
- **D8 night hold** — `ROOM_TYPE_HVAC_HOLD_NIGHT` covers every non-hallway room type, night ≥ day for every type (monotonicity). Sized as an insurance tail for unmeasured rooms whose mmwave can drop a still body mid-sleep.
- **Reset-only backstop.** Person-trust preserve fires ONLY while the zone is UNESTABLISHED (post-reload gap, before the D1 producer has read every room). Once established, occupancy alone decides — an empty zone retreats even if a resident's phone reads `home` elsewhere in the house. Kills the "any-resident-home was holding every empty zone all night" over-preserve.
- **D5 migration.** `_migrate_hvac_zone_entry_dwell_to_zero` rewrites the stored `hvac_zone_entry_dwell` option from the legacy default `3` → `0`, so the CM-flow persisted value no longer shadows the new module default. Per-room D1 tail-hold is the sole hold source now. Idempotent via `hvac_zone_entry_dwell_zero_migration_done`.
- **Hallway enum.** `ROOM_TYPE_HALLWAY = "hallway"` added; both config-flow selector lists carry the "Hallway (Circulation — excluded from HVAC occupancy)" option; entries in `ROOM_TYPE_TIMEOUTS`, `ROOM_TYPE_HVAC_HOLD`, `ROOM_TYPE_HVAC_HOLD_NIGHT`. Reclassification of the 6 existing hallway rooms is an operator runbook step (Options flow per-room), NOT applied by this cycle.
- **D2 diagnostic entity.** `binary_sensor.<room>_hvac_occupied` (disabled-by-default; enable per zone as needed) exposes the D1 producer's decision + attrs (`armed`, `tail_expires_at`, `hold_expires_at`, `source`, `room_type`, `hvac_vacancy_hold_s`, `kinds_active`).
- **Vacancy sweep decoupled.** The two lighting-sweep call sites (row-1 retreat + D6 stale branch) fire only when `not zone.any_room_occupied` (LIGHTING-fused). A standing hallway occupant never gets swept dark under the new HVAC-denomination retreat.

## What ships DORMANT (guarded by `switch.ura_hvac_coordinator_guest_mode_actuation`, live: OFF)

These are the preset-layer corrector machinery. They live in `_async_apply_preset_overrides` which is gated at method-entry by `if not self._guest_mode_actuation_enabled: return`. The switch is OFF on the live install → this code does not execute today.

- **D9 compose-away.** When an established empty zone reaches the DPM apply loop, compose the `away` preset baseline (instead of the house-state target preset baseline) for that zone and emit through the existing chokepoint. Intent: the DPM is the corrector for third-writer restores (nudge-restore, pre-heat return, ramp-audit).
- **F2 throttle-bypass on compose-away.** The DPM's `_last_emitted_range` throttle skips its short-circuit on the compose-away branch so a third-writer restore that emits comfort setpoints without updating `_last_emitted_range` gets overwritten on the next tick. Known limitation carded (see below).
- **F4 arrester establishment-aware read.** `_comfort_delay_active` consults the F3 shared helper so a manual push right after a reload isn't stomped by the arrester dropping its grace during the unestablished window.

**Because guest_mode_actuation is OFF live, D9/F2/F4 acceptance criteria are NOT live-verifiable this cycle.** They ship correct-by-construction (Tier-3 review + mutation-drill-verified, source-side); their live activation is a separate operator decision (flip the switch). Documented explicitly per operator round-5 direction.

## Live acceptance criteria (discriminating)

**Only the LIVE-ACTIVE surface is live-verifiable this cycle.**

- **Primary (verifiable):** Zone 3 preset flip rate over a full day should drop materially from the baseline of 56/day (2026-09-16) → 62/day (2026-09-17) once the circulation exclusion + per-room hold debounce the corridor-driven flapping. Discriminator: after one full day post-deploy, `ura_activity_log` shows Zone 3 `preset_change` rows at a substantially lower rate. A day rate near the 56-62 baseline means the debounce didn't take effect (either hallway not reclassified OR retreat gate still on lighting signal).
- **D5 migration:** on the first `_async_setup_entry` after upgrade, `hvac_zone_entry_dwell` in the CM entry's stored options is `0` (not `3`), and `hvac_zone_entry_dwell_zero_migration_done` is `True`. Idempotent — no rewrite on subsequent restarts.
- **Circulation exclusion:** in a room manually reclassified as hallway, `binary_sensor.<room>_hvac_occupied` reads `off` continuously even while `binary_sensor.<room>_occupied` reads `on` (transit ≠ HVAC-occupied).
- **INV-1 (comfort/night safety):** overnight, no bedroom-typed zone flips to `away` while its resident's mmwave / occupancy sensors continuously read occupied. Discriminator: `preset_change` rows on bedroom zones between 22:00-06:00 = 0.
- **INV-2 (energy/promptness) — daytime, preset-layer:** an established empty zone flips to `away` within one decision cycle after the D1 tail-hold expires. Discriminator: for a room that clears mid-day, the corresponding zone's `preset_change` row lands within one grace + tail-hold window.
- **D9/F2/F4 NOT live-verifiable this cycle** (dormant). Their activation deliverables are gated on future operator decision to flip `switch.ura_hvac_coordinator_guest_mode_actuation`.

## Live Validation — Validated 2026-09-25 (write-back)

Deployed 2026-09-17 20:16 CDT. Evidence gathered read-only on 2026-09-25 from the HA recorder (7-day window, starting 09-18 04:12 CDT), the URA DB `ura_activity_log`, and `.storage/core.config_entries`. All times are CDT.

| # | Criterion | Verdict | Observed evidence |
|---|---|---|---|
| 1 | Zone 3 preset flip rate drops materially from the 56–62/day baseline | **PASS** | `ura_activity_log` zone_3 `preset_change` rows per day. **Before:** 09-14 45, 09-15 40, 09-16 57, 09-17 66. **After:** 09-19 9, 09-20 20, 09-21 15, 09-22 18, 09-23 18, 09-24 17, 09-25 31\*. The recorder count of `climate.back_hallway_zone_3` preset changes agrees: 09-19 11, 09-20 31, 09-21 17, 09-22 20, 09-23 20, 09-24 20, 09-25 33\*. Every day after the ship is 2–7× below the 09-16/17 baseline, and below every day measured before it. The 7 hallway rooms were reclassified to `room_type: hallway` (entries modified 09-18 01:38–01:39Z). Caveat: v5.103.8–.13 shipped over the same days, so this drop is not attributed to D1 alone. |
| 2 | D5: stored `hvac_zone_entry_dwell` = `0` and the sentinel set | **FAIL (criterion as written)** | The CM entry options hold `hvac_zone_entry_dwell: 5.0` and `hvac_zone_entry_dwell_zero_migration_done: True`. `number.ura_hvac_coordinator_zone_entry_dwell` = `5` at every recorded boot (09-18 10:13, 09-18 16:11, 09-20 09:36, 09-21 23:23, 09-25 18:09/20:38/20:52), and `0` never appears. The migration only rewrites an exact `3` (`__init__.py:792`), so it correctly left an operator-set 5 alone. **The plan's premise (stored value = legacy 3) did not hold on this install.** As a result, the README claim that the "per-room tail-hold is now the sole hold source" is **not true live**: a 5-minute zone entry dwell still applies. The recorder cannot show whether the value was 3 at the 09-17 first boot. Operator decision: set it to 0, or keep 5 deliberately. |
| 3 | Circulation exclusion: a hallway room's `hvac_occupied` stays `off` while `occupied` is `on` | **PASS** | All 7 hallway `binary_sensor.*_hvac_occupied` entities: **0** `on` rows in 7 days; attributes `source: hallway_excluded`, `armed: false`, `hvac_vacancy_hold_s: 0`. Meanwhile the lighting-occupancy sensors had `on` rows: master hallway 2873, foyer 839, guest bedroom 2 hallway 523. The other 4 hallways have no matching `*_occupied` entity name, so they were not cross-checked. |
| 4 | INV-1: no bedroom zone flips to `away` overnight while its resident's sensors read occupied | **INCONCLUSIVE — no violation of the stated sensor condition; 2 suspect events** | There were 29 night (22:00–06:00) `away` writes after the deploy. Every one logged `any_room_hvac_occupied` false/None. At each flip in a resident-bedroom zone (zone_1 Master Bedroom; zone_2 Jaya/Ziri), the bedroom's `*_occupied` and `*_presence` entities read `off`, with 0 `on` rows in the prior 30 min. So the flips did not happen while the sensors read occupied. The README's literal discriminator ("night `preset_change` rows = 0") is mis-specified, because it also counts legitimate `sleep` transitions, and it is not met. **Suspect events:** zone_2 on 09-24 at 02:47 and on 09-25 at 02:09. Jaya was home both times. Her bedroom occupancy was last `on` at 02:10 and 01:30, the flip came after the 30-min D8 night hold, and the room re-occupied at 02:56 and 02:25. That fits either "she was out of the room" or "mmWave dropped a still sleeper for longer than the hold". The recorder cannot tell these apart. This is the open night-trust question tracked under step-4-B. |
| 5 | INV-2: an established empty zone retreats within one grace + tail-hold window (daytime) | **INCONCLUSIVE** | 135 daytime `vacant_past_grace` → `away` writes after the deploy, all with `any_room_hvac_occupied: false`, so the gate reads the fused signal as designed. The latency oracle is confounded. Zone membership was approximated from each room's `climate_entity`, which does not match URA's HVAC-zone membership (some flips happened while an approximated "member" was still `on`). Many flips are also re-retreats after third-writer reclaims. Median home→away latency after the last approximated member cleared: zone_2 5.0 min, zone_1 15.1, zone_3 22.2. That is not a clean measurement. |
| 6 | D9 / F2 / F4 (setpoint-layer corrector) | **NOT-EXERCISED (dormant)** | `switch.ura_hvac_coordinator_guest_mode_actuation` has been `off` in all 13 recorded states from 09-18 to 09-25 (only `off`/`unavailable`), so `_async_apply_preset_overrides` returns at entry. The proof is in-suite only (Tier-3 mutation drill). |

\* **09-25 is contaminated:** an HA core update and restart (18:05–18:11), an Envoy reboot, and a network restart. `climate.back_hallway_zone_3` was `unavailable` from 20:24 to 21:15, and 10 of that day's 31 zone_3 rows are `away→home` retries logged during that outage (00:29–02:09Z).

**Method + limits.** The recorder keeps only 7 days, so the pre-ship baseline comes from the URA DB. **The zone_1 manual-% metric is deliberately left out:** it is non-stationary and was retracted as an acceptance signal (attributed 2026-09-25: of zone_1's 88 manual entries after the 09-20 11:39 Bryant schedule removal, ~70 were written by URA's own AC soft-nudge start/restore/reset — raw `set_temperature` → Carrier manual hold — per `ac_ramp_events`; ~17 look like human step-downs. See `HVAC-ZONE1-MANUAL-OSCILLATION-1` MECHANISM_CORRECTED_2026_09_25). Zone_3 manual time was about 0 h/day (0.0–0.2 h) from 09-18 to 09-24. Dismissed boot transients: `unavailable` rows on the dwell Number and the guest switch at every restart, and at 09-25 20:38/20:52 (CM entity reloads). **Verdicts: 2 PASS · 1 FAIL · 2 INCONCLUSIVE · 1 NOT-EXERCISED.**

## Known residuals — carded (not fixed here)

- `HVAC-DEGRADED-ROOM-TRIPWIRE-1` — a zone with a permanently-disabled room (config entry disabled / in setup_retry) never reaches HVAC-ESTABLISHED under the `all()` gate → never retreats. Benign (wrong direction is never wrong) but leaves the feature INERT for that zone. Needs a code trip-wire per No-Soak that surfaces the degraded room; NOT a relaxation of the gate.
- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` — F2 throttle-bypass on compose-away is currently unconditional (always bypasses on the compose-away branch). This would produce a per-tick emit storm if D9 activates without further narrowing. **Blocker on ever enabling `guest_mode_actuation`.** Fix: narrow the bypass to be edge-triggered on S8/S9/S11/S13-return `_last_emitted_range` invalidation, not unconditional. Do this BEFORE flipping the switch.
- `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` — the ungated restore writers (S8 cancel-nudge at `hvac_override.py:5774`, S9 startup-ramp-audit at `:6180`, S11 release-banked, S13 pre-heat return) emit comfort setpoints without updating `_last_emitted_range`. Under `guest_mode_actuation` OFF this stays as pre-cycle live behavior; it is a real correctness gap that the D9 corrector was intended to close but doesn't (dormant). Not new — pre-existing, uncorrected live because D9 is dormant.

## Rollback

- Automatic: none needed for the DORMANT surface — flipping guest_mode_actuation OFF restores pre-cycle behavior byte-for-byte on the preset-layer path.
- Manual (LIVE-ACTIVE surface): revert `feature/hvac-conditioning-demand` merge; the D5 stored-option rewrite persists (sticky) but pre-cycle code just reads `3` as `3` again — no harm.
