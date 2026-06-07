# URA v4.7.26 — CM Option-Writeback Reload Suppression

**Release date:** 2026-06-06
**Tier:** Tier 2-DB (operator-elevated — three parallel framing-disjoint staff-engineer
reviews: A = data correctness + cross-field invariants + config-flow UX; B = async +
HA lifecycle + reload/race + listener-as-apply-point; C = new surfaces + restart/seed
round-trip + test-fixture authority + plan-completion — plus live validation).
**Scope:** Stops the Coordinator-Manager (CM) entry from doing a full multi-coordinator
reload every time the operator edits a runtime HVAC/DPM timer knob. When a CM options
write touches ONLY the allowlisted runtime keys, the update-listener pushes the values to
the live coordinator attributes in place and suppresses the reload. Mixed or
non-allowlisted changes still reload as before. ROOM and ZONE_MANAGER entries are
unchanged. Also lands the v4.7.25 A-MED-1 config-flow combined-error follow-up and drops
RestoreEntity from the DPM-dwell Number (options is the sole source of truth).

**Files:**
- `custom_components/universal_room_automation/__init__.py` (listener suppression +
  `_apply_in_place` + `_seed_cm_last_applied_options` + `OPTIONS_RELOAD_SUPPRESS_KEYS`)
- `custom_components/universal_room_automation/config_flow.py` (A-MED-1 combined error)
- `custom_components/universal_room_automation/number.py` (DPM-dwell RestoreEntity removal)
- `quality/tests/test_cm_reload_suppression.py` (NEW — 31 tests)
- `docs/planning/PLANNING_cm_option_writeback_reload_suppression.md`
- `docs/reviews/code-review/cm_reload_suppression_tier2db.md`

---

## Trigger

Editing any one of the v4.7.25 HVAC presence-timer Numbers (or the DPM-dwell Number)
fired the CM update-listener, which did an **unconditional full `async_reload`** of the
CM entry — rebuilding presence / HVAC / energy / safety / diagnostics / house_state /
signals coordinators and re-creating every CM entity. Proven live: editing ONE timer
Number re-stamped all four with identical `last_changed` to the millisecond.

On top of that, the operator saw a **"Failed to perform the action number/set_value.
connection lost"** banner on those Numbers. Root cause diagnosis (this cycle's durable
finding): that banner is **NOT a URA crash** — the write completes server-side and the
value persists. It is the **frontend websocket hitting its 4096-pending-message
backpressure cap** (confirmed: repeated `Client unable to keep up with pending messages`
errors to the iOS app; the flood is mostly non-URA noise — `sensor.*_rx`/`_tx`
network-rate sensors + heavy template re-renders). URA's **aggravator** was the
reload's `state_changed` burst at the save moment tipping the already-saturated socket
over. Suppressing the reload removes URA's contribution to that burst.

Restart-restore was already fine (verified, not a concern): options live in
`.storage/core.config_entries`; on setup both the CM coordinator constructor
(`cm_config = {**data, **options}`) and each Number `__init__` re-seed from options. No
RestoreEntity needed.

---

## Headline Changes

- **Reload suppression on allowlisted runtime keys.** A new frozenset
  `OPTIONS_RELOAD_SUPPRESS_KEYS` holds the 5 runtime-tunable CM keys (the 4 HVAC presence
  timers + DPM dwell). The CM update-listener diffs old vs new options:
  - changed keys ⊆ allowlist → `_apply_in_place` pushes live coordinator attrs, **no reload**
  - empty diff → no-op
  - mixed / non-allowlisted → full reload (legacy behavior, untracked task preserved)
- **Per-CM-entry last-applied-options snapshot** at
  `hass.data[DOMAIN]["cm_last_applied_options"][entry_id]`, seeded at CM setup (before
  listener registration), cleared at CM unload (before platform teardown), reseeded on the
  reload fall-through.
- **Live-attr push** writes `hvac._vacancy_grace`, `_vacancy_grace_constrained`,
  `_max_occupancy_hours`, `_zone_entry_dwell` so the next HVAC decision cycle picks them up
  instantly. DPM dwell needs no push — the Energy coordinator's DPM evaluate-and-emit
  re-reads `entry.options` fresh every tick (`_get_cm_options()`).
- **Defensive clamp** re-enforces the v4.7.25 invariant
  `_vacancy_grace_constrained <= _vacancy_grace` in the in-place path, in case an
  out-of-band write bypasses the Number-setter clamp.
- **DPM-dwell Number** no longer inherits RestoreEntity; options is the sole store.
- **A-MED-1 (from v4.7.25):** the config-flow HVAC-settings step now runs BOTH cross-field
  validations (cover-temp hysteresis + vacancy-grace constraint) unconditionally and
  surfaces a combined `cover_and_vacancy_combined` error when both fire (single violations
  keep their per-field message).

---

## Tier 2-DB Review + Fix-up

Three framing-disjoint reviews ran in parallel. **0 CRITICAL, 3 HIGH, 6 MEDIUM, 3 LOW.**
All HIGH + all MEDIUM + 2 LOW fixed in the fix-up commit; 1 LOW deferred as a non-issue.
Full report: `docs/reviews/code-review/cm_reload_suppression_tier2db.md`.

- **A-HIGH-1 (fixed).** Single try/except wrapped all four key-apply blocks — one bad
  value silently dropped its siblings. Now per-key try/except; `_apply_in_place` returns
  the cleanly-applied set.
- **B-HIGH-1 (fixed).** In-place path blindly trusted the clamp invariant; added a
  defensive re-clamp for out-of-band writes.
- **B-HIGH-2 (fixed).** Reload fall-through now reseeds the snapshot before scheduling the
  reload, closing a second-in-flight-write race window.
- **C3 (fixed).** Listener owns the snapshot MERGE based on the applied-set; failed keys
  keep their old value to re-diff next fire.
- **A-MED-2 / B-MED-1 / B-MED-2 / A-MED-1 / C1 / C2 (fixed).** Combined-error both-keys
  gate; pop-before-unload; widened exception catch; None-HVAC INFO log; two missing D1
  tests; byte-equal translations lockstep test.
- **A-LOW-1 (deferred).** Snapshot stale if setup raises mid-reload — setup-failed state is
  already broken and HA retries; reload-reseed + unload-pop cover realistic paths.
- **B-CRIT-1 preserved.** The fall-through reload remains an UNTRACKED
  `hass.async_create_task(... async_reload ...)`.

---

## Tests

- Cycle: **31 passed** (test_cm_reload_suppression.py).
- Full suite baseline-diff: **5105 passed** (post-fix-up), 62 failed + 14 collection
  errors — all pre-existing environmental (`ModuleNotFound: homeassistant` / missing DB
  fixtures). Zero new failures attributable to this cycle.
- Pre-deploy zero-bugs gate: no conflict markers; `py_compile` clean; `strings.json` +
  `translations/en.json` valid JSON.

---

## Live Validation (Review D) — Validated 2026-06-06

HACS v4.7.26 downloaded, `ha_check_config` valid, HA restarted. Results recorded
against the prospective criteria, using live entity `last_changed` attributes and the
home-assistant.log as the authoritative signals.

| Criterion | Result |
|---|---|
| HACS shows installed_version 4.7.26 after download + restart | **PASS** — pending_update cleared after `ha_hacs_download`; integration came up `loaded` post-restart with all CM entities present. |
| Editing ONE allowlisted timer Number does NOT re-stamp the other three (distinct `last_changed`) | **PASS (the robustness bar)** — set `number.…_48_zone_vacancy_delay_minutes` 10→12; re-read of all four: **only 48 moved** to `2026-06-07T01:16:45.212Z`, while `47`/`49`/`50` all kept their boot-seed `2026-06-07T01:14:29.215Z` (distinct, unchanged). Pre-fix, editing one re-stamped all four with identical `last_changed` to the ms. Reload suppressed. |
| Edited value reaches the live HVAC attr | **PASS (path) / in-suite (next-cycle propagation)** — the suppression INFO confirms `_apply_in_place` ran (it pushes `hvac._vacancy_grace`); the Number read-back matched the set value (`verified_state` 12, then 11, then restored 10). Full next-decision-cycle attr propagation is covered in-suite (the live attr is an internal Python field, not separately exposed). |
| Log shows the suppression INFO, not a reload, for an allowlisted edit | **PASS** — at URA logger=INFO, a single allowlisted edit emitted: `CM options changed for 'URA: Coordinator Manager' (01KJEC3FYPYAGBQKZWC94CR8GR) — in-place apply, suppressing reload (changed_keys=['hvac_vacancy_grace_minutes'])`. No CM reload burst followed (the three sibling Numbers did not re-stamp). URA logger restored to WARNING after. |
| A mixed/non-allowlisted CM options change still reloads | **In-suite covered (not live-triggered)** — the fall-through reload rebuilds all coordinators and would re-induce the cold-boot away-actuation storm; triggering it live for a covered branch was not worth the disruption. 31 unit tests exercise the mixed/non-allowlisted → full-reload + snapshot-reseed path. |
| Persistence across restart (Bug Class #32 unchanged) | **PASS** — post-restart all four Numbers came up at their persisted **non-default** option values (47=3, 48=10, 49=5, 50=4; defaults are 3/15/5/8), seeded from `entry.options` on CM setup. The 10→12→11→10 edits each survived their in-place apply (read-back matched), proving writeback durability without a reload. |
| A-MED-1 combined error | **In-suite covered (not live-driven)** — surfacing the combined `cover_and_vacancy_combined` error requires driving the options flow with both cross-fields violated; this config-flow UX path is covered in-suite, not exercised through the live MCP options flow. |
| No errors attributable to the cycle | **PASS** — ERROR-level scan since boot for `universal_room_automation` returned only 3 lines, all at 20:09:3x (boot window): `database.py` "DB write worker not running — call start_write_worker() first" (compliance/environmental/energy). Pre-existing boot-ordering transient in `database.py`, fired once at boot, not from this cycle's files (`__init__.py` listener / `number.py` / `config_flow.py`). Zero errors from the update-listener or `_apply_in_place`. |

Notes:
- The suppression INFO is `_LOGGER.info`; URA's logger sits at WARNING in normal
  operation, so the line is below threshold by default — it was captured by briefly
  raising URA to INFO, then restored. The authoritative proof of suppression is the
  behavioral `last_changed` divergence, which holds regardless of log level.
- The operator's pre-validation timer settings were preserved: 48 was restored to its
  boot value (10) after the test edits.
- Boot-storm: as on prior cycles, MCP calls timed out for the first few minutes
  post-restart while the event loop drained the cold-boot away-actuation storm;
  validation ran after it settled (~01:14Z onward).

---

## Not in scope

- **Part 2 — EC/HC options-writeback retrofit.** Applies the same options-sole-source +
  live-attr-push pattern to the Energy Coordinator family, the HVAC tunable factory, and
  the remaining HVAC/DPM Numbers; their keys join `OPTIONS_RELOAD_SUPPRESS_KEYS`. Hard
  dependency: ships AFTER this cycle is live + validated. Plan:
  `docs/planning/PLANNING_part2_ec_hc_options_writeback_retrofit.md`.
- **Per-room ComfortTempMin/Max persistence** — separate follow-up cycle (different reload
  path, real data-loss hazard on ROOM entries). DO NOT DROP.

## Review

See `docs/reviews/code-review/cm_reload_suppression_tier2db.md`.
