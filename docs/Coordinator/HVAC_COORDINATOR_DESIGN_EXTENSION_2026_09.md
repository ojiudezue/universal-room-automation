# HVAC Coordinator — Design Extension (v5.103.x, 2026-09)

**Parent:** [`HVAC_COORDINATOR_DESIGN.md`](HVAC_COORDINATOR_DESIGN.md) (the 2026-01 historical spec).
**Operator manual:** [`HVAC_COORDINATOR_MANUAL.md`](HVAC_COORDINATOR_MANUAL.md).
**Status:** current through v5.103.13 · **Last updated:** 2026-09-18

This document records how the HC diverged from the 2026-01 design during the **"make HVAC supple"**
arc (`HVAC-SUPPLE-SEQUENCE-1`, shipped as v5.103.1–.13). Where this doc and the parent design
disagree, **this doc wins** for the areas it covers (control strategy, energy-constraint response,
pre-cool). It cites file:line, versions, and the cards each change came from.

---

## 1. Conditioning-demand: HVAC has its *own* occupancy

The parent design aggregated room occupancy directly (§5). Since v5.103.7, HVAC uses a **separate**
occupancy signal, `RoomCondition.hvac_occupied` (a sibling field, **not** a swap of `.occupied`), rolled
up per HVAC zone as `zone.any_room_hvac_occupied`. Why a sibling: the room-automation `.occupied` is
smoothed/debounced for *lights*; HVAC wants a demand signal tuned to *conditioning* (slower to arm, held
longer). Additions:
- **Circulation exclusion:** rooms of `room_type = hallway` (and other transit types) never generate
  conditioning demand (`ROOM_TYPE_HVAC_HOLD[hallway] = 0`), so pass-through traffic doesn't hold a zone.
- **Per-room vacancy tail-hold:** `CONF_HVAC_VACANCY_HOLD` / `_NIGHT` (per-room, config-flow) extend how
  long a just-emptied room keeps its zone armed; resolved by `hvac_zones._effective_hvac_hold_seconds`
  with a **night ≥ day** clamp. Type defaults live in `ROOM_TYPE_HVAC_HOLD[_NIGHT]` (const.py:1203/1214).
- **Debounce:** the home↔away preset flap was debounced (v5.103.7). Card: `HVAC-ZONE-CONDITIONING-DEMAND-1`.

## 2. D5 duty-cap — reframed from "compressor protection" to honest energy-shed

**The old story was wrong.** D5 forced a zone to `away` when cooling runtime exceeded a fraction of a
rolling 20-min window during EC coast/shed, under the name `runtime_exceeded` implying Bryant compressor
protection. A Bryant/carrier_api audit (`AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md`) established:
the **Infinity/Evolution control board protects the compressor natively** (variable-speed units modulate
rather than cycle; the board logs short-cycling as a fault and self-delays). D5's force-to-away protects
*nothing* — it is occupancy-blind **energy-shed policy**. Fixed in v5.103.9 (`HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1`):
- **Honest name:** `runtime_exceeded` → **`energy_shed_cap_reached`** (no alias).
- **Occupancy gate (no-write defer):** under coast, if a zone is fused-occupied it **defers** the
  forced-away and writes **nothing** to the thermostat (ledger reason `energy_shed_cap_deferred_occupied`).
  **Shed still dominates** (occupied zones still shed under grid stress). Empty zones under coast still
  shed. The no-write matters: a setpoint write flips Carrier to `manual` and can self-lock URA (the S14
  lesson) — so defer means *do nothing*, leaving the occupant comfortable.
- **Knobs to Rung 3 (dashboard-tunable):** the caps + window are live `Number` entities + a master switch,
  labeled **"AC Runtime Cap · Coast / Shed / Window / Enable"**; `0` on a cap = documented kill.
- **Fires only during EC coast/shed** (peak-TOU), never in normal mode — measured ~11×/night house-wide,
  clustered in the 4–7pm peak window. Occupancy-blind night waste is now gated.
- Parked follow-up: `HVAC-D5-REGROUND-ON-ODU-VAR-1` (re-ground the duty estimate on the real `ODU Var %` /
  `stage_status` that `ha_carrier` exposes, richer than the coarse `hvac_action` integral).

## 3. Pre-cool — TWO distinct concepts, one deleted vestige

There are two things historically called "pre-cool." They are **not** the same:

**Path A — the real afternoon solar-banking** (`hvac_predict._should_energy_precool`, v5.7.1). This is the
one that *actuates*. It requires **live PV export/surplus**, fires only in the **10am–2pm window**
(`ENERGY_PRECOOL_HOUR_START..PEAK_HOUR_START`), summer/shoulder, mode `normal`. It banks coolness on
surplus solar before the 4–8pm peak so the house coasts through the expensive occupied evening. It signals
`pre_cool_active` / `pre_cool_likelihood` and applies its own offset (`_get_energy_precool_offset`). Knobs:
enable (switch), offset (Number), scope (Select), SOC floors + forecast threshold (config).

**Path B — the deleted EC-constraint `pre_cool` mode.** The Energy Coordinator used to set a constraint
`mode="pre_cool"` on `off_peak AND soc<50 AND solar_class∈{good,excellent}`. git-blame: born **phase-blind
in v3.7/v3.9** (bare `off_peak`, and off-peak occurs twice a day), it **missed the June-2026 phase-fix its
sibling coast branch got**, was **superseded by Path A (v5.7.1)**, and was **never deleted**. Its outputs
were inert-except-harmful — the −2°F offset was applied only under coast/shed (never under pre_cool), and
`mode="pre_cool"` only *blocked* Path A via its `mode != "normal"` gate. **Deleted in v5.103.11**
(`EC-SOLAR-CLASS-DAYTIME-FORECAST-PROVENANCE-1`); the offset constant is **tombstoned** (kept so a stored
config entry doesn't strand). Consequence: `sensor.ura_energy_coordinator_hvac_constraint` will never show
`pre_cool` again — the authoritative "is it pre-cooling?" signal is **`pre_cool_active`** on the HVAC side.

**Preserved principle (KEEP+DOCUMENT):** Path A is *surplus-only*, so a **hot-forecast day with low morning
SOC** (no surplus) gets no pre-cool — a real uncovered case Path B was reaching for. Parked as
`EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` (a phase-aware off-peak-*grid* pre-cool, reusing `summer_peak_ahead`;
measure-first). Also open: `HVAC-PRECOOL-WINDOW-TOU-DERIVED-1` — the 10–14 window is **summer-hardcoded**,
not responsive to shoulder/winter peaks (derive it from the TOU schedule).

## 4. Pre-cool observability — `pre_cool_skip_reason`

New in v5.103.12 (`HVAC-PRECOOL-SKIP-REASON-OBS-1`): `_should_energy_precool` now records **why it did not
fire**, published on `sensor.ura_hvac_coordinator_mode` as **`pre_cool_skip_reason`**. Values:
`""` (firing/eligible) · `no_constraint` · `off_season` · `outside_window` · `no_pv_surplus` ·
`mode_<mode>` · `already_today` · `soc_unknown_cool_day` · `soc_below_floor`. This closes the blind spot
left when Path B (a misleading label) was deleted, and is the **measure-first signal** for the
grid-anticipatory gap (count `no_pv_surplus` skips on hot days).

## 5. Boot delivery of the EC constraint (restart-day fix)

**The bug the skip-reason obs immediately surfaced.** The EC is set up before HVAC (sequential
`CoordinatorManager`), so the EC's boot decision cycle dispatched `SIGNAL_ENERGY_CONSTRAINT` **before HVAC
subscribed** (fire-and-forget, no replay), and the EC only re-dispatches on a *mode change*. So HVAC's
`_energy_constraint` stayed `None` from boot until the first change (evening coast) — Path A pre-cool (and
any normal-mode constraint consumer) was dead on a restart morning. Fixed in v5.103.13
(`HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1`):
- **Producer-owned builder:** `EnergyCoordinator._build_energy_constraint()` is now the *single source* for
  the `EnergyConstraint` payload — both the dispatch site and a new `current_energy_constraint()` route
  through it (no shape drift).
- **HVAC pulls at setup:** right after subscribing, HVAC calls `energy.current_energy_constraint()` and
  seeds `_handle_energy_constraint()` — ordering-proof (EC fully set up by then), idempotent, and fully
  guarded (energy-absent/None/exception → no-op = old behavior).
- Validated live: post-restart during coast, HVAC held `mode=coast`, `offset=2`, `pre_cool_skip_reason=
  outside_window` (not `no_constraint`), and the D7 dwell (`energy_constraint_duration_s`) survived.

## 6. Attribution & legibility (v5.103.8) + honest labels (v5.103.10)

- **`retreat_reason`** on the zone-preset sensor: why a zone was let go (`vacant_past_grace` /
  `energy_shed_cap_reached` / `energy_shed_cap_deferred_occupied` / `stale_occupancy` / `house_state_transition`).
- **Coast/shed dwell:** `energy_constraint_since` / `energy_constraint_duration_s` on the "10 · Mode" sensor
  (+ RestoreEntity resume-if-same — see §5's D7 note).
- **`hvac_occupied` diagnostics:** ~43 per-room `binary_sensor.<room>_<room>_hvac_occupied` (doubled slug).
- **Labels de-jargoned:** the duty knobs → "AC Runtime Cap · …", the comfort-delay knobs → "Comfort
  Grace · …". The room vacancy-hold config fields carry assistive help text (0 = disabled + per-type
  ranges + night-clamp), and stay **blank when unset** (a prefilled suggested-value would persist on any
  save and pin the room against the type table — deliberately avoided).

## 7. What did NOT change / non-goals
- The Carrier hardware model, zone↔room mapping, fan coordination, and the coast/shed *offset* mechanism
  (parent §2/§3/§6/§7) are unchanged.
- `DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT` is the **only** correctly-named compressor-protection cap and is
  unrelated to D5.
- We did **not** re-ground D5 on ODU stage, build grid-anticipatory pre-cool, or make the pre-cool window
  TOU-derived — all parked/inbox with cards above.

## 8. Card index (this arc)
`HVAC-SUPPLE-SEQUENCE-1` (umbrella) · `HVAC-ZONE-CONDITIONING-DEMAND-1` · `HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1` ·
`HVAC-AWAY-ATTRIBUTION-LEGIBILITY-1` · `HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1` · `HVAC-KNOB-LABEL-PASS-1` ·
`EC-SOLAR-CLASS-DAYTIME-FORECAST-PROVENANCE-1` · `HVAC-PRECOOL-SKIP-REASON-OBS-1` ·
`HVAC-PRECOOL-NO-CONSTRAINT-POST-BOOT-1` · (parked) `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1`,
`HVAC-PRECOOL-WINDOW-TOU-DERIVED-1`, `HVAC-D5-REGROUND-ON-ODU-VAR-1`.
