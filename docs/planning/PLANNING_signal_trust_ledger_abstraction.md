# PLANNING: SignalTrustLedger Abstraction Cycle (DESIGN-AHEAD, BUILD-GATED)

**Author date:** 2026-07-28.
**Version target:** un-numbered — build gated (see next block).
**Tier proposal:** **Tier 3** (four framing-disjoint reviews, incl. adversarial-completeness D). See Tier Classification.

---

## STATUS: BUILD GATED — DO NOT IMPLEMENT YET

> **This is a design-ahead plan.** No code is to be written under this cycle until BOTH of the following hold:
>
> 1. The **stuck-signal watchdog cycle** (`docs/planning/PLANNING_stuck_signal_watchdog.md`, deliverables D1/D2/D3/D4) has **shipped, live-validated, and lived-in for ≥ 2 weeks with its `Validated <date>` table in the README carrying real observed evidence** — OR a new stuck-signal incident class has appeared in the interim that the concrete watchdog demonstrably misses (documented incident memo required, cited here at revive-time).
> 2. Operator explicit go to elevate abstraction from design-parked to build-scheduled.
>
> Rationale (fan DOC-2 precedent + 2026-07-14 Marginal-Benefit Decomposition rule): a concrete detector shipped and observed in production is the ONLY authoritative fixture set for a behavior-frozen extraction. Abstracting before the watchdog is proven risks freezing the WRONG shape (the shape D4 wired to NM may differ from what the ledger surface wants). We record the design now to (a) prevent P14 from being deleted before we decide to promote it, and (b) keep the abstraction ambition from silently drifting while attention is on the concrete cycle.
>
> **If this cycle is ever cancelled, P14 (per-zone BLE-tier weighted veto, `presence.py:4815-4970`) gets deleted instead** — it is currently vestigial (Pattern F unhandled per v4.7.16 README §7), and it exists on disk exclusively to be PROMOTED here.

---

## Falsifiable invariant (stated up front — reviewer D's job is to break it)

> **Every migrated call site produces a byte-identical verdict to its pre-migration logic on the golden fixture set. No detection site in the "asserted-too-long ⇒ demand corroboration ⇒ act" family bypasses the ledger. The ledger owns detection verdicts only; every action stays at the call site that owned it before migration.**

Operationally the cycle must guarantee, under any legal per-room / per-zone / per-person config:

1. For every migrated site (P22, P24, P18, D1, D2, D3, promoted P14), and for every input in the pre-cycle golden fixture set captured under the concrete watchdog's live traffic, `ledger.verdict(...)` returns a value that maps 1:1 to the pre-migration outcome. Divergences MUST be zero, not "small".
2. No site in that family calls its own private stuck/duty-cycle/freshness/weighted-veto arithmetic post-cycle — every such site routes through `SignalTrustLedger`. Reviewer C proves this per-site via real source mutation (neuter the ledger call at ONE site → a specific test must fail; restore).
3. The ledger EMITS verdicts + evidence and reuses the ONE NM hook (X21 dedup-latch, established by watchdog D4). It NEVER actuates (does not force-vacant, does not exclude sensors, does not veto GUEST) — those remain at the call sites, which read `verdict.reason` and `verdict.evidence` and act as they did before.

Reviewer D re-enumerates the ENTIRE family surface — including pre-existing code, not just this diff — and provides a concrete legal-config reachable repro for any leak.

---

## Institutional context verified

**Adjudicator docs (both authoritative — this cycle does NOT re-litigate their verdicts):**
- `docs/planning/CATALOG_cross_correlation_primitives.md` — ~70 primitives, HEAD-verified at v5.34.1. Names the "asserted-too-long ⇒ demand corroboration ⇒ act" family and its members.
- `docs/planning/PLANNING_stuck_signal_watchdog.md` — concrete detector cycle (D1 census stuck-count, D2 duty-cycle Fix #9 variant, D3 frozen-tracker, D4 NM surface for P22/P24/P18/X7). Defines the shape this abstraction extracts.
- `docs/planning/PLANNING_v4.7.16_room_level_veto_density_weighting.md` + `docs/readmes/README_v4.7.16.md` §7 — Pattern F (`room_level_weighted`) was DESIGNED and INTENTIONALLY left unhandled in v4.7.16's shared veto helper; P14 is the vestigial diagnostic-only artifact awaiting either promotion (here) or deletion.

**Prior successful-abstraction precedents (this cycle follows their recipe):**
- **v5.30.0 owner-set registry** — behavior-frozen extraction via golden-parity oracle: capture pre-cycle inputs+outputs, then reject any diff. Method reused verbatim here.
- **v4.7.15 universal veto helper (Bug Class #48 sprint)** — shared helper with Patterns A-E; Pattern F left unimplemented as vestigial hook. Precedent for shipping a helper with a documented "future pattern slot" and it staying honest.
- **LkgValue (`lkg.py:47-79`)** — freshness-as-byproduct discipline: consumers receive `envelope()` returning value + tier in ONE call; no forgettable `is_stale()` predicate that a consumer can drift past. This cycle applies the same discipline: `ledger.verdict(...)` returns verdict + evidence in ONE call; no `is_stuck(signal_key)` predicate is exposed.

**Code locations surveyed end-to-end during scoping (must be re-read at build-revive time in case HEAD drifted):**
- `custom_components/universal_room_automation/coordinator.py` — P22 Fix #9 (`_stuck_sensor_hours`, :1502-1543), P24 RESILIENCE-001 (:1690-1754). Both are the archetypal "asserted-too-long ⇒ corroborate ⇒ act" shape.
- `custom_components/universal_room_automation/domain_coordinators/hvac.py:1253-1303` + `.../presence.py:1838-1940` — P18 zone stale-occupancy failsafe (the multi-source-corroboration exemplar).
- `custom_components/universal_room_automation/domain_coordinators/presence.py:4815-4970` — P14 vestigial per-zone BLE-tier weighted veto (Pattern F). To be PROMOTED as the ledger's `defer_to_consensus` verdict path for zone-scoped consumers.
- `custom_components/universal_room_automation/camera_census.py:1114-2221` — where watchdog D1 will land; the ledger will absorb its per-camera stuck-count logic post-watchdog.
- `custom_components/universal_room_automation/person_coordinator.py:123-435` — C11 tracking_status; watchdog D3 (frozen-tracker) lands here; ledger will consume the SAME anchor.
- `custom_components/universal_room_automation/domain_coordinators/_nm_cycle_a.py` — X21 per-(surface,type)/day latch. The ledger reuses this hook via the same helper the watchdog D4 registers (`stuck_signal` notification type). ONE hook, not new plumbing.
- `custom_components/universal_room_automation/lkg.py` — the `envelope()` API is the shape prototype for `verdict()`.

**Prior planning docs consulted (skim + relevant excerpts):**
- `docs/planning/PLANNING_v4.7.16_room_level_veto_density_weighting.md` §0 (institutional-context probe) — establishes `CONF_SCANNER_AREAS`/`is_direct_ble_room` as the room-to-BLE-tier map the promoted P14 must read; no new field needed.
- `docs/planning/PLANNING_stuck_signal_watchdog.md` §D1..D4 — the exact call-site shapes the ledger must reproduce byte-identical.
- `docs/planning/PLANNING_presence_pair_guest_latch_veto_gap.md` — GUEST-derivation must not regress; ledger discounts inputs, never derives GUEST.
- `docs/planning/CATALOG_cross_correlation_primitives.md` — full body, not just index.

**Memory bodies pulled:**
- `project_session_pickup_2026_07_20.md` (current session shipped state).
- `project_presence_guest_latch_and_veto_gap.md` (GUEST regression risk anchor).

**Design docs read (if present at revive time):** `docs/Coordinator/presence.md`, `docs/Coordinator/camera_census.md`, `docs/Coordinator/hvac.md`.

### Greps run — REUSED / NEW table

| Proposed symbol | Grep target | Result |
|---|---|---|
| `SignalTrustLedger` class | `TrustLedger`, `SignalTrust`, `Ledger` in `custom_components/universal_room_automation/**` | NEW — no existing type occupies this name. Nearest sibling: `LkgValue` (value-envelope axis, not detection-verdict axis). |
| `verdict(signal_key, ...)` API | grep `def verdict`, `.verdict(` | NEW — LkgValue uses `envelope()`, no `verdict()` on any class today. |
| `RoomSignal(room, tier, weight, source_kind)` dataclass | grep `RoomSignal`, `room_signal` | NEW — but the fields all exist as loose parameters at P14's Pattern-F design site (`presence.py:4815-4970`). This dataclass FORMALIZES that shape; not invention. |
| `corroborator_spec` | grep `corroborator`, `corroboration` | NEW naming; REUSED semantics — P12 `signal_consensus` (presence.py:5786-5839) + P13 tally (:5650-5687) are the interior-corroboration source of truth. Ledger CONSUMES; does not re-implement. |
| Per-signal assert-duration book | grep `_sensor_on_since`, `_stuck_sensor_hours` in `coordinator.py` | REUSED (Fix #9 book at :193 is the exemplar). Ledger's per-signal book is a generalization of that dict-keyed-by-entity-id pattern; migration lifts it into the ledger and P22 reads back through the ledger. |
| Per-signal duty-cycle ring | grep `dutycycle`, `on_ratio` | NEW (matches watchdog D2's ring). Post-watchdog the ring lives ONCE inside the ledger; D2's ring is migrated in. |
| NM hook | grep `_nm_cycle_a`, `nm_type=` | REUSED — the watchdog D4 registers `stuck_signal` notification type + `kind` subclassification. Ledger emits via that exact type; NO new NM type. |
| `defer_to_consensus` verdict | grep `defer`, `weighted_veto` | NEW verdict enum member; REUSED semantics — this is the vestigial P14 max-aggregation ("strong evidence dominates") from v4.7.16 review A1, promoted into the enum. |
| `is_stuck(signal_key)` predicate | forbid — grep to prove absent post-cycle | Forbidden by design (LkgValue lesson). Reviewer C proves absence. |

Any "NEW" the reviewer surfaces prior art for at revive time → drop and reuse.

---

## Design principles (ratified 2026-07-28 — this cycle MUST encode them)

1. **Extraction, not invention.** Every ledger behavior maps to an existing site's pre-cycle behavior on a golden fixture. If a proposed ledger capability has no pre-cycle site, it does NOT ship in this cycle — it becomes a follow-up. This is the v5.30.0 owner-set-registry recipe.

2. **Detection verdicts only; actions stay at call sites.** The ledger returns `verdict = {trusted | suspect(reason) | stuck(reason) | defer_to_consensus(reason)}` + `evidence` (dict of what corroborated / failed to corroborate). It does NOT exclude sensors, does NOT force-vacant, does NOT veto GUEST, does NOT emit NM directly — it exposes an emit hook that call sites (or a thin ledger-owned wrapper reusing the X21 latch established by watchdog D4) invoke.

3. **LkgValue freshness-as-byproduct discipline.** `verdict()` returns verdict + evidence in ONE call. No `is_stuck(signal_key)` / `is_suspect(signal_key)` predicate is exposed to consumers, because a forgettable predicate is exactly how consumers drift.

4. **ONE grand TrustEngine is rejected.** Explicit non-absorption list (see next section). The ledger owns exactly one axis: **detection verdicts on the "asserted-too-long ⇒ demand corroboration ⇒ act" family.** State-machine × time × cross-coordinator seams are the two worst historical bug families (2026-07-14 note); do not build a seam that lives on both.

5. **P14 is PROMOTED, not preserved-in-parallel.** Pattern F becomes the ledger's `defer_to_consensus` verdict, with `RoomSignal(room, tier, weight, source_kind)` as the formal input dataclass and max-aggregation ("strong evidence dominates") as the aggregation rule. If this cycle is cancelled, P14 is deleted (recorded above in STATUS block).

6. **Numbers get knobs (2026-07-16 rule).** No inline literals. See per-deliverable knob tables.

---

## Explicit non-absorption list (do NOT absorb into this cycle)

The ledger's axis is *detection verdicts on stuck / duty-cycle / weighted-veto signals.* The following live on DIFFERENT axes and remain independent — attempting to absorb any of them collapses this cycle into a grand-TrustEngine anti-goal:

| Primitive | Axis it lives on | Why not absorbed |
|---|---|---|
| `LkgValue` (X1, `lkg.py:47-79`) | value-bounding (physics envelope on numeric values) | Different axis (bound a value, not verdict a detection). Ledger MAY consume LkgValue tier as an evidence field; must not re-implement bounding. |
| `WriteVerifier` (X4, `energy_write_verify.py`) | commanded-vs-oracle echo verification | Different axis (commanded state, not asserted signal). |
| P12 `signal_consensus` arithmetic (presence.py:5786-5839) | scoring (weighted delta sum) | Ledger CONSUMES the published consensus + P13 tally as one corroborator input. Does NOT re-compute consensus. |
| Dedup / fusion / z-score machinery (camera_census C1-C5, various z-score sites) | multi-source combine / statistical anomaly | Different axes; ledger operates DOWNSTREAM of fusion (on the fused signal's assertion duration). |
| Behavioral conduct check (X5) | commanded-vs-conduct | Different axis (write-verify family). |

If a reviewer proposes to fold any of these in, the response is: separate cycle, and only if a lived-in incident demonstrates the axes converge.

---

## Core surface (sketch — subject to build-time refinement)

```python
# custom_components/universal_room_automation/signal_trust_ledger.py  (NEW)

class VerdictKind(StrEnum):
    TRUSTED = "trusted"
    SUSPECT = "suspect"
    STUCK = "stuck"
    DEFER_TO_CONSENSUS = "defer_to_consensus"

@dataclass(frozen=True)
class Verdict:
    kind: VerdictKind
    reason: str | None                # machine-readable reason code
    evidence: Mapping[str, Any]       # what corroborated / failed to corroborate

@dataclass(frozen=True)
class RoomSignal:                     # promoted from vestigial P14 Pattern F
    room: str
    tier: int                         # 1/2/3 signal-class tier (mmwave-PIR / camera / BLE)
    weight: float
    source_kind: str                  # 'mmwave' | 'pir' | 'camera' | 'ble' | ...

@dataclass(frozen=True)
class CorroboratorSpec:
    # declarative; ledger reads P12/P13 outputs by these keys, not by reaching into presence internals
    interior_tiers_required: int      # default 1 (matches watchdog D1)
    require_pir_transition: bool      # default False (D2 sets True for PIR-flap check)
    scope: Literal["room", "zone", "house"]

class SignalTrustLedger:
    def register(self, signal_key: str, tier: int, spec: CorroboratorSpec) -> None: ...
    def observe(self, signal_key: str, *, value: Any, ts: float) -> None: ...       # tick input
    def verdict(self, signal_key: str, *, now: float) -> Verdict: ...                # tick output
    def verdict_weighted(self, signals: Sequence[RoomSignal], *, now: float) -> Verdict:
        """Max-aggregation ('strong evidence dominates'); returns defer_to_consensus for zone-scoped consumers."""
```

**No `is_stuck()` / `is_suspect()` predicates.** Consumers call `verdict()` and read the tagged union.

---

## Migration table — every call site + its pre-migration anchor + parity method

| # | Site | File:line (pre-cycle anchor) | Pre-migration behavior anchor | Parity method |
|---|---|---|---|---|
| M1 | **P22** Fix #9 stuck-sensor exclusion | `coordinator.py:1502-1543` | Continuously-on ≥ `_stuck_sensor_hours` (4h) → EXCLUDE + WARN | Golden fixture set = tick stream from live P22 book at watchdog-live time; migrated site calls `ledger.verdict(...)`; verdict.kind==STUCK → EXCLUDE + WARN identically. Byte-identical exclusion set required. |
| M2 | **P24** RESILIENCE-001 max-active failsafe (+ Tier-1 freshness skip) | `coordinator.py:1690-1754` | Occupied > failsafe (60min closet/bath, 4h else) → if Tier-1 fresh (<2× timeout) skip; else force vacant | Golden fixture from live P24 firings during watchdog live period. Verdict TRUSTED → skip; STUCK → force vacant. The Tier-1-fresh SKIP is encoded in `CorroboratorSpec.interior_tiers_required=1` with Tier-1 counted. |
| M3 | **P18** Zone stale-occupancy failsafe | `hvac.py:1253-1303` + `presence.py:1838-1940` | Occupied > max_occupancy_hours → demand ≥min(2, possible) of {recent motion<1800s, BLE, camera, ≥2 rooms} → confirm-and-reset OR force away + sweep; sleep-skipped | Golden fixture set = pre-cycle triggers from real house. `CorroboratorSpec` encodes the min(2,possible) rule; sleep-skip stays at call site (state-machine concern). |
| M4 | **Watchdog D1** Census-layer per-camera stuck-count | `camera_census.py` (post-watchdog) | Continuous-count assertion window OR duty-cycle assertion window > `CONF_STUCK_CAMERA_HOURS` with zero interior corroboration → discount from `fresh` + NM | Golden fixture = the watchdog's own live-validated evidence (recorded in the watchdog's README `Validated <date>` table). Migrated site calls `ledger.verdict(...)` and does the SAME discount at the SAME position in tick order. |
| M5 | **Watchdog D2** Fix #9 duty-cycle variant | `coordinator.py` (post-watchdog) | Ring-buffer on-ratio > `CONF_STUCK_SENSOR_DUTYCYCLE_PCT` in window + no PIR transitions → classify stuck | Ring moves INTO ledger; D2 site becomes `ledger.verdict(...)` call. Warm-up floor (`MIN_TICKS`) enforced by ledger, tested identically. |
| M6 | **Watchdog D3** Frozen-tracker check | `person_coordinator.py` (post-watchdog) | `device_tracker.last_updated` age ≥ `CONF_FROZEN_TRACKER_DAYS` + other evidence disagrees → NM (no auto-prune) | Verdict SUSPECT with `evidence={disagreeing_evidence: [...]}`. No auto-prune retained. |
| M7 | **P14 PROMOTION** per-zone BLE-tier weighted veto (was vestigial Pattern F) | `presence.py:4815-4970` (deleted post-cycle) | Currently diagnostic-only. Designed rule: max-aggregation on `RoomSignal(room, tier, weight, source_kind)` → verdict `{accept | veto | defer_to_consensus}` (v4.7.16 review A1 "strong evidence dominates") | Golden fixture = a SYNTHESIZED set (P14 is diagnostic-only so no live behavior exists to freeze). Fixture set MUST be reviewed by operator + reviewer A before ledger implementation begins. This is the ONLY site without a lived-in oracle; it is called out as such and gets the most reviewer-D attention. |

**Per-site mutation-anchored test (Tier 3 framing C — MANDATORY).** For every row above, reviewer C must:
1. Edit production source at that site to bypass/neuter the `ledger.verdict(...)` call (return a hard-coded verdict).
2. Run the full pytest suite.
3. Confirm a SPECIFIC named test fails.
4. Restore.

A site whose bypass leaves the suite green is an untested site → unacceptable. A global monkeypatch of `SignalTrustLedger.verdict` is NOT a substitute (it proves the class is load-bearing in aggregate; it does NOT prove each site routes through it — the exact Bug Class #53 shape).

---

## Golden-parity oracle harness (build-first deliverable)

Before ANY migration, D0 builds the oracle harness (v5.30.0 recipe):

- **Capture.** During the ≥2-week watchdog live-in, add a lightweight tap at each of M1..M6's decision points logging `(inputs, outputs, timestamp)` to a rolling per-site JSONL under `.storage/ura_ledger_golden/`. Tap is REMOVED at build close (it exists only to seed the fixture).
- **Freeze.** At build-start, dump the JSONL to `quality/tests/fixtures/signal_trust_ledger/<site>.golden.jsonl`. This IS the acceptance fixture.
- **Parity oracle test.** `test_ledger_parity_<site>` replays each fixture row through both the pre-migration function (kept alive as `_legacy_<site>_verdict` for the duration of this cycle) AND `ledger.verdict(...)`. Fails on ANY divergence.
- **Post-migration.** `_legacy_*` shims are deleted only after the cycle's readme-writeback confirms live parity for ≥ 1 week.

M7 (P14) has no live oracle — its fixture is HAND-BUILT and operator-approved (per the "hand-build the fixture before automating" rule).

---

## Tier classification — Tier 3 (four framing-disjoint reviews)

**Why Tier 3, not Tier 2-DB:**
- Shared primitive consumed by 7 detection sites. Bug Class #53 "computed-but-not-consumed" / one-missed-site is the archetypal failure mode. Three converging framings can still miss ONE unmigrated site (this is exactly the v5.5.3 arbitrage precedent that coined Tier 3).
- Trust-hierarchy ripple: verdict changes propagate to exclusion, failsafe force-vacant, zone force-away, census fresh floor — spanning coordinator/presence/hvac/census/person surfaces.
- Cost + safety impact via P24/P18 paths (bad verdict → wrong occupancy → wrong HVAC).

**The four framings (D must be adversarial-completeness):**

- **A — Local correctness.** Per-verdict arithmetic; `CorroboratorSpec` semantics; `RoomSignal` weight math; max-aggregation "strong evidence dominates" per v4.7.16 review A1; edge cases (empty corroborator set, all-tier-1 rooms, all-BLE-only rooms, warmup floors).
- **B — Integration / state-machine integrity.** No suppression of legitimate exclusions/failsafes; no double-emit against watchdog D4's NM latch; byte-identical on the no-op path; restart behavior (in-memory ledger book cold on boot — is that the intended behavior? verify against P22's own boot behavior); tick-order preserved (D1 must still discount BEFORE C7 captures peak — same constraint as watchdog).
- **C — Test authority via REAL per-site source mutation.** Per the migration table above. Global monkeypatch is NOT acceptable. Reviewer C reports one row per site: `<site>: mutation caused <test_name> to fail — PASS` or `<site>: mutation left suite green — FAIL (site not routed through ledger)`.
- **D — Adversarial completeness / diff-blind.** Sole job: falsify the invariant stated at the top. D re-enumerates the ENTIRE "asserted-too-long ⇒ corroborate ⇒ act" surface — INCLUDING pre-existing sites the plan did not enumerate (a P14-parallel might exist in `aggregation.py` or `zone_presence.py`). Every flagged leak comes with a concrete legal-config reachable repro (values + state that trigger). Runs in parallel with A/B/C.

**Additional Tier-3 stringency (per CLAUDE.md):**
- Falsifiable invariant stated up front (done above).
- Config-boundary / combinatorial testing across `interior_tiers_required` × `require_pir_transition` × `scope` × per-room `CONF_SCANNER_AREAS` presence/absence.
- Orchestrator independent verification BEFORE ship: personally re-grep for `is_stuck(`, `_stuck_sensor_hours` accesses outside the ledger module, and any per-site duty-cycle ring surviving migration. Re-run one mutation-anchored test per site.
- Operator checkpoint BEFORE deploy (not just before build).
- If any pass finds CRITICAL/HIGH: fix, re-verify with the site's mutation-anchored test, AND re-run D's completeness enumeration (fixes can reveal N+1th sites).

---

## Rough size estimate

- **New module:** `signal_trust_ledger.py` — ~350-450 LOC (dataclasses, book, ring, verdict engine, weighted-verdict path).
- **Migration edits:** 7 sites × ~10-20 LOC net delta each ≈ ~100 LOC.
- **Golden-parity harness + fixtures:** ~150 LOC scaffold + generated fixtures (KB-scale).
- **Tests:** ~15 parity tests + ~10 per-site mutation-anchored tests + ~8 edge/boundary tests ≈ ~700-900 LOC.
- **Deletions:** P14 site (`presence.py:4815-4970`, ~150 LOC), any private stuck-book kept by legacy sites post-verify (~50 LOC).
- **Const additions:** small — most existing knobs (`CONF_STUCK_CAMERA_HOURS`, `CONF_STUCK_SENSOR_DUTYCYCLE_*`, `CONF_FROZEN_TRACKER_DAYS`) are REUSED from the watchdog cycle.

**Estimated total:** ~1200-1500 LOC net across ~10 files. Genuinely a Tier-3-sized cycle; do not attempt as a hotfix.

---

## Numbers-get-knobs — new constants introduced by THIS cycle

Most knobs are reused from the watchdog. New here:

| Knob | Rung | Default | Rationale |
|---|---|---|---|
| `LEDGER_WEIGHTED_AGGREGATION` | 1 (module const) | `"max"` | Aggregation rule for `verdict_weighted`. Enum: `"max"` (v4.7.16 A1 "strong evidence dominates") \| `"sum"` (rejected today; kept as an escape hatch requiring code review). |
| `LEDGER_DEFER_TO_CONSENSUS_MIN_TIER` | 1 (module const) | `2` | Signals below this tier cannot trigger `defer_to_consensus` (avoids a single BLE ping becoming a defer). |
| `LEDGER_GOLDEN_TAP_ENABLED` | 2 (options-flow) | `False` in production, `True` during watchdog live-in and this cycle's oracle capture | Kill-switch for the tap that writes `.storage/ura_ledger_golden/`. Turned OFF post-cycle. |

Rung reasoning per the 2026-07-16 ladder: aggregation rule and tier floor are safety-boundary numbers (operator legitimately never turns them; changing them affects verdicts across the family → require review). The tap enable is operator-legit-tunable (dashboard-visible so operator knows recording is active) but not a live-tunable behavioral knob.

**No entity-rung (Number/Select/Switch) knobs.** This cycle exposes zero live-tunable behavioral values — verdicts are policy the operator does not tune by observation.

---

## GO CRITERIA (build-gate — enforced by orchestrator at revive time)

Mirroring the fan DOC-2 pattern:

1. **Watchdog cycle SHIPPED.** `docs/planning/PLANNING_stuck_signal_watchdog.md` D1..D4 all in a tagged release.
2. **Watchdog LIVE-VALIDATED.** README carries the `Validated <date>` results table with real evidence, not prospective bullets.
3. **Lived-in ≥ 2 weeks** with no rollback and no follow-up fix-up cycle in that window OR
   **new stuck-signal incident class appeared** in the interim that the concrete watchdog demonstrably misses (documented incident memo cited here at revive-time).
4. **Golden-tap data collected** for ≥ 2 weeks under `LEDGER_GOLDEN_TAP_ENABLED=True`, capturing at least: 5+ P22 firings, 5+ P24 firings, 3+ P18 firings, 3+ D1 discounts, 3+ D2 classifications, 1+ D3 emit. (M7/P14 excepted — hand-built fixture.) If any bucket is short, extend live-in until it fills or accept a hand-built supplement with operator sign-off.
5. **Operator explicit GO.** Not implicit from "watchdog is fine". This is a Tier-3 shared-primitive cycle; the operator's Marginal-Benefit Decomposition applies: the MARGIN of the abstraction over the concrete watchdog is *maintainability + P14 disposition + one N+1th similar site becoming cheap*. If those margins do not clearly pay for the Tier-3 review cost + the shared-primitive ripple risk, park indefinitely and delete P14 instead.

---

## Follow-ups explicitly parked (not this cycle)

- **Absorb watchdog D4's NM registration into ledger.** Kept at watchdog scope in v1; ledger reuses the type. If a future site wants a different type, revisit.
- **LkgValue integration as an evidence field.** Ledger `evidence` dict may carry `{lkg_tier: "bounded"}` if it turns out useful — deferred until a consumer asks.
- **Zone-tier aggregations beyond P14.** If a second weighted-veto shape appears, add to `RoomSignal` axis; do not fork.
- **Absorb C7 peak-hold state machine.** Explicitly rejected today — it's a fusion/state-machine axis, not the ledger's axis.

---

## Live validation write-back (mandatory per CLAUDE.md)

At build close, `docs/readmes/README_v<version>.md` gets a `Validated <date>` table with one row per migrated site:
- `M1..M7: parity oracle GREEN over <N> fixture rows over <period>; mutation-anchored test <test_name> FAILs on bypass, PASSes on restore.`
- Plus a "post-restart soak" row: 1 week of live operation with zero divergence between `_legacy_<site>_verdict` shims (kept alive for the soak) and `ledger.verdict()`. Shims deleted after the writeback confirms.

Cycle does not close until the README carries the post-restart parity table.

---

## Addendum 2026-08-09 — gate state audited; a new prerequisite lands ahead of this cycle

**Gate state (verified, not assumed):**

| # | Criterion | Status |
|---|---|---|
| 1 | Watchdog D1–D4 in a tagged release | ✅ v5.35.0 (2026-07-28) |
| 2 | README `Validated <date>` table with real evidence | ✅ Validated 2026-07-28, H1/H3 PASS |
| 3 | Lived-in ≥2wk, no rollback/fix-up **OR** new missed incident class | ⚠️ **first leg failed** — v5.35.1 hotfix + v5.35.2 landed inside the window. Second leg **fires**: chatter (transition-rate) evades both shipped rules. Requires the incident memo this criterion demands. |
| 4 | Golden-tap fixtures ≥2wk under `LEDGER_GOLDEN_TAP_ENABLED` | ❌ **the constant and the module were never created — zero fixtures.** The tap was to run *during* the live-in window; that window passed untapped. |
| 5 | Operator explicit GO | ❌ pending |

**Criterion 4 is the hard blocker.** This cycle cannot be built to its own parity standard without
either re-opening a tapped live-in window or accepting hand-built fixtures with operator sign-off.
Recommendation: enable the tap during the chatter/reliability cycle so fixtures accumulate as a
byproduct rather than needing a dedicated window.

**Principle 1 ("Extraction, not invention") binds a specific proposal.** Chatter / transition-rate
detection has **no pre-cycle site**, so it must NOT enter via this cycle. It ships concretely first
(extending `_detect_duty_cycle_stuck`), lives long enough to produce an oracle, then migrates as an
extension of M5.

**New prerequisite: SENSOR-CAPABILITY-1.** This design already assumed a richer kind vocabulary than
production has — `RoomSignal(..., source_kind: str  # 'mmwave' | 'pir' | 'camera' | 'ble')` — but
`occupancy_substrate.py:81` maps kind 1:1 onto the three CONF buckets (`_KIND_TO_CONF`), so 'ble' and
'camera' are not expressible as source kinds today. Separating capability from role is therefore a
prerequisite for M7/`verdict_weighted` as specified, not a nice-to-have. See
`AUDIT_mmwave_only_rooms_2026-07-31.md` Finding 6.

**P14 disposition unchanged:** still preserved solely for promotion here; still deleted if this cycle
is cancelled.

---

### Criterion 3 — SATISFIED 2026-08-09 (second leg)

First leg **failed at origin**: it required ≥2 weeks lived-in with no fix-up, but v5.35.1 and v5.35.2
both landed the same night as v5.35.0. Second leg fires: see
`docs/planning/INCIDENT_chatter_class_missed_by_watchdog_2026-08-09.md` — the chatter
(transition-rate) class evades both shipped rules (off-ticks reset P22's clock; ~50% duty never
reaches D2's 85%), measured at Garage B 3,769 off / 3,765 on in 24h, with a chattering PIR able to
*shield* a stuck mmWave because it satisfies D2's corroboration test.

Criteria 1, 2, 3 now met. **Open: 4 (fixtures — see `AUDIT_ledger_golden_fixture_yield.md`) and
5 (operator GO).**
