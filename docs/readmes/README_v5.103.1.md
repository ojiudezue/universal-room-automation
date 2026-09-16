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

## Live validation (to be completed after restart)

- [ ] **D1:** a boot log scan shows **no** `ValueError: Invalid entity ID garage_a`.
      This is the criterion that discriminates a real fix from a plausible one —
      the error appeared on the 2026-09-16 boot scan.
- [ ] **D1 negative:** activity rows that *do* carry a well-formed `entity_id`
      still ride the event (the guard must not be a blanket drop).
- [ ] **D2:** the next genuine thermostat override produces an
      `override_detected` row in `ura_activity_log` with `mode` populated —
      queried directly, not inferred.
- [ ] **D2 negative:** ordinary preset changes produce **no**
      `override_detected` rows (a ledger that fires every tick would drown the
      signal it exists to provide).
- [ ] No new URA ERROR in the boot scan.

---

## Context

D2 is **step 2 of `HVAC-SUPPLE-SEQUENCE-1`** — the instrument the rest of the
HVAC sequence depends on. Steps 1–3 of that sequence change no behaviour by
design; they exist so the one behaviour change (step 4) can be proven.

Not shipped here, and deliberately: the `resume`-then-pin write sequence derived
on 2026-09-16 (which fixed a zone stuck in an anonymous hold and held for 8
minutes across 9 cloud refreshes), and the per-kind suppression-TTL split it
requires. Those change live thermostat behaviour and are their own cycle.
