# URA v5.76.0 — Memory Compactor (Stage 2) + Circling Transition Exemption

Two plan-reviewed cycles, one deploy. Config rider: garage cameras → egress list at this restart.

## MEMORY-COMPACTOR-1 (Tier 2-DB: plan review + 3 framing-disjoint reviews + 15-finding fix-up)

Stage 2 of Hierarchical Entity Memory: the deferred distill/correct compaction engine.
- **Engine** `memory_compactor.py`: nightly pass over `memory_episodes` via per-type registered
  rules (transparent statistics, no LLM). Seeded: `phantom_recurrence` (priority 1, adjudicated-only,
  attrs stamp `coverage: d2_gated` — rates measure D2-detected phantoms, NOT sensor health),
  `actuation_conflict_summary` (aggressive: 639 near-identical rows → per-shape window summary),
  `exterior_track_baseline` (D1 hand-compact fixture-first, oracle diffed byte-for-byte).
- **Atomic combined DAO** `distill_memory_fact`: INSERT OR IGNORE + supersede UPDATE in ONE
  `_db()` acquisition/commit (invariant §1a). Facts never edited; corrections supersede with lineage.
  `count(memory_episodes)` never decreases; redaction ships as disabled framework
  (`MEMORY_REDACTION_HORIZON_DAYS=None`; operator-confirmed revisit trigger 20k rows).
- **Data-driven node discovery** (Review A HIGH): `read_distinct_nodes_for_episodes` DAO on the
  read pool — room-scoped rules actually fire (the hardcoded scope table was dead for rooms).
- **Wiring**: nightly `_cleanup_ops` AND the deferred `_cleanup_ops_d` mirror (Reviews B+C converged
  on the missing deferred tuple — Bug Class #27; a permanent parity test now asserts the mirror).
  Cadence guard (24h, operator-confirmed 02:30 piggyback); `button.ura_memory_compact_now`
  (manual override, vacuum-button precedent); 6 observation-only attrs on `sensor.ura_memory_status`.
- Kill switches: `MEMORY_COMPACTOR_ENABLED=False`, `MEMORY_COMPACTOR_CADENCE_HOURS=0`.
- Test posture: 23 tests; 5 mutation drills real-run sequential (incl. AST-scan hardened against
  the importlib evasion Review C demonstrated); orchestrator re-drill of the node DAO.

## CIRCLING-LABEL-1 (Tier 2: plan review + 2 reviews, both SHIP)

Classification-transition exemption: an exterior track escalating (pass_by → approach → circling)
now bypasses the dispatch cooldown ONCE per (track, target class) — circling forms → one HIGH page,
instead of being swallowed by the earlier hop's cooldown.
- Invariants: I1 exactly-one-per-escalating-transition (set-ledger, bool-collapse drill-anchored);
  I2 strict `<=` no-de-escalation re-dispatch; I3 safeword window outranks AND does not consume;
  I4 flap-bound one-per-(track,class). RAM-only ledger (restart re-arm ≤2 pages/track, documented).
- XCORR-1 burst demotion short-circuits for exemption dispatches (plan review caught the original
  mechanism was wrong: single-camera-night circling would have demoted to LOW — D5b test pins it).
- Cross-camera same-track double-grant race closed: optimistic ledger seed pre-dispatch with
  rollback on all four abort paths (Review B).
- Zero new knobs. 24 tests; 8 drills + orchestrator re-drill of the XCORR-1 short-circuit.

## GARAGE-EGRESS-APPLY-1 (config rider at this restart)

`camera.garage_a` + `camera.garage_b` move into `egress_cameras` on the parent URA entry via the
flush-watcher pattern (edit applied in the stop→boot gap after the shutdown flush).

## Acceptance criteria

- **Test:** test_memory_compactor.py (23) + test_circling_label_transition.py (18) +
  test_circling_founding_case_transition.py (6); suite baseline name-diff clean (26 pre-existing).
- **Live L1:** boot clean, zero URA ERROR lines post-restart.
- **Live L2 (compactor):** press `button.ura_memory_compact_now` → `sensor.ura_memory_status`
  attrs populate (`compactor_last_run`, `facts_created` ≥ 1, `writes_last_run` small int ≪ 500);
  DB shows ≥ 1 row per seeded topic (`phantom_recurrence`, `actuation_conflict_summary`,
  `exterior_track_baseline`); `phantom_recurrence` facts carry `coverage: d2_gated`.
- **Live L3 (compactor invariant):** `count(memory_episodes)` unchanged by the run; no fact row
  in-place-edited (supersede lineage only).
- **Live L4 (compactor nightly):** after first 02:30 tick, `compactor_triggered_by = nightly`.
- **Live L5 (garage egress):** parent entry `egress_cameras` contains both garage cameras post-boot;
  garage person events route as egress, not interior.
- **Live L6 (circling, organic):** next real escalating track dispatches at the transition
  (ledger attrs visible via diagnostics); no double-page on any (track, class).

## Live Validation

### Validated 2026-08-14 (v5.76.0 boot, ~23:05 CDT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA errors | **PASS** | system_log ERROR × universal_room: 0 entries (via ha_get_logs source=system; note: /config/home-assistant.log does not exist on HAOS — first scan was hollow, redone via the correct source) |
| L2 | Manual compact run distills | **PASS** | `button.ura_coordinator_manager_compact_memory_now` pressed → `sensor.ura_coordinator_manager_memory_status` attrs: `facts_created=20`, `writes_last_run=20` (≪ cap 500), `triggered_by=manual`, `aborted_reason=null`, `skipped_missing_identity=0`. DB: `phantom_recurrence` 3 rows / `actuation_conflict_summary` 8 / `exterior_track_baseline` 9. Phantom facts carry `coverage: d2_gated` (verified on row). **README correction:** entity_ids are device-prefixed (`ura_coordinator_manager_*`) — the plan's bare `button.ura_memory_compact_now` does not exist; first press dispatched into a void and surfaced as a false "success (timeout)". |
| L3 | Preservation invariant | **PASS** | `count(memory_episodes)` 1849 pre = 1849 post; 0 superseded rows (no corrections yet, none expected on first run); no in-place edits possible by construction (drill-anchored) |
| L4 | Nightly `triggered_by=nightly` | **ORGANIC (open)** | First 02:30 tick |
| L5 | Garage → egress survived boot | **PASS** | Flush-watcher log: flush detected, applied in gap; post-boot parent entry `egress_cameras` = [madrone_g6_entry, doorbell_lite, front_door_aerial, **garage_a, garage_b**] |
| L6 | Circling exemption end-to-end | **ORGANIC (open)** | Next real escalating track: one HIGH page at the transition, no double-page per (track, class) |
