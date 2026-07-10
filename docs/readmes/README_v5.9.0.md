# URA v5.9.0 — Census over-count fix: same-area dedup + sustain-before-latch (Tier 2-DB)

Fixes the person-census over-count the operator confirmed live in BOTH modes: the count reads **higher than actual** (spatial double-count) and **lingers after people leave** (peak-hold amplification). Also ships a rider: the per-room reconcile gate switch is renamed **"Device Auto Recovery"**.

## Root causes (verified in source)
1. **Spatial:** `camera_census.py` summed per-camera person counts within each platform (`frigate_total += count`, `binary_platform_count += 1`) — two cameras seeing the same body = 2. The cross-platform `max()` only reconciled *between* platforms, after each side was already inflated.
2. **Handoff amplification (thoroughfare):** one person walking garage-hallway → stairway produces a 5–15s detection-tail overlap → instantaneous `fresh_count=2` → the census **peak-hold latched it for minutes** (`_apply_hold_decay`: peak held for the full interior hold window, then slow decay). One mechanism explained both symptoms.
3. **Critical wiring (found by Review B):** with enhanced census ON (the live default), the shipping `unidentified_count` comes from `_get_unrecognized_camera_count()`, not `_calculate_house_census` — the fix had to land in BOTH.

## What ships
- **D-A — Same-area spatial dedup, zero-config:** one shared helper `_dedup_by_area` (max within an HA area, sum across areas + unassigned) used by BOTH `_calculate_house_census` and `_get_unrecognized_camera_count` — the two paths cannot diverge (Bug Class #53 guard). Rides on `CameraInfo.area_id` already populated from the registry: **no new CONF, no config-flow field.**
- **D-B — Sustain-before-latch:** a HIGHER `fresh_count` only latches the census peak after persisting `CENSUS_PEAK_SUSTAIN_SECONDS` (15s const). Handoff spikes can't sustain; a real second person latches (worst-case latch latency ~60s at the 30s census cadence — consumers tolerate it: the guest gate already sits behind 300s persistence; the AWAY veto is condition-based). House zone only — the property (exterior) zone keeps instant-rise/instant-drop.
- **D-C — Hold re-tune:** `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES` 15 → 3 (the "lingers" fix; decay stepper unchanged).
- **D-E — Observability:** `URAPersonsInHouseSensor` attrs `area_contributions`, `raw_pre_dedup_sum`, `pending_peak` — the naive-sum vs dedup delta is one attribute read away.
- **Rider:** `AutoRecoverySwitch` display name → **"Device Auto Recovery"** (key/unique_id unchanged; entity_id stable).
- **Deferred by design:** cross-area overlap-group config (until live shows a residual), per-input TTL (stretch, gated on a stuck-sensor repro), transit-transfer suppression (stretch).

**Invariant:** ordering availability → same-area dedup → sustain-latch → hold/decay; one body in view of K same-area cameras contributes exactly 1; a transient increase below the sustain window never latches the peak.

## Review / gate (Tier 2-DB)
3 framing-disjoint reviews: **A=SHIP, B=FIX-FIRST (CRITICAL B-C1: dedup didn't reach the enhanced-census path), C=BLOCK (the initial test file was tautological — stub mirrors, zero production imports; reinstating the ORIGINAL BUG passed 154 tests).** Fix-up: shared-helper rewiring + full test rewrite driving real `PersonCensus` (17 tests), property-zone exemption, observability-stale fix, LOWs in-cycle. **Orchestrator independently re-ran the decisive mutation** (reinstated the original same-area sum): 4 named tests fail, byte-identical restore, 17/17 green. Full suite = documented 35-failed/14-error ordering-flake baseline, **zero regressions vs clean develop**; `quality/real_construction/` 1 passed. Review doc: `docs/reviews/code-review/v5.9.0_census_overcount.md`. Also new **Bug Class #54** (perceived actuation-latency misattribution) filed in QUALITY_CONTEXT.md from the 2026-07-08 latency investigation.

---

## Acceptance

```yaml
version: 5.9.0
hypotheses:
  - id: H1
    name: ura_v590_deployed
    description: URA v5.9.0 is the running HACS-installed version and all entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.9.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: census_attrs_live
    description: The persons-in-house sensor publishes the new dedup observability attrs.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_persons_in_house, attribute: raw_pre_dedup_sum }
    expected: { condition: "!=", value: "unknown" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 24h }
  - id: H3
    name: no_error_storm
    description: No recurring URA error after the census change.
    oracle: home_assistant
    query: { kind: home_assistant.log_count, search: "universal_room_automation", period: 24h }
    expected: { condition: "<", value: 5 }
    window: { first_check_after: 1h, confirm_after: 24h, alert_if_violated_after: 72h }
```

## Live Validation — Validated 2026-07-08 (post-restart)
| # | Criterion | Result | Observed evidence |
|---|---|---|---|
| L1 | Deploy healthy | **PASS** | `installed_version = v5.9.0`; `state_summary: {loaded: 40}` (40/40). Only ERROR lines are a known **shutdown-transient** burst at 21:23:12 ("DB write worker not running" during teardown, pre-boot) — zero post-boot URA errors. |
| L2 | Census attrs live | **PASS** | `sensor.universal_room_automation_persons_in_house` = 3 with all three new attrs present: `area_contributions: {}`, `raw_pre_dedup_sum: 0`, `pending_peak: null` (cameras currently clear → honest empty values). `identified_count: 3`, `unidentified_count: 0` — no phantom guests at validation time. |
| L4 | AWAY-veto guard | **PASS (indirect)** | `unidentified_count = 0` with 3 identified residents present — the veto-feeding value is sane post-dedup. Positive case (real guest → ≥1) is organic; the mutation-anchored suite covers the code path. |
| L5 | Rider rename | **PASS** | Switches show "**<Room> Device Auto Recovery**" (AV Closet, Breakfast Nook, Butler Pantry, Dining Room sampled); entity_ids unchanged (`*_auto_recovery`), all ON. |
| L3 | Thoroughfare walk | **PENDING (operator)** | One person garage-hallway → stairway must NOT latch 2 (`pending_peak` may blip, no promotion); a real second person latches within ~60s. Observe on next natural walk; `pending_peak` attr makes it visible. |
| L6 | 3-min decay | **PENDING (organic)** | After cameras go clear, house census decays within the new 3-min hold (was 15). Observable within hours of normal occupancy. |
