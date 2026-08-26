# URA Cheatsheet — always-on standing context

The load-bearing facts that prevent single-site and wrong-scope errors. This is the **cheap, always-loaded** version — it is inlined verbatim into the `ura-builder` / `ura-reviewer` / `ura-planner` agent system prompts so a fresh agent carries it at zero tool-cost. This file is the canonical copy; keep the inline copies in sync with it. The full docs it points to are opened **on demand**, only when a finding hinges on a detail.

---

- **Geometry:** Room (base: sensors + actuators, per-room occupancy) → house Zone (aggregates rooms) → House. **HVAC zone ≠ house zone** — one thermostat `zone_N` fans out to MULTIPLE house zones; compound HVAC names are legit; don't "fix" them.

- **Scope every value** as room / zone / house / **cross-cutting** (fans, presence-fusion, notifications, anomaly, DB) and change ALL sites at that scope — one missed site is Bug Class #53.

- **Route through the primitive, never hand-roll a second path:** governed-write `emit_set_*` (HVAC), owner-set/peer-hold (EVSE, one switch/many owners), excursion *kinds* (setpoint), `_floor_reserve` (reserve), value-stamp + `command_trail`, `_result` (sole battery emit), the DB `_write_queue` (WAL + single serialized writer — **batch, never per-row**).

- **Value entry/exit:** entry-reset a per-tick value at the top; capture before the first `await` then thread the local; stamp-then-consume-verbatim; clamp BEFORE stamp; byte-identical on the no-op path.

- **Diagnose on ground truth** (actuator state / `command_trail` / a DB row), never display prose (it lies). Regression trip-wires live in the AnomalyDetector wired to NM, not on a calendar.

- **Deep reference — open on demand:** `docs/reviews/URA_ARCHITECTURE_MAP.md` (geometry, coordinators, primitives, anomaly/bayesian/DB-WAL) + `docs/reviews/URA_CODE_TRACING_METHODOLOGY.md` (value-flow: producer → entry/exit → consumers → cross-cycle).
