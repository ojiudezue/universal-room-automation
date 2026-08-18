# Plan Re-Review #2 — Census Toggles → Device Switches (revised)

**Reviewed doc:** `docs/planning/PLANNING_census_toggles_to_device_switches.md` (revised)
**Prior review:** `docs/reviews/code-review/census_toggles_switches_plan_review.md`
  (PLAN-NEEDS-FIXES: 1 CRIT + 2 HIGH + 3 MED/LOW)
**Tier:** 2-DB (revised plan self-elevated per prior finding)
**Reviewer:** ura-reviewer (plan re-review pass, framing-disjoint from prior:
  focus = fix correctness + completeness + no-new-gap; adversarial re-grep of
  the discharge / cleanup / default-flip surface)
**Date:** 2026-08-18
**Verdict:** **PLAN-READY** — all six prior findings correctly and completely
addressed; two LOW polish notes for the build brief (non-blocking).

---

## Independent verification — face_recognition consumer + subscriber coverage table

`grep -rn "CONF_FACE_RECOGNITION_ENABLED\|_face_recognition_enabled" custom_components/`
(re-run 2026-08-18, plan hypothesis independently re-enumerated — I did NOT
inherit the plan's list).

| Site | file:line | Role | Cached? | Discharge covered by revised plan? |
|---|---|---|---|---|
| Constant def | `const.py:2180` | — | — | n/a (new `DEFAULT_FACE_RECOGNITION_ENABLED = True` to be added, D3) |
| Import | `transit_validator.py:28` | — | — | n/a |
| Instance init | `transit_validator.py:195` | `self._face_recognition_enabled = False` (bare init before `async_init`) | attr default | not a `merged.get` — no default-flip needed here; safely overwritten at `:259` and by the new signal handler |
| **Boot cache read** | `transit_validator.py:259` | `merged.get(CONF_FACE_RECOGNITION_ENABLED, False)` → cached attr | **YES** | **YES** — D2 subscribes `SIGNAL_URA_FACE_RECOGNITION_CHANGED` in `async_init`, handler re-runs the same read, unsub mirrors `_config_signal_unsub` teardown at `:823-827` (verified pattern exists) |
| Attr read (log arg) | `transit_validator.py:421` | reads cached attr | — | covered by cache-refresh via D2 |
| Attr read (decision) | `transit_validator.py:546` | reads cached attr | — | covered |
| Attr read (decision) | `transit_validator.py:768` | reads cached attr | — | covered |
| Import | `config_flow.py:342` | — | — | n/a |
| Options-flow field | `config_flow.py:2958-2959` | `default=self._get_current(..., False)` | render-time only | D3 flips inline `False` → `DEFAULT_FACE_RECOGNITION_ENABLED` — correct |
| Instance init | `presence.py:1575` | `self._face_recognition_enabled: bool = False` | attr default | safe (same reasoning as tv:195) |
| Import (fn-local) | `presence.py:2447` | — | — | n/a |
| **Boot cache read** | `presence.py:2451` | `merged.get(..., False)` → cached attr | **YES** | **YES** — D2 subscribes new signal in `async_setup`; unsub appended to `self._unsub_listeners` (verified: this is the file's convention; torn down by `_cancel_listeners` from `async_teardown` at `:7195+`, which is the correct sibling pattern the plan alludes to as "the coordinator's normal unsub list") |
| Exception fallback | `presence.py:2454` | `self._face_recognition_enabled = False` on except | error-path attr set | **note L-1** below (non-blocking) |
| Attr read (decision) | `presence.py:4465` | reads cached attr | — | covered by cache-refresh via D2 |

**Result:** consumer enumeration is COMPLETE. Every boot-cached consumer of
`CONF_FACE_RECOGNITION_ENABLED` has a discharge subscription in the revised
plan. No orphan cache. Suppression-needs-discharge invariant is satisfied.

**Egress-identity fresh-read verification (path (a)):**
`camera_census._is_egress_identity_enabled()` (`camera_census.py:2858-2870`)
scans `hass.config_entries.async_entries(DOMAIN)` for the INTEGRATION entry
and reads `merged.get(...)` on every call — verified fresh-read. All downstream
call sites (`camera_census.py:1886, 2889, 2943, 3657` and the indirect
`transit_validator.py:1094`) route through this helper. No cache exists;
allowlist-only entry (no signal) is correct.

---

## Q1 — Signal-discharge completeness (suppression-needs-a-discharge)

**PASS.** Only two boot-cached consumers exist (table above); both subscribe
via D2. Cleanup is specified for both:

- Transit validator: revised plan cites the sibling `_config_signal_unsub`
  teardown at `:823-827` — verified present. Mirroring that pattern for
  `_face_recog_signal_unsub` prevents Bug Class #38 leak on unload.
- Presence: revised plan says "append to the coordinator's normal
  dispatcher-unsub collection." Verified: `self._unsub_listeners` (defined
  `:582`, appended to in the exact `async_setup` block the plan targets at
  `:2517-2628`, and torn down by `_cancel_listeners` called from
  `async_teardown`). This is unambiguously the right list.

Restart behavior: the boot read at `:259` / `:2451` re-primes the cache from
`entry.options` (persisted). No signal at boot; the boot IS the refresh.
Correct per plan's D2 note.

---

## Q2 — Dual-fire safety

**PASS.** The two fire sites are:
1. `_IntegrationOptionsSwitch._write` — direct `async_dispatcher_send` after
   `async_update_entry` returns.
2. `_dispatch_integration_key_signals` — invoked by `_async_update_listener`'s
   suppress branch (verified at `__init__.py:6647-6650`) after subset check
   passes.

Subscribers set `self._face_recognition_enabled = merged.get(...)` — an
idempotent bool assignment reading the SAME persisted value both times. No
side effect that isn't a bool swap. No cross-coordinator ordering hazard.
Belt-and-suspenders is a documented, harmless double-refresh.

Kill-switch behavior when `INTEGRATION_RELOAD_SUPPRESS_ENABLED = False`
(verified at `__init__.py:5938+6640`): listener falls through to full reload,
but the switch's own dispatcher_send still fires. Subscribers refresh cache,
then reload rebuilds them from scratch — still idempotent, still safe.

---

## Q3 — Allowlist extension does not break the 2026-08-15 mitigation's intent

**PASS.** Verified by re-grepping every consumer of the two keys being added:

- `CONF_FACE_RECOGNITION_ENABLED`: no structural setup branch exists (all 3
  consumer sites are boot caches in coordinators that are re-subscribable via
  signal; no `__init__.py` structural branch keys off it).
- `CONF_EGRESS_IDENTITY_ENABLED`: all consumers route through
  `camera_census._is_egress_identity_enabled()` fresh-read; no `__init__.py`
  branch reads it at setup.

`CONF_ENHANCED_CENSUS` correctly stays OFF the allowlist — its
`__init__.py:2253` structural setup branch is exactly the situation where a
suppress-only path silently would NOT re-run the setup logic. Parking that
key is the correct call and the plan states the revisit trigger clearly.

Snapshot bookkeeping (`_seed_integration_last_applied_options` +
`integration_last_applied_options` in `hass.data`, verified at
`__init__.py:6626-6660`) advances on the suppress path — a follow-up write to
either key still diffs correctly against the post-write baseline.

---

## Q4 — INV-1 tests non-hollow

**PASS.** Two dedicated tests are specified and each has a real production
oracle:

- `test_face_matching_toggle_does_not_reload_parent_entry`: observes (a) the
  suppress branch's INFO log line
  (`"INTEGRATION options changed for '%s' (%s) — in-place apply, suppressing reload"`
  — verified string at `__init__.py:6647`) AND (b) a sibling entity's
  `last_changed` not advancing across the toggle window. This is exactly the
  oracle prior review's FINDING-3 required — it observes the fall-through
  branch's absence, not the switch's own return path.
- `test_face_matching_signal_refreshes_cached_consumer`: writes via the real
  switch, subscribes the real transit_validator to the real dispatcher, then
  asserts the cached bool actually changed within one event-loop turn. Drives
  production code paths end-to-end; not a handler-called-directly stub. Good.

Cleanup test (`test_face_matching_signal_unsubscribes_on_unload`) covers
Bug Class #38. Restart-repopulation test covers the boot re-prime.

---

## Q5 — Default-flip correctness

**PASS with note.** `DEFAULT_FACE_RECOGNITION_ENABLED = True` is a NEW
constant. Verified no existing code depends on the currently-inline `False`:

- Every runtime read of `CONF_FACE_RECOGNITION_ENABLED` uses inline `False`
  as the default today; D3 replaces all such sites with the new constant.
- Test suite: `quality/tests/test_egress_face_identity_d1.py` explicitly
  passes `egress_identity_enabled=<bool>` to its `_make_census` helper and
  does not rely on `DEFAULT_EGRESS_IDENTITY_ENABLED`; no test grep-hit
  for `face_recognition_enabled` beyond the CONF-name imports. Default flip
  cannot silently break a test.
- `presence.py:2454`'s exception fallback stays `False` — this is an
  error-path degrade, orthogonal to the default flip. Fine to leave as-is;
  see LOW-1.

Both defaults flip live on deploy — clearly stated in "Default-flip
live-behavior note" (§ Scope) and again in D6 acceptance. D6 Live includes
the egress crossing check ("NO phantom guest is registered" on next real exit
crossing), which is the correct L3-organic-pending discriminator.

---

## Q6 — Anything the revision newly broke

**No new breakage introduced.** The scope reduction from 3 → 2 switches is
clean (enhanced_census parked with an explicit re-runnability trigger; no
dangling references to it remain in D0–D6). The allowlist expansion is
matched by discharge for the only cached key. The new signal is added to the
correct module (`domain_coordinators/signals.py`, alongside its sibling
`SIGNAL_URA_TRANSIT_CONFIG_CHANGED` — verified as house style). The
`_dispatch_integration_key_signals` helper (verified at
`__init__.py:5952-5978`) already iterates whatever keys are in the
`_INTEGRATION_KEY_SIGNAL_TABLE`; no code change needed there — the plan
correctly proposes only a DATA change (add one dict entry).

---

## LOW polish notes (non-blocking; forward to builder brief)

- **L-1 (LOW, note-only):** `presence.py:2454`'s exception fallback path sets
  `self._face_recognition_enabled = False` on read-failure. After the default
  flip that becomes asymmetric with the "healthy read" default (True). Not a
  correctness bug (the intent is "degrade closed on config-read failure"),
  but the reasoning is worth a one-line comment in the code so a future
  reader doesn't "fix" it to True and silently disable degrade-closed. Ask
  builder to leave the value False and add the rationale comment.
- **L-2 (LOW, note-only):** D5 Live asks operator to verify
  `transit_validator._face_recognition_enabled is True` "via a dev-tools
  template that reads the coordinator attr." That attribute isn't exposed
  through any entity today. Recommend the Live evidence be a log-scan
  (`grep face_recognition_enabled` in the URA logs on next relevant event)
  or the switch's `is_on` (which is the surface source of truth after the
  cycle). Non-blocking — pick one in the README write-back.

---

## Items the revision gets right (worth explicit note)

- Correct co-opting of the 2026-08-15 mitigation (path A, as prior review
  strongly preferred).
- Correct scope reduction (path (i) for enhanced_census — options-only —
  with a clean revisit trigger).
- Institutional-context section now cites the mitigation code end-to-end,
  including the snapshot bookkeeping site.
- Cost corrected to ~5 min + supervisor-watchdog; "avoids reload entirely"
  framing is accurate for the two in-scope keys.
- INV-1 rewritten with genuinely discriminating observations (points 3+4).
- Non-hollow reload-absence test spec matches FINDING-3's requirement
  (fall-through-branch oracle, not switch-method patch).
- Numbers-get-knobs placement is correct (rung 3 for both, with the
  existing `INTEGRATION_RELOAD_SUPPRESS_ENABLED` documented as the fire-axe).

---

## Verdict

**PLAN-READY.** All prior findings fixed correctly and completely. No new
gaps introduced. Dispatch build under Tier 2-DB (three framing-disjoint
reviews) as the revised plan specifies. Ask the builder to carry L-1 and
L-2 forward as pre-build polish.
