> **SUPERSEDED 2026-09-26 by `PLANNING_hvac_entry_dwell_hvac_clock.md`.** This plan gated on the LIGHTING clock (`_became_occupied_time` / `zone.any_room_occupied`) — the very denomination HVAC occupancy was built to escape (state-of-play §3.2 DENOMINATION DEFECT, card `HVAC-ENTRY-DWELL-ROOM-CLOCK-1` `reframe_2026_09_26`). Kept for history; do not build.

> **SUPERSEDED 2026-09-28 — FOLDED into `PLANNING_hvac_fast_occupancy_response.md` §5b (D5 transit filter, built v5.103.20).** See that plan; this file is historical.


# PLANNING — HVAC-ENTRY-DWELL-ROOM-CLOCK-1

**Tier:** 2-DB (elevated per standing policy for regression-prone HVAC preset-decision changes;
three framing-disjoint reviews + live validation + README write-back).
**Workstream:** HVAC-W2-OCCUPANCY-TRUTH (§11 W2). Companion, not substitute, for the parked
W2-1 fast path. Depends on nothing not already live.
**Author date:** 2026-09-26. **Target release:** patch bump under 5.90.x cadence.

---

## Goal (operator scope)

Keep entry latency low while restoring **hysteresis** against brief transits. Today the zone
entry dwell (`hvac.py:2438-2451`, guard `dwell_minutes > 0`, knob
`number.ura_hvac_coordinator_zone_entry_dwell`, minutes) is set to `0` (§2, §8) precisely
because any `dwell > 0` costs a full extra 5-min tick (§10 C18 mechanism): the FIRST tick that
sees lighting occupancy also **starts** the dwell clock (`zone.current_session_start = now` at
`hvac_zones.py:786`, "Row 2d") and therefore always trips the skip.

**Change:** move Row 2d's clock earlier — to the **earliest real occupancy start** among the
zone's currently lighting-occupied rooms — so a tick that sees a room that has ALREADY been
present ≥ dwell can act immediately. The dwell skip itself is unchanged; on ship the operator
turns the knob 0 → 1 (minute).

## Falsifiable invariant (the one property this cycle must guarantee)

> **For any zone Z, in a house state where the entry dwell applies (home_day / home_evening /
> home_night / guest / waking), on a decision tick T with `zone.any_room_occupied == True`
> and target preset != "away" and Z not in `_pre_arrival_zones`:**
>
> - **ACT:** the dwell skip does NOT fire (preset flip proceeds) whenever
>   `max_room continuous_lighting_occupation_at_T ≥ dwell_minutes` — i.e. some room has been
>   continuously STATE_OCCUPIED for at least the dwell before this tick.
> - **HOLD:** the dwell skip DOES fire (preset unchanged) whenever the longest such duration
>   is `< dwell_minutes` — i.e. everyone currently present has been in less than the dwell
>   (transit).

D's job (Review D) is to falsify exactly this — enumerate reachable configs where either half
fails.

## Non-goals

- **No** occupancy-triggered decision cycle (W2-1 fast path stays PARKED per §9d note).
  This card only changes WHEN the dwell clock starts; the 5-min tick cadence is untouched.
- **No** change to `zone.any_room_occupied` fusion (Row 2d stays lighting-fused per §3.2 /
  Row 2d design comment `hvac_zones.py:766-770`).
- **No** wake-capable room-type gating (operator-noted complement — separate card).
- **No** change to HVAC-denomination clocks `last_occupied_time` /
  `continuous_occupied_since` (Row 2a / 2c — different consumers).
- **No** change to `_became_occupied_time` semantics in the room coordinator; this cycle is a
  READ-only new consumer.

---

## Institutional context verified

**Design docs**
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — read completely; §2 (5-min tick, no
  occupancy-triggered cycle; C18 mechanism), §3.1 (Row 2d NO-SWAP, `any_room_occupied` is
  lighting), §3.2 (dwell gate at `hvac.py:2355-2368` — matches current-file `:2438-2451` after
  v5.103.16), §3.3 (LIVE dwell), §8 (`hvac_zone_entry_dwell` set to 0 2026-09-26 evening,
  Row-2 knob rung), §9d (W2 fast-path scope operator-decided; this cycle is disjoint), §10
  C11 (dwell migration history), C18 (this cycle's mechanism), §11 (W2 workstream).
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` — §2d row confirming Row 2d
  lighting-fused was a DELIBERATE NO-SWAP; the only consumer is the dwell check.
- `docs/planning/AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md` (S2
  entry) — only consumer today is the S1 dwell check; follows S1's fate.
- `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` — parked; this cycle intentionally
  does NOT overlap (fast-path changes cadence; we change the clock only).
- `docs/planning/AUDIT_hvac_preset_flap_fix_implications.md` — Row 2d/2c/2a interactions.

**Prior planning / audit consulted**
- `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1` (kanban) — orthogonal (tail-hold sizing).
- `HVAC-HOLD-SIZING-ALL-ROOMS-1` (kanban) — orthogonal (per-room vacancy holds).
- `HVAC-ZONE-CONDITIONING-DEMAND-1` — Row-2 denomination split (context).

**Memory bodies**
- `reference_hvac_state_of_play.md` — enforces mandatory complete read of state-of-play
  before any HVAC work.
- `feedback_tier2plus_prior_art_scan.md` — this section's discipline.
- `feedback_marginal_benefit_pushback.md`, `feedback_do_robust_fix_not_bandaid_and_card.md` —
  justify shipping the simple root-cause fix over the parked fast path (§ Marginal-benefit
  below).

**Prior-art scan — REUSE-or-BUILD per proposed piece**

Per Tier 2+ rule (2026-09-05). All findings by grep on `develop`.

| Proposed piece | Verdict | Evidence |
|---|---|---|
| Producer of "when did this room's current lighting occupancy start" | **REUSE** `RoomCoordinator._became_occupied_time` | Declared `coordinator.py:303` ("When current occupancy session started"); set at `coordinator.py:3614, 3682, 3869, 4797, 4829` on STATE_OCCUPIED rising edges; cleared to `None` on vacant edges `:4121, :4400, :4808, :4840, :5273`. Public accessor `get_became_occupied_time()` at `coordinator.py:5384-5395`. Same STATE_OCCUPIED that `data.get("occupied")` (`hvac_zones.py:647`) fuses into `any_room_occupied`. |
| Restart persistence for that timestamp | **REUSE** existing RestoreEntity + DAO | `binary_sensor.py:278-282, 343-346, 403-404` (RestoreEntity ISO roundtrip); DB column `became_occupied_time TEXT` at `database.py:1278`, DAO write at `:5087-5094`; boot restore `__init__.py:5047-5053`, dump `:5531-5533`. |
| Cross-coordinator read from hvac_zones → room coordinator | **REUSE existing plumbing** | The room coordinator is already in scope inside the Row-2 loop: `coordinator = room_coordinators.get(room_name)` at `hvac_zones.py:668` (map built `:617-619`). No new signal, no new dispatch, no new coupling. |
| Dwell knob | **REUSE** `number.ura_hvac_coordinator_zone_entry_dwell` (minutes, integer) — rung 3 (live-tunable Number, RestoreEntity-persisted per v4.7.25 pattern) | §8 live value 0; option key `hvac_zone_entry_dwell`. |
| Fallback source (candidate) `_last_occupied_since_for_handler` | **REJECT** — wrong semantics | `coordinator.py:320` doc: bathroom-exhaust snapshot captured ON the vacant tick BEFORE `_became_occupied_time` is cleared; NOT a live session start. Consumers `automation.py:2830, 2841`. |

**Code locations surveyed end-to-end during scoping**
- `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py:600-790`
  (producer loop, Row 2a-e, current Row 2d writer).
- `custom_components/universal_room_automation/domain_coordinators/hvac.py:2380-2500`
  (dwell skip; effective_preset; pre-arrival exemption).
- `custom_components/universal_room_automation/coordinator.py:300-330, 3600-3900, 4080-4130,
  4380-4410, 4780-4850, 5180-5280, 5380-5400` (all `_became_occupied_time` set/clear/expose
  sites; restore path).
- `custom_components/universal_room_automation/__init__.py:5040-5060, 5520-5540` (restore /
  dump).
- `custom_components/universal_room_automation/binary_sensor.py:250-410` (RestoreEntity).

---

## Producer AND Consumer map (per standing rule)

### Producer — `zone.current_session_start` (Row 2d, `hvac_zones.py:783-788`)

TODAY (arithmetic): on the tick where `any_room_occupied` first becomes True, assigned `now`;
reset to `None` when `any_room_occupied` is False. Dependency health: `any_room_occupied` is
the OR of `RoomCondition.occupied` which mirrors each live room's `data.get("occupied")` —
healthy today (lighting occupancy is the well-exercised path).

AFTER (arithmetic): on the tick where `any_room_occupied` is True AND
`zone.current_session_start is None`, assign the EARLIEST `_became_occupied_time` among the
zone's currently occupied rooms; while `any_room_occupied` remains True, allow the value to
move **only monotonically backward** (a newly-visible earlier start replaces it — restart /
newly-joining room previously present); reset to `None` when `any_room_occupied` is False.
Fallback (defense): if `any_room_occupied` is True but no occupied room reports a
`_became_occupied_time` (race with `None` clear inside the tick), fall back to `now` — this
degrades to today's behaviour for one tick, never later.

Dependency health: `_became_occupied_time` is set on every STATE_OCCUPIED rising edge and
persisted across restart (see prior-art table); the only failure mode is a room whose
coordinator has not yet loaded (`coordinator is None` at `hvac_zones.py:680`) — that room is
already skipped in Row-2d population and contributes nothing here either.

### Consumers of `zone.current_session_start` — exhaustive grep

Two consumers total (grep 2026-09-26):

| # | Consumer | Site | Trust vs display | Verdict on moving the clock earlier |
|---|---|---|---|---|
| 1 | Dwell skip (this cycle's *target* consumer) | `hvac.py:2438-2451` (`_apply_house_state_presets`) | Trust (decides whether to write preset) | **INTENDED CHANGE** — the whole point. |
| 2 | (none — no sensor attr, no other reader) | — | — | — |

Confirmed grep hits (`current_session_start`): `hvac_zones.py:135` (field decl), `:766-770`
(comment), `:785-786, :788` (writer). `hvac.py:2446-2447` (reader). No sensor attribute, no
D5 / D6 / D7 / D9 reader, no ledger, no telemetry — only the dwell skip.

**Producer-adjacent invariants that MUST NOT regress**:
- `zone.last_occupied_time` (Row 2a, HVAC-denomination) — untouched.
- `zone.continuous_occupied_since` (Row 2c, HVAC-denomination) — untouched.
- `zone.vacancy_sweep_done` (Row 2b, lighting) — untouched.
- `zone.any_room_hvac_occupied`, `is_zone_hvac_established`, `conditioning_retreat_ok` —
  untouched.

---

## Edge cases (operator-listed + reachability)

| # | Case | Behaviour required | How this design meets it |
|---|---|---|---|
| E1 | A room leaves mid-session (earliest-arriving room goes vacant while others remain) | Session `current_session_start` MUST NOT jump forward and re-arm the dwell | Monotonic-backward rule: while `any_room_occupied` remains True, only replace if the candidate is EARLIER. A continuing session keeps its old start. |
| E2 | A new room joins an existing session | Session continues; start may move earlier if the joiner has an earlier `_became_occupied_time`, otherwise unchanged | Same rule. |
| E3 | Restart / reload | A person continuously present for an hour before restart MUST cause the first post-restart tick to act (not "now"), because their `_became_occupied_time` was persisted | RestoreEntity + DAO restore `_became_occupied_time` at `binary_sensor.py:278-282` / `__init__.py:5047-5053`. First post-restart HVAC producer pass populates Row 2d from that value. Fallback to `now` only if the restore literally left `_became_occupied_time=None` on an occupied room (degrades to today, one tick). |
| E4 | Hallway room (`ROOM_TYPE_HALLWAY`) currently occupied | Row 2d today counts hallways (via lighting `any_room_occupied`); Row 2d tomorrow SHOULD still count them (no denomination swap — §3.1 unchanged) | We iterate zone.rooms and read `_became_occupied_time` from every occupied room including hallways — matches today's scope. |
| E5 | Excluded room (disabled / SETUP_ERROR / removed — v5.103.15 live-room set) | Contributes nothing | Room's coordinator is either absent (`hvac_zones.py:680`) or the room is not in `zone.rooms`; either way it never contributes a session start. |
| E6 | Transient (loading) room ≥ 300 s | Contributes nothing | Same — coordinator absent or classified transient; no reads. |
| E7 | Coordinator present but `_became_occupied_time` is `None` while `data["occupied"]` is True (rare intra-tick race) | Do NOT crash; do NOT eternally hold the dwell | Fallback: if NO occupied room yields a timestamp, use `now` (today's behaviour). One tick of today's cost; self-heals as soon as the room sets the timestamp. |
| E8 | Pre-arrival zone | Dwell already exempted at `hvac.py:2448` | Unchanged. |
| E9 | Target preset == "away" | Dwell already exempted at `hvac.py:2449` | Unchanged. |
| E10 | Someone override-occupied via `switch.<room>_override_occupied` (§9c) | Override sets `data[STATE_OCCUPIED]=True` at `coordinator.py:4791-4811`; this in turn drives `_became_occupied_time` set at `:4797` | Behaves as a real presence — session_start = when override was flipped. Documented, not new behaviour. |

---

## Knob (numbers-get-knobs ladder)

Reused knob: **`number.ura_hvac_coordinator_zone_entry_dwell`** (`hvac_zone_entry_dwell`
option, minutes, integer, live-tunable, RestoreEntity-persisted). **Rung 3** (live-tunable
Number, dashboard-exposed) — correct rung: the operator legitimately tunes it by observation
of flap rate vs entry latency (evidence: 5 → 2 → 0 in the last 12 h).

**Recommended value on ship: `1` (minute).** Why:
- Filters transits shorter than 60 s (walk-through, glance-in), which is the pre-dwell-0
  flap class the operator called out.
- With the room-clock fix, a person present ≥ 60 s WHEN the tick arrives acts on that tick
  (no extra latency). Only a *fresh cold entry* within the last 60 s pays a tick-and-a-half
  delay — that class was already paying ~2.5 min average with dwell 0 (§2 update).
- Expected worst-case entry latency: unchanged from today's 5-min tick cadence for a fresh
  cold entry; the SAVING vs the current-code `dwell=1` regression (would be 5-10 min) is the
  entire point.
- Kill-switch semantics preserved: `dwell_minutes > 0` guard at `hvac.py:2442`; the operator
  can flip back to `0` at any time and get exactly today's behaviour.

---

## Deliverables

### D1 — Row 2d writer: earliest-room start with monotonic-backward latch
File: `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py`
around `:783-788`. Compute `candidate = min(coord._became_occupied_time for room_name in
zone.rooms where room_coordinators.get(room_name) is present AND
RoomCondition.occupied is True AND their _became_occupied_time is not None)`. If no
candidate, fall back to `now`. Latch: assign when `current_session_start is None`;
otherwise replace only if `candidate < current_session_start`. Reset to `None` on
`not any_room_occupied` (unchanged).

Access via the existing local `room_coordinators` dict (already built `:602-619`); use
the public `get_became_occupied_time()` accessor to avoid touching the private attribute
from another module.

#### Acceptance criteria
- **Verify:** on the FIRST decision tick after a room has been continuously occupied for
  ≥ dwell, `_apply_house_state_presets` proceeds past the dwell guard for that zone.
- **Verify:** on a decision tick where all currently-occupied rooms became occupied < dwell
  ago, the dwell guard skips (preset unchanged).
- **Verify:** a mid-session room-vacate does NOT push `zone.current_session_start` forward.
- **Verify:** on cold-start with a persisted `_became_occupied_time` older than dwell, the
  first HVAC decision tick post-boot acts (no dwell skip) for that zone.
- **Test:** unit tests in `quality/tests/hvac/test_hvac_zone_entry_dwell_room_clock.py`
  covering the 10 edge cases E1–E10 above. Each test constructs a `ZoneManager` with fake
  room coordinators that expose configurable `_became_occupied_time` and
  `data["occupied"]`, drives one `update_room_conditions` pass, and asserts
  `zone.current_session_start`; then drives one `_apply_house_state_presets` call and
  asserts the skip decision.
- **Test:** mutation drill (per Tier 2-DB Review C): edit the writer to keep today's
  `= now` behaviour and confirm at least ONE test in the new file fails specifically for
  the ACT-when-already-present case; restore.
- **Live:** post-deploy, with knob = 1, observe zero occurrences of "occupied ≥60 s before
  tick, dwell skipped" over 3 occupied days in `climate_write` (W1-A ledger) joined against
  `_became_occupied_time` history.

### D2 — Knob default to 1 on ship
Update the option/Number default from 0 → 1 (`__init__.py` migration + Number entity default;
follow the v5.103.7 dwell-migration pattern but this time migrate any stored `0` set by the
2026-09-26 evening operator action to `1`, and leave any operator-set non-zero value alone).

#### Acceptance criteria
- **Verify:** after deploy the live number entity reads `1` (unless operator has since set
  otherwise).
- **Live:** `number.ura_hvac_coordinator_zone_entry_dwell` state == `1` in HA within 60 s of
  restart.

### D3 — README write-back on close
`docs/readmes/README_v<version>.md` prospective "Live" bullets replaced post-restart with a
`Validated <date>` results table: dwell knob value observed; a per-zone entry-latency sample
(min/median/p95) over 3 occupied days from `climate_write`; flap-rate sample (same source);
one specific test that would have failed without D1's monotonic-backward latch.

---

## Discriminating acceptance criteria (per "acceptance criteria must discriminate")

For each observation, state the different failure it discriminates:

| Observation under the fix | Different failure it rules out |
|---|---|
| `zone.current_session_start` after a room-vacate mid-session is UNCHANGED from before the vacate | A naïve "min over currently-occupied rooms with no latch" would jump FORWARD here → dwell re-arm bug. |
| First post-restart HVAC tick with a 1-h-old persisted `_became_occupied_time` acts (no skip) | A regression where restore is lost or Row 2d uses `now` → skip would occur (today's C18). |
| Fresh cold entry with knob=1: tick at t=30 s SKIPS, tick at t≥60 s ACTS | Off-by-one on comparator (`<` vs `<=`) or unit mixup (seconds vs minutes). |
| Hallway-only zone (hypothetical) still triggers session start | An accidental HVAC-denomination swap of Row 2d (hallways would drop to 0). |

---

## Tier classification & review framings

Tier 2-DB (three framing-disjoint reviews + Review D live validation):

- **A — Local correctness.** Writer arithmetic; comparator boundaries; unit (minutes vs
  seconds) at `hvac.py:2447`; None-safety; fallback path; the monotonic-backward latch is
  applied exactly on `zone.current_session_start` update, never elsewhere.
- **B — Cross-coordinator + lifecycle.** Restart / reload behaviour end-to-end (DAO restore →
  RestoreEntity → first producer pass → first `_apply_house_state_presets`). Race between
  `_became_occupied_time` set/clear in the room coordinator and the HVAC producer read.
  Confirm no new coupling (only READ of an already-public accessor already consumed by
  `person_coordinator.py`, `sensor.py`, `aggregation.py`). Confirm all Row-2a/2b/2c writes
  are byte-identical.
- **C — Test authority + consumer completeness.** Independent grep of `current_session_start`
  consumers (must return the same two sites); source-mutation drills per Review C protocol on
  the writer and the comparator; drill on the fallback branch.
- **D — Adversarial completeness + live validation.** State the falsifiable invariant above
  in code; enumerate every reachable {house_state, pre_arrival, target_preset, any_room_occupied,
  session_age} tuple and verify ACT/HOLD. Post-restart: replay one real entry and one real
  transit from `climate_write` + `_became_occupied_time` history.

---

## Deferred / non-goals (explicit)

- W2-1 fast-path (occupancy-triggered cycle) — stays PARKED (§9d).
- Wake-capable room-type gate (closets / pantry / bath don't wake a zone) — separate card.
- Short-visit fast-retreat — separate card.
- Any change to `hvac_occupied` / tail-hold sizing.

## Marginal-benefit decomposition (per pushback duty)

Simplest version = today (dwell = 0): entry latency avg ~2.5 min / worst 5 min, zero
hysteresis. Root-cause version (this cycle): restore hysteresis at ~0 latency cost when the
person has actually been present ≥ dwell before the tick. Marginal ingredient cost: ONE new
cross-coordinator READ of an already-public, already-persisted attribute; ONE new consumer
of `current_session_start` (which had ONE consumer). No new listener, no new signal, no new
state machine, no synthetic time. Marginal benefit clearly pays: the operator's stated
resistance to dwell=0 (transit flaps) is the whole reason we're here, and the alternative
(W2 fast path) is a much larger surface. Ship this; keep W2 fast path parked.
