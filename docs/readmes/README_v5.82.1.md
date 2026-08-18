# URA v5.82.1 — Face-confirmed arrival now resolves `_2`-only cameras (hotfix)

Tier-1 hotfix (card `CENSUS-FACE-RESOLVER-MIGRATE-1`). A bucket-2 finding from the census/identity
post-ship supersession sweep: a *useful* helper that was silently under-wired, not dead.

## The problem this closes

`presence.py:_get_face_for_camera` (the v3.19.0 face-confirmed-arrival helper) resolved its face
sensor by string-building `f"sensor.{base}_last_recognized_face"` — with **no `_2`-suffix
tolerance**. Since the Frigate-1 retirement, some cameras' Frigate face sensor exists *only* as the
disambiguated `_2` variant, so on those cameras the helper silently found nothing and face-confirmed
arrival never fired. The rest of the census stack got the `_2` resolver in v5.80.0; this one caller
was missed.

## What shipped

`_get_face_for_camera` now resolves via the **reused** `camera_census._resolve_face_entity_id(base)`
(canonical-preferred, fail-closed, Frigate-1-retired-safe), falling back to the bare id only if the
census object isn't wired yet (early boot / fixtures — `census` is set unconditionally at
`__init__.py:2234`, so this is degenerate-safe, not a persistent no-op). No resolver logic
duplicated. Intended behavior change: face-confirmed arrival now fires on `_2`-only cameras it
previously missed.

## Review

Tier-1, one adversarial review (SHIP-with-fix). Fixed: a **hollow test anchor** (M1) — the test
stubbed the resolver, so combined with a broad `except Exception` a resolver rename would silently
revert to the bare path with the suite green. Now a real-`PersonCensus` smoke test asserts the
symbol exists (mutation-drilled: rename → smoke test fails → restore), and the `except` is narrowed
to `(LookupError, ValueError, TypeError)` so an `AttributeError` propagates loudly. Diagnostics note:
`_face_lookup_missing_count` now also counts presence-driven lookups (rate shift, not a bug).

## Non-goals

No new entities/sensors/knobs. Single call site; additive path; no trust-decision demotion depends
on it. `_face_lookup_missing_count`'s rate change is diagnostic only.

## Acceptance criteria

- **Test:** `test_face_resolver_migrate.py` — `_2`-only camera resolves (fix), bare canonical still
  resolves (no regression), no sensor → None, real-`PersonCensus` symbol smoke test. 47 passed on
  merged develop.
- **Live:** boot clean, zero URA ERROR. Organic (Wed occupancy): on a `_2`-only face camera, a
  face-confirmed arrival that previously produced no name now resolves the resident — provable only
  with a real recognized face on such a camera.

## Live Validation

_Pending post-restart (L1 boot-clean immediately; the `_2`-camera resolution is organic on Wed)._
