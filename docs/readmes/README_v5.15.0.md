# URA v5.15.0 — EV Charge-Start Dead-Band Fix ("wake to an uncharged car")

**Cycle class:** Tier 3 (delicate shared-primitive; battery ↔ TOU ↔ EVSE ↔ plugs trust hierarchy).
**Commits:** build `93e8dd05`, fix-up `853827b0`, review doc `c9276548`.
**Review record:** `docs/reviews/code-review/ev_charge_start_deadband_tier3.md`.
**Plan:** `docs/planning/PLANNING_ev_charge_start_deadband.md`.

## The problem, in plain language

The operator kept waking to an uncharged car despite cheap off-peak power all
night. Investigation (2026-07-12, live recorder + source audit) showed URA's
charge-STOP machinery was healthy and persistent, and the v4.7.28 off-peak
ensure-ON also fired correctly every 5-minute cycle — but one stop rule, the
**battery-drain pause**, had a release gate that was unreachable most nights:

- The pause engages when the EV is charging, the battery is discharging
  >100 W, and battery SOC < 50%. That is true **every evening by design**,
  because URA's own battery strategy drains the battery toward its overnight
  "drain target".
- The release required SOC ≤ **static reserve + 2 = 12%**, or SOC ≥ 55%
  *with live solar*. But the battery **parks** overnight at its drain target —
  15–40% depending on tomorrow's solar class — which sits *above* 12 and
  *below* 55-at-night. **Neither release could ever fire before sunrise.**
- Net effect: the EV was vetoed through the entire off-peak window. Two
  floors — the static reserve and the per-night drain target — were never
  reconciled (Bug Class #53).

Live proof from the night of 2026-07-11→12: ensure-on turned the charger ON
at 21:00:58; the drain pause killed it at 21:05:46; it stayed off through
5 hours of off-peak; a 02:00 external start was silently re-killed at exactly
the 1-hour override cooldown. The car got ~2.5 kWh all night.

## What changed (and what deliberately did not)

1. **The release floor is now the battery's REAL park floor.** A new field
   `_last_reserve_level` captures the reserve the battery emitter actually
   commands each cycle (`_result()` is the single chokepoint every decision
   branch returns through — inclement holds and arbitrage parks included).
   `compose_release_floor(battery, tou_period)` composes
   F = max(static reserve, that commanded park), and both the L2 EVSE and
   L1 plug drain calls consume it. The moment the battery parks at its
   planned floor and stops discharging, the drain pause releases and the car
   charges from guaranteed off-peak grid — which is what the code's own
   docstring always claimed it did.
2. **Off-peak only.** The new floor and the anti-flap sticky apply ONLY
   during `off_peak`. During peak/mid-peak the battery legitimately
   discharges deep, and the drain pause keeps its full pre-fix backstop
   semantics (static reserve). This was a review catch (B-H1/D-HIGH-1): the
   first build applied the floor in all periods, which would have disabled
   drain protection during peak on unknown-solar days.
3. **Anti-flap "sticky band" at the floor (F−2 ≤ SOC ≤ F+2).** Inside the
   band the pause does not re-engage — at the floor the battery has nothing
   left to protect, and EV load can pull transient >100 W readings that would
   otherwise flap the charger every 5 minutes. Below F−2 the pause re-arms
   (protection against the hardware reserve failing to hold). A one-shot INFO
   log fires when the sticky suppresses a would-be pause.
4. **L1/L2 parity (operator requirement).** The Moes L1 plug path gets the
   identical floor AND the `solar_replenishing` signal it never received
   before (pre-existing gap: plug releases were reserve-only, the daytime
   solar-recovery release could never fire). A plug designated as an EV
   charger now behaves exactly like the Emporia L2 EVSEs.
5. **Two new diagnostic attributes** on the battery-strategy sensor:
   `current_offpeak_drain_target` (tonight's selected target) and
   `effective_release_floor` (the F actually enforced). The existing
   per-class `drain_targets` map is untouched (not duplicated).
6. **Deliberately unchanged:** the 1-hour manual-override cooldown still
   re-kills an externally-started charge when pause conditions genuinely
   hold (operator decision D3 — anchored by a regression test). No new CONF,
   entities, or schema.

## Review gate (Tier 3 — full detail in the review doc)

- 4 parallel framing-disjoint reviews (A local correctness, B integration/
  state-machine, C test-authority via real per-site source mutation,
  D adversarial completeness) — **all four returned FIX-FIRST, 8 HIGHs**,
  including: the floor missing the inclement/arbitrage park values (A+B+D
  convergent), the period-blind sticky (B+D), and C proving the build's
  headline deliverable had zero real test authority (stub-mirror tests with
  false anchoring claims). All fixed in `853827b0`.
- Focused completeness re-pass (E) on the fix-up's new surface: **SHIP** —
  all 16 emitter branches enumerated, zero-tick floor staleness (including
  the first boot cycle), safe period fallthrough.
- **12/12 source mutations turn a named test red**; the orchestrator
  independently re-ran the park-floor neuter mutation (2 named tests red,
  byte-identical restore, 43/43 green).
- Suite at pre-existing baseline: 35F/6556P/33S/14E, zero new failures;
  +43 tests in `quality/tests/test_energy_pool_drain_release.py`.

## Follow-ups filed (NOT in this release)

- **D-HIGH-3:** three pause sets (`_paused_by_us`, `_paused_by_fill_priority`,
  `_paused_by_grid_cap`) have their only release path behind a config
  toggle — toggle-off while paused pins the device across restarts. Own
  cycle, queued.
- **E-MED-1:** multi-EVSE battery-hold overlay parks reserve outside the
  emitter funnel (starvation direction, self-clears).
- Coordinator-tick test harness (energy.py currently unimportable in tests;
  call-site authority is via the extracted `compose_release_floor` helper —
  disclosed compensating construction).

## Acceptance

```yaml
version: 5.15.0
hypotheses:
  - id: H1
    name: ura_v5150_deployed
    description: v5.15.0 is the running HACS version and all URA entries load.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: update.universal_room_automation_update, attribute: installed_version }
    expected: { condition: "==", value: "v5.15.0" }
    window: { first_check_after: 10m, confirm_after: 1h, alert_if_violated_after: 6h }
  - id: H2
    name: ev_charges_overnight_at_park
    description: On the first non-excellent solar night, once the battery parks at its drain target, the EVSE turns ON within 2 decision cycles (~10 min) and STAYS on (no 5-min flapping) through off_peak.
    oracle: home_assistant
    query: { kind: home_assistant.history, entity: switch.garage_a, window: "21:00-06:00" }
    expected: { condition: "on_within_10m_of_battery_park_and_no_flap" }
    window: { first_check_after: 1d, confirm_after: 3d, alert_if_violated_after: 7d }
  - id: H3
    name: new_floor_attrs_present
    description: Battery-strategy sensor exposes current_offpeak_drain_target and effective_release_floor with plausible values.
    oracle: home_assistant
    query: { kind: home_assistant.state_attribute, entity: sensor.ura_energy_coordinator_battery_strategy, attribute: effective_release_floor }
    expected: { condition: ">=", value: 10 }
    window: { first_check_after: 30m, confirm_after: 2h, alert_if_violated_after: 24h }
```

## Live Validation (prospective — write back observed results post-restart)

| # | Criterion | How to verify |
|---|---|---|
| L1 | Deploy healthy, zero URA errors across restart | error_log scan post-boot |
| L2 | `effective_release_floor` + `current_offpeak_drain_target` attrs present and consistent with tonight's solar class | battery-strategy sensor attrs |
| L3 | **First non-excellent night:** EVSE ON within ~10 min of battery parking at floor; stays on; `energy_status` shows release not battery_drain_paused | recorder: switch.garage_a + SOC + battery-strategy attrs. **If tonight classifies `excellent`, this is PENDING-ORGANIC until the first non-excellent night — the fix is behavior-identical to pre-fix at excellent (release threshold; the sticky additionally removes a pre-existing 1-tick flap at reserve).** |
| L4 | L1 plug parity: Moes plugs release under the same conditions | pause_dispatch_state / plug switch history |
| L5 | No pause/release flapping at the floor (≥1 h stable) | switch history period analysis |
| L6 | Peak-period drain protection intact (regression): EV charging during peak with battery discharging below 50% still pauses | opportunistic — only if the scenario occurs organically |
