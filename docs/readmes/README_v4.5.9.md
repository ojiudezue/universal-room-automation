# v4.5.9 — HVAC cover dispatch tilt-awareness + intent-respecting management

**Date:** 2026-05-10
**Type:** Tier 2 cycle (~330 LoC production + ~520 LoC tests; touches 4 production files + new docs/review)
**Predecessor:** v4.5.8

## Summary

Two distinct fixes shipped together because they share the same dataclass + dispatch loop in `domain_coordinators/hvac_covers.py`:

1. **Bug Class #33 closure (third hit):** v4.5.0.4 made the per-room cover dispatcher tilt-aware; v4.5.6 made the per-room gate helpers tilt-aware; **neither cycle audited the HVAC coordinator's separate cover-dispatch path.** Live confirmed on 2026-05-09 18:00 CDT when HVAC's solar-window-end open command raised Study A and Master Bedroom venetian blinds (position 0→100, slats stuck at tilt=0) instead of tilting slats open at position=0.

2. **Intent-respecting cover management** (user-flagged 2026-05-09): pre-v4.5.9 the controller closed every discovered cover when conditions converged, regardless of whether the room intended that cover to be open. It then reopened every cover at end-of-window via a single `_covers_closed: bool`, including covers HVAC didn't close and covers the room never wanted open. Per-room `cover_open_mode = none` rooms were treated identically to `at_time` rooms.

Both addressed in one v4.5.9 cycle to avoid two restarts in a day, share the test infrastructure, and force a coordinated design (closed-set tracking depends on dispatch landing the right service for tilt covers).

## What changed

### D1 — Dispatch tilt-awareness (Bug Class #33 third hit)

**`ManagedCover` dataclass gains two fields:**

```python
@dataclass
class ManagedCover:
    entity_id: str
    cover_type: str = COVER_TYPE_SHADE      # NEW v4.5.9: "shade" or "tilt"
    owning_room_name: str = ""              # NEW v4.5.9: room that owns this cover
    last_command_time: str = ""
    manual_override_until: str = ""
```

**`discover_covers` resolves cover_type via three-tier strategy:**

1. **Room-derived (preferred):** for room-sourced covers, read `CONF_COVER_TYPE` from the owning room's entry.
2. **Auto-detect:** for CM-level covers (no owning room) OR rooms without `CONF_COVER_TYPE`, read the entity's `supported_features` bitmask. If it has tilt bits (`OPEN_TILT=128, CLOSE_TILT=256, SET_TILT_POSITION=64`) AND `current_tilt_position` attribute is exposed, classify as tilt.
3. **Default "shade"** preserves pre-v4.5.9 dispatch.

**New per-cover dispatch helpers `_command_close_one` / `_command_open_one`:**

```python
if cover.cover_type == COVER_TYPE_TILT:
    service = "close_cover_tilt"   # or "open_cover_tilt"
else:
    service = "close_cover"        # or "open_cover" (unchanged)
```

**New `_is_cover_already_in_target_state` is tilt-aware** with the same 5/95 thresholds the v4.5.0.4 verify path + v4.5.6 gate helpers use — all four sites in URA now agree on what "closed" / "open" means for tilt blinds.

### D2 — Per-cover closed-set replaces single bool

`self._covers_closed: bool` → `self._hvac_closed: set[str]` of entity IDs HVAC explicitly closed in the current solar window.

**Close phase:** per-cover, gated by intent + occupancy + manual override. Adds successful closes to `_hvac_closed`.

**Open phase:** ONLY iterates `_hvac_closed` (not all managed covers). Drops covers where:
- the cover got removed from discovery mid-day (`if cover is None: discard`)
- the user manually re-opened during the closed window (`if manual_override_until > now: discard`)

Then opens what's left and clears the set.

This is the architectural fix for "HVAC opens every cover at 18:00, including covers it didn't close." Now HVAC opens *only* what HVAC closed.

### D3 — Intent-respecting close via per-room predicate

New helper on `RoomAutomation`: `is_cover_currently_intended_open(now: datetime) -> bool`.

| `cover_open_mode` | Returns |
|---|---|
| `none` | False (manual-only; HVAC must not touch) |
| `on_entry` | False (occupancy-driven; HVAC can't predict future occupancy) |
| `at_time` | True iff in time window |
| `on_entry_after_time` | True iff in time window |
| `at_time_or_on_entry` | True iff in time window |

`CoverController._should_hvac_close` calls this before closing any cover. CM-level explicit covers (no owning room) bypass this gate — user added them deliberately to the HVAC list.

**Behavior change from a user's perspective:** rooms with `cover_open_mode = none` now never have HVAC issue close on them. Rooms with `cover_open_mode = on_entry` (occupancy-only) also skip — explicit trade-off; switch to `at_time_or_on_entry` if you want HVAC management.

### D4 — `CONF_COVER_HVAC_MANAGED` per-room opt-out

New per-room CONF, default `True`. Form field added to the cover_behavior step (both setup and reconfig flows). Read by `discover_covers` — covers from rooms with this set to False are excluded from `self._covers` entirely. Per-room cover automation still runs; HVAC just doesn't touch them.

Use cases: master bedroom where someone naps, kid's room, library with light-sensitive art.

The cover step is now **11 fields** (was 10). Bumped past the v3.x D3 soft 10-field UX limit; documented in test_cycle_b_config_flow with comment that pushing to 12 should do another step split.

### D5 — Occupancy-aware close skip

`CoverController._should_hvac_close` skips covers in occupied rooms unless room temp is meaningfully above the zone's cooling setpoint.

- Threshold: `OCCUPIED_CLOSE_TEMP_DELTA = 2.0°F` (matches v3.8.4's `fan_activation_delta` for symmetric comfort tolerance)
- Vacant rooms: always allow close
- Missing room temp or setpoint data: defer (return True; let other gates decide)

Avoids ruining a sunny afternoon in an occupied room that's still comfortable.

### D6 — Diagnostic surfacing

`get_cover_status` now returns:

```python
{
    "managed_covers": ...,
    "managed_tilt_covers": ...,    # NEW v4.5.9
    "managed_shade_covers": ...,   # NEW v4.5.9
    "hvac_closed_set": [...],      # NEW v4.5.9: sorted list of entity IDs HVAC has closed right now
    "hvac_closed_count": ...,      # NEW v4.5.9
    "covers_closed": bool(...),    # back-compat: any HVAC-closed?
    "manual_overrides": ...,
}
```

So you can see at a glance from the HVAC mode sensor which covers HVAC currently has closed.

## What this DOES NOT do

- **Doesn't extend manual-override duration** beyond 2 hours (L2 deferred — needs design conversation)
- **Doesn't add forecast-aware skip** when peak < 90°F (L3 deferred — threshold tuning)
- **Doesn't add per-orientation classification** (L4 deferred — significant rework, v4.6.x candidate)
- **Doesn't integrate sleep mode** (L5 deferred — edge case)
- **Doesn't add soft-gradient close** via `set_position` (L6 deferred — adds complexity, only works for shade)
- **Doesn't add heating-season inverse** (L7 deferred — separate v4.6.x consideration)
- **Doesn't persist `_hvac_closed` or `manual_override_until` across restarts.** Documented in v4.5.9_review.md as a LOW-severity edge case.

## Tier 2 Review

Two reviews + this README's live validation plan = full Tier 2 protocol. Detailed findings in `docs/reviews/code-review/v4.5.9_review.md`.

| Severity | Finding | Resolution |
|---|---|---|
| (no CRITICAL) | — | — |
| (no HIGH) | — | — |
| MEDIUM | Cover step now 11 fields, exceeds v3.x D3 10-field UX soft limit | Documented in test bump; if pushed to 12 in a future cycle, do another step split |
| LOW | `_get_room_coordinator` duplicated between hvac_covers.py and hvac_predict.py | Acceptable; small helper, factoring would add more surface than it saves |
| LOW | Intent predicate returns False for `cover_open_mode = on_entry` (HVAC can't predict future occupancy → conservative) | Documented; users wanting HVAC mgmt should use `at_time_or_on_entry` |
| LOW | Manual-override stamps in-memory; lost on restart inside close window | Documented in review; persistence pass deferred |
| LOW | `_zone_manager.zones` mutation during iteration could raise RuntimeError if zone reconfigure lands mid-cycle | Low probability; defensive snapshot deferred |

**Verdict: APPROVED for deploy.**

## Tests

52 new tests in `quality/tests/test_v459_hvac_cover_intent.py`:

- **D1 cover_type resolution (7):** room-declared wins, auto-detect via features+attr, default shade fallback
- **D1 dispatch service selection (4):** tilt × {open, close} → `_tilt` services; shade → unchanged
- **D1 already-in-target tilt-aware (11):** thresholds at 0/5/6/94/95/97; no-attr fallback; missing state
- **D3 intent predicate (8):** all 5 cover_open_mode values × time-window edges
- **D5 occupancy-aware close (7):** vacant always allows, occupied at-setpoint blocks, occupied 1-above blocks, occupied at-threshold (2°F) allows, occupied well-above allows, missing-data defers
- **D2 closed-set lifecycle (4):** open phase only touches set, manual override drops from set, removed cover drops from set, set empty after open
- **D4 opt-out filter (2):** opt-out room excluded, default True includes
- **Source contract (9):** ManagedCover has cover_type, dispatch uses tilt services for tilt covers, already-in-target tilt-aware, closed-set replaces bool, _should_hvac_close consults intent+occupancy, intent predicate exists on RoomAutomation, CONF_COVER_HVAC_MANAGED read in discover_covers (Bug Class #32 prevention), diagnostic attrs exposed

Mirror-style — same pattern as v4.5.0.4 / v4.5.3 / v4.5.6 / v4.5.7 / v4.5.8.

**Test count progression:**
- v4.5.8: 2002 tests, 0 isolated failures across 56 files
- **v4.5.9: 2054** (+52), 0 isolated failures across 57 files

## Live validation (post-restart)

Detailed plan in `docs/reviews/code-review/v4.5.9_review.md` "Live validation plan." Summary:

1. **Immediate post-restart:** no errors, HVAC mode sensor exposes new attrs (`hvac_closed_set` empty, `managed_tilt_covers` count populated).
2. **Next solar window (~13:00 CDT, hot day):** HVAC closes specific covers per intent gate. Tilt covers get `cover.close_cover_tilt` (NOT `close_cover`); slats tilt to ≤5; blind position stays at intended position. Rooms with `cover_open_mode = none` or `cover_hvac_managed = False` untouched. Occupied rooms at-setpoint skipped.
3. **Solar window end (~18:00 CDT):** ONLY covers HVAC closed get reopened. Tilt covers get `cover.open_cover_tilt`; slats tilt to ≥95. `hvac_closed_set` clears.
4. **Manual-override smoke test:** open a cover HVAC closed → next coordinator tick HVAC doesn't re-close → at end-of-window HVAC drops from set, doesn't reopen.

## Deploy notes

- No DB schema changes
- No migration needed (`CONF_COVER_HVAC_MANAGED` defaults True; missing key reads as True)
- HACS download required after deploy.sh
- HA restart required (hvac_covers.py + automation.py + const.py + config_flow.py all touched)

## Documents

- Plan: `docs/planning/PLANNING_v4.5.9_hvac_cover_intent.md`
- Review: `docs/reviews/code-review/v4.5.9_review.md`
- Bug class #33 narrative updated in `docs/QUALITY_CONTEXT.md`
- VibeMemo decision trail: entry [009](../../.vibememo/users/ojiudezue/entries/009_hvac_cover_intent_v459.json) (related to entry 008's solar-gain controller WHY capture)

## Next

- **v4.6.0** — Routine Awareness with reconciled AnomalyEvent foundation
- **Sensor Health Surfacing** (backlog) — chattering + stuck-on detection per the 2026-05-08 Kitchen mmWave investigation
- **CM cleanup cycle** — `CONF_MUSIC_FOLLOWING_ENABLED` + `CONF_COMFORT_ENABLED` + unused `"comfort"` slot
- **Cover livability v2** (backlog) — L2-L7 from v4.5.9 plan: extended manual override, forecast-aware skip, per-orientation classification, sleep integration, soft-gradient close, heating-season inverse
