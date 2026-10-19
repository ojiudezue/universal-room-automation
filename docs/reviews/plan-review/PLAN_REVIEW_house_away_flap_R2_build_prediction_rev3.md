# Plan review R2 (adversarial build-prediction): House AWAY flap, Rev 3

**Plan:** `docs/planning/PLANNING_house_away_flap_untracked_occupant.md` Rev 3 (`d4794ebd8`, develop)
**Card:** HOUSE-STATE-AWAY-FLAP-UNTRACKED-OCCUPANT-1, Tier 3
**Reviewer:** ura-reviewer, framing R2 ("what will the builder get wrong?"), 2026-10-18
**Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger 1-12) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted here. Every finding below cites code read on `develop` @ `d4794ebd8`.

**Verdict: FIX-PLAN.** There are 4 HIGH, 5 MEDIUM and 5 LOW findings. All of them are plan-text fixes; none needs a new probe. The two traps the plan names itself are stated unambiguously (§1). The HIGHs are traps the plan does not name.

---

## 1. The two named traps: stated unambiguously?

| Trap | Verdict | Evidence |
|---|---|---|
| Guard after each branch's already-AWAY check | **PASS** | D2 "Placement" plus INV-ALREADY-AWAY say it three ways, and name the outer-`if` anti-pattern and its consequence (`presence.py:1297` ARRIVING). The anchor test `test_alpha_guard_never_produces_arriving_from_away` carries a mutation. The order is right for all three branches: nobody-home `:1128`, α `:1176`, β `:1272` (β's AWAY check already sits inside the branch, after the conjuncts). |
| No UTC `now` into `infer()` | **PASS** | D2 plus C11. `infer` defaults `now = dt_util.now()` (`presence.py:1112-1115`) and uses `now.hour`. The only `infer` caller is `presence.py:6487` and it passes no `now` (grep `\.infer(` gives 1 production site). One residual is LOW-5. |

---

## 2. Findings

### HIGH

**R2v3-H1: INV-DISCHARGE is false as written. Guard fall-through can move an empty house into SLEEP (600 s dwell), GUEST (300 s) or HOME_*.** Bug class: state-machine × time seam; the invariant is wrong.
- D2 says a denied branch should "fall through" and that this "equals today's conjunct-false path". After α and β, `infer()` keeps going: `has_people` (`:1292`), the ARRIVING→HOME step (`:1303`), GUEST exit (`:1325`), **sleep hours → `return HouseState.SLEEP` (`:1330-1334`)**, WAKING, GUEST entry, then time variants.
- INV-DISCHARGE bounds acceptance at "≤ 120 s for HOME_*". `DEFAULT_HYSTERESIS` (`house_state.py:129-139`) gives SLEEP 600 s, GUEST 300 s and WAKING 60 s.
- **Legal repro.** Defaults are sleep 23→06, W = 180.
  1. 23:01:00: the last occupant walks the hallway. An interior camera sets `unidentified = 1`, which stamps B.
  2. 23:01:40: they are gone. Phones go `not_home`, unid = 0, face = 0, and the room tails keep `any_zone_occupied = True` (300 s tail).
  3. α is eligible but guard-denied, so control falls through. `has_people` is True and it is a sleep hour, so `infer` returns **SLEEP**. HOME_NIGHT dwell is long past, so the transition is **accepted**.
  4. Zones get `set_sleep(True)` (`presence.py:~7027`), HVAC applies sleep presets, and **AWAY cannot be accepted before 23:11:40**.
  5. Without the guard, α returns AWAY at 23:01:40.
- From ARRIVING the same fall-through turns a ghost-ARRIVING collapse into ARRIVING→HOME_* (`:1303-1305`). That also skips the `_arriving_last_was_outdoor_only` re-arm cooldown (`presence.py:6992-7008`).
- **Fix in plan:** separate the two holds.
  - **Guard A** means the house may be empty and we are waiting. On a denied branch with `current_state != AWAY`, use `return None` (hold the current state). This is safe for INV-ALREADY-AWAY because the AWAY check precedes it, and it cannot emit SLEEP, GUEST or ARRIVING→HOME on a would-be-AWAY tick.
  - **Veto B** means someone is home. It keeps fall-through, because SLEEP or GUEST with a guest in GB1 is correct.
  - Restate INV-DISCHARGE with the real dwell table. Add `test_guard_hold_does_not_enter_sleep_on_would_be_away_tick` (mutation: fall-through instead of None → RED) and `test_guard_hold_from_arriving_returns_none`.
  - The current `test_discharge_while_hysteresis_blocks` would encode the wrong 120 s bound.

**R2v3-H2: The fan and veto B form a feedback loop that holds an empty house HOME for the full cap, and every HA restart grants a fresh cap.** Bug class: suppression without a discharge; open-loop measurement of a closed-loop system.
- The comfort-fan veto acts only in `{AWAY, VACATION}` (`fan_veto.py:60`, `:167`). Veto B keeps the house out of AWAY, so the fan is never vetoed. The fan keeps the LD2410 phantom alive (ledger #1: Jaya 68% presence with the room empty and the fan on). The phantom keeps `binary_sensor.jaya_bedroom_occupied` on, which keeps veto B, which keeps the fan running.
- P3 simulated veto B over history in which α had already fired AWAY and the fan veto had broken the loop. The 0 C1 / 9 C2 control minutes are therefore **open-loop numbers** and do not bound the closed loop.
- §3.4's row "Comfort-fan AWAY veto: fans not vetoed on the occupant (intended)" misses this.
- **Cap semantics under restart:** D3 boot-seeds `occupied_since` from `last_changed` with "no residual clamp: the cap must count the real run". HA does not restore `last_changed` across a restart; the entity's first write at boot sets it. So after every restart the run restarts at about boot time, and the cap is **per restart, not per real run**. `test_occupied_since_boot_seed_counts_real_run` passes on a mock and is false live.
- **Legal repro.**
  1. Jaya Bedroom cap = 16 h. Everyone leaves Friday 08:00 (operator travel is a live pattern) with Jaya's fan on, a phone flagged `phone_left_behind`, or all phones `not_home`.
  2. The LD2410 phantom holds continuously (the 300 s tail bridges its gaps).
  3. The house stays HOME until 00:00 Saturday.
  4. A deploy restart at 22:00 re-seeds the run, so the hold continues to 14:00 Saturday.
  5. Jaya's HVAC zone stays on comfort the whole time, because the room's own HVAC occupancy holds as well.
  Under the restart-storm pattern (memory: up to 8/night), the hold has no bound.
- The answer to "can veto B hold HOME forever?" is therefore **yes, via restarts**. Without restarts it is bounded at 16 h, through the fan loop.
- **Fix in plan:**
  - Persist nothing new. Instead bound the run with an independent clock: seed `occupied_since = min(last_changed, the recorder's last off→on for the entity)`, or more simply clamp the post-boot residual to `cap − (now − boot)`. Alternatively state that a restart grants a fresh cap and **lower Jaya's cap** to match that.
  - Name the loop breaker. If the fan pause-recheck (`presence_fan_recheck.py`, VACATED → `leave_off=True`) is meant to end the phantom, say so, check that Jaya's recheck is enabled live, and add `test_veto_room_phantom_with_fan_released_by_recheck_or_cap`.
  - Otherwise add a fan-on discount: a veto room whose fan is on and whose tick is radar-sole (`STATE_RADAR_SOLE_TICK`, gold pattern "Capability-radar-sole boolean") does not hold.
  - Mint a D0 discriminator row: "AWAY entries per verified-empty day with Jaya's fan on".

**R2v3-H3: The 60 s periodic (the guard's only discharge) is registered at the end of the same try-block as the code D3 modifies.** Bug class: suppression without a discharge (single point of failure).
- `async_track_time_interval(self._periodic_inference, 60 s)` sits at `presence.py:2926-2930`, inside one `try:` that first runs `_discover_zones`, `_discover_room_sensors`, `_discover_zone_cameras`, `_discover_room_fans` and **`_discover_guest_rooms` (`:2881`)**. The handler is `except Exception: _LOGGER.exception("Error during presence discovery (non-fatal)")`.
- A builder bug in the extended `_discover_guest_rooms` therefore silently skips periodic registration. An example is `int(merged.get(CONF_ROOM_AWAY_HOLD_MAX_H))` on a float or None from the NumberSelector, which is a realistic legal-config value.
- With no camera traffic, nothing re-runs inference in an empty house. Guard A then never releases, and the D0 "A stuck" column is the only detector, 14 days later.
- **Fix in plan:**
  - Require the new per-room parsing to run inside its own per-room try/except (the existing boot-seed already does this at `:5248-5323`), **or** move the periodic registration out of the discovery try-block.
  - Add `test_periodic_registered_when_guest_room_discovery_raises` (mutation: put the raise back in the shared block → RED).
  - Add a live check: `_periodic_inference` timestamps advance (e.g. `away_eligible_at` is re-evaluated) after boot.

**R2v3-H4: Two config paths will not behave as the plan assumes. Room-field changes need a restart, and the D5 knob reloads the CM unless it is allowlisted.** Bug class: one missed site (#53).
- (a) `_discover_guest_rooms` has exactly one caller, `async_setup` (`presence.py:2881`). Its docstring says "reads fresh from options each call", but it is called once.
  - The plan's **operator config action after deploy** (GB1 = 8, GB2 = 8, Jaya = 16) therefore does nothing until the next HA restart.
  - The per-room **kill switch** (cap → 0) is also not live, so D3's Live criterion cannot pass in the same window as the deploy.
  - "One restart" (§9) conflicts with "configure after deploy".
  - Fix: either a room-entry options listener that calls a re-discover (and cleans up its unsubscribes, `:5183-5191`), or state that the caps must be set **before** the single restart, and that the kill switch needs a restart or a CM reload.
- (b) D5 clones `FanInterferenceHoldNumber`, whose setter writes CM `entry.options`. `_async_update_listener` (`__init__.py:~8392`) **reloads the CM for any key not in `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:7480`)**. The template's key is listed there (`:7559`) and has an in-place apply (`:8263-8280`).
  - A builder who clones only `number.py` gets a full CM reload on every slider move. Memory `feedback_parent_entry_reload_watchdog_hazard` documents the event-loop stall and watchdog restart that follow.
  - Fix: D5 must list `OPTIONS_RELOAD_SUPPRESS_KEYS` plus `_NO_LIVE_ATTR_KEYS` (W is read fresh each tick, so no in-place push is needed). Add a test anchor: `test_away_camera_quiet_change_does_not_reload_cm`.

### MEDIUM

**R2v3-M1: The restart-restored `away_entries_today` will not equal the plan's own live oracle.** Bug class: day-boundary-blind; producer/consumer asymmetry.
- `house_state_log.timestamp` is **naive UTC** (`database.py:2968`, `datetime.utcnow().isoformat()`). Hydration compares it against the **local** date string (`presence.py:2582`, `dt_util.now().date().isoformat()`).
- In CDT the restored count therefore includes yesterday's AWAY rows from 19:00 to 24:00 local. The DAO docstring (`database.py:3043`) admits the approximation.
- The live increment is placed at the inference acceptance site (`~6961`, next to `_count_transition` at `:7023`). Override and boot-reconcile AWAYs go through `_dispatch_house_state_change` and land in `house_state_log`, but are not counted live.
- So the D4 Live criterion ("equals `SELECT COUNT(*) … state='away'` since local midnight") fails after any restart taken in the evening, or after any override.
- **Fix:**
  - The DAO kwarg takes a UTC instant (local midnight converted to UTC), not a date string.
  - Filter `state='away' AND (previous_state IS NULL OR previous_state <> 'away')`.
  - Either increment at `_dispatch_house_state_change` (the sole row writer) or filter the query on inference triggers. Pick one and make the oracle match.
  - Leave the existing `_transitions_today` call byte-identical (default kwarg).

**R2v3-M2: Recorder growth. Answer to open item (b): the attributes are recorded.**
- `PresenceHouseStateSensor` (`sensor.py:5557`) has no `_unrecorded_attributes` and no `_attr_should_poll = False`, so HA polls it every 30 s. Its `dwell_seconds` (`house_state.py:449`) already changes on every poll, so each poll already writes a new `state_attributes` blob (about 2,880 per day).
- The plan adds about 15 attributes to every blob, so row count stays the same but each row gets wider. `away_hold_age_s` and `last_camera_body_at` change constantly as well.
- **Fix:** put `away_hold_age_s` (derivable from `away_eligible_at`) in `_unrecorded_attributes`. Keep `last_camera_body_source`, `last_camera_body_at`, `away_hold`, `last_away_reason` recorded, because D0 needs them.
- Open item (b) is closed per code. The HA-side `recorder: exclude:` is not visible from the repo; the builder checks `configuration.yaml` on the mount.

**R2v3-M3: Under-specified `_guest_room_state` reader table.** Bug class: one missed site.
- Reality check of the plan's list: `:5189` is `.clear()`, `:5227` creates the dict, `:5305` is the boot seed, `:5367` is the listener, `:5500` is the gate, `:5677` is `_clear_guest_room_first_seen` (the guest kill switch; the plan calls it "the `presence.py:5677` loop"), and `:7653` is teardown. That list is complete (grep).
- The plan does not fix three things, so each builder will choose differently:
  1. Must the guest-detection kill switch (`_clear_guest_room_first_seen`, driven by `_guest_detection_enabled`) leave `occupied_since` alone? It must, because veto B is not a guest feature.
  2. Must transition 2 (the known resident, `:5383-5389`) leave `occupied_since` alone? D3 says yes ("still holds"), but the listener's existing branch structure invites a builder to clear both stamps.
  3. Must an attribute-only state event (on→on; `async_track_state_change_event` fires on attribute changes) not reset `occupied_since`?
- **Fix:** add a reader-by-reader disposition table to D3 (guest-only / all / veto-only), plus `test_guest_kill_switch_does_not_clear_occupied_since` and `test_attribute_only_event_keeps_occupied_since`.

**R2v3-M4: v8 card target view does not exist. Answer to open item (a).**
- The newest committed snapshot (`docs/ha-config-snapshots/lovelace_ura_v8_backup_2026_09_29.json`) has views `now, rooms, energy, people, security, climate, health, music`. There is no `presence` view.
- The `hero` template exists and takes `variables.color`, and `orange-dark` is used. In the template, `variables.color` is a static string, so "orange while held" needs a `[[[ ]]]` JS template on the variable or in the styles.
- **Fix:** name the view (PICK: `people` or `now`; do not silently add a view). Spell out the button-card JS for `label` and color. Keep the snapshot-first step as written.

**R2v3-M5: INV-B's justification fails for a veto room outside any house zone.**
- "Nobody-home and β already cannot fire, because r's occupancy makes `any_zone_occupied` true" holds only if r belongs to a zone whose roll-up reads it. A room with no zone is a legal config.
- In that case nobody-home or β fires AWAY while the veto room is occupied, and the operator's "house careful" intent leaks. INV-B as written (α only) still holds, so this is an intent gap.
- **Fix:** either add the veto conjunct to all three branches (two more lines, after the AWAY check, with R2v3-H1's fall-through semantics), or add `test_veto_room_without_zone` and document the assumption.

### LOW

- **L1:** D1 gates the stamp write on `W > 0`, and `test_no_stamp_written_when_W_zero` locks that in. Turning the knob 0 → 180 then starts from a stale B. Stamping unconditionally is still byte-identical in outputs (only RAM changes) and removes a read of W in the census handler.
- **L2:** When α is denied by the guard or veto, the plan does not say whether `_veto_path` stays `none` or becomes `active`. Setting `active` makes the sensor and the D7 episode (`presence.py:7926`) claim α fired. Specify: the denied branch leaves `_veto_path` alone and only sets `_away_hold`.
- **L3:** INV-BYTE-ID says only display values change. But nobody-home now sets `_veto_path = "nobody_home"` even with W = 0 and R = ∅, and that value is persisted in the D7 memory-episode payload (`:7926`). The set of possible values grows. Say so, and confirm there are no value consumers (grep: only `sensor.py:5661` and `presence.py:6518/7926`).
- **L4:** `_last_camera_body_ts` can be `None` in engine-level tests or before setup. D2's subtraction would raise TypeError. Specify `None` → quiet (fail-open, consistent with the boot seed).
- **L5:** `_away_hold` is reset only inside `infer()`. If `_run_inference` returns early (boot-settle deferral, `presence.py:~6951`), the sensor can show a stale `camera_recent`. Reset the mirrored value on early-return paths, or document it.

---

## 3. Falsifiable invariant (reviewer's statement) and status

> **INV-EMPTY-REACHES-AWAY:** if the house is physically empty from t0, every tracker is `not_home` or excluded, no camera body is seen after t0, and every veto room is truly unoccupied, then AWAY is accepted by t0 + W + 60 s + dwell(current state), and no non-AWAY transition is accepted between t0 and AWAY.

| Break attempt | Result |
|---|---|
| W = 0 | Holds (kill switch; byte-identical apart from L3). |
| W = 30 (below the tick) | Holds; release at the next periodic, ≤ 60 s. |
| W = 1800 | Holds as bounded; it is a departure-timing cost, not a leak. |
| Cap = 0 | Room not registered, so no hold. Holds, **but only after a restart** (H4a). |
| Veto room is also a guest room | INV-GUEST-UNCHANGED holds if the M3 table is written. α's fall-through can now reach GUEST where it used to reach AWAY. That is intended but not stated. |
| Sleep hour, last body < W before leaving | **LEAK**: SLEEP accepted, AWAY ≥ 600 s later (H1). |
| Periodic not registered | **LEAK**: no discharge (H3). |
| Phantom radar + fan in a veto room ("truly unoccupied" is violated by the sensor, not the person) | **LEAK**: up to the cap, unbounded across restarts (H2). |
| Phone forgotten in a veto room | Not new. The tracker reads `home`, so α is already ineligible today (pre-existing; `phone_left_behind` exclusion `presence.py:5677-5805` per state-of-play §3). Veto B adds nothing beyond H2. |
| `camera_input_degraded` | Holds. α is skipped; the guard applies to nobody-home and β; B ages out. |

Plan invariants: INV-A **PASS** (as specified). INV-B **PASS** (α only; see M5). INV-DISCHARGE **LEAK** (H1, H2, H3). INV-NO-BLE-HOLD **PASS** (the stamp keys on unid/face only). INV-ALREADY-AWAY **PASS**. INV-GUEST-UNCHANGED **PASS, conditional on M3**. INV-BYTE-ID **PASS with the L3 caveat**.

## 4. Must-fix before build dispatch
1. H1: guard-denied branches `return None`; veto-denied branches fall through. Restate INV-DISCHARGE with the real dwell table and add the two tests.
2. H2: decide the restart semantics of the cap and name the loop breaker for the fan and phantom loop (recheck, a radar-sole-with-fan discount, or a lower Jaya cap). Fix the false boot-seed test.
3. H3: isolate the periodic registration or the new parsing from the discovery try-block, plus a test.
4. H4: room-field changes need a restart or a re-discover hook, so reorder the config action before the restart. Add the knob key to `OPTIONS_RELOAD_SUPPRESS_KEYS` and `_NO_LIVE_ATTR_KEYS`, plus a no-reload test.
5. M1 through M5, and fold L1 through L5 into the D-sections (each is 1 to 5 lines).

**Verdict: FIX-PLAN.**
