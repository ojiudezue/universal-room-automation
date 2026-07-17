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

## Live Validation (prospective — replace with Validated table post-restart)
- **Live (D2):** `soc_resolution` attribute populates with tier + source ages within one decision cycle of restart.
- **Live (D2):** divergence detector SILENT through a clean day; zero D2 NM alerts absent a real cloud-vs-local split; next real ≥25-pp split fires exactly one WARNING NM/day.
- **Live (BA-EVC):** kill switch entity exists, state OFF after restart; flipping ON+OFF produces no actuation while no transition is active.
- **Live (BA-EVC):** `sensor.ura_energy_drain_precedence_state` = `hold_only`; no `drain-precedence:` actuation lines in log while switch OFF.
- **Live (BA-EVC):** no reserve-floor change attributable to DP while OFF (battery_strategy attrs unchanged vs pre-deploy).
- **Live (recorder exclusion):** post-restart, `sensor.envoy_482543015950_energy_consumption_today` produces NO new rows in `statistics_short_term`/`statistics`; live state still updates.
- **Live (regression):** zero URA ERROR lines post-restart; all 40 rooms set up; write-verify watchdog (v5.19.0) still stamping.
- **Suite:** EVSE filter 312 passed / 3 skipped; full-suite failures within pre-existing baseline set.

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
