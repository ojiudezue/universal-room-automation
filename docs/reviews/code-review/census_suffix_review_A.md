# Census-Suffix-Fix — Reviewer A (correctness + matching semantics)

- Commit reviewed: `c20b86819` (feature/census-suffix). The merge commit `c7df46635` is a develop catch-up; disjoint surfaces.
- Spec: `docs/planning/AUDIT_census_accuracy_regression.md`
- Framing: correctness + matching semantics. Sibling reviewers cover async/lifecycle and adversarial completeness.

## Verdict: SHIP

Wire-in anchors are load-bearing. Both mutation drills fire the named
test and are cleanly reversible. Strip helper semantics are narrow and
safe. Real (registry) entity_ids are stored at every assignment site.
Ambiguity guard produces a bounded WARNING (per resolve call, not per
tick).

## What `_strip_disambiguation_suffix` actually strips

`camera_resolver.py:291-298` — `re.sub(r"_\d+$", "", name)`. **Only a
trailing `_<digits>` run is stripped.** Internal digits (e.g.
`cam2_person_occupancy`) and non-digit suffixes (e.g.
`_person_count_rate`) are untouched. This is the entire risk surface for
the over-match concern, and it is narrow.

Failure modes I looked for and ruled out:

- `sensor.<x>_person_count_rate` — no trailing digits → not stripped →
  does not spuriously match `_person_count`. Safe.
- `binary_sensor.cam2_person_occupancy` — trailing token is the suffix
  itself, no trailing digits → not stripped. Safe.
- `sensor.<x>_person_count_confidence_2` — strips to
  `..._person_count_confidence`, does NOT end in `_person_count`. Safe.
- `sensor.frontdoor_2_person_count` (internal `_2`) — no trailing
  digits → not stripped; matches directly. Safe.
- `sensor.<x>_person_count_120` (legitimate `_120` non-disambiguation
  variant) — would be stripped and treated as disambiguation. There is
  no known Frigate/UniFi naming convention that produces this, so
  practically safe; called out for the record.

## Wire-in anchor / mutation drill (re-run by reviewer)

Env: `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before each run.
Restore verified by `diff -q` after every drill.

- **Baseline:** 4 passed.
- **Drill A1 — count-sensor branch (line 1411)**: rewrote
  `_strip_disambiguation_suffix(_entity_name(eid)).endswith(...)` →
  `_entity_name(eid).endswith(...)`.
  → `test_suffix_disambiguated_count_sensor_maps` FAILED with
  `person_count_sensor=None`. Restored → 4/4 green. **Load-bearing.**
- **Drill A2 — person-binary branch (line ~1396)**: rewrote
  `_has_any_suffix_stripped(...)` → `_has_any_suffix(...)`.
  → `test_suffix_disambiguated_person_binary_maps` FAILED with
  `person_binary_sensor=None`. Restored → 4/4 green. **Load-bearing.**

Both anchors detach the strip in a way a maintainer could plausibly
introduce, and both are caught by the correctly-named test. The
regression-shape test's OLD-side assertion (`not name.endswith("_person_count")`
+ direct call to `_strip_disambiguation_suffix`) is not decorative — it
proves the raw name still requires the strip helper to match, so if a
future maintainer removes the strip helper entirely the test breaks
independently of the wire-in drills.

## Real entity_id constraint — verified at every assignment

- `camera_resolver.py:1396-1398` — `person_bs = _prefer_canonical(person_bs, eid, ...)`; `eid` comes from `entity_registry` iteration.
- `camera_resolver.py:1411-1413` — same shape for `count_s`.
- `camera_census.py:418-419` (canonical branch) — `canonical_id` is only assigned after `ent_reg.async_get(canonical_id) is not None`, so it is a real entity_id.
- `camera_census.py:430` (fallback) — assigns `fallback_id = s_entity.entity_id` from `device_sensors` iteration; real.
- `camera_census.py:830-840` (second legacy path) — canonical via `ent_reg.async_get`; fallback via `ent_reg.entities.values()` and `cand.entity_id`. Real.

No site fabricates a canonical `sensor.<base>_person_count` id and
stores it without a registry lookup.

## Ambiguity guard — semantics + log-spam analysis

- **Preference:** canonical wins over `_N` at both the resolver and the
  legacy-census sites. Test `test_ambiguity_prefers_canonical_over_disambiguated`
  covers both slots.
- **Log cadence:** `_prefer_canonical` fires inside
  `_scan_device_entities`, which is invoked from
  `CameraResolver.resolve_operator_declaration`. Call sites are
  `binary_sensor.py:1215` (per-sensor first_added / re-setup), `__init__.py:587`
  (per-room setup), `camera_census.py:552`. None of these are per-tick
  loops; a device with both canonical + `_N` present would produce a
  single WARNING per resolve call per ambiguous slot. Not spam-per-cycle.
  Fine to ship.
- **Symmetry:** `_prefer_canonical` is safely idempotent for like-vs-like
  (`current` and `candidate` both canonical or both disambiguated) —
  returns `current`, no warn. Correct first-wins semantics preserved.

## Cross-site consistency (resolver vs two legacy camera_census paths)

Same strip helper (`_strip_disambiguation_suffix`) is imported and used
at all three sites. Same base-name derivation
(`stripped_name[:-len("_person_occupancy")]`). Same canonical-first,
then `_N`-variant search order. No drift.

One asymmetry (not a ship blocker, LOW):

- **LOW-1 — census legacy paths don't run `_prefer_canonical` on the
  person_binary slot.** In `camera_census.py:_scan_device_entities`
  (first legacy path), the two `_person_occupancy` / `_person_detected`
  matches are still first-wins by scan order; if a device carries both
  canonical and `_N` person binaries, the CameraInfo person_binary is
  whichever comes first out of the registry (typically canonical, but
  not guaranteed) and there's no WARNING. The resolver path guards
  this correctly. Recommend a follow-up to route the census legacy
  binary-match through the same guard; not a shipping issue because
  (a) the fix's own regression is proven and (b) prior code had the
  same first-wins behavior plus the strip miss.

## Test-authority note

The regression test drives `CameraResolver` directly (via
`_il.spec_from_file_location`) so mutations to the real source module
route through it. This is the correct pattern per the C3 mutation
discipline. No hollow anchors detected.

## Findings summary

| # | Sev | Site | Description | Disposition |
|---|-----|------|-------------|-------------|
| A-LOW-1 | LOW | `camera_census.py` legacy `_scan_device_entities` binary_sensor branches | Ambiguity guard not applied to person_binary; first-wins by registry order (no regression vs prior) | Defer to follow-up |

Zero CRITICAL / HIGH / MEDIUM.

## Ship

Correctness + matching-semantics framing: SHIP.
