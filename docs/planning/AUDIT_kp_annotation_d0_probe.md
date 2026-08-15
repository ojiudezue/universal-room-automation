# AUDIT: Known-Person Annotation D0 Probe (read-only)

**Date:** 2026-08-14 (run 2026-08-15 01:45 UTC)
**Plan:** `docs/planning/PLANNING_known_person_annotation.md` rev-3 (commit a28e4568f)
**Method:** one-shot read-only Python probe over the live HA recorder
(`sqlite3 'file:/config/home-assistant_v2.db?mode=ro'`) + `.storage` registry reads via
`ssh ha "python3 -" < script.py`. No writes, no config changes, no entity pokes.
(Plan names this artifact `AUDIT_known_person_d0_probe.md`; committed under the
dispatcher-specified filename `AUDIT_kp_annotation_d0_probe.md`.)

## Headline verdict

**PARK v1 build entirely — "producer coverage insufficient" (plan adjudication rule, third branch).**
Sub-probe (b) measured **0.0%** of perimeter person events with a real name available at
t=0 (threshold to ship: ≥50%; threshold to park: <30% *at any timing* — observed ≤0.1% even
at +30s). This parks BOTH legs (annotation and stranger). Sub-probes (a.iii) and (d)
independently add blockers: **no producer exposes any confidence attribute**, and the primary
doorbell's face producer has **never emitted a name** in the window.

## Probe window deviation

Recorder retention is **7.69 days** (earliest row 2026-08-07 09:12 UTC), not the plan's 30
days. All counts below are over 7.69 days. This weakens rate estimates but cannot change the
verdict: 0% at t=0 over 1,532 events is not a small-sample artifact.

## D0.pre.1 — tracked_persons currency audit

Live entry (`Universal Room Automation` config entry):
`tracked_persons = ["person.ezinne", "person.oji_udezue", "person.jaya", "person.ziri"]`.

| Slug | person entity exists | friendly_name | Missing? |
|---|---|---|---|
| person.ezinne | yes | Ezinne | — |
| person.oji_udezue | yes | Oji Udezue | — |
| person.jaya | yes | Jaya | — |
| person.ziri | yes | Ziri | — |

No household member appears missing (registry holds no other `person.*` entities). List is
current. **NOTE for D1 design:** Frigate emits first-name identities (`Oji`, not
`Oji Udezue` / `oji_udezue`) — the slug↔recognized-name mapping must match on first-name
token, not friendly_name equality.

## D0.pre.2 — message-format decision

Default binds absent operator objection: `Person detected — likely {names}.` on its own
line at the END of the message. **Recorded as CONFIRMED-BY-DEFAULT; operator may override
at D0 review.** (Moot for v1 given the park verdict; binds for any revival.)

## (a) Identity-producer inventory per perimeter camera

`perimeter_cameras` (live entry, 9): reolinkstudybporchptz, rear_ptz (high-res channel),
utilities_ptz (high-res channel), front_side_ptz, armcrest, hot_tub, pool_equipment,
g5_bullet, back_yard.

- **Frigate-2 face producers:** every perimeter camera has `sensor.<slug>_last_recognized_face`
  AND a `_2` sibling in the registry — producer *entities* exist universally.
- **UniFi Protect face attributes:** exhaustive scan of latest attributes on all `camera.*`
  and `event.*smart_detection*` entities found **zero** face-related attribute keys.
  **UP is NOT an identity producer on this install.**
- **Doubletake:** zero registry/recorder hits. Confirmed retired.
- **llmvision:** excluded per rev-2 binding decision #1 — not probed.

Per-producer 7.69-day state history (both legs):

| Camera | Real-name emissions | Distinct states |
|---|---|---|
| reolinkstudybporchptz (+_2) | 0 | unavailable/Unknown only |
| rear_ptz (+_2) | 0 | unavailable/Unknown only |
| utilities_ptz (+_2) | 0 | unavailable/Unknown only |
| front_side_ptz (+_2) | 0 | unavailable/Unknown only |
| armcrest (+_2) | 0 | unavailable/Unknown only |
| hot_tub | 2 (Ezinne 1, Jaya 1) | + None |
| pool_equipment | 3 (Jaya 3) | + None |
| g5_bullet (_2 leg only) | 2 (Ezinne 2) | + None |
| back_yard (+_2) | 0 | unavailable/Unknown only |
| doorbell_lite (+_2) | 0 | unavailable/Unknown only |
| madrone_g6_entry | 9 (Jaya 8, Ezinne 1) | + None |
| madrone_g6_entry_2 | 10 (Ezinne 7, Jaya 2, Oji 1) | + None |

Structural observation: the `unavailable`/`Unknown` counts are IDENTICAL across all base
sensors (25/24) and across all `_2` sensors (28/27) — these are synchronized restart/boot
transitions, not per-camera pipeline activity. **6 of 9 perimeter face producers emitted
nothing but boot churn in the entire window.** The only live face pipelines are hot_tub,
pool_equipment, g5_bullet(_2), and madrone_g6_entry(_2).

### (a.iii) Confidence-attribute distribution — BLOCKED

Every face sensor's attribute set is exactly `['friendly_name', 'icon']` across the full
window, on every leg. **No confidence/score attribute exists on ANY producer.** Therefore:

- `stranger_leg_confidence_floor` **cannot be derived** — no p10-of-recognized /
  p25-of-unknown data exists. The plan's rule "the default comes from the histogram" has no
  input.
- ALL producers fall under the MED-2 `CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS` review —
  which as specced would exempt every camera, i.e. the confidence guard is structurally
  inert on this install. If the cycle revives, the stranger-leg guard design must not rely
  on a confidence floor at all, or Frigate must first be configured to expose sub-label
  scores on this sensor.

## (b) Latency + coverage on real perimeter events

Events = collapsed ON edges (60s dedup across all person legs per camera), 7.69 days:

| Camera | Events | name@t0 | +5s | +10s | +30s | no-name@60s |
|---|---|---|---|---|---|---|
| reolinkstudybporchptz | 27 | 0 | 0 | 0 | 0 | 27 (100%) |
| rear_ptz | 99 | 0 | 0 | 0 | 0 | 99 (100%) |
| utilities_ptz | 28 | 0 | 0 | 0 | 0 | 28 (100%) |
| front_side_ptz | 503 | 0 | 0 | 0 | 0 | 503 (100%) |
| armcrest | 63 | 0 | 0 | 0 | 0 | 63 (100%) |
| hot_tub | 64 | 0 | 0 | 0 | 0 | 64 (100%) |
| pool_equipment | 58 | 0 | 0 | 0 | 0 | 58 (100%) |
| g5_bullet | 85 | 0 | 1 | 1 | 2 | 83 (98%) |
| back_yard | 605 | 0 | 0 | 0 | 0 | 605 (100%) |
| **ROLLUP** | **1,532** | **0 (0.0%)** | 0.1% | 0.1% | 0.1% | **99.9%** |

Nearest-identity deltas where an identity existed at all (n=2): +3.1s, +20.7s — identity
always arrived AFTER the event. **In-first-message annotation (the ONLY v1 shape per rev-2
binding #3) is infeasible: 0% availability at composition time.** Even the removed
annotate-by-edit shape would cover ≤0.1%.

## (c) Enrollment coverage

Real-name recognitions across ALL local producers, 7.69 days:
`{Ezinne: 11, Jaya: 14, Oji: 1}`.

| Person | Recognized ≥1× in window | Count | Effective |
|---|---|---|---|
| Ezinne | yes | 11 | enrolled, low-rate |
| Jaya | yes | 14 | enrolled, low-rate |
| Oji Udezue | yes ("Oji") | 1 | marginal |
| Ziri | **no** | 0 | **effectively unenrolled** |

Nominal coverage 3/4 = **75%** (below the 80% ship gate; in the 60-80% "guard defaults
CLOSED" band). But recognition RATES are so low (≤2/day house-wide) that all four members
would routinely present as unidentified at any single camera — the stranger-leg
false-positive risk applies to everyone, not just Ziri.

## (d) Doorbell-specific unknown cadence

**Doorbell identity finding (plan expected "front-door doorbell"):** the install has TWO
doorbells — `doorbell_lite` (UP Doorbell Lite; `event.doorbell_lite_doorbell`) and
`madrone_g6_entry` (UP G6 Entry; `event.madrone_g6_entry_doorbell`).
**NEITHER doorbell camera is in `perimeter_cameras`** — as configured today, the
perimeter-alert trigger path (and therefore the folded D3 stranger leg) would never fire at
either doorbell. This is a config gap the operator must adjudicate before any revival:
either add the doorbell(s) to `perimeter_cameras` or scope the stranger leg to a separate
camera list.

7.69-day cadence (probed anyway, on the doorbell producers directly):

| Doorbell | Events | /day | named @5s/@10s/@15s/@30s | unknown-in-15s | no-update-in-15s | stranger-fires/day |
|---|---|---|---|---|---|---|
| doorbell_lite | 96 | 12.5 | 0 / 0 / 0 / 0 | 0 | 95 | **12.4** |
| madrone_g6_entry | 45 | 5.9 | 3 / 7 / 8 / 9 | 1 | 35 | **4.7** |

- `doorbell_lite`'s face producer has **never emitted a name** — a stranger leg there would
  fire ~12.4/day, exceeding the plan's ~10/day tightening threshold, essentially all false.
- `madrone_g6_entry` is the only functioning doorbell identity pipeline: 20% of events
  resolve to a household name within 30s (most within 10-15s — the 15s
  `stranger_leg_identity_attempt_timeout_s` candidate is supported by this producer's
  timing, and is the ONLY D0-derivable knob default). Still 4.7 would-fire/day, dominated
  by no-producer-update, not by "producer said unknown".

## Adjudication against the plan's numeric gates

| Gate | Threshold | Measured | Verdict |
|---|---|---|---|
| (b) real name @ t=0 | ≥50% ship / 30-50% degraded / <30% park | **0.0%** (0/1,532) | **PARK** |
| (b) any timing bucket | <30% → park | ≤0.1% at +30s | **PARK** |
| (c) enrollment coverage | ≥80% / 60-80% / <60% | 75% (Ziri 0, Oji 1 event) | degraded band — moot given (b) |
| (a.iii) confidence floor derivable | histogram exists | **no confidence attribute on any producer** | **BLOCKED** |
| (d) stranger cadence | ≲10/day | 12.4/day (doorbell_lite), 4.7/day (g6_entry) | exceeds/near threshold — false-stranger risk unbounded per plan |

**Per the plan's third adjudication branch: park v1 entirely (BOTH legs), publish D0 as-is,
verdict "producer coverage insufficient."**

## Derived knob defaults (recorded for revival; NOT shipping)

| Knob | Default | Citation |
|---|---|---|
| `stranger_leg_confidence_floor` | **UNDERIVABLE** — no confidence attribute exists (a.iii) | (a.iii) table |
| `stranger_leg_enrollment_coverage_gate` | would default CLOSED (75% < 80%) | (c) table |
| `stranger_leg_identity_attempt_timeout_s` | 15s (8/9 named resolutions land ≤15s on the only working producer) | (d) madrone_g6_entry row |
| `known_person_annotation_budget_ms` / `_freshness_s` | moot — 0% t=0 availability | (b) rollup |

## What changes the plan (revival preconditions)

1. **Fix the Frigate face pipeline first** — 6/9 perimeter cameras' face sensors emit only
   boot churn. Whether faces aren't being submitted, sub-labels aren't publishing, or the
   recognition model is off for those cameras is a Frigate-side investigation, not a URA
   cycle.
2. **Enroll Ziri; re-enroll/verify Oji** (1 recognition in 7.69 days).
3. **Confidence exposure:** get Frigate to publish a score attribute on
   `last_recognized_face`, or redesign the stranger guard without a confidence floor.
4. **Doorbell config gap:** add `doorbell_lite` / `madrone_g6_entry` to `perimeter_cameras`
   (or a dedicated doorbell list) — today the stranger leg has no trigger at any doorbell.
5. **Re-run this probe** after (1)-(4); gates re-adjudicate on fresh data. The probe script
   shape is reproducible from this doc's method line.

## Operator sign-off

- Ship-vs-park verdict: **PARK** (auto-adjudicated by the plan's own numeric rule; operator
  countersign requested).
- D3 guard defaults: recorded above as revival placeholders only.
- D0.pre.1 curation: no list changes proposed; first-name-mapping note stands.
- D0.pre.2: default message format binds.
