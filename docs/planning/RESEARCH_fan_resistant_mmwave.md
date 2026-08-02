# Research Survey — Fan Interference with mmWave Presence Sensors (2026-08-01)

Full agent report summarized; key conclusions preserved for the fusion paper + hardware decisions.

## Verdict: PARTIAL body of research
Rotating-blade micro-Doppler is mature radar science (drone/helicopter/wind-turbine detection —
"HERM lines"/blade flashes are trivially separable signatures) — but it is used to DETECT rotors,
never shipped as fan-REJECTION in any consumer presence sensor at any price. Static-clutter removal
(standard in TI reference chains) does nothing for fans (they are MOVING clutter). Human-vs-nonhuman
point-cloud classification performs 90-96% in-lab but requires point clouds LD2410-class modules
don't produce. **Blade-signature notch filtering for fans is an evident research gap.**

## What vendors actually ship
- Aqara FP2: user-drawn interference zones — leaky (documented ghost-inside-interference-zone
  firmware regressions) and blanks real presence in the masked area.
- LD2410/2412 (our fleet): per-gate radial sensitivity only — no angular data; documented to FAIL
  when fan and occupants share a range band (the LD1125H/2410 ceiling-fan community thread is a
  clean negative result).
- **LD2450: the one validated hardware fix** — X/Y target tracking + ESPHome polygon exclusion
  ("Filter") zones over the fan. ~$5-10 module. Users who failed with 2410-class succeeded here.
- 60GHz (Infineon XENSIV / TI / EP Pro class): finer resolution buys USABLE zone exclusion, not
  intrinsic fan immunity — untuned 60GHz can be WORSE (more sensitive to small motion). Fan
  rejection is a processing property, not a frequency property. No rigorous 24-vs-60 comparison
  published.

## Synthesis for URA
Our corroboration/demotion/pause-and-recheck stack is NOT a workaround for missing known tech —
**it is the state of practice, and ahead of industry** (nobody ships fan-signature filtering;
spatial masks leak; fusion remains necessary at every hardware tier).

**Top 3 actions:**
1. Worst fan rooms: swap the fan-adjacent 24GHz gate-only sensor for LD2450-class + polygon
   exclusion zone over the fan (only validated hardware step-change).
2. Placement is a first-class knob: fan inside the FOV cone = unrecoverable by tuning; re-aim first.
3. Keep and trust the fusion layer regardless of hardware.

## Paper-relevant novel contribution candidate
**Fan-periodicity detection in the fusion layer**: fan-speed-correlated re-trigger cadence
approximates blade-signature filtering in software, with no new hardware — the software analogue of
the unshipped micro-Doppler technique. Fold into PLANNING_paper_and_oss_fusion_library.md as a
candidate contribution + evaluation experiment (we have the fan-state + mmWave event data to test it).

(21 sources in the original agent report — academic micro-Doppler, TI/Infineon reference designs,
Aqara/ESPHome/HA community threads; retrievable from session transcript 2026-08-01.)
