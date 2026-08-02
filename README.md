# Universal Room Automation — your house runs itself

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-blue.svg)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/version-5.45.0-green.svg)](https://github.com/ojiudezue/universal-room-automation/releases)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-3800%2B-brightgreen.svg)](quality/tests)

**Rooms · zones · house.** URA manages your home at three tiers — every
room runs itself (lighting, fans, covers, comfort), rooms aggregate into
zones, and the whole house runs as one system under a nine-state machine —
with domain coordinators (presence, safety, security, energy, HVAC) riding
across all three. Local, observable, reversible. Built on Home Assistant —
it doesn't replace what you have.

Project site: **https://universalroom.org/** · Live dashboard demo: **https://ura.phalanxmadrone.com**

Production install: 18+ months in one home. Current release: **v5.45.0**.

---

## 1. Stop thinking devices

Home automation platforms hand you a folder of devices and a trigger
list. URA changes the unit of thought: a **room is a node** carrying 74+
signals — occupancy, temperature, humidity, light, power, person count,
predictions — not a place where devices happen to live. Rooms roll up
into **zones** (physical areas that share a thermostat and a fate), and
zones roll up into one **house**: a 9-state machine —

`home_day` · `home_evening` · `home_night` · `sleep` · `waking` ·
`arriving` · `away` · `guest` · `vacation`

Every URA decision starts from that state. Transitions are inferred from
presence + clock + manual overrides, and a select entity lets you
override the state whenever you want.

## 2. Three tiers of management

URA is not a bundle of coordinators — the tiers do the work; the
coordinators serve them.

**Room tier — every room runs itself.** Each room entry fuses its own
sensors (PIR, mmWave, BLE, cameras, door/window, temperature, humidity,
lux, power) into one occupancy truth, then acts on it: lighting with
dark-aware thresholds and night-light modes, comfort fans with
temperature ladders and trust guards, humidity fans, covers on schedules
and solar gain, per-room timeouts and overrides. A room is useful on its
own — 40+ of them run this way in the reference install.

**Zone tier — rooms that share a fate.** Zones group rooms around a
thermostat and a physical area: zone presence modes, zone-level cameras
and occupancy confidence, HVAC zone coupling. (House zones and HVAC
zones are deliberately distinct — one thermostat can serve several
living areas.)

**House tier — one system, nine states.** The house state machine
(`home_day` → … → `vacation`) is the single source of truth that room
and zone behavior keys off: presets follow it, security arming can
follow it, notification severity follows it, guest mode is a first-class
state with real policy behind it.

The domain coordinators in §5 are the cross-cutting layer that reads all
three tiers and answers the questions no single room can — who's home,
what's safe, what to spend, what to heat.

## 3. Before and after

Before: 200 trigger-list automations, each blind to the others, each
re-deriving "is anyone home" badly.

After: one observable system. Music follows you, the AC stops
overshooting, the battery saves money — because the right place knows
what's going on.

## 4. Vanilla HA underneath

URA sits **on top of** your existing Home Assistant. Your YAML
automations keep working. Your dashboards keep working. Toggle URA off
and the house reverts to vanilla HA — nothing on your hardware is
permanently changed. Every coordinator additionally has an
**Observation Mode**: it computes decisions and logs what it *would*
do while issuing zero service calls, so you can watch URA think about
your house before letting it act.

## 5. Five coordinators riding across the tiers

| Coordinator | What it runs |
|---|---|
| **Presence** | House state, per-room and per-zone presence, multi-source fusion (motion, mmWave, Bermuda BLE, camera person detection) |
| **Safety** | 12 hazard types — smoke, CO, water leak, freeze, intrusion — severity cascade to lights, locks, notifications. Never spams. |
| **Security** | Locks + cameras + entry sensors as one armed picture. Auto-arm on geofence. |
| **Energy** | Enphase battery, solar, EV, pool, smart plugs vs live TOU rates — with verifiable savings per cycle |
| **HVAC** | Per-zone presets keyed to house state; waste detected from energy (kWh rate), not just temperature; solar-gain cover management |

Each coordinator has a master enable switch, Observation Mode, and
per-feature sub-toggles. Priorities (Safety 100 > Energy 40 > HVAC 30 >
Music Following 25 > Comfort 20) let higher coordinators preempt or
constrain lower ones via signals.

## 6. The engine: two clocks

- **Reflexes in milliseconds** — an event bus for the things that must
  be instant: intrusion, smoke, motion into an empty room.
- **Strategy on a five-minute cycle** — battery strategy, HVAC presets,
  load decisions, issued as **idempotent service calls** so a repeated
  decision is a no-op, not a flap.

State that matters (decisions, anomalies, energy snapshots, billing
cycles) persists to URA's own SQLite DB at
`/config/universal_room_automation/data/` through a managed, batched,
observable write queue.

Architecture:

```
URA Integration (parent entry)
├── Coordinator Manager
│   ├── Presence · Safety · Security · Energy · HVAC coordinators
│   ├── Music Following — per-person room-following audio
│   └── Notification Manager — per-person channels, digests, severity routing
├── Zone Manager
│   └── Zones — thermostat-keyed areas grouping rooms
└── Room Entries — per-room sensors, fusion, automation
```

Diagrams (Mermaid + PDF) in [`docs/diagrams/`](docs/diagrams/):
[system architecture](docs/diagrams/system_architecture.pdf),
[house-state machine](docs/diagrams/house_state_machine.pdf),
[coordinator signal flow](docs/diagrams/coordinator_signal_flow.pdf).

## 7. Recent highlights (v5.x)

The site describes v4.6.15; the codebase has kept moving. Since then:

- **Multi-modal presence fusion doctrines** — extend-not-create (new
  sources extend existing fusions rather than spawning parallel truth),
  divergence-aware confidence, and mmWave fan-corroboration demotion so
  a ceiling fan can't impersonate a person.
- **CameraResolver** (v5.45.0) — cross-integration physical-camera
  resolution: one real camera seen by Frigate, UniFi Protect, and
  Reolink resolves to one node via a correlation ladder (device → MAC →
  identifiers → name-stem → operator declaration; ambiguity never
  guesses).
- **Notification Manager** — per-person channels (iMessage/BlueBubbles,
  WhatsApp, Pushover), severity-aware digests, dedup, stuck-signal
  watchdog.
- **Exterior-person escalation** — perimeter camera person detection
  escalates through the security/notification pipeline.
- **Savings + forecast sensor families** — peak-avoidance and AC-ramp
  savings accounted per cycle in dollars, plus Bayesian occupancy
  forecasts per room.

Full release ledger: [`docs/readmes/`](docs/readmes/) — one README per
version, each carrying its post-deploy live-validation table.

## 8. Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/ojiudezue/universal-room-automation` as Integration
3. Install Universal Room Automation, restart Home Assistant
4. Settings → Devices & Services → Add Integration → "Universal Room Automation"
5. Follow the config flow: create the integration, add a Zone Manager, add zones, add rooms

### Manual

Copy `custom_components/universal_room_automation/` into your HA
`config/custom_components/`, restart, add via Settings → Devices &
Services.

### Requirements

- Home Assistant 2024.6.0+ (recent releases recommended)
- Python 3.12+ (HA OS default), SQLite (HA built-in)

### Recommended companions

- **Bermuda BLE Trilateration** — per-room BLE presence
- **Enphase Envoy** — battery + solar + grid data for the Energy coordinator
- **Solcast PV Forecast** — solar forecast for battery strategy
- **UniFi Protect / Frigate / Reolink** — camera-based presence + safety

Energy features gate on Envoy + Solcast and degrade gracefully when
absent; the rest of URA continues normally.

## 9. Engineering discipline

URA is one production house, run like a product:

- **Tiered adversarial reviews** — hotfixes get one staff-engineer
  adversarial pass; feature cycles get two parallel reviewers with
  disjoint framings; regression-prone and invariant-critical cycles get
  three or four framing-disjoint reviews so blind spots can't converge.
- **Mutation-anchored tests** — for load-bearing invariants (battery
  reserve floors, clamps, gates), reviewers neuter one production site
  at a time and confirm a specific test fails. A site whose bypass
  leaves the suite green is an untested site.
- **Probe-first cycles** — when a cycle's value depends on empirical
  data properties, a one-shot read-only measurement probe over existing
  history runs *before* the plan, and gates each deliverable.
- **Live-validation write-backs** — after every deploy, observed
  results (entity values, log scans, DB reads) are written back into
  that version's README as a validation table. The git history of the
  release READMEs *is* the validation ledger.

The receipts: [`docs/reviews/`](docs/reviews/) (per-cycle review
records), [`docs/readmes/`](docs/readmes/) (release + validation
ledger), [`docs/QUALITY_CONTEXT.md`](docs/QUALITY_CONTEXT.md) (the
documented bug-class catalog the reviews hunt against).

Tests:

```bash
PYTHONPATH=quality python3 -m pytest quality/tests/ -v
```

3,800+ tests, ~30s on a modern laptop.

## 10. Privacy + control

URA runs **locally** inside Home Assistant. No URA cloud, no telemetry,
no accounts. The only network calls URA initiates are solar/weather
forecast fetches; every decision happens on your hardware. Every
coordinator has Observation Mode, a master kill-switch, and per-feature
sub-toggles — granular off-ramps at every level.

## 11. Documentation

- **Project site:** https://universalroom.org/
- **Coordinator manuals:** [`docs/Coordinator/`](docs/Coordinator/) —
  design + operator manuals per coordinator (Energy, HVAC, Presence,
  Safety, Security, Music Following, Notification Manager)
- **User manuals:** [`docs/user-manual/`](docs/user-manual/) —
  [Energy](docs/user-manual/ENERGY_COORDINATOR.md),
  [HVAC](docs/user-manual/HVAC_COORDINATOR.md),
  [Dynamic Presets](docs/user-manual/DYNAMIC_PRESET.md)
- **Explainers:** [Energy](docs/ENERGY_MANAGEMENT_EXPLAINER.md) ·
  [HVAC](docs/HVAC_MANAGEMENT_EXPLAINER.md)
- **Vision + roadmap:** [`docs/VISION_v7.md`](docs/VISION_v7.md) ·
  [`docs/ROADMAP_v11.md`](docs/ROADMAP_v11.md)

## 12. Contributing

URA is maintained by one developer for one production house. It's not a
community project (yet), but questions and ideas are welcome:

1. Check the [manuals](docs/user-manual/) first — they're current
2. Open a [Discussion](https://github.com/ojiudezue/universal-room-automation/discussions) for questions
3. For bugs, open an [issue](https://github.com/ojiudezue/universal-room-automation/issues) with relevant logs

PRs welcome, but expect a careful review (see §8).

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- The **Home Assistant** community, for the platform URA rides on
- **Bermuda BLE**, **Enphase Envoy**, **Solcast** — URA's data backbone
