# Plan review: PLANNING_presence_gps_assistive.md (b53bee6ff), card PERSON-BLE-WINS-OVER-STALE-GPS-1

Tier-2 adversarial plan review, 2026-10-24. Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all 730 lines) and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No §10 ledger claim is re-asserted here.

**Verdict: FIX-REQUIRED.** The core idea is right and narrow: one predicate at the two `_ps_state == "home"` arms, reusing the S3 arm, `away_ble_silent_only`, 0.82 and the kill-switch base class. Two premises are wrong, though. The first is how a dead BLE fleet and a fresh boot look to the predicate (F1, F3). The second is that the change reaches every trust consumer of "is this person home" (F2).

## What holds (verified)
- Sites: the only `person.state == home` force sites in person_coordinator are `person_coordinator.py:734` and `:832`, plus the matrix fallback `:435`, which they overwrite. The plan's §7 is complete for this file.
- The S3 arm side effects (`:776-792`, `:861-873`) match the plan's description.
- `_ble_fleet_live` (`:297-341`) proves liveness only through some person's `last_bermuda_update` from the previous tick. It returns False on empty data, so it is False for the last person out. The plan is right on that point.
- `_read_source_inventory` ignores `bluetooth_le` (`:287-289`), so the new tracker helper does not duplicate an existing reader.
- `get_person_location` exists at `person_coordinator.py:1471`. It is relevant to F2.
- Knob: rung 3, reuses `_PresenceKillSwitchBase`, OFF = today's behaviour. Acceptable.
- INV-1 and INV-3 are falsifiable as written. INV-2 is not true as written (F4).

## Findings

### F1 HIGH: a dead BLE fleet reads `not_home`, not `unavailable`, so the predicate fires for every app user at once
Evidence (source, not docs):
- `private_ble_device/device_tracker.py`: `state = STATE_HOME if self._last_info else STATE_NOT_HOME`. When advertisements stop, `_async_track_unavailable` sets `_last_info = None`. The entity has no `available` override (`private_ble_device/entity.py`). So when proxies go offline or the adapter wedges, the tracker reads **`not_home` and stays available**.
- Bermuda `device_tracker.py:84-91` + `bermuda_device.py:692-700`: `zone = STATE_HOME` only if `last_seen` is within `CONF_DEVTRACK_TIMEOUT`, else `STATE_NOT_HOME`. The entity is a `CoordinatorEntity` (`entity.py:29`), so it goes unavailable only when the Bermuda coordinator update itself fails, not when the scanners go deaf.

So plan §4 ("A dead BLE fleet shows as trackers `unavailable`/`unknown` (→ no change, INV-2)") holds only for an integration crash. For the common failure (proxies down, adapter wedged, Wi-Fi event) every resident's trackers read `not_home`.

**Repro:** all ESPHome proxies drop at 20:00, house HOME_EVENING, everyone home, cameras see nobody interior for a moment. After Bermuda's devtrack timeout, Jaya and Ziri go away (they already do today). Under the plan, Oji and Ezinne (GPS `home`) also go away. `all_tracked_persons_away = True`, census BLE list is empty, so path α (or nobody-home if no zone holds) fires **AWAY with four people home**. Today GPS `home` is the only thing that stops this. The plan removes that guard and offers nothing in its place.

"Kids already go away today" does not make this acceptable. Today the app users' GPS keeps the house out of AWAY. After the change nobody does.

**Plan change (narrowest, reuse first):** add a fourth conjunct, `ble_fleet_healthy_now`. It must not depend on the departing person, and it must not depend only on other residents, or it fails for the last person out. Candidates, in preference order:
1. **Bermuda Active Proxy Count** (`BermudaActiveProxyCount`, unique_id `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT`, `bermuda/sensor.py:519-540`, value `coordinator.count_active_scanners()`). Resolve it by registry unique_id, never by entity_id suffix. Require > 0 (or ≥ a floor). No URA code reads it today (grep `active_proxy|proxy_count`: 0 hits), so this is a NEW read of an existing HA entity. Before relying on it, a **D0b probe is required**: show from the recorder that the count actually drops during past proxy outages. `count_active_scanners` semantics are unverified here.
2. As a disjunct, any tracked person's `bluetooth_le` tracker reading `home` (fresh `last_updated`), or `_ble_fleet_live(now)`. Both prove the fleet can hear phones. Neither helps the last person out, which is why (1) is needed.
3. If (1) fails D0b, fall back to "fleet healthy = some person BLE-visible within N min". Accept that the last person out stays GPS-held (today's behaviour) and state that as a named residual.

Add a test: all trackers `not_home`, proxy count 0 → `home` (byte-identical to develop). Add a mutation drill that drops the health conjunct and turns that test RED.

### F2 HIGH: many trust consumers read HA `person.<x>.state` directly and bypass the gate; the consumer map is wrong about one of them
Plan §6 lists `aggregation.py:4494, 4634` ("zone persons_home reliable signal → fewer false vetoes"). That is false: both read the raw HA person state (`aggregation.py:4455-4463`, `:4589-4596`, strict `state.state == "home"`), so the plan does not change them. A frozen GPS keeps leaking through every raw reader. Classification (verified by reading each site):

| Site | Reads | Trust or display | Frozen-GPS "home" leaks after the plan? |
|---|---|---|---|
| `aggregation.py:4455-4463` → `ReliableSignal("zone_persons_home")` `:4494` | raw person.state | **trust** (zone veto, consumed `presence.py:2121/2133`) | **Yes, daytime.** The house zone stays "person home" for an away person. |
| `aggregation.py:4589-4596` → `:4634` | raw | **trust** (same) | **Yes** |
| `hvac_zones.py:2655-2675` (D7 / row-1 fail-open preserve) | raw | **trust** (HVAC preset preserve when fused signal unestablished or degraded) | **Yes.** The zone keeps conditioning. |
| `hvac.py:3401-3410` night-trust preset hold | raw | trust, FAN_TRUST_STATES only and only if `not _zone_conditioning_retreat_ok` | Narrow (the measured frozen segments are all daytime), but reachable |
| `hvac_fans.py:1525-1535` night vacancy hold | raw | trust, night only | Narrow, same reason |
| `hvac.py:3978-3986` `main_row_home_persons` | raw | purpose not verified (feeds an `async_create_task`; looks diagnostic) | Builder must classify it |
| `camera_census.py:5884-5895` stale-face latch guard (`face_recognized_count`) | raw `== "not_home"` | **trust** (path α requires face 0) | **Yes.** A face seen at egress is not dropped while person.state = home, so α stays blocked up to `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (1800 s). |
| `camera_census.py:4193-4199` `is_face_leg_person_vetoed`; `transit_validator.py:1837-1847` egress veto | raw `not_home` | trust (identity) | Yes (no veto). Minor. |
| `camera_census.py:4391-4445` BLE transition legs; `security.py:2024-2030`; `presence.py:5124/5143`, `:8734` geofence | edges on raw state | trust (edge-triggered) | No false edge is produced. A frozen state emits no edges, so leaving these alone is defensible. |
| `camera_census.py:5686-5694`, `:5726-5733` | tracker inventory / router guests | structural | No |

**Plan change:** add a §6b with this table and a disposition per trust row. The narrowest consistent option is one shared helper on PersonCoordinator, built on the existing `get_person_location` (`person_coordinator.py:1471`). Call it `is_person_home(person_entity_id)`. It normalises entity_id → name using the existing pattern (`__init__.py:3065-3067`) and returns True iff the URA location is not in {away, unknown, ""}. It falls back to raw `person.state == "home"` when person_coordinator or the person is absent, which keeps Wigton and no-coordinator byte-identical. Adopt it at the aggregation ×2, hvac_zones and face-latch rows. Either adopt it at the two night holds or justify leaving them with the measured "0 overnight frozen segments" (§5). Then the non-goal "No HVAC, census, or camera code changes" must be rewritten to match. The alternative is to keep the non-goals, state each leak by name as accepted, and drop the plan's §6 claim about aggregation. Either way, the plan cannot claim HVAC is touched "only via house state".

### F3 HIGH: the `restored` exclusion is not a boot guard
Neither BLE tracker is a RestoreEntity:
- private_ble starts with `_last_info = None` → `not_home` (`entity.py` `__init__`), unless `async_last_service_info` has a cached advert.
- Bermuda starts with `zone = STATE_NOT_HOME` (`bermuda_device.py:119`).

Neither ever carries `restored: true`, so the plan's guard ("The `restored` exclusion covers the boot window") does nothing. After a restart, person_coordinator's `self.data` is empty, so there is no STALE hold and present residents go straight to the person-state branch. A present app user whose BLE trackers have not yet re-advertised (`not_home`) and whose person.state is GPS `home` would be stamped away on the boot tick.

Recorder probe at the 8 most recent restarts (scratchpad `pr_boot.py`): present trackers' first `home` rows land at +0 to +280 s (private_ble +42/+53/+154/+253/+280 s). No `not_home` row was recorded in between, so the boot value is not proven either way: the recorder skips writes that repeat the pre-restart value. The source says the initial state is `not_home`, so the window is real until disproven.

**Plan change:** gate the predicate on a boot latch, using the A-M1 semantics `_ble_fleet_live` already uses. Do not fire until the fleet has been proven live this session: the F1 health conjunct is True, or some `bluetooth_le` tracker has written `home` since start, or `_ble_fleet_live` has returned True once. Add an acceptance test for the boot tick (empty `self.data`, trackers `not_home`, GPS home → `home`) and a mutation drill. Delete the `restored` rationale, or keep the check only as harmless belt-and-braces and say so.

### F4 MEDIUM: INV-2 is false as worded
"If any BLE tracker is unavailable … byte-identical" is true, but the invariant's protective claim (a dead fleet → no change) is false (F1). Restate it so it carries the health and boot conjuncts: "under no fleet-health evidence, or before the boot latch, behaviour is byte-identical to develop". INV-2 is then falsifiable by the F1 and F3 repros.

### F5 MEDIUM: the live acceptance criterion does not discriminate
"House AWAY within ~10 min if last out" can fail for a reason the plan does not model: the F2 face latch can hold α for up to 30 min after a garage face. Either fix the face-latch row (F2) or extend the criterion: Oji's `location` must read Away within ~10 min (the discriminating observation), and the house AWAY may lag by up to the face window. Also add a D0 re-run criterion for false aways: overnight episodes where an app user's URA location reads `away` while their own BLE tracker is `home` within ±3 min must be 0.

### F6 LOW: §4 "Timing" omits the Bermuda devtrack timeout
How quickly BLE reads `not_home` depends on Bermuda `CONF_DEVTRACK_TIMEOUT` and on the bluetooth unavailable timeout for private_ble. Read the live values (config-first) and cite them instead of "a few minutes".

### F7 LOW: §1.1 says no BLE device_tracker reader exists in URA
That is true for person_coordinator, but `camera_census.py:4250-4270` already iterates `device_trackers` and counts BLE per slug (`slug_ble_count`). Check whether its classifier (source_type test) can be reused as the tracker filter, or cite it and record why not.

## Must-fix before build
F1 (fleet-health conjunct + D0b probe), F2 (raw-reader table + disposition + corrected non-goals), F3 (boot latch replaces `restored`), F4 (INV-2 rewording). F5–F7 are in-plan edits.

## Bug classes
F1 and F3: observation of a degraded upstream treated as evidence (the dead-fleet backstop class `_ble_fleet_live` exists for). F2: #53 computed-but-not-consumed (the gate is not consumed by the raw-state readers). F4: unfalsifiable/false invariant.

---

## Re-review rev 2 (3311ad713), 2026-10-24

**Verdict: FIX-REQUIRED (minor).** These are three plan-text edits. No new design and no further plan review are needed; once the orchestrator confirms the edits, the plan is READY. F1–F7 are addressed, and the change is still narrow: one gate at two sites, one listener, and seven one-line read swaps that keep their comparison strings.

### F1–F7 verification
- **F1 fleet guard: fixed.** `count_active_scanners(max_age=10)` is confirmed at `bermuda/coordinator.py:574-581`. The registry lookup by unique_id follows the resolve-via-registry rule. "Missing sensor → rule off" is specified (§4.2) and tested (`test_proxy_entity_missing_rule_off`). The floor of 30 is grounded in D0b (p1 44). The published state goes through `BermudaGlobalEntity._cached_ratelimit` (`bermuda/entity.py:204-215`, interval 60 s at `:193`), so a drop shows up as an HA state up to ~60 s late, not 10 s. That is still inside the 300 s tracker timeout. **§5.3's "within 10 s" should read "within ~60 s".** (LOW, text only.)
- **F2 raw readers: fixed.** The seven ADOPT sites match my table. `hvac.py:3978-3986` is now classified as display. Leaving the two identity vetoes and the edge readers raw is justified. See R2-3 for one inconsistency.
- **F3 boot latch: fixed.** The `restored` clause is gone. `_fleet_healthy_since = None` at process start plus `BLE_LEADS_ARM_S = 1200` covers both boot and recovery. The 1200 s is grounded in the measured +16.8 min re-acquire. Its discharge is specified.
- **F4 INV-2: fixed.** It is falsifiable and now includes the fleet, boot and unsampled-dip repros.
- **F5 live criteria: fixed.** The person-location discriminator, the 30 min house bound and the false-away overnight re-run are all present.
- **F6 timing: fixed.** It cites live `devtracker_nothome_timeout = 300` and the habluetooth 900 s fallback. The live HA version is still unchecked; the plan says so.
- **F7: not addressed.** `camera_census.py:4250-4270` already filters `device_trackers` per slug and counts the BLE ones. The plan neither reuses that filter nor says why not. **LOW: one sentence.**

### New findings in rev 2

**R2-1 MEDIUM: the "entry-reset at the top" of `_gps_home_overruled` exposes an empty set mid-tick.**
`_async_update_data` (`person_coordinator.py:453`) awaits inside the per-person loop: `:465` `_build_scanner_room_map`, `:521` `_find_bermuda_area_sensor`, `:531` `_calculate_confidence`. If the set is cleared at the top and refilled person by person, then any §6b reader that runs during those awaits sees the set empty. That covers aggregation zone vetoes, HVAC and the face latch. During that window, an overruled person reads raw `home` again, and the outcome flickers on every tick.
**Plan change:** build a local `overruled: set[str]` during the tick and assign `self._gps_home_overruled = overruled` once, after the person loop and before return. This is the "capture, thread the local, assign once" pattern. Add the test `test_overruled_set_not_visible_partial_mid_tick`: stub an await to yield, read `effective_person_state` from another task, and expect the previous tick's set. (The current set vs previous-tick `self.data` mismatch is fine: on the first overrule tick, `get_person_location` still says home → raw. That is conservative and one tick late.)

**R2-2 MEDIUM: there is no teardown hook for the listener.**
PersonCoordinator has no listener, `async_shutdown` or unsub infrastructure today (grep of `person_coordinator.py` for `async_track|_unsub|async_shutdown`: 0 hits). Unload only does `hass.data[DOMAIN].pop("person_coordinator", None)` (`__init__.py:5680`). So "unsubscribed on unload" names a mechanism that does not exist. A builder may register the listener and leak it on every reload (untracked-listener class).
Also, §4.2 re-resolves the entity "on a miss" at tick time. If Bermuda loads after URA, the listener is never registered, and the dip protection silently degrades to tick sampling.
**Plan change:** register the listener at the first successful resolution, whether that happens at setup or on a later tick, and do it once. Store the unsub. Release it with `entry.async_on_unload(...)` at the coordinator's creation site, or with an `async_shutdown` override called before the `:5680` pop. Extend `test_listener_unsubscribed_on_unload` to cover the case where the entity resolves late.

**R2-3 LOW: the face-latch ADOPT contradicts the identity-veto LEAVE.**
The plan leaves `camera_census.py:4193` / `transit_validator.py:1837` raw because the overrule outlasts the person's return until BLE re-acquires them, so a door face would be vetoed. The same timing applies to the ADOPTed face-latch guard at `camera_census.py:5884-5895`: a face recognised at the door while the person is still overruled is dropped from `face_recognized_count`. The effect is benign: it delays nothing that BLE re-acquisition does not already gate, and arrival is driven by other signals. But the plan should say so in §6b rather than give opposite rulings on the same timing argument.

### Regression checks (no finding)
- `effective_person_state` for a missing, LOST or unknown person: `get_person_location` is not `"away"`, so it returns raw → byte-identical. With no coordinator, it returns raw. Name mapping `person.{k.lower().replace(' ', '_')}` matches the existing construction at `person_coordinator.py:479`.
- If the Bermuda coordinator stalls with its entities still available, the count freezes at its last value, but the Bermuda trackers freeze too and do not flip to `not_home`. The rule needs both integrations, so it cannot fire. No leak.
- Rung 1 for `BLE_LEADS_MIN_ACTIVE_PROXIES` / `BLE_LEADS_ARM_S` (review-only safety bounds) is correct, and the kill switch stays on D2.

### Must-fix before build
R2-1 (local set, assign once), R2-2 (listener registration-at-resolution + an unload hook that actually exists). R2-3, F7 and the 60 s text fix are one-line edits.
