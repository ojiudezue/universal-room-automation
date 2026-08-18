# Code Review A — Census Toggles → Device Switches

**Cycle:** CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1
**Branch:** `feature/census-toggles-switches` (commit `fb6f771a1`)
**Reviewed from:** worktree `.claude/worktrees/census-switches` (three-dot diff `develop...HEAD`)
**Framing (A):** Correctness + INV-1 (switch `is_on` ⇔ `entry.options[KEY]` ⇔ consumer read); default-flip readers; availability/scope; entity-id/unique-id stability.
**Verdict:** **SHIP.** No CRITICAL/HIGH findings. Two LOW notes + one behavioral-change INFO.

---

## Summary

Two new integration-entry device switches (`switch.ura_presence_face_matching`, `switch.ura_name_people_at_doors`) are added via a new shared class `_IntegrationOptionsSwitch` in `switch.py`. Both are read-write against `entry.options` on the INTEGRATION entry only (not duplicated per-room), with the parent-reload storm suppressed by the `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` branch already in `_async_update_listener`. `CONF_FACE_RECOGNITION_ENABLED` uses a discharge signal (`SIGNAL_URA_FACE_RECOGNITION_CHANGED`, fired dually from the switch AND the reload-suppress branch — idempotent) to refresh the two cached consumers (`transit_validator.py:259`, `presence.py:2451`). `CONF_EGRESS_IDENTITY_ENABLED` is fresh-read at every consumer (`camera_census._is_egress_identity_enabled`, plus the indirect path via `transit_validator.py:1158`), so no signal is wired.

The cycle test file passes (21/21) and mutation-anchored around the load-bearing invariants (default flip, signal wiring, entity-id pin, dual-fire idempotency, no-reload).

## INV-1 audit — holds

- `is_on`: `bool(merged.get(self._conf_key, self._default))` — merges `data | options`, defaults to `DEFAULT_*` (True for both). Correct.
- `entry.options[KEY]` write: `_write` calls `async_update_entry(entry, options={**entry.options, key: value})` before `async_write_ha_state`; `async_update_entry` is a synchronous mutation, so subsequent `is_on` reads observe the new value immediately. Correct.
- Consumer read: every reader I could find uses the merged-with-`DEFAULT_*` shape (see "Default-flip audit"), so a switch-toggle observed via the discharge signal (face-recog) or fresh-read (egress) reflects the persisted value.
- Listener path: on any options-mutation the switch fires the signal first (subscriber refresh available BEFORE the listener runs); the listener then re-fires the same signal via `_INTEGRATION_KEY_SIGNAL_TABLE`. Both re-reads see the identical persisted value; the second is a no-op. Idempotent.

## Default-flip audit — all callers updated

Every current reader of `CONF_FACE_RECOGNITION_ENABLED` and `CONF_EGRESS_IDENTITY_ENABLED` was checked; each either uses the new `DEFAULT_*` constant or is an initializer/reset:

| Site | Behavior |
|---|---|
| `transit_validator.py:197` | init to `False` before `async_init` — intentional pre-boot guard, not a merged-read. Fine. |
| `transit_validator.py:266` | uses `DEFAULT_FACE_RECOGNITION_ENABLED`. |
| `transit_validator.py:368` | signal handler uses `DEFAULT_FACE_RECOGNITION_ENABLED`. |
| `presence.py:2456` | uses `DEFAULT_FACE_RECOGNITION_ENABLED`. |
| `presence.py:2488` | signal handler uses `_DEF_FR`. |
| `presence.py:2466` | `except Exception → False` — see A-LOW-2. |
| `camera_census.py:2866` | uses `DEFAULT_EGRESS_IDENTITY_ENABLED`. |
| `switch.py:_IntegrationOptionsSwitch.is_on` | uses `self._default`. |
| `config_flow.py:2960/2976` | uses new defaults. |

No orphaned `.get(KEY, False)` literal remains.

## Availability / scope

- Switches are added ONLY inside the `if entry_type == ENTRY_TYPE_INTEGRATION` branch (`switch.py:154`). Not duplicated per-room. Correct.
- No `available` override — defaults to `True`; entity only exists while the integration entry is loaded (unloaded via platform teardown). Fine.
- `unique_id = f"{DOMAIN}_{unique_suffix}"` stable across restarts; `entity_id` pinned via `self.entity_id = f"switch.{object_id}"` before add-to-platform — first-registration slug is deterministic, later re-registrations respect the registry entry. Correct.

## Translations

`translations/en.json` and `strings.json` both carry `entity.switch.presence_face_matching` and `entity.switch.name_people_at_doors` with matching `name` + `description` payloads. Path shape matches sibling entries (`optimizer_kill_switch` etc.). Fine.

---

## Findings

### A-LOW-1 — `_write` fires the discharge signal on no-op writes
**Bug class:** #46 (dispatcher over-fire) — informational.
**Where:** `switch.py:_IntegrationOptionsSwitch._write` fires `self._fire_signal` unconditionally, without comparing `old` vs `value`.
**Impact:** Toggling from ON → ON (or a UI double-tap) dispatches the signal; subscribers re-read the same value; no observable effect. HA's `async_update_entry` itself de-dupes same-value writes so the listener's `_dispatch_integration_key_signals` path is naturally skipped for a real no-op, but the switch fires eagerly.
**Fix (optional):** wrap in `if self._fire_signal is not None and old != value:`. Not required — behavior is defensively idempotent by design.

### A-LOW-2 — presence.py `except → False` clobbers a good cached value on transient boot errors
**Bug class:** #21 (silent state loss on generic except).
**Where:** `domain_coordinators/presence.py:2465-2470`.
**Impact:** If `async_setup` re-runs (e.g. rebuild path) and `async_entries` transiently raises, `self._face_recognition_enabled` is force-cleared to `False` — the switch UI would still show ON while the coordinator distrusts face-recog. INV-1 violation. Documented as intentional (degrade-closed) in the code comment, and the discharge signal re-heals it on the next toggle or listener fire. Low severity because the exception path is rare (`hass.config_entries.async_entries` is in-memory).
**Fix (optional):** narrow the except to `AttributeError, KeyError`; leave existing cached value alone otherwise. Not required — current behavior is a documented, conservative safety choice.

### A-INFO — Default-flip changes live behavior for existing installs on first boot post-deploy
Existing installs whose operator never opened the options flow have `entry.options` MISSING both keys. After this deploy, all readers return `True` via the new `DEFAULT_*` constants. Effect: face-recognition trust in `transit_validator` and `presence`, plus egress-identity fusing in `camera_census`, silently activate at the first restart. This is the stated intent of the cycle (const.py comment: *"defaults ON so validation occurs in production; the switch itself is the operator's live kill-switch backstop"*) and is guarded by the two new switches. Flagging so the README's live-validation block treats "face-recog trusted a person on first post-restart transit" and "egress event carried a `person_id` on first door crossing" as EXPECTED, not regressions.

---

## Not findings (checked and clean)

- `_write` write-then-state ordering: `async_update_entry` is synchronous → `is_on` sees the new value before `async_write_ha_state` is called. No race.
- `is_on` merge order `{**data, **options}` — options wins, matching every other integration-options reader. No path where a stale `data` shadows a persisted `options` toggle.
- Concurrent toggles: event loop serializes; no shared mutable state beyond `entry.options` itself.
- `enhanced_census` intentionally NOT exposed as a switch (confirmed by test `test_enhanced_census_not_exposed_as_switch`).
- Snapshot `integration_last_applied_options` is seeded on setup (`__init__.py:3881`) so the first post-deploy switch toggle's `changed_keys` is `{KEY}` (subset of allowlist) → suppress branch fires, not reload. Verified.
- Reload-suppression math holds: both keys are in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`; `_INTEGRATION_KEY_SIGNAL_TABLE` has the face-recog entry only, egress absent by design (fresh-read).

---

## Verdict

**SHIP.** INV-1 holds across all reachable paths. Default-flip readers uniformly updated. Two LOW notes are optional polish; the INFO is expected-behavior-on-deploy that the README should acknowledge in the live-validation table.
