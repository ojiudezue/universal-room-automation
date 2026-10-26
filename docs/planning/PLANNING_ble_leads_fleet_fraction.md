# PLANNING — BLE leads: fleet guard as a fraction of the remembered fleet

**Status:** Rev 1, for operator review. No code written. **Card:** `PERSON-BLE-WINS-OVER-STALE-GPS-1`,
block `residual_fleet_fraction_2026_10_24` (`docs/planning/kanban.data.yaml`). Parent plan:
`PLANNING_presence_gps_assistive.md` rev 3 (shipped v5.103.90 / .91).
**Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all of §0-§11,
the §10 ledger, addendum, gold patterns), `docs/architecture/SENSOR_FLEET_CLASSES.md`, the parent plan,
`README_v5.103.90.md`, and the card. No §10 claim is re-asserted. Sensor fleet classes are not touched.

**Operator ask (card, 2026-10-24):** the 30-proxy floor should be a fraction of the installed scanner
base that is working, not a static number. Design recorded on the card: a fraction of a URA-remembered
high-water fleet size, with an absolute floor.

## 0. Bottom line (marginal-benefit pushback first)
- **Here, nothing changes:** over 7 days every fraction 0.5-0.8 arms and disarms on exactly today's
  readings (§2.3). **At Wigton too:** no Bermuda entity → no rule (parent R1, `person_coordinator.py:495-498`).
- **It buys:** a future Bermuda home with < ~30 proxies, which today can never arm (fails safe, not wrong).
  **It costs:** one small persisted HA `Store` and a moving threshold.
- **Recommendation:** build the simple version below (rung-1 constants, a 7-day rolling daily max, no
  new entity, no options field). If the operator would rather not carry a Store for a home that does
  not exist yet, **park it with the trigger "a second Bermuda install is onboarded"**. Both are
  defensible; the static 30 is not dangerous, only non-portable.

## 1. Institutional context verified
### 1.1 Prior-art scan, REUSE or BUILD
| Piece | Verdict | Existing symbol |
|---|---|---|
| Fleet guard, latch, listener, tick re-read | **REUSED unchanged** except the one comparison | `_apply_proxy_state` `person_coordinator.py:455-465` (the only comparison against the floor), `_on_proxy_state_change` :467-475, `_ensure_proxy_listener` :487-523, `_fleet_armed` :525-532, per-tick capture :791-801 |
| Proxy entity resolution | **REUSED** | `_resolve_proxy_entity_id` :444-453, unique_id `BERMUDA_ACTIVE_PROXY_COUNT_UNIQUE_ID` `const.py:263` |
| Floor constant | **REUSED name, value and meaning change** | `BLE_LEADS_MIN_ACTIVE_PROXIES` `const.py:261` (30 → 3, now the absolute floor). Read at `person_coordinator.py:459` and :504 (log) only; no test imports it by name (grep `quality/tests`: 0 hits) |
| Arm window | **REUSED unchanged** | `BLE_LEADS_ARM_S = 360` `const.py:262` |
| Fraction | **NEW** `BLE_LEADS_ACTIVE_FRACTION` | grep `FRACTION\|fleet` in `const.py`: no BLE fleet fraction exists |
| Fleet-size window | **NEW** `BLE_LEADS_FLEET_WINDOW_DAYS` | none |
| Persisted fleet size | **NEW `Store`, REUSED pattern** | `Store(hass, 1, f"{DOMAIN}.hvac_zone_state")` `domain_coordinators/hvac.py:962`; house-state store `domain_coordinators/manager.py:466`. Grep `high_water\|max_seen\|_hwm` in the integration: 0 hits. Not the URA DB (no write queue, no schema change) |
| Bermuda total proxy count | **NOT used** (rejected, §3.2) | `sensor.bermuda_global_total_proxy_count`, unique_id `BERMUDA_GLOBAL_PROXY_COUNT` (live registry) |
| Rejected alternative: recorder long-term statistics max | **NOT used** | would depend on recorder retention and excludes (`RUNBOOK_recorder_excludes.md`) and an executor read at boot; a 7-entry Store is simpler |

Greps: `BLE_LEADS|_fleet_healthy_since|PROXY_COUNT|_proxy_entity|high_water|max_seen|_hwm`, `Store(`,
`BLE_LEADS_MIN_ACTIVE_PROXIES` in tests, plan filenames (`PLANNING_ble_scanner_borrow_v2.md`: unrelated).
### 1.2 Bermuda source (live `/config/custom_components/bermuda`, read 2026-10-26)
Active = `count_active_scanners()` (advert in last 10 s; `coordinator.py:574`, `sensor.py:531-536`); total =
`len(scanner_list)` (`sensor.py:506-511`) from `async_current_scanners()` (`coordinator.py:1496`); both ~60 s
rate-limited. A proxy dropping off HA's list leaves **both**, so active/total cannot see it; a remembered size can.
### 1.3 Config-first
No options field, Number or HA-side setting controls the floor. Setting the floor lower (a code change
anyway, rung 1) would portably arm small homes but weakens the guard here. A per-install options field
(rung 2) was considered: it fixes portability with no new state, but every new install must be told its
proxy count and it goes stale as proxies are added. Code with a learned size is the better fit.

Memory: `reference_presence_state_of_play`, `feedback_measure_before_build`, `feedback_marginal_benefit_pushback`,
`feedback_suppression_needs_discharge`, `project_single_user_no_backcompat`.

## 2. D0 — measurement (RUN 2026-10-26, read-only, `immutable=1`)
Recorder retention 10-19 04:18 → 10-26 06:40 (7.1 d). Scripts: session scratchpad `fleetfrac.py`,
`fleetsim.py`. The builder copies them to `scripts/probes/ble_fleet_fraction_probe.py`.
### 2.1 Distributions
| Series | Rows | p1 | p5 | p50 | p99 | max | Lowest non-zero |
|---|---|---|---|---|---|---|---|
| Active | 1,069 | 0 | 55 | 60 | 62 | 62 | **50** (once, 10-23 13:49) |
| Total | 315 | 0 | 0 | 61 | 62 | 62 | 55 |
Time-weighted: (active, total) = (62,62) 28%, (60,62) 26%, (61,62) 25%, (56,56) 9% (10-19 before ~21:30,
when the fleet was 55-56), (0,0) 0.17% (17 min in all).
### 2.2 Dips and restarts
- 16 `homeassistant_start` events. Every `0` reading of active sits 100-155 s from one; each lasts ~60 s
  and both counts read 0 together.
- Two `unavailable`→`0` reloads not at a restart: 10-21 16:43 (known Bermuda reload) and **10-26 05:51**
  (new; 12 h from any restart). Both are caught by today's latch.
- **The installed base moves.** Total read 55-56 until 10-19 ~21:30, then climbed to 62 by 10-20 01:33
  and has sat at 58-62 since. Proxies join and leave HA's scanner list for hours. A remembered size must
  therefore follow a shrinking fleet, not only a growing one.
- Lowest active/total ratio with both non-zero: 0.82 (50/61, 10-23 13:49).
### 2.3 Replay: would a fraction have armed and disarmed correctly?
Rule replayed: disarmed while active < max(3, f × size), size = max reading in the trailing 7 days.
| f | Size from active: disarm episodes | not at a restart/reload | Size from total: not at restart |
|---|---|---|---|
| today (30) | 17 | 0 | — |
| 0.5 / 0.6 / 0.7 / 0.75 / 0.8 | 17 | **0** | 1 (window-start artefact) |
| 0.85 | 18 | **1** (10-23 13:49, 50 < 52.7) | 2 |
| 0.9 | 20 | **3** (10-22 19:36, 10-23 13:48, 10-25 16:37) | 4 |
**Verdict:** f ≤ 0.8 is identical to today here; 0.85+ starts false disarms on normal jitter. **GO** on
f = 0.5: same threshold here (31 vs 30), widest margin above jitter, and it still disarms on a
half-fleet outage. What D0 cannot show: a partial hardware outage while HA runs (none happened, as in
parent §5.3). That rests on source (§1.2).

## 3. Design
### 3.1 The rule
`threshold = max(BLE_LEADS_MIN_ACTIVE_PROXIES, ceil(BLE_LEADS_ACTIVE_FRACTION × fleet_size))`, compared
at the single existing site `_apply_proxy_state` (`person_coordinator.py:459`). Everything else in the
guard (listener, tick re-read, boot latch, 360 s arm, entity-missing → off) is unchanged.
- `fleet_size` = max of the stored **daily maxima of the active count** over the last
  `BLE_LEADS_FLEET_WINDOW_DAYS` local days, including today's running max.
- **Unknown size** (fresh install / unreadable Store): this session's running max; boot latch still applies.
### 3.2 Where the high-water mark lives, and why
- **Active, not total.** In replay they agree (both 62). The total series has a window-start artefact.
  Total adds a second entity and listener for no measured gain. A proxy in HA's list that never hears
  an advert is not part of a working fleet. (Revisit trigger: an install where total ≫ active.)
- **Persisted** in `Store(hass, 1, f"{DOMAIN}.ble_fleet_size")`, payload `{"daily_max": {"YYYY-MM-DD": int}}`,
  at most 7 entries. Loaded once in the person coordinator's setup. Saved with `async_delay_save` (60 s)
  only when today's max rises or the day rolls, so a few writes per day. Not the URA DB: no write queue,
  no migration.
  - Persistence is load-bearing. Without it, a restart during a partial outage would learn the degraded
    count as the fleet size and arm on it.
- **Decay = rolling window of daily maxima, 7 days.** A permanently removed proxy leaves the size within
  7 days; until then the threshold is a little high, which is the safe direction (it can only disarm).
  A short outage cannot lower the size, because the other days' maxima still hold it up.
  - An outage longer than 7 days rebases the size to the degraded fleet. That is accepted: after a week
    the smaller fleet is the installed base.
- **Writes only from numeric readings > 0**, so restart zeros never poison it.
### 3.3 Restart semantics
Empty at boot stays (`_fleet_healthy_since = None`, 360 s arm). The Store survives restarts, so the first
threshold compares against yesterday's fleet, not the boot readings. Load failure → unknown size (§3.1).
### 3.4 Knobs (rung 1, `const.py`, review-only)
| Knob | Value | Why rung 1 | Kill / edge semantics |
|---|---|---|---|
| `BLE_LEADS_ACTIVE_FRACTION` | 0.5 | Safety bound against a degraded fleet; a dashboard slider turned down would silently arm a half-dead fleet. Same rung as the floor it replaces. | 0.0 → threshold = floor alone (not a kill switch) |
| `BLE_LEADS_MIN_ACTIVE_PROXIES` | **3** (was 30) | Absolute floor: fewer than 3 live proxies cannot cover a house. Homes with < 3 proxies never arm (fail safe). | Name kept, meaning narrowed; comment rewritten |
| `BLE_LEADS_FLEET_WINDOW_DAYS` | 7 | Decay horizon; matches the operator's "~7 d" and the recorder retention used to size f | ≥ 1 |
| `BLE_LEADS_ARM_S` | 360 | Unchanged | — |
The kill switch is unchanged: `switch.ura_presence_coordinator_ble_leads_home_away`.

## 4. Falsifiable invariant
**INV-F1.** On any reachable path, the overrule never runs while the latest active count is below
`max(3, ceil(0.5 × S))`, where S is the max non-zero active reading over the last 7 local days (store
plus session). It also never runs within 360 s of the last such reading, of `unknown` or `unavailable`,
or of process start.
*Falsified by:* stored daily maxima {62,…}, restart, Bermuda reports 25 steady for 10 min, and the rule
arms (a 25 < 31 breach). Also falsified by `0` or `unavailable` entering the store, or by a store write
of a value larger than any reading.
**INV-F2 (byte-identical here).** With a store size of 59-62, every arm and disarm decision equals
today's static-30 decision for every active reading ≥ 31 or ≤ 29. Only a reading of exactly 30 differs.
That value never occurred in the 1,069 readings.

## 5. Producer and consumer checks
**Producer:** threshold = f(floor, fraction, stored daily maxima, session max). Dependencies: Bermuda
active count, healthy (median 60; zeros only at restarts and reloads); HA Store (in use by HVAC and
house state). The arithmetic is replayed in §2.3 against the recorder, which is external to URA.
**Consumers of the threshold:** `_apply_proxy_state` only, called from the listener and the tick, which
feeds `_fleet_healthy_since` → `_fleet_armed` → `_fleet_armed_now`. That reaches the overrule gate at
both `person.state == "home"` arms and, through `_gps_home_overruled`, `effective_person_state` /
`person_state_for_trust` (the §1-table trust readers and the census face latch). All of these are
trust consumers, and none reads the threshold itself. Display: the INFO log at :504 and :797.
**Emission/decision sites:** (1) `:459` comparison, the change; (2) `:504` log, which prints the
threshold and size; (3) a new store update inside `_apply_proxy_state`, the only writer; (4) the
store load in setup. No other site compares against the proxy count (grep `BLE_LEADS_MIN_ACTIVE_PROXIES`:
`person_coordinator.py:59, 459, 504`, `const.py:261`).

## 6. Deliverables
### D1 — Fraction threshold + persisted fleet size (`person_coordinator.py`, `const.py`)
- `_fleet_threshold()` helper. The daily-max store is updated from `_apply_proxy_state` with numeric
  readings > 0 only. Load in setup, delayed save, prune to the window.
- Log lines name the threshold and size. INFO only when the threshold changes by ≥ 1.
- **Verify:** store {d-1: 62}, reading 31 → healthy; 30 → not healthy (threshold 31).
- **Verify (discriminating):** store {d-1: 8} (small home), reading 4 → healthy; static 30 would read
  not healthy. That observation is the portability fix; under today's code the same input disarms.
- **Verify:** empty store, session max 62, reading 25 → not healthy; restart with the persisted store
  {62} and Bermuda reporting 25 → not healthy (persistence is load-bearing; with the store neutered,
  the same input arms).
- **Verify:** `0` / `unavailable` / `unknown` readings never change the store; day maxima older than 7
  days are pruned, so a {62 eight days ago, 40 since} store gives threshold 20.
- **Verify:** fraction 0 → threshold 3; < 3 proxies never arms.
- **Test:** `test_person_gps_assistive.py::test_fleet_threshold_fraction_of_stored_size`,
  `::test_small_fleet_arms_with_fraction`, `::test_restart_partial_outage_uses_persisted_size`,
  `::test_zero_and_unavailable_never_stored`, `::test_fleet_size_decays_after_window`,
  `::test_fleet_floor_absolute`, `::test_store_load_failure_uses_session_max`. Every existing
  fleet-guard test passes unmodified, or with its count changed only where it sits between 3 and 30.
- **Mutation:** compare against the old constant 30 → `::test_small_fleet_arms_with_fraction` RED; skip
  the store load → `::test_restart_partial_outage_uses_persisted_size` RED; admit 0 into the store →
  `::test_zero_and_unavailable_never_stored` RED; drop the prune →
  `::test_fleet_size_decays_after_window` RED.
- **Live:** INFO at setup reads `fleet size 62, threshold 31`. `.storage/universal_room_automation.ble_fleet_size`
  exists with today's max. After the next restart, "fleet armed" appears within ~7 min (unchanged).
  Discriminating check: the stored maxima match the recorder's daily max of
  `sensor.bermuda_global_active_proxy_count`. A wrong source (total) or a poisoned 0 shows as a mismatch.
- **Live re-run (one shot, 48 h after deploy):** the D0 replay against the live threshold shows 0
  disarms that are not at a restart or reload, and the `presence_gps_override_probe.py` result is
  unchanged (0 GPS-home segments with all own-BLE `not_home` > 10 min outside arm windows).
### D2 — Docs (same commit)
State of Play §3 fleet bullet + residual R2 re-based to "≥ half the remembered fleet"; `const.py:248-260`
comment rewritten; card residual closed.

## 7. Non-goals
No change to the latch, arm window, listener, gate, switch or any trust reader. No options field, Number,
sensor or attribute. No total-count or per-scanner health (residual R2 unchanged in kind). No Wigton
enablement (R1).

## 8. Residuals
R-F1 a fresh install restarted mid-outage before day one learns the degraded size (self-corrects on
recovery). R-F2 an outage > 7 days becomes the fleet size. R-F3 jitter here reaches 0.81; a noisier fleet
may need a lower fraction (reviewed change).

## 9. Tier
**Tier 2** (operator: own review). One comparison site plus a new persisted value on the presence →
house-state trust path, fail safe in both directions (the threshold only moves within [3, 0.5 × S]).
One adversarial plan review before build; build reviews A (arithmetic, store edge cases, day roll,
timezone) and B (Store lifecycle, restart, unload, listener interplay). Builder: `ura-builder`.
Deploy risk: LOW (identical decisions at this house per §2.3).
