# PLANNING — Room classification consistency, Option A (ROOM-CLASSIFICATION-CONSISTENCY-1)

**Card:** ROOM-CLASSIFICATION-CONSISTENCY-1 · **Date:** 2026-09-14
**Status:** RE-SCOPED after plan-review + live-config check → D1 (documentation) build-ready; D2/D3 PARKED pending operator PICK
**Basis:** `AUDIT_room_classification_consistency.md` + adversarial plan-review (2026-09-14, FIX-PLAN-FIRST) + live `.storage` check.
**Operator direction:** "Option A but well documented."

---

## What the plan-review + live check changed (READ THIS FIRST)

The plan-review returned **FIX-PLAN-FIRST with a CRITICAL**, and a live `.storage/core.config_entries`
read settled the value question. The original Option A had three build deliverables (D1 doc, D2 wire
basement, D3 retire outdoor coercion). The evidence collapses that:

- **Live config: 0 rooms typed `basement`, 0 zones flagged `outdoor`** (46 URA entries; distribution:
  common_area 15, closet 7, bathroom 7, bedroom 6, generic 2, garage 2, utility 2, infrastructure 1,
  media_room 1). So **D2 and D3 have ZERO current benefit** — they wire code paths that fire for no
  configured room today.
- **D2 is net-negative:** the review (HIGH-3) shows wiring `basement` reachable *simultaneously* turns
  on the `safety.py:2082/2146/2209` hazard behaviours — including an **un-knobbed LOW-severity NM page
  at 65% RH** that a normal room logs silently. A basement is *more* alert-prone, not neutral. Wiring a
  band nobody uses, whose activation creates a new alert source, is negative expected value.
- **D3 is net-negative and dangerous:** the review (CRITICAL-1) found **TWO** coercion sites, not one.
  `safety.py:428` is a display-only chip helper. `safety.py:1319-1323` is the **safety-coordinator's
  sensor-discovery coercion, deliberately built by NM Cycle A (A4/H1/B-HIGH-1) to SUPPRESS humidity
  hazards on outdoor sensors** (see the comment at `safety.py:1301-1307`). "Retire the coercion" would,
  read literally, remove `:1319` and **resume real NM humidity pages on every outdoor sensor** the day a
  zone is flagged outdoor. There is no outdoor zone today, so it fixes nothing now and plants a latent
  regression for later.

**Conclusion (Marginal-Benefit Decomposition):** the entire value of "Option A well documented" lives in
**D1 — the documentation**. D2/D3 are speculative wiring with negative expected value given the live
config. The parsimonious, correct move is: **build D1 now; PARK D2/D3 behind the exact config trigger
that would give them a consumer** — at which point they are required and inherit the review's safety-test
requirements. This is surfaced to the operator as a PICK, because it reduces the scope they approved.

---

## Falsifiable invariant (D1 only)
D1 is **pure documentation — it changes NO code and NO runtime behaviour.** The deliverable is a doc
whose every producer/consumer claim is grep-verified against the live tree. Nothing to regress.

---

## D1 — `docs/architecture/ROOM_CLASSIFICATION.md` (BUILD NOW — Tier 1, pure docs)

A single canonical doc mapping every room/zone classification surface, corrected against the plan-review's
grep findings. Per surface: axis, scope, ONE producer (with the honest caveats below), every consumer
with file:line + trust-vs-display, blast radius. Plus the invariants and the two documented hazards.

**The corrected surface map (review-verified — supersedes the audit's table):**

| Surface | Axis / scope | Producer (honest) | Consumers (file:line, trust/display) |
|---|---|---|---|
| `CONF_ROOM_IS_GUEST_ROOM` | property / room | flag; gated by `PresenceGuestDetectionEnabledSwitch` (switch.py:3621) | **flag read** presence.py:4879 (trust); presence.py:5741/:6321 consume the **gate RESULT**, not the flag |
| `CONF_WET_ROOM` | property / room | flag; bathroom seed const.py:1234 via config_flow.py:1449 | automation.py:2522 (read), :2528 (sleep exemption), :2632 (presence arming) — no others repo-wide |
| `ROOM_TYPE_UTILITY` | function / room | `CONF_ROOM_TYPE` enum | ONE row: ROOM_TYPE_TIMEOUTS const.py:1177 (=600, **coincidentally == garage** — Bug Class #63, note it) |
| `ROOM_TYPE_INFRASTRUCTURE` / `switch.infrastructure` | function / room | **`coordinator.py:336` hardcodes the `"infrastructure"` string** (NOT the enum) to set `_infrastructure_room`; switch.py:5130 re-asserts restored state **only after entity-add** → **reload window where the enum, not the switch, is authority** | energy exclusion aggregation.py:3522+; ROOM_TYPE_TIMEOUTS |
| `CONF_SHARED_SPACE` | property / room | flag | automation.py:3150 accessor (callers :3172/:3213); aggregation.py:1508 thresholds; aggregation.py:1211 display |
| `CONF_ZONE_IS_OUTDOOR` | property / **zone** | flag | **TWO coercion sites**: safety.py:428 (display chip only, via aggregation.py:4570) AND safety.py:1319-1323 (discovery → `_sensor_room_types="outdoor"`); the latter feeds safety.py:2076 (**suppresses ALL humidity hazards**), :2146 (swing gate), :707/:766/:799 (rate-detector excludes); also presence.py:5661 AWAY veto |
| `basement` (room_type key) | function / room | **UNREACHABLE** — no `ROOM_TYPE_BASEMENT` const (const.py:421-429), not in either dropdown, no producer; bands `{65/75/85, 2.0h}` safety.py:214 sit dead | — (0 rooms typed basement, live-confirmed) |

**Invariants the doc states:**
1. **One producer per flag — with the two honest exceptions documented, not hidden:** (a) infrastructure's
   enum-vs-switch authority has a reload window (`coordinator.py:336` re-derives from room_type each
   construction); (b) `CONF_ZONE_IS_OUTDOOR` is coerced to a room-type string at **two** sites — one
   display, one load-bearing hazard-suppression built by NM Cycle A. Neither is "fixed" here; both are
   documented so the next cycle doesn't trip on them.
2. **Explicit scope:** `CONF_ZONE_IS_OUTDOOR` is zone-scoped; every other flag is room-scoped.
3. **KEEP+DOCUMENT (not delete):** `_humidity_table_key`'s `"outdoor"` return (safety.py:286-287) is
   unreachable (resolve_safety_bands early-returns on `rt=="outdoor"` at :324) — dead but semantically
   load-bearing; keep with a one-line note. Same for the dead basement bands.
4. **Five room_type-keyed tables exist** (ROOM_TYPE_TIMEOUTS const.py:1171, _FAILSAFE_DURATIONS :1196,
   _RECHECK_FACTOR :765, _BLE_HOLD_CAP_DEFAULT :1207, _FEATURE_DEFAULTS :1232). Document that a new
   room_type value falls through ALL five to defaults — so adding one is never "just an enum member."

**Institutional citations (review-mandated):** `PLANNING_zone_safety_alert_split.md` (owns
`resolve_safety_bands`/`evaluate_zone_chip`/the zone_is_outdoor param), `PLANNING_nm_overhaul_2026_07.md`
(NM Cycle A authored the outdoor exclusion + the :1319 coercion — the authority on *why* the room-type
path is dead by design), `PLANNING_onboarding_simplify.md` (owns ROOM_TYPE_FEATURE_DEFAULTS + the
one-producer CONF_WET_ROOM decision). Existing tests that already pin this behaviour:
`test_zone_safety_alert.py:62-65,:211` (basement bands), `test_safety_coordinator.py:1266-1300`
(`_sensor_room_types="basement"`).

- **Acceptance:** **Verify** the doc lists all 7 surfaces with review-verified producer+consumers+blast
  radius; **Verify** it names BOTH outdoor coercion sites and the infra reload window explicitly;
  **Verify** it records the 5 room_type tables + the utility/garage coincidental-equality. No code, no test.

---

## D2 — Wire the `basement` orphan — **PARKED**
**Revival trigger:** an operator wants a room typed `basement` (today: 0). When revived it is NOT a
neutral wiring fix — per plan-review HIGH-3 it must:
- enumerate all four activated behaviours (safety.py:2082 ladder, :2146 swing disabled, :2209 LOW-rung
  65% paging **un-knobbed**, chip);
- **decide explicitly whether the 65% LOW NM page is desired**, and if not, add a CM knob override
  (the `normal` branch honors CONF_HUMIDITY_NORMAL_*; basement does not);
- add the ROOM_TYPE_BASEMENT const + dropdown, seed decisions for all 5 room_type tables (HIGH-2).

## D3 — Retire the outdoor coercion — **PARKED**
**Revival trigger:** an operator flags a zone `outdoor` (today: 0), OR a cycle deliberately reworks the
NM outdoor-humidity-exclusion. When revived, per plan-review CRITICAL-1 / MEDIUM-1:
- enumerate BOTH coercion sites; **`safety.py:1319-1323` stays** (it is the NM-A hazard suppression) unless
  the cycle carries its own before/after hazard-emission proof;
- if a passthrough is introduced, state the `is_outdoor`-before-`garage`/`bathroom` precedence explicitly
  (else a garage in an outdoor zone regresses freeze detection);
- the `ROOM_TYPE_OUTDOOR` room-dropdown bullet is **dropped** (HIGH-1 footgun: one click silently disables
  freeze+overheat alerting for a room) unless promoted to a named delta with the opt-out documented.

## D4 — Regression fence — **folds into D2/D3 when revived**
Not needed for D1 (no code). When D2/D3 revive, the fence must cover the safety-coordinator discovery +
`_handle_humidity` hazard path (not just the six display reads) and include a mutation drill on
`safety.py:1319-1323` (MEDIUM-3).

---

## Non-goals
- **NOT** unifying flags (Option B, parked).
- **NOT** touching the GUEST gate, AWAY veto, or the NM outdoor hazard-suppression coercion (`:1319`).
- **NOT** wiring dead paths (basement/outdoor) that have no configured consumer — deferred to their triggers.

## Recommendation to operator
Build **D1 (documentation) now** — pure win, zero risk, delivers "well documented." **Park D2/D3** — the
live config (0 basement, 0 outdoor) gives them no benefit today and the review shows both are net-negative
until a real consumer exists. PICK: (A) D1-only + park [recommended] · (B) full Option A with the
review's safety tests attached.
