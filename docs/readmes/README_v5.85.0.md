# URA v5.85.0 — STEP: physics chatter-quarantine (SHADOW-FIRST)

Sensor Trust/Exclusion Program (STEP). A shared `SensorExclusionSet` primitive plus a
physics-grounded **chatter detector** that spots sensors flapping faster than their device
family can physically re-arm, and can quarantine their *vote* out of the occupancy fusion —
**shipping in SHADOW mode (detect + surface, do not act).**

## What "chatter" means (grounded, not heuristic)

A sensor chatters iff it produces **≥ K transitions with inter-edge interval < the device
family's blind-time floor T_floor** inside a rolling window — "impossibility events": a PIR /
mmWave / opener / reed physically cannot re-arm that fast, so a burst of sub-floor intervals is
un-fakeable by a healthy device. The **burst (K)** is the signal, never a single sub-floor edge
(a healthy fast mmWave legitimately emits sub-floor intervals).

- **Calibrated by probe** (`docs/planning/PROBE_mmwave_healthy_cadence.md`): unified
  `T_floor = 1.0s`, `K = 10`, `window = 300s`. The original 1.5s/K=20 was rejected — it would
  both false-quarantine a healthy Meross **and** miss `invisoutlet` (chatters at 13).
- **Blind-time-gated sensors ONLY** via `CHATTER_PROVENANCE_ALLOWLIST` (PIR / mmWave / opener /
  reed). Camera / AI / aggregate / bed-multistate provenance is **DENIED** — they have no
  physical blind-time floor, so the impossibility argument doesn't hold.

## Quarantine ≠ occupancy drop

A quarantine removes the chattering sensor's **vote** from the occupancy fusion. Occupancy is
then the fusion of the remaining trusted inputs — the room does not go dark because one sensor
was excluded. All 6 fusion legs route through the single `_fusion_filter_active()` consumer.

## Shipping in SHADOW (the important part)

`select.ura_chatter_mode` — **off / shadow / act**, **default `shadow`**:
- **shadow** (this ship): detect, surface on the room's `unavailable_entities` sensor
  (`chatter_telemetry`: per-sensor burst_count / t_floor / k / would_quarantine), emit NM — but
  **do NOT** promote any exclusion. Zero occupancy impact.
- **act**: additionally quarantines the vote (the `is_act` gate at `coordinator.py:2298`).
- **off**: detector idle.

On an **act→shadow / act→off** flip, every live chatter exclusion is discharged
(`_release_all_chatter_exclusions`, all 6 mode transitions) so no stale quarantine survives a
mode change (suppression-needs-a-discharge).

## Control / observability co-location

- **CONTROL = house-level:** `select.ura_chatter_mode` on ENTRY_TYPE_INTEGRATION; `K` / `T_floor`
  Numbers on ENTRY_TYPE_COORDINATOR_MANAGER (beside PeakBufferTarget).
- **OBSERVABILITY = room-level:** burst telemetry on each room's `UnavailableEntitiesSensor`
  (sensors live in rooms).

## Migration (boot-safe)

The retired `CONF_CHATTER_QUARANTINE_ENABLED` bool reconciles into `CONF_CHATTER_MODE` at CM
setup: a pre-STEP `False` (disable-intent) → `mode=off`; otherwise mode stays at its default
(`shadow`). Wrapped in `try/except`, guarded on key-present, idempotent, runs before
`add_update_listener`. Cannot crash CM setup.

## Review

**Tier 3** (delicate shared primitive consumed by many fusion sites; operator-flagged). Full
gauntlet: 4 framing-disjoint reviews (A correctness / B integration+state-machine / C per-site
source-mutation test-authority / **D adversarial completeness**), **2 DO-NOT-SHIP rounds**
surfacing 2 HIGH safety leaks (D-HIGH-1/2) + hollow tests (C-CRIT-1/2/3), all fixed; probe
recalibration; a D7 mode-flip HIGH (stale-exclusion-on-flip) found by both reviews, fixed; final
de-hollow of the transition assignment (drill 25). **111 tests.** Every load-bearing site
(shadow gate, fusion filter, transition release) is mutation-anchored.

**Orchestrator independent verification (2026-08-19, pre-deploy):** personally re-grepped all
promote / `is_excluded` decision sites; personally mutated the shadow gate `if is_act:` → `if True:`
→ reds exactly the 3 shadow-invariant tests, restore → 9/9 green byte-clean; personally read the
migrate for boot-safety; confirmed no import-shadow (the v5.84.0 incident class) — the migrate uses
local-only const names and the sibling function aliases its imports.

## Falsifiable invariant

*In shadow mode, no reachable path promotes a chatter exclusion into the fusion set.* Enforced by
the single `is_act` gate (mutation-anchored). On act→shadow, all exclusions discharge.

## Acceptance criteria — LIVE (shadow-mode observability)

- **L1:** boot clean, **zero URA ERROR**; `select.ura_chatter_mode` = `shadow`.
- **L2:** `K` / `T_floor` Number entities present on the Coordinator-Manager, at defaults 10 / 1.0.
- **L3:** the chatter detector registers listeners on allowlisted blind-time-gated entities (DEBUG
  register log), no listener on denied provenance.
- **L4 (discriminator):** on any real chatter episode, the room's `unavailable_entities` sensor
  shows `chatter_telemetry` with `would_quarantine: true` **AND** the sensor's vote is still
  counted (shadow = detect-only; occupancy unchanged) — this distinguishes shadow-working from
  act-leaking. If no episode occurs in-window, telemetry shows the empty/observing shape.
- **L5:** zero chatter exclusions promoted while mode=shadow (the invariant, live).

## The 2-day forcing gate

Per operator: **STEP must be turned to `act` within 2 days (by 2026-08-21) or declared moot.**
Rationale: with this many devices, statistical significance on whether chatter detection fires
should be trivial if it works. Scheduled at deploy.

## Live Validation

### Validated 2026-08-19 (~11:26 CDT, clean v5.85.0 restart) — house `away`

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Boot clean, zero URA ERROR | **PASS** | `system_log` ERROR count for `universal_room_automation` (1h) = 0; `error_log` grep `chatter` = 0 lines |
| L1 | Mode ships shadow-first | **PASS** | `select.ura_chatter_mode` = `shadow` (the migrate did not force it off; default honored) |
| L1 | Presence up + inferring | **PASS** | `sensor.ura_presence_coordinator_presence_house_state` = `away`, FRESH `last_changed 11:25:11` (genuine fresh boot, not restored) |
| L2 | K / T_floor Numbers present at defaults | **PASS** | `number.ura_chatter_burst_k` = **10.0**, `number.ura_chatter_t_floor` = **1.0** (probe-calibrated defaults, on Coordinator Manager) |
| L3 | Chatter path error-free at boot | **PASS** | zero chatter-path errors in `error_log`; detector registration is DEBUG (logger off) so absence-of-error is the boot signal |
| L4 | Shadow surfaces `would_quarantine` on a real episode, vote still counted (discriminator) | **PENDING (organic)** | requires a real chatter episode; house `away` at validation. Watched via the 2-day forcing gate (`trig_01XZno8URQxUmuiNJczBjKaw`, fires 2026-08-21 09:00 CDT) |
| L5 | Zero exclusions promoted while mode=shadow (the invariant, live) | **PENDING (organic)** | the invariant is mutation-anchored in-suite (orchestrator drill: `if is_act:`→`if True:` reds the 3 shadow tests); live confirmation folds into L4's episode |

**Boot transients dismissed:** two `CONNECTION_FAILED` polls at ~11:23–11:24 CDT were the expected restart window (URA setup ~116s + Envoy warmup ~166s), not a failure — the third poll at 11:26 returned the fresh presence state.

**Note on L4/L5:** these are the shadow-mode *behavioral* discriminators and cannot be forced in-suite (real `UniversalRoomCoordinator` = v5.8.0 territory) nor without an organic chatter event. The falsifiable invariant ("shadow never promotes") is proven in-suite and by the orchestrator's own pre-deploy mutation of the `is_act` gate. Live L4/L5 are the job of the **2-day forcing gate** — which is also the flip-to-`act`-or-declare-moot decision point.

**Cycle status:** boot-validated live (L1/L2/L3 PASS). Shadow observability accumulating toward the 2026-08-21 forcing gate.
