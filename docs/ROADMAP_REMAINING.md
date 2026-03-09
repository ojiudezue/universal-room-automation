# URA — Remaining Roadmap

*Snapshot as of 2026-03-08 · Current version: v3.9.5*

## 1. Dashboard v2 Polish (v3.9.5+)
Minor fixes to the 7-tab glass morphism dashboard shipped in v3.9.5.
No extended plan — punch-list driven.

## 2. Notification Manager C4b (v3.9.6)
Inbound message parsing from WhatsApp/Pushover/Companion, response dictionary,
safe word challenge for CRITICAL alerts, TTS ack announcements, BlueBubbles stubs.
~645 lines, 3–4 hours.
**Blocked on:** BlueBubbles setup (manual).

**Plan:** [`docs/plans/PLAN_notification_manager_c4b.md`](plans/PLAN_notification_manager_c4b.md)
**C4a reference:** [`docs/plans/PLAN_notification_manager_c4a.md`](plans/PLAN_notification_manager_c4a.md)

## 3. AI Custom Automation (v3.10.x)
Person-specific enter/exit rules parsed once at config time by LLM, stored as
structured service calls, executed at runtime with zero AI cost.
**Needs plan rewrite** — original assumed `ai_task.generate_data` service which
doesn't exist. Must choose real backend (conversation.process or direct API).

**Plan (needs revision):** [`docs/PLANNING_v3.4.0_CYCLE_5.md`](PLANNING_v3.4.0_CYCLE_5.md)
**Earlier iterations:** [`docs/PLANNING_v3.4.0.md`](PLANNING_v3.4.0.md), [`docs/PLANNING_v3_4_0_REVISED.md`](PLANNING_v3_4_0_REVISED.md)

## 4. Comfort Coordinator (v3.10.x)
Comfort scoring, circadian lighting integration, per-person temperature
preferences. Stubbed in config flow but not built. Lower priority — defer
unless needed before Bayesian.

**Plan:** [`docs/Coordinator/COMFORT_COORDINATOR.md`](Coordinator/COMFORT_COORDINATOR.md)

## 5. Bayesian Predictive Intelligence (v4.0.0)
Capstone milestone. Per-person per-room occupancy prediction using Bayesian
inference, guest-aware training, camera+BLE confidence boosting, energy
consumption prediction integration, uncertainty quantification.

Foundation already partially built:
- Energy predictor Bayesian accuracy tracking + temp regression (v3.7.12)
- Person room transition history in DB (v3.2.x)
- Census person count validation (v3.5.x)
- Occupancy patterns in SQLite (daily/weekly aggregates)

**Plan:** [`docs/ROADMAP_v10.md`](ROADMAP_v10.md) §v4.0.0
**Architecture context:** [`docs/VISION_v7.md`](VISION_v7.md)
