# STEP Chatter Quarantine — Review D (Tier-3 Adversarial Completeness / Diff-Blind)

**Cycle:** STEP D1..D5 chatter-quarantine (worktree `.claude/worktrees/step-chatter` @ `07b3ad116`)
**Reviewer role:** D — falsify the load-bearing invariant across the WHOLE surface (diff + pre-existing), produce concrete legal-config reachable repros.
**Verdict:** **DO NOT SHIP.** Two HIGH leaks break invariant part 1 ("no correctly-working blind-time-gated sensor is ever quarantined"). One MEDIUM leak weakens invariant part 2 (genuine chatterer escape). One MEDIUM operator-hostility (Numbers-Get-Knobs violation). One LOW kill-switch-off release-quiet gap.

## Invariant restated (falsifiable form)

> **INV-CHATTER (as of `PLANNING_sensor_health_surfacing.md` §2 header and §D2 restated at line 512):**
> 1. No correctly-working blind-time-gated sensor is EVER quarantined by the chatter client — a healthy sensor produces zero sub-`T_floor` events by construction.
> 2. Every sustained sub-`T_floor`-burst sensor IS quarantined within one observation window.
> 3. A quarantined sensor's vote is excluded from the room-tier occupancy fusion; occupancy derived from OTHER trusted inputs is preserved unchanged.

D's job: break each. Reach = "concrete legal-config repro with device kind, provider, knob values, house state."

## Surface enumerated (diff-blind sweep)

Chatter-adjacent surface I re-walked independently of the plan's list:
- `custom_components/universal_room_automation/domain_coordinators/chatter_detector.py` (new) — 477 LOC.
- `.../sensor_exclusion.py` (new) — 176 LOC.
- `coordinator.py` (touched): `__init__` construction (`_exclusion_set`, `_chatter_detector` at L576/L584), `_update_signal_subscriptions` listener rebuild (L1462), tick-site (L2555..L2886), enable gate `_chatter_quarantine_enabled` (L2150), fusion sites (motion / mmwave / occupancy at L2891..L2942).
- `sensor.py` L1835..L1898 — `_chattering_entities` diagnostic surface (D5).
- `__init__.py` L4817 — `async_teardown` wire.
- `const.py` L3798..L3901 — `CHATTER_*` knobs.
- Pre-existing exclusion consumers repo-wide (`_dutycycle_excluded_now`, `_stuck_excluded_fired`, `_stuck_sensor_kinds`, `_p22_stuck_sensor_set`, `stuck_sensors` local alias). All confirmed diagnostic-only outside the fusion sites; fusion authority is the shared `SensorExclusionSet.is_excluded()`.
- Zone/House/Substrate tier: confirmed by grep — no `_exclusion_set` / `_chattering_entities` reader outside room-tier. INV-CHATTER-4 scope holds.
- `sensor_capability.py` — searched for a `t_floor` / `blind_time` field: **NONE.**

---

## D-HIGH-1 — Healthy mmWave falsely quarantined; the planned rung-2 T_floor override is NOT IMPLEMENTED

**Invariant part broken:** #1 (healthy sensor never quarantined).

**Mechanism.** `chatter_detector._t_floor_for()` (chatter_detector.py:101) returns ONLY family defaults from `CHATTER_T_FLOOR_DEFAULTS`. There is no consultation of `sensor_capability` for a per-entity override. `_resolve_provider()` calls `get_capability(...)` but ONLY reads `provider` / `provider_tag` — never a blind-time / T_floor field. Grep of `sensor_capability.py` confirms the schema carries no `t_floor` / `blind_time` field at all.

The plan (`PLANNING_sensor_health_surfacing.md` L434-438, `const.py` docstring L3823-3828) explicitly promises:

> "Ladder: family default → per-entity `sensor_capability` override → learned p1-p5 ONLY from a KNOWN-HEALTHY DIFFERENT reference unit."
> "Per-entity `T_floor` override — via existing `sensor_capability` schema — Rung 2."

Neither the rung-2 override nor the rung-3 learned-reference ladder is wired. The family default is the ONLY source, and it is `mmwave = 1.5 s`.

**Concrete legal-config reachable repro.** Aqara FP1 (or LD2410-based ESPHome mmWave, or Everything Presence Lite) tagged `provider = mmwave`, wired under `CONF_MMWAVE_SENSORS`, kind = `mmwave`. Aqara FP1 default reporting cadence during target motion is 1 s (documented on the device); ESPHome LD2410 default is 0.5-1 s. A person moving continuously for 10 min in the bedroom drives `on → off → on` transitions at ~1 s intervals. Dedup guard (`prev_state_val == state_val: return`, L366) does NOT fire because the sensor genuinely oscillates. Each `on → off → on` produces two sub-1.5 s intervals. Twenty such intervals inside a 10-min window = K=20 reached. The healthy FP1 is **flagged chatter, promoted into `SensorExclusionSet` as `("chatter", <fp1>)`, and vetoed from the room's presence leg** for ≥ 15 min (`CHATTER_RELEASE_QUIET_S = 900 s`). Bedroom presence collapses to whichever PIR/BLE remains — for a Zone 1-style master-bedroom-at-night, this recreates the "away while occupied" class (memo `zone_away_when_occupied_home_night_gap`) via a new mechanism.

**Why the invariant declaration is falsified.** The plan's own §4-D2 line 284-288 says "learning must be from a DIFFERENT reference unit"; the intent is that a healthy fast-mmWave has a `T_floor` below its true blind time and by construction cannot generate sub-`T_floor` events. That construction is untrue in code: `T_floor = family default = 1.5 s`, which is HIGHER than the device's real 1 s cadence, so a healthy sensor DOES cross the impossibility line.

**Fix shape (advisory, not a spec).** Either (a) implement the promised per-entity `sensor_capability.t_floor` override + resolve it in `_t_floor_for(entity_id=…)`, or (b) raise the mmwave default to ≥ 3.0 s and re-probe D0 whether any real chatterer sits above 3 s (probe already indicates ratgdo storms at ~1 s → still above 3 s? verify). Option (a) is the plan; option (b) is a stop-gap.

---

## D-HIGH-2 — Boot-transient sub-floor events poison `_sub_floor_events`; first post-boot edge instant-flags

**Invariant part broken:** #1 (healthy sensor never quarantined) — the boot-settle guard has a load-bearing bug.

**Mechanism.** In `chatter_detector._on_edge` (chatter_detector.py:338-420), the boot-settle gate at line 400-401 (`if not boot_settled: return`) is placed AFTER the sub-floor event append at line 392-398. So during `!boot_settled`, the sensor's sub-floor events ARE inserted into the `_sub_floor_events[eid]` deque; only the score-check (line 404-407) is skipped. The deque is trimmed only by wall-clock cutoff (`sf[0] < now - 600 s`). Consequently, sub-floor events that occurred during the boot-settle window (typically 60-180 s, sourced from presence coordinator's `_boot_settle_done`) remain valid in `sf` for up to `CHATTER_OBSERVATION_WINDOW_S = 600 s` after the event.

When boot-settle releases, the very NEXT sub-floor edge computes `len(sf) >= K = 20` against a deque already primed with 20+ boot-window entries → **instant chatter promotion of a healthy sensor**.

The code comment at L370-371 ("Boot-settle gate: sample edges but do NOT score them until boot settle has released (prevents restart-flurry false-fires)") describes the intent; the implementation retains the sample IN the scoring deque, defeating the intent.

**Concrete legal-config reachable repro.** HA restart at 7 pm; user is exercising in the bedroom during the restart. Aqara FP1 (or any mmWave / fast PIR) genuinely fires `on/off/on` at ~1 s cadence for the first 60-90 s of boot-settle (person is moving in front of the sensor). Say 25 sub-1.5 s events accumulate in `_sub_floor_events[<fp1>]`. Boot-settle releases (presence coordinator flips `_boot_settle_done = True`). The user takes another step; the FP1 fires another `on/off/on`; `_on_edge` computes `len(sf) = 26 ≥ 20`; **the FP1 is quarantined ~5-10 s after boot-settle release, even though nothing physically changed at the sensor**.

This is worse than D-HIGH-1 because it is timing-only (not device-specific) and happens on **every restart** where any tracked room has active motion during boot-settle. Restarts are routine (every deploy, every HAOS update). This is a Cycle-A-class transient false-fire that the plan's guard was specifically designed to prevent — but the guard is in the wrong place.

**Fix shape (advisory).** Either (a) put the boot-settle return BEFORE the sub-floor append + `_edge_windows` append (do nothing at all during boot-settle beyond stamp `_last_edge_ts`/`_last_edge_state` if release-quiet needs it), or (b) at boot-settle release, clear `_edge_windows`, `_sub_floor_events`, and `_last_edge_ts` for all entities to start scoring from a fresh slate. Option (a) is minimal.

---

## D-MED-1 — Genuine chatterer escapes on default Z2M / numeric entity_ids (invariant #2)

**Invariant part broken:** #2 (every sustained sub-`T_floor` burst is quarantined).

**Mechanism.** `_classify` (chatter_detector.py:135-166) requires a positive `(kind, provider)` allowlist match to score. Providers come from either the URA capability layer (`get_capability(...).provider`) or the entity_id substring fallback (`_PROVIDER_SUBSTRINGS`). When the capability layer returns None (device not yet capability-tagged) AND the entity_id contains none of `ratgdov`, `ratgdo`, `garage_door`, `mmwave`, `presence`, `_pir`, `zigbee`, `_motion` — the classifier returns `(False, None)` and the sensor is never listened-for.

**Concrete legal-config reachable repro.** A Zigbee2MQTT-added PIR whose "friendly name" was never customised typically ships as `binary_sensor.0x00158d0001abcdef_occupancy` (or `binary_sensor.aqara_motion_sensor_p1_87ab_occupancy`). Both fall into `CONF_OCCUPANCY_SENSORS` → kind = `occupancy`. Neither entity_id matches any `_PROVIDER_SUBSTRINGS` entry (no `mmwave`/`_pir`/`_motion`/`zigbee_pir` substring in the raw MAC-style id — `zigbee` DOES appear via the substring `zigbee` if present, but many Z2M ids omit the vendor). If the URA capability layer has not been populated for this entity, `provider = None`. Classifier returns `(False, None)`; the sensor is silently EXCLUDED from the chatter listener. A genuine chattering PIR of this shape is therefore never quarantined, in direct contradiction of invariant #2.

Severity MEDIUM (not HIGH) because the user's actual fleet appears well-labelled and capability-tagged; but the invariant is stated in absolute terms ("every sustained ... IS quarantined"), and this class of miss is trivially reachable by adding an off-the-shelf Z2M sensor without a friendly-name customisation.

**Fix shape (advisory).** Either extend the fallback substrings to include `_occupancy` (safest, since `CHATTER_PROVENANCE_DENYLIST` already keeps camera aggregates out via the family regex, and `_occupancy` under kind=`occupancy` maps sanely to `pir`/`mmwave`) — or LOG once per unlabeled candidate at `INFO` so operators see silent-DENY misses.

---

## D-MED-2 — Numbers-Get-Knobs violation on the load-bearing tuning surface

**Invariant part broken:** none directly, but it precludes rung-3 backout when D-HIGH-1 / D-HIGH-2 fire in the wild.

`CHATTER_T_FLOOR_DEFAULTS`, `CHATTER_BURST_K`, `CHATTER_OBSERVATION_WINDOW_S`, `CHATTER_RELEASE_QUIET_S` are all `Final` module consts. `_chatter_quarantine_enabled()` has a rung-2 enable toggle (good), but the actual detection thresholds are only editable by a reviewed code change. Combined with `DEFAULT_CHATTER_QUARANTINE_ENABLED = True` (deploys ENABLED), this means: if D-HIGH-1 fires false on the FP1 fleet in production, the ONLY operator response is the enable toggle (fully OFF) — there is no way to raise mmWave T_floor from 1.5 → 3.0 s without redeploying. The plan itself (L438) put the per-entity override at rung-2; the family default arguably deserves rung-2 too when the healthy population is bimodal across device families.

**Recommendation.** Either (a) implement the promised rung-2 per-entity override in `sensor_capability` (also fixes D-HIGH-1), or (b) expose the four consts as rung-2 config keys with the current values as defaults.

---

## D-LOW-1 — Kill-switch-OFF path skips `check_release`; sticky `_chattering` on re-enable

**Invariant part broken:** none (invariant is preserved), but a re-enable transient can cause a one-tick stale mass-promote before the release-quiet check runs.

**Mechanism.** `coordinator.py` tick-site L2802-2885: when `_chatter_quarantine_enabled()` returns False, only the else-branch (L2874-2880) runs, which mirrors `chattering_entities()` into `_chattering_entities` for the diagnostic surface but does NOT call `check_release`. The detector's `_chattering` set accumulates any sensors that were flagged before the kill-switch flipped OFF (or during a period when both rungs are True but a middle tick returned False due to option-flow race). On re-enable, the else-branch stops running; the enabled branch (L2803-2873) calls `check_release` first, which correctly releases any quiet entities.

Real-world reach is low — kill-switch toggles are rare — but the invariant "the promise INV-CHATTER-4 holds byte-identical when disabled" is technically true (no promotion / no NM), so this is diagnostic-only sluggishness, not a fusion leak. Kept LOW.

---

## Enumerated non-leaks (checked and dismissed)

- **INV-CHATTER-3 (occupancy from OTHER trusted inputs preserved).** Fusion sites at coordinator.py L2891-2942 loop `motion_sensors` / `mmwave_sensors` / `occupancy_sensors` and skip only the excluded entity; other tier-1 sensors continue to vote. A room whose ONLY sensor is quarantined vacates — that IS the correct behaviour (broken hardware, no signal). Confirmed no cascade into zone/house that force-vacates additional rooms.
- **`stuck_sensors` local alias contamination.** Chatter adds to the local `stuck_sensors` alias (L2836) but that alias's only downstream reads are diagnostic (`_stuck_sensor_kinds` labelling). The authoritative gate for fusion is `_exclusion_set.is_excluded()`, which correctly reflects chatter promotions. Safe.
- **D2-raise codepath / Reading A byte-identity.** On D2 detector raise, the STEP D1 tick-site does NOT re-populate the exclusion set for the D1 client (L2787-2796 comment). Chatter runs INDEPENDENTLY at L2802+ and still promotes on that tick. Chatter's own fail-safe wraps the entire block in try/except at L2881-2885. Byte-identity for empty-clients (STEP-EXCLUDE-2) holds because `reset_tick()` clears at L2560 and every writer must re-add. Confirmed.
- **Zone/house/substrate leak of quarantine.** Grep confirmed `_exclusion_set` and `_chattering_entities` are read only by room-tier coordinator + the D5 diagnostic sensor. INV-CHATTER-4 (no zone/house propagation) holds — a quarantined sensor still contributes its raw state to the substrate/zone-any layer; that is the DESIGNED scope-limit and matches the plan.
- **Teardown / Bug Class #38.** `_chatter_unsub` is stored on the instance, released by `_drain_listener` on rebuild AND by `async_teardown` (called from `__init__.py` L4817). Idempotent. Register-rebuild each `async_register_listeners` call refreshes `_entity_to_meta` from scratch. Confirmed no leaked callback across reload.
- **Restart persistence.** Detector state is RAM-only by design — matches the plan's "restart → chatter re-detected from live edges" semantics. Not a leak.
- **Combinatorial: `T_floor = 0` per-family kill switch.** `_t_floor_for` returns 0.0 for unmapped kinds/providers; `async_register_listeners` at L275-278 continues past T_floor=0 (does not register that entity), and `_on_edge` at L353-354 short-circuits. Semantics is correctly "OFF", not "always chatter". ✓
- **Combinatorial: K extremes.** K = `CHATTER_BURST_K = 20`. `K = 10**9` would make `len(sf) >= K` unreachable — documented as kill switch in the plan. `K = 0` would flag on the first sub-floor event; not currently reachable via any operator surface (const only). Non-issue given D-MED-2 posture.
- **State-change dedup vs oscillation.** L365-367 drops same-value repeats. An `on → on` fast repeat CANNOT drive scoring — good. But this doesn't defend against genuine `on → off → on` oscillation, which is exactly what D-HIGH-1 exploits (healthy fast mmWave DOES oscillate).

---

## Verdict + gates

**DO NOT SHIP** until D-HIGH-1 and D-HIGH-2 are fixed. Recommended sequence:

1. Move the boot-settle guard to BEFORE the deque appends (D-HIGH-2). Or clear all per-entity deques at boot-settle release. Add a test that:
   - primes `_sub_floor_events[e]` with 25 events during `!boot_settled`
   - flips boot_settled
   - fires one more sub-`T_floor` edge
   - asserts the sensor is NOT in `chattering_entities()`.
2. Wire per-entity `T_floor` override into `sensor_capability` and consult it from `_t_floor_for(entity_id, kind, provider)` (D-HIGH-1). Add a test with a `capability.t_floor = 0.5` override, drive 25 sub-1.5-s edges through the entity, assert NOT chattering.
3. Ship D-MED-1 fix (add `_occupancy` substring OR INFO-log silent-DENY misses) inside the same fix-up round to close invariant #2.
4. Ship D-MED-2 rung-2 exposure OR leave as follow-up with an operator-visible note (kill-switch alone gives a big-hammer backout, which is acceptable if operator is briefed).
5. After fix-up, re-run D's completeness enumeration (a fix can reveal an N+1th site) and re-verify both HIGH sites with mutation-anchored tests (Tier-3 §C requirement).

Invariant statement restated for the record: **no correctly-working blind-time-gated sensor is EVER quarantined; every sustained sub-`T_floor`-burst sensor IS; a quarantined vote is excluded from room-tier fusion, other trusted inputs preserved.** Parts 1 and 2 are currently falsified as shown; part 3 holds.
