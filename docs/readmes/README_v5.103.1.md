# v5.103.1 — Make the arrester auditable, and stop poisoning HA's event bus

Two small, additive, defensive fixes. **No behaviour change to HVAC actuation,
presence, or energy.** Both exist because an investigation on 2026-09-15/16 hit
walls that were instrumentation gaps rather than defects.

---

## D1 — `ACTIVITY-LOG-BARE-SLUG-ENTITY-ID-1`: guard the `ura_action` bus event

**The defect, live on the running system.** Home Assistant's recorder subscribes
to *every* event on the bus and calls `split_entity_id()` on any `entity_id`
field it finds. URA's EVSE charge-onset telemetry was writing a **bay slug**
(`"garage_a"`) into that field. A bare word has no domain, so the recorder's
listener job raised:

```
ValueError: Invalid entity ID garage_a
  recorder/core.py:304 _event_listener -> entityfilter.py:230 -> core.py:176
```

24 such rows exist in the URA DB (`garage_a` onset_release ×12, onset_hold ×11,
`garage_b` ×1). A URA-internal naming convention was escaping into someone
else's code path and erroring there.

**The fix.** `activity_logger.py` now admits only a well-formed
`domain.object_id` value onto the bus event. Malformed values are dropped from
the **event** with a debug line.

**Why the guard sits at the producer rather than at the call sites.** The slug
is genuinely useful *bay identity* in the DB column, and no consumer requires
entity-id shape there. Rewriting the call sites would change DB semantics for a
cosmetic gain. The contract that actually matters is HA's, at the bus boundary —
so one guard fixes the error, protects every future caller, and leaves the
diagnostic value intact. This matters immediately because D2 adds new writers to
the same ledger.

---

## D2 — `ARRESTER-LEDGER-INVISIBLE-1`: arrests now leave a durable record

**The defect.** The HVAC override arrester recorded its decisions *only* as
`_LOGGER.info` lines — and URA's log keeps WARNING and above. Every arrest was
erased as it was written. `hvac_override.py` contained **zero**
`activity_logger` calls, while `hvac_fans.py` has used the durable ledger for
some time.

**The cost, measured.** On 2026-08-20 a live override could not be confirmed
*or* ruled out after the fact. On 2026-09-16, three separate investigations
stalled in one night because a thermostat write that demonstrably happened
(cooling ceiling moved 75 → 76) could not be attributed to anything: the
activity log held no HVAC row for the entire window.

**The fix.** A `_arrest_ledger` helper (reusing the `hvac_fans.py:1058` pattern)
writes a durable row at both detection sites:

| field | purpose |
|---|---|
| `action` | `override_detected` |
| `details.mode` | `governed` vs `passive` — tells a real arrest from a detection-without-revert |
| `zone_id`, `entity_id` | which zone, which thermostat |
| `old/new_preset`, `old/new_high`, `old/new_low` | what actually moved |

**Fail-open by construction:** broad `except`, no `await`, hands off via
`async_create_task`. Recording an arrest must never be able to *prevent* one —
that would be strictly worse than the invisibility it replaces.

The ledger call sits **after** the `if not is_override: return` guard, so
ordinary state changes write nothing.

---

## Evidence

- **D1:** 12 tests, including a cross-check asserting the guard agrees with Home
  Assistant's own `split_entity_id` for every sample — an *independent oracle*,
  so if HA changes that contract the test fails (correctly). Mutation drill:
  guard neutered → 9 failed; restored → 12 passed.
- **D2:** 6 tests, AST-based per-site. Mutation drill: delete the governed call
  → 3 failed; delete the passive call → 2 failed; restored → 6 passed.
  - *A hollow anchor was self-caught here.* The first version of these tests used
    string search, so deleting the governed call left them **green** — the
    passive call still matched `_arrest_ledger` and `override_detected`. The
    mutation drill exposed it and the tests were rewritten to pin each site via
    AST. Recorded because it is exactly the failure class the suite is meant to
    prevent.
- Suite: 18 cycle tests pass. The 4 failures in the arrester/override/activity
  selection were verified **pre-existing** in the baseline captured before these
  changes.

---

## Live validation — Validated 2026-09-16 00:05 CDT (post-restart)

Deployed v5.103.1, HACS-installed, HA restarted ~23:58 CDT. Version on the host
confirmed `v5.103.1`; guard present (2 refs) and ledger present (3 refs) in the
**installed** files, not merely in the PR.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | No new URA ERROR after restart | **PASS** | ERROR-level scan filtered to `universal_room_automation`: 0 entries |
| 2 | No `ValueError: Invalid entity ID garage_a` | **PASS (but see note)** | ERROR scan for `Invalid entity ID`: 0 entries |
| 3 | D1 guard exercised on a real event | **NOT YET EXERCISED** | the producing event has not fired since deploy — see below |
| 4 | D1 negative: well-formed `entity_id` still rides the event | **NOT YET OBSERVED** | 9 `ura_action` events fired post-restart; none carried an `entity_id` field |
| 5 | D2: a genuine override writes an `override_detected` row | **PENDING** | requires a real thermostat override; cannot be forced honestly |
| 6 | D2 negative: ordinary preset changes write no such row | **PENDING** | same |

### Criterion 2 is NOT yet a discriminating pass — stated plainly

The error is absent, but **the guard has not been tested**, because the thing
that produces it has not happened since the deploy. The EVSE onset telemetry is
**edge-triggered** (one row per state transition per bay/leg), and the most
recent bare-slug row is `2026-09-16T03:59:33Z` = **22:59 CDT, an hour before the
restart**. Correct epoch-based query over the last 60 minutes returns **0**.

So absence-of-error currently proves only that nothing tried to emit one. It
will become a real pass at the next onset hold/release, which is when the DB
should gain a bare-slug row **while the log stays clean** — that pairing is the
discriminator, not the silence alone.

### A measurement error worth recording

An earlier check of this used
`timestamp >= datetime('now','-20 minutes')` and returned `2`, which read as
"the guard is letting slugs through". That query was **wrong**: the column holds
ISO strings (`2026-09-16T03:59:33...+00:00`) and `datetime()` returns
space-separated (`2026-09-16 04:42:00`); in a string comparison `'T' > ' '`, so
it matched *every* row dated today regardless of time. Same format-mismatch
class as the TZ skew that produced false egress figures. The corrected query
uses epoch conversion and returns 0.

## Context

D2 is **step 2 of `HVAC-SUPPLE-SEQUENCE-1`** — the instrument the rest of the
HVAC sequence depends on. Steps 1–3 of that sequence change no behaviour by
design; they exist so the one behaviour change (step 4) can be proven.

Not shipped here, and deliberately: the `resume`-then-pin write sequence derived
on 2026-09-16 (which fixed a zone stuck in an anonymous hold and held for 8
minutes across 9 cloud refreshes), and the per-kind suppression-TTL split it
requires. Those change live thermostat behaviour and are their own cycle.
