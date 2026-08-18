# Review B — Cross-coordinator + double-count precedence
## Cycle: EXTERIOR-GUEST-FACE-FASTFOLLOW-1 D1 (egress-face-identity)

**Branch reviewed:** `feature/egress-face-identity-d1` @ `fa5b57c52`
**Base (three-dot merge-base):** `develop`
**Framing:** B — Cross-coordinator ripple + double-count precedence. Owns the load-bearing invariant "an egress-face fuse increments identified_count by exactly 1 through the surviving writer, and never inflates household headcount past reality."
**Verdict:** **DO-NOT-SHIP** — 1 CRIT, 1 HIGH, 2 MED, 1 LOW. B-CRIT-1 is a direct repro of the exact double-count-into-GUEST failure mode this cycle was scoped to prevent.

---

## Independent both-fuse-sites verification (mandated deliverable)

Re-greped `identified_count | recognized_set | known_persons | raw_total_ceiling` across
`camera_census.py` after the diff — writers found:

| # | file:line | function | writer semantics | egress_face_ids unioned? | Normalization applied? |
|---|-----------|----------|------------------|--------------------------|------------------------|
| 1 | `camera_census.py:1878` | `_calculate_census_for_zone` raw | `known_persons = face∪ble∪egress` → `identified_count = len(...)` | **YES** (`:1873–1877`) | `_normalize_name_set` on face + ble; egress already normalized on register (`:2762`). ✓ |
| 2 | `camera_census.py:3510` | `_apply_enhanced_house_census` | `recognized_set = ble∪face_recog∪egress` → `identified_count = len(...)` | **YES** (`:3504–3509`) | `_normalize_name_set` on both sources + egress pre-normalized. ✓ |
| 3 | `camera_census.py:3603` | `_apply_enhanced_property_census` (exterior zone hold/decay) | pass-through `identified_count = raw_result.identified_count` — no recompute | N/A (consumes site 1's output verbatim) | N/A |

**No third writer downstream of `:3510`.** Grep confirms `_apply_enhanced_property_census` at `:3603` only propagates raw_result — no recomputation of identified_count / recognized_set past site 2. Plan-review C-CRIT-1 is *architecturally* resolved: both fuse sites are wired, both apply the normalization, no shadow writer overwrites.

**No additive `identified_count += …` path** anywhere in the integration (grep clean; `bayesian_predictor.py` hits are an unrelated `_known_persons` namespace).

**I4 identity-notion segregation verified.** Diff greps for `location`, `sub_label`, `exterior_track`, `person_coord.data` return zero hits — the fused identity does not leak into per-person location fields or exterior_track_linker sub_labels.

---

## Findings

### B-CRIT-1 — Exit-direction egress registers a phantom identified person for 5 min
**Severity:** CRITICAL
**Bug class:** Double-count precedence / suppression-needs-a-discharge (2026-08-16 census double-count family)
**Files:** `transit_validator.py:1216–1230` × `camera_census.py:1878` / `:3510` / `:3542`

**Repro (legal-config, reachable, no test-only state):**
1. Sole resident "Oji" walks out the front door. BLE goes `not_home` shortly after.
2. `EgressDirectionTracker._resolve_direction` fires with `direction="exit"`. `_resolve_egress_face_identity` returns `"Oji"` from the fresh face sensor (still fresh because the crossing IS the moment the face was seen, and `person.oji` is not yet `not_home`).
3. **`census.register_egress_face("Oji", ts)` is called UNCONDITIONALLY** (`transit_validator.py:1220` — inside `if person_id:`, above the `if direction != "ambiguous"` gate). `_egress_face_ids["oji"] = ts`, TTL = 300 s.
4. Next census tick, `_apply_enhanced_house_census` runs. Person has left: cameras=0, `ble_persons=∅`, `face_recognized=∅`, `egress_face_ids={"oji"}`.
5. `recognized_set = {"oji"}` → `identified_count = 1`; `raw_total_ceiling = max(0, 1) = 1`; `additive_total = 1 + 0 = 1`; **`total_persons = 1`**.
6. **`aggregation.py:5983 ZoneGuestCountSensor._get_guest_count`** — `camera_total = census.last_result.house.total_persons = 1`; `ble_total = 0` (person left, BLE gone). `guest_count = max(0, 1 − 0) = **1 phantom guest**`.

For up to `EGRESS_FACE_UNION_TTL_S = 300 s` after every legitimate exit, the house reports one phantom person in `identified_count` AND one phantom guest. This is the **exact** batch-defect signature the fastfollow was scoped to prevent, only relocated from face-plus-BLE double-count to egress-plus-empty-BLE phantom-count.

The invariant "identified_count matches the number of persons physically inside the house right now" is falsified on every exit. `raw_total_ceiling`'s job is to keep unidentified from exceeding physical evidence; it cannot bound identified_count itself (`max()`, not `min()`), so the phantom rides straight into the total.

**Fix (mandatory, small):**
- Gate the census register on `direction == "entry"` — the fuse only makes semantic sense for a person who just came IN and briefly isn't on interior cameras.
- OR (belt-and-braces) add `census.evict_egress_face(person_id)` on `direction == "exit"` so an exit crossing removes any prior entry-registration for that identity too (covers "walked in 4 min ago, now walked out" within the TTL).

Do NOT rely on the TTL for correctness — 300 s of phantom-guest is enough to trigger a GUEST-mode transition on the batch's guest-math consumers.

**Discriminating acceptance check:** simulate an exit crossing with a fresh face and observe `census.last_result.house.identified_count` at t+30s. Under fix: 0 (or unchanged from pre-exit). Under bug: 1 for 300 s.

---

### B-HIGH-1 — Ambiguous-direction crossings pollute the census register
**Severity:** HIGH
**Bug class:** suppression-needs-a-discharge (ambiguous should not commit to household state)
**File:** `transit_validator.py:1220` vs `:1233`

The DB write correctly gates on `direction != "ambiguous"` at `:1233`, but `register_egress_face` at `:1220` fires for `direction == "ambiguous"` too. Ambiguous means we couldn't decide entry vs exit at 0.3–0.4 confidence — precisely the case where injecting an identity into the household census union for 5 min has the worst signal-to-noise ratio. It also inherits B-CRIT-1's phantom-count failure mode for ambiguous crossings of a person who's actually leaving.

**Fix:** mirror the DB-write gate — `if person_id and direction != "ambiguous":`. This also lines up register semantics with the DB row of record (a person we wouldn't stamp in the DB should not be stamped into the live census either).

**Discriminating check:** feed an ambiguous crossing with a fresh face → `_egress_face_ids` empty; feed an unambiguous entry with a fresh face → `_egress_face_ids` populated.

---

### B-MED-1 — First-name-slug normalization collision surface (new risk)
**Severity:** MEDIUM
**Bug class:** identifier-namespace collision
**Files:** `camera_census.py:2735–2765 _normalize_person_name`; call sites `:1875–1876`, `:3506–3507`.

`_normalize_person_name` reduces every identifier to `lower().split('_', 1)[0]`. This fixes an obvious pre-existing double-count (`"Oji" ∪ "oji_udezue"` used to be size-2), which is real value — but it introduces a NEW collision surface: two residents whose Frigate face-library first names collide (`"Oji Udezue"` and a hypothetical `"Oji Smith"`) reduce to the same slug and count as ONE, understating `identified_count`. This can turn a real second resident into a phantom guest (`camera_total − identified_count` inflated).

Not exploitable in the current single-Oji household, but the D1 build persists it as a load-bearing helper for D2/D3. Because the plan bills this normalizer as the "one namespace to rule them all" (I5), the collision policy needs to be explicit in the plan, not an emergent property of `split('_', 1)[0]`.

**Fix (defer to D2 planning; flag in review):** either (a) use the URA person slug (`oji_udezue`) as the canonical namespace and normalize Frigate names *up* into it via a first-name→slug lookup keyed on tracked_persons, or (b) explicitly document "URA does not support two tracked persons with the same first name" as a supported-configuration constraint and add a startup log warning if the tracked_persons list contains a collision.

**Discriminating check:** add a tracked-persons config with two entries `oji_udezue` and `oji_smith`; face-sensor "Oji" appears on one camera; identified_count = 1 under bug, 2 (or an explicit unsupported-config error) under fix (a).

---

### B-MED-2 — Namespace divergence between DB `person_id` and census union member
**Severity:** MEDIUM (data-integrity, not correctness)
**Bug class:** payload-shape drift across writers of the "same" identifier
**Files:** `transit_validator.py:1140` (returns raw `val` from face sensor, e.g. `"Oji"`) → DB row `person_id="Oji"`; `camera_census._normalize_person_name` (`:2758`) stores `"oji"` in the union.

Same crossing produces `person_id="Oji"` in the DB and `"oji"` in the live census set. Downstream consumer at `sensor.py:2903` (`_last_occupant`) handles it (`.replace('_', ' ').title()` → `"Oji"`), but the two representations of the "same" identifier will confuse future joins (e.g. any planned analytics that JOIN `person_entry_exit_events.person_id` against the URA person slug in `person_coordinator.data` — it will miss all Frigate-only entries).

**Fix:** normalize once at the source in `_resolve_egress_face_identity` (return `val.strip().lower().split('_',1)[0]`) so DB and census carry the same namespace. Update the `_last_occupant` consumer if the resulting titlecasing regresses (single-token "oji".title() → "Oji", still correct). D1 could ship this in the same commit — one-line change.

---

### B-LOW-1 — `raw_total_ceiling` no longer bounds `identified_count`
**Severity:** LOW (documentation / invariant statement)
**File:** `camera_census.py:3542`

Pre-diff, `identified_count ≤ camera_total_pre_cancel` was empirically true because both derived from camera-facing signals. Post-diff, egress-face can push `identified_count` past `camera_total_pre_cancel` (that IS its purpose — bridging the transit gap). `raw_total_ceiling = max(camera_total_pre_cancel, identified_count)` now silently absorbs this by RAISING the ceiling to accommodate the fused identity. The `clamped_total` clamp is a no-op in that regime. Fine for entry (intentional). Combined with B-CRIT-1's exit-phantom, this is the mechanism that lets the phantom ride into `total_persons`.

**Fix (paired with B-CRIT-1):** once exit-direction is gated out, add a comment at `:3542` making the new post-fuse invariant explicit: "identified_count MAY exceed camera_total_pre_cancel by up to |egress_face_ids|; the ceiling is the union of physical evidence and identity evidence, both trusted."

---

## Cross-coordinator ripple audit (no findings)

- **Guest-math consumer** (`aggregation.py:5983 _get_guest_count`): reads `house.total_persons` and `person_coordinator.data`. B-CRIT-1 propagates here — every finding lands on this consumer.
- **Room-level `_get_identified_persons_in_room`** (sensor.py per-room): grep clean — no read of `census._egress_face_ids` or `recognized_set` outside camera_census. Room-level identity remains room-scoped (I4). ✓
- **v5.79.0 guest-room lead precedence:** unchanged; the guest sensor reads census output post-fuse, and B-CRIT-1's phantom guest will race against any lead — expected order-of-precedence effects fall out from fixing B-CRIT-1.
- **person_id downstream (`sensor.py:4184/4262/4323/4371` × 4 listeners + `database.py:3709`):** all listeners fall back to `"unidentified"` when `person_id is None` — accepting a real name is a no-op wiring change; no double-emit risk (event fires once per crossing regardless).

---

## Summary table

| ID | Severity | Class | Fix scope | Blocks ship? |
|----|----------|-------|-----------|--------------|
| B-CRIT-1 | CRITICAL | Double-count precedence / discharge | one-line gate in `transit_validator._resolve_direction` | YES |
| B-HIGH-1 | HIGH | Suppression discharge / ambiguity | one-line gate (same site as CRIT-1) | YES |
| B-MED-1 | MEDIUM | Namespace collision | plan-level; document constraint + startup warn | No (defer, flag) |
| B-MED-2 | MEDIUM | Payload-shape drift | one-line normalize in `_resolve_egress_face_identity` | No (fix in-cycle) |
| B-LOW-1 | LOW | Invariant documentation | comment at `:3542` | No (fix in-cycle) |

**Verdict: DO-NOT-SHIP** pending B-CRIT-1 and B-HIGH-1. Both are the same one-line gate (`direction == "entry"`) at `transit_validator.py:1220`. B-MED-2 and B-LOW-1 are worth folding into the same fix-up round; B-MED-1 is a D2 planning input.

---

## Bug-class contribution to QUALITY_CONTEXT.md

Recommend appending a note to Bug Class "Double-count precedence / census attribution" (or open a new class if none exists): *"Any writer that INJECTS identity into a census set on an event must be direction/discharge-aware. An unconditional register on a bidirectional event (entry+exit) produces phantom household state for the TTL after every exit."*
