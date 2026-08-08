# URA v5.61.0 — Straggler batch: linker allowlist, arrester sunset, transit diagnostic

Three fixes. Review record: `docs/reviews/code-review/v5.61.0_straggler_batch.md`.
**Tier 2-DB** (live HVAC comfort governance + security observation scope) — 3 framing-disjoint
reviews found **2 CRITICAL + 6 HIGH**, all fixed, orchestrator drill-verified.

## SECC-1 — interior cameras were being tracked as exterior tracks

**Problem:** the exterior open-tracks diagnostic held tracks for interior cameras
(`armcrestash41b` = Study A, `playroom`), and `ignored_offlist_events` was empty — nothing was
being rejected. **Root cause (deeper than first diagnosed):** `set_allowed_cameras` has one caller,
inside `PerimeterAlertManager.async_setup()`, guarded on the linker being present in `hass.data` —
but setup runs at `__init__.py:2414` and the linker is only registered at `:2451`. **The allowlist
install has never run, on any boot.** The `SIGNAL_EXTERIOR_LINKER_READY` signal existed but the
perimeter manager never subscribed.

**Fix:** subscribe to the READY signal and install there (unsub tracked); WARN instead of silently
no-oping; `_allowlist_installed` keeps the **pre-fix admit-all behavior during the bootstrap window**
and only fails closed *after* a confirmed install — so a real perimeter event can never be dropped
at boot; boot-sanity WARNING if perimeter cameras are configured but the allowlist is empty;
`ignored_offlist_events` capped at 128 keys and cleared on install.

## ARREST-SUNSET-1 — Temp Arrester Override didn't release when it should

**Problem:** `sunset_temp_arrester_override` hardcoded `house_state == "sleep"` while its sibling
`sunset_immune_holds` used a shared constant — a policy fork. Going **away or on vacation left the
override engaged**, suppressing the arrester in an empty house.

**Fix — operator-directed contract:**

> Flipping it on buys at least **15 minutes**. If a real context change happens inside that window,
> it ends the moment the window does. Otherwise any real context change ends it — except
> `arriving`, `guest`, `waking` — and it expires on its own after **6 hours**.

- Single predicate `house_state_invalidates_arrester_hold()` consumed by **both** sunset sites
  (the fork was the bug); denylist `ARRESTER_HOLD_PRESERVING_STATES = {arriving, guest, waking}` so
  an unclassified future state defaults to *invalidating* (fail-safe).
- `ARRESTER_OVERRIDE_MIN_LIFE_S = 900` grace that **defers** rather than discards: a blocked sunset
  records a pending obligation, discharged by a one-shot timer with the periodic sweep as backstop.
- Timer cancelled on teardown; stale pending cleared on re-engage; NM "ended (auto)" note fires on
  the timer path too, deduped per engagement.
- **Intentional ripple, operator-ratified:** person-scoped immune holds share the predicate, so a
  manual thermostat change now releases at the next real context change (e.g. ~5pm `home_evening`)
  instead of surviving to bedtime. Operator: *"I generally want manual control to be short lived
  else what's the point of all the code? Manual is wasteful generally. It's easy to re-engage."*

## TRANSIT-DIAG-1 — v5.60.0's checkpoint inventory is now observable

`checkpoint_cameras_by_area` + `protect_sourced_count` are exposed on the existing presence
diagnostic sensor (reused, not a new entity). v5.60.0's live validation had required raising the log
level and forcing a rebuild just to read it.

## Acceptance criteria

- **Verify (suite):** 8380 passed; failing-name diff vs baseline = 0. PASS pre-deploy.
- **Live (the CRITICAL):** post-restart the linker's allowlist is **non-empty** — no boot-sanity
  WARNING, and `ignored_offlist_events` starts counting interior events instead of sitting empty.
- **Live:** no interior camera appears in `open_tracks` on the exterior diagnostic.
- **Live:** presence diagnostic exposes `checkpoint_cameras_by_area` with all five checkpoint areas.
- **Live (organic):** the operator's engaged override releases on the next real context change
  (or its 6h decay), and the switch flips OFF to match.

## Live Validation

(prospective — replaced with the Validated table post-restart)
