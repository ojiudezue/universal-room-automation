# v5.42.0 — Fan Seam Phase 1 + D2 mmWave Demotion (combined deploy)

Two review-complete cycles, dependency-ordered in one deploy (D2's post-demotion
story relies on Phase 1's ownership fix).

## 1. Fan seam Phase 1 (Tier 2-DB; incident 2026-08-01)
- **BUG 1:** the room-tier vacancy-hold override can no longer arm fan TURN-ONs —
  it applies only when a fan is already running (its documented intent). Every
  restart previously armed 5 minutes of turn-on-into-vacant-hot-rooms.
- **BUG 2:** HVAC-tier external-state sync gains case 3 — a fan lit by an external
  actor (incl. room-tier during boot warmup) is ADOPTED (`trigger="external"`),
  so the vacancy-off path always has an owner. Closes the 4h-vacant-fan class.
- Review fix-up: vacancy stamp reset across cooldown open/clear (jointly
  mutation-anchored), stale-stamp clear tested, string-percentage adoption.

## 2. D2 mmWave fan-corroboration demotion (Tier 3)
mmWave-sole occupancy sustained under a running fan is DEMOTED (released with
source `mmwave_fan_demoted`) when: fan on ≥ 600s, PIR stale ≥ 2× occupancy_timeout,
no BLE person, no camera person (covered rooms) — with hard gates: never during
SLEEP/WAKING/HOME_NIGHT, never for no-PIR rooms (fail-closed), never inside
debounce/boot-settle/recheck-in-flight. Precedence: recheck first; D2 OUTRANKS
the continuously-re-armed interference hold once its higher bar is met (demote +
clear hold atomically). Post-demotion flap latch: mmWave alone cannot re-create
occupancy until a clean edge (mmWave-off / PIR / BLE / fan-off).
Review history: 3 CRITICALs found and fixed across two N+1 rounds (unreachable
gate; unreachable arbitration; missing sleep gate). Blast radius pinned
room-tier-only (zone view unchanged, tested).
Kill switches: MMWAVE_FAN_CORROBORATION_ENABLED=False; BLE_MOTION_CONFIRM_MULTIPLIER=0;
upstream D3_DIAGNOSTIC_ENABLED=False.

## Suite
70/70 cycle tests post-merge; full suite 7816 passed / 32 failed = pre-existing
baseline, zero drift.

## Live Validation — prospective
- **Live:** next HA restart: ZERO vacant-room fan turn-ons in the boot window
  (BUG 1); log-scan for "Fans on at" with room vacant must be empty.
- **Live:** an externally-lit fan in a vacant room is adopted (INFO "adopted
  externally-lit fan") and swept off within vacancy-hold + one HVAC tick (BUG 2).
- **Live:** first organic demotion: INFO line + `binary_sensor.<room>_occupied`
  attrs `mmwave_fan_demoted=True`, `mmwave_fan_demotions_since_boot` increments,
  occupancy releases with source `mmwave_fan_demoted`, and NO T→F→T flap while
  the mmWave stays on (latch).
- **Live:** zero demotions during sleep-family house states.
- **Live:** no new URA errors referencing fan_veto/fan_recheck/hvac_fans/demotion.

### Validated 2026-08-01 (~14:20 CDT, first post-deploy boot)
| Criterion | Result | Evidence |
|---|---|---|
| BUG 1: zero vacant-room fan turn-ons in boot window | **PASS** | Boot reproduced the morning incident's exact conditions (hot vacant Study A, house away, restart); ura_activity_log has ZERO fan actions since boot — this morning's identical window produced "Fans on at 100%". |
| No new URA errors | **PASS** | ERROR log empty post-boot (also second consecutive clean boot for v5.41.0's write path). |
| BUG 2: adoption + sweep | pending-organic | Needs an externally-lit fan; watch for "adopted externally-lit fan" INFO + off within vacancy-hold + tick. |
| First organic demotion (D2) | pending-organic | Needs fan-sustained mmWave phantom while home-day/away; watch INFO line + `mmwave_fan_demoted` source + no flap. |
| Zero sleep-window demotions | pending-organic | Standing watch across coming nights. |
