# v4.7.18.2 — Boot-warning dedup: per-ZONE "no room coordinators" log-once

**Tier 2 cycle (two framing-disjoint reviews).** ~34 LoC prod across `aggregation.py` (+39/-?) and `__init__.py` (+15/-5), + a 620-line behavioral+AST test module. Reviews: A = correctness/edge (SHIP, 0C/1H/2M/3L), B = async/lifecycle/restart (SHIP, 0C/0H/1M/2L). All findings fixed in one pass (`97f7a69`). Review docs: `docs/reviews/code-review/v4.7.18.2_review_A_correctness.md` + `_review_B_lifecycle.md`.

## The problem

Every HA restart, the aggregation layer emitted ~20 warnings like:

```
WARNING [custom_components.universal_room_automation.aggregation]
Zone 'Entertainment + Master Suite': No room coordinators found after 60s - zone may be empty or rooms not configured
```

Cosmetic, self-resolving (~60s), but noisy. Not a real bug — a **fan-out**: each zone spawns ~20 `ZoneSensorBase` entities, each runs its own 60s retry timer in `async_added_to_hass`, and if room coordinators haven't registered by t=60s they all warn at once. Only the largest HVAC zone (Master Suite) hits the timing window.

**Key lesson (why the first attempt was wrong):** a per-ENTITY log-once flag yields ZERO reduction — each of the ~20 entities already logs exactly once (its own timer cancels after firing). The ~20 lines come from ~20 DISTINCT entities, not one entity repeating. The fix must dedup **per ZONE**, not per entity. (First attempt `78b07cb` shipped the ineffective per-entity flag; reworked per-zone in `f941564`.)

## The fix — per-ZONE dedup set

A shared `set` at `hass.data[DOMAIN]["_no_coord_warned_zones"]`. In `ZoneSensorBase.async_added_to_hass`'s nested `_check_coordinators` retry-exhausted branch: the first entity per zone warns and records the zone; the rest skip. The set is cleared on Zone Manager AND integration-entry unload so a reload re-warns.

- **Success path (A-MED-1):** when coordinators DO become ready, `warned_zones.discard(self.zone)` so a later transient re-warns correctly.
- **Defensive read (B-LOW-2):** failure branch reads `hass.data.get(DOMAIN)` (not `setdefault`) — if the callback fires after teardown removed the DOMAIN bag, skip rather than resurrect it.

## Files changed

| # | File | What |
|---|---|---|
| 1 | `aggregation.py` | Per-zone dedup in `_check_coordinators` (failure branch warns-once-per-zone via `_no_coord_warned_zones`); success branch discards the zone from the set (A-MED-1); defensive `get(DOMAIN)` read (B-LOW-2). |
| 2 | `__init__.py` | `async_unload_entry`: integration-entry branch pops `_no_coord_warned_zones` before deleting the `integration` bag (B-MED-1); Zone-Manager branch pops it defensively (B-LOW-1) so reload re-warns. |
| 3 | Tests | `quality/tests/test_v4_7_18_2_boot_warning_logonce.py` — 8 tests (4 AST canaries asserting the per-zone set + `warned_zones.add(self.zone)` + absence of the dead `_coordinator_warning_logged` flag; 4 behavioral driving the real `async_added_to_hass` retry cycle, incl. late-coordinator discard). |

## Tier 2 review resolutions

| ID | Sev | Issue | Resolution |
|---|---|---|---|
| A-HIGH-1 | HIGH | Test authority — behavioral tests must drive the real `ZoneSensorBase.async_added_to_hass`, not a reimplementation. | **Fixed** — tests run the production coroutine; parent `AggregationEntity.async_added_to_hass` stubbed to async no-op (bare MRO would AttributeError at `super()`). |
| A-MED-1 | MED | Stuck zone never re-warns after a transient recovery. | **Fixed** — success branch `discard`s the zone from the set. |
| B-MED-1 | MED | Integration-entry unload deleted the `integration` bag without clearing the warned-zones set → stale set across reload. | **Fixed** — pop `_no_coord_warned_zones` first. |
| B-LOW-1 | LOW | Zone-Manager unload didn't clear the set → reload wouldn't re-warn. | **Fixed** — defensive pop on the zone-manager branch. |
| B-LOW-2 | LOW | Failure branch `setdefault` could resurrect a torn-down DOMAIN bag. | **Fixed** — read via `get(DOMAIN)`; skip if None. |

## Migration

- **No DB migration. No CONF migration. No new config knobs.** Pure log-noise dedup using a transient `hass.data` set.
- The set is integration-scoped and rebuilt every boot; nothing persisted.

## Live validation (post-restart)

```python
# HA error_log count for the string should drop to <=4 (one per HVAC zone max), was ~20:
# ha_get_logs source=error_log search="No room coordinators found after 60s" hours_back=1  -> <=4 lines
```

## Acceptance

```yaml
version: v4.7.18.2
hypotheses:
  - id: H1
    name: room_coordinator_warning_log_once_per_zone
    description: |
      Each HVAC zone emits the "No room coordinators found after 60s"
      warning at most once per boot (was ~20 from entity fan-out).
    query:
      kind: ha_log_count
      source: error_log
      search: "No room coordinators found after 60s"
      hours_back: 1
    expected:
      condition: "<="
      value: 4
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.18.1 — prior per-entity behavior restored. No persisted state shape changed; clean either direction.
