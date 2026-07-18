# URA v5.20.0 — Cloud-Reliance D2 + Battery-Aware EV Charging

Two review-complete Tier-3 cycles ship together (one restart). A third rider takes
effect at the same restart: the recorder exclusion of the dead-accumulator Envoy
consumption statistic (operator-ratified 2026-07-17, RUNBOOK_lts_repairs_r4.md).

## Cycle 1 — Enphase Cloud-Reliance D2
SOC divergence detection (cloud-vs-local split classes → NM alert) + `soc_resolution`
observability attr (tier + source ages) + cloud-lag gate. D3 verified no-op.
Commits 63362276 · b48e9bc5 · a3457bb1 · 2c1ce3fc. Review: 6 passes, 1 CRIT
(dead-NM-backref, invented-attribute class) + 6 HIGH, all fixed
(`docs/reviews/code-review/cloud_reliance_d2_tier3.md`).

## Cycle 2 — Battery-Aware EV Charging (EVSE drain-precedence)
Hold-then-eval night transition: battery holds for the car at off_peak, evaluates
whether draining to target then charging the car fits before must-start-by, and
if so pauses EVSE(s) (owner "dp"), pins the composed reserve floor at drain target
(max()-composition, INV-DP3), releases at floor with sticky peer/TOU-aware
reversion, and force-starts at must-start-by regardless (INV-DP2). State machine
KV-persisted; `evse_dp_paused` set persisted with 10h staleness; restore drops the
transition (no half-actuated resurrection) and the HOLD_ONLY orphan retry driver
cleans up. **Ships OFF** (`CONF_DP_ENABLE=False`; switch "Battery-Aware EV
Charging" = kill switch, retirement trigger in plan doc).
Commits f517a120…8eb72e51 (build) · 8f2bfc9e · 447daf84 · b48addf0 (fix-ups).
Review: 4 framing-disjoint reviews + 2 D re-passes + orchestrator mutation
verification; 2 CRIT + 7 HIGH found/fixed
(`docs/reviews/code-review/battery_aware_ev_charging_tier3.md`).

## Entities (new/renamed)
- `switch.…battery_aware_ev_charging` (unique_id `drain_precedence_enable`) — kill switch, default OFF.
- `sensor.ura_energy_drain_precedence_state` — friendly name "EV Charging Plan"; DP state + attrs.
- 7 DP knob Number entities (drain target, eval delay, lead times, etc. — see B1 commit f517a120).

## Validated 2026-07-17 (post-restart, ~5-10 min after boot; HA up in ~80s)

| Criterion | Result | Evidence |
|---|---|---|
| D2: `soc_resolution` populates with tier + ages | **PASS — organically exercised day zero** | `sensor.ura_energy_coordinator_battery_strategy` attr `soc_resolution` = `{tier: cloud_fallback, cloud_soc: 99.3, cloud_soc_age_s: 90.1, cloud_settings_lag_s: 99.9, divergence_active: false}`. Local Envoy entry is in `setup_retry` (device unreachable — the known flaky termination, NOT v5.20.0), so the fallback path ran for real at first boot instead of the happy path. |
| D2: divergence detector silent absent a real split | PASS (boot window) | `divergence_active: false`; zero D2 NM alerts. Full clean-day + one-WARNING-per-real-split criteria remain organic (need Envoy back + a real split). |
| BA-EVC: kill switch exists, OFF | PASS | `switch.ura_energy_coordinator_battery_aware_ev_charging` = `off` (registry-confirmed friendly name "Battery-Aware EV Charging"). |
| BA-EVC: state sensor dormant | PASS | `sensor.ura_energy_coordinator_ev_charging_plan` = `hold_only` (note: entity_id derives from the friendly name via has_entity_name — README's earlier `drain_precedence_state` id was the unique_id, not the entity_id). Zero `drain-precedence:` lines in error_log. |
| BA-EVC: no DP reserve-floor contribution while OFF | PASS | `battery_strategy` = `self_consumption`, `inclement_reserve_floor: 10`, no DP attrs present. |
| Recorder exclusion: no new statistics rows | PASS-provisional | Latest `statistics_short_term` row for the excluded entity is 548 min old (predates deploy — Envoy has been down ~9h, so exclusion vs entity-absence are not yet distinguishable). Definitive proof when the Envoy recovers: live state updates while statistics stay frozen. Check then. |
| Regression: zero URA errors | PASS | system_log ERROR × `universal_room_automation` = 0 entries; presence house_state live (`home_evening`, confidence 0.85). |
| Suite | PASS | EVSE filter 312/3; full suite 36F/14E = pre-existing baseline exactly. |

Boot transients seen and dismissed: none URA-attributable. Open live item carried
forward: Envoy `setup_retry` (physical re-termination on the operator's list);
`enphase_ev` cloud entry `loaded` — which is precisely why D2 has data.

## Not done / deferred (plan accounting)
- D2-M1 accepted gap: plugged-idle car invisible to needed_kwh (no trustworthy plugged
  signal across EVSE integrations); must-start-by is the liveness backstop. Documented in code.
- D3-L1 accepted: indefinite peer-hold keeps DP floor pinned (conservative direction, sub-dollar bound).
- Organic transition validation (arm→pause→drain→release on a real night) requires the
  operator flipping the switch ON — separate activation decision AFTER deploy validation.
- `_crosscheck_consumption` still compares against the dead accumulator (read-safe but
  meaningless) — backlog hygiene item.
- QUALITY_CONTEXT additions queued: invented-attribute getattr (3rd cycle), tautological
  test anchor, slice-seam hand-off drop, docstring-claimed-parity-not-implemented.
