# HVAC Arc — Remaining Tail (problem/solution)

**As of 2026-09-18, after v5.103.8.** The "make HVAC supple" sequence
(`HVAC-SUPPLE-SEQUENCE-1`) is shipped through step 4 + its knobs/observability.
This is what remains, ordered by priority. Each item is a card on the board.

Six ships closed the core: v5.103.1 (arrester ledger) · .2 (resume-then-pin) ·
.3 (boot-restore + S14 removal) · .4 (lockout telemetry + anomaly) · .7
(conditioning-demand debounce) · .8 (knobs + attribution + coast observability),
plus the 7-hallway reclassification that activated the circulation exclusion.

---

## 1. `HVAC-D5-REFRAME-AND-OCCUPANCY-GATE-1` — planned, plan written, at operator checkpoint

**Problem.** During evening peak-TOU **coast**, the D5 duty-cycle limiter forces a
zone to `away` once its compressor has run a set fraction of a rolling 20-min
window — **regardless of occupancy.** So a kitchen you're standing in gets
abandoned on a hot evening. Its `runtime_exceeded` label implies Bryant
compressor-protection, but the 2026-09-17 audit found **no Bryant grounding** —
it is a URA energy-policy heuristic wearing a safety-sounding name. This is the
one live complaint the v5.103.7 debounce did *not* fix (D5's input is the
thermostat's own `hvac_action`, not the fused occupancy signal).

**Solution.** Gate D5 on the now-live `zone.any_room_hvac_occupied` — under
**coast**, defer the forced-away when a zone is occupied (don't rest the
compressor by abandoning a person); under **shed** (harder grid-stress), preserve
existing behavior. Reframe the reason string to an honest `coast_duty_limit`.
Tier 2-DB (presence ↔ HVAC ↔ EC ripple). **Live comfort/energy tradeoff — held at
an operator pre-build checkpoint** (shed × occupancy precedence). *Also being
researched: whether the Bryant thermostat already protects the compressor
natively, which could make D5 partly redundant — see the Bryant research task.*

## 2. `HVAC-PRESET-LOCKOUT-ESCAPE-1` — planned (gated on a measurement)

**Problem.** `should_change_preset` refuses to write a preset to a zone reading
`manual` — including when *URA itself* caused the manual — so URA can lock itself
out of controlling a zone.

**Solution.** A provenance-aware escape: URA may override a `manual` it induced.
**Gated:** the v5.103.4 lockout-telemetry 24h read decides whether this is
frequent enough to build — don't build on the hypothesis.

## 3. `HVAC-ZONE1-MANUAL-OSCILLATION-1` — waiting_operator (mechanism FOUND)

**Problem.** Zone 1 flapped `manual↔away`; a mystery writer kept re-asserting
`manual`, so named holds never stuck durably there.

**Finding / solution.** Root-caused: the re-manual writer is the **Bryant
thermostat's own schedule**, not URA. So the fix isn't URA code — it's an operator
decision about the Bryant native schedule (disable/align it). This also de-scopes
what the thermostat abstraction must handle. (Directly related to the Bryant
research task: the native schedule is doing more than we credited.)

## 4. `HVAC-SETHVACMODE-CHOKEPOINT-1` → `HVAC-THERMOSTAT-ABSTRACTION-1` — planned / pre-planning (write abstraction, Phase 1 → 2)

**Problem.** Two of three thermostat write verbs (`set_preset_mode`,
`set_temperature`) route through governed funnels, but **`set_hvac_mode` has no
chokepoint — 7 raw bypass sites.** More broadly, callers express *mechanics* (raw
writes) not *intent*, and there is no single vendor-abstraction handle, so
per-vendor knowledge (Carrier quirks) leaks into many sites.

**Solution.** *Phase 1 (Tier 2):* add `emit_set_hvac_mode` and migrate the 7
sites, so all three verbs are governed (a future audit asserts full coverage in
one grep). *Phase 2 (parked):* a `ZoneThermostat` handle owning every push/pull +
the vendor strategy, so it extends to non-Carrier systems and the borrow becomes
its client. Phase 1 was gated on the zone_1 oscillation trace — now resolved as
Bryant-cloud, so it won't over-fit.

## 5. `HVAC-HOT-ENTRY-LATENCY-1` — planned

**Problem.** An occupant walks into an 80°F zone and beats URA to the thermostat
by ~2.5 min, because the decision tick is a hard 5-minute floor — no dwell setting
can react faster (the "binding constraint").

**Solution.** A dedicated ~60s HVAC fast sub-loop for the hot-and-occupied case
(the proven `energy._solar_follow` pattern), leaving the 5-min tick for everything
else. Deferred earlier as the "fast-in" piece; the design is pinned in
`PROPOSAL_hvac_conditioning_demand_2026_09_16.md` (Stage D).

## 6. `HVAC-GUEST-AS-ZONE-PERSON-1` — pre-planning

**Problem.** The guest wing (zone 3) has no assigned residents, so three
identity-gated suppressions (night-trust away-suppression, sleep veto,
person-home bias) are inert there.

**Solution.** Derive a *dynamic* zone-person from an occupied guest room with an
explicit liveness/decay contract — the operator's own idea, and the principled
alternative to a stubbed dummy (rejected as fabricating a trust input).

---

## Residuals from the shipped work (planned, contained)

- **`HVAC-DEGRADED-ROOM-TRIPWIRE-1`.** *Problem:* a zone with a permanently
  disabled/`setup_retry` room never "establishes," so conditioning-demand is
  silently inert for it (safe — won't wrongly retreat — but invisible). *Solution:*
  a code trip-wire that surfaces the degraded room (do NOT relax the safety gate).
- **`HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`.** *Problem:* if guest-mode
  actuation (the "Custom Preset Ranges" switch, currently OFF) is ever enabled,
  D9's unconditional throttle-bypass would emit ~12 setpoint writes/hr/zone to the
  Carrier cloud indefinitely. *Solution:* narrow the bypass to a ground-truth diff.
  **Hard blocker on enabling that switch.**
- **`HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`.** *Problem:* nudge / ramp-audit
  / banking restore-writers put comfort setpoints on an empty night zone and (with
  D9 dormant) nothing re-corrects them. *Solution:* the restore sites invalidate the
  emit cache. Measure-first (likely rare).

## D5 knob cluster (inbox; fold into #1)

- **`HVAC-D5-KNOBS-TO-RUNG-3-1`.** D5's caps/window are Rung-1 constants with no
  kill switch → expose on the knob ladder (Numbers + an enable switch).
- **`HVAC-D5-WINDOW-START-RESTORE-1`.** Verify the duty counter survives a reload
  (contingent — read the restore path first).
- **`HVAC-D5-SLEEP-EXIT-RESET-1`.** The counter accumulates overnight during the
  sleep-skip and can instant-trip on wake (measure-first).

## Parked (with revival triggers)

- **`HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`.** The full 200-min 2–6am
  degradation-defense leniency; uncork only on an *observed* occupied-bedroom
  sensor degradation (Ziri's "dead sensor" was refuted — it was away).
- **`HVAC-PRESET-FLAP-1`.** The original flap ledger; superseded by the debounce —
  dispose at arc close.

---

## Open question — ANSWERED 2026-09-17 (Bryant audit) + a NEW one surfaced

**Was URA's D5 duty-cycle "protection" redundant with the Bryant thermostat's own compressor
protection?** **YES, PARTIALLY.** The Infinity/Evolution control board + equipment delay-on-break
already protect the compressor natively (variable-speed units modulate rather than cycle; the board
logs short-cycling as a fault and self-delays). URA's force-to-`away` does NOT lengthen any compressor
off-time — **it is pure energy-shed policy wearing a protection name** (audit's "zero Bryant grounding"
CONFIRMED). Resolution: **option (b)** — reframe (`runtime_exceeded` → `energy_shed_cap_reached`) +
occupancy-gate (defer for occupied coast zones, shed still dominates) + knobs to Rung-3. NOT delete
(it stays a legit coast/shed load-shed lever on EMPTY zones). Follow-up parked:
`HVAC-D5-REGROUND-ON-ODU-VAR-1` (ha_carrier exposes a richer real-duty signal, ODU Var %/stage_status).
Full detail: `AUDIT_bryant_duty_cycle_redundancy_2026_09_17.md`.

**NEW true-up finding (the deeper yikes).** URA *had* this occupancy fix already — "S14" (2026-08-11)
held occupied zones at a comfort offset during the D5 off-phase instead of forcing away — and it was
**REMOVED 2026-09-16** because a raw setpoint write flips Carrier to `manual`, and `should_change_preset`
then refuses the zone: **S14 created the exact lockout.** So (1) the D5 occupancy-gate must defer as a
NO-WRITE (ledger-only), never restore an offset-hold; and (2) EC's own coast/shed offset is *also*
`occupied_only=True` and setpoint-based — **does it self-lock the same way, house-wide?** Untraced →
carded `HVAC-EC-OFFSET-SELF-LOCKOUT-1` (investigating). That question sizes the lockout-escape (item #2)
and tests whether "EC handles graceful shed on occupied zones" is even true today.
