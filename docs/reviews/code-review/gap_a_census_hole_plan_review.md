# Plan Review — GAP-A-CENSUS-HOLE-1

**Plan:** `docs/planning/PLANNING_gap_a_census_hole.md` (rev 1, 2026-08-16)
**Base commit:** 48ba48824 on `develop`
**Tier:** 2-DB (adversarial plan review, single pass, pre-build)
**Reviewer framing:** independent re-grep of all load-bearing claims; adversarial
freshness / circularity / consumer-asymmetry probes.

## Verdict

**SHIP the plan, with two notes to fold into the build brief.** The
core proposal is sound: `census_count == 0` on path α is a semantic
mismatch with H1's stated intent, `CensusZoneResult.face_recognized_persons`
is the correct signal, and the threading (payload key → coordinator
field → `infer()` kwarg with default 0) preserves I3 byte-identity for
all pre-existing callers. Consumer sweep verified; merge order sound;
no scope growth.

The **circularity concern (Question 3) is answered clean** — see §3.

Findings below are LOW/MEDIUM only; none block the build.

---

## Independent verification of claims

### Q1 — Trace confirmations

| Claim | Verified | Notes |
|---|---|---|
| `presence.py:1047-1057` — α clause with `census_count == 0` | ✅ | Exact match; comment at :1039-1046 documents H1 intent and I3 invariant. |
| `presence.py:4194-4207` `_census_count` assigned from payload `interior_count` | ✅ | Confirmed at :4201. |
| `camera_census.py:3079-3103` — `identified_count = |ble ∪ face|`, `total = identified + held_unidentified` | ✅ | :3082 union, :3083 len, :3096 sum. **BLE-only membership does bump `total_persons` with zero camera evidence.** Plan's bug thesis stands. |
| `camera_census.py:158` `face_recognized_persons: list[str]` field on `CensusZoneResult` | ✅ | Populated in returned `CensusZoneResult` at :3079-3115. |
| `SIGNAL_CENSUS_UPDATED` payload does NOT currently carry `face_recognized_persons` / `face_recognized_count` | ✅ | Confirmed via `_handle_census_update` at :4194-4230 reading only `interior_count / unidentified_count / confidence`. |

All Q1 trace claims verified.

### Q2 — Freshness bound: no knob needed (with caveat)

The planner explicitly declined to fabricate the window value. It is:

- **`CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800`** (30 min) —
  `custom_components/universal_room_automation/const.py:2609`.

The two-gate structure is verified as described:

1. **Age gate** at `camera_census.py:3033` — `if age <= 1800`.
2. **Tracker cross-check** at `camera_census.py:3034-3057` — drops the
   face-recognized person if `person.<slug>.state == "not_home"`.
   Explicit "stale-face latch guard" for the documented
   `sensor.frigate_*_last_camera` `unavailable⇄camera` re-stamp flap.

Adversarial case tested — "face 55 min ago, tracker says home but
actually stale": AGE gate elapses at 30 min, so it drops. Age is
bounded even against a stale/hostile tracker signal. **Plan's
"no knob" claim holds on the happy path.**

**But — MEDIUM (freshness fail-open):** the cross-check is documented
fail-OPEN when the person entity is missing / unknown / unavailable
(`camera_census.py:3039-3041` comment; the `if person_state is not
None AND state == "not_home"` construct only drops on positive-away
signal). Legal-config adversarial repro: `person.ezinne = unavailable`
(HA startup, integration reload, GPS provider outage) + a face
recognized 25 minutes ago → face_recognized_count = 1 → α veto
blocked despite Ezinne genuinely absent. In this mode, the ONLY
freshness bound is the 30-minute age gate.

30 min is a defensible upper bound for a safety-critical veto (won't
persist across a real absence). This is not fatal and does not
require a new operator knob. **But the plan should explicitly
acknowledge the fail-open mode in its Freshness §** — the current
prose implies "two gates, both must fail" when it is actually "either
gate holds, one is fail-open under legal states". Add one sentence
so the invariant statement is honest. No code change; documentation
only.

### Q3 — Circularity check (highest-value question)

**Answer: NO circularity. Composition is sound.**

The proposed change makes the α veto depend on `face_recognized_count`,
which comes from `_get_face_recognized_person_names`, which cross-checks
`person.<slug>.state`. PATH-ALPHA-DENOM-1 changes how
`all_tracked_persons_away` is classified (H2/O1 overlay on URA's
internal denominator).

The critical fact: **URA does not write `person.<slug>.state`**. The
HA `person` entity is fed by device_trackers (GPS, router, etc.),
which are strictly upstream of URA. The face cross-check therefore
reads a signal that is independent of PATH-ALPHA's classifier output.
No feedback edge exists.

Second-order check — could PATH-ALPHA indirectly influence
`person.state` via a HA automation reading URA sensors and calling
`person.reload`? Not in this repo; URA does not expose a person-state
override, and no automation in the plan touches person.state. If a
future URA cycle ever writes to `person.*`, this composition must be
re-audited — worth capturing as a fence in the vibememo / kanban card
for GAP-A. **Not a build blocker; the fix ships safely today.**

### Q4 — Consumer enumeration spot-check

Independent re-grep of `census_count` in `presence.py` produced the
same site list as the plan (12 hits at :108/:115/:117/:140/:158/:961/
:978/:1026/:1039-1050/:1127/:1167/:1285/:1309/... etc. — matches).
Three sites spot-verified vs plan verdicts:

- **:1026** nobody-home backstop (`census_count == 0 and not
  any_zone_occupied → AWAY`). **Unchanged verdict correct** — this
  path is TIGHTER than α (also requires `not any_zone_occupied`);
  BLE-only census>=1 lands here as no-op and drops through to α,
  where the fix applies. No conflict.
- **:1167** `has_people = census_count > 0 or any_zone_occupied` (drives
  sleep/wake). **Unchanged verdict correct** — as plan states, a
  BLE-home phone at bedtime is legitimate sleep evidence. Fixing
  this consumer would break sleep detection for forgotten phones.
- **:1127 (β outer guard)** — left alone per non-goal. **Asymmetry
  analysis (Q4-follow-up):** after the fix, path α is MORE permissive
  than β on the BLE-only census limb. If `face_recognized == 0` and
  `census_count >= 1` (BLE-only), α fires but β does not. This is
  SAFE — β cannot spuriously fire (stricter gate never activates
  where α wouldn't have anyway). The remaining exposure is:
  forgotten-phone + at least one LOST person + camera empty → α
  fails denominator (H2 doesn't help LOST), β blocked by census
  clause → no veto. Plan documents this as a follow-up card. **LOW
  finding:** consider naming the specific unhandled scenario in the
  follow-up card acceptance criteria, so evidence gathering post-ship
  knows what pattern to look for.

### Q5 — Acceptance criteria drilled both directions

Verified:
- Forward direction (forgotten-phone → CAN go away): present, precise
  fixture at :113. ✅
- Reverse direction (real face → STILL blocked): present at :114. ✅
- Reverse direction (unidentified body → STILL blocked): present at
  :115, correctly asserts unchanged limb. ✅
- I3 byte-identity (default-zero backfill): present at :118. ✅
- Load-bearing cross-check mutation (Tier-3 flavor): present at :119.
  ✅
- Live post-restart write-back to README table: present at :121. ✅
- Merge-order recommendation (PATH-ALPHA first, GAP-A rebases): sound;
  disjoint hunks in same file/function are the expected case, plan
  correctly flags "do not resolve silently — re-review". ✅
- Non-goals fenced explicitly: β, `total_persons` semantics, new
  CONF_*, refactors, FAN-LAYER territory. ✅

---

## Findings

### MED-1 — Fail-open freshness mode not acknowledged in Freshness §
The face cross-check is fail-OPEN when `person.<slug>` is
missing/unknown/unavailable (documented at `camera_census.py:3039-3041`).
In that state, only the 30-min age gate bounds a stale face-block. The
plan's Freshness § reads as "two gates, both hold" when the honest
statement is "two gates; the tracker gate is fail-open by design, and
in the fail-open mode the 30-min age gate is sole defense — which is
still a defensible bound for a veto but should be stated". Fix: add
one sentence to §Freshness. No code change.

### LOW-1 — Cite `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800`
value up-front
Planner correctly declined to fabricate but the value IS in-repo
(`const.py:2609 = 1800` / 30 min). Add to Freshness §. The build must
cite it in the README anyway per plan; naming it in the plan
strengthens the "no knob" argument (30 min is a defensible upper
bound, and the reader shouldn't have to grep for the number that
carries the whole argument).

### LOW-2 — Follow-up card for β should name the unhandled scenario
Plan lists a follow-up card for β with `census_count == 0` clause.
Recommend the card explicitly name the trigger pattern:
**forgotten-phone + at least one LOST person + camera empty**. That
is the *exact* case α still cannot cover after this cycle. Naming it
helps shipwatch/organic-evidence collection know what to look for.

### INFO — Composition-with-PATH-ALPHA fence
Not a finding; a fence for the vibememo record. **If any future URA
cycle writes to `person.<slug>.state`**, the α-veto ↔ face-cross-check
composition becomes cyclic and must be re-audited. Today: no such
write exists.

---

## Institutional context verification

- `git grep "CENSUS_FACE_RECOGNITION_WINDOW_SECONDS"` — 8 hits;
  definition at `const.py:2609 = 1800`.
- `git grep -n census_count custom_components/.../domain_coordinators/presence.py`
  — enumeration matches plan §Consumer enumeration; no missed reader.
- `git grep -n "face_recognized_persons\|face_recognized_count"` —
  field defined `camera_census.py:158`, populated :3079-3115; no
  current reader in `presence.py` (plan's premise stands: this is a
  new payload key, not a duplicated one).
- `git grep -n "person\.<" custom_components/.../` for any URA writer
  to `person.*` — none. Confirms Q3 no-circularity.

## Non-scope, non-drift observations

Plan text is tight, single-deliverable, hard operator scope fence
honored. No scope growth to flag. The "one payload key + one field +
one kwarg + one clause" framing is exactly the minimal-diff shape
that composes cleanly with a concurrent PATH-ALPHA cycle in the same
function.

---

**Reviewer disposition: SHIP the plan.** Fold MED-1 (fail-open
sentence) and LOW-1 (window value cite) into the plan before build
dispatch — both are text-only. LOW-2 goes on the β follow-up card
when it's opened. INFO fence goes on the GAP-A kanban card.
