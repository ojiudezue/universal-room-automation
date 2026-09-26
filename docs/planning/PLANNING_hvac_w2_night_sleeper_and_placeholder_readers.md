# PLANNING — HVAC W2: night still-sleeper hold + reloading-room placeholder readers

**Revision:** rev 2 (2026-09-26). Rev 1 got FIX-PLAN-FIRST on both pieces; rev 2 restructures
Piece A around the D-A0 probe result (knob-turn IS the fix; code build parks with revival
triggers) and folds all Piece B plan-review findings (F15–F20). Change log at the bottom.

**Workstream:** HVAC-W2-OCCUPANCY-TRUTH (kanban L1834).
**Scope of THIS plan:** two W2 children — HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1
(Piece A) and HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1 (Piece B) — plus scope-check on
HVAC-GUEST-AS-ZONE-PERSON-1 (Piece C).
**Not in scope:** HVAC-DEGRADED-ROOM-TRIPWIRE-1 (v5.103.15, in review), W2 fast path,
HVAC-HOT-ENTRY-LATENCY-1, Piece C build.
**Read first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — completely, including
C16 (Carrier poll cadence), C17 (preset suppression 120 s / temp 5 s), C18 (hot entry 5–10
min), C19 (corrected §9.3 — URA marked Jaya's room VACANT FIRST at 01:25:53 / 01:31:18; fan
turned off in consequence, not as trigger). Operator principle (binding): **HVAC matches
occupancy IN THE ZONE — never "anyone home"**.
**Sequence:** builds start ONLY after (i) v5.103.15 merges to `develop` and (ii) the W2
fast-path plan reviews confirm no `hvac.py` overlap with Piece B's D5 / F8 / F9 / row-10 sites
and no producer-pass ordering conflict.

---

## Institutional context verified

### Design docs
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — read in full, incl. C16–C19 and
  the corrected §9.3 fan narrative. Load-bearing: §2 (5-min tick; §C18 hot-entry latency
  5–10 min), §3.1 producer + D8 night hold (`const.py:1230-1242`), §3.2 shared retreat gate
  (`hvac_zones.py:1085`; delegate `hvac.py:3830`) + bypassing readers list, §7 lockout
  mechanics (C17 preset window 120 s), §9.3 REWRITTEN (fan = consequence; per-room knob is
  the fix path), §9.4 placeholder readers, §9b (failed room = not defined), §9c (override
  switches unchanged), §9d (fast-path shaves the 5-min tick only), §10 C16–C19, §11 arc.
- `docs/planning/PLANNING_hvac_live_room_establishment.md` — v5.103.15 classifier this plan
  REUSES: `is_zone_transient_blocked`, `_coordinator_absent_this_pass`,
  `excluded = not defined` (operator option (a)).
- `docs/planning/PLANNING_hvac_w2_occupancy_fast_path.md` — dispatched; overlap flagged.
- `docs/planning/PLANNING_hvac_zone_conditioning_demand.md` — origin of D7/D8 and the
  preserved full 200-min/4-discharge machinery.

### Kanban cards (read in full)
- **HVAC-W2-OCCUPANCY-TRUTH** (L1834) — parent, ordering, operator decisions 2026-09-26.
- **HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1** (L2261) — Piece A. TRIGGER_FIRED_2026_09_25;
  full 200-min/4-discharge machinery preserved on the card (probe rejects it — see A0).
- **HVAC-RELOADING-ROOM-PLACEHOLDER-READERS-1** (L1965) — Piece B. Evidence: D5
  `hvac.py:2278-2296`, D6 `presence.py:2148-2157`, `continuous_occupied_since`
  `hvac_zones.py:746-754`, F7 (zone.rooms frozen at discovery).
- **HVAC-GUEST-AS-ZONE-PERSON-1** (L20648) — Piece C.
- **HVAC-DEGRADED-ROOM-TRIPWIRE-1** (L1903) — v5.103.15 in-flight; classifier reused by B.

### Memory bodies pulled
- `feedback_suppression_needs_discharge` — every hold names re-arm + discharge + restart.
- `feedback_measure_before_build` — D-A0 done; Piece A restructured accordingly.
- `feedback_marginal_benefit_pushback` — knob-turn dominates the code build on the data.
- `feedback_extend_existing_never_rebuild` — Piece B rewires onto v5.103.15; Piece A
  extends existing hold knob.
- `feedback_falsify_before_asserting` — INV-A1 rewritten to be falsifiable against the
  producer's actual behaviour (occupancy-driven retreat only); INV-B3 rewritten.
- `feedback_tier2plus_prior_art_scan` — REUSE/BUILD verdicts below (person→room binding is
  REUSED, not NEW).
- `feedback_coincidental_equality_masks_concept_split` — Piece C recommendation.

### Prior-art scan — REUSE/BUILD per proposed piece (file:line)

Piece A (knob-turn baseline + PARKED code design):
- **REUSED — per-room night-hold knob:** `CONF_HVAC_VACANCY_HOLD_NIGHT` (v5.103.8), effective
  at `_effective_hvac_hold_seconds` (`hvac_zones.py:894`), applied in the tail-hold path
  around `hvac_zones.py:643`. Options-flow range **0–7200 s** (`config_flow.py:11739`). This
  is the WHOLE Piece A baseline: raise Jaya Bedroom from live 1800 s to 5400 s (pending
  operator approval).
- **REUSED — night hold table:** `ROOM_TYPE_HVAC_HOLD_NIGHT` (`const.py:1230-1242`) — the
  per-room override multiplies this baseline. Unchanged.
- **REUSED — night window:** `FAN_TRUST_STATES = ("home_night","sleep","waking")`
  (`hvac_const.py:881`). Piece A (if built) uses this exact set — not a new time window.
  Probe reference window 22:00–08:00 covers all three.
- **REUSED — person→room binding:** `PersonCoordinator.get_room_occupants`
  (`person_coordinator.py:1554`); trust helpers `trustworthy_persons_in_room`
  (`_ble_corroboration.py:67`) and `phone_trustworthy` (`_ble_corroboration.py:34`). **No new
  binding config.** Includes the phone-left-behind gate via `phone_trustworthy`.
- **REUSED — radar-blip tail-restart is EXISTING producer behaviour**, not a corroborator.
  `_compute_hvac_occupied` (`hvac_zones.py:966-1035`) rides room `STATE_OCCUPIED`: raw blip
  → room on; held-room clears tail (`source="held"`) and re-tails on fall; post-release
  rising edge re-arms (`source="edge"`). Verified in probe (09-24 room on 01:58:27 →
  hvac_occupied on 02:01:54; 09-25 02:25:43 → 02:29:51). **Corroborator (b) dropped.**
- **NEW (only in the PARKED code build) — "still_sleeper" arm_source and a suite-BLE
  stationarity predicate.** Not built at ship; kept in the parked design.

**Explicit corrections to rev-1 prior-art claims:**
- Rev-1 said "`occupancy_source='override'` BLE anchor". WRONG. §9c: `override` is the
  manual per-room Override Occupied/Vacant switch, NOT a BLE anchor. Dropped from spec.

Piece B (rewire only; no new predicates):
- **REUSED — shared retreat gate:** `_zone_conditioning_retreat_ok` (`hvac.py:3830`) via
  `conditioning_retreat_ok` (`hvac_zones.py:1085`).
- **REUSED — established gate for D6:** `is_zone_hvac_established`
  (`hvac_zones.py:1043`, symbol resolved). C7 named D6 as a **sanctioned exception** to the
  shared-gate rule; D6 stays raw at the presence.py producer, and instead the **hvac.py
  consumer call site** gates on `self._zone_manager.is_zone_hvac_established(zone_id)`.
  presence.py is UNTOUCHED.
- **REUSED — v5.103.15 classifier:** `is_zone_transient_blocked`,
  `_coordinator_absent_this_pass`, `excluded = not defined`.
- **REUSED — synthetic-empty placeholder path:** `hvac_zones.py:616-641`.
- **NEW — none.** Every fix is a rewire onto existing predicates + one new distinct D5 defer
  reason `energy_shed_cap_deferred_unestablished` for logging clarity.

Piece C:
- **VERIFY-FIRST citations corrected (rev-2):** real sleep-veto site is
  `aggregation.py:4298-4382`; non-sleep person-home bias is `aggregation.py:4424-4522`
  (rev-1 cited stale line numbers `:4017-4019` / `:4152-4154`). Verify-first stands.

### Code locations surveyed
- `custom_components/universal_room_automation/domain_coordinators/hvac.py` — tick
  (`:1356-1547`), D5 duty-cycle occupancy defer (`:2271-2289`), D6 stale-failsafe consumer
  (`:2063`), retreat delegate (`:3830`), F8 pre-cool (`hvac_predict.py:583`), F9 pre-heat
  (`hvac_predict.py:1386`), row-10 arrester comfort-delay raw fallback
  (`hvac_override.py:2336`).
- `.../hvac_zones.py` — producer (`:966-1035`), tail-hold (`:894` / apply site ~`:643`),
  `continuous_occupied_since` (`:746-754`), synthetic-empty (`:616-641`),
  `is_zone_hvac_established` (`:1043`), retreat gate (`:1085`), zone-status attrs (`:751`).
- `.../presence.py` — D6 Source-4 producer (`:2148-2157`) — **not touched by Piece B**.
- `.../person_coordinator.py:1554`, `_ble_corroboration.py:34,:67`.
- `const.py:1230-1242`, `hvac_const.py:881`, `config_flow.py:11739`.
- Aggregation: `aggregation.py:4298-4382`, `:4424-4522` (Piece C).

---

## Piece A — night still-sleeper (RESTRUCTURED per D-A0)

### A-0 Ship path (recommended, zero code): raise Jaya Bedroom `hvac_vacancy_hold_night`

The measurement (probe, 7.8 nights) shows Jaya Bedroom is the ONLY affected bedroom; sleep-state
retreats had needed-extension gaps of **32.6 / 45.9 / 54.4 min** (`ura_activity_log`; probe max
55.6 min in gap-window). All 13 stationary-in-suite episodes returned within 56 min; 0/9
STAYED (genuine-exit) episodes were stationary in-suite.

**The knob is already the correct rung.** Per-room `CONF_HVAC_VACANCY_HOLD_NIGHT` is
options-flow (`config_flow.py:11739`, range 0–7200 s) — legitimately operator-tunable, not a
safety bound. Existing consumer: `_effective_hvac_hold_seconds` (`hvac_zones.py:894`),
applied in the tail-hold branch around `hvac_zones.py:643`. Zone-scoped by construction (the
knob lives on the room; only Jaya's room's tail lengthens).

**Recommendation (operator decision required before turning it):**
`switch.<...jaya_bedroom>` `hvac_vacancy_hold_night`: **1800 → 5400 s** (90 min). Rationale:
covers max measured 55.6 min gap + one 5-min tick + margin, well under the 7200-s ceiling.

**Cost, measured:** conditioning zone_2 up to ~60 extra minutes after a genuine night exit.
Probe: **zero genuine night exits** in 7.8 nights (every real Jaya morning departure landed
in the `home_day` table, ≥07:30, where the night hold does not apply). Cost realised = 0.

**Discharge (per suppression-needs-a-discharge):** the knob is the existing tail-hold — house
state exits `FAN_TRUST_STATES` → day hold takes over (60 s); person leaves during night → tail
expires normally after 5400 s; restart → tail-hold state rebuilds from D1 producer. Nothing
new to discharge.

**Acceptance (A-0):**
- **Live:** re-run `scripts/probes/hvac_night_sleeper_probe.py --days 8` two weeks after the
  knob change. **Pass** = zero zone_2 retreats during `sleep`/`home_night`/`waking` on nights
  Jaya was stationary in-suite. **Fail** = any such retreat (revives Piece A build).
- **Live (discriminator):** on any night Jaya's phone is genuinely `not_home` before 22:00,
  zone_2 must retreat within (5400 s + 5-min tick) of the last room drop.
- **README write-back:** the observed (post-knob) retreat-rate table replaces the current
  09-24/09-25 anchor row.
- **No soak.** This is a one-shot re-probe, not a "watch for a week".

### A-1 PARKED code build — design preserved, revival triggers explicit

**Status:** PARKED. Do not build unless a revival trigger fires. This section carries the
design (with rev-1 review findings folded) so a future cycle can uncork it fast without
re-deriving.

**Revival triggers (either):**
1. A genuine night exit (Jaya `not_home` or Bermuda area outside the suite union) is followed
   by a zone_2 hold > 30 min while the room reads vacant (i.e. the longer 5400-s knob costs
   real comfort/energy in the wild).
2. A re-probe (any bedroom, any zone) shows a second affected room with sleeper retreats
   under the new baseline — the class is not Jaya-only.

**Design (constraints for revival, non-negotiable):**

- **Person→room binding:** `PersonCoordinator.get_room_occupants`
  (`person_coordinator.py:1554`) + REUSE `_ble_corroboration.trustworthy_persons_in_room`
  (`:67`) and `phone_trustworthy` (`:34`). NO new binding config. Phone-left-behind gate
  provided by `phone_trustworthy`; a phone that hasn't moved in ≥ N min while stationary
  score is high is not trustworthy (existing semantics).
- **Freshness source INDEPENDENT of value change.** A frozen Bermuda `*_area` (unchanged for
  hours) yields distance variance 0 — that is NOT stationary, that is a stuck sensor. Use the
  entity `last_updated` / `last_reported` from the recorder / state machine, not the value.
  A stationary predicate MUST require: `phone_trustworthy` True AND area last_updated within
  freshness window AND distance last_updated within freshness window AND distance pstdev ≤
  threshold over the dwell.
- **Window:** exactly `FAN_TRUST_STATES` (`hvac_const.py:881`) —
  `("home_night","sleep","waking")`. Probe reference window 22:00–08:00. No new time window.
- **Suite union for area.** Bermuda flaps Bedroom↔Bathroom continuously (rev-1 discriminator
  would have failed the 09-24 anchor at 93 % Bathroom, 7 % Bedroom). Suite = room + all
  scanner areas configured for that room (existing per-room config).
- **Blip corroborator (b) is DROPPED.** Rev-1's option (b) is already existing producer
  behaviour (`hvac_zones.py:966-1035` `source="held"`/`"edge"`). No new blip rule.
- **Extension is per-pass in the tail-EXPIRED branch of `_compute_hvac_occupied`**
  (`hvac_zones.py:~1010-1020`), NOT baked in at the falling edge. On each pass, if the tail
  would expire AND the still-sleeper predicate is True AND the room has NOT been released
  since last arm, hold `hvac_occupied=True` for this pass; set attr `arm_source="still_sleeper"`.
- **Never re-arm a released room** (C6 hazard). Once the predicate goes False (person left
  the suite / freshness lost / house-state exit), the room is RELEASED; a subsequent True
  predicate in the same night does NOT re-extend until the room next transitions on→off
  through a real occupancy edge.
- **Cap:** `HVAC_NIGHT_STILL_SLEEPER_MAX_EXTENSION_MIN = 90` (module const, `hvac_const.py`;
  matches probe max + margin).
- **Dwell:** 10 min stationarity before arming (probe: Jaya in-suite well before every drop).
- **State surface:** REUSE the existing per-room diagnostic entity
  `binary_sensor.<room>_<room>_hvac_occupied` (`binary_sensor.py:745`); expose
  `arm_source="still_sleeper"` + `still_sleeper_remaining_s` as attrs. **No new entity.**
- **Shadow-attribute-first with actuation gated.** Ship the predicate + `arm_source` attr
  first WITHOUT touching `hvac_occupied` (shadow mode). Kill-switch entity
  `switch.ura_hvac_coordinator_night_still_sleeper_hold` (RestoreEntity, default OFF)
  toggles actuation on. Two-stage roll-out.
- **D6 interaction:** the still-sleeper extension keeps the room's `hvac_occupied` True, so
  D6 Source-4 counts it. This is intended (a still-sleeper IS occupancy). Piece B's D6 gate
  is orthogonal (it excludes coordinator-absent rooms, not still-sleeper rooms).
- **Discharge (explicit; suppression-needs-a-discharge):** (1) `phone_trustworthy` False /
  freshness lost; (2) area leaves suite union; (3) house-state exits `FAN_TRUST_STATES`;
  (4) `HVAC_NIGHT_STILL_SLEEPER_MAX_EXTENSION_MIN` cap; (5) restart — extension state is NOT
  persisted, next producer pass re-evaluates from scratch (**restart gap: after a restart the
  extension is dormant until the room next goes off→on and the predicate arms; this is
  intentional fail-closed**).

**Invariants (falsifiable) for the parked design:**
- **INV-A1 (reworded, falsifiable):** during `FAN_TRUST_STATES`, no zone retreats to `away`
  driven by that zone's fused occupancy becoming False when a bound zone_person is
  trustworthy-in-suite (per the predicate above) at the retreat instant. Non-occupancy-driven
  retreats (safety, EC coast, D5 shed) are OUT OF SCOPE for INV-A1.
- **INV-A2 (zone scope):** still-sleeper extension in room R affects only R's zone. No
  house-wide read.
- **INV-A3 (degrade safely):** if any predicate input is stale/unavailable/absent, extension
  does not arm. Behaviour reverts to the raised knob baseline.
- **INV-A4 (discharge):** the five discharges above cover every reachable state; no path can
  hold a released room extended.

**Knob ladder (parked build):**
| Knob | Rung | Why |
|---|---|---|
| `HVAC_NIGHT_STILL_SLEEPER_MAX_EXTENSION_MIN=90` | Module const | Safety cap; changes require review |
| `HVAC_NIGHT_STILL_SLEEPER_DISTANCE_STD_FT=3.0` | Module const | Couples to sensor physics |
| `HVAC_NIGHT_STILL_SLEEPER_DWELL_MIN=10` | Module const | Anti-flap window |
| `HVAC_NIGHT_STILL_SLEEPER_FRESHNESS_MAX_S` | Module const | Independent-freshness gate |
| `switch.ura_hvac_coordinator_night_still_sleeper_hold` | Switch entity (RestoreEntity, default OFF) | Live kill-switch; shadow→actuation gate |
| Per-room `CONF_HVAC_NIGHT_STILL_SLEEPER_ENABLE` | Options flow | Per-bedroom disable |

**Acceptance (revival build; discriminating, evidence-row based):**
- **Sensor:** `binary_sensor.<room>_<room>_hvac_occupied` attrs
  `arm_source in {"tail","edge","held","hallway_excluded","still_sleeper"}`,
  `still_sleeper_remaining_s`, `discharge_reason` on release.
- **Discriminating (evidence-row) test set:** each test asserts the presence/absence of an
  `arm_source="still_sleeper"` transition AND (for the actuation half) the
  presence/absence of a `ura_activity_log` `preset_change`/`preset_change_suppressed` row
  keyed by zone + reason. NOT "count rows".
  - `test_still_sleeper_holds_zone_when_ble_stationary_suite_union` — 09-24 Jaya anchor
    replay (93 % Bathroom): PASS = extension arms.
  - `test_still_sleeper_rejects_out_of_suite_area` — area = hallway/other room: FAIL to arm.
  - `test_still_sleeper_rejects_frozen_sensor` — area value unchanged for freshness window +
    distance last_updated stale: FAIL to arm (INV-A3).
  - `test_still_sleeper_rejects_phone_left_behind` — `phone_trustworthy` False: FAIL to arm.
  - `test_still_sleeper_does_not_re_arm_released_room` — arm → release → predicate True
    again mid-window: does NOT re-arm (C6).
  - `test_still_sleeper_zone_scope` — arm on zone_2 room does not affect zone_1/zone_3.
  - `test_still_sleeper_discharges_on_fan_trust_state_exit` — house exits `FAN_TRUST_STATES`
    → release within one pass.
  - `test_still_sleeper_cap_releases_at_max_extension` — cap fires; discharge_reason=`cap`.
  - `test_still_sleeper_restart_clears_extension` — restart mid-arm: next pass unarmed.
  - `test_still_sleeper_shadow_mode_writes_attr_but_not_hvac_occupied` — actuation switch OFF.
  - `test_still_sleeper_actuation_mode_extends_hvac_occupied` — actuation switch ON.
- **Wire-in / neuter drill:** each of the above tests must FAIL RED when the corresponding
  production predicate branch is neutered in source; restore, re-verify GREEN.
- **Live:** the D-A0 re-probe (A-0 acceptance) also serves the build: zero sleeper retreats
  on any bedroom. One-shot. No soak.

**A-1 non-goals:**
- No "anyone home" gate. Ever.
- No new time window.
- No change to D7/D8.
- Does not build the parked 200-min/4-discharge machinery (probe rules it out).
- No re-derivation of the sleep-veto in HVAC (that lives in aggregation.py; Piece C).

**A-1 tier and reviews (only if revived):** Tier 2-DB with plan review; framings A=local
correctness of predicate + freshness independence + C6 no-re-arm; B=state machine + shadow→
actuation + restart + discharge coverage; C=surfaces + fixture authority + adversarial
completeness (re-enumerate every writer of `arm_source`).

---

## Piece B — placeholder readers (rev-2, findings F15–F20 folded)

### B-1 D6 gated at the hvac.py consumer (F15)

**Change:** at the D6 stale-failsafe consumer in `hvac.py:2063`, gate the raw
`any_room_hvac_occupied` read on
`self._zone_manager.is_zone_hvac_established(zone_id)` (existing predicate,
`hvac_zones.py:1043`). If not established, D6 defers (no `stale_occupancy` away, no
stuck-signal NM).

`presence.py:2148-2157` is UNTOUCHED. This preserves C7's sanctioned exception (D6 is the
one reader that legitimately runs on the raw producer signal at the producer tier); the
gate lives at the HVAC consumer.

**Distinct log reason:** the D6 defer path emits reason `stale_failsafe_deferred_unestablished`
in `ura_activity_log` (`hvac.py` action stream), distinct from any existing D6 reason —
required for the acceptance oracle below.

### B-2 D5 coast defer via shared gate (from rev-1, kept)

At `hvac.py:2278-2296`, replace the raw fused-occupancy read with the shared retreat check:
defer when `not self._zone_conditioning_retreat_ok(zone)`. **Distinct D5 defer reason
`energy_shed_cap_deferred_unestablished`** (F17) — required by the acceptance oracle.

### B-3 Continuity clock — narrowed gate (F16)

At `hvac_zones.py:746-754`, `continuous_occupied_since` holds its previous value (does NOT
reset) ONLY when the room is under a v5.103.15 transient block OR a LIVE room's coordinator
is coordinator-absent this pass. **Never hold for an EXCLUDED (failed/disabled/removed)
room** — an excluded room's clock would otherwise freeze forever (§9b: excluded acts as if
not defined). Concretely: hold iff `is_zone_transient_blocked(room)` OR
(`_coordinator_absent_this_pass(room)` AND NOT `is_room_excluded(room)`). Excluded rooms
follow the normal reset path.

**Deliberation on dropping B-3 entirely:** the continuity clock's downstream consumers are
the stale-occupancy failsafe (D6, now gated by B-1) and optimizer stuck-occupancy
telemetry. B-1 already prevents D6 from acting on a synthetic empty; the residual value of
B-3 is the optimizer telemetry not spuriously resetting during a reload. Cost of B-3 is
one narrow conditional. **Kept, with the F16 narrower gate**; if a reviewer prefers to
drop it entirely on the grounds that B-1 covers the only load-bearing consumer, that is a
legal simplification and this plan does not oppose it — reviewer C to decide.

### B-4 Per-site disposition table (F18) — enumerate now, do not defer to reviewers

Every raw reader of `any_room_hvac_occupied` / the synthetic-empty flag / the fused signal
on a decision path (grepped in this planning pass; symbols resolved per F20 — reviewer
re-greps to confirm):

| Site | Symbol / role | Disposition | Reason |
|---|---|---|---|
| D5 coast defer (`hvac.py:2278-2296`) | `_maybe_defer_energy_shed_cap` | **FIX** (B-2) — route through `_zone_conditioning_retreat_ok`; reason `energy_shed_cap_deferred_unestablished` | Reviewer D F3 repro |
| D6 stale-failsafe consumer (`hvac.py:2063`) | stale_occupancy consumer | **FIX** (B-1) — gate on `is_zone_hvac_established(zone_id)`; reason `stale_failsafe_deferred_unestablished` | one-tick away + stuck-NM |
| `continuous_occupied_since` (`hvac_zones.py:746-754`) | continuity clock producer | **FIX** (B-3, narrowed) | reset on synthetic-empty poisons D6 / optimizer |
| **F8 pre-cool** (`hvac_predict.py:583`) | pre-cool eligibility read | **JUSTIFY (no fix)** | pre-cool DRIVES conditioning UP (adds comfort), never toward away; a false-empty here causes at worst one skipped pre-cool tick, which the next tick corrects. Fail-safe direction. |
| **F9 pre-heat** (`hvac_predict.py:1386`) | pre-heat eligibility read | **JUSTIFY (no fix)** | same as F8, opposite verb. Skipped-tick self-corrects. |
| `last_occupied_time` (producer bookkeeping in `hvac_zones.py`) | timestamp only | **JUSTIFY (no fix)** | display / analytics only; not a decision input. |
| `zone_presence_state` display (`hvac.py:4190-4191`) | UI / diagnostic | **JUSTIFY (no fix)** | display-only per §3.2 bypass list; not a trust decision. |
| `ura_activity_log` detail fields | logging only | **JUSTIFY (no fix)** | writes reflect the decision; do not drive it. |
| **row-10 arrester comfort-delay raw fallback** (`hvac_override.py:2336`) | tri-state guard fallback (`:2304-2340`) | **JUSTIFY (no fix)** — but ADD an assertion test | tri-state guard already handles the None case (§3.2); raw fallback fires only when the delegate is unavailable. Add a test that with the delegate available the raw path is NEVER taken. |
| **F7 zone.rooms frozen at discovery** | producer construction | **DEFER (own card)** | crosses fast-path territory; separate scope. |

Reviewer C's job is to re-grep and add any missed site to this table with a disposition —
NOT to enumerate from scratch (F18: do not defer enumeration to reviewers).

### B-5 Invariants (rev-2)

- **INV-B1 (retained):** no reader on a decision path that could drive a zone toward `away`
  acts on a synthetic-empty. Fixed sites: D5, D6. Justified sites: F8, F9, row-10 (with
  test).
- **INV-B2 (narrowed):** `continuous_occupied_since` does not reset while a room is
  transient-blocked or a LIVE room is coordinator-absent this pass. Excluded rooms follow
  normal reset semantics.
- **INV-B3 (REWORDED — F17):** **when the zone is established, Piece B's decisions are
  byte-identical to develop post-v5.103.15.** (Rev-1 said "healthy path" which was
  ambiguous — a zone can be unhealthy-but-established, and Piece B intentionally changes
  behaviour on the unestablished path. Byte-identity is only defensible on established.)

### B-6 Wire-in anchors + neuter drills

- **D5 anchor (F19-conformant):** integration test sets `switch.ura_ec_coast_active` (or
  equivalent) ON, drives `zone_runtime_exceeded=True` on zone_1, `home_evening`,
  zone_1=[Office occupied, Study empty], reload Office coordinator. Assert: NO
  `preset_change` to `away` in `ura_activity_log` during the unestablished window; a
  `preset_change_suppressed` (or the distinct-reason equivalent) row appears with reason
  `energy_shed_cap_deferred_unestablished`.
- **D6 anchor:** unestablished zone (Office reloading) + otherwise-eligible stale window →
  no `stale_occupancy` `preset_change`; a suppressed row with reason
  `stale_failsafe_deferred_unestablished`.
- **Continuity anchor:** unit — room transient-blocked one pass →
  `sensor.ura_hvac_coordinator_zone_{n}_status` attr `continuous_occupied_hours` does not
  reset. Excluded room → clock resets normally.
- **Row-10 anchor:** delegate available → assert raw fallback branch is not entered
  (instrument via a debug counter or a mutation-drill on the raw branch that MUST leave the
  test green).
- **Neuter drill (per site):** revert each fix in production source → the corresponding
  test above FAILS RED; restore, re-verify GREEN. A site whose neuter leaves the suite
  green is an untested site.
- **INV-B3 drill:** on an established zone with no coordinator-absent rooms this pass, an
  integration suite diff against develop post-v5.103.15 is EMPTY.

### B-7 Acceptance criteria (F19 — real surfaces + real oracles)

- **Surfaces (real, not invented):**
  - `sensor.ura_hvac_coordinator_zone_{n}_status` attrs
    `continuous_occupied_hours`, `coordinator_absent_rooms`, `transient_rooms`
    (existing per §3.2 / `hvac_zones.py:751`).
  - `ura_activity_log` rows: `preset_change`, `preset_change_suppressed` (existing;
    §4.2 S1 site).
- **Oracle:** `ura_activity_log` `preset_change` vs `preset_change_suppressed` presence +
  reason, keyed by zone_id + timestamp window around the drive event. Do NOT use
  `hvac_excursion_events` (borrows are unrelated).
- **Live:** post-deploy, force a coordinator reload on a live room in zone_1 during coast
  conditions and confirm (a) no `preset_change` to `away`, (b) a `preset_change_suppressed`
  with reason `energy_shed_cap_deferred_unestablished`, (c) `continuous_occupied_hours`
  unchanged for the affected zone.

### B-8 Non-goals
- Not touching `presence.py` (C7 sanctioned exception preserved).
- Not resolving F7.
- Not changing the retreat gate itself.
- No behaviour change on the established path (INV-B3).

### B-9 Tier and reviews
- **Tier 2-DB.** Framings:
  A = local correctness (each rewire, distinct reasons, B-3 narrowed gate);
  B = cross-coordinator integrity (D6 semantics preserved via consumer-side gate;
  optimizer telemetry; restart; INV-B3 byte-identity on established);
  C = adversarial completeness — re-grep every reader of the fused signal / synthetic-empty
  flag / continuity clock and add any missed row to B-4's table with a disposition. Also
  decide B-3 keep-vs-drop.
- Plan-review pass before build (already this rev-2).

---

## Piece C — HVAC-GUEST-AS-ZONE-PERSON-1 scope check (rev-2)

**Recommendation stands: DO NOT include in this plan. Sequence AFTER Piece B and Piece A's
A-0 knob turn.** Reasons unchanged from rev-1, with corrected citations:

1. **Operator verify-first (2026-08-20).** Verify whether the sleep-veto at
   `aggregation.py:4298-4382` and the non-sleep person-home bias at `:4424-4522` gate on
   real occupancy vs `zone_persons` membership. (Rev-1's `:4017-4019` / `:4152-4154`
   citations were STALE — corrected here.) The verification may shrink or kill the card.
2. **Coincidental-equality hazard.** Piece C would supply a synthetic person; INV-A2 depends
   on real person→room binding. Keep the plumbing disjoint.
3. **Suppression-needs-a-discharge unresolved on the card.**
4. **Blast radius fits its own Tier 2-DB cycle.**

**Proposed sequence:** Piece B → Piece A A-0 (knob turn) → verify-first on
`aggregation.py:4298-4382` and `:4424-4522` → Piece C planning cycle (separate doc) if the
verification confirms the gap.

---

## Sequencing (build order)

1. v5.103.15 merges to `develop`.
2. W2 fast-path plan reviews confirm no overlap with Piece B's D5 / D6 / F8 / F9 / row-10
   sites and no producer-pass ordering conflict.
3. **Piece B build** (Tier 2-DB, three framings, per-site disposition table pre-populated).
4. **Piece A A-0 knob turn** on operator approval (Jaya Bedroom
   `hvac_vacancy_hold_night` 1800 → 5400 s). No code.
5. Two-week re-probe write-back (A-0 acceptance).
6. Piece A A-1 build stays PARKED unless a revival trigger fires.
7. Piece C verify-first → separate plan.

## Deferred items (accounted for, not silently dropped)

- **F7 (zone.rooms frozen at discovery)** — own card follow-up on B evidence.
- **Full 200-min/4-discharge machinery** — probe rejects (max need 55.6 min); preserved on
  HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1 for the historical record.
- **Piece A code build** — PARKED with explicit revival triggers.
- **Morning residual** (3 zone_2 retreats 06:14–07:00 during `home_day` outside
  FAN_TRUST_STATES) — separate card if operator cares about early-morning comfort; not in
  W2 scope.
- **Jaya Zigbee radar hardware repair** — physical, not in this plan.
- **Piece C build** — separate cycle.

## Return summary (rev-2)

- **Measured numbers:** 6 sleep-state sleeper drops in 7.8 nights (5 caused zone_2 retreat);
  needed-extension gaps 32.6 / 45.9 / 54.4 min (ura_activity_log), probe max 55.6 min;
  0/26 non-returning blips in gaps; 13/13 stationary-in-suite episodes returned; 0/9
  STAYED (genuine-exit) episodes were stationary in-suite; distance in ft, stationary
  std 0.4–1.3 ft. Jaya-only on this data; Master 3 drops (0 sleeper), Ziri away all week,
  guest bedrooms 0.
- **Chosen corroborator:** (a) BLE stationary in-suite (suite union), std ≤ 3 ft, with
  independent freshness gate (last_updated on area + distance) and `phone_trustworthy`.
  Corroborator (b) DROPPED — it already exists in the D1 producer.
- **Ship path (recommended):** knob turn only — Jaya Bedroom
  `hvac_vacancy_hold_night` 1800 → 5400 s. Code build PARKED with revival triggers.
- **Invariants:** INV-A1 reworded to occupancy-driven retreat only, restart gap stated;
  INV-A2/A3/A4 kept; INV-B1 kept; INV-B2 narrowed (no hold for excluded rooms); INV-B3
  reworded to "when the zone is established → byte-identical to develop post-v5.103.15".
- **Tiers:** Piece A A-0 = no-tier (operator knob turn + re-probe); A-1 = Tier 2-DB (only
  if revived); Piece B = Tier 2-DB (three framings + plan review + neuter drill per fixed
  site + INV-B3 byte-identity drill on established); Piece C = own Tier 2-DB cycle after
  verify-first.

---

## Change log — findings → sections (rev-1 → rev-2)

| Piece-A findings | Section(s) touched |
|---|---|
| Knob is baseline + recommendation (1800 → 5400 s) | A-0 (new); Ship path; Return summary |
| Code build becomes PARKED with explicit revival triggers | A-1 (new); Deferred items |
| Person→room via `PersonCoordinator.get_room_occupants` (:1554) + REUSE `_ble_corroboration` (:34, :67) — no new binding config | Prior-art scan; A-1 predicate |
| `override` is NOT a BLE anchor (§9c) | Prior-art scan (explicit correction to rev-1) |
| Extension per-pass in tail-EXPIRED branch, never at falling edge, never re-arm released room (C6) | A-1 design |
| Window = `FAN_TRUST_STATES` (`hvac_const.py:881`); probe 22:00–08:00 | A-1 design |
| Freshness INDEPENDENT of value change (frozen sensor ≠ stationary) | A-1 design; INV-A3 |
| `phone_trustworthy` gate (phone-left-behind) | A-1 design |
| Drop option (b) — blips already re-arm via STATE_OCCUPIED | Prior-art scan; A-1 design |
| INV-A1 reworded (occupancy-driven retreat only); restart gap stated | A-1 invariants |
| D6 interaction | A-1 design |
| Shadow-attribute-first with actuation gated by switch | A-1 design; knob ladder |
| State on existing `hvac_occupied` entity as `arm_source="still_sleeper"` | A-1 design |
| Discriminating evidence-row acceptance; no soak | A-1 acceptance; A-0 acceptance |

| Piece-B findings | Section(s) touched |
|---|---|
| F15 gate D6 at `hvac.py` consumer on `is_zone_hvac_established(zone_id)`; presence.py untouched (C7 sanctioned exception) | B-1; Prior-art scan |
| F16 continuity clock holds only for transient-blocked or LIVE coordinator-absent; NEVER for excluded rooms; weigh dropping B-3 | B-3; B-9 (reviewer C decides drop) |
| F17 reword INV-B3 ("zone established → byte-identical"); distinct D5 defer reason `energy_shed_cap_deferred_unestablished` | B-2; B-5; B-6; B-7 |
| F18 per-site disposition table pre-populated (F8, F9, last_occupied_time, zone_presence_state display, activity-log detail, row-10 raw fallback) — no deferring enumeration | B-4 |
| F19 real surfaces only (`sensor.ura_hvac_coordinator_zone_{n}_status` attrs + `ura_activity_log preset_change` / `preset_change_suppressed`); D5 test sets coast + runtime_exceeded | B-6; B-7 |
| F20 resolve lines by symbol | B-4 (symbols named); B-1 (`is_zone_hvac_established` at `:1043`); across code-locations survey |

| Piece-C findings | Section(s) touched |
|---|---|
| Sleep-veto real citation `aggregation.py:4298-4382`, non-sleep `:4424-4522` (rev-1 `:4017-4019` / `:4152-4154` were stale) | Piece C; Institutional-context (aggregation surveyed); Deferred items |
| Recommendation stands (DO NOT include; sequence after B + A-0) | Piece C |

| Cross-cutting | |
|---|---|
| Re-read C16 (Carrier poll 30-min + 5-min post-write guard), C17 (preset suppression 120 s / temp 5 s), C18 (hot entry 5–10 min), C19 (fan is consequence, not trigger — Jaya narrative corrected) | Read-first note; §9.3 basis for A-0 |
