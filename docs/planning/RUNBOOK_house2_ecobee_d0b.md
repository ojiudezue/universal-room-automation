# RUNBOOK — House 2 ecobee D0b supervised probe

Plan: `docs/planning/PLANNING_hvac_w1c_p2_ecobee.md` REV 3, §7 D0b plus the binding "D0b go/no-go criteria"
appendix of plan review #2. Script: `scripts/probes/house2_ecobee_d0b_probe.py`. (The plan names
`scripts/probes/ecobee_write_probe.py`; this kit uses the House 2 name. Same deliverable.)

Build of P2 (D1–D6) stays blocked until this run reports **OVERALL GO**.

## What you need
- About 45 minutes at the House 2 thermostat. P2 alone is five writes at least 2 min apart.
- A House 2 long-lived access token (HA profile → Security). Keep it in your shell only. Never commit it.
- Python 3.9+ on the laptop. No extra packages.

## 1. Setup at the thermostat (P0 setup notes, PR2-13)
Set these before the run. Each one moves setpoints by itself and would read as a person.
- [ ] Hold action: **until I change it**
- [ ] No ecobee program / schedule running
- [ ] **Auto heat/cool enabled** (and note the minimum heat/cool delta it shows)
- [ ] Smart Home/Away **OFF**
- [ ] Eco+ **OFF** (including its schedule and peak-relief features)
- [ ] Follow Me **OFF**
- [ ] Indoor temperature is between 66 and 80 °F (the probe aborts outside this band)

## 2. Setup in House 2 Home Assistant
- [ ] The House 2 URA **HVAC coordinator is OFF** (Coordinator Manager).
- [ ] No automation or script writes the thermostat. The probe lists the UI-managed ones that reference the entity.
      YAML-only automations without an `id` cannot be searched — check those by hand. Disable anything listed.

## 3. Dry run first (reads only, sends nothing)
```bash
export HA_URL=http://<house2-ha>:8123
read -s HA_TOKEN && export HA_TOKEN     # paste token; not echoed, not in shell history
python3 scripts/probes/house2_ecobee_d0b_probe.py --dry-run
```
Check: the right climate entity was picked (pass `--entity climate.<id>` if not), the URA HVAC switch shows `off`,
the starting state looks right, the indoor band check is `True`, and every planned write is inside 66–80 °F with both legs.

## 4. Live run
```bash
python3 scripts/probes/house2_ecobee_d0b_probe.py --entity climate.<id> --out house2_d0b_results.json
```
Every write asks for `y`. Anything other than `y` stops the run and restores the starting state.
**Ctrl-C (or SIGTERM) at any time stops the run and restores the starting state automatically.**

| Step | What happens | Your part |
|---|---|---|
| Preflight | Lists climate entities, URA HVAC switches, referencing automations | Confirm coordinator OFF and no writers |
| Snapshot | Prints the full starting state (mode, legs or `temperature`, preset, fan) | Note it down |
| P0 | Asks for hold action, min delta, program, Auto, Smart Home/Away, Eco+, Follow Me | Read them off the thermostat/app |
| P1 | `set_hvac_mode heat_cool` (from `cool`; offers to switch to cool first if already heat_cool). Records state at the moment the blocking call returns, latency, whether legs appear | `y` |
| P2 | Five range writes (70/75, 70.5/75.5, 71/76, 69.5/74.5, 70/74), ≥ 2 min apart. Records state changes per write, single-leg intermediates, echo latency, readback rounding (incl. .5 and 70 °F, also against ±0.5 °F), and any self-move in the gap | `y` each; at the end say which hold the thermostat shows and whether it persists |
| P3 | 72/74 then 70/72 (the winter-home 2 °F gap). Records whether and which leg the ecobee moves → device min delta | `y` each |
| P4 | Writes 70/75, then asks you to change **one leg at the wall**. Records shape (did the other leg move), latency, separability from the URA write | Change one leg, press Enter right away |
| Q4 | Only if P4 was not separable | Accept or not |
| P5 (optional) | Records a wall-unit mode change and back | Do it |
| P6 (optional) | Records the app "Resume schedule" signature | Do it |
| Restore | Restores the snapshot and reads it back | `y` |

## 5. Read the result
The script prints G1–G7 and OVERALL and writes the JSON file (all events with monotonic timestamps).

- **G1** heat_cool exposed, legs present, Auto enabled
- **G2** writes land within measured T ≤ 1.0 °F (if T ≥ 0.5 °F the PR2-4 near-duplicate rule applies)
- **G3** echo p95 ≤ 120 s (else C1 becomes mandatory)
- **G4** device min delta measured
- **G5** wall change separable from the URA write (or Q4 accepted)
- **G6** the HomeKit hold persists (else Q1 before build)
- **G7** starting state restored and confirmed

**NO-GO** if any write produced a no-setpoint (`temperature=None`) state, a single-leg intermediate was seen, the
restore failed, or G1/G2 failed. Report to the orchestrator; do not build.

## 6. After the run
- [ ] Check the thermostat shows the starting state. If G7 is NO-GO, set it back by hand now.
- [ ] Turn back on any automation you disabled. Leave the URA HVAC coordinator OFF until P2 ships.
- [ ] Hand the JSON file to the orchestrator for `docs/planning/AUDIT_house2_ecobee_probe_2026_10_0x.md`.

## Known limits of this probe
- HA's REST service endpoint always calls services with `blocking=True`
  (`homeassistant/components/api/__init__.py`). The non-blocking P1 variant (PR2-5) cannot be run over REST; the
  probe records the state at the instant the blocking call returns. Treat the non-blocking case as unmeasured.
- State changes are observed by polling `/api/states` every 0.5 s (`--poll-s`). An intermediate state shorter than
  that can be missed, so "no single-leg intermediate" is a best-effort result.
- G5 uses a value test (changed leg more than T from the URA value). The timing is recorded for your Q4 judgement.
- P7 (hold expiry / program transition) is not scripted.
