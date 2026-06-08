# v4.7.33 — Override Arrester TTL suppression (A-F5)

**Tier:** 2-DB (elevated — shared suppression primitive consumed by 9 call sites across
`hvac.py`, `hvac_predict.py`, `hvac_override.py`; regression-prone HVAC actuation).
3 framing-disjoint reviews + fix-up + live validation.
Review: `docs/reviews/code-review/v4.7.33_af5_ttl_suppression.md`.
**Baseline tag:** `pre-review-v4.7.33`.

## Institutional context verified
- **Grep `_suppressed_entities` / `suppress(` / `unsuppress(`** across
  `custom_components/` — found the field + 5 internal `add()` sites in
  `hvac_override.py` and 9 external callers (`hvac.py` ×7, `hvac_predict.py` ×2).
  REUSED the existing `suppress()`/`unsuppress()` public API (signatures unchanged);
  the only NEW symbol is the module const `SUPPRESS_TTL_SECONDS` (no equivalent
  existed — it is an internal timing primitive, deliberately NOT a Number entity per
  the Parsimonious Room Config policy).
- **Read end-to-end:** `hvac_override.py` suppression surface (field init, `suppress`/
  `unsuppress`, `_handle_climate_change`, `_revert_override`, `_restore_after_reset`,
  the soft-nudge sites); every external call site in `hvac.py` / `hvac_predict.py`.
- **Memory pulled:** `project_session_pickup_2026_06_08.md` (the A-F5 entry that scoped
  this), which named the exact defect, line refs, and the operator's TTL proposal.
- **Design doc:** none specific to the arrester; the cycle is internal to the HVAC
  override path.

## The defect
v4.7.32 made `_revert_override` (`hvac_override.py:851`) fire TWO climate service calls
under a single `suppress()` — `set_hvac_mode heat_cool` then `set_preset_mode` — but the
suppression mechanism was a `set[str]` that the listener popped on the FIRST resulting
state event. So the SECOND URA-generated event ran unprotected through override
detection and could re-arm the arrester. Any thermostat that emits multiple settle
events per service call hit the same latent class.

## What changed
- Replaced `_suppressed_entities: set[str]` + single-discard with
  `_suppressed_until: dict[str, datetime]` — a **5s TTL window** (`SUPPRESS_TTL_SECONDS`).
  `suppress()` opens the window; `unsuppress()` pops it (error path); the listener
  checks `now < until` WITHOUT popping a still-valid entry (survives N settle events)
  and cleans expired entries.
- All 5 internal suppression sites routed through `self.suppress()`.
- **Review HIGH fix — mid-window manual passthrough:** URA never writes
  `preset_mode=manual`, so a fresh non-manual→manual transition inside the window is
  unambiguously a USER override → the listener drops suppression and falls through to
  detection. This preserves the arrester's core job (the fixed window otherwise swallows
  a real override landing within 5s of a URA write). All of URA's own settle events
  stay suppressed.
- **Review HIGH fix — disable hygiene:** the `enabled` setter now clears
  `_suppressed_until` on disable (symmetry with the other in-flight state it clears).

## Why it's safe
- **External contract preserved (Review B):** the dict is entity-keyed, so a lingering
  window on one zone never masks another; every error-path `unsuppress()` still closes
  the window; one site uses `finally: unsuppress`. The TTL change is a strict net
  improvement — it closes a latent multi-settle-event leak the old single-pop had at
  every single-write site, reducing spurious NM override alerts.
- **A-F5 not re-opened by the passthrough:** `_revert_override`'s two events are
  (1) `set_hvac_mode` (preset unchanged — never a fresh non-manual→manual transition)
  and (2) `set_preset_mode` to a NON-manual original_preset; neither matches the
  passthrough predicate, so both stay suppressed.
- **Restart-safe:** `_suppressed_until` is in-memory only; a 5s window is meaningless
  across a 30s+ restart, so starting empty is correct. No RestoreEntity interaction.

## Acceptance criteria
### In-suite (proven pre-deploy)
- **Test:** `test_override_arrester_ttl_suppression.py` (11) — drives the real
  `suppress`/`unsuppress`/`_handle_climate_change` via a fake clock + a
  `_find_zone_by_entity` spy (no re-implementation). Core guards:
  `test_two_consecutive_events_both_suppressed` (fails against the old set-model),
  `test_user_override_passthrough_mid_window` (HIGH fix 1),
  `test_disable_clears_suppression_window` (HIGH fix 2),
  `test_suppression_is_per_entity`, `test_suppress_before_first_service_call_in_revert_override`.
- **Test:** `test_v4511_ac_energy_aware_ramp_down.py` (160) — soft-nudge ordering guard
  updated to the new `self.suppress(...)` API; passes.
- **Suite:** baseline-diff vs `pre-review-v4.7.33` = **zero new failures** (39 pre-existing
  flakes identical on both trees).
- **Migration:** `grep _suppressed_entities hvac_override.py` → nothing.

### Live Validation (prospective — to be written back post-restart)
- **Live:** v4.7.33 loaded — `update.universal_room_automation_update`
  `installed_version=v4.7.33`.
- **Live:** Zero URA errors post-boot — error_log ERROR search "universal_room_automation"
  → 0 lines.
- **Live:** Override arrester active — no `_suppressed_entities` AttributeError / no
  arrester traceback in logs (proves the field rename took on the running instance).
- **Live (trip-wire):** A real override revert (`Override revert on … restoring preset`)
  followed by NO spurious re-detection on the same entity within 5s — observable
  opportunistically when a manual override actually happens; NOT a scheduled watch
  (no-soak policy). Mechanism proven in-suite by the 11 behavioral tests.

## Notes / accepted trade-offs (from review)
- **Wall-clock TTL (LOW):** the 5s window uses `dt_util.now()` (wall clock). A remote
  thermostat whose settle event lands >5s after the write could be misread — benign by
  construction for `_revert_override` (revert targets a non-manual preset, which
  detection ignores). TTL kept at 5s; bumping it would widen the user-override blind
  window the worse direction. Accepted.
- **Stale-entry cleanup (LOW):** `_suppressed_until` only prunes on a later event for
  that entity; an entity that never re-emits leaves one stale entry. Bounded by zone
  count (~30 × ~100 bytes) — not a leak. Re-evaluate only if TTL or zone count grows.
- **Source-substring ordering guard (LOW):** the `_revert_override` ordering test is a
  best-effort static check (fragile to renames), consistent with the existing
  soft-nudge guard.
