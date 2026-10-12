# URA v5.103.52 — Night lights go red on return at sleep; plain-English room sensors form

Cards: NIGHTLIGHT-RED-RECONCILE-PARITY-1, SENSOR-FORM-PLAIN-TEXT-1. Tier 1 each (one review each, findings fixed and drilled). Full-suite name-diff: 0 new vs pre-cycle baseline (132 = 132 failing names; an 11-test regression from the form change was caught by the name-diff and fixed before ship).

## 1. Night-light red parity (NIGHTLIGHT-RED-RECONCILE-PARITY-1)
**Problem:** when a night light came back online (or was corrected by the reconciler) while the house was asleep, it was re-sent with the normal colour instead of sleep red — the red-at-sleep decision lived only in the canonical turn-on path.
**Fix:** the red-hue decision moved into the shared resolver, so the reconcile-on-return path (including the reconciler's house-sleep branch and rooms mixing canonical/reconciled lights) sends red at sleep exactly like the canonical path.

## 2. Room sensors form in plain English (SENSOR-FORM-PLAIN-TEXT-1)
**Problem:** the sensors step used internal wording and exposed a raw JSON capability field to everyone.
**Fix:** short user-focused labels, one plain question per added sensor ("What can it see?"), and the raw JSON field moved to Advanced only (with the standard Advanced hint on the step).

## Not built / deferred
None from either card.

## Live validation (prospective)
- Boot: 0 URA errors.
- Sensors options step renders the plain labels; JSON field hidden unless Advanced mode.
- Next sleep-time night-light reconcile/return: light comes back red (check light attributes `hs_color`/`rgb_color` on a sleep-period return).
