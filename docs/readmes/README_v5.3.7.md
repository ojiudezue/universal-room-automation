# URA v5.3.7 — EC Envoy Boot-Decoupling + Restore-Poisoning Guards

Incident-driven resilience cycle (2026-06-12 night: flaky Envoy broke URA boot twice + silently disabled 6 EC switches). Tier 2-DB: 3 framing-disjoint reviews + validator + fourth-pass spot-check + 2 fix-up passes. Ledger: `docs/reviews/code-review/ec_envoy_boot_decoupling.md`. Plan: `docs/planning/PLANNING_ec_envoy_boot_decoupling.md`.

## What ships

- **D1 — Three-way Envoy validation** (`energy_const.py`): entity-registry existence instead of one-shot `hass.states.get`. Hard-fail = not in registry / V0 / V1; degraded = registered but state missing or unavailable (boot race, device blip) → EC proceeds; live = pass.
- **D2 — EC always registers when energy enabled.** The `_envoy_validation_ok` gate is gone; only V0/V1 config errors skip EC. A slow/dead Envoy can no longer take battery strategy, TOU, and EVSE logic down for a whole boot. HVAC `net_power_entity` passed whenever registry-known.
- **D3 — Deferred re-validation** at `EVENT_HOMEASSISTANT_STARTED` + failsafe timer for the repair-issue surface; issue kept (not silently cleared) if EC genuinely failed to register; scheduled after CM registration so warm reloads can't race it.
- **D4 — `after_dependencies: ["enphase_envoy"]` removed** from the manifest — eliminates the all-40-entries-stranded failure mode when the Envoy integration hangs at boot.
- **D6 — Bug Class #52 restore-poisoning guards**: RestoreEntity restore is skipped (seed stays authoritative, accounting still converges) when last state is not `on`/`off` — EC sub-switch factory, HVACDynamicPresetSwitch, and 4 additional unguarded sites. Restore-accounting counter is now dynamically registered (no hardcoded 6).
- **D7 — Degraded observability** (kept by operator decision despite thin delta over the existing status enum + NM 3-miss alert): `envoy_degraded` / `envoy_degraded_since` attrs on `sensor.ura_energy_envoy_status`.

## Review trail
- Reviews A/B/C + validator: 0 CRITICAL / 5 HIGH / 6 MEDIUM / 6 LOW → all HIGH+MEDIUM fixed, LOWs fixed in-cycle except A4/B5 (deferred, documented).
- Fourth pass: FIX-FIRST (warm-reload race, counter leak, mirror tests) → fix-up 2 with mutation-check-proven test authority (6 tests fail under inverted guards).
- Suite: failure-ID set byte-identical to pre-cycle develop baseline across all three commits; +23 cycle tests.

## Live Validation — Validated 2026-06-12 (boot 15:58Z)

**The cycle proved itself on its very first boot.** The Envoy entity was AGAIN unavailable at validation time (third boot in a row — enphase_envoy's slow first refresh), and the new path handled it exactly as designed: EC registered anyway, ran degraded, recovered on the next cycle.

| Criterion | Result | Evidence |
|---|---|---|
| Clean restart, all entries, zero URA ERRORs | PASS | 40/40 entries `loaded`; no URA ERROR lines in boot window |
| EC registered + producing despite Envoy race | **PASS — exercised in anger** | Log 10:58:37 CDT: "Envoy deferred re-validation (event_homeassistant_started): still degraded (reason=state_unavailable) — runtime continues, no repair issue." Pre-v5.3.7 this exact condition dropped EC for the whole boot. `tou_period` = `off_peak` at 15:58:46Z, <1 min after boot |
| EC sub-switches match CM options post-restart | PASS | All 10 correct on first boot: 7 intended-ON all ON (incl. solar_hvac_banking, ev_tou_management, grid_arbitrage), 3 intended-OFF all OFF. No restore poisoning recurrence |
| No spurious `energy_envoy_invalid` repair issue | PASS | Deferred re-validation logged "no repair issue" with the Envoy in boot-race degrade; none raised after recovery |
| `envoy_degraded` attrs (D7) | PASS — full lifecycle observed | `true` + `since=10:58:15` during the boot race; cleared to `false`/`null` with `offline_count_today: 0` on the next decision cycle after the Envoy entity recovered (16:01Z, 3.176 kW) |
| Manifest decouple (D4) | PASS (structural) | `after_dependencies` absent from installed manifest; URA booted without waiting on enphase_envoy |
| sub_switches_synced healthy | NOT INDIVIDUALLY READ | Implied healthy by all 10 switches available+correct; accounting symmetry mutation-tested in-suite |
| Registry-absent hard-fail, issue lifecycle, restore-skip guards | IN-SUITE | 23 cycle tests incl. mutation-check-proven guards (production logic inverted → 6 tests fail) |
