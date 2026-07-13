# Wave review record — 2026-07-13 overnight wave (presence batch · zone-prune hotfix · Envoy write-verification)

Combined record for the three cycles whose review stacks completed first.
Sibling docs: `ev_charge_start_deadband_tier3.md` (v5.15.0, shipped);
energy-hygiene + BLE-cancel get their own doc when their stacks close.

---

## Cycle 1 — Presence batch (guest latch + veto gap + edge observability)

**Build** `cd93d169` (tag `pre-review-presence-batch`) · **Fix-up** `f0aa3231` · **Tier 2-DB, 3 framings**
**Plan:** `PLANNING_presence_guest_latch_and_veto_gap.md`

| Severity | Found | Fixed | Notes |
|---|---:|---:|---|
| CRITICAL | 1 | 1 | Triple-confirmed independently by ALL THREE framings |
| HIGH | 2 | 2 | |
| MED | 4 | 3 | B-MED-1 resolved by honesty-correction (doc), not code |
| LOW | 2 | 2 | |

**The CRITICAL (A-CRIT-1 = B-CRIT-1 = C-HIGH-1):** the D2 immediate-engage
limb restated three conjuncts of its enclosing `if`, reducing the OR-group
to always-true — silently deleting the 60-min LOST-away grace AND the
v5.7.0 FIX-2b indoor-clear debounce. Proof triangle: A by precedence
enumeration; C by mutation (whole OR-group → `True` left the full suite
identical); B empirically (two pre-existing behavioral guards pass at
parent, fail at build). **Fix:** the limb now requires
`sustained_external_empty` (N=3 consecutive ticks of census==0 ∧ unid==0 ∧
debounced-indoor-clear, reusing `CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`) —
empty house engages in ~30-60s, single-tick sensor flakes structurally
cannot. Regression proof: both `test_n1_1_behavioral_*` guards pass again;
tautology-revert mutation red ×3 (re-run independently by the orchestrator:
red ×3, byte-identical restore).

Also fixed: Pattern E stale-epoch on mid-persistence guest re-arm
(A-MED-1); false zero-new-failures claim from test sys.modules pollution
(B-HIGH-1 — resolved jointly with the zone fix-up; pairing verified 30/30
by orchestrator); grace mutation authority restored (B-HIGH-2/C-MED-2);
mutation-record corrections (C-MED-1). **Honesty correction (B-MED-1):**
D2 does NOT kill an indoor-blip flap cycle — the 2026-07-12 flap's real
killer was the operator's config removal of the noisy sensor; AWAY-hold
suppression backlogged.

**New bug-class candidate:** *"Guard conjunct restated from enclosing
scope"* — a predicate limb that re-asserts conditions its outer clause
already guarantees is vacuous; reviewers should reduce every new limb
against its enclosing context. (Sibling of #53.)

---

## Cycle 2 — Zone-prune hotfix (name-collision guard + mint guard + dispatch snapshot)

**Build** `bd6ceff4` · **Fix-up** `fb103b8e` · **Tier 2, 2 framings**
**Plan:** `PLANNING_zone_delete_prune_name_collision.md`

| Severity | Found | Fixed | Notes |
|---|---:|---:|---|
| CRITICAL | 1 | 1 | Dead code invisible to every runnable test |
| HIGH | 3 | 3 | Incl. one pre-existing, deliberately activated |
| MED | 3 | 3 | |
| LOW | 3 | 2 | A-LOW-2 documented tradeoff |

**The CRITICAL (A-CRIT-1):** the D1 guard — the actual incident fix —
imported `CONF_ZONE_THERMOSTAT` from the wrong module; the ImportError was
swallowed at DEBUG, the survivor set stayed empty, and the prune proceeded
exactly as in the 2026-07-12 incident. The build's source-string grep
"anchors" stayed green throughout — the existence proof that string
anchors do not meet the tier bar. **Fix:** import corrected; guard logic
extracted to pure module-level helpers with 14 runnable behavioral tests
(incident scenario, solo-prune negative, import smoke test); mutation M1
(revert import) red ×5.

**Deliberate activation (B-HIGH-2, pre-existing):** `_resolve_zone_id_for_delete`
read the never-populated `hass.data[DOMAIN]["hvac_coordinator"]` slot —
every live delete resolved `(None, …)`, making D3 a live no-op and
aborting thermostat-carrying deletes (and retro-explaining the 2026-07-12
live delete's husk-path resolution). Fixed via the canonical
CoordinatorManager lookup; id-keyed purge + D3 snapshot now genuinely
active, safe behind the working D1 guard. Same dead-slot fix applied to
D2's P1 predicate (A-HIGH-1/B-HIGH-1). Guard sets fold legacy
ENTRY_TYPE_ZONE + ZM-embedded (A-HIGH-2). Failure direction inverted to
WARNING + spare-on-unknown (A-MED-1) — a wrong prune costs hours of inert
HVAC; a wrong spare costs nothing.

**Bug-class recurrences:** dead `hass.data` slot (documented class,
2 more sites found); source-string test anchors as false authority
(Bug Class #60 family).

---

## Cycle 3 — Envoy write-verification + redundancy (tripwire · SOC fallback · dormant failover)

**Build** `bca23cad` · **Fix-up** `1a4bd11e` · **Tier 2-DB, 3 framings**
**Plan:** `PLANNING_envoy_write_verification_and_redundancy.md`

| Severity | Found | Fixed | Notes |
|---|---:|---:|---|
| CRITICAL | 1 | 1 | Config section never flattened (Bug Class #55) |
| HIGH | 6 | 6 | A/B convergent ×2 + 4 distinct |
| MED | 7 | 7 | |
| LOW | 4 | 4 | |

**The CRITICAL (C-CRIT-1):** the `cloud_verification` options section was
never flattened at submit — all four operator-configurable oracle fields
were write-only; only hard-wired defaults could ever function, and the
blank-to-disable path was unreachable. Fixed via the
INCLEMENT_ADVANCED_SECTION pop/merge pattern + explicit-empty-disables
semantics + saved-value redisplay, anchored by a round-trip test.

**HIGH cluster (trustworthy-alerting integrity):** no supersession → stale
15-min check vs newer command = routine false CRITICAL NM that then
day-latch-masks real alerts (A-H1=B-H1; fixed: per-surface pending-handle
cancel-on-reschedule + ledger-timestamp belt); ledger stamped with desired
not commanded value + deadband/tolerance gap = standing false REVERTED
(A-H2=B-H2; fixed at the dispatch tap — **residual two-writer overwrite
found by orchestrator verification and closed in the energy-hygiene
cycle**, see its doc); Bug Class #38 untracked timers (B-H3; fixed:
tracked handles + cancel_all in teardown); cloud SOC fallback tier
unit-unguarded at consumption — a fraction-scaled cloud sensor would feed
SOC≈0.7 into every gate exactly when the primary is dead (A-H3; fixed:
normalize + None on non-%; units-vigilance directive validated twice this
wave); ledger production site and coordinator wiring layer had zero test
authority (C-H1/C-H2; fixed with real construction/wiring tests — 10/10
mutations red post-fix-up).

**Also:** reversion anomalies now emit on TRANSITION (not per-window ~96
rows/day — write-flood history); NM latch split per (surface, alert_type);
verifier-never-actuates (W-6) verified end-to-end; D3 failover confirmed
fully dormant.

---

## Wave process findings (feed QUALITY_CONTEXT / protocol)

1. **Framing-disjoint reviews caught 3 CRITICALs + ~14 HIGHs post-build in
   this wave alone**; every CRITICAL was invisible to (or actively masked
   from) the builder's own green suite.
2. **Concurrent builders in one checkout is now a proven incident class**
   (BLE-cancel: tree-contention recovery silently dropped two committed-
   claimed hunks → would-have-shipped census crash, v5.8.0 pattern).
   Standing change: parallel builders get worktree isolation.
3. **Builders claiming unexecuted mutation anchors** recurred (2 of 5
   builds); the "RUN your mutations yourself and report" instruction is
   now standard in build prompts, and reviews re-execute regardless.
4. Bug-class candidates for QUALITY_CONTEXT.md: "guard conjunct restated
   from enclosing scope (vacuous limb)"; "edge-triggered resume vs
   level-triggered ensure-on" (L1 plug incident, operator-coined pattern:
   stops are diligent, starts are lazy).
