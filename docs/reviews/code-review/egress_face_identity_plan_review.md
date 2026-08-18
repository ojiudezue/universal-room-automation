# PLAN REVIEW — Egress Face-Identity (D1 focus, D2 gate sanity)

**Date:** 2026-08-18
**Plan under review:** `docs/planning/PLANNING_egress_face_identity.md`
**Tier:** 2-DB (one adversarial plan review before build)
**Reviewer scope:** D1 only (D2 gated on Wed payload)
**Verdict:** **PLAN-NEEDS-FIXES** (one CRIT, one HIGH, two MED, two LOW)

The plan's institutional-context section is strong (readers/writers correctly
grepped for the two-emission-site enumeration and the identity-notion
segregation), and the marginal-benefit split (D1 now / D2 gated) is
defensible. However, the load-bearing invariant I1 is asserted against the
WRONG writer: there is a second, independent `identified_count` computation
that the plan does not mention and that a fuse into `:1855` alone will
not reach at house level. That is exactly the 2026-08-17 GUEST-CENSUS
double-count geometry the plan claims to have designed against, so this
must be fixed IN THE PLAN before build dispatch.

---

## Independent identified_count-writer enumeration

Grep: `grep -nE 'identified_count|known_persons' custom_components/universal_room_automation/camera_census.py`

Two live writers (not one, as the plan claims):

1. `camera_census.py:1855-1856` — `_cross_correlate_persons`
   ```python
   known_persons = face_ids | ble_ids
   identified_count = len(known_persons)
   ```
   Feeds the raw per-zone `CensusZoneResult`. This is the writer the plan
   names as THE single writer for the union fuse.

2. `camera_census.py:3391-3392` — `_apply_enhanced_house_census`
   ```python
   recognized_set = set(ble_persons) | set(face_recognized)
   identified_count = len(recognized_set)
   ```
   Where `face_recognized = self._get_face_recognized_person_names(now)`
   (`:3388`). This function is called on the HOUSE zone result and returns
   a NEW `CensusZoneResult` at `:3440` whose `identified_count=identified_count`
   OVERWRITES the raw value from writer #1. This is the value that flows
   into the house-level `identified_count` attr at `:1253`, into
   `unidentified_count` via `raw_total_ceiling`/`clamped_unidentified`, and
   into the guest-math consumer.

Additionally, exterior zone construction hard-codes `identified_count=0`
at `:1648-1649`; not a fuse target but noted for completeness.

Consequence for D1 as scoped: adding `egress_face_ids` to the union at
`:1855` will change per-zone raw results (and `identified_persons` at the
raw layer), but at the house level the value is discarded and replaced
with `len(set(ble_persons) | set(face_recognized))` — which contains
neither `egress_face_ids` nor anything derived from egress. **The
cycle's central deliverable (fuse egress-face identity into the census
union) does not reach the house-level count under the plan as written.**
This is the invariant I1 claim being asserted against the wrong site.

---

## Emission-site enumeration (independent)

Grep: `grep -rnE "ura_person_egress_event|log_entry_exit_event\(" custom_components/universal_room_automation/`

Producers (2 sites, as plan claims):
- `transit_validator.py:1102` — `hass.bus.async_fire("ura_person_egress_event", {..., "person_id": None, ...})`
- `transit_validator.py:1120` — `await database.log_entry_exit_event(person_id=None, ...)`

Both are inside `_resolve_direction` and share the same local
`direction`/`confidence`/`egress_camera_id`/`egress_timestamp`, so a single
`_resolve_egress_face_identity(...)` call above them can supply both,
consistent with the plan's D1 file plan. No 3rd producer.

Consumers (all pre-existing, listener-only):
- `sensor.py:4184, 4262, 4323, 4371` — four `async_listen("ura_person_egress_event", ...)` sites, all sharing the `_handle_egress_event` handler pattern already using `event.data.get("person_id") or "unidentified"`.
- `database.log_entry_exit_event` at `database.py:3709` — sole DB writer; no other callers.

Emission-site enumeration in the plan is correct.

---

## Reuse claim verification

Grep confirms the plan's reuse citations resolve:
- `camera_census._resolve_face_entity_id` at `:2470` ✓
- `_get_face_recognized_persons_fresh` at `:2652` ✓
- `_get_face_recognized_person_names` at `:3283` ✓
- `_extract_camera_stem` at `transit_validator.py:1050` (delegates to `CameraIntegrationManager._extract_camera_stem`) ✓

D1's helper can consume these without introducing a parallel Frigate-face
resolver. Reuse claim OK.

---

## I4 (identity-notion segregation) verification

Non-goals §5 explicitly forbids writes into `person_coord.data[name]["location"]`
and into `exterior_track_linker` sub_label/identified. Plan's declared write
targets for D1 are:
- `transit_validator.py:1106/1121` (person_id slot in ura_person_egress_event + DB row)
- `camera_census.py` (new `egress_face_ids` register + fuse into `:1855`)

Neither touches the two segregated stores. I4 upheld in the plan's write
surface. No finding.

---

## Findings

### C-CRIT-1 — I1 asserted against the wrong writer; house-level fuse missing

**Where:** Plan §2 (I1), §3b (PRODUCER), §4 D1 file plan (`camera_census.py`).

**Claim in plan:** `known_persons = face_ids | ble_ids | egress_face_ids` at
`camera_census.py:1855` is the sole writer of `identified_count`; fusing
`egress_face_ids` there guarantees I1.

**Reality (grep):** `_apply_enhanced_house_census` at `:3391-3392`
independently recomputes `identified_count = len(set(ble_persons) |
set(face_recognized))` from `_get_face_recognized_person_names(now)` and
returns a new `CensusZoneResult` at `:3440` that overwrites the raw
`identified_count` from `:1855` for the HOUSE zone. The house-level
attribute at `:1253` (`identified_count`), the derived `unidentified_count`
via `raw_total_ceiling` at `:3424`, and every downstream guest-math
consumer read the `:3391` value — not the `:1855` value.

**Consequence:** D1 as scoped delivers the fuse at the per-zone raw layer
where nothing consumes it, and DOES NOT flow into the house-level count
that the acceptance criteria describe ("house-level `identified_count` for
the tick during a known crossing equals `|face_ids ∪ ble_ids ∪
egress_face_ids|`"). The fuse would be a no-op at the house level. This
is exactly the 2026-08-17 GUEST-CENSUS geometry (an independent
recomputation site that ignores an "authoritative" union), which the plan
cites as motivation. A builder following the plan literally would ship a
tested-green cycle whose invariant fails on the running house.

**Recommended plan edit (in `PLANNING_egress_face_identity.md`):**

1. §0: add a REUSED entry — "`camera_census._apply_enhanced_house_census`
   at `:3371-3466` (independent house-level `identified_count` writer at
   `:3391-3392` and `identified_persons` writer at `:3443`). D1 MUST fuse
   `egress_face_ids` here as well; the union at `:1855` alone does not
   propagate to the house zone."

2. §3b PRODUCER: replace "sole writer" wording with:
   > "The union has TWO effective sites: the raw per-zone writer at
   > `:1855` (`face_ids | ble_ids`) AND the house-level rewriter at
   > `:3391-3392` (`set(ble_persons) | set(face_recognized)`). D1 fuses
   > `egress_face_ids` into BOTH — at `:1855` for raw zone results and
   > at `:3391` by extending `recognized_set` to
   > `set(ble_persons) | set(face_recognized) | set(egress_face_ids)`.
   > `identified_persons` at `:3443` (`sorted(recognized_set)`) inherits
   > the fuse automatically. No new count writer is introduced; both
   > existing writers become union writers over one additional NAME set."

3. §4 D1 file plan: expand the `camera_census.py` bullet to name both
   fuse sites explicitly (":1855 AND :3391").

4. §2 I1 test text: adjust discriminator to state the observation at BOTH
   layers so the test can't pass at raw while failing at house. Add an
   acceptance test that mutates the `:3391` union out and confirms a
   specific test fails (per Tier-3-style mutation gate — advisable even
   at Tier-2-DB here because this is the exact site of the last CRIT).

5. §6 collision-risk item 1: rewrite to acknowledge the second writer
   was in fact the 2026-08-17 site and that mitigation now covers BOTH.

Without these edits the invariant I1 is not falsifiable against the code
as it exists and the cycle can ship a green build that fails silently on
the running house.

---

### C-HIGH-1 — `EGRESS_FACE_UNION_TTL_S` missing from the knob-ladder table

**Where:** §3b names `EGRESS_FACE_UNION_TTL_S` (default 300) as the TTL
for the egress-face register consumed by the census fuse. §7 knob table
lists `FACE_MATCH_WINDOW_S`, `CROSS_NVR_AGREEMENT_WINDOW_S`,
`PROTECT_CORROBORATION_CONFIDENCE_BUMP`, `PROTECT_CORROBORATION_ENABLED`
— but omits `EGRESS_FACE_UNION_TTL_S`.

**Consequence:** Numbers-get-knobs policy violated for a load-bearing
value. A builder is left to infer the rung; the wrong choice inflates or
starves the `identified_count` window the cycle is meant to deliver.

**Recommended plan edit:** Add row to §7:

| `EGRESS_FACE_UNION_TTL_S` (default 300) | How long an egress-face name stays in `egress_face_ids` for the census fuse (both `:1855` and `:3391` sites) | **Module constant** (`const.py`) | Bounds the incremental identification window; wrong value inflates `identified_count` past the crossing (I1 timing side). Not operator-tunable. |

Also cross-reference from §4 D1 `const.py` bullet.

---

### C-MED-1 — D2 body detailed alongside D1 in the same file plan risks accidental build

**Where:** §4 D2 is fully specified (files, acceptance criteria, tests),
followed by §7 knobs that already include the two D2-only constants and
the D2 kill switch. §8 verdict is SPLIT but the D2 spec is not fenced
against inheritance by the D1 builder.

**Gate reality:** §4 D2 opens with an explicit Precondition
("Precondition (measure-before-build gate): at least one real face-match
POST captured ... Do NOT hard-code a guessed field ... If the payload is
too poor ... park D2"). §7 marks `PROTECT_CORROBORATION_ENABLED` default
`False`. That IS a gate. Not leaky in principle.

**Risk:** The autonomy protocol dispatches builders with the plan doc as
context; a builder reading §4 end-to-end can mistake "specced" for
"in-scope." Recall memory: `feedback_wire_in_anchor_mandatory` — three
cycles in a row shipped neuter-deletable wire-ins whose builders had the
spec in front of them.

**Recommended plan edit:**
- Add a bold banner at top of §4 D2: `> **DO NOT BUILD D2 IN THIS CYCLE.** Payload capture gate not met. D2 spec is retained here for continuity; build only after §D2-payload appendix lands.`
- Add explicit line to §4 D1: `Out of scope for this build: everything under §4 D2, all D2 knobs in §7, all §5 non-goals.`
- Mirror on the kanban card (EXTERIOR-GUEST-FACE-FASTFOLLOW-1) — but
  the plan doc must carry it too so the builder-fresh context has it.

---

### C-MED-2 — `identified_persons` list-vs-set duplication risk not addressed

**Where:** `:1857` (`sorted(list(known_persons))`) and `:3443`
(`sorted(recognized_set)`). Additionally `:1193` computes
`face_persons=list(set(house_result.identified_persons + property_result.identified_persons))`.

**Risk:** If D1 populates `egress_face_ids` with names from a slightly
different namespace than `_get_face_recognized_person_names` returns
(e.g. slug vs display name, casing), the union is set-based but the
elements are NOT the same key. "Oji" and "oji" become two entries and I1
is violated by name-namespace drift — not by an additive writer.

**Recommended plan edit:** Add I5 (or fold into I1): "Name normalization
invariant — every name entering `egress_face_ids` is normalized to the
same key shape as `_get_face_recognized_person_names` output (verify by
reading `:3283-3369`). Any resident recognized by both sources produces a
single set element." Add unit test with a case-varied name pair.

Without this the invariant I1 has a namespace-drift hole the double-count
test as written won't catch (the test uses `"Oji"` on both sides).

---

### C-LOW-1 — I3 discriminator wall-clock coupling

**Where:** §4 D1 acceptance test text — "age the face state to
`FACE_MATCH_WINDOW_S + 1s`."

**Risk:** Behavioral tests coupled to wall clock have a track record here
(memory: rung-gate seam / wall-clock-coupled tests). §4 line 241 does
say "NO wall-clock coupling" but the discriminator wording could be read
as `time.sleep`-adjacent.

**Recommended plan edit:** Reword to "advance the fixture clock past
`FACE_MATCH_WINDOW_S` (freezegun / injected `now`)". Small; costs nothing
now, saves a fix-up later.

---

### C-LOW-2 — Person-trust veto pattern not called out on the new helper

**Where:** `_get_face_recognized_person_names` at `:3346-3366`
already applies the `person.<slug>=not_home` fail-open veto (v4.7.13/14
pattern). The new `_resolve_egress_face_identity` helper the plan
introduces reads face state directly (`sensor.<cam>_last_recognized_face_2`
via the reused resolver), bypassing that veto.

**Risk:** A resident whose person.<slug> is `not_home` could have a
just-flapping last_recognized_face and be stamped onto an egress event.
The plan's discriminator ("recognized 30+ minutes earlier ⇒ None") is
protected by `FACE_MATCH_WINDOW_S`, but the not_home veto is a separate
guard the census layer already applies and the egress-stamp path would
skip.

**Recommended plan edit:** §3a PRODUCER — add "helper applies the same
person.<slug>=not_home fail-open veto (mirror `:3346-3366`) before
returning a name." Add unit test: veto path returns None even with fresh
face state.

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| CRIT | 1 | C-CRIT-1 (house-level writer missed) |
| HIGH | 1 | C-HIGH-1 (`EGRESS_FACE_UNION_TTL_S` off the ladder) |
| MED | 2 | C-MED-1 (D2 not fenced against accidental build), C-MED-2 (name namespace) |
| LOW | 2 | C-LOW-1 (wall-clock wording), C-LOW-2 (person-trust veto on new helper) |

**Verdict — PLAN-NEEDS-FIXES.** C-CRIT-1 alone would ship a green cycle
whose invariant fails on the running house — the exact GUEST-CENSUS
regression class the plan cites as motivation. Fix all findings in the
plan, then dispatch the builder.

D2 gate: after the plan fixes above, the D2 gate is genuine (Precondition
+ default-OFF kill switch). C-MED-1 tightens the fence so the D1 builder
cannot accidentally inherit it.
