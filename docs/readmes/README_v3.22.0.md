# v3.22.0 — Signal Wiring (Cycle F)

**Date:** 2026-04-01
**Tests:** 70 new
**Review tier:** Feature (2 adversarial reviews + fixes)

## What Changed

Cross-coordinator signal responses are now fully wired and configurable.
All 8 responses default OFF — users opt-in via the Coordinator Manager
options flow ("Signal Responses" step). Disabled responses log what they
WOULD have done for validation before enabling.

### D1: Signal Response Config Infrastructure
- 8 new `CONF_*` config keys in const.py (all default OFF)
- "Signal Responses" step in Coordinator Manager options flow
- `_get_signal_config()` helper on BaseCoordinator for runtime config reads
- Full strings/translations for all toggles with descriptions

### D2: Wire SIGNAL_SAFETY_HAZARD
- **HVAC:** Smoke/CO critical → stop all managed fans (configurable)
- **HVAC:** Freeze risk → emergency heat on all zones (configurable, arrester suppress/unsuppress)
- **Security:** Smoke/fire critical → unlock all egress doors (configurable)
- **Energy:** Any critical hazard → emergency max load shed (configurable)
- **Music:** Any critical hazard → stop all playback (configurable)

### D3: Wire SIGNAL_PERSON_ARRIVING
- **Security:** Add arriving person to expected arrivals (5-min window, configurable)
- **Music:** Start music in person's zone (OFF by default, configurable)

### D4: Wire SIGNAL_SECURITY_EVENT
- **Music:** Critical security event → stop all playback (configurable)

## Review Findings Fixed
- 2 CRITICAL: Hazard type string mismatches ("co"→"carbon_monoxide", "freeze"→"freeze_risk")
- 3 HIGH: Arrester unsuppress in finally block, security log accuracy, music observation mode guards
- Deferred: Emergency load shed recovery path, config entry caching (tracked in task #10)

## Files Changed
- `const.py` — 8 new config keys
- `config_flow.py` — signal_responses options step
- `domain_coordinators/base.py` — _get_signal_config helper
- `domain_coordinators/hvac.py` — safety hazard handler (fans + heat)
- `domain_coordinators/security.py` — safety hazard handler (egress) + person arriving handler
- `domain_coordinators/energy.py` — safety hazard handler (load shed)
- `domain_coordinators/music_following.py` — 3 signal handlers (hazard/arrival/security)
- `strings.json` + `translations/en.json` — signal response step strings
