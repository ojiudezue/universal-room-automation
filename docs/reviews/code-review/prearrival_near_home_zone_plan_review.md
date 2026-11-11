# Plan review: PREARRIVAL-NEAR-HOME-ZONE-1 (Tier 2, one adversarial plan review)

**Plan:** `docs/planning/PLANNING_prearrival_near_home_zone.md` rev 1 (develop, 2026-11-11), including the D0 result appended in §12.
**Reviewer:** ura-reviewer, plan-review pass, 2026-11-11.
**Read first, completely:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 C1-C39), `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 items 1-32) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted below. No contradiction between those docs and the code read here was found.

## Verdict: FIX-PLAN

One HIGH (INV-NH-3 is broken by the plan's own step ordering, in the common case on this install) and three MEDIUMs (HA semantics cited from the wrong HA version; INV-NH-2 contradicts D2; listener re-registration trigger cites a setup-only site). All are plan text fixes; none changes the shape of the design. The D0 result (CONDITIONAL GO at 3 km only, 2-5 min lead) is an operator marginal-benefit call, not a plan defect.

## Findings

### HIGH-1: INV-NH-3 broken: the home reset (step 3) is gated behind the GPS-source check (step 1), and home events on this install are normally BLE-sourced
- **Where:** plan §2.3 steps 1 and 3; INV-NH-3 (§3).
- **Mechanism:** step 1 says an event whose person `source` is not a `gps` tracker is "ignored (no seed, no fire)". Step 3 (home → memory `inside`) comes after it. HA's person entity takes its source from a non-GPS tracker whenever one reads home:
  - 2026.2 (`.venv-ha`, the plan's citation): `person/__init__.py` `_update_state` prefers a non-GPS tracker reading `home`.
  - 2026.11.1 (the live version, `/Users/okosisi/ha-config/.HA_VERSION`): `person/entity.py` `_update_state` takes `latest_connected or latest_legacy_home or latest_gps or latest_not_home`. `private_ble_device` trackers are `BaseScannerEntity` with `TrackingType.CONNECTION` and `in_zones = [zone.home]` (`device_tracker/entity.py` ~:365-367), so they win whenever the IRK is heard.
  - So while Oji or Ezinne is home with their phone, `person.source` is the BLE tracker. Every `home` event fails step 1 and the memory is never reset.
- **Repro (legal config, common case):** Ezinne drives home from 5 km. Her last usable fix before arrival is 3.3 km out, so the memory reads `outside`. The phone sends no fix inside 3 km before the `home` edge, which is D0 column "none": Oji 71/79, Ezinne 2/10 at R = 3 km. At home, every event is BLE-sourced, so the memory stays `outside`. Next morning she leaves. BLE drops, the person source switches to the GPS tracker, and the first fix arrives at 400 m, `not_home`, inside the zone. Previous = `outside`, current = `inside`, state ≠ home, so the detector FIRES `near_home` on a departure. That starts a pre-arrival episode, an S12 pre-cool borrow and pre-arrival fans in zone_1 for up to 20 min while the person drives away.
- **Fix in plan:**
  1. Step 3 must run FIRST, on `new_state.state == "home"` regardless of source, accuracy or coordinates. Optionally also when `zone.home` is in the person's `in_zones` (2026.11).
  2. Step 1 then applies only to non-home events.
  3. Add tests `test_home_via_ble_source_resets_memory` and `test_departure_after_no_lead_arrival_never_fires`: far fix → `home` with a `private_ble` source → `not_home` GPS fix inside the zone, asserting no fire.
  4. Add the same sequence to D4's departure check.
- **Bug class:** #53-adjacent (a reset computed only on a subset of the paths that need it), plus a state-machine seam.

### MEDIUM-1: §1.2 cites HA 2026.2 semantics; the live house runs 2026.11.1, which differs on three points the plan relies on
`.venv-ha` is 2026.2. `.venv-ha-2611` and the live `.HA_VERSION` are 2026.11.1. In 2026.11:
- **(a) A passive zone's state is NOT always 0.** `Zone._state_is_in_zone` (`zone/__init__.py` ~:577) now counts any person or tracker whose `in_zones` attribute contains the zone. `async_in_zones` (~:147-275) appends every containing zone, including passive ones, BEFORE the "Skip passive zones" check, which only excludes them from the ACTIVE zone. So §1.2's "a passive zone's own state is always 0: it carries geometry, not a signal" is false on the live version. INV-NH-1's clause "never changes a … zone state" is also false as worded: HA itself will change the near-home zone's state and `persons` attribute. It is harmless, because no URA code reads `zone.*` except `security_lock_regime._is_approach_zone` (`security_lock_regime.py:1266-1279`) and the selector at `config_flow.py:9212` (grep of the package). Reword INV-NH-1 to "URA never writes a `person.*` / zone state, and `person.state` never takes the near-home zone's name".
- **(b) `person.state` is unchanged by a passive zone.** Active-zone selection still skips passive zones (`device_tracker/entity.py` `_async_update_zones`, `next(z … if not passive)`). §2.1's central claim therefore HOLDS on 2026.11. Cite this site, not the 2026.2 one.
- **(c) A REUSE candidate the plan did not consider.** `person.attributes["in_zones"]` (and the zone's `persons` attribute) is HA's own membership. With the new companion app, `mobile_app` trackers report `in_zones` from the app itself and HA does not recompute geometry (`mobile_app/device_tracker.py:137-183`). Whether the iOS app's region monitoring includes passive zones is UNVERIFIED. If it does not, `in_zones` never lists the near-home zone, while geometry from coordinates still works. Keeping the URA-side geometry test is therefore defensible, but §1.6 must record this as a considered REUSE candidate and say why it was rejected. If the operator drive test shows the app does monitor the zone, `in_zones` membership is a simpler and earlier signal.
- **(d) A free signal for D4.** Once the zone exists, its recorder history (state = count, `persons`) shows each HA-side crossing directly. Use it as the D4 cross-check, and as the ground truth for the drive test that D0 recommends.
- **(e) Test version.** Tests run on `.venv-ha` (2026.2), but person-source semantics differ on the live version. D2 tests must build `State` objects for BOTH precedence shapes: a GPS-sourced `home`, and a connection-sourced `home` with `in_zones`. They must not depend on HA's person entity logic.

### MEDIUM-2: INV-NH-2 contradicts D2's registration rule
INV-NH-2 says that with "the zone missing / non-passive / unavailable … no `person.*` listener is registered by HVAC". D2 registers whenever the option is set and `near_home` is ticked, and handles a bad zone with a per-event runtime check (one WARNING, no fire). A builder cannot satisfy both, and `test_off_registers_no_listener` will pin one of them arbitrarily. Pick one:
- **Recommended:** INV-NH-2's "no listener" applies only to the option-empty and source-unticked cases. A missing or non-passive zone is "listener registered, zero calls into `_handle_person_arriving`, one WARNING". This also covers a zone created or fixed after boot without a reload.

### MEDIUM-3: The listener re-registration trigger cites a setup-only site, and the options path is unstated
- `_person_zone_map` is built only in `async_setup` (`hvac.py:1408-1411`). `_handle_zm_zones_updated` (`hvac.py:6353`) prunes deleted zones and does NOT rebuild the map. "Re-registered when the person map changes (`:1408-1411`)" therefore names no runtime event, and a builder may invent a rebuild hook.
- `pre_arrival_sources` is read once at setup (`hvac.py:1431-1440`) and is not in `OPTIONS_RELOAD_SUPPRESS_KEYS`, so an options save reloads the CM and HVAC is torn down and set up again.
- The plan should state:
  1. Register once in `async_setup`, after the `:1440` sources read, appended to `self._unsub_listeners`.
  2. No runtime re-registration. Options and zone_persons changes arrive through the reload, which also clears the RAM memory (consistent with §2.3 step 6).
  3. `CONF_PRE_ARRIVAL_NEAR_HOME_ZONE` must NOT be added to `OPTIONS_RELOAD_SUPPRESS_KEYS`. If it ever is, an in-place re-register becomes mandatory.
- D2's "builder verifies at `hvac.py:1431-1440`" is then settled in the plan instead of left to the builder.

### LOW-1: Which observation mode gates the fire is ambiguous
HVAC has its own `_observation_mode` (`hvac.py:717`, `:1175`). Presence gates geofence at `presence.py:5237`, and person_coordinator gates BLE at `person_coordinator.py:1113-1124`. D2 says "presence observation mode" (parity with the other producers, and correct). Specify the read path as the one at `person_coordinator.py:1113-1119` (`coordinator_manager.coordinators["presence"].observation_mode`), and state that HVAC observation mode needs no extra gate here because it already gates writes in the decision cycle. Bug class #23.

### LOW-2: The `SIGNAL_PERSON_ARRIVING` consumer enumeration is incomplete
`music_following.py:281` / `:552` also subscribes. §1.1 and §8.3 omit it. Isolation (INV-NH-1) still holds by construction because the detector calls `_handle_person_arriving` directly. Add the row so §8 is a complete enumeration.

### LOW-3: Diagnostics counter
`near_home_fires_today` needs a local-midnight reset. Reuse the type and reset site of `_pre_arrival_triggers_today` (`hvac.py:7276`) rather than a bare int.

### LOW-4: D0 follow-through must land in the plan before build
- The D0 verdict is CONDITIONAL GO at R ≈ 3 km only. That is lead ≈ 2-5 min over geofence, bounded by the ~100-160 s fix cadence. D0 ran with Oji's sample flap-contaminated and pre-trip, and without the proximity cross-check.
- Required in the plan:
  1. The chosen R.
  2. That the operator drive test is a pre-build gate, as D0 recommends.
  3. The marginal-benefit statement for the operator: a few minutes of earlier pre-cool, for ~100 lines plus a listener.
- A 3 km zone also makes HIGH-1's departure repro wider: most departures cross inside the zone.

## Verified as correct (holds because…)
- **Passive zone does not move `person.state` on the live 2026.11 version.** The active zone skips passive zones (`device_tracker/entity.py` `_async_update_zones`; `zone/__init__.py` `async_in_zones` "Skip passive zones"). The §1.1 raw `person.state` readers are therefore unaffected.
- **INV-NH-1 isolation by construction holds.** `_handle_person_arriving` (`hvac.py:7211-7281`) contains no dispatcher send. Its side effects are the HVAC zone sets, an activity row, diagnostics and the decision kick. It is a `@callback`, so a direct call from a state-change callback is safe.
- **INV-NH-4 holds.** It is falsifiable by diff, and the handler is source-agnostic except for the filter at `:7221`.
- **Prior-art verdicts.**
  - Lock-regime approach zone: `_is_approach_zone` compares `person.state` to the zone name (`security_lock_regime.py:1266-1279`). It only works for a non-passive zone, and the live CM value `security_lockout_approach_zone = zone.home` (read from `.storage/core.config_entries` 2026-11-11) makes it inert. Not sharing the key is correct.
  - P5 proximity: `_on_distance_event` (`:1309-1328`), with the same seed/fire edge shape the plan copies.
  - Not reusing presence's geofence listener is correct (it would need a new signal).
- **Person-zone map is live for the target people.** ZM `zone_persons` lists Oji and Ezinne on Entertainment and Master Suite, and Jaya and Ziri on Upstairs (`.storage`). The live CM `pre_arrival_sources` is `['geofence','ble','camera_face']` (stored), so the new default does not reach this install, as the plan says.
- **Knob ladder.** Rung-1 hysteresis and accuracy, rung-2 zone option and source value, window knob 35 reused. Each states its kill semantics. OK.
- **Acceptance criteria discriminate.** In D4, the source tag and the ordering against the geofence row separate a correct early fire from a departure fire. Add the BLE-sourced-home departure case (HIGH-1).

## Summary
| Severity | Count | Fix in plan |
|---|---|---|
| CRITICAL | 0 | — |
| HIGH | 1 | HIGH-1 |
| MEDIUM | 3 | MEDIUM-1, -2, -3 |
| LOW | 4 | LOW-1 to -4 |

Bug classes: state-machine reset on a partial path (#53-adjacent), observation-mode gating (#23), wrong-version source citation (verify by claim type).

Must-fix before build dispatch: HIGH-1, MEDIUM-1 (a, c, e), MEDIUM-2, MEDIUM-3, and the D0 decision items in LOW-4.
