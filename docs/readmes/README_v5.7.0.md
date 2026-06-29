# URA v5.7.0 — Guest-mode detection trust fix (WS-A)

Fixes the false-GUEST / dead-phone false-AWAY class in house-state inference. An away resident whose phone has no in-house BLE fix is stamped `tracking_status=LOST` (location=away); previously that excluded them from the away accounting, so the house couldn't resolve AWAY and could read GUEST. WS-A admits "lost-but-away" trackers into the away veto — **guarded** so it can never force AWAY while a real resident is home.

## What ships (Tier 3 — 4 framing-disjoint reviews + checkpoint)
- **A1** — a tracker that is `LOST`/`STALE` but `location==away` counts toward the away veto (was excluded).
- **A2** — the new "path β" (LOST-admitted) AWAY veto requires **no indoor zone occupied** (the v4.7.14 ACTIVE path is byte-identical, "path α").
- **A3** — per-person **grace** (youngest lost stamp; `CONF_LOST_AWAY_GRACE_MIN`, default 60) + **sleep exemption** (`CONF_LOST_AWAY_SLEEP_EXEMPT`, default on) that gates on sleep STATE **or** sleep HOUR, + an **indoor-clear debounce** (`CONF_LOST_AWAY_INDOOR_CLEAR_TICKS`, default 3) so a single-tick mmWave dropout can't force-AWAY a still resident.
- **A4** — per-zone **`CONF_ZONE_IS_OUTDOOR`** (default false): outdoor zones (e.g. "Outside") are excluded from indoor-occupancy so the outdoor ghost neither blocks nor fakes presence.
- New diagnostics on `sensor.ura_presence_coordinator_presence_house_state`: `veto_path` (none/active/lost_admitted), `lost_away_persons`, `lost_away_grace_remaining_s`, `outdoor_zones`.

## Falsifiable invariant (I1)
The house never transitions to AWAY while a real resident is home. Path β fires only when census=0 ∧ unidentified=0 ∧ no indoor zone occupied (outdoor excluded) ∧ youngest-lost grace elapsed ∧ indoor-clear debounce satisfied ∧ not sleep-exempt. I2 (unidentified-while-home still arms GUEST) and I3 (path α byte-identical) preserved.

## Review trail
4 framing-disjoint reviews: A/B SHIP; C/D FIX-FIRST (D-HIGH-1 sleep-state-vs-hour; C-HIGH-1 untested input-wiring) → two builder fix-ups → orchestrator caught the fixes were source-grep-only twice and closed them with real **behavioral** `_run_inference` mutation anchors (D-HIGH-1 sleep-hour, A1/A4 wiring, debounce, stampless) → **D re-pass: SHIP** (I1–I4 hold; VACATION safe; no N+1 leak). Every load-bearing site fails a specific behavioral test under logic-flip (orchestrator-verified). Suite at the 35-failed baseline, +48 cycle tests; path α byte-identical.

## Deferred (fast-follow, both fail-safe)
- **WS-A4 camera-census outdoor exclusion** — presence-side shipped; camera-side → **v5.7.0.1**. An outdoor camera's census can only *suppress* β, never misfire.
- **`_lost_away_since` persistence** — skipped; post-restart everyone is stampless → β held until fresh grace ages. Safe direction.
- **WS-B (HVAC actuation)** — separate cycle (v5.7.1), **gated on this WS-A live validation**.

---

## Acceptance

```yaml
version: 5.7.0
hypotheses:
  - id: H1
    name: ura_v570_deployed
    description: URA v5.7.0 is the running HACS-installed version.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.7.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: no_presence_error_storm
    description: No recurring URA error after the WS-A detection-trust change.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
  - id: H3
    name: veto_path_surface_live
    description: WS-A veto_path diagnostic is published on the house-state sensor.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_presence_coordinator_presence_house_state, attribute: veto_path }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
```

> Shipwatch note: deep behavioral correctness (dead-phone-home→stays-HOME) is in-suite-authoritative (the watcher can't stage it). The Shipwatch `home_assistant` adapter is currently a stub (backlogged), so these resolve `pending` until it ships. Verify entity/attribute names against live HA before trusting `confirmed`.

## Live Validation — Validated 2026-06-29 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy | **PASS** | `update.universal_room_automation_update` installed_version = `v5.7.0`; zero URA ERROR entries in the system log at boot. |
| L2 | New diagnostics live | **PASS** | `sensor.ura_presence_coordinator_presence_house_state` (state `home_day`) exposes `veto_path="none"` (no veto firing — house occupied, correct), `lost_away_persons=[]`, `lost_away_grace_remaining_s=null`, `outdoor_zones=[]`, `all_tracked_persons_away=false`. |
| L3 (I1, headline) | No force-AWAY-while-home / lost-away→AWAY | **in-suite-authoritative + standing live check** | The invariant is mutation-anchored across 6 behavioral tests (orchestrator-verified). Live: requires a real all-away period to observe `veto_path=lost_admitted` → AWAY, and confirmation that no AWAY-via-`lost_admitted` ever occurs while a resident is present. Watch `veto_path` over the next all-away window. |
| L4 | Config knobs | **code-proven (config-flow round-trip tested)** | `CONF_LOST_AWAY_GRACE_MIN` / `CONF_LOST_AWAY_SLEEP_EXEMPT` in the Presence options step; `CONF_ZONE_IS_OUTDOOR` per zone (default false → `outdoor_zones=[]` live, consistent). Not entities, so verified in-suite + visible on opening room/coordinator config. |

**Note:** the headline behavioral correctness (dead-phone-home → stays HOME; lost-away-empty → AWAY) cannot be staged on the live instance without a real away event, so it is in-suite-authoritative (the 6 logic-flip-anchored behavioral tests). The deploy is healthy and the detection surface is live; L3's live observation is the standing watch. WS-B (HVAC actuation) remains gated on observing L3 live.
