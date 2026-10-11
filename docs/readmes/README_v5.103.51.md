# URA v5.103.51 — Running-fan false presence: fix the mechanisms we already had

Cards: FAN-SUSTAINED-SHAKE-DEMOTE-1. Tier 2-DB (presence ↔ HVAC fans). Measured first, plan + plan review (FIX-REQUIRED → Rev 2), context-wide prior-art audit (reuse gold patterns), three framing-disjoint reviews (A correctness, B lifecycle/HVAC, C test authority via per-site mutation) with all findings fixed and re-drilled, full-suite name-diff 0 new. Plan: docs/planning/PLANNING_fan_noise_running_rejection.md. Read-first docs: PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md, SENSOR_FLEET_CLASSES.md.

## Problem (measured 2026-10-04→10-11)
Study A sat "occupied" ~26 h/week while empty with its fan running. The four existing fan mechanisms did almost nothing: the pause-and-recheck correctly declared Study A empty 28× but its own fan restore undid 27 of them; the running-fan release (D2) never fired anywhere — it classified sensors by entity name and threw out every Hobeian ZV motion sensor (named `…_presence`); the 5-second fan-start gate fired 27×, 23 on dead fan entities flapping unavailable, and couldn't catch radars that latch 1–4 minutes after a fan starts.

## Fix
- **Recheck leaves the fan off after an "empty" verdict** (through the existing restore path, so HVAC's fan bookkeeping is cleared — no fake manual-off, no 1 h lockout). A fan you switched on by hand comes back on. HVAC's suppression now lasts the whole pause.
- **Sensors classified by capability, not name:** D2 and the comfort-fan away veto use the existing capability layer (`derive_capability`) plus a device-model safety net. All 22 ZG-204ZV motion sensors count as fan-immune witnesses; real radars filed under motion (Meross MS600) are excluded, including after firmware updates; unknown models fall back to the old name rule.
- **Dead fan entities no longer fake fan activity:** a fan flapping through unavailable keeps its last real state (expires after 120 s if it stays unavailable; a real power-on still counts); the recheck skips a running fan the actuator reconciler has quarantined as flapping.
- **Recheck timing fits the sensor:** watch window scaled by the slowest recognised sensor family in the room (switch in the presence options, Advanced); cooldown 30 → 15 min; restart recovery uses the live window and cooldown.
- **5-second fan-start gate retired** (window 0; counter kept).

## Config changes alongside (no code)
Game Room / Media / Guest Bedroom 1 / Master Bedroom now use the stable HomeKit `_2` fan entities (Bond local polling flaps — BOND-BRIDGE-UNRESPONSIVE-1). Study A radar tuned (motion 5, static 6, distance 2.5 m) — measured separately.

## Not built / deferred
ZV 5-minute post-fan-on gate (FAN-ZV-POWERON-TRANSIENT-GATE-1); fan-distance-band veto; general corroboration rule; URA-owned radar tuning (URA-SENSOR-TUNING-1). Operator items: move the three Meross MS600s to presence sensors; record the ESP32 radar family (Jaya, Ziri, Kitchen, Study B).

## Live validation (prospective)
- Boot: no URA errors; no recheck/HVAC fan errors.
- Next Study A recheck "empty" verdict: fan stays off, room stays vacant (no re-latch within 15 min), and no `manual_off_cooldown` opens.
- One week (≈2026-10-18): Study A and other fan rooms' empty-room fan-on occupied minutes vs the 2026-10-04→10-11 baseline (re-run scripts/fan_noise); guard: VACATED verdicts while BLE places someone in the room must not rise.
