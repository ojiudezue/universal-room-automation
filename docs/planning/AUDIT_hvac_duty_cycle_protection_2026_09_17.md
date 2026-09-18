# AUDIT — HVAC D5 duty-cycle "protection" (runtime_exceeded)

**Date:** 2026-09-17
**Scope:** READ-ONLY. Re-ground the D5 duty-cycle mechanism that is live-firing on zone_3
(~12% of aways carry `reason=runtime_exceeded`). Distinguish it cleanly from the S14
off-phase ceiling that was **removed in v5.103.3** (`docs/readmes/README_v5.103.3.md:34`).
**Verdict up front:** **NEEDS A CYCLE.** D5 is a URA-invented energy-shed heuristic, NOT a
Bryant/Carrier compressor protection spec. It is on the wrong knob rung, mis-framed in the
reason ledger, and (by design) can push OCCUPIED zones to `away` for up to a full 20-minute
window under coast/shed. Step-4-B's `hvac_occupied` fused signal will NOT reduce its firing
rate — D5's runtime input is thermostat `hvac_action`, not URA occupancy flapping.

---

## 1. History uncorked

| Artifact | file | Relevance |
|---|---|---|
| README v3.17.0 §D5 | `docs/readmes/README_v3.17.0.md:35-38` | Original ship. Framing: "20-min rolling window; coast 75%, shed 50%. Skip during sleep (RH4). Reset only on normal→constrained." **No Bryant/Carrier spec cited.** |
| README v5.103.3 (S14 REMOVED) | `docs/readmes/README_v5.103.3.md:34-98` | Distinguishes S14 (raw off-phase ceiling write, removed) from D5 duty-cycle enforcement (kept live). |
| Comfort-delay bypass on D5 | `custom_components/.../hvac.py:1899-1955` | ARREST-COMFORT-1 §3.4 lets a D3 guard SKIP the D5 forced-away when `comfort_delay_active AND SOC≥floor AND not blind AND not shed`. Shed still dominates. |
| Post-peak coast RELEASE | `hvac.py:2771-2784` (comment cites v4.7.30 Review B-MED-1) | Fix to clear runtime counters on constrained→normal so the flag doesn't ride the tail of the window and pin a zone to away after release. |
| `_accumulate_zone_runtime` | `hvac.py:3331-3375` | The tick loop that produces `runtime_exceeded`. |
| Constants | `hvac_const.py:396-399` | `DUTY_CYCLE_WINDOW_SECONDS=1200; DUTY_CYCLE_COAST=0.75; DUTY_CYCLE_SHED=0.50`. Comment header says only "v3.17.0: Duty cycle". No compressor spec, no Bryant link. |

Prior planning-doc grep for "duty_cycle" / "DUTY_CYCLE" turned up **zero dedicated planning
doc** for the mechanism — it entered as one of the seven deliverables of the v3.17.0 Zone
Intelligence README and has ridden since. That is the entire paper trail.

---

## 2. Logic, grounded (cite-only)

**Producer — `_accumulate_zone_runtime(now)` at `hvac.py:3331-3375`.** Called from the HVAC
tick loop.

1. `elapsed = min((now - self._last_runtime_accumulation).seconds, 300.0)` — real wall-clock
   delta, capped at 300s (`hvac.py:3338-3342`). This means at tick cadence the accumulator
   is honest even if the loop stalls, but a >5-minute stall silently under-counts.
2. Per zone:
   - Initialise window if unset (`hvac.py:3346-3349`).
   - **Window expiry reset:** if `(now - zone.window_start) >= 1200s`, reset
     `window_start=now`, `runtime_seconds_this_window=0`, `runtime_exceeded=False`
     (`hvac.py:3352-3355`).
   - **Accumulation gate — this is load-bearing:**
     `if zone.hvac_action in ("heating", "cooling") and elapsed > 0`
     (`hvac.py:3358-3359`). The runtime source is the *thermostat's own reported action*
     (`hvac_zones.py:444` — `zone.hvac_action = state.attributes.get("hvac_action", "")`),
     NOT URA's preset writes and NOT `any_room_occupied`. So D5 does **not** count URA's
     own away/home flapping into runtime; only actual compressor activity.
   - **Mode gate:** in `normal` the function `continue`s (`hvac.py:3367-3368`) — no
     enforcement. Only `coast` and `shed` enforce.
   - **Sleep skip (RH4):** `if self._house_state == "sleep": continue` (`hvac.py:3370-3372`).
   - **Cap:** `max_seconds = 1200 * 0.75 = 900s` under coast, `1200 * 0.50 = 600s` under
     shed. Once `runtime_seconds_this_window >= max_seconds`, `zone.runtime_exceeded = True`
     (`hvac.py:3374-3375`).

**Reset paths** (`hvac.py:2762-2784`, `_handle_energy_constraint`):
- **normal → constrained (coast/shed):** clear all zones' `window_start`,
  `runtime_seconds_this_window`, `runtime_exceeded`. Intentional (comment 2763): "not on
  coast↔shed bounces, which would defeat enforcement."
- **constrained → normal:** ALSO clear (`hvac.py:2780-2784`, v4.7.30 B-MED-1). Otherwise
  the flag lingers up to a full window and keeps the zone forced-away after RELEASE.
- **coast ↔ shed bounces:** no reset. The 600s cap becomes retroactively binding when
  dropping from coast to shed; accumulated runtime under coast is not zeroed.

**Consumer — forced away:**
- `hvac.py:1928` — early D5 branch: if `zone.runtime_exceeded and _house_state != "sleep"`
  and the D3 comfort-delay bypass conditions are NOT all met, `effective_preset = "away"`
  (the actual assignment lives at S14's former site; the D3 branch skips it when granted).
- `hvac.py:2103` — the vacancy-or-runtime shortcut: if
  `(zone_vacant_past_grace or zone.runtime_exceeded) and effective_preset == "away"` and
  zone is already away, `continue` (same-write suppression). This is a **shared write
  path** — see §4b.
- `hvac.py:2200-2201` — reason-ledger tag: when `effective_preset == "away"` AND
  `zone.runtime_exceeded`, `preset_change_reason = "runtime_exceeded"` (this is the exact
  string the operator saw at 12% on zone_3).
- `hvac.py:2259-2263` — S1 chokepoint's DEFER-reason set includes `runtime_exceeded`, so
  under `comfort_delay_active` an in-flight D5 write is deferred by the emit chokepoint.

**Restore across reload:**
- `hvac_zones.py:610, 643, 692` — `runtime_seconds_this_window` is snapshotted and restored.
  `window_start` is NOT in the restored fields visible in the grep window (§4c).

---

## 3. Bryant / Carrier grounding — VERDICT: **URA-invented heuristic, not a manufacturer spec**

Full-domain grep of `custom_components/universal_room_automation/domain_coordinators/` for
`Bryant | Carrier | Infinity | compressor` returns:

- `hvac_excursion.py:608, 724, 1057` — mentions Carrier settle latency (~60s), unrelated.
- `hvac_const.py:502-503, 583, 597, 610, 1137` — Bryant polling cadence (~60-90s), variable-
  speed modulation behaviour, cloud-fault handling. **None cite a compressor duty-cycle or
  min-off-time spec.**
- `hvac_const.py:561` — `DEFAULT_HVAC_AC_HARD_RESET_DAILY_LIMIT: Final = 2  # compressor
  protection cap`. This IS framed as compressor protection, but it is a **different
  mechanism** (AC ramp-down hard-reset daily cap, `README_v3.17.0.md:274-280`), not D5.
- `hvac_const.py:396-399` — the D5 constants themselves carry **no comment linking them to
  any manufacturer spec**. The block header is a bare "# v3.17.0: Duty cycle."
- `README_v3.17.0.md` §D5 — no Bryant/Carrier spec, no cycles-per-hour figure, no min-off
  time. Framed as an *energy-mode* rule ("Coast mode: 75% max runtime. Shed mode: 50% max
  runtime"), not a hardware protection rule.

**Conclusion:** D5's numbers (20 min, 75%, 50%) are URA-chosen shed-policy knobs. Calling
the resulting condition "compressor-protection" (as the operator's framing did) is
**misleading — the mechanism is a load-shedding policy**, not a compressor-cycles-per-hour
guard. The variable-speed Bryant/Carrier compressors URA drives modulate continuously and
do not need URA to enforce a duty cycle for their own safety; the Infinity board handles
its own minimum-off-time. **Flag the constants as un-grounded knobs.**

---

## 4. Soundness audit

### 4a. Does `runtime_exceeded` fire spuriously via URA-induced flapping?

**No, not directly.** The accumulator gates on `zone.hvac_action in ("heating","cooling")`,
which is the thermostat's own reported action (`hvac_zones.py:444`). URA-forced
preset=`away` widens the setpoint band; if the compressor stays running to reach the
widened band, `hvac_action` remains "cooling" and runtime keeps accumulating. **This is a
self-consistent feedback path, not a runaway:** if the compressor stops (thermostat reads
`idle`), runtime stops accumulating. If it keeps running because the setpoint band is still
narrower than the room delta, the shed is legitimately not achieving relief — which is the
condition D5 is designed to detect. **No vicious-cycle bug.**

### 4b. Interaction with vacancy retreat (both write `away`)

Both D1 vacancy (`zone_vacant_past_grace`) and D5 (`runtime_exceeded`) converge on the same
target (`effective_preset = "away"`) and share the same-write suppression branch at
`hvac.py:2103`. When both are true, the reason-ledger precedence at `hvac.py:2196-2201`
ranks `stale_occupancy > vacant_past_grace > runtime_exceeded`, so a zone that is BOTH
vacant AND runtime-exceeded logs `vacant_past_grace`. **Correctness-wise this is fine**
(same delivered preset, no double-write, no oscillation). **Attribution-wise the 12%
runtime_exceeded number on zone_3 is therefore an under-count of D5's real reach — it
only counts ticks where D5 fired while D1 did NOT.** Read that carefully.

### 4c. Reset correctness across preset / house-state / reload

- **Preset changes:** no coupling. Correct — D5's input is thermostat `hvac_action`, not
  URA presets.
- **House-state transitions:** `sleep` is the only special case (skip enforcement AND skip
  firing; `hvac.py:3370-3372`). Runtime KEEPS accumulating during sleep because the
  `continue` is below the accumulator; when sleep ends the counter is already at whatever
  it was, and the cap check then fires. **Latent surprise:** waking into `coast/shed` can
  instantly trip `runtime_exceeded` on any zone that ran heavily overnight, forcing away on
  wake. Worth verifying live.
- **Reload / restart:** `runtime_seconds_this_window` is persisted (`hvac_zones.py:643`)
  and restored (`hvac_zones.py:692`). Whether `window_start` is persisted is not shown in
  the grep window — if it is NOT, then a restart resets the window to `None` on next tick
  and the counter is orphaned (accumulated seconds vs a freshly-started window → early
  false trip). **FLAG for verification** (`hvac_zones.py:685-700` — worth reading fully in
  the follow-up cycle).
- **coast ↔ shed bounce:** intentionally NO reset. A zone that accumulated 700s under coast
  (below the 900s coast cap) then bounces to shed will instantly trip the 600s shed cap.
  Correct-by-design per the 2763 comment.

### 4d. Does D5 read the NEW per-room `hvac_occupied` (step-4-B)?

**No, and step-4-B does NOT help.** D5's inputs are:
- `zone.hvac_action` (thermostat attribute, `hvac_zones.py:444`)
- `self._energy_constraint_mode` (Energy Coordinator dispatch)
- `self._house_state` (only to skip in `sleep`)

None of these are the fused per-room `hvac_occupied`. The mechanism is entirely OCCUPANCY-
BLIND. Step-4-B's debounce (`HVAC-ZONE-CONDITIONING-DEMAND-1`) narrows the D1 vacancy path
and adds a caller-side point-gate on the DPM setpoint composition (D7/D9); it does not
touch D5. **D5 will keep firing at the same rate after step-4-B ships**, and — because D5
forces away on OCCUPIED zones during coast/shed — it will now visibly compete with
step-4-B's INV-1 ("no sleeping resident's own bedroom falls to away"). Sleep-skip
(`hvac.py:3371`) covers the night window; the daytime coast/shed case does not.

### 4e. Knob placement

`DUTY_CYCLE_WINDOW_SECONDS`, `DUTY_CYCLE_COAST`, `DUTY_CYCLE_SHED` — all module constants
(`hvac_const.py:397-399`). No `CONF_*`, no options-flow field, no `Number` entity.

Per the Numbers-Get-Knobs ladder in CLAUDE.md, a policy value that governs how often URA
forces an occupied zone to `away` during energy events is a **legitimate operator-tunable
policy knob (Rung 3)**, not a safety bound (Rung 1). It's currently on the wrong rung.
There is no kill switch — `0` for `DUTY_CYCLE_SHED` would (per the current `>=` compare)
fire immediately on any runtime; there is no clean "disable D5" toggle.

---

## 5. VERDICT — needs a cycle

D5 duty-cycle enforcement is **not compressor-protection**, is on the wrong knob rung, is
occupancy-blind, and its reason-ledger label (`runtime_exceeded`) mis-suggests a hardware
safety mechanism. It is not urgently harmful (correct in mechanism, no vicious cycle, no
regression risk from doing nothing), but it is fair game for a small correctness/framing
cycle, especially in the shadow of step-4-B.

**Scope for the cycle — Tier 2 (regression-prone: touches HVAC preset path shared with
step-4-B, D1 vacancy, comfort-delay S1 gate):**

1. **Reframe the reason string.** `runtime_exceeded` → `energy_shed_cap_reached` (or
   similar). Update the ledger allow-list (`hvac.py:2168-2178`), the reason-precedence
   test, and any dashboard/README references. Keep the attribute name `runtime_exceeded`
   internally for now to minimise ripple, or rename in the same cycle if disjoint.
2. **Occupancy gate.** Before firing `runtime_exceeded=True` (or before consuming it at
   `hvac.py:1928`), read `zone.any_room_hvac_occupied` from step-4-B. If the zone is
   occupied by the fused signal AND we are not in `shed` (shed still dominates), SKIP the
   forced-away and log `reason=energy_shed_cap_deferred_occupied`. Piggyback on the D3
   comfort-delay accessor pattern already established at `hvac.py:1928-1955`.
3. **Knob placement (Rung 3).** Add `Number` entities:
   `number.ura_hvac_duty_cycle_window_minutes` (default 20, range 5-60),
   `number.ura_hvac_duty_cycle_coast_pct` (default 75, range 0-100 — 0 disables coast
   enforcement), `number.ura_hvac_duty_cycle_shed_pct` (default 50, range 0-100 — 0
   disables). `0` = kill switch, documented on the knob.
4. **Verify `window_start` restore.** Read `hvac_zones.py:685-700` end-to-end; if
   `window_start` is NOT restored, add it (Bug Class prior-art: restore-then-orphan).
5. **Live-validate on the wake-from-sleep-into-coast/shed case (§4c).** One-shot query
   against the URA DB `preset_change` rows carrying `reason=runtime_exceeded` within
   ±5min of a house_state transition out of sleep. If clustered, add "reset window on
   sleep exit" as a §2b sub-deliverable.

**Card candidates (stubs — for adjacency-sweep + minting):**

- `HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1` — Tier 2. Owns items 1+2. Depends on
  `HVAC-ZONE-CONDITIONING-DEMAND-1` (step-4-B) shipping the fused `hvac_occupied`. Blocks
  on: nothing.
- `HVAC-D5-KNOBS-TO-RUNG-3-1` — Tier 1. Owns item 3. Additive Number entities; safe.
- `HVAC-D5-WINDOW-START-RESTORE-1` — Tier 1, contingent on §4c grep verifying the gap.
- `HVAC-D5-SLEEP-EXIT-RESET-1` — Tier 1, contingent on §5-item-5 live measurement.

**Non-goals:**

- Do NOT rename `runtime_exceeded` at the internal attribute level in this cycle unless
  item 1 is scoped as attribute+string; the string alone is the operator-facing surface
  driving the confusion.
- Do NOT add a "compressor-cycles-per-hour" spec-based limit; if the operator wants real
  compressor protection, that's a separate cycle grounded in a Bryant/Carrier Infinity
  service manual, and per the AC hard-reset cap (`hvac_const.py:561`) the safety envelope
  already lives elsewhere.

---

## 6. Summary for the operator

- **Logic in plain terms:** every tick, for each zone, if the thermostat is actively
  heating/cooling AND we're in `coast` or `shed` AND it's not sleep, add real elapsed
  seconds to a 20-minute rolling counter. If the counter crosses 75% (coast) or 50%
  (shed) of the window, flip the zone's preset to `away` for the remainder of that window.
  Counter resets on window expiry, on normal→constrained, and on constrained→normal.
- **Bryant grounding:** none. Zero code comments, zero README references, zero manufacturer
  spec ties the numbers to a compressor duty cycle. It's a URA-invented energy-shed
  policy that has been ambiently mislabeled as "compressor protection."
- **Does it need work?** Yes — Tier 2 cycle to reframe the ledger reason string, add an
  occupancy gate that consumes step-4-B's fused `hvac_occupied`, promote the knobs to
  Rung 3, verify `window_start` restore across reload, and check the wake-from-sleep-into-
  shed edge live. Nothing urgent, nothing dangerous — but keep it off the compressor-
  protection story it doesn't earn.
