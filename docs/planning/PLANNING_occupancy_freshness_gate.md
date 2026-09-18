# PLANNING — Occupancy freshness gate (stuck-frozen-on demote)

**Card:** `STUCK-MOTION-FROZEN-ON-BLINDSPOT-1` · **Tier:** 2-DB (occupancy TRUST; presence→house_state→zone
ripple; false-negative = abandoning a real occupant).
**Origin:** live incident 2026-09-18 — `binary_sensor.upstairs_hall_motion_3` (a **camera/Frigate** motion
object) latched `on` at 16:27 when the feed stopped, held the room occupied, pinned `house_state=home_day`
and zone_2 `home` with all persons `not_home`. Every existing defense missed it (motion exempt as trusted
corroborator; staleness keyed on `unavailable`; the stuck-on sensor *vouched* for the phantom).

> **Plan-review 2026-09-18 (Tier-2+ mandate):** first draft was **NOT BUILD-READY** — 4 CRIT + 3 HIGH. The
> load-bearing miss (CRIT-1): a room-tier exclusion **does not reach zone/house**, so it would not have fixed
> the incident it was written for. This revision folds all findings; the review record is `docs/reviews/
> plan-review/STUCK-MOTION-FROZEN-ON-BLINDSPOT-1.md` (summary inline below each deliverable).

## Institutional context verified (from the read-only scan + measure + plan-review greps)
**Measured (recorder, 7d): a standalone age threshold is UNSAFE.** These inputs are edge-driven (≈0
heartbeat rows); legitimate silence-while-`on` reaches **p95 1.8 h / max 23 h** (camera-motion),
**p95 20 min / max 26 h** (room PIR), **p95 52 min / max 5 h** (mmWave still-body). A useful (minutes–1 h)
age gate would clip live occupants → the false-negative the card fears. Incident confirmed: last row
16:27:56 `on`, then >1 h silence.

**REUSE (verified at file:line by plan-review — do not rebuild):**
- `SensorExclusionSet` (`sensor_exclusion.py:53-120`): multi-writer per-client `promote(client, entity_id,
  reason)` / `release` / `is_excluded`; `reset_tick()` clears **everything each tick** — NO sticky state, so
  **re-evaluation per tick IS the release** (there is no `release()` bookkeeping to write). → add client `"freshness"`.
- A demoted sensor's vote contributes **0** to the room legs: sole consumer `_fusion_filter_active`
  (`coordinator.py:2247-2258`); legs at `:3239-3254`; the OR that holds the room is
  `any_sensor_active = motion_detected or presence_detected or occupancy_detected` (`coordinator.py:3260`).
  **This line is the INV-FRESH.1 guarantee** — excluding ONE sensor's vote cannot zero the OR while any other
  input is `on`.
- Precedent promotion helper `_should_promote_to_stuck_exclusion` (`coordinator.py:2619-2664`) — the 4-AND
  predicate shape to MIRROR: (1) kill switch, (2) sleep-doctrine `_d2_house_state_allows()`, (3) **non-empty
  corroborator guard** `if not corroborators: return False`, (4) every corroborator OFF ≥ `CORROBORATOR_DISAGREE_S`
  with a **cold-state fail-safe** (`last_fire is None → return False`). Promotion call sites: `coordinator.py:2988`
  (p22 continuous-on), `:3070` (dutycycle); both after `reset_tick()` (`:2980`) and before the legs (`:3239`).
- `CORROBORATOR_DISAGREE_S = 900.0` (`const.py:4184`). `_CORROBORATOR_KINDS` (`sensor_role.py:59-66`) =
  {motion, pir, pir_split, bed, camera_presence, ble_presence}. `resolve_role` / `SensorCapability.kind`
  (`sensor_role.py:79-130`) for per-kind floors; `derive_capability` → None for un-wired entities → treat as
  no-floor (fail-safe never-demote).
- **Kind vocabulary (`const.py:461-468`) — CLOSED SET:** `motion, mmwave, occupancy, pir, bed, camera_presence,
  ble_presence, pir_split`. **There is NO `camera_motion` kind** — the incident entity derives `kind=motion`.
- `_mmwave_demoted_latch` (`coordinator.py:4132`, evaluated `:3293` via `_evaluate_mmwave_demoted_latch:2666`)
  — a freshness demote of an mmWave flips `presence_detected` False and would clear this latch with a false
  `mmwave_off` reason. Must be handled (HIGH-3).

**Prior plans consulted:** `PLANNING_stuck_signal_watchdog.md`, `PLANNING_sensor_health_surfacing.md`
(STEP contract), `PLANNING_stuck_sensor_consequence.md` (positive-evidence variant PARKED),
`PLANNING_mmwave_corroboration_tier3.md` (D6 parked dead/stuck-mmwave — adjacent, sibling-linked).

## Falsifiable invariant (INV-FRESH)
1. **The freshness gate NEVER causes a room to be reported unoccupied while at least one *non-stale*
   occupancy input in that room is `on`.** Guaranteed structurally: demote zeroes exactly ONE sensor's vote
   in the `any_sensor_active` OR at `coordinator.py:3260`; any other `on` input still holds the room.
2. **A sensor is never excluded by AGE ALONE.** Age above p95 legitimate silence is *expected* and is
   protected by the corroboration gate, not the floor — the floor only bounds *when the gate is allowed to
   consider* a sensor. A sensor with any independent corroborator that fired within `CORROBORATOR_DISAGREE_S`
   is never demoted regardless of its own age.

## D1 — Freshness demote at the ROOM tier (corroboration-gated, per-kind)
A sensor is promoted into `SensorExclusionSet` under client `"freshness"` (vote → 0) **only when ALL** hold
(mirror `_should_promote_to_stuck_exclusion`; place the try in its OWN block after `:2988`, before the legs
`:3239`, so a detector exception cannot disable it):

0. **kill switch:** `FRESHNESS_GATE_ENABLED` (const) AND `CONF_FRESHNESS_GATE_ENABLED` (options, default ON) — an explicit deliverable, not a maybe.
1. the sensor is currently `on`;
2. **its `kind` has a floor** (fail-safe: kind ∉ table → NEVER demote) AND
   `now - state.last_changed ≥ FRESHNESS_AGE_FLOOR[kind]`. **Use `last_changed`, NOT `last_updated`** —
   `last_updated` bumps on attribute-only writes and Frigate/Protect carry churning attributes + a two-stage
   back-fill (`reference_protect_face_latency_async`), so `last_updated` would never age on a frozen-but-
   attribute-live feed and the gate would silently no-op. Floors (module constants, Rung-1 safety envelope):
   | kind | floor | basis |
   |---|---|---|
   | `motion`, `pir`, `pir_split` | 7200 s (2 h) | > p95 1.8 h camera-motion / covers PIR |
   | `mmwave`, `occupancy` | 21600 s (6 h) | > still-body max 5 h |
   | `bed` | 21600 s (6 h) | still-body class |
   | `camera_presence` | 7200 s (2 h) | motion class |
   | `ble_presence` | (no floor — never demote) | phone-left-behind is a separate concern |
   | any kind not listed | (no floor — never demote) | fail-safe default |
3. **corroboration disagrees** — the lone-dissenter gate, with the precedent's guards PLUS subject-exclusion:
   - build the corroborator set = every `_CORROBORATOR_KINDS` sensor in the room **EXCEPT the subject sensor
     itself** (CRIT-2: the incident subject is `kind=motion` ∈ corroborator kinds; without subject-exclusion
     the gate can NEVER fire on a motion subject, because the subject is `on` and vouches for itself);
   - **non-empty guard (CRIT-3):** if that subject-excluded set is empty → **NO demote** (a lone sensor with
     no independent corroborator is never silenced — vacuous-true refused, mirroring `:2646-2649`);
   - **corroborator eligibility (MED-2):** a corroborator that is ITSELF `on` past its own kind floor does not
     count as a live corroborator (two frozen siblings must not vouch for each other);
   - every remaining eligible corroborator reads OFF AND has been OFF ≥ `CORROBORATOR_DISAGREE_S` (900 s),
     with the **cold-state fail-safe**: any corroborator whose last-fire baseline is `None` → NO demote.
   - **Do NOT trust `_effective_corroborators_last_tick`** — it is populated only inside
     `_detect_duty_cycle_stuck` which early-returns `set()` at the boot-settle gate (`:1768`), so it is
     empty/stale on early ticks (another vacuous-true source). Compute the corroborator set independently for
     freshness, or gate on `_d2_completed_cleanly`.
4. **sleep-doctrine guard (HIGH-3):** for `mmwave` / `occupancy` / `bed` kinds, require `_d2_house_state_allows()`
   (refuse during SLEEP / WAKING / HOME_NIGHT) — a sleeping person is ~100% mmWave duty with zero PIR, exactly
   the state a long-horizon mmWave demote would wrongly hit. Motion/camera kinds are exempt (no still-sleeper hazard).

**`_mmwave_demoted_latch` interaction (HIGH-3):** when the subject is an mmWave demoted by freshness, suppress
the false `mmwave_off` latch-clear in `_evaluate_mmwave_demoted_latch` — a freshness demote is not a genuine
mmWave-off edge and must not clear the D2 flap-protection latch. Builder: pass a `freshness_demoted` flag or
check the exclusion set before the `not presence_detected → "mmwave_off"` branch (`coordinator.py:2681`).

Kind from `resolve_role`/`SensorCapability.kind`. Covers camera-motion inputs (`*_motion_3`) — they derive
`kind=motion`, the incident kind.

### D1 Acceptance (must DISCRIMINATE)
- **Verify (incident, room tier):** lone `on` motion input, `last_changed` age > 2 h, all *other*
  corroborators quiet ≥ 15 min → demoted; room drops to unoccupied **iff** no other input `on`.
- **Verify (INV-FRESH.1 false-negative safety):** same stale sensor, sibling mmWave/camera `on` → room stays
  occupied (demote silences only the stale vote).
- **Verify (INV-FRESH.2 tail case — NEW per HIGH-2):** occupant present, motion latched **3 h (> 2 h floor)**,
  one independent corroborator fired 10 min ago → **NOT demoted** (the corroboration gate, not the floor,
  protects the tail). This is the row the old "30 min < floor" case never exercised.
- **Verify (CRIT-2 self-corroboration):** subject is the room's ONLY motion-kind sensor, `on`, aged out, no
  other corroborator kind present → **NOT demoted** (subject-excluded set empty → non-empty guard fires).
- **Verify (sleep guard):** mmWave `on` 6 h during HOME_NIGHT, no PIR → **NOT demoted**.
- **Test:** unit tests driving the room fusion (`_fusion_filter_active` → the `:3260` OR) with fixtures
  {frozen-lone / frozen-but-sibling-alive / live-still-mmwave / under-floor / lone-no-corroborator /
  sleep-mmwave / two-frozen-siblings}; each condition (0/1/2/3/4) + the demote wire-in separately
  mutation-anchored — neuter one → a specific named test REDs.

## D2 — Propagate the freshness verdict to the ZONE tier (CRIT-1 — the incident fix)
**Without this, D1 does not fix the reported symptom.** The incident's observable was `zone_2=home` +
`house_state=home_day`. Zone occupancy is fed by `presence._on_substrate_kind_changed`
(`presence.py:3296-3324` → `tracker.update_room_occupancy` → `_room_provenance` → `_room_occupied`
`:647`), and the occupancy **substrate is exclusion-blind by contract** (STEP-EXCLUDE-4,
`sensor_exclusion.py:22-24`). Worse, a frozen sensor emits **no `off` edge**, so the substrate's `motion=True`
bucket for that room is latched with no event to clear it — a room-tier `is_excluded()` changes nothing upstream.

**Deliverable:** when D1 promotes a sensor into the `"freshness"` client, drive a corresponding clear of that
room's substrate bucket for the demoted sensor's kind, so `_room_occupied` re-evaluates and (if no other live
input) the zone releases. Adjudicate the STEP-EXCLUDE-4 collision **in writing in the build**: either (a) a
room→substrate freshness-clear call on demote, or (b) a zone-tier freshness read at
`presence._on_substrate_kind_changed`. **Recommended (a)** — keep the freshness authority at the room tier
(single producer) and have it emit the missing edge, rather than teaching the substrate to import the
exclusion module (which the STEP contract forbids). The build must state which and why.

### D2 Acceptance
- **Verify (the actual incident):** reproduce upstairs-hall — frozen lone motion in a zone_2 room, all persons
  `not_home` → after ≤1 detection tick, `zone_2` leaves `home` and `house_state` re-evaluates off `home_day`.
  **This is the pass criterion the card exists for**; D1 alone cannot satisfy it.
- **Verify (INV-FRESH.1 at zone tier):** a genuinely occupied sibling room in the same zone keeps the zone `home`.
- **Test:** a presence-level test driving `_on_substrate_kind_changed` with a freshness-demoted room, asserting
  `_room_occupied` flips; mutation-anchored (remove the substrate-clear → zone-stays-home test REDs).

## D3 — Observability (MED-1)
There is no `sensor.<room>_excluded_sensors` entity — `excluded_sensors` is an **attribute**
(`sensor.py:2499-2502`) sourced only from `_dutycycle_excluded_now`, so a `"freshness"` promotion is invisible.
Source that attribute (and/or a new `freshness_demoted` attribute) from `_exclusion_set.provenance()` /
`entities_for_client("freshness")` so the operator can see a freshness demote. Rewrite the Live criterion to
name the real entity + attribute.

## Non-goals
- **NOT** a hard drop and **NOT** inside `_is_sensor_on` (`coordinator.py:2727`) — un-gated per-read drop
  defeats the safety. Demote via the exclusion set only.
- **NOT** teaching the substrate to import `sensor_exclusion` (STEP-EXCLUDE-4) — D2 emits the missing edge instead.
- **NOT** the zone_2 vacancy-override secondary (away-while-occupied for motion-only occupancy) — carded separately.
- **NOT** touching the mmWave still-body presence-timeout or the continuous-on 4 h rule.
- **Known accepted gap (MED-2):** two frozen siblings that fail their OWN kind floor are excluded from each
  other's corroborator set (so they can still be demoted); but two frozen siblings *below* their floor mutually
  vouch — accepted, a correlated-bridge failure (`sensor_capability.py:108`) out of scope this cycle.

## Knob ladder
`FRESHNESS_AGE_FLOOR[kind]` = module constants (Rung-1) — a *trust* safety envelope (clipping a live occupant
is the harm), changing requires review; not a dashboard knob. `FRESHNESS_GATE_ENABLED` (const) +
`CONF_FRESHNESS_GATE_ENABLED` (options, default ON) = explicit kill switch (D1.0). `CORROBORATOR_DISAGREE_S`
reused (existing).

## Restart behavior
Both `last_changed`/`last_updated` reset at RestoreEntity restore → age 0 → floor not met → fail-safe
no-demote on boot (mirrors `coordinator.py:2969-2976`); no restore-poisoning. State plainly in the build.

## Review framings (Tier 2-DB)
- **A — correctness:** the 5-condition AND (0 kill / 1 on / 2 age+kind-floor+`last_changed` / 3 corroboration
  with subject-exclusion + non-empty + eligibility + cold-state / 4 sleep guard); floor table completeness +
  fail-safe default; age math.
- **B — trust/lifecycle:** INV-FRESH.1 holds at BOTH tiers (D1 room + D2 zone); the substrate-edge propagation
  actually clears the latched bucket; `_mmwave_demoted_latch` not falsely cleared; no double-exclude with
  continuous-on/dutycycle; `reset_tick` per-tick release; restart fail-safe.
- **C — test authority via mutation:** each of conditions 0–4 + the D1 demote wire-in + the D2 substrate-clear
  is separately mutation-anchored to a named test that REDs when neutered (real fusion/substrate drive, not
  source-greps). Explicitly verify the CRIT-2 subject-exclusion and CRIT-3 non-empty guard each have their own
  failing-on-removal test.
