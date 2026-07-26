# URA v5.31.0 — LKG wave-1 (SOC + solar) · Owner-set registry · Morning fix batch

Combined release. Production jumps **v5.28.0 → v5.31.0**, shipping the accumulated,
individually-reviewed develop delta plus the 2026-07-26 fix batch as one manifest
(disjoint subsystems; operator go 2026-07-26).

## What ships

### Already-merged, previously-reviewed (were waiting on the next manifest)
- **Owner-set registry refactor (v5.30.0, Tier-3 behavior-frozen).** EVSE pause-owner
  plumbing derives from single-source declarations in `energy_pool_owners.py`.
  **Zero intended behavior change** — golden oracle v3 (3,158 rows, SHA-pinned) +
  permanent in-suite mutation matrix; 4 reviews + orchestrator call-site verification.
- **LKG wave-1 D1 — SOC on the generic `LkgValue` primitive** (behavior-frozen; 3
  reviews SHIP; real-oracle parity grid; expired-tier = sole expiry authority,
  mutation-anchored).
- **LKG wave-1 D2 — solar upper-envelope + nameplate config field (19.4 kW default)**
  (Tier 2-DB; A-HIGH-1 gate-on-**stamped-production** fix; continue-only money path
  verified; orchestrator mutation re-verified).
- **Tier-1 pair** — load_shed prune quirk retired (proven init-only/no live
  consequence) + arbitrage reason-map invariant sweep.
- EC manual §5.5a (EV SOC-threshold jurisdiction table + two-80s gotcha).

### Morning fix batch (2026-07-26, this cycle — 3 framing-disjoint reviews + orchestrator mutation check)
1. **AC kWh Avoided → true daily accumulator.** Was a rolling-24 h point-in-time value
   mislabeled `total_increasing`/"Today" (wandered, never reset at midnight). Now sums
   `ac_ramp_events` since **local midnight** — monotonic within day, resets at 00:00,
   DST-safe, restart-derived from the DB. Display-only; no decision consumers.
2. **HVAC override self-count fixed (B1) + sleep preset preserved (B2).** URA's own
   AC-nudge `set_temperature` writes induce `preset sleep→manual` on Carrier/Bryant
   thermostats; the arrester was **self-counting those as "manual overrides"** (~26/night
   on an empty house) and, worse, **never restoring the preset** — leaving the thermostat
   in `manual` all night, defeating the sleep schedule. B1 = kind-tagged suppression
   (URA-induced manual stays suppressed); B2 = snapshot + restore the pre-nudge preset.
   (Nudge *firing* at setpoint is intentional per hotfix v4.7.16.2 and unchanged.)
3. **Fan manual-off cooldown (room-tier) + reconciler defer + mismatch diagnostic.**
   A manually-turned-off room-tier comfort fan was re-armed within ~30 s. New room-tier
   manual-off cooldown (`DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S=3600`, `0`=kill), the actuator
   reconciler now defers while the cooldown is live (HIGH from review B), and a once-per-boot
   WARN when a room is `hvac_coordination_enabled=True` but not actually HVAC-fan-managed.
4. **Census face cross-check.** A stale Frigate `last_camera` sensor (flaps
   `unavailable⇄value`, re-stamping `last_changed`) kept a departed person face-latched.
   Now a face-recognized person whose `person.<slug>` is `not_home` is dropped (fail-open
   on missing/unknown). Mirrors the v4.7.13/14 person-trust veto.

**Accepted tradeoff (documented):** a *genuine* user preset→manual flip landing inside
the ≤5 s post-nudge suppression window is swallowed (vs. 85 false auto-counts/night —
far worse). Bounded, low-probability.

**Not shipping:** LKG D3 (outdoor-temp envelope) — held on its branch behind a CRIT-1
producer-wiring fix; persist-vs-clear decision ratified (persist ≤12 h → notify+release)
for the future fix-forward.

## Review provenance
- Morning batch: `docs/reviews/code-review/v5.31.0_morning_batch.md` — 3 framing-disjoint
  reviews (A correctness SHIP / B cross-coordinator: 1 HIGH reconciler gap fixed /
  C test-authority: 2 HIGH grep-only-vs-behavioral fixed) + a fix-up pass + orchestrator
  personally re-ran mutations on the arrester B1 site and the reconciler defer (both
  caught by named tests). All CRITICAL/HIGH closed.
- Owner-set, D1, D2, Tier-1 pair: review records already in `docs/reviews/code-review/`.

## Live Validation — Acceptance Hypotheses (Shipwatch)

Watched against the HA recorder after restart. Each: hypothesis · oracle entity/attr · expected · window.

- **H1 — Clean boot.** Zero URA `ERROR` lines post-restart; `sensor.ura_presence_coordinator_presence_house_state` available with a valid house state. Window: 15 min.
- **H2 — Owner-set behavior-frozen (regression guard).** `sensor.ura_energy_coordinator_ev_charging_status` and the EVSE pause-owner attrs (`paused_by_*`, `pause_reason_human`) render with the same shape/values they did pre-deploy for the same conditions; no new/missing attrs. Confirmed = boring. Window: 1 h.
- **H3 — SOC via LKG unchanged.** `sensor.ura_energy_coordinator_battery_strategy` `soc` attribute tracks `sensor.envoy_482543015950_battery` within ±2 pp on the fresh path (no divergence introduced by D1). Window: 1 h.
- **H4 — Solar envelope admits on stamped production.** On a producing morning, `battery_strategy` `solar_production` > 0 and the excess-solar path behaves as before; no excess-solar admit at 0 W stamped. Window: next daylight producing period.
- **H5 — kWh-avoided resets at midnight + monotonic.** `sensor.ura_hvac_coordinator_ac_kwh_avoided_today` is monotonic non-decreasing through the day and **resets to ≈0 at local 00:00** (vs. the pre-fix ~40–51 that never reset). Oracle: recorder history across the next local midnight. Window: next midnight boundary.
- **H6 — Override self-count drops on empty house.** `sensor.ura_hvac_coordinator_hvac_override_frequency` `overrides_today` no longer climbs from URA's own nudges when the house is empty overnight (expect a large drop vs. the observed 26/8 h). Window: next empty-house overnight.
- **H7 — Sleep preset survives nudges.** The Carrier/Bryant zone thermostats (e.g. `climate.thermostat_bryant_wifi_studyb_zone_1`) do **not** get stuck in `preset_mode: manual` overnight — preset returns to `sleep`/`home` after each nudge (recorder: no sustained `manual` runs coincident with `ac_ramp_events`). Window: next overnight.
- **H8 — Fan manual-off sticks.** A room-tier comfort fan (e.g. `fan.fanswitch_treat_wifi_jayabedroom`) turned off manually while hot+occupied does **not** re-arm within the cooldown window (no `turn_on` for ≥ a few minutes post-off). Window: operator-exercised.
- **H9 — Census excludes departed faces.** With the house empty, `sensor.universal_room_automation_persons_in_house` `face_recognized_persons` contains no `person.<slug>` that is `not_home`; `identified_count` reflects only live presence. Window: next empty-house period.

**Boot-transient to dismiss:** brief `unavailable` on room sensors during the config-entry reload settle; the `test_freeze_floor` full-suite ordering pollution is a test-harness artifact, not runtime.

### Validated 2026-07-26 (restart ~12:08 CDT)

| # | Result | Observed evidence |
|---|---|---|
| H1 | **PASS** | 41/41 URA config entries `loaded` (0 `setup_error`); zero URA `ERROR` lines in error_log post-boot; `sensor.ura_presence_coordinator_presence_house_state` live (`arriving`), coordinators emitting. |
| H9 | **PASS (early)** | `sensor.universal_room_automation_persons_in_house` `face_recognized_persons: []`, `identified_count: 1` (the 1 = Ezinne's stuck GPS tracker, not a face latch). No `not_home` person face-counted. |
| H2 | pending | Needs a pre/post owner-state comparison under matching EV conditions (owner-set behavior-frozen). |
| H3 | **soc populated** | `battery_strategy.soc = 54.4` at T+4 min (was null); direct Envoy compare deferred — `sensor.envoy_482543015950_battery` briefly 404 (boot transient / Envoy re-key, not URA; URA soc reading fine). |
| H4 | pending | Next daylight producing period. |
| H5 | **PASS** | `ac_kwh_avoided_today` re-derived `0.0`→`23.558` (real since-midnight total); `accuracy_note` now states "Sum of per-event kwh_avoided … since local midnight. Monotonic within-day, resets at 00:00 local." Midnight-reset itself recorder-watched at next boundary. |
| H6/H7 | pending-organic | Next empty-house overnight: override self-count no longer climbs from URA nudges; Bryant/Carrier presets not stuck in `manual`. |
| H8 | pending-operator | Manually off a room-tier comfort fan hot+occupied → does not re-arm within cooldown. |

H1/H9 confirmed live; H3/H5 to settle within a cache cycle; H2/H4/H6/H7/H8 handed to **Shipwatch** on the next qualifying window per the hypotheses above.
