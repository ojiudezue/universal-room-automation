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

## Live Validation (Review D) — prospective criteria
- [ ] Clean restart; zero new URA ERRORs; all 40 entries loaded.
- [ ] EC registered and producing: `sensor.ura_energy_coordinator_tou_period` non-unknown within ~5 min of boot.
- [ ] All EC sub-switches AVAILABLE and matching CM options after restart (the 2026-06-12 poisoned states must NOT recur — esp. all 7 intended-ON switches ON).
- [ ] `sensor.ura_energy_coordinator_sub_switches_synced` healthy (not PROBLEM) post-restart — proves C1/C7/D2 accounting symmetry.
- [ ] No `energy_envoy_invalid` repair issue with the Envoy healthy.
- [ ] `envoy_degraded: false` attr visible on `sensor.ura_energy_envoy_status`.
- [ ] Manifest decouple: boot order shows no after_dependencies wait on enphase_envoy (loader behavior; proven structurally by manifest diff).
- [ ] Hard-to-prove-live (covered in-suite): registry-absent hard-fail path, deferred re-validation issue lifecycle, restore-skip behavioral guards (mutation-checked).

*Replaced with observed results post-restart per the README write-back rule.*
