# Plan review 3 (re-verify): NVR witness layer

Plan: `docs/planning/PLANNING_nvr_witness_layer.md` at develop 45e2d54d. Card NVR-WITNESS-CONSOLIDATION-1.
Inputs: `PLANREVIEW_nvr_witness_layer_1.md`, `_2.md`; operator decisions Q1 `all`, Q2 yes, Q3 table, Q4 W1 first;
CLAUDE.md "Registry, never name guessing" (CLAUDE.md:117-123). Read-only; no pytest; the full enumeration was not re-run.
HVAC and presence state-of-play docs not read: no finding depends on them.

Verdict: **FIX-PLAN** (0 CRITICAL, 0 HIGH, 4 MEDIUM, 3 LOW). Every review 1 and review 2 CRITICAL/HIGH/MEDIUM is closed.
The new DB section adds four text-level gaps, all small plan edits. No design change is needed.

## 1. Prior findings: closed?

Review 1 H1, H2, M1-M5 were confirmed closed by review 2 and are still present (§4.1, §4.2/W5c, §5, §10 step 3, W3, W5a, W4).

| Review 2 item | Closed | Where |
|---|---|---|
| H1 classifier vs opt-out | Yes: phased invariant, function-keyed allowlist with knob + deletion step, behavioural test (b), fallback test (c) | §6 INV-W-ONE-CLASSIFIER |
| H2 windowed queries, episode cap | Yes: in-memory ring, `EPISODE_MAX_S`, ⌈1200/MAX⌉ test | §7 Ring/Episodes, W2 tests, §9 |
| H3 census value space | Yes: `platform_for` mapping, `"unknown"` → `CAMERA_PLATFORM_UNIFI`, UniFi-like branch kept as counted fallback, census golden incl. fallback | §4.1, W5b tests |
| H4 W1 name evidence | Yes: option (b) four-condition uniqueness, residual named, knob-off golden, mutation on condition 2 | §5, W1 |
| M1 owner/lifecycle | Yes | §7 Owner, `test_layer_built_once_lazy_fetch_reload_no_orphan` |
| M2 close owner | Yes: tracked superseding timer, `close_reason = shutdown` excluded | §7 Episodes, INV-W-ONE-EPISODE |
| M3 fire definition | Yes: transit's predicate and clock, symmetric window | §7 Fire, Ring |
| M4 agreement params | Yes: `pair`, `last_n`, `min_samples`; no pair window | §7 Agreement |
| M5 multi-family | Yes: family set, `ineligible`, W3 excludes | §7, W3 tests |
| M6 gap ≥ window | Yes for gap/ring (INV-W-WINDOWS + inversion test). PRE/POST vs cap not addressed: see L2 | §6 |
| M7 Store migration | Superseded by Q3: import as a separate `alert_sample` kind, never mixed into episode rates. Consistent with M7's concern | §7 Perimeter history |
| L1-L4 | Yes (§10 order; W0 sizing + per-flush bound; cache in §4.1; per-consumer goldens + master kill) | |

## 2. New findings

**M1 (MEDIUM, restart safety, Tier 2-DB B): the import is not specified as atomic, and the marker row has no kind.**
§7 says "a marker row prevents a second import", but `record_kind` is defined as `'episode' | 'alert_sample'` only
(§7 schema). A builder will either invent a third kind silently (readers that filter `record_kind != 'episode'` would then
count it as an alert sample) or put the marker elsewhere. Nothing says the imported rows and the marker are written in one
transaction; if HA stops between them, the next boot imports again and doubles the perimeter history. The precedent DAO
commits once per `_db()` block (`database.py:7766-7775`), so atomicity is cheap. Fix: add `record_kind = 'import_marker'`
(or a `pipeline_version`-keyed marker), state that rows + marker go in one `_db()` block with one commit, and that every
reader filters by explicit kind. Test: `test_perimeter_store_import_crash_between_rows_and_marker_no_duplicate`.

**M2 (MEDIUM, #63 concept split, W5a): "same semantics as its tracker" is contradicted by retention and ordering.**
The tracker scores the last N outcomes with no age limit (`perimeter_fp_gates.py:139,:166`). The table prunes rows past
`NVR_WITNESS_RETENTION_DAYS` by date, and imported rows have `started_at NULL` with order in `seq` while new rows order by
`started_at`. "Last 100 alert samples" over that table is undefined (NULLs sort first or last by dialect choice) and a quiet
camera's samples age out where the tracker would keep them. Fix: one ordering key for alert samples (`seq` for all, new
rows continue the sequence, or a synthetic `started_at` from import time preserving order), state that prune excludes
`alert_sample` rows or keeps the newest `PERIMETER_SS_WINDOW_N` per camera, and add a test that the table rate equals the
tracker rate on the imported corpus. The W5a replay gate would catch a divergence, but only after 14 days.

**M3 (MEDIUM, registry rule, CLAUDE.md:117-123): W1 still pairs by a name comparison that is neither logged nor counted.**
Condition (1) compares the Frigate object name (registry identifier: fine) with the candidate's "dstem", which §5 derives
from "the device's registered camera entity", i.e. its entity_id string. Under the new rule a string test on a non-URA
entity is allowed only as a logged, counted fallback. Either (a) compare against registry fields only (the candidate
device's `name` / `name_by_user`, normalised the way HA slugifies, which is what produced `camera.garage_a`), or (b) declare
W1's comparison a counted fallback in `name_fallback_count` with target "garage_a only" and cite the exception. The plan
must pick one; as written it is a new name guess, which the rule calls a defect.

**M4 (MEDIUM, INV-W-OPTOUT scope): the W2 perimeter mirror write has no opt-out.** From W2, `finalize_due` appends every
sample to the table. INV-W-OPTOUT covers decision output only, so it still holds, but `NVR_WITNESS_ENABLED=False` is
documented as "no subscriptions; all consumers legacy" (§9) and the mirror is a new write in perimeter's path. Say whether
the master kill stops the mirror (it should), and include it in `test_master_kill_all_consumers_golden` (no rows written).

**L1 (LOW): shutdown flush drops.** Teardown flush racing `DBShuttingDown` drops the last buffered alert samples (§7), so the
table drifts below `.storage` by a few samples per restart. Acceptable; say so, and let the W5a replay compare counts.

**L2 (LOW, review 2 M6 tail): `PRE_S` + `POST_S` vs crossing vision's clip/settle limits has no const test.** Add one line.

**L3 (LOW): index coverage.** `(camera_key, record_kind, started_at)` serves boot load and episode rates; alert-sample
"last N by seq" (after M2) needs `seq` in the index or the query sorts per camera. Small table; note it.

## 3. Rewrite contradictions checked

| Pair | Result |
|---|---|
| Invariants vs migration order | Consistent: phased ONE-CLASSIFIER matches W2 → W5b/c; W1 precedes and touches no classifier site |
| Opt-out vs one-classifier | Resolved by the legacy-branch allowlist with knob + supersession step |
| DB table vs Tier 2-DB framings | Consistent: §10 assigns A/B/C to the table part; B's import concern sharpened by M1 |
| W1 uniqueness vs registry rule | Gap: M3 |

## 4. Tier 2-DB checklist on §7 Persistence

| Requirement | Status |
|---|---|
| DAO through the serialized write path, batched | PASS: one `executemany` per flush, `log_hvac_evidence_shadow` shape (`database.py:7739`); per-row write is a named mutation |
| Schema extracted from production in tests | PASS: W2 DB tests "schema extracted from production DDL, real DAO" |
| `.storage` import idempotent and restart-safe | LEAK: M1 (marker kind, atomicity) |
| Retention | PARTIAL: nightly batched prune named; conflicts with tracker semantics (M2) |
| Index coverage | PASS for episodes; L3 for alert samples |
| Write volume | PASS: W0 sizing, assumed bound stated, per-flush row-bound test |
| Pre-deploy row-rate snapshot / sentinel live check | PASS: W2 Live "non-null `families_json` within an hour" |

## 5. Goal fidelity

Operator: "exercise both nvr platforms simultaneously, then cross compare"; agreement record "critical for learning... baked
into the design"; "consolidation so there's no drift"; "not necessary to disturb what's in flight". The plan delivers each:
Q1 `all` puts both NVRs on every crossing, the record is first-class and persisted in one table (Q3), classifiers and
comparisons converge on one module, and in-flight plans are only listed in §11, not edited. Hard constraint (AWAY fast)
untouched (§10 non-goals). No drift found.

## Must-fix before build

1. M1: marker kind + single-transaction import + crash test.
2. M2: one ordering key for alert samples; retention rule for them; table-rate = tracker-rate test.
3. M3: W1 comparison on registry fields, or declared as a counted fallback.
4. M4: master kill stops the perimeter mirror; covered by the master-kill golden.
LOWs: one line each in the same edit.
