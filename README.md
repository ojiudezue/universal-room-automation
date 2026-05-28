# Universal Room Automation (URA)

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-blue.svg)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/version-4.6.15-green.svg)](https://github.com/ojiudezue/universal-room-automation/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-3800%2B-brightgreen.svg)](quality/tests)

**The coordinator layer that turns Home Assistant into a self-managing house.**

URA is a Home Assistant custom integration. It runs five domain coordinators (Presence, Safety, Security, Energy, HVAC) on a shared house-state machine, makes decisions every 5 minutes, and exposes everything as standard HA sensors + switches. Sub-second reactions where they matter (intrusion, smoke, motion-into-empty-room). Deliberate 5-min cycles where they don't (battery strategy, HVAC presets, load shedding).

Production install: **18+ months in one home**. v4.6.15 current.

Website: **https://universalroom.org/**
Live dashboard demo: **https://ura.phalanxmadrone.com**

---

## What URA actually does

### The 9-state house-state machine

Every URA decision starts from one of nine states: `home_day`, `home_evening`, `home_night`, `sleep`, `waking`, `arriving`, `away`, `guest`, `vacation`. Transitions are inferred from presence + clock + manual overrides. Every coordinator reads the current state and adjusts behavior.

Override the state manually when you need to (a select entity exposes the override).

### Five domain coordinators

| Coordinator | Picks decisions about |
|---|---|
| **Presence** | Who's home, where they are, which zone they're in, what house state we're in |
| **Safety** | 12 hazard types — smoke, CO, water leak, freeze, intrusion. Cascades to lights, locks, NM, never spams |
| **Security** | Lock + camera + entry-sensor aggregation. Auto-arm on geofence. |
| **Energy** | Enphase battery reserve SOC, EV pause/resume, pool pump speed, smart plugs, HVAC offsets — all keyed to live TOU rates + solar forecast |
| **HVAC** | Per-zone thermostats keyed to house-state preset map. AC overshoot detection from kWh-rate. Solar gain cover management. |

Each coordinator has a master enable switch, an observation mode (compute but don't actuate), and per-feature sub-toggles.

### Why "coordinator layer"

URA does NOT replace your existing Home Assistant setup. Your YAML automations keep working. Your dashboards keep working. URA sits ON TOP, making decisions about high-level house behavior that no single automation can express. Disable URA tomorrow → HA reverts to vanilla. Nothing is permanently changed on your hardware.

---

## Architecture at a glance

```
URA Integration (parent entry)
├── Coordinator Manager
│   ├── Presence Coordinator    — house state, zone presence, multi-source presence
│   ├── Safety Coordinator      — hazard detection, cascading alerts
│   ├── Security Coordinator    — locks + cameras + entry sensors, arming logic
│   ├── Energy Coordinator      — battery strategy, TOU optimization, load shedding
│   ├── HVAC Coordinator        — per-zone presets, AC ramp-down, solar gain mgmt
│   ├── Music Following         — per-person room-following audio
│   └── Notification Manager    — multi-channel routing (iMessage, BlueBubbles, Pushover)
├── Zone Manager
│   └── Zones — physical zones with thermostat + rooms (Master Suite, Upstairs, etc.)
└── Room Entries — per-room sensors, automation, occupancy
```

**Priorities:** Safety 100 > Energy 40 > HVAC 30 > Comfort 20 > Music Following 25. Higher-priority coordinators can preempt or constrain lower ones via signals.

**Storage:** Decisions, anomalies, energy daily snapshots, peak imports, billing cycles → all in URA's own SQLite DB at `/config/universal_room_automation/data/universal_room_automation.db`. URA writes through a managed write queue (batched, budgeted, observable).

**Decision cadence:** 5 minutes for strategy coordinators (Energy, HVAC). Event-driven for reactive coordinators (Safety, Security, Presence). 30-second polling for low-stakes monitoring (lock status, camera availability).

---

## What's in the box (v4.6.15)

- **5 active domain coordinators** (above), all with observation mode + master kill-switches
- **30+ config entries** typical install (1 integration + 1 CM + 1 Zone Manager + N rooms)
- **600+ entities** typical install across 6 platforms (sensor, binary_sensor, switch, button, number, select)
- **HACS-installable** via custom repository
- **Test suite:** 3,800+ tests in `quality/tests/`. Runs in <30 seconds.
- **Documentation:** 4 user manuals + 2 technical explainers (see `docs/`)
- **Standalone PWA dashboard** (separate repo: `ura-dashboard-pwa`) — React + Vite + Zustand, installable on iOS/Android, served from a homelab. Optional.

---

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/ojiudezue/universal-room-automation` as Integration
3. Install Universal Room Automation
4. Restart Home Assistant
5. Settings → Devices & Services → Add Integration → "Universal Room Automation"
6. Follow the config flow: create the integration, add a Zone Manager, add zones, add rooms

### Manual

1. Download the latest release tarball
2. Copy `custom_components/universal_room_automation/` to your HA `config/custom_components/`
3. Restart HA
4. Add via Settings → Devices & Services

### Requirements

- **Home Assistant** 2024.6.0 or newer (2026.5.x recommended; uses modern Coroutinefunction-aware schedulers)
- **Python** 3.12+ (HA OS default)
- **SQLite** (HA built-in)

### Recommended companion integrations

- **Bermuda BLE Trilateration** (`agittins/bermuda`) — precise per-room BLE presence
- **Enphase Envoy** (HA built-in) — battery + solar + grid data for Energy Coordinator
- **Solcast PV Forecast** — solar forecast for Energy Coordinator's strategy
- **UniFi Protect / Frigate** — camera-based presence + safety
- **HACS** — for distribution

Energy Coordinator features are gated on Envoy + Solcast being configured. HVAC's solar-gain features are gated on Envoy too. Both degrade gracefully when those integrations are unavailable (Coordinator refuses to start + raises a Repair issue; rest of URA continues normally).

---

## Documentation

### User manuals (lived-with documentation)

- **[Energy Coordinator user manual](docs/user-manual/ENERGY_COORDINATOR.md)** — battery strategy, TOU, arbitrage, load shedding, grid import cap, all knobs
- **[HVAC Coordinator user manual](docs/user-manual/HVAC_COORDINATOR.md)** — per-zone presets, AC ramp-down, solar covers, energy constraint integration

### Technical explainers (architecture-level)

- **[Energy Management Explainer](docs/ENERGY_MANAGEMENT_EXPLAINER.md)** — concise reference: hardware, control levers, TOU table, decision cycle, sensors, entities
- **[HVAC Management Explainer](docs/HVAC_MANAGEMENT_EXPLAINER.md)** — same shape for HVAC: hardware, levers, preset model, AC ramp state machine, sensors, entities

### Architecture + vision

- **[Vision v7](docs/VISION_v7.md)** — what URA is and isn't
- **[Roadmap v11](docs/ROADMAP_v11.md)** — current near-term queue (v4.7.x Guest Mode Actuation, Dynamic Preset Management, Appliance Coordinator)
- **[Architecture Overview](docs/architecture-overview.md)** — system diagrams
- **[Quality Context](docs/QUALITY_CONTEXT.md)** — the 42 bug classes URA's review process guards against

### Release notes

Most recent in [`docs/readmes/`](docs/readmes/):
- **[v4.6.15](docs/readmes/README_v4.6.15.md)** — thread-safety hotfix (Bug Class #42)
- **[v4.6.14](docs/readmes/README_v4.6.14.md)** — Dashboard Sensor Sweep
- **[v4.6.8](docs/readmes/README_v4.6.8.md)** — EC TOU rate reconciliation + cost surface

Full list: see [GitHub releases](https://github.com/ojiudezue/universal-room-automation/releases).

---

## Quality discipline

URA ships under a tiered review protocol depending on scope:

| Tier | Scope | Review |
|---|---|---|
| Tier 1 | Hotfix; 1-3 files; no new features | 1 staff-engineer adversarial review |
| Tier 2 | Feature cycle; new sensors/entities; multi-file | 2 parallel reviewers + live validation |
| Tier 2-DB | DB-sensitive feature cycle (schema, DAO migration, persisted payload changes) | 3 parallel reviewers with disjoint risk framings |

Every cycle tags a `pre-review` baseline before applying fixes so review-fix diffs are isolated. Live-validation acceptance criteria are mandatory for Tier 2+.

Bug-class catalog in [`docs/QUALITY_CONTEXT.md`](docs/QUALITY_CONTEXT.md) — 42 documented classes from "Lambda + async_create_task in HA scheduler callback" (Bug Class #42, fixed v4.6.15) to "Schema mirror drift in test fixtures" (#39, fixed v4.6.3).

---

## Running tests

```bash
# Full suite
PYTHONPATH=quality python3 -m pytest quality/tests/ -v

# Just a focused module
PYTHONPATH=quality python3 -m pytest quality/tests/test_v4615_threadsafety.py -v
```

3,800+ tests. ~30 second runtime on a modern laptop.

---

## Current focus (post-v4.6.15)

The active queue at the time of this README:

| Cycle | Status | Notes |
|---|---|---|
| **v4.7.x Guest Mode Actuation Phase 1** | Plan filed | HVAC zone preset range overrides under `guest` house state; owns the shared per-(zone, preset, range) override schema |
| **v4.7.x Dynamic Preset Management** | Plan filed | Weather-forecast-driven daily preset adjustment (2 cycles: weather redundancy + preset application). Composes on Guest Mode's override schema. |
| **v4.7.x Appliance Coordinator v3** | Plan filed | Cost-deferral + interrupt-at-start for LG ThinQ + Rainbird; PWA-consumable surfaces |
| **AnomalyType discriminator** | On-tap | Tier 2-DB schema migration for `point_in_time` vs `regime_shift` classification |

See [`docs/ROADMAP_v11.md`](docs/ROADMAP_v11.md) for full near-term roadmap including dependency ordering.

---

## Project stats

- **Current production:** v4.6.15
- **Code:** ~57,000 LoC across 48 Python modules
- **Tests:** 3,800+ across 60+ test files
- **Entities (typical install):** ~600 across 6 platforms
- **Domain coordinators:** 5 active + base framework + manager
- **Config entry types:** 5 (Integration, Coordinator Manager, Zone Manager, Zone, Room)
- **Development:** ~21 months
- **Architecture evolution:** v2.0 → v4.6.15

---

## Privacy + control

URA runs **locally** inside your Home Assistant. No URA cloud. No telemetry. No accounts. No outside dependency for any decision — once Solcast + weather data are fetched (the only network calls URA itself initiates), every decision happens on your hardware. Disable the integration → HA reverts to default behavior.

Every coordinator has an **Observation Mode** — compute decisions, log what they would do, but issue zero service calls. Use it to evaluate URA on your house before letting it actually touch anything.

Every coordinator has a **master kill-switch** + sub-feature switches. Granular off-ramps.

---

## Contributing

URA is currently maintained by one developer for one production house. The architecture is solid; the test coverage is real; the documentation is current. But it's not a community project (yet).

If you're using URA and have a question or improvement idea:

1. Check the [user manuals](docs/user-manual/) first — they're current
2. Open a [GitHub Discussion](https://github.com/ojiudezue/universal-room-automation/discussions) — not an issue
3. For bugs, open an [issue](https://github.com/ojiudezue/universal-room-automation/issues) with the relevant `ha_get_logs` output

PRs welcome but expect a careful review (see "Quality discipline" above).

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgments

- **Home Assistant** community for the platform that makes URA possible
- **Bermuda BLE Trilateration** + **Enphase Envoy** + **Solcast** integrations — URA's data backbone
- **Claude (Anthropic)** for development assistance throughout the v3 → v4 evolution

---

## Support

- **Website:** https://universalroom.org/
- **Documentation:** [docs/](docs/) folder in this repo
- **Issues:** [GitHub Issues](https://github.com/ojiudezue/universal-room-automation/issues)
- **Discussions:** [GitHub Discussions](https://github.com/ojiudezue/universal-room-automation/discussions)
