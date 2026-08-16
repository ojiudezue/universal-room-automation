# PLANNING — GAP-A-CENSUS-HOLE-1: forgotten-phone census leak into path-α

**Rev:** 1 (2026-08-16). Tier 2-DB. Thread: presence.
**Approval:** implied — operator: *"Gap A error is big and we have not offered a solution."*
**Scope constraint (operator):** ONE change — the path-α veto predicate's `census_count == 0` clause → camera-provable-only evidence. No new knobs unless the freshness analysis proves one is required.

---

## Institutional context verified (greps, file:line)

- **Path-α site (target):** `custom_components/universal_room_automation/domain_coordinators/presence.py:1047-1057`. Clause `and census_count == 0` present. Intent-of-record in comment `presence.py:1039-1042`: *"If Frigate face-IDs a resident (census_count >= 1), SOMEONE is provably in front of a camera — phone trustworthiness is irrelevant."*
- **`census_count` provenance in PresenceCoordinator:** `presence.py:4194-4207` — `self._census_count = int(census_data.get("interior_count", 0))`. Payload key = `interior_count` = `house_result.total_persons`.
- **`total_persons` computation:** `camera_census.py:3079-3103` (`_apply_enhanced_house_census`) — `recognized_set = set(ble_persons) | set(face_recognized)`; `identified_count = len(recognized_set)`; `total_persons = identified_count + held_unidentified`. **Confirms:** BLE-home membership alone bumps `census_count` with zero camera evidence.
- **`face_recognized_persons: list[str]`:** `camera_census.py:158` (`CensusZoneResult` field), populated at `camera_census.py:3116`. **Reachable at the census dispatch site (`camera_census.py:1166-1179`) but NOT currently in the `SIGNAL_CENSUS_UPDATED` payload** (payload today: `interior_count / identified_count / unidentified_count / property_count / total_on_property / confidence / source_agreement`).
- **Face freshness gates in `_get_face_recognized_person_names` (`camera_census.py:2982-3060`):**
  - Age gate `age <= CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (constant imported at :3031; build must cite its file:line + value in the README).
  - **Tracker cross-check** at `:3034-3055`: drops face-recognized person if `person.<slug>.state == "not_home"`. This is the load-bearing gate that defeats the well-documented `sensor.frigate_*_last_camera` `unavailable⇄camera` re-stamping flap.
- **Consumer sweep of `census_count` in `presence.py`:** all sites listed with verdicts in §"Consumer enumeration."
- **Prior docs consulted:** `docs/planning/AUDIT_away_transition_2026_08_13.md` (root incident; names this census hole as latent), `docs/planning/PLANNING_path_alpha_lost_dissolution.md` rev-3.5.1 (adjacent denominator work — see §"Merge order").

**No new CONF_\*, sensor, entity, options field, or Number/Select/Switch.** One additive key on an existing dispatched payload. One int field on PresenceCoordinator. One int kwarg on `infer()` (defaults to 0 → I3 byte-identity preserved). One clause change in `presence.py`.

---

## The bug (falsifiable)

Current predicate `presence.py:1047-1057`:

```python
if all_tracked_persons_away and unidentified_count == 0 and census_count == 0:
    ...return HouseState.AWAY
```

`census_count == 0` does NOT mean "no camera evidence" — it means `|ble_home ∪ face_recognized| + held_unidentified == 0`. **A resident's forgotten phone at home lands them in `ble_home` → `census_count >= 1` → veto blocked**, even when H2 correctly excluded that person from `all_tracked_persons_away`. H2 fixed the denominator half; the census half stayed open. Independent second path into the AWAY-BLOCK-1 cul-de-sac.

**Legal-config repro.** Ezinne's phone on charger at home; Bermuda BLE resolves → `ble_persons = {"ezinne"}` → `identified_count = 1` → `census_count = 1`. All four trackers `not_home` on GPS; H2 excludes Ezinne → `all_tracked_persons_away = True`. `unidentified_count = 0`, no face-recognition, no zone occupied. Path α SHOULD fire (H1's stated intent). Path α does NOT fire (census clause).

## Falsifiable invariant

> **I-GA:** Path α blocks the AWAY veto ONLY when there is camera-provable indoor human evidence — a fresh face-recognition OR an unidentified camera person. A BLE-only "identified" home count, without corresponding camera evidence, does NOT block path α.

Break → plan falsified. Both directions drilled in acceptance criteria.

---

## Leading candidate: VERDICT — RECOMMEND, no new knob

Replace `census_count == 0` with `face_recognized_count == 0`. `CensusZoneResult.face_recognized_persons` already exists and is reachable at the dispatch site; add its length to `SIGNAL_CENSUS_UPDATED` and store on the coordinator. Restores H1's documented intent ("provably in front of a camera") byte-for-byte:
- Real face on-screen → still blocks (correct).
- Unidentified body → still blocks (correct, unchanged limb).
- BLE-only home phantom-blocker → removed (the exact class H2 handles on the denominator side).

### Freshness analysis (mandatory §1) — verdict: no new knob

Can `face_recognized_persons` go stale in a way that blocks the veto indefinitely?

**No.** Two independent gates bound it:
1. **Age gate** `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` in `_get_face_recognized_person_names` (`camera_census.py:3031-3033`) — a face falls out at window elapse.
2. **Tracker cross-check** (`camera_census.py:3034-3055`) — the person's `person.<slug>` tracker must not be `not_home`. This is the load-bearing gate that defeats the `sensor.frigate_*_last_camera` re-stamp flap the code explicitly documents at :3034-3041. Without this cross-check, gate 1 would be defeatable; WITH it, a departed person's face drops within one tracker update.

The bound is already sane. Adding a new operator-tunable window would be a knob-ladder violation (safety bound → rung 1 only) with no marginal benefit and clear ingredient risk (a live-tunable on a shared primitive). **No new knob.**

The candidate does, however, become newly *dependent* on the cross-check. D-tests include a per-site mutation that neuters the cross-check and asserts a NAMED test fails, so this coupling is discovered at review time, not incident time.

### Consumer enumeration on `census_count` (mandatory §2 — RESACC-1 lesson)

Every `census_count` reader in `presence.py` (other files use it for logging/energy/tests only):

| Site | Semantics | Changed by this cycle? |
|---|---|---|
| `:1026-1031` — nobody-home branch `census_count == 0 AND !any_zone_occupied → AWAY` | Total-zero backstop | **No** — byte-identical. |
| `:1047-1057` — **path α (H1), THE fixed site** | Trust chokepoint | Yes — this cycle. |
| `:1123-1130` — path β outer guard, same `census_count == 0` clause | Same phantom-blocker class as α | **Out of scope this cycle (see non-goals).** Follow-up card if AWAY-BLOCK-1 evidence recurs on the β side after this ships. |
| `:1167` — `has_people = census_count > 0 or any_zone_occupied` (sleep/wake) | Wants ANY signal incl. BLE | **No** — a phone at home is legitimate sleep evidence. |
| `:1818-1821` — `TransientSignal("census_count", ...)` H1 ledger reader | Persists the value | **No** — behavioral clause moves; the transient signal continues to carry the raw count for diagnostics. |
| `:4855-4874` — `has_people` mirror | Same as :1167 | **No.** |
| `:4962-4973` — boot-settle `_census_count >= BOOT_SETTLE_MIN_INPUTS` | Boot-transient suppression | **No.** |
| `:5631, :5719, :5750-5771` — force-AWAY debug/log | Diagnostics | **No.** |
| `:5983, :6046-6098, :6228-6250` — anomaly bookkeeping (persistence-suppressed) | Analytics | **No.** |
| `:6747, :7111` — sensor attribute exposure | Diagnostics | **No.** |

No other trust-decision consumer diverges. Sensor's `total_persons` unchanged. DB `census_log` write shape unchanged.

### Merge order vs feature/path-alpha (mandatory §3)

**PATH-ALPHA-DENOM-1** (rev-3.5.1) changes the DENOMINATOR (`all_tracked_persons_away` classifier + H2/O1 overlay wiring at 5 consumer sites). It does NOT touch the `census_count == 0` limb. This cycle changes ONLY the camera-evidence limb.

Textual overlap is bounded to the same function (`StateInferenceEngine.infer`) and signal handler (`_handle_census_update`), but the two edits are in disjoint hunks (denominator plumbing vs. one clause + one payload key + one kwarg).

**Recommendation: PATH-ALPHA-DENOM-1 merges first, this cycle rebases onto post-PATH-ALPHA `develop`.** PATH-ALPHA is larger, farther along, and its H2/O1 overlay is what this cycle's invariant relies on (`all_tracked_persons_away` correctly excluding phone-left-behind persons). Rebase is expected conflict-free at the α clause; if a real conflict surfaces, do not resolve silently — re-review the affected hunks. **Do not interleave the builds.**

### Alternatives considered (mandatory §4)

- **Subtract H2-excluded persons' BLE contribution from `census_count` at the veto site.** Rejected — Bug Class #53 (computed-but-not-consumed) shape: correction lives at ONE reader while sensor + other consumers see the uncorrected value.
- **Change `identified_count` in `camera_census.py` to face-only.** Rejected — ripples through six months of downstream readers (sensor, DB, property aggregation, boot-settle, guest-mode confidence).
- **Do nothing; rely on PATH-ALPHA + H2.** Rejected — the census half is an independent second path into the same cul-de-sac; AUDIT_away_transition_2026_08_13.md flags it as a distinct latent leak.

---

## D1 — Predicate + payload (ONE deliverable)

**Changes:**
- `camera_census.py:1166-1179` — add `"face_recognized_count": len(house_result.face_recognized_persons)` to the `SIGNAL_CENSUS_UPDATED` payload.
- `presence.py:_handle_census_update` (:4194-4230) — read `face_recognized_count` (default 0); store on new `self._face_recognized_count: int` initialized to 0.
- `presence.py:StateInferenceEngine.infer` (:961) — add kwarg `face_recognized_count: int = 0` (default preserves I3 byte-identity for pre-existing callers).
- `presence.py:_run_inference` (:5719) — pass `face_recognized_count=self._face_recognized_count`.
- `presence.py:1047-1057` — replace `census_count == 0` with `face_recognized_count == 0`. Keep the other two clauses unchanged. Update the H1 intent comment (:1039-1042) to describe the new predicate.

**No other file touched.** Sensor attribute for `face_recognized_count` on the existing house-census sensor is a diagnostic mirror of the payload key; add IF trivial (one attribute pass-through); skip otherwise — not load-bearing.

### Acceptance Criteria — both directions drilled

- **Verify (forgotten-phone-at-home + all away + no camera → house CAN go away):** fixture `_ble_persons = {"ezinne"}` (⇒ `census_count = 1`), `phone_left_behind_ON = True` for Ezinne, other trackers `not_home`, `unidentified_count = 0`, `face_recognized_count = 0`, no zone occupied. `infer()` returns `HouseState.AWAY`; `_veto_path == "active"`. Pre-cycle predicate returns `None`; reddens post-revert.
- **Verify (real face on-screen → veto still blocked):** same fixture but `face_recognized_count = 1`. `infer()` does NOT return AWAY.
- **Verify (unidentified body → veto still blocked):** `unidentified_count = 1`, `face_recognized_count = 0`, all tracked away. `infer()` does NOT return AWAY (unchanged limb; asserts I3 on this branch).
- **Verify (nobody-home branch preserved, I3):** `census_count == 0 AND !any_zone_occupied` still returns AWAY via `presence.py:1026-1031` — this cycle does not touch it.
- **Verify (payload additive):** subscribers that do not read `face_recognized_count` observe zero behavioral change.
- **Verify (default backfill):** `_handle_census_update` invoked with a payload missing the new key stores `_face_recognized_count = 0`; `infer()` call with omitted kwarg preserves the current behavior on the OTHER two clauses (byte-identity on the α check when face-count defaults to 0).
- **Verify (cross-check load-bearing — Tier-3 mutation-anchor):** neuter the `person_state.state == "not_home"` short-circuit in `_get_face_recognized_person_names` and confirm a named test `test_face_cross_check_is_load_bearing_for_veto` FAILS.
- **Tests (named):** `test_gap_a_forgotten_phone_alpha_fires`, `test_gap_a_real_face_still_blocks_alpha`, `test_gap_a_unidentified_still_blocks`, `test_gap_a_payload_additive`, `test_gap_a_signal_backfill_default_zero`, `test_face_cross_check_is_load_bearing_for_veto`.
- **Live (post-restart):** contrived forgotten-phone scenario permits AWAY within one inference tick of the payload arriving; observed values (entity_id, attribute, timestamp) written back to the README validation table per policy.

---

## Non-goals (explicit)

- No change to path β (`presence.py:1123-1130`). β's `census_count == 0` clause is the same phantom-blocker class — separate follow-up card if evidence recurs after this ships.
- No change to `total_persons` / `interior_count` / `identified_count` semantics anywhere.
- No new CONF_\*, options-flow field, Number/Select/Switch entity, or knob (freshness bound analysis: existing gates are sane).
- No refactor of `camera_census`, `_apply_hold_decay`, or the census sensor.
- Does not touch the phantom-zone / fan-loop side of AWAY-BLOCK-1 (FAN-LAYER / STUCK-SENSOR-1 territory).

---

## Tier 2-DB review framings

- **A — data integrity + shape preservation.** No other trust-decision reader of `census_count` diverges. Payload additive; missing key → 0. Sensor + DB shapes unchanged.
- **B — cross-coordinator + no-flap.** Real face still blocks α; unidentified still blocks α; nobody-home branch unchanged; sleep-side `has_people` unchanged; H2's exclusion at its 5 consumer sites is not shadowed or duplicated by this change.
- **C — test authority via per-site mutation.** Neuter (i) the new `face_recognized_count == 0` clause, (ii) the payload key extraction in `_handle_census_update`, (iii) the tracker cross-check in `_get_face_recognized_person_names` — each reddens a distinct named test.

**Live D:** validator confirms AWAY transition under contrived forgotten-phone scenario; README write-back per policy.

**Plan review (one, pre-build, per Tier-2 protocol):** adversarial re-grep of `census_count` readers; sanity-check the freshness-no-knob decision; confirm the merge-order recommendation still holds against the current `feature/path-alpha` HEAD.

### Freshness — corrections from plan review (efec78928)

- **Window value (LOW-1, was undetermined at authoring):** `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS = 1800` (30 min) at `const.py:2609`.
- **Honest bound (MED-1):** the two gates are NOT equally strong. The person-tracker
  cross-check (`camera_census.py:3034-3055`) is documented **fail-OPEN** when
  `person.<slug>` is missing / `unknown` / `unavailable` (`:3039-3041`). In that mode the
  ONLY bound on a stale face blocking the veto is the 30-minute age gate. That is a
  defensible upper bound (a face recognized ≥30 min ago cannot block), and it is the
  reason no new knob is added — but the plan does not claim belt-and-braces where only
  one belt holds. Build must not "fix" the fail-open behavior in this cycle (out of scope).
- **Circularity (plan-review Q3): CLEAN.** The cross-check reads `person.<slug>.state`, an
  HA-native entity fed by device_trackers upstream of URA; **URA writes no `person.*`
  entity**, so the PATH-ALPHA matrix cannot feed back into face evidence. **Fence:** if any
  future cycle ever makes URA write `person.*`, this composition must be re-audited.
- **β follow-up (LOW-2) — residual pattern named, NOT built here:** forgotten-phone +
  ≥1 genuinely-LOST person + camera empty (α fails on the denominator, β blocked on its
  own census clause at `:1123-1130`). Revisit only if that pattern is observed post-ship.
