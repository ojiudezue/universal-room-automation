# AUDIT — Is BLE evidence weighed at the HOUSE level? (AWAY-BLOCK-1 rec 5 follow-up)

**Status:** READ-ONLY analysis of record, 2026-08-13. No fixes applied.
**Question (operator):** "Are we missing weighing the BLE evidence at the house
level? Check everywhere to see if we are, and if we do make a change, that it
doesn't unbalance our different purposes."
**Evidence:** source trace on develop @ a7ff3574 +
`docs/planning/AUDIT_away_transition_2026_08_13.md` (incident of record).
All paths relative to `custom_components/universal_room_automation/`.

## Verdict in one paragraph

BLE evidence is weighed at the house level **asymmetrically**: BLE *presence*
reaches the house tier through several channels (zone Tier-3 occupancy, census
BLE-cancel, β-denominator admission of LOST+away trackers), but sustained BLE
*absence* — "no tracked phone has had an in-house Bermuda fix for hours" — is
consumed **nowhere** as affirmative vacancy evidence. The gap is **confirmed,
with a critical nuance**: in the 2026-08-13 incident the aggregate
"all-phones-BLE-absent" was true from ~16:43Z, yet from 19:29Z onward path β's
denominator was ALREADY satisfied (LOST+away admission *is* BLE-absence
evidence) and the sole blocker was the phantom mmWave zone via
`indoor_blocked`. A house-level BLE-vacancy signal therefore adds value only in
two shapes: (1) as an extra corroborator for discounting phantom-classed zones
(composing with rec 3), which is safe; or (2) as an override of stale-`home`
phone trackers (the pre-19:29 window), which is genuinely unbalancing
(false-away on dead-phone-at-home; guest-blind). Recommend shape (1) only.

## 1. Map — where BLE evidence is consumed today

| Surface | Location | What BLE does there | Reaches HOUSE away decision? |
|---|---|---|---|
| **tracking_status** | `person_coordinator.py:167-169` (const.py:167-169), update loop `:126-460` | ACTIVE = recent Bermuda room fix; STALE = decay ≤300s after last fix (`:308-334`); **LOST = no recent Bermuda data at all** — location falls back to the HA `person` entity state (`:336-392`). So LOST *already encodes* "phone not BLE-visible in-house". | Indirectly — via the α/β denominators below. |
| **PersonLocationSensor** | `person_sensors.py` (reads `person_coordinator.data`) | Exposes location/tracking_status/confidence per person. | No — diagnostic surface only. |
| **Zone Tier-3 BLE occupancy** | `presence.py:4469-4491` `_update_ble_zone_presence` → `update_ble_presence` `:839-848`; consumed in `_derived_mode` `:680-708` | Any person located in a zone's room ⇒ zone OCCUPIED, highest-priority tier. **Presence-only: BLE absence never flips a zone AWAY** — the zone falls through to Tier 1/2 sensors (this is how the phantom mmWave zone stayed "occupied" with zero BLE). | Yes, but only in the OCCUPIED direction (feeds `any_zone_occupied` / `any_indoor_zone_occupied`). |
| **BLE Tier-2 weighting** | `presence.py:5330-5393`, `BLE_TIER_2_WEIGHT=0.6` (const.py:435) | v4.7.16 D3 diagnostic weighting of BLE room fixes. | No — diagnostic. |
| **Census BLE-cancel** | `camera_census.py:2236-2320` `_ble_home_by_area`; `CONF_CENSUS_BLE_CANCEL_ENABLED` (const.py:2586) | Per-area cancellation of camera "unidentified" counts by residents whom BLE places (ACTIVE only) in that area — prevents un-face-matched residents from arming the guest gate. **STALE/LOST explicitly excluded** (Fix 5a, Bug Class #7). Monotone-reducing (invariant I3): BLE can only *cancel* unidentified, never create it. | Indirectly — lowers `unidentified_count`, which is a conjunct in α/β. Again presence-only. |
| **Zone confidence / direct-BLE rooms** | `is_direct_ble_room` `person_coordinator.py:1240-1267`; `_check_zone_occupancy_confidence` relocated per `hvac.py:2833` (v4.7.15 D4) | BLE coverage-density classification for HVAC zone-vacancy confidence. | No — HVAC tier. |
| **Fan-interference BLE corroboration ladder** | `presence.py:544-558` (`_fan_interference_hold_until`, set by `_compute_fan_interference_rooms`) | Room-tier: mmWave in a fan-suspect room checked against BLE corroboration. Truth-preserving — hold can only EXTEND occupancy. | No — room tier; and publishes `fan_interference_rooms` which `infer()` does NOT consume (incident audit §c, last row). |
| **BLE pre-arrival** | `person_coordinator.py:248-283` (`SIGNAL_PERSON_ARRIVING`, source "ble") | BLE reappearance after ≥15 min away fires arrival signal. | Arrival direction only. |
| **Path α (v4.7.14)** | `presence.py:1047-1057`; denominator `:5110-5146` | Requires `tracking_status == ACTIVE` (`_tracking_active`) — i.e. requires a *recent BLE fix*. LOST/STALE excluded ⇒ "away⇒LOST empties the denominator" (v5.16.0 memory). | Yes — but BLE absence *disables* α rather than informing it. |
| **Path β (v5.7.0 WS-A)** | predicate `_tracking_active_or_lost_away` `presence.py:169-192`; denominator `:5147-5181`; veto `:1059-1160` | Admits **LOST/STALE + location=="away"** — this IS consumption of BLE-absence evidence (phone entity says away AND Bermuda can't see it in-house). **LOST/STALE + location=="home" is deliberately inert** (WS-A3, `person_coordinator.py:353-366` clears the LOST-since stamp on home). Guarded by `indoor_blocked` (`:1091-1094`), census==0, unid==0, grace, sleep exemption, `sustained_external_empty` immediate-engage limb (`:1122-1136`). | **Yes — the only away-direction consumer of BLE-absence, and only when the phone entity corroborates "away".** |
| **Guest gate / guest Path B** | `presence.py:4550-4683` (guest-room sustained occupancy); guest-arming via `unidentified_count` | BLE touches it only through census BLE-cancel (above). Guest phones are untracked ⇒ BLE-invisible by definition. | Guest state blocks nothing in α/β directly; `unidentified_count==0` is the guest-protection conjunct. |

**Summary of the asymmetry:** every away-decision-relevant BLE channel treats
BLE as a *presence prover* or a *trust gate*. The single place BLE absence has
away-direction force is the β predicate, and there it is subordinate to the
phone entity saying "away". No surface computes or consumes an aggregate
"no tracked phone BLE-visible in-house for T".

## 2. The gap — confirmed, with a load-bearing nuance

**Confirmed:** "no phone BLE-visible in-house for 2.7 h" (all four
`tracking_status ∈ {LOST, STALE}` from ~16:43Z) was true and consumed nowhere
as vacancy evidence. Specifically:

- 16:43–19:28Z: Jaya/Ziri were STALE/LOST-**home** (phone entities stale-home).
  WS-A3 makes LOST-home inert in BOTH denominators — by design
  (`presence.py:5150-5156` comment: "LOST+home entries are NOT counted as
  away"). Their BLE absence carried zero weight; census stayed 2.
- 19:29–20:46Z: all four became LOST+**away** ⇒ β's denominator WAS satisfied
  (`all_trusted_or_lost_away_persons_away=True` is precisely
  "every tracked phone is BLE-absent-in-house AND entity-away"). β was blocked
  **only** by `indoor_blocked` from the fan-pinned mmWave zone
  (incident audit §b.2).

**The nuance:** a new house-level BLE-vacancy aggregate would have been
*redundant* with β's denominator for the 82-minute window (both true; both
blocked by the same phantom zone). It would only have fired *earlier* (the
2.7 h stale-home window) if allowed to **override** the phone entities'
stale-`home` — and even then it would STILL have been vetoed by the phantom
zone unless it also overrode `indoor_blocked`. So the missing ingredient in
the incident is not BLE weighing per se; it is (a) the phantom-zone discount
(rec 3) and (b) tracker liveness (rec 5). BLE-vacancy's genuine marginal
contribution is as a **corroborator** for (a).

**Least-ripple plug-in points, ranked:**
1. **Rec-3 composition (recommended):** in the caller that computes
   `any_indoor_zone_occupied` / `sustained_external_empty`
   (`presence.py:~4854-4877` + `_run_inference`), a zone whose occupancy is
   mmwave-sole AND fan-interference-flagged may be discounted from
   `indoor_blocked` **only when** house-level BLE-vacancy corroborates
   (all tracked phones LOST/STALE for ≥T). BLE-vacancy tightens rec 3 —
   it can only make the discount HARDER to apply, never fire away alone.
2. **`sustained_external_empty` conjunct (acceptable):** add "AND
   all-phones-BLE-absent" to the immediate-engage limb's external-empty
   definition — again purely restrictive.
3. **New independent `all_phones_ble_absent` away conjunct/trigger
   (rejected):** see §3 — fights guests, LOST-home, and I1.

## 3. Balance audit — purposes BLE serves vs a house-level BLE-vacancy weight

| Purpose / constraint | Interaction with a BLE-vacancy signal | Discount-shape (rec-3 composition) | Independent-trigger shape |
|---|---|---|---|
| **(a) LOST-while-home ambiguity** — dead/charging phone upstairs or coverage gap, person home. WS-A3 exists exactly for this (`person_coordinator.py:353`: LOST-home clears the grace stamp). Not quantified from recorder in this pass (probe below); qualitative frequency is high — overnight charging + Bermuda coverage gaps make LOST/STALE-home a routine state, per the Jaya/Ziri 2.7 h stale-home in this very incident *while they may genuinely have been home until ~19:28Z* (audit Q6 leaves this unresolved). | **False-away risk is the killer for any override shape.** | Respects it: the person's actual presence still shows on PIR/mmWave/camera ⇒ zone occupied by non-mmwave-sole provenance ⇒ no discount ⇒ no AWAY. Only a person sitting motionless in a fan-blown mmwave-only room with a dead phone loses — the same residual rec 3 already accepts. | Fights it head-on: forces AWAY over a stale-home tracker whose owner may be home. Violates I1. |
| **(b) Guests** — untracked phones are BLE-invisible by definition; guest-occupied house must not go away. | β already requires `unidentified_count==0 AND census_count==0`; guest Path B (`presence.py:4550+`) holds house in GUEST independent of α/β. | Respects it: the discount only affects β's indoor guard; the census/unid conjuncts and guest state remain untouched. A guest tripping PIR/camera keeps `unidentified_count>0` or a non-mmwave zone occupied. Residual: a guest alone in a no-PIR, camera-blind, fan-interference room — identical to rec 3's residual, not new. | Fights it: "no BLE ⇒ empty" is definitionally false for guests. |
| **(c) Veto denominator (v5.16.0 / v5.7.0 β)** — LOST admission semantics carefully tuned (LOST+away in, LOST+home out, grace, sleep exemption). | A BLE-vacancy aggregate is derivable FROM the same `tracking_status` data — no new writer to `person_coordinator`. | Respects it: read-only aggregate over existing statuses; denominators byte-unchanged. | Fights it: a second, competing away path duplicates β with weaker guards — exactly the shared-primitive ripple Tier 2-DB/3 exists for. |
| **(d) BLE flakiness** (Jaya-bedroom flap memory; Bermuda noise) | Bermuda noise manifests as spurious *fixes* (flapping ACTIVE), not spurious absence. | Respects it — fail-safe direction: a noise-induced spurious fix makes someone ACTIVE ⇒ BLE-vacancy goes false ⇒ discount denied ⇒ house stays home. Noise can only suppress the new behavior. Require sustained T (≥ the 300 s STALE decay, realistically 15-30 min knob) to ride through fix gaps. | Same fail-safe direction, but the stakes of the false-negative side are higher. |
| **(e) BLE device budget** (finite HAOS BLE socket capacity; no new scanners) | Signal is computed from existing Bermuda data. | Respects it: zero new BLE hardware/integrations. | Same. |

## 4. Recommendation

**Gap: CONFIRMED — no house-level consumer of sustained BLE absence exists.
Safe shape: YES, but only as a corroborating DISCOUNT, not a trigger.**

Adopt the rec-3 composition: define `house_ble_vacancy` = every tracked,
phone-trustworthy person has `tracking_status ∈ {STALE, LOST}` continuously
for ≥ `CONF_BLE_VACANCY_SUSTAIN_MIN` (knob rung 2/3; default ~20 min;
0 = disabled/kill-switch), computed read-only from `person_coordinator.data`
in the same caller that builds the β kwargs. Use it solely as an **additional
required conjunct** for rec 3's phantom-zone discount (mmwave-sole +
fan-interference-flagged zones excluded from `indoor_blocked` only when BLE
also sees nobody). Optionally also AND it into `sustained_external_empty`.
Expose it as a sensor attribute (`ble_vacancy`, `ble_vacancy_since`) for
diagnostics regardless.

This shape is strictly restrictive relative to rec 3 alone — every failure
mode of BLE (noise, dead phone, guest invisibility) pushes it toward "not
vacant", i.e. toward holding HOME — so it cannot introduce a new false-away
path, and it addresses the operator's balance concern by construction. It
would have fired in the incident at ~19:29Z + T (composing with rec 3), ending
the hold ~60+ min early even with no PIR installed.

**Do NOT build** an independent `all_phones_ble_absent ⇒ away` trigger or a
LOST-home override: it re-litigates WS-A3, is guest-blind, and its only unique
coverage (the stale-home 2.7 h window) is better served by rec 5 tracker-
liveness hygiene (device/app work) plus rec 1 (a PIR corroborator, which
releases the phantom via the already-shipped D2 demotion).

**Measure-before-build gate (pre-plan probe):** before any build, run a
one-shot recorder probe quantifying, over ≥14 days: (i) fraction of time with
all trackers STALE/LOST while ≥1 person is verifiably home (false-away
exposure for any override shape — expected high, confirming the rejection);
(ii) fraction of genuinely-empty windows where `house_ble_vacancy` (20-min
sustain) is true (coverage of the discount conjunct — must be near 1.0 or the
conjunct starves rec 3).

**Tier if built:** rides rec 3's cycle (Tier 2-DB minimum — trust-hierarchy
ripple on the shared β primitive); the falsifiable invariant is unchanged from
rec 3's ("a zone occupied by any non-mmwave-sole or non-fan-flagged evidence,
or any ACTIVE BLE fix, can never be discounted from `indoor_blocked`").
