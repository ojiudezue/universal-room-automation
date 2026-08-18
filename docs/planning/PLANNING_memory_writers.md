# PLANNING — MEMORY-WRITERS-1 (scope reset)

**Cycle:** memory-writers close-out
**Tier proposed:** Tier 2 (additive, memory-ineligible, no cross-coordinator trust edge)
**Author:** orchestrator, 2026-08-18
**Status:** DRAFT — awaiting operator go

---

## TL;DR — the card's stated scope is already shipped

The KANBAN card MEMORY-WRITERS-1 names its "top 1–2" writers as
**fan-release retro-phantom** and **away_transition_blocked**. Both
are already on develop, shipped in **v5.78.0** (PATH-ALPHA D4/D5). The
adjacent two writers the retro named — **tracker_trust_excluded** (D6)
and **house_state_transition** (D7 with rich snapshot) — also shipped
in the same cycle. The card's YAML row is `status: shipped_organic`;
the epic card's `next` field still names the same two writers as the
"remaining forward step", which is a stale hand-off.

**Marginal-benefit verdict on the card as written: SIMPLIFY — do not
rebuild what shipped.** Instead:

1. **Recommend closing MEMORY-WRITERS-1 as SHIPPED** (the audit's two
   top-ranked candidates are live; not under-firing — see §2).
2. **Open a small follow-up that fills the ONE remaining actionable
   audit gap** — a `zone_phantom` writer covering the zone-tier
   divergence Investigation 1 flagged as *completely* unwitnessed
   ("no zone-tier episodes exist at all", AUDIT_memory_retro_value.md
   Investigation 1 & the "Missing episode types" list).

This planning doc scopes that single-writer follow-up.

---

## 1. Institutional context verified

**Prior-art surfaces read:**

- `custom_components/universal_room_automation/memory_writers.py`
  (lines 1–644, read end-to-end) — the D4–D7 family already
  implements the architectural pattern for episode writers:
  fire-and-forget, kill-switch, dedup via `source_ref`,
  swallow-own-exceptions, in-construction rate bounds
  (window/hold/debounce/edge-only).
- `custom_components/universal_room_automation/coordinator.py:2790–2828`
  — D4 `write_phantom_retro` call site (fan-off correlated
  edge-check on the room's substrate).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:1599,
  2379–2396, 6079–6100, 6548–6589` — D5 tracker construction, boot
  reconcile, D6 observe(), D7 emit with rich gate-input snapshot
  (census / unidentified_count / excluded_persons / veto_path
  ALREADY populated at :6557–6576 → the audit's Investigation 2
  guest-FP query IS now natively answerable; no snapshot enrichment
  needed).
- `custom_components/universal_room_automation/const.py:3796–3820` —
  kill-switch constants for all four shipped writers (rung-1
  Numbers-Get-Knobs, module constants — the correct rung: these are
  "does the writer fire" toggles, not operator-tunable policy).
- `docs/planning/ARCHITECTURE_hierarchical_memory.md` §4 (episodic
  tier writer contract), §5c (compaction), §8 (memory-ineligible
  decisions — the enforcement bar for new writers).
- `docs/planning/AUDIT_memory_retro_value.md` — full read; the
  "Missing episode types" list is the authoritative candidate set.
- `docs/planning/kanban.data.yaml:2684–2723` — MEMORY-WRITERS-1
  row + `folded_2026_08_16` note ("FOLDED into the PATH-ALPHA cycle
  as D4-D7"). Confirms shipped state.
- `docs/readmes/README_v5.78.0.md` — referenced by the card as the
  ship vehicle (existence confirmed via grep).

**Live evidence sampled (read-only):** DB file exists at
`/Users/okosisi/ha-config/universal_room_automation/data/universal_room_automation.db`.
Row-count sampling deferred — operator's brief already stated the
observed shape ("4 rows" for `away_transition_blocked`) and the
mechanism reading below (§2) explains that shape without a DB probe.

**Every proposed addition (single writer scope below):** REUSED /
NEW called out inline in §4.

---

## 2. Verified determination — new writers vs fix-under-firing

Per operator's brief, precisely disambiguate:

| Writer | Shipped? | Live behavior | Verdict |
|---|---|---|---|
| **fan-release retro-phantom** (`phantom_retro`, D4) | YES v5.78.0 | Fires when mmWave releases within `PHANTOM_RETRO_RELEASE_WINDOW_S` of a fan-off AND the preceding hold ≥ `PHANTOM_RETRO_MIN_HOLD_S`. Detector-INDEPENDENT (was the retro-audit's headline gap-fixer). | DO NOT DUPLICATE. If organic evidence shows the release/hold thresholds miss real latches, retune the two constants; do not add a second writer. |
| **away_transition_blocked** (D5) | YES v5.78.0 | Coalesced open/close on held path-α+β block. **4 rows on live is the SHAPE of a 300s min-hold debounce + 6h max-open coalescing, not under-firing.** The design (memory_writers.py:194–204, `AWAY_BLOCK_EPISODE_MIN_HOLD_S=300`) explicitly emits ONE row per sustained block-episode, not per tick. The 82-min AWAY-BLOCK-1 incident correctly generates ~1 row, not ~80. | DO NOT ADD A NEW WRITER. If rare firing is a diagnosability concern, the surface to tune is the min-hold constant (rung-1 knob), NOT a duplicate writer. Recommend leaving as-is until organic data shows a missed real block. |
| **tracker_trust_excluded** (D6) | YES v5.78.0 | 60s debounce edge-writer. | Out of card scope; verify shipped. |
| **house_state_transition** (D7) | YES v5.78.0, snapshot rich | Snapshot already carries census + unidentified_count + excluded_persons + veto_path (presence.py:6557–6576) → guest-FP recurrence is queryable natively. | Out of card scope; verify shipped. |
| **zone_phantom** (zone-tier divergence) | **NO** — never built | AUDIT Investigation 1: "the F2 zone-vs-house-tier divergence (no zone-tier episodes exist at all)". Zero coverage for the entire zone tier. | **BUILD (this cycle).** |
| exterior_track multi-source (Protect timestamps in hops) | NO | Depends on Protect Alarm Manager webhook wiring, tracked under EXTERIOR-GUEST-FACE-FASTFOLLOW-1. | DEFER — dependency not shipped. |

**Minimal recommended scope for this cycle:** ONE new writer,
`zone_phantom`.

---

## 3. Marginal-benefit decomposition

| Option | Marginal benefit | Marginal ingredient risk | Verdict |
|---|---|---|---|
| Do nothing (close card as shipped) | Zero new coverage; the two card-named writers already answer their target questions. | None. | Legitimate baseline. |
| Retune D5 min-hold (300 → 120s) to raise firing rate | ~2–3× row rate on incident-shape blocks; risk: more flap-driven rows during normal home_day → sleep transitions. | Behavior knob turn; no new code. | REJECT for now — no organic evidence of missed blocks; premature retune. |
| **Add `zone_phantom` writer (proposed)** | Fills the sole zone-tier writer gap the audit named. Would witness the F2 zone-vs-house divergence class that today produces ZERO memory rows anywhere. | ONE new producer on the write queue, edge-only + hold-gated by construction (see §4). Same writer contract as D4–D7, so no new architectural surface. | **BUILD.** Modest marginal benefit, modest marginal risk (parallel to a shipped family), inside Tier-2 envelope. |
| Add exterior_track Protect-timestamp hop | High value for first-witness questions. | Requires external Protect webhook plumbing that lives in another planned cycle. | DEFER — dependency-blocked. |

---

## 4. Deliverable — D1: `zone_phantom` writer

Single new writer. All references REUSED unless flagged NEW.

### Contract

Emit ONE `zone_phantom` episode when, for a configured hold window,
the **zone tier reads occupied while the house tier reads away** (or
its sleep/vacation equivalents where zone-occupancy would be
inconsistent). Episode is `node_id="zone:<zone_slug>"`, adjudication
`"observed"`, `adjudicated_by="zone_house_divergence"`.

### Producer check (per operator's producer/consumer rule)

**How the value is computed and its dependencies:**

- Zone-tier occupancy — REUSED, read from the existing zone presence
  tracker / zone occupied sensor (verify exact accessor in
  `domain_coordinators/presence.py` zone section during build — planner
  did not lock a line yet; leave to builder with a mandatory
  cite-file:line before writing).
- House-tier state — REUSED, `_inference_engine`'s current state
  (already used by D7 emit at presence.py:6577).
- Both must be currently **healthy** (not `unavailable`, not restored
  boot state). Writer skips on any unhealthy read (fail-closed on
  producer, matching the D4–D7 pattern).

**External ground truth for tests:** hand-built fixtures replaying
Investigation-1-shape divergence (zone stays occupied ≥ hold while
house transitions away and stays away).

### Consumer check

**Zero consumers on any actuation path.** Enforced by the same
consumer-graph test as the D4–D7 family (memory_writers.py:31–32
docstring cites `quality/tests/` enforcement — builder to extend the
existing test to cover the new episode_type token).

### Rate-bounding BY CONSTRUCTION

- Kill switch: **NEW** `ZONE_PHANTOM_WRITER_ENABLED` (const.py, module
  constant, rung-1) — REUSED pattern from
  `HOUSE_STATE_TRANSITION_WRITER_ENABLED` etc.
- Hold gate: **NEW** `ZONE_PHANTOM_MIN_HOLD_S` (default `300`, matching
  D5 semantics — sustained divergence, not a race across a house-state
  edge). Rung-1 constant; can promote if operator retunes.
- Edge-only: emits at the transition from "pending-divergence" to
  "held-divergence"; the same divergence does NOT re-emit until the
  divergence CLEARS and re-opens. Same shape as D6 debounce.
- Coalesced close: on divergence clearance, close the open row via
  `close_memory_episode` (REUSED DAO helper D5 uses); OPEN-row boot
  reconcile via the SAME pattern as `reconcile_open_away_block_on_boot`
  — **NEW** helper `reconcile_open_zone_phantom_on_boot` (a ~15-line
  copy-adapt of the D5 boot reconcile).
- `dedup_source_ref=True` with `source_ref =
  "zone_phantom:<zone_slug>:<opened_at_iso>"` to prevent
  boot-replay double-writes.

### Episode-type vocabulary registration

Register `"zone_phantom"` in `MEMORY_FACT_TOPICS` / episode-type
registry (REUSED gate, same location the D4–D7 registrations went;
grep during build). Boot-assert exercised by existing vocabulary-gate
test.

### Numbers-Get-Knobs placement

| Knob | Home | Why |
|---|---|---|
| `ZONE_PHANTOM_WRITER_ENABLED` | const.py (rung-1 module constant) | Kill switch; operator would only flip via reviewed code change. |
| `ZONE_PHANTOM_MIN_HOLD_S` | const.py (rung-1) | Detection shape, not policy the operator turns. Promote to entity ONLY if organic tuning is observed to matter (evidence trigger for revisit). |

### Files touched

- `custom_components/universal_room_automation/memory_writers.py` —
  add `ZonePhantomWriter` class (edge-writer + open/close, ~120 LoC
  patterned on `AwayBlockEpisodeTracker`) and
  `reconcile_open_zone_phantom_on_boot` (~20 LoC).
- `custom_components/universal_room_automation/const.py` — two new
  constants at the `AWAY_BLOCK_EPISODE_*` / `TRACKER_TRUST_*` block
  (lines 3796–3820).
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  — construct writer alongside D5/D6 (near :6079–6100); call
  `observe(...)` in the zone-tier tick hook; call boot reconcile
  alongside D5 boot reconcile (near :2379).
- `quality/tests/test_memory_writers.py` — parallel tests to the
  D4–D7 suite: hold-not-emit / hold-satisfied-emits / clearance-closes
  / hostile-flap-rate-bound / boot-reconcile-closes-open-row /
  consumer-graph-token-added.

**Do NOT touch (out of scope):** any actuation path;
`compaction.py`; any of the shipped D4–D7 writers; any const outside
the two new tokens; kanban.data.yaml (planner does not hand-edit).

---

## 5. Falsifiable invariant

**I1 (zone_phantom writer):** Under any input sequence where the zone
tier reads OCCUPIED while the house tier reads AWAY (or equivalent)
continuously for ≥ `ZONE_PHANTOM_MIN_HOLD_S`, exactly one OPEN
episode row exists in `memory_episodes` with `episode_type =
"zone_phantom"` and `node_id = "zone:<zone_slug>"` at any instant
during the sustained divergence, and it is CLOSED on the first tick
where divergence no longer holds; and NO episode is emitted for
divergences shorter than the hold. Boot with a pre-restart OPEN row
force-closes it with `closed_by="restart"`.

**I2 (memory-ineligible):** No integration code path READS
`episode_type = "zone_phantom"` on an actuation branch. Enforced by
the extended consumer-graph test.

Both invariants must hold at ship. A concrete legal-config repro
for I1 lives in the test suite as the hostile-input drill.

---

## 6. Acceptance criteria

### D1 — zone_phantom writer

- **Verify:** with the writer enabled, replaying an Investigation-1-shape
  divergence fixture (zone occupied, house away, held ≥ 300 s) produces
  exactly ONE OPEN `zone_phantom` row; a sub-hold divergence produces
  ZERO rows.
- **Verify (discriminator):** a 60-flip-per-minute hostile input
  produces AT MOST one row (rate-bound proof, mirroring the D6 drill).
- **Verify (discriminator vs D5):** a house-tier away without zone-tier
  occupied does NOT emit `zone_phantom` (only `away_transition_blocked`
  emits, if D5 predicates hold) — proves the two writers are disjoint
  and neither impersonates the other.
- **Test:** `test_zone_phantom_hold_gate_positive`,
  `test_zone_phantom_hold_gate_negative`,
  `test_zone_phantom_hostile_flap_rate_bound`,
  `test_zone_phantom_close_on_clearance`,
  `test_zone_phantom_boot_reconciles_open_row`,
  `test_zone_phantom_not_consumed_on_actuation_path` (extend
  consumer-graph test).
- **Sensor:** none new — episodes queryable via the existing
  `universal_room_automation.memory_query` service filtered by
  `episode_type="zone_phantom"`; house-level compactor picks it up on
  the next nightly tick once row count crosses the compactor's
  per-type threshold (existing machinery, no build).
- **Live (organic — house-empty testable subset):**
  - L1 (in-suite, deterministic): all D1 tests green.
  - L2 (live, empty-house testable): boot with the writer enabled
    produces ZERO spurious zone_phantom rows during the 24 h after
    deploy (the divergence trigger requires a specific zone/house
    disagreement that does not spontaneously occur when the house is
    empty and steady-state; observing zero rows over 24 h confirms
    the writer is NOT flap-firing).
  - L3 (live, occupancy-dependent — organic): the writer emits an
    OPEN episode on the next real zone-vs-house divergence (e.g. the
    F2 divergence class that motivated the audit). This is
    **occupancy-conditional and cannot be forced in an empty house**;
    validate on the first organic occurrence and write results back
    into `README_v<version>.md` per the CLAUDE.md README-writeback
    rule.

### Adjacent — MEMORY-WRITERS-1 card disposition

- **Verify (docs):** kanban.data.yaml row for MEMORY-WRITERS-1 already
  has `status: shipped_organic` + `folded_2026_08_16` note. Operator
  action: close the row as `done` once L3 lands, or explicitly split
  the zone_phantom follow-up as a child card (recommended:
  `MEMORY-WRITERS-2` — zone-tier coverage). **Planner does not
  hand-edit the kanban; recommendation only.**

---

## 7. Non-goals

- No changes to any shipped D4–D7 writer (no threshold retune, no
  snapshot enrichment — D7 snapshot is already sufficient for the
  guest-FP question per §1).
- No `exterior_track` multi-source hop writer (blocked on Protect
  webhook cycle).
- No new consumer of `zone_phantom` on any actuation, presence, or
  house-state decision path. Memory stays observational (arch §8).
- No new sensor entities; no config-flow additions; no options-flow
  additions.
- No compactor rules for `zone_phantom` in this cycle — compactor
  picks it up automatically at its per-type volume threshold; the
  distillation rule for zone_phantom can be added in a later cycle
  when row volume exists.
- No changes to test infrastructure beyond a parallel test module
  matching the D4–D7 pattern.

---

## 8. Tier classification & review protocol

**Proposed: Tier 2** (feature cycle, additive writer parallel to a
shipped family, memory-ineligible by construction, no
cross-coordinator trust edge, no shared-primitive strategy change).

**Arguments FOR staying at Tier 2:**
- The writer sits on the same fire-and-forget queue as four shipped
  siblings; no new architectural surface.
- Memory-ineligible per arch §8 — cannot regress any actuation path
  by construction (enforced by consumer-graph test).
- No cross-coordinator ripple (writes only into `memory_episodes`,
  read only by the RO facade + compactor).

**Arguments AGAINST (would push to Tier 2-DB):**
- Touches `memory_episodes` table (DB-sensitive per Tier 2-DB
  triggers). Row shape is REUSED (existing schema, new episode_type
  vocabulary token only) → does NOT meet the "changes payload shape
  of a persisted record" trigger; and does NOT migrate ≥3 callers
  to a new DAO. Both hard triggers absent.

**Recommendation: Tier 2, two framing-disjoint reviews:**
- Reviewer A: correctness + edge cases (hold gate math, clearance,
  boot reconcile idempotency, source_ref dedup under boot replay).
- Reviewer B: memory-ineligible enforcement + rate-bounding under
  hostile input (async lifecycle of the writer instance, listener
  cleanup, consumer-graph test extension actually catches a synthetic
  actuation-path reader).

Then Review 3 = live validation (L2 empty-house watch; L3
occupancy-conditional written back into README when it lands).

**Operator may elevate to Tier 2-DB** if desired — the DB touch is a
plausible elevation trigger even though the hard triggers do not fire.
Planner default: Tier 2 with the review-B framing already tuned to
what a third reviewer would look at.

---

## 9. Plan-completion tracking

If the operator agrees with the scope-reset:
- **Deferred / parked with evidence trigger:** exterior_track
  multi-source hop writer — revisit when Protect Alarm Manager face
  webhook cycle ships and a Protect-side per-track timestamp is
  available.
- **Explicitly not built:** duplicate/replacement of any D4–D7 writer
  (justification: shipped and correct).
- **Documentation follow-up:** the epic card
  `MEMORY-PROGRAM-EPIC.next` field on the kanban is stale — it should
  be updated post-cycle to reference the zone-tier follow-up rather
  than the already-shipped top-two writers. Planner recommends;
  operator/orchestrator applies via the kanban tooling.
