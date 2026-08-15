# AUDIT — MEMORY-COMPACTOR-1 D1 hand-compact of `exterior_track`

**Status:** frozen fixture — the `statement_fn` template below is the
authoritative reference implementation. Sibling doc to
`AUDIT_memory_handbuild_study_a.md`.

**Probe:** live URA DB (Samba mount, RO SQLite URI) at 2026-08-14 20:03
CDT. 1052 total `exterior_track` rows, all under `node_id =
"exterior:perimeter"`, span 2026-08-06 → 2026-08-14 (~8 days). Attrs
JSON regular (linker-produced): `{track_id, label, sub_label,
classification, path: [camera, …], hops: […], ...}`.

## Distillation rule (Rule R3 in `MEMORY_COMPACTION_RULES`)

**Trigger:** N ≥ 20 tracks of same `label` on the same first-hop
`camera` (i.e. `attrs.path[0]`) within a rolling 7-day window ending at
`now`.

**Identity keys** (for correction / supersession, per plan §D2): the
pair `(attrs.camera, attrs.label)`. A future run under the same
`(node_id, topic, camera, label)` whose full `attrs` differ from the
current fact supersedes it.

**Topic:** `exterior_track_baseline` (new — see §D0 vocabulary
amendment).

## Frozen `statement_fn` (pure, deterministic — MED-1 fix)

```python
def statement_fn(rows, node_id, topic):
    """Pure function: rows_in_window -> (statement, attrs).

    `rows` is a non-empty list of memory_episode dicts, ALREADY
    grouped by (attrs.path[0], attrs.label) — the engine groups
    upstream so this function sees one group at a time.
    Rows carry: 'id', 'started_at', 'ended_at', 'attrs'.
    """
    cam   = rows[0]["attrs"]["path"][0]
    label = rows[0]["attrs"]["label"]
    n     = len(rows)
    first_ts = min(r["started_at"] for r in rows)
    last_ts  = max(r["started_at"] for r in rows)
    spans = []
    for r in rows:
        e = r.get("ended_at")
        if not e:
            continue
        try:
            spans.append(
                (datetime.fromisoformat(e)
                 - datetime.fromisoformat(r["started_at"])).total_seconds()
            )
        except Exception:
            pass
    import statistics as _st
    typical_span_s = round(_st.median(spans), 1) if spans else 0.0
    attrs = {
        "camera": cam, "label": label, "count": n,
        "first_ts": first_ts, "last_ts": last_ts,
        "typical_span_s": typical_span_s,
    }
    statement = (
        f"exterior_track baseline camera={cam} label={label} "
        f"count={n} first={first_ts} last={last_ts} "
        f"typical_span_s={typical_span_s}"
    )
    return statement, attrs
```

- No timestamps sourced from wall-clock (deterministic given input).
- No set-ordering ambiguity: `sorted()` on ids in `derived_from`
  (engine responsibility), scalar `min/max/median` on values.
- Same input list → same output tuple (verified by
  `test_statement_fn_is_deterministic`).

## Hand-oracle facts (2026-08-14 snapshot, full 7-day window)

Ten (camera, label) groups meet N ≥ 20. Table below is the reference
oracle for the full DB. The machine fixture in
`quality/tests/fixtures/memory_compactor/exterior_track_rows.json`
uses the first 20 rows of the three highest-volume groups (rear_ptz|car,
front_side_ptz|person, utilities_ptz|car), and the expected engine
output for that fixture is
`quality/tests/fixtures/memory_compactor/exterior_track_oracle.json`.

| camera | label | count | first_ts | last_ts | typical_span_s |
|---|---|---:|---|---|---:|
| rear_ptz | car | 232 | 2026-08-07T22:54:24 | 2026-08-14T20:03:28 | 21.0 |
| front_side_ptz | person | 100 | 2026-08-08T10:59:33 | 2026-08-12T11:38:57 | 67.8 |
| utilities_ptz | car | 93 | 2026-08-08T11:04:55 | 2026-08-14T18:37:47 | 5.5 |
| back_yard | person | 74 | 2026-08-07T20:16:57 | 2026-08-12T14:07:00 | 201.2 |
| reolinkstudybporchptz | animal | 60 | 2026-08-08T01:56:43 | 2026-08-12T14:37:27 | 0.0 |
| front_side_ptz | car | 46 | 2026-08-08T10:34:26 | 2026-08-12T12:16:36 | 13.6 |
| pool_equipment | person | 43 | 2026-08-08T01:40:41 | 2026-08-12T03:56:16 | 0.4 |
| rear_ptz | person | 28 | 2026-08-07T20:48:00 | 2026-08-14T15:23:09 | 15.9 |
| hot_tub | person | 25 | 2026-08-08T01:01:27 | 2026-08-12T14:30:30 | 0.4 |
| doorbell_lite | person | 21 | 2026-08-08T11:15:15 | 2026-08-12T12:50:01 | 59.6 |

`derived_from` per fact is the comma-joined sorted episode id list of
the exact rows folded (invariant §1(c): every raw id appears in
exactly one fact's `derived_from`, within this rule/window).

## Type-shape notes for the engine

- `attrs.path` is always a non-empty list on real rows; empty-path
  rows are excluded upstream by the linker. Engine defensively skips
  rows whose `path` is missing/empty.
- `label` is `person | car | animal` in the live sample; the engine
  treats it as an opaque string.
- `ended_at` may be null on rows whose linker window did not close;
  engine excludes such rows from the `spans` median but includes
  them in `count`.
- `adjudication='observed'` on all 1052 rows (linker's default). This
  rule sets `require_adjudicated=False` — the raw observation itself
  is the useful signal for a baseline.

## Invariant §1(c) hand-check

For the fixture (60 rows, 3 groups): every raw id 510..990 appears in
exactly one oracle fact's `derived_from`. Verified by set-partition
in `test_stage0_fixture_diff` (`derived_from` strings joined and
split, then compared set-equal to the source id set per group).
