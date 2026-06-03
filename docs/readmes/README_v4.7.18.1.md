# v4.7.18.1 — SLEEP→WAKING deadlock hotfix (raw-signal wake timer + daytime backstop)

**Tier 1 hotfix, operator-elevated to Tier 2** ("I don't want to bork the build on this hotfix"). ~70 LoC prod in `presence.py` + 1 LoC `sensor.py` + 33 new tests. Two framing-disjoint reviews (A = correctness/edge, B = async/lifecycle/restart). A: SHIP (0C/0H/3M/4L). B: FIX-FIRST (1C/2H) — all fixed or document-accepted. Review docs: `docs/reviews/code-review/v4.7.18.1_tier1.md` + `_reviewerB.md`.

## The bug (live incident 2026-06-03)

House stuck in `SLEEP` for 13.75h. `wake_blocked_ticks=4666`, `census_count=2` (Jaya home all morning), `camera_occupied_count=0`.

`HouseState.SLEEP` has exactly two exits (`house_state.py:66-69`):

- **AWAY** requires `census_count == 0` — correctly blocked because someone is provably home.
- **WAKING** requires sustained zone occupancy — but the v4.7.15 D3 wake gate read `ZonePresenceTracker.mode`, and `set_sleep(True)` hard-sets every tracker's `_override = SLEEP` (`presence.py:351-357`). `mode` returns `_override` before `_derived_mode` (`:225-229`), so `mode` can NEVER report `OCCUPIED` during sleep → the sustained-occupancy timer never arms → WAKING is vetoed indefinitely.

Net: HVAC, lighting, and every house-state-driven behavior stays in sleep policy into the afternoon. The deadlock only surfaces when someone stays home all morning — otherwise `SLEEP → AWAY` masks the broken wake path.

## The fix — Option D ("Option D is gold")

### D1 — raw-signal wake timer (root cause)

New `ZonePresenceTracker.raw_occupied` property (`presence.py:234-244`) returns `_derived_mode == OCCUPIED`, bypassing the override. The WAKING sustained-occupancy timer is re-sourced from `any_zone_raw_occupied` (`:2544-2566`); the mode-based `any_zone_occupied` is left untouched for every other consumer. The gate's entire purpose is to detect movement *during* sleep — reading the sleep-masked `mode` was self-defeating.

**Fan-noise containment** (preserves v4.7.15 D3 intent): the engine only proposes WAKING *after* `sleep_end_hour` (`presence.py:522-532`), so a fan firing mmwave at 03:24 cannot wake the house — the gate isn't consulted mid-night. The 90s sustained threshold still applies — a brief blip resets the timer. Residual: a fan running continuously could make the gate pass immediately at `sleep_end_hour` (eager 6 AM wake). This is strictly better than an all-day deadlock and is a latency concern, not correctness. mmwave fan-rejection (sensor fusion / zone masking) is a tracked separate side-quest.

### D2 — daytime wake backstop (safety valve)

In the WAKING gate (`presence.py:2872-2925`, inside `if wake_decision.fired:`): if `census_count > 0` AND `sleep_end_hour + 3 <= local_hour < sleep_start_hour`, force WAKING (fall through without suppressing) and increment `_wake_backstop_fires`. Defends against any future masking regression that could re-trap the house. A-M2 fix clamps `_backstop_hour = min(sleep_end_hour + 3, sleep_start_hour - 1)` so the window can never go inert, with one-time `_backstop_clamp_logged` debug.

New counter `_wake_backstop_fires` (`presence.py:671-676`) surfaced as `wake_backstop_fires` attribute on the house-state sensor (`sensor.py:3854-3855`), next to `wake_blocked_ticks`.

## Files changed

| # | File | What |
|---|---|---|
| 1 | `domain_coordinators/presence.py` | + `raw_occupied` property (`:234-244`); + `_WAKE_BACKSTOP_HOURS_AFTER_SLEEP_END = 3` (`:109-114`); + `_wake_backstop_fires` counter (`:671-676`); wake timer re-sourced from `any_zone_raw_occupied` (`:2544-2566`); backstop block in WAKING gate (`:2872-2925`); boot-seed `_room_occupied` (`:1490-1515`) + `_camera_occupied` (`:1675-1696`) from live entity state at discovery (B-HIGH-1); B-HIGH-2 doc-and-accept comment (`:2611-2622`). |
| 2 | `sensor.py` | + `wake_backstop_fires` attribute on house-state sensor (`:3854-3855`). |
| 3 | Tests | + `quality/tests/test_v47181_sleep_wake_deadlock.py` (33 tests: 26 build + 7 fix-up). Sibling-test fixture repairs in `test_v4715_universalize_veto.py` + `test_v472_feature_b_guest_signal.py` (mock trackers set `raw_occupied`; char-window guards widened). |

## Tier 2 review resolutions

| ID | Sev | Issue | Resolution |
|---|---|---|---|
| B-CRIT-1 | CRIT | "Restart HA to confirm the house wakes from stuck SLEEP" is INVALID — `HouseStateMachine` does not persist `_state` (`manager.py:143` builds fresh; `house_state.py:111` inits AWAY; only `_transitions_today` hydrated). Restart resets to AWAY → HOME_DAY, auto-clearing the stuck-sleep WITHOUT exercising the fix. | **Fixed (plan, no code)** — rewrote Live Validation: 33 unit tests are primary proof; organic confirmation = next natural night→morning cycle. Deploying clears the live problem but proves nothing about the fix. |
| B-HIGH-1 | HIGH | Discovery didn't seed current sensor state → `raw_occupied` False on first tick post-boot. | **Fixed** (`1b6b192`) — boot-seed `_room_occupied`/`_camera_occupied` from `hass.states.get` at discovery, mirroring the handler predicates. |
| A-M2 | MED | Backstop hour window could go inert for short sleep windows. | **Fixed** — clamp `_backstop_hour` to `sleep_start_hour - 1`. |
| B-HIGH-2 | HIGH | `_run_inference` unserialized → cosmetic backstop double-count exposure. | **Document-and-accept** — pre-existing condition; WAKING transition is idempotent; no lock added to keep hotfix blast radius minimal. |

## Architectural finding (B-CRIT-1) — flagged, not scoped

`HouseStateMachine` does NOT persist `_state` across HA restart. Consequence: this fix is **inert at boot** (the house never boots into SLEEP) → zero regression risk; it only activates on the next organic SLEEP-with-someone-home. Whether house_state *should* persist across restart is a separate, undecided follow-up.

## Migration

- **No DB migration. No CONF migration. No new config knobs** (per `single-user-no-backcompat` + `configurability-clarity`).
- **First restart after deploy:** house initializes to AWAY → normal inference. The fix sits dormant until the next organic overnight SLEEP.
- **Rollback to v4.7.18:** clean — no persisted state shape changed.

## Live validation (post-restart)

Restart cannot reproduce the deadlock (B-CRIT-1). Post-deploy checks:

```python
# 1. Integration loads clean — no URA ERROR in the hour post-restart:
# ha_get_logs source=system_service slug=core | grep -E 'universal_room_automation.*ERROR'  → 0 matches

# 2. New attribute present + sane on the house-state sensor:
ha_get_state(
    "sensor.ura_presence_coordinator_presence_house_state",
    attribute_keys=["wake_backstop_fires", "wake_blocked_ticks"],
)
# wake_backstop_fires == 0 at boot (fix inert until next organic SLEEP).

# 3. House transitions sanely (AWAY → ARRIVING → HOME_DAY), NOT stuck.
```

**Organic confirmation** (next night→morning cycle, if someone stays home): `sensor.ura_presence_coordinator_presence_house_state` leaves SLEEP after `sleep_end` (by `sleep_end + 3h` at latest); `wake_blocked_ticks` stops climbing; `wake_backstop_fires` increments only if D2 was needed.

## Acceptance

```yaml
version: v4.7.18.1
hypotheses:
  - id: H1
    name: wake_backstop_fires_attribute_present
    description: |
      The house-state sensor exposes a wake_backstop_fires integer
      attribute (0 at boot since the fix is inert until the next organic
      SLEEP-with-someone-home).
    query:
      kind: ha_state_attribute
      entity: sensor.ura_presence_coordinator_presence_house_state
      attribute: wake_backstop_fires
    expected:
      condition: "is_numeric"
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h

  - id: H2
    name: house_not_stuck_in_sleep_during_day
    description: |
      During daytime hours (sleep_end+3 .. sleep_start) with someone home,
      the house must not remain in SLEEP. Either WAKING via sustained raw
      occupancy (D1) or the daytime backstop (D2) must release it. This is
      the core regression guard for the deadlock.
    query:
      kind: ha_state
      entity: sensor.ura_presence_coordinator_presence_house_state
    expected:
      condition: "not_equals"
      value: "sleep"
    window:
      first_check_after: 168h    # next night→morning cycle
      confirm_after: 336h
      alert_if_violated_after: 720h
      only_during: daytime_with_census_positive

  - id: H3
    name: integration_loads_clean
    description: |
      No URA ERROR logs in the hour after restart — boot-seed of
      _room_occupied/_camera_occupied (B-HIGH-1) must not crash discovery.
    query:
      kind: log_grep
      source: home_assistant_core
      pattern: "universal_room_automation.*ERROR"
    expected:
      condition: "no_matches_in_window"
      value: null
    window:
      first_check_after: 1h
      confirm_after: 24h
      alert_if_violated_after: 72h
```

## Rollback

HACS install v4.7.18 — prior wake-gate behavior restored. No persisted state shape changed; clean either direction.
