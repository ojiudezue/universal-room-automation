# v5.100.1 — Config-menu polish: CM sub-editor help text + zone-menu standardization

**Type:** UX polish (config-flow help text + one menu-routing change). **Tier:** 1-2 (config-flow;
no schema/persistence change → option round-trip + RestoreEntity byte-identical). Cards:
`CM-CONFIG-FLOW-UX-SELECTORS-1`, `CM-CONFIG-FLOW-UX-1` (zone-menu half).

## Why
Operator review of the live menus: the Coordinator-Manager notification sub-editors had **no
help text** (raw fields, unclear units/shapes), and the Zone menu felt **non-standard** vs the
House/CM/Room menus.

## What shipped
- **CM notification sub-editors — help text (D1).** Added `data_description` for all **16 fields**
  in "Notification Volume & Noise Reduction" and **5** in "Per-Person Routing & Hazard Overrides"
  (units, ranges, the humidity monotonic ladder, kill-switch semantics, and the persisted dict
  shapes for the three `ObjectSelector` matrices). **Finding:** the selectors were already correct
  (Number/Boolean/Entity/Object) — the crudeness was missing help, not wrong widgets. **No schema
  change.**
- **Zone menu standardization (D2).** The Zone-Manager options flow no longer opens with a trivial
  one-option "Manage Zones" wrapper — it routes straight to the zone picker; fixed a stale field
  label (`zone_entry`→`zone_name`) + added help. The two-step *select-zone → per-zone categorized
  submenu* is retained (one ZM entry manages N zones — a single flat menu can't represent N zones
  without duplication); the per-zone submenu already matches the House/CM/Room categorized standard.

## Non-goal / carded
The three dict/matrix routing fields remain structured `ObjectSelector` inputs (documented via
help text) — a lossy per-key selector was deliberately not forced.

## Live validation — acceptance criteria
- **L1:** restart clean, config valid, no new URA errors.
- **L2:** the two CM notification sub-editor pages show help text under each field; units visible.
- **L3:** the Zone options flow opens directly on the zone picker (no redundant one-item menu);
  the per-zone submenu is categorized like House/CM/Room.
- **L4 (no regression):** an existing CM notification option + a zone setting still round-trip
  (set → persist → re-read) unchanged (in-suite: 1003 pass, name-diff 0; the 5 suite-ordering
  flakes pass in isolation).

## Validated 2026-09-08 (post-restart, v5.100.1 live)

| Criterion | Result | Evidence |
|---|---|---|
| L1 clean boot | **PASS** | URA loaded (`persons_in_house`=2); config valid; **zero URA ERRORs** in the post-boot error_log scan. |
| L4 no regression | **PASS** | Zone-rename + notification round-trip tests pass in isolation; suite 1003 pass, name-diff 0 (5 pre-existing cross-pollination flakes). |
| L2/L3 UI (help text + zone picker) | **operator visual** | Translation-only rendering; verify in the UI (help text under the two CM notification steps; zone flow opens on the picker). |

**Rollback not needed.** Translation + one routing line; no schema/persistence change.
