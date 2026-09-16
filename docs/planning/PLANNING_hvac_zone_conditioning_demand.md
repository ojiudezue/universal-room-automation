# PLANNING — HVAC Zone Conditioning Demand (kind-aware, per-room hold, OR aggregation)

**Card:** `HVAC-ZONE-CONDITIONING-DEMAND-1` (step 4 of `HVAC-SUPPLE-SEQUENCE-1`)
**Tier:** 2-DB (regression-prone, cross-coordinator ripple — presence ↔ HVAC ↔ compliance)
**Status:** pre-build. Stage 0 confirmed (42 corridor : 0 dwelling). Operator checkpoint cleared.
**Companions (read first):**
- `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`
- `docs/planning/AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md`

This plan graduates the proposal to a buildable spec. No versioning — unshipped.

---

## 0. Falsifiable invariant (single load-bearing property)

> **A house-zone whose only occupied member rooms are `hallway`-typed (circulation)
> is NEVER conditioned. A zone with any dwelling-typed member room whose
> HVAC-occupancy signal is true (kind-aware presence, layered on the room's
> grace-held `STATE_OCCUPIED`, held for that room's `hvac_vacancy_hold`) IS
> conditioned. Retreat happens exactly once, at the zone level, after the LAST
> HVAC-occupied member room has been clear for `vacancy_grace` (10 min live).**

Corollaries reviewers must falsify:
- Aggression is **absolute**: no relaxation, no soft posture, no partial vote from hallways. If a hallway is the only occupied room, the zone stays vacant. (Non-goal below.)
- Grace-hold is **inherited, not rebuilt**: the HVAC-occupancy view is a kind-aware filter *on top of* the room's already-grace-held `STATE_OCCUPIED`, never over raw substrate reads (audit §(ii) row on `grace_hold`).
- The two dwell timers (per-room `hvac_vacancy_hold` for adopt, zone `vacancy_grace` for retreat) never stack — the zone-level `CONF_HVAC_ZONE_ENTRY_DWELL` defaults to **0** in the same cycle the per-room hold ships (audit footgun S1).

The invariant is asymmetric on purpose: fast-in (OR / min) and conservative-out (last-to-clear + one zone grace).

---

## 1. Institutional context verified (REUSE-or-BUILD per piece)

Sources: audit §(ii), re-verified this session against source. File:line citations authoritative.

| Piece the plan needs | Verdict | Existing prior art | Notes |
|---|---|---|---|
| Kind-aware presence (mmwave / motion / occupancy) | **REUSE** | `occupancy_substrate.is_kind_active(room, kind)` at `occupancy_substrate.py:732`; `get_room_kinds` at `:747`; module handle at `hass.data[DOMAIN]["occupancy_substrate"]` (see `presence.py:2592`) | Zero new wiring. Live consumers: `music_following.py:528`, `binary_sensor.py:669`, `presence.py:3270`. |
| Per-kind provenance at zone boundary | **REUSE** | `ZonePresenceTracker.provenance_for(room)` at `presence.py:707` | Fan-interference-hold-aware; use if we want the hold to ride. The HVAC-occupancy view uses `is_kind_active` directly for a fan-hold-*excluded* read — documented decision, see D1. |
| Per-room, per-consumer secondary hold pattern | **REUSE (shape)** | `CONF_FAN_VACANCY_HOLD` at `const.py:966`; `DEFAULT_FAN_VACANCY_HOLD=300` at `const.py:1153`; consumer `automation.py:2164` | New `CONF_HVAC_VACANCY_HOLD` follows this shape. **Do NOT add a third copy of the default** — `DEFAULT_FAN_VACANCY_HOLD` already double-defined at `const.py:1153` + `hvac_const.py:821`; put the new default in root `const.py` only. |
| Zone occupancy confidence | **REUSE + EXTEND** | `presence.check_zone_occupancy_confidence(zone)` at `presence.py:2057`; consumer `hvac.py:1826` | Source-4 (multi-room count) may want to count HVAC-occupied rooms once the new signal exists. D6 stuck-signal branch stays. |
| Grace-hold semantics | **REUSE (untouched, inherited)** | ARM `coordinator.py:2925-2938`; consume `coordinator.py:3581-3585` | Load-bearing. New HVAC-occupancy view MUST derive from `data[STATE_OCCUPIED]` (grace-held), not raw substrate — else H1 sparse-dropout failure reintroduced. |
| Pre-arrival machinery | **REUSE + EXTEND** (Stage C, out-of-scope here) | `hvac.py:469` (`_pre_arrival_zones/_persons/_start`); exemption `hvac.py:1993` | Not touched by this cycle. |
| Zone OR aggregation (adopt) | **REUSE (existing OR)** | `hvac_zones.py:148` `any_room_occupied = any(r.occupied ...)` | Aggregation math unchanged. Only the *input* to `RoomCondition.occupied` moves. |
| Zone retreat (grace) | **REUSE (unchanged)** | `hvac.py:1786-1791` grace_minutes gate | Stays `vacancy_grace` (live 10 min). |
| Population point (THE swap) | **REUSE (repoint)** | `hvac_zones.py:546` `occupied=data.get("occupied", False)` | This one line is the entire ripple surface. `RoomCondition.occupied` has 12+ HVAC-path consumers (`hvac.py:1787,1808,1990,3462,3627`, `hvac_override.py:2282,2433`, `hvac_predict.py:578,1368`, `hvac_zones.py:584,555`, `hvac_egress.py:483`, `hvac_fans.py:755,986`, `presence.py:2152`) — we do NOT add a parallel field. |
| ROOM_TYPE defaults table | **REUSE (pattern) + BUILD (new table)** | `ROOM_TYPE_TIMEOUTS` at `const.py:1171`; safe-get idiom at `coordinator.py:695`, `config_flow.py:1381`, `presence_fan_recheck.py:1102` | Add `ROOM_TYPE_HVAC_HOLD` mirroring shape. `.get(type, DEFAULT)` everywhere — new `hallway` value cannot KeyError. |
| Fast sub-loop (Stage D fast-in) | **DEFERRED (non-goal, see §6)** | `SOLAR_FOLLOW_TICK_S=60` `energy_const.py:996`; `_solar_follow` at `energy.py:1382` | Not built this cycle. |
| `hallway` room_type enum value | **BUILD (safe additive)** | Enum in `const.py:421-429`; selector `config_flow.py:1387` | Additive. Migration is operator-driven reclassification of the 6 hallways (Garage Hallway, Kitchen Hallway, Kitchen Hallway Garage, Master Hallway, Upstairs Hallway, Foyer). |
| `CONF_HVAC_VACANCY_HOLD` (per-room) | **BUILD** | No equivalent exists. `CONF_FAN_VACANCY_HOLD` is the shape template. | Room config flow; read at the HVAC-occupancy producer. |
| Per-room HVAC-occupancy entity | **BUILD** | No equivalent. `OccupiedBinarySensor` is sibling, not equivalent. | Operator mandate: must be observable. `binary_sensor.<room>_hvac_occupied`, ~43 entities. |

**Planning docs consulted:** the proposal + audit above; `PLANNING_hvac_supple_sequence*` for step-arc context; the shipped `ROOM-CLASSIFICATION-CONSISTENCY-1` (v5.103.0) for the room-type enum precedent.

**Memory bodies pulled:** `feedback_tier2plus_prior_art_scan`, `feedback_do_robust_fix_not_bandaid_and_card`, `feedback_suppression_needs_discharge`, `feedback_coincidental_equality_masks_concept_split`, `project_zone_away_when_occupied_home_night_gap`, `reference_hvac_zone_tonnage`.

**Design docs read:** `docs/Coordinator/HVAC.md` (per-coordinator design), presence/occupancy_substrate module headers.

**Code locations surveyed end-to-end / in relevant span:** `hvac_zones.py` (entire); `hvac.py` L160-540, L1750-2000; `hvac_const.py`; `presence.py` L680-733, L2055-2160; `occupancy_substrate.py` L732-770; `coordinator.py` L534-540, L2900-2940, L3350-3460, L3560-3640; `const.py` L960-975, L1150-1200, L421-429.

---

## 2. Deliverables

### D1 — Per-room HVAC-occupancy producer (the kind-aware view)

**What.** New helper on the HVAC coordinator (or a small dedicated module under `domain_coordinators/`) that, per room, produces a boolean HVAC-occupancy value:

```
hvac_occupied(room) =
    room[STATE_OCCUPIED]                             # grace-held, fused
    AND kind_aware_filter(room)                      # see below
    with tail-hold(room, hvac_vacancy_hold)          # per-room decay
```

- `kind_aware_filter(room)`: reads `occupancy_substrate.is_kind_active(room, kind)`. Default rule: **any of** `mmwave`, `occupancy`, `motion` is sufficient to *contribute*; `hallway`-typed rooms return `False` unconditionally (aggression = absolute).
- The AND-gate against grace-held `STATE_OCCUPIED` preserves fail-open on sensor blip (audit row on `grace_hold`; class-#7 sparse-dropout defense).
- The tail-hold is the per-room decay duration (`CONF_HVAC_VACANCY_HOLD`, default per `ROOM_TYPE_HVAC_HOLD[type]`, see D3). It bridges mmWave dropouts only; retreat proper is still the zone `vacancy_grace`.

**Wire-in.** Swap the input at `hvac_zones.py:546`:

```
occupied = self._hvac_occupancy.value_for(room_name)   # NEW producer
```

No parallel field on `RoomCondition`. The 12+ downstream consumers of `RoomCondition.occupied` see the new semantics transparently.

**Acceptance criteria (D1):**
- **Verify:** every consumer at the 12+ sites listed above reads the same field; no new `hvac_occupied` attribute leaked into `RoomCondition`.
- **Verify:** on a simulated sensor blip (unavailable), `hvac_occupied(room)` stays true iff `data[STATE_OCCUPIED]` stays true — i.e. grace_hold rides.
- **Sensor:** `binary_sensor.<room>_hvac_occupied` (D2) matches the producer's value each tick.
- **Test:** unit test `test_hvac_occupancy_producer_grace_hold_inherits` proves the AND-on-STATE_OCCUPIED path; `test_hvac_occupancy_producer_hallway_returns_false` proves hallway suppression.
- **Live (discriminating):** with a hallway PIR firing and no dwelling room occupied, `binary_sensor.<hallway>_hvac_occupied == off` AND `sensor.hvac_zone_<N>_status` attribute `any_room_occupied == false`. **Under the wrong-fix failure mode** (kind filter present but not the hallway short-circuit), the hallway sensor would flip *on* on PIR. That distinguishes the fix from "we filtered the kinds but forgot the hallway rule."

### D2 — Per-room HVAC-occupancy diagnostic entity (observability)

**What.** New `binary_sensor.<room>_hvac_occupied` platform entry mirroring `OccupiedBinarySensor` structure (state + attrs: `kinds_active`, `hvac_vacancy_hold_s`, `hold_expires_at`, `room_type`, `source = "hvac_occupancy"`).

**Acceptance criteria (D2):**
- **Verify:** entity created for every room that has an existing `<room>_occupied` sibling; count matches room registry count.
- **Sensor:** `binary_sensor.<room>_hvac_occupied.attributes.source == "hvac_occupancy"`.
- **Test:** platform-add test asserts 1:1 with room registry.
- **Live (discriminating):** in a bedroom with a still occupant (mmWave active, motion quiet), `<bedroom>_hvac_occupied == on` while `<bedroom>_occupied` may also be on but for different reasons — attributes show `kinds_active` includes `mmwave`. **Under the wrong-fix failure mode** (the entity is a rename of the lighting-fused signal), `kinds_active` would be missing or would equal the union without mmWave-only stillness — that distinguishes real kind-aware from a cosmetic sensor.

### D3 — `ROOM_TYPE_HVAC_HOLD` defaults + `CONF_HVAC_VACANCY_HOLD` per-room override

**What.**
- Add `ROOM_TYPE_HVAC_HOLD` dict in `const.py` alongside `ROOM_TYPE_TIMEOUTS` (`const.py:1171`). Initial values (short by default — retreat lives at the zone):
  - `hallway`: `0` (does not contribute at all)
  - `bathroom`, `closet`, `garage`, `infrastructure`, `utility`: `0`
  - `bedroom`: `120`
  - `common_area`, `generic`: `60`
  - `media_room`: `180`
- Add `CONF_HVAC_VACANCY_HOLD` in `const.py` next to `CONF_FAN_VACANCY_HOLD` (`const.py:966`). Room-level override; unit = seconds; default resolves via `ROOM_TYPE_HVAC_HOLD.get(type, 60)`.
- Read the effective value at the D1 producer via the same shape as `automation.py:2164` reads `CONF_FAN_VACANCY_HOLD`.
- **Do NOT** define `DEFAULT_HVAC_VACANCY_HOLD` in `hvac_const.py`; single home in `const.py` (avoids the double-definition already seen for `DEFAULT_FAN_VACANCY_HOLD`).

**Acceptance criteria (D3):**
- **Verify:** `.get(type, DEFAULT)` idiom used at every read (grep for `ROOM_TYPE_HVAC_HOLD[` should return zero — subscript access is forbidden).
- **Sensor:** `binary_sensor.<room>_hvac_occupied.attributes.hvac_vacancy_hold_s` equals the resolved value.
- **Test:** `test_room_type_hvac_hold_defaults_and_override` covers (a) type default, (b) per-room override wins, (c) unknown room_type falls back to 60.
- **Live:** on the Kitchen (short-hold dwelling), attribute `hvac_vacancy_hold_s == 60` (or override); on Master Bedroom, `== 120` unless overridden.

### D4 — `hallway` room_type enum value + reclassification of 6 rooms

**What.**
- Add `ROOM_TYPE_HALLWAY = "hallway"` to the enum block at `const.py:421-429`.
- Add to the `config_flow.py:1387` selector list (hand-built list; must edit).
- Reclassify the 6 known hallways (Garage Hallway, Kitchen Hallway, Kitchen Hallway Garage, Master Hallway, Upstairs Hallway, Foyer) via a **one-shot config edit** — NOT an auto-migration. Document in the README the exact rooms and expected effect.
- Wire `ROOM_TYPE_HALLWAY` into `ROOM_TYPE_TIMEOUTS` (short, e.g. `120`) and `ROOM_TYPE_HVAC_HOLD` (`0`, see D3). Verify no `ROOM_TYPE_*` table uses subscript access (already audited safe: `coordinator.py:695,3814`, `presence_fan_recheck.py:1102`, `config_flow.py:1381`).

**Acceptance criteria (D4):**
- **Verify:** grep confirms zero subscript accesses on any `ROOM_TYPE_*` table (all `.get(...)`).
- **Verify:** the 6 hallway config entries carry `room_type: hallway` post-reclassification.
- **Sensor:** `sensor.<room>_status.attributes.room_type == "hallway"` for the 6 rooms.
- **Test:** `test_hallway_room_type_no_keyerror_across_tables` iterates every `ROOM_TYPE_*` table with `hallway`.
- **Live (discriminating):** with a person walking Garage Hallway → Kitchen Hallway → Foyer during a vacant zone, `sensor.hvac_zone_1_status` stays `vacant` throughout; `binary_sensor.garage_hallway_hvac_occupied == off` throughout. **Under the wrong-fix failure mode** (enum added but `ROOM_TYPE_HVAC_HOLD["hallway"]` not `0`), the corridor's short PIR pulse would flick the sensor on for the hold window — distinguishing "enum plumbed" from "enum plumbed AND hold=0."

### D5 — Retire zone-level `zone_entry_dwell` (default 0, keep field one release)

**What.** Change `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` at `hvac_const.py:377` from `3` → `0`. Leave the `CONF_HVAC_ZONE_ENTRY_DWELL` field, the `number.py:417` `ZoneEntryDwellNumber` entity, and the consumer at `hvac.py:1986-1996` **in place** for one release — labeled with a code comment: `# LEGACY 2026-09 — superseded by CONF_HVAC_VACANCY_HOLD (per-room). Slated for deletion next release once observability window closes.`

**Why not delete now.** Audit S1 — the entity is operator-facing and live-editable. Deleting the config surface in the same cycle blinds an observability window. The default flip is the load-bearing change; the field's continued presence is documentation only.

**Acceptance criteria (D5):**
- **Verify:** default is `0`. Live install: operator resets the entity to `0` (or plan ships a migration hint) — see live check below.
- **Verify:** with default at 0, `hvac.py:1991` check `session_start < dwell` is effectively a no-op (dwell always 0).
- **Test:** `test_zone_entry_dwell_default_zero_no_op` — session-start check does not delay adopt.
- **Live (discriminating):** on first room occupancy after zone vacant, elapsed time to `any_room_occupied → true → zone adopt` ≤ one loop tick + per-room hold. **Under the failure mode** (default flipped in const but the live-install override sticks at 3), the adopt is delayed by 3 min — the live check is the entity read, not the const read.

### D6 — Zone-aggregation retreat semantics preserved (documentation-only)

**What.** No code change. Explicitly document — in `hvac.py:1786-1791` block comment AND in the README — that the zone-level `vacancy_grace` (live 10 min) is the sole retreat timer. Per-room `hvac_vacancy_hold` is a gap-bridger only.

**Acceptance criteria (D6):**
- **Verify:** grep confirms zero new `_hold` or `_grace` fields added to `ZoneState`.
- **Live:** on last dwelling room clearing (all others already clear), the zone transitions to `vacant` exactly `vacancy_grace` after the last-clear timestamp, ±1 loop tick.

---

## 3. Code supersession triage (audit §(i), condensed for build)

Zero-DELETE outcome (per audit). What ships:

| Item | Bucket | Action this cycle |
|---|---|---|
| `_zone_entry_dwell` field + preset-loop check (S1/S2) | **KEEP + DOCUMENT** | D5: default 0, comment as legacy. Delete next release. |
| `RoomCondition.occupied` read path (S3) | **KEEP + WIRE** | D1: repoint population source at `hvac_zones.py:546`. |
| Redundant-second-hold conflation (S4) | **KEEP + DOCUMENT** | D6: comment in `hvac.py:1786`. Semantically resolved by D3. |
| mmWave-sole suppression latch (S5) | **KEEP unchanged** | Add block-comment note that HVAC-occupancy view is intentionally out-of-band. |
| Fan-transition creation-suppression gate (S6) | **KEEP unchanged** | Same note. |
| `presence.py:697` fan-interference hold on fused view (S7) | **KEEP** | Document that HVAC-occupancy uses `is_kind_active` directly (fan-hold NOT inherited). |
| No S14 siblings found (S8) | n/a | Re-grep at build time. |

**Nothing DELETEs.** This is a signal-swap re-architecture; the "code stacked on code" the operator flagged in the proposal §10a is retired via a **default flip (S1) + one comment update (S4) + one population-source swap (S3)**, not deletions.

---

## 4. Knob ladder

Every new number gets a named home. Per the placement ladder:

| Knob | Home | Reason |
|---|---|---|
| `ROOM_TYPE_HALLWAY` enum value | **Config/options flow** (per-room `CONF_ROOM_TYPE`) | Per-deployment classification — operator sets on the 6 hallways once. |
| `ROOM_TYPE_HVAC_HOLD` defaults (`hallway=0`, `bedroom=120`, …) | **Module constant** (`const.py`) | Governance = reviewed code change. Tuning the default table shifts the whole house; deserves review. |
| `CONF_HVAC_VACANCY_HOLD` (per-room override, seconds) | **Config/options flow** (room-level) | Operator tunes per-room by observation. Rare edit; not dashboard-tunable. |
| `binary_sensor.<room>_hvac_occupied` | **Diagnostic entity** | Observability, not a knob. |
| `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` flip 3 → 0 | **Module constant** (`hvac_const.py:377`) | Reviewed code change; live entity retained for one release. |
| `hvac_vacancy_grace_minutes` (live 10) | **Number entity** (existing, unchanged) | Live-tunable; operator legitimately turns this by observation. Not touched this cycle. |

Fast-in (Stage D) knobs are **not** on this ladder — deferred.

---

## 5. Tier 2-DB review protocol (three framing-disjoint axes)

Per CLAUDE.md standing policy: trust-hierarchy ripple + shared primitive → Tier 2-DB even though no DAO change. Three parallel reviews, each with an explicit framing:

- **Review A — correctness + edge cases on the D1 producer.** Grace-hold inheritance; kind-aware filter under mmWave dropout, PIR-only rooms, fan-hold interactions; per-room hold decay across restart; hallway short-circuit; every consumer of `RoomCondition.occupied` still sees a semantically sensible value (list = the 12+ sites in §1).
- **Review B — cross-coordinator / precedence / no-flap.** Zone-level retreat timer unchanged; per-room hold does not stack with zone `vacancy_grace`; `CONF_HVAC_ZONE_ENTRY_DWELL=0` default is honored under both fresh install and existing-config restart; pre-arrival exemption at `hvac.py:1993` unaffected; `check_zone_occupancy_confidence` Source-4 semantics unchanged (or updated intentionally); no double-adopt on the 60 s fast tick (n/a — fast tick deferred).
- **Review C — surfaces + test authority.** New `binary_sensor.<room>_hvac_occupied` round-trips options/registry/RestoreEntity; `ROOM_TYPE_HALLWAY` enum change does not KeyError any `ROOM_TYPE_*` table (audit list); config-flow reclassification of the 6 hallways persists across reload; behavioral tests drive production code paths (not their own booleans); mutation-verify each test — neuter D1's hallway short-circuit ⇒ specific test fails.

Fix all CRITICAL/HIGH before deploy. Live-validation as Review D (post-restart) records observed values into `README_v<version>.md`.

---

## 6. Non-goals (explicit)

- **Fast-in (Stage D).** No new `async_track_time_interval` sub-loop this cycle. Reaction latency remains 5 min. **Revival trigger:** operator observation of unacceptable adopt latency in the hot-and-occupied case, OR a 3rd/4th fast sub-loop need surfaces elsewhere. Parked design: `_solar_follow` pattern at `energy.py:1382`.
- **Whole-zone SOFT posture / partial-vote aggression.** Launch posture is **absolute**. **Revival trigger:** operator comfort complaints tied to a genuine hallway lingering (long phone call in Foyer, etc.).
- **Stage B stillness refinement.** Not built until Stage A residuals are measured and mmWave dropout gate (proposal §5 Stage B) passes.
- **Stage C guest-as-zone-person.** Separate card `HVAC-GUEST-AS-ZONE-PERSON-1`.
- **Auto-migration of the 6 hallway rooms.** Operator reclassifies by hand — no `.storage` rewrite ships with this cycle.
- **Delete of `CONF_HVAC_ZONE_ENTRY_DWELL` entity/field.** Deferred one release for observability (D5).

---

## 7. Source disagreements resolved

Two disagreements between the proposal and the audit — resolved explicitly so the builder does not re-litigate:

1. **`vacancy_grace` / `zone_entry_dwell` live vs default.** Proposal §8 cites live 10 / 5. Audit §(ii) row 5 notes source defaults are 15 / 3 (`hvac_const.py:374,377`). **Resolution:** the 10 / (retiring) 5 are load-bearing `.storage` overrides; this plan tunes against the LIVE values, and D5 changes the source default (3 → 0), not the live entity. The live entity read is the authoritative operational number.
2. **Proposal Stage A′-2 says "retire zone-level `zone_entry_dwell`"; audit S1 says "keep + document, default flip only, delete next release."** **Resolution:** adopt the audit's staged approach (D5). Behaviorally identical (default=0 → no-op) while preserving observability. Operator is not blinded.

Everything else is consonant — the proposal describes the WHY, the audit locks the WHERE, this plan pins the WHAT SHIPS.

---

## Summary

- **Falsifiable invariant:** a zone whose only occupied rooms are `hallway`-typed is never conditioned; a zone with any dwelling-typed member room's HVAC-occupancy true (grace-held + kind-aware) IS; retreat is one zone-level `vacancy_grace`.
- **Deliverables:** D1 producer (kind-aware, grace-held, hallway short-circuit) · D2 diagnostic entity per room · D3 `ROOM_TYPE_HVAC_HOLD` + `CONF_HVAC_VACANCY_HOLD` · D4 `hallway` enum + reclassify 6 rooms · D5 zone-entry-dwell default 0 (keep entity one release) · D6 documentation-only retreat-semantics preservation.
- **Ripple surface:** ONE line (`hvac_zones.py:546`) + one default flip + additive enum + additive entity + additive consts. Zero-DELETE.
- **Review tier:** 2-DB, three framing-disjoint axes (correctness / cross-coord / surfaces).
- **Non-goals:** fast-in loop, soft posture, Stage B, Stage C, entity delete, auto-migration.
- **Resolved sources:** live vs default numbers, and the "retire vs default-flip" tension on `zone_entry_dwell`.
