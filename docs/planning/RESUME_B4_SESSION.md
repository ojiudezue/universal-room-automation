# B4 Session Resume — Fast Start

**Use this file to resume a new Claude Code session quickly.**

Paste this as your first prompt:

---

Resume B4 Energy Integration work. Read `docs/planning/RESUME_B4_SESSION.md` for context, then check memory at `~/.claude/projects/-Users-okosisi-Code-universal-room-automation/memory/project_b4_deploy_state.md`.

## Where We Left Off

v4.1.0 (B4 Layer 1) is committed, tagged, PR #214 merged to master. Code is on GitHub.

### Immediate Next Steps (in order):

1. **Deploy to HA** — Use HA MCP tools:
   - `mcp__home-assistant__ha_hacs_download` repository=ojiudezue/universal-room-automation version=v4.1.0
   - `mcp__home-assistant__ha_check_config`
   - `mcp__home-assistant__ha_restart` confirm=true
   - Wait 2-3 min, verify `sensor.ura_energy_coverage_delta` has new attributes

2. **Post-deploy verification** — See checklist in `docs/planning/PLANNING_v4.x_B4_ENERGY_INTEGRATION.md` under "Post-Deploy Validation Checklist → Layer 1"

3. **Build Layer 2** (~220 lines) — Occupancy weighting toggle + DailyEnergyPredictor Bayesian integration + battery strategy. Full spec in `docs/planning/PLANNING_v4.x_B4_ENERGY_INTEGRATION.md` under "Layer 2".

### Key Context
- Branch: `develop` (up to date)
- gh CLI: authenticated as ojiudezue
- HA MCP: should be configured in `.mcp.json` (needs session restart to load)
- Pre-existing test failures: 239 failed in test suite (not caused by B4), 2 collection errors (test_cycle_b_config_flow.py, test_fan_control_v318.py)
- pytest path: `/Users/okosisi/Library/Python/3.9/bin/pytest`
- Config flow save timeout (bug #1): known, living with manual reloads

### Quality Review Notes for L2
- Extract duplicated `_get_sensor_list`/`_sum_sensors` to AggregationEntity base
- Consider persisting `_energy_baselines_today` alongside power profiles
- Follow CLAUDE.md review protocol (Tier 1 for L2 since it's focused scope)

### Files to Read Before Building L2
- `docs/planning/PLANNING_v4.x_B4_ENERGY_INTEGRATION.md` — Layer 2 section
- `custom_components/universal_room_automation/domain_coordinators/energy_forecast.py` — DailyEnergyPredictor + RoomPowerProfile
- `custom_components/universal_room_automation/domain_coordinators/energy.py` — Energy coordinator setup
- `custom_components/universal_room_automation/switch.py` — for adding OccupancyWeightedPredictionSwitch
- `custom_components/universal_room_automation/bayesian_predictor.py` — predict_room_occupancy API
