# Review B2 (re-review) — guest-count-dedup H1 fix-up

Scope: focused adversarial re-review of fix-up commit `456a51578` on
`feature/guest-count-dedup` (site #3 `UnidentifiedPersonsSensor` migration +
shape-invariant test), on top of original build `d010122bd`. Prior verdicts:
Review A SHIP, Review B DO-NOT-SHIP (H1 = missed site #3), Review C SHIP.

Verdict: **SHIP.**

- 18/18 cycle tests green (`quality/tests/test_guest_count_dedup_migrate.py`).
- Independent repo-wide shape re-grep confirms no site #4: the only live
  `max(0, camera_total - …)` production line is
  `camera_census.py:1899` (canonical producer, correctly excluded from the
  CONSUMER invariant). The other three occurrences
  (`sensor.py:4445`, `aggregation.py:5932`, `binary_sensor.py:1571`) are
  docstring narrative describing the retired naive form.
- `ble_identified` attribute has zero live consumers repo-wide (searched
  `custom_components/`, `dashboards/`, `scripts/`, `quality/` — only
  historical planning docs and prior review docs reference the string).
- Shape-invariant test mutation-verified to bite: removing the
  `camera_census.py` producer-exclusion causes the test to flag
  `camera_census.py:1899` — proving the pattern is real, not vacuous, and
  the exclusion is doing load-bearing work rather than hiding a bug.

---

## 1. Site #3 semantic equivalence

The migration replaces two independently-fused substrates with the deduped
`house.unidentified_count` (`camera_total - |face_ids ∪ ble_ids|`).

- OLD BLE substrate: `person_coordinator.data` filtered by
  `location not in (None, "unknown", "away")` — a *tracker-derived*
  "present somewhere" count.
- NEW identified substrate: face+BLE ids the census resolved *this cycle*.

These substrates are not identical, but the swap is **correct for this
sensor's stated purpose** ("camera sees them but BLE can't identify"). The
naive form double-counted residents into "unidentified" precisely when the
two fusions disagreed, which is the pathology the cycle exists to fix
(cross-references `project_guest_mode_false_positive_backlog` and
`feedback_cross_investigation_synthesis`). The swap matches the semantics
already accepted for sites #1/#2 in Review A. No finding.

## 2. Enabled-sensor scrape-shape break (`ble_identified` retired)

`sensor.universal_room_automation_unidentified_persons` is
`entity_registry_enabled_default=True` (verified at
`sensor.py:4457`), so retiring the `ble_identified` attribute is a live
scrape-shape change on shipping hardware.

Grep across `custom_components/`, `dashboards/`, `scripts/`, and `quality/`
(excluding the new test itself and review docs): **no live consumer** of
the `ble_identified` attribute on this entity. The replacement keys
(`identified_count`, `unidentified_count`) are additive and share the same
`house` snapshot as `native_value`, so the attribute surface is
strictly-more-consistent than pre-migration.

**Finding — INFO-1 (non-blocking):** the retired `ble_identified` attribute
key must appear in the `README_v<version>.md` "attribute contract changes"
section for the post-restart validation ledger, per CLAUDE.md README
write-back rule. Prevents a future cycle from having to re-litigate whether
this key ever shipped.

## 3. Shape-invariant test is real

`test_shape_invariant_no_naive_camera_minus_ble_count` in
`quality/tests/test_guest_count_dedup_migrate.py`:

- Regex `max\s*\(\s*0\s*,\s*camera_total\s*-\s*(?:ble|identified)\w*\s*\)`
  matches both `ble_identified` and `identified_count` variants; would
  match the producer line at `camera_census.py:1899` — confirming the
  pattern has real teeth.
- Producer exclusion is scoped to exactly one path
  (`camera_census.py`); if a future refactor splits the producer out to a
  new file, the test will flag it and force a conscious decision (correct
  failure mode, not a silent gap).
- Triple-quoted string blanking (`_TRIPLE_STR_RE`) preserves line numbers
  by substituting newlines, so line-numbered failure messages remain
  useful. Blanking correctly hides the three legitimate docstring
  narratives that reference the retired form.
- `# ...` comment blanking runs before the pattern check, so a naive site
  hidden inline in a `# TODO ...` comment wouldn't false-match either.
- Mutation-verified above: removing the producer exclusion produces
  exactly one hit; adding the pattern to a non-producer file would produce
  a hit. Test bites.

**One narrow concern — LOW-1 (non-blocking):** the shape regex requires
the identifier immediately after `camera_total -` to *start* with `ble` or
`identified`. A future re-introduction that names its subtrahend
differently (e.g. `known_persons`, `resident_count`) would slip the shape
gate. This matches the *actual* substrates in the codebase today, so it's
not a real gap for this cycle — but future planners of related work should
tighten to a semantic rule ("any `max(0, camera_total - X)` where X is not
imported from `camera_census.house`") if the substrate name-space widens.
Not blocking; capture in QUALITY_CONTEXT for the SHAPE-vs-TOKEN lesson.

## 4. No site #4 — independent re-verification

`grep -rn -E "max\(\s*0\s*,\s*camera_total\s*-" custom_components/`
returns 6 hits: 3 docstring lines + 3 lines inside `camera_census.py`
(1862 comment, 1899 code = the producer, 2410 comment). Zero live
consumer sites. Consistent with the fix-up commit message.

## 5. Boot / graceful degradation

`native_value` returns `None` when either `census` is absent from
`hass.data[DOMAIN]` or `census.last_result is None`. This matches the
prior None-when-source-missing contract (OLD returned None when either
`census_state` was None or `person_coordinator` was missing). No new
flap risk; sensor is simply `unknown` until the first census cycle
completes, same as prior boot semantics. `try/except` around the field
read is defensive against `last_result` shape drift and returns None
(does NOT swallow into 0), preserving the None-vs-0 distinction the two
prior sites also observe. Fine.

---

## Summary of findings

| ID | Severity | Blocking | Note |
|---|---|---|---|
| INFO-1 | INFO | No | Record `ble_identified` attribute retirement in README write-back |
| LOW-1 | LOW | No | Shape regex is name-anchored (`ble*`/`identified*`); tighten if substrate name-space widens later |

No CRITICAL, no HIGH, no MEDIUM. Fix-up is complete, semantically
equivalent for the sensor's stated purpose, introduces no scrape-shape
regression on any known consumer, and the shape-invariant test is a real
root-cause fix (not a hollow anchor) for the token-grep gap that Review B
identified.

**SHIP** the two-commit branch `feature/guest-count-dedup`.
