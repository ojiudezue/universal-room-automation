# PLANNING — Presence: GPS assistive, BLE leads (card PERSON-BLE-WINS-OVER-STALE-GPS-1)

**Status:** Rev 3 (re-review ef276f8d5 items R2-1, R2-2, F7, LOW and wording folded in; no further review round), plus operator answers 2026-10-24: arm window re-derived to 360 s, WiFi row 4 dropped, pre-arrival on dropout accepted, Ziri's away is correct. Rev 2 applied plan-review fixes F1-F7
(`docs/reviews/code-review/plan_review_presence_gps_assistive.md`, d46e28f7a). Awaiting re-review. No code written.
**Card:** `PERSON-BLE-WINS-OVER-STALE-GPS-1` (`docs/planning/kanban.data.yaml:32943`).
**Read first (done, completely):** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`
(all 730 lines, §0-§11 + addendum + gold patterns) and `docs/architecture/SENSOR_FLEET_CLASSES.md`.
Sensor-fleet classes are not touched by this cycle. HVAC is touched at four raw `person.state` reads
(§6b) through one shared helper; no HVAC logic changes.

**Operator intent (verbatim, 2026-10-24):** "We have to demote gps in code. And make it assistive vs
at same level as ble. But we could make it so a toggle makes it more important for ble sparse and more
app use." / "The house works well on ble. Only Ezinne even has the app. The kids don't. For now gps is
assistive not probative." / "I don't have to care about Bluetooth being missed while at home. Or prove
I do." / "Leave ha alone." / Users may turn location off or deny iOS permission, so missing GPS must
never block away. Addendum: "Make sure you understand ble prior art... For key subsystems I expect
very narrow changes unless justified. Don't act like this is green field."

### Rev 2 change log (plan review d46e28f7a)
| Finding | Fix in this revision |
|---|---|
| F1 HIGH dead fleet reads `not_home` | D0b probe run (§5.3). New fleet-health conjunct on Bermuda's Active Proxy Count, resolved by registry unique_id (§4.2). Missing sensor → rule off. |
| F2 HIGH raw `person.state` trust readers bypass the gate | New §6b table. One shared helper `effective_person_state()` on PersonCoordinator, adopted at 7 sites. Edge-triggered and identity readers left alone, with reasons. §6 and §9 corrected. |
| F3 HIGH `restored` is no boot guard | `restored` clause dropped. A boot latch arms the rule only after the fleet has been healthy for `BLE_LEADS_ARM_S` this session (§4.3). |
| F4 MED INV-2 false | INV-2 rewritten with the fleet-health and boot conditions (§3). |
| F5 MED live check doesn't discriminate | The live check now keys on Oji's location, with the house-AWAY lag bounded. Added an overnight false-away re-run criterion (D1 Live). |
| F6 LOW timeouts | Live values read and cited (§4.4). |
| F7 LOW census tracker walk | Reviewed; not reused, with reason (§1.1). |
| Operator answers (2026-10-24) | Q2: row 4 dropped, so the gate requires WiFi MISSING/unavailable. Q3: dropout-triggered pre-arrival accepted. Q4: Ziri is at college, so his away is accurate; no card. Restarts: "react quickly for the main case… safe for edge cases" → `BLE_LEADS_ARM_S` re-derived from the fastest-recovering tracker = **360 s** (§4.3, §5.4). Main-case latency stated from measurement (§4.4). |
| Rev 3 (ef276f8d5) | R2-1 overruled set built in a local and assigned once (§4.1). R2-2 listener registered on first resolve, including a late Bermuda load, and released via `entry.async_on_unload` plus teardown (§4.2). F7 sentence (§1.1). LOW note on the face-latch timing (§6b). Proxy sensor publishes up to ~60 s late (§4.2, §5.3). |

---

## 1. Institutional context verified

### 1.1 Prior-art scan (code + plans + memory), REUSE-or-BUILD per piece

| Piece | Verdict | Existing symbol |
|---|---|---|
| Tracking statuses ACTIVE / STALE / LOST | **REUSED, no new status** | `TRACKING_STATUS_*` (const), stamped in `person_coordinator.py:573, 667, 767, 780` |
| Away stamp for "BLE says gone" | **REUSED** `tracking_reason="away_ble_silent_only"` (row 14) | `person_coordinator.py:426-429`; vocab `const.py` `TRACKING_REASON_VALUES` (~:197-215) |
| Away confidence | **REUSED** `BLE_SILENT_ONLY_AWAY_CONFIDENCE = 0.82` | `const.py:243` |
| S3 away side effects (`_person_lost_since`, `_lost_away_since`, `_person_was_away`) | **REUSED** verbatim | `person_coordinator.py:776-792` and `:861-873` |
| Per-tick GPS/WiFi/BLE axis read | **REUSED, unchanged** | `_read_source_inventory` `person_coordinator.py:209-295` (ignores `bluetooth_le` by design, :287-289) |
| Fleet liveness gate | **REUSED, unchanged, not used as the guard** | `_ble_fleet_live` `:297-341`. It proves liveness only through another resident's Bermuda fix, so it is False for the last person out. That makes it useless as the guard for this rule. |
| Fleet-health evidence | **NEW read of an existing HA entity** | Bermuda `sensor.bermuda_global_active_proxy_count`, unique_id `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT` (live registry, 2026-10-24). Value = `coordinator.count_active_scanners(max_age=10)` = scanners with an advert in the last 10 s (`/config/custom_components/bermuda/coordinator.py:574-581`, Bermuda 0.8.7). grep `active_proxy|proxy_count` in the integration: 0 hits. |
| Per-person BLE device_tracker evidence (`bluetooth_le`) | **NEW small helper in person_coordinator**. **F7, in one sentence:** the walk at `camera_census.py:4250` is not reused because its sticky rule keeps an unavailable tracker counted as BLE, and this rule needs unavailable to mean no opinion. Detail: `camera_census.py:4245-4300` already walks `person.device_trackers` with a `source_type == "bluetooth_le"` test, but it is an inline loop inside a census producer, with census-specific sticky classification (`_known_ble_trackers`, demotion rules, collision warnings). Extracting it would edit a census hot path to share a one-line `source_type` test, and its sticky rule (unavailable trackers stay admitted) is the wrong semantics here, where unavailable must mean no opinion. Cited, not reused. Same `source_type` test, same string. |
| Shared "is this person home" read for trust consumers | **NEW thin method on PersonCoordinator** built on `get_person_location` (`person_coordinator.py:1471`) with a raw-HA fallback (§6b) | name mapping reuses the `person.{name.lower().replace(' ', '_')}` rule at `person_coordinator.py:479` (inverse of `__init__.py:3065-3067`) |
| Toggle | **REUSED class** `_PresenceKillSwitchBase` (`switch.py` ~3700-3838; sibling `PresenceAwayVetoEnabledSwitch` :3871). **NEW subclass + one backing field.** No GPS knob exists (grep `gps` in `switch.py`/`const.py` CONF_*). |
| Cross-coordinator read of a presence flag | **REUSED pattern** | `person_coordinator.py:614-619` (`coordinator_manager.coordinators["presence"]`) |
| State-change listener on an HA entity with unload cleanup | **REUSED pattern** | `async_track_state_change_event` + `entry.async_on_unload` / `_unsub` lists used throughout (e.g. `presence.py` `_handle_fan_change` listener family) |

Greps run: `BLE_SILENT_ONLY_AWAY_CONFIDENCE|BLE_FLEET_LIVENESS_WINDOW_S|PERSON_GPS_FRESHEST_WINS_ENABLED|CONF_.*GPS|gps_as|gps_probative|active_proxy|proxy_count` over the integration; `class .*Switch` in `switch.py`; `person_coordinator` consumers repo-wide; raw `person.*` reads per plan review §F2 (each site re-read, §6b).

### 1.2 Prior planning docs consulted
- `PLANNING_path_alpha_lost_dissolution.md` (matrix section): the 16-row matrix, the **case-(b) never-collapses-to-LOST pin** (:6, :39, :156), row 10 GPS-only home (:75). Narrowed here for one evidence shape (§4.5).
- `PLANNING_person_gps_freshest_wins.md`: GPS axis = freshest real reading (v5.103.76); restart note :86. Unchanged.
- `AUDIT_tracking_status_consumers.md`: `tracking_status` consumer lineage.
- `PLANNING_v4.7.14_away_state_person_tracker_trust.md` (header): origin of path α and of the raw-person-state trust pattern the §6b sites copy ("v4.7.13/v4.7.14 person-trust veto").

### 1.3 Memory bodies
`reference_presence_state_of_play`, `reference_sensor_fleet_classes`, `feedback_ble_config_is_tuned_check_before_asserting`, `feedback_extend_existing_never_rebuild`, `feedback_measure_before_build`, `feedback_suppression_needs_discharge` (the boot latch discharges on a timer, §4.3), `project_guest_mode_false_positive_backlog` (adjacent, unchanged).

### 1.4 Config-first check
Live config (`.storage/core.config_entries`, read 2026-10-24): `tracked_persons = [ezinne, oji_udezue, jaya, ziri]`; `person_decay_timeout` unset → 300 s (`const.py:170`); Bermuda `devtracker_nothome_timeout = 300`. No URA GPS knob exists. Removing the phone GPS tracker from `person.oji_udezue` is ruled out ("leave HA alone"), and it would also lose GPS's away-hastening role. **Code is required.**

---

## 2. Existing BLE / person machinery — inventory (what we already have)

Current `develop`. Right-hand column: behaviour in the 10-24 frozen-GPS case (Oji left, phone GPS
frozen at `home` since the 14:02 restart, both his BLE trackers `not_home`).

| # | Mechanism | Where | What it does | Frozen-GPS case |
|---|---|---|---|---|
| 1 | Three-tier Bermuda room resolution | `person_coordinator.py:520-660` | Bermuda area → room → S1 row 1, ACTIVE, `location=<room>`. BLE wins when it sees the phone. | Not reached (area unresolved). |
| 2 | STALE decay hold | `:660-695` | Last fix < 300 s: keep room, STALE; counts home for α/β (`presence.py:6301-6316`). | First 5 min after leaving (intended). |
| 3 | Person-state branch (Bermuda exists, no room) | `:697-806` | Matrix with BLE `silent`, then three-way split on HA `person.state`: `home` → force ACTIVE+home (:734-761); unknown → LOST `no_signal`; else → ACTIVE+away (:776-792). | **Decisive site:** GPS-led `person.state=home` → forced home. |
| 4 | Person-state branch (no Bermuda sensor) | `:807-887` | Same split, BLE `MISSING`. | Twin override at :832-849. |
| 5 | 16-row matrix | `_classify_matrix_row` `:343-451` | Rows 2/3/10 GPS-home → `home_ble_silent`; row 4 → home 0.5; rows 6/9 → away; row 14 → `away_ble_silent_only` 0.82; row 16 → LOST. | Row 10 → home 0.75 (moot: #3 forces home). |
| 6 | BLE axis vocabulary | `:364-370` | visible / silent / indeterminate / MISSING. | `indeterminate` most of the episode. |
| 7 | Fleet liveness gate | `_ble_fleet_live` `:297-341` | Live iff any person had a Bermuda room fix within 90 s on the previous tick; empty data → False. | **Gap:** proven only by another visible resident, so the last person out is always `indeterminate`. |
| 8 | GPS freshest-wins | `:230-295` | Freshest real GPS reading; no age limit. | `gps=home` (frozen). |
| 9 | Invariant I-α | `:203-207` | No-signal never votes away. | Untouched. |
| 10 | Path α | engine `presence.py:1229`, denominator `:6346-6393` | AWAY iff all trusted `location ∈ {away, ""}` + unidentified 0 + face 0 + cameras OK. **Confidence not read.** | Blocked by forced home. |
| 11 | Nobody-home | `presence.py:1126-1131` | `census_count == 0 AND NOT any_zone_occupied`. `camera_census._get_ble_persons` (`camera_census.py:2670-2687`) counts any `location` not away/unknown. | Blocked: forced home adds 1 to census. |
| 12 | Path β + grace / indoor-clear / sleep exemption | `presence.py:1053-1072` | LOST-away admission. | N/A (ACTIVE). |
| 13 | Phone-left-behind | `binary_sensor.py:2095-2270`, `presence.py:6262-6288` | Excludes a person whose phone stayed home. | N/A. |
| 14 | Row-14 comment | `:423-425` | Claims a 0.9 path-α threshold. | **No such threshold** (#10). Kids vote away today; must not be "enforced". |
| 15 | BLE pre-arrival | `:601-638` | BLE re-fix after ≥15 min `_person_was_away` → `SIGNAL_PERSON_ARRIVING`. | Never armed. |
| 16 | Raw `person.state` trust reads outside person_coordinator | §6b (7 sites) | Zone person-home vetoes, HVAC preserves, night holds, face-latch guard read HA `person.state` directly. | All see the frozen `home`. A fix that stops at #3/#4 leaks here (F2). |

**The kids already run BLE-led.** Jaya and Ziri have no GPS. Their HA `person` state comes from their
`bluetooth_le` trackers, so BLE loss → `person.state=not_home` → #3 else-arm → ACTIVE+away. The defect
is narrow: for an app user, HA's `person` aggregation lets GPS `home` outrank their own BLE `not_home`,
and #3/#4 and the #16 readers take that at face value.

---

## 3. Falsifiable invariants

Definitions used below:
- **own-BLE-away(p):** person p has ≥1 tracker in `person.device_trackers` with `source_type == "bluetooth_le"`, and every such tracker's state is exactly `not_home`.
- **fleet-armed:** the Active Proxy Count entity resolves, its state has been numeric and ≥ `BLE_LEADS_MIN_ACTIVE_PROXIES` continuously for ≥ `BLE_LEADS_ARM_S`, measured from the later of process start and the last time it read below the floor, `unknown` or `unavailable` (§4.2-4.3).
- **overrule(p):** switch ON ∧ fleet-armed ∧ p's WiFi axis ∈ {`MISSING`, `unavailable`} ∧ own-BLE-away(p), evaluated in a `_ps_state == "home"` arm.

**INV-1 (the fix).** If overrule(p) holds on a tick, p is not stamped `location == "home"`. p is stamped ACTIVE + `away` + `away_ble_silent_only`, and `effective_person_state(person.p)` returns `not_home` at every §6b trust site.
*Falsified by* the 10-24 tuple (person.state home, gps home, wifi MISSING, both BLE trackers `not_home`, proxy count 55 steady for 30 min) yielding `home` at person_coordinator or at any §6b trust site.

**INV-2 (no away from a degraded or unproven fleet; no away from absent evidence).** If the switch is OFF, or the fleet is not fleet-armed (proxy sensor missing, below floor, unavailable, or not yet `BLE_LEADS_ARM_S` since boot or since the last drop), or any of p's BLE trackers reads anything but `not_home`, or p has no BLE tracker, or WiFi says home: then p's stamp and every §6b site's result are **byte-identical to develop**. I-α is untouched. Missing or unknown GPS never adds a home witness, so it can never block away.
*Falsified by* F1's repro (all proxies dead, trackers `not_home`, GPS home → anything but `home`), by F3's repro (boot tick, trackers `not_home`, GPS home → anything but `home`), or by a Bermuda reload dip that is not sampled on a tick but is followed by an overrule within `BLE_LEADS_ARM_S`.

**INV-3 (toggle).** Switch OFF → byte-identical to develop everywhere, including §6b sites.

**INV-4 (BLE visibility still wins).** S1 and STALE are unchanged. The rule runs only in the two `_ps_state == "home"` arms, and `effective_person_state` differs from raw only for persons currently overruled.

---

## 4. The rule

### 4.1 The gate (unchanged shape from Rev 1)
In both `_ps_state == "home"` arms (`person_coordinator.py:734`, `:832`), before forcing home:
```
if ble_leads_enabled and fleet_armed(now) and  sources["wifi"] in ("MISSING", "unavailable") and own_ble_trackers_all_not_home(person_state):
    run the existing S3 away arm; tracking_reason = "away_ble_silent_only"; confidence = BLE_SILENT_ONLY_AWAY_CONFIDENCE
    overruled_this_tick.add(person_name)     # local, created at the top of _async_update_data
```
**R2-1:** the set is built in a local (`overruled_this_tick = set()` before the person loop) and
assigned once, `self._gps_home_overruled = frozenset(overruled_this_tick)`, after the loop and before
`return person_data`. It is never mutated in place, so a §6b reader running between awaits mid-tick
sees the previous tick's complete set, never a half-built one. On the `UpdateFailed` path the previous
set is kept, which matches `self.data`, since DataUpdateCoordinator keeps the last good data. It is the
only state `effective_person_state` consults (§6b).

### 4.2 Fleet health (F1)
`fleet_armed(now)` reads `self._fleet_healthy_since` (a datetime or None):
- The proxy entity_id is resolved once via `entity_registry.async_get_entity_id("sensor", "bermuda", "BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT")` and cached; re-resolved on a miss. **Not found → `fleet_armed` is False → rule off** (Wigton, no-Bermuda installs: byte-identical).
- **R2-2, registration:** a method `_ensure_proxy_listener()` runs at the top of every tick. If no listener is held and the registry lookup now resolves, it subscribes. This covers a Bermuda that loads after URA (or is added later): the first tick after the entity appears registers it. The resolved entity_id is cached, and a lookup miss does nothing (rule off). If the resolved entity_id changes (entity renamed), the old unsub is called and it re-subscribes.
- **R2-2, release:** the unsub callable is passed to `self.config_entry.async_on_unload(unsub)` (the person coordinator is built with the integration entry at `__init__.py:3086`; DataUpdateCoordinator holds it as `config_entry`). It is also kept in `self._proxy_unsub` and released by a new `async_teardown()`, called from the unload path immediately before `hass.data[DOMAIN].pop("person_coordinator", None)` (`__init__.py:5680`), which mirrors the TransitionDetector teardown right after it. Double release is guarded (set `_proxy_unsub = None` after calling).
- One `async_track_state_change_event` listener on that entity: a new state below the floor, `unknown`, `unavailable` or non-numeric → `_fleet_healthy_since = None`. A state ≥ floor while `_fleet_healthy_since is None` → `_fleet_healthy_since = now`. The listener exists because the measured dips last ~60 s (§5.3) and the 30 s person tick (`const.py:46`) can miss one. **Wording:** the proxy sensor itself is rate-limited and publishes up to ~60 s late (`_cache_ratelimit_interval = 60`, `bermuda/entity.py:193`). A real proxy outage therefore shows within about 70 s (10 s freshness plus 60 s publish), still well inside the 300 s tracker timeout. A dip shorter than the rate limit may never be published at all; that case is covered by the two-integration requirement in §4.4. A Bermuda reload resets its trackers to `not_home`, so a missed dip followed by an overrule would break INV-2.
- The tick also re-reads the current state (same rule) so a missed listener event self-heals.
- `fleet_armed` = `_fleet_healthy_since is not None and now - _fleet_healthy_since >= BLE_LEADS_ARM_S`.

**Why not the reviewer's fallback disjuncts** (some resident's BLE `home`, or `_ble_fleet_live`): both
prove the fleet only through another resident, so the last person out (the case this card is about)
never gets the rule. They also add a second health definition next to the proxy count. The proxy
count is independent of who is home and is source-verified (§5.3). When it is missing, the rule is off;
that is the named residual for non-Bermuda installs.

### 4.3 Boot latch (F3)
`_fleet_healthy_since` starts as None at process start, so the rule cannot fire until the proxy count
has been ≥ floor for `BLE_LEADS_ARM_S` this session. **Default 360 s** (re-derived per the operator,
§5.4). The rule needs ALL of a person's BLE trackers `not_home`, so after a restart the
**fastest-recovering** tracker governs, not the slow private_ble tail: one tracker reading `home`
blocks the rule. Measured over 23 (person, restart) cases where the person was home before the
restart, the fastest tracker re-read `home` within 300 s in 19 and within 360 s in 20. Among the app
users (Oji, Ezinne, the only people the rule can act on), 14 real cases, all within 360 s; at 300 s one
miss (Oji 10-20 02:08, 344 s). 1200 s was sized to the 16.8 min private_ble tail, which does not govern
an all-trackers rule. The same latch covers recovery from a proxy outage.

**Residual tail risk (stated):** an app user who is home can still have every BLE tracker read
`not_home` past 360 s after a restart. Measured: no app-user case in 7.6 d. The only longer cases were
Jaya (515 s at 22:23, 842 s at 04:42; no GPS, so the rule cannot act on her) and Oji 10-20 17:52
(2,959 s, consistent with him having left: that is the 10-20 17:47 departure). If it happens: that
person reads away until BLE re-hears them. The house goes AWAY only if every other resident also reads
away AND cameras see nobody (α), or the zones are empty (nobody-home). The kids carry the same exposure
today. The `restored` clause from Rev 1 is deleted: neither tracker type
is a RestoreEntity, so it never carries `restored` (review F3).

Discharge (suppression-needs-discharge): the latch releases on its own after `BLE_LEADS_ARM_S` of
healthy count. If the count never becomes healthy, the rule stays off, which is today's behaviour.

### 4.4 Timing (F6, live values)
- Bermuda `*_bermuda_tracker`: `not_home` after `devtracker_nothome_timeout = 300` s without an advert (live Bermuda options).
- `private_ble_device_*`: `not_home` when habluetooth declares the IRK device unavailable. For a non-connectable phone that is the learned advertising interval, or the fallback `FALLBACK_MAXIMUM_STALE_ADVERTISEMENT_SECONDS = 900` s (`habluetooth/const.py:27`, the version in `.venv-ha`; the live HA version was not checked).
- **Main-case latency, measured** (§5.4, 33 departures 10-17 → 10-24): Bermuda's tracker goes `not_home` 296-410 s after the last room fix (typically ~320 s, i.e. its 300 s timeout). private_ble follows within -600 to +218 s of that (the 900 s fallback never showed; habluetooth uses the learned advert interval). So the rule fires **~5-9 min after leaving** (typically ~6-7 min), counted from the last BLE room fix. Today a frozen GPS means it never fires.
- **When the app reports, GPS away still wins:** ~30 s median (card probe, 7 clean events 14-43 s). The new rule matters only when GPS lags or freezes.
- Requiring both integrations also protects against a single-integration reset: a Bermuda reload alone cannot fire the rule while private_ble still hears the phone.

### 4.5 Per-row table (default mode). "away-evidence" = fleet-armed ∧ own-BLE-away.

| Row / case | GPS | WiFi | BLE | Today | Default (switch ON) | Change? |
|---|---|---|---|---|---|---|
| S1 / STALE | any | any | room fix / < 300 s | room | same | no |
| 2 / 3 | home | home | any | home | same (WiFi witness) | no |
| 4 | home | not_home | any | home 0.5 | same (dropped per operator Q2: no WiFi trackers live) | no |
| 10 (10-24) | home | MISSING/unavail | away-evidence | home 0.75 | **away 0.82** | **yes** |
| 10 | home | MISSING/unavail | no away-evidence (any tracker home/unknown/unavail, no tracker, fleet not armed) | home | same | no |
| state home, GPS unknown/MISSING | unk | MISSING/unavail | away-evidence | home 0.75 | **away** | **yes** |
| 6 / 8 / 9 / 11 / 13 | away | any | any | away (row 8 home via WiFi) | same: **GPS away hastens away** | no |
| 14 / 16 / S6 | — | — | — | unchanged | same | no |

**What GPS still does:** it hastens away; it holds home when BLE has no opinion or the fleet is
degraded or unproven; it never holds home against healthy BLE saying the person is gone.

**Deviations from existing semantics, each justified:**
1. *Case-(b) pin narrowed.* The pin protects a phone on a charger with cold Bermuda. A charging phone at home still advertises, so private_ble reads `home` → no change. It narrows only under affirmative BLE `not_home` from two integrations, with a proven-healthy fleet. ACTIVE-away is produced, not LOST.
2. *(Rev 3) Row 4 unchanged* (operator dropped it).
3. *No new status, reason or confidence.* `away_ble_silent_only` is reused; `tracker_sources.gps == "home"` shows GPS was overruled.
4. *Seven raw readers now go through one helper (§6b).* The fix is otherwise not consumed where trust decisions are made (Bug Class #53).

---

## 5. D0 — measure-before-build probes (RUN 2026-10-24, read-only)

`ssh ha "python3 -" < script`, read-only URI on `home-assistant_v2.db`. Window = retention,
2026-10-17 04:12 → 2026-10-24 18:47 CDT (7.6 d). Scripts in the session scratchpad
(`probe3.py`, `probe4.py`, `f1.py`, `f1b.py`, `f1c.py`); re-runnable.

Live tracker inventory: Oji = phone GPS + `private_ble_device_8ce182` + Bermuda tracker (+ `gold_macos_client`, gps source, `unknown`); Ezinne = GPS `zinny_s_iphone_15` + BLE `ezinne_iphone` + Bermuda tracker; Jaya = `private_ble_device_249050` + Bermuda tracker; Ziri = `ziri_iphone` (BLE), almost never seen.

### 5.1 (b) GPS overriding BLE-silent to home today
| Person | Segments (≥ 2 min) | Minutes | Raw BLE during them |
|---|---|---|---|
| Oji | **13** | **1,132 (18.9 h)** | both BLE trackers `not_home` ≥ 95% of every segment except two short ones (BLE ~50%) |
| Ezinne | 1 | 2 | BLE home 100% |
| Jaya / Ziri | 0 | 0 | no GPS |

Oji's segments (start CDT, length): 10-19 09:37 8.5 m; 10-19 17:50 104 m (GPS 103 m old at start);
10-20 07:26 55.5 m; 10-20 22:21 5 m; 10-21 07:30 42 m; 10-22 16:45 77 m; 10-22 19:28 23.5 m;
10-23 11:32 152 m; 10-23 17:33 45.5 m; 10-24 08:45 85.6 m; 10-24 10:10 → ongoing 520 m. None
overnight. Every closed segment ended with a Bermuda room fix.

**Caveat found by D0b:** the 10-24 10:10 segment start, and the 10-20 17:50 / 10-20 22:21 starts,
coincide with HA restarts (§5.3). At a restart, both BLE integrations reset to `not_home`, so some
segment *starts* are restart artefacts rather than departures. Under Rev 2 the boot latch keeps
those minutes at today's behaviour. This is part of the oracle question Q1.

### 5.2 (a) Resident at home but BLE-silent long enough to be marked away
Proxy for "at home": BLE-silent episodes ≥ 5 min starting 23:00-06:00. **Oji 0, Ezinne 0, Jaya 0**
(Ziri n/a, never resolved). Jaya's daytime episodes (school, evenings) are already marked away by the
existing BLE-led path.

### 5.3 D0b — does the Active Proxy Count drop when the BLE fleet goes deaf? (F1)
- Registry: `sensor.bermuda_global_active_proxy_count`, unique_id `BERMUDA_GLOBAL_ACTIVE_PROXY_COUNT`, enabled.
- Distribution over 2,474 rows: median 54, p1 44, max 62; `0` on 20 rows, `1` twice, `20` once (all at boot), `unavailable` once.
- **Fleet-wide BLE `not_home` clusters** (≥ 4 of the 6 resident BLE trackers flipping `not_home` within 2 min): 17. **14 of the 17 coincide with the count reading 0** within ±10 min. The other 3 (10-20 07:25, 10-21 07:29, 10-21 15:47) had a normal count (59-62) and sit at school-run / pickup times: real departures, correctly not flagged.
- **Every 0 / unavailable reading is an HA restart (19 `homeassistant_start` events) or one Bermuda reload (10-21 16:43, `unavailable` then 0).** Each dip lasted ~60 s. After them, present residents' trackers re-read `home` at +0 to +16.8 min (private_ble slowest).
- **What the probe proves:** the count goes to 0 and the trackers go `not_home` together at every integration-level reset, and the count stays high through real departures. **What it cannot prove:** that the count drops during a proxy-hardware or adapter outage while HA keeps running, because none happened in the window. That half rests on source: `count_active_scanners(max_age=10)` counts scanners with an advert in the last 10 s (`bermuda/coordinator.py:574-581`), so a deaf proxy leaves the count within 10 s by construction. The sensor publishes up to ~60 s late (`bermuda/entity.py:193`), so the drop is visible within ~70 s, well inside the 300 s tracker timeout.
- **Guard chosen on this evidence:** count ≥ `BLE_LEADS_MIN_ACTIVE_PROXIES` (default 30: below p1 44, above every non-boot partial reading) held for `BLE_LEADS_ARM_S` (360 s, §5.4), with an edge listener so a 60 s dip cannot slip between 30 s ticks. A partial outage that keeps the count ≥ 30 but blinds the scanners near a resident is a named residual (§9); it needs both BLE integrations to lose that phone for ≥ ~5-9 min.

**Go/no-go:** GO.

### 5.4 Arm window and departure latency (operator follow-up, read-only, scratchpad `arm.py`, `lat.py`)
- **Restart recovery**, per (person, restart) where the person had a BLE tracker `home` before shutdown, seconds from `homeassistant_start` to the first `home` on ANY of their BLE trackers. 23 cases: −4, −4, −3, −3, −3, −2, −1, 0, 4, 6, 8, 13, 16, 18, 81, 117, 145, 154, 197, **344** (Oji, 02:08), **515** (Jaya), **842** (Jaya, 04:42), **2,959** (Oji, 10-20 17:52, a departure). ≤ 300 s: 19/23; ≤ 360 s: 20/23; app users: 14/14 real cases ≤ 360 s. Bermuda trackers usually lead (0-150 s); private_ble lags 42-2,196 s.
- **Departure latency**, 33 non-restart Bermuda `home → not_home` edges: 296-637 s after the last room fix (median ~318 s; two Jaya outliers 594/637 s). private_ble `not_home` relative to that: −599 to +218 s (median ~+90 s).
- Verdict: 360 s covers every observed app-user restart; 300 s misses one by 44 s. The operator asked for "~300 s if the data supports it"; the data supports 360 s, which is still under 1/3 of the Rev 2 value.

---

## 6. Producer and consumer checks

**Producer:** `person_coordinator.data[p]` (`location`, `tracking_status`, `tracking_reason`, `confidence`)
plus the new per-tick `_gps_home_overruled` set. Dependency health: Bermuda area sensors (healthy except
Ziri); BLE trackers (healthy; reset at every restart, §5.3); Bermuda proxy count (healthy, median 54);
GPS (Oji's freezes / lags, Ezinne's healthy); HA `person` aggregation (prefers GPS; not changed).

**Consumers of person_coordinator `location`:**

| Consumer | file:line | Trust / display | Effect |
|---|---|---|---|
| Path α denominator | `presence.py:6346-6393` → `:1229` | trust | overruled person counts away → α can fire (still needs unidentified 0, face 0, cameras OK) |
| Census BLE-home list | `camera_census.py:2670-2687`, used `:1714` | trust (census → nobody-home `presence.py:1126`, guest gate) | phantom resident removed |
| Path β | `presence.py:1053-1072` | trust | unchanged (ACTIVE) |
| BLE pre-arrival | `person_coordinator.py:601-638` | trust | armed after an overrule → fires on BLE return (Q3) |
| `persons_home` attr / NM targeting | `aggregation.py:2070-2090` | display + routing | listed away |
| fan_veto / fan recheck / room BLE limbs | `fan_veto.py:296-320`, `presence_fan_recheck.py:672, 1168`, `coordinator.py:4060-4075, 4615-4620` | trust | room strings only; `home`/`away` are not rooms → no effect |
| Music following, transitions, DB snapshot, location sensor | `music_following.py:597-713`, `transitions.py:158+`, `person_coordinator.py:889-907`, `aggregation.py:5700-5760, 6038-6064` | display / history | show away |
| HVAC | via `SIGNAL_HOUSE_STATE_CHANGED` and the §6b sites | trust | house can go AWAY; §6b sites see `not_home` |

(Rev 1 listed `aggregation.py:4494, 4634` here as person_coordinator consumers. That was wrong; they read
raw HA state and are now in §6b.)

### 6b. Raw `person.state` readers (F2) — disposition

New method on PersonCoordinator:
```
def effective_person_state(self, person_entity_id: str) -> str | None:
    raw = hass.states.get(person_entity_id); raw_state = raw.state if raw else None
    name = the tracked key k with f"person.{k.lower().replace(' ', '_')}" == person_entity_id
    if name in self._gps_home_overruled and self.get_person_location(name) == "away":
        return "not_home"
    return raw_state
```
It differs from raw HA **only** for a person overruled this tick (cross-checked against
`get_person_location`). Everything else, including persons URA disagrees with for other reasons, stays
raw, which keeps each site byte-identical outside the overrule. Call sites reach it through a
module-level wrapper `person_state_for_trust(hass, person_entity_id)` in `person_coordinator.py`. With
no person_coordinator in `hass.data`, or any exception, it returns the raw state, so Wigton and the
no-coordinator path stay byte-identical.

| Site | Reads | Trust / display | Disposition |
|---|---|---|---|
| `aggregation.py:4455-4463` → `ReliableSignal("zone_persons_home")` `:4494` | raw `== "home"` | trust (zone veto, `presence.py:2121/2133`) | **ADOPT** |
| `aggregation.py:4589-4596` → `:4634` | raw `== "home"` | trust (same) | **ADOPT** |
| `hvac_zones.py:2655-2675` `zone_has_home_person` (D7 / row-1 fail-open preserve) | raw `== "home"` | trust (HVAC preset preserve) | **ADOPT** |
| `hvac.py:3401-3410` night-trust preset hold | raw `== "home"` | trust (FAN_TRUST_STATES, only if not `_zone_conditioning_retreat_ok`) | **ADOPT.** 0 overnight frozen segments were measured, but adopting costs one line and keeps HVAC from holding a zone for a person URA has as away. |
| `hvac.py:3978-3986` `main_row_home_persons` | raw `== "home"` | **display** (activity-log payload for the preset row; feeds only `activity_logger.log`) | **ADOPT** for consistency, so the log matches the 3401 decision it is correlated with. Not trust-bearing. |
| `hvac_fans.py:1525-1535` night vacancy hold | raw `== "home"` | trust (night, FAN_TRUST_STATES) | **ADOPT** (same reasoning as hvac.py:3401) |
| `camera_census.py:5884-5895` stale-face latch guard | raw `== "not_home"` | trust (path α needs face 0) | **ADOPT.** Otherwise a face seen as the person leaves holds α for up to `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (1800 s). **Timing note (LOW):** the census reads the previous tick's overruled set, up to 30 s old. Being one tick late only delays when the face drops out, by ≤ 30 s against a 1800 s window. It cannot drop a face early, because the set only contains persons both BLE integrations have already lost. |
| `camera_census.py:4193-4199` `is_face_leg_person_vetoed`; `transit_validator.py:1837-1847` egress veto | raw `== "not_home"` | trust (identity) | **LEAVE.** These veto a face leg for a person who is `not_home`. The overrule state ends exactly on the person's return, before BLE re-acquires them, which is when the door face fires, so adopting would veto real arrival identities. Today a working GPS has the same timing; we add no new veto. |
| `camera_census.py:4391-4445` BLE transition legs; `security.py:2024-2030`; `presence.py:5124/5143`, `:8734` geofence | edges on raw state changes | trust (edge-triggered) | **LEAVE.** The overrule produces no HA state edge, so these see no false edge; a frozen GPS emits none today either. Synthesising edges would add crossing events the cycle does not need. |
| `camera_census.py:5686-5694`, `:5726-5733` | tracker inventory / router guests | structural | **LEAVE** (not a home/away read) |

---

## 7. Emission / decision-site enumeration

1. `person_coordinator.py:734-761` (Bermuda exists, no room) — **change** (gate).
2. `person_coordinator.py:832-849` (no Bermuda sensor) — **change** (same helpers; Bug Class #53 if missed).
3. `:435-437` matrix fallback — overwritten by 1/2; **no edit**, pinned by test.
4. Matrix rows 2/3/4/10 — **no edit** (the matrix stays a pure function of axes).
5. S1 / STALE — **no edit**.
6. The seven §6b ADOPT sites — **change** (one-line swap to `person_state_for_trust`).
7. `_gps_home_overruled` built in a local and assigned once after the person loop (R2-1) — **new**, one site.
8. Proxy listener register (`_ensure_proxy_listener`, per tick) and release (`entry.async_on_unload` + `async_teardown` at `__init__.py:5680`) — **new**.

---

## 8. Deliverables

### D0 / D0b — probes (DONE, §5)
The builder copies `probe4.py` and `f1c.py` to `scripts/probes/presence_gps_override_probe.py` for the post-deploy re-run.

### D1 — The gate, fleet guard and boot latch (person_coordinator.py)
- `_own_ble_trackers_all_not_home(person_state) -> bool`: ≥1 `bluetooth_le` tracker in `device_trackers`, every one exactly `not_home`; exception → False.
- `_ble_leads_enabled() -> bool`: presence `_ble_leads_enabled` via the `:614-619` pattern; missing → True; exception → True.
- Fleet guard (§4.2): registry-resolved proxy entity, `_fleet_healthy_since`, the listener (unsub on unload), tick re-read, `fleet_armed(now)`. Proxy entity missing → False.
- Gate at sites 1 and 2 (§4.1). Factor the S3 arm body into one local helper shared by the else-arm and the overrule path, so the side effects cannot drift.
- `_gps_home_overruled: frozenset[str]`, built in a local and assigned once per tick (R2-1).
- `_ensure_proxy_listener()` + `async_teardown()`; teardown wired at `__init__.py:5680` (R2-2).
- DEBUG log on transition into or out of overruled (not per tick); one INFO when `fleet_armed` changes.
- Knobs (rung 1, `const.py`, review-only because they are safety bounds against a degraded fleet):
  `BLE_LEADS_MIN_ACTIVE_PROXIES = 30` (floor; 0 = any count passes, which leaves only the boot latch and unavailable as protection, so it is not a kill switch); `BLE_LEADS_ARM_S = 360` (boot / recovery latch; §5.4). The kill switch is D2.

**Acceptance criteria**
- **Verify:** 10-24 tuple, fleet armed → `location="away"`, ACTIVE, `away_ble_silent_only`, 0.82, `tracker_sources.gps == "home"`, `_person_was_away` True.
- **Verify (discriminating):** same tuple with one BLE tracker `home` → `home`; with a tracker `unavailable` → `home`; WiFi `home` → `home`; no `bluetooth_le` tracker → `home`.
- **Verify (F1):** all trackers `not_home`, proxy count 0 → `home` (byte-identical); count 31 for 359 s → `home`; at 360 s → away.
- **Verify (F1 dip):** armed; a listener event of `0` then `55` 60 s later, with no tick in between; overrule tuple on the next tick → `home` until 360 s after the 55.
- **Verify (F3 boot):** empty `self.data`, process just started, count 55, trackers `not_home`, GPS home → `home` for the first 360 s; and with ONE tracker reading `home` at 100 s, still `home` after 360 s.
- **Verify:** proxy entity absent from the registry → `home` (rule off).
- **Verify:** both sites behave identically; all 16 matrix row fixtures pass unmodified.
- **Test:** `test_person_gps_assistive.py::test_frozen_gps_home_ble_not_home_goes_away`, `::test_one_ble_tracker_home_keeps_home`, `::test_ble_unavailable_keeps_home_ialpha`, `::test_wifi_home_witness_keeps_home`, `::test_no_ble_tracker_keeps_home`, `::test_row4_unchanged_wifi_not_home`, `::test_fallback_home_without_witness_overruled`, `::test_no_bermuda_branch_twin_site`, `::test_side_effects_match_s3_arm`, `::test_pre_arrival_fires_on_ble_return_after_overrule`, `::test_fleet_dead_keeps_home`, `::test_fleet_below_floor_keeps_home`, `::test_arm_window_boundary`, `::test_unsampled_dip_resets_latch_via_listener`, `::test_boot_latch_keeps_home`, `::test_proxy_entity_missing_rule_off`, `::test_listener_unsubscribed_on_unload`, `::test_listener_registers_on_late_bermuda_load`, `::test_overruled_set_assigned_once_after_loop`, `::test_overruled_set_kept_on_update_failed`.
- **Mutation (framing C):** neuter site 1 → `test_frozen_gps_home_ble_not_home_goes_away` RED; neuter site 2 → `test_no_bermuda_branch_twin_site` RED; drop the fleet conjunct → `test_fleet_dead_keeps_home` RED; drop the arm window → `test_boot_latch_keeps_home` RED; drop the listener reset → `test_unsampled_dip_resets_latch_via_listener` RED; drop the WiFi check → `test_wifi_home_witness_keeps_home` RED.
- **Live (F5, discriminating):** the next time Oji leaves with the phone and its GPS lags or freezes, `sensor.universal_room_automation_oji_udezue_location` reads Away with `away_ble_silent_only` within one 30 s tick of both his BLE trackers reading `not_home` (expect ~5-9 min after he leaves). That observation is the discriminator. If he is last out, the house-state sensor's `last_away_branch` records an AWAY (`active` / `nobody_home`) within 30 min of that. That is the face-latch bound, now closed by §6b; a longer lag points at a §6b site that was missed.
- **Live:** `sensor.bermuda_global_active_proxy_count` resolves (one INFO at setup naming it); within ~7 min of restart (360 s + the ~60 s proxy publish lag) the INFO "fleet armed" appears.
- **Live re-run (D0 probe, 24 h after deploy):** (1) GPS-home URA segments with both BLE trackers `not_home` > 10 min, excluding the 6 min after a restart: **0** (was 11 of 13). (2) **False aways:** episodes where an app user's URA location reads `away` while their own BLE tracker reads `home` within ±3 min, overnight (23-06): **0**. (3) No `away_ble_silent_only` stamp for an app user within 360 s of a `homeassistant_start`; and any app-user `away_ble_silent_only` stamp within 360-900 s of a start is listed and checked against BLE (the tail residual).

### D1b — `effective_person_state` and the seven §6b swaps
- Method on PersonCoordinator + module wrapper `person_state_for_trust(hass, entity_id)` (§6b).
- Swap at `aggregation.py:4458`, `aggregation.py:4592`, `hvac_zones.py:2671`, `hvac.py:3405`, `hvac.py:3982`, `hvac_fans.py:1531`, `camera_census.py:5888` (exact lines re-located at build). Each keeps its comparison string (`== "home"` / `== "not_home"`) and its fail-open/closed shape.

**Acceptance criteria**
- **Verify:** overruled person → each of the seven sites reads `not_home` (zone veto False, HVAC preserve False, night holds not extended for that person, face latch drops them).
- **Verify (byte-identical):** non-overruled person, switch OFF, or no person_coordinator → each site sees the raw state (parametrised over home / not_home / zone name / unknown / missing entity).
- **Test:** `test_person_gps_assistive.py::test_effective_state_only_differs_when_overruled`, `::test_effective_state_fallback_no_coordinator`, plus one per site: `::test_zone_persons_home_veto_uses_effective_state` (×2 sites), `::test_hvac_zone_has_home_person_effective`, `::test_hvac_night_trust_effective`, `::test_hvac_fans_night_hold_effective`, `::test_face_latch_drops_overruled_person`.
- **Mutation:** revert each swap to the raw read, one at a time → that site's test RED (7 drills).
- **Live:** during an overrule, `binary_sensor`/zone status for the house zone shows no `zone_persons_home` veto naming Oji; the HVAC activity log row's `home_persons` excludes him.

### D2 — Toggle `switch.ura_presence_ble_leads_home_away` (rung 3)
- `PresenceBleLeadsEnabledSwitch(_PresenceKillSwitchBase)`: `_unique_slug = "presence_ble_leads_enabled"`, `_friendly_name = "BLE Leads Home/Away"`, `_backing_field = "_ble_leads_enabled"`, `_since_field = "_ble_leads_suppressed_since"`, icon `mdi:bluetooth`. Backing field + since field on PresenceCoordinator next to `_away_veto_enabled` (`presence.py:1780`).
- Description: **"BLE Leads Home/Away — On: a phone's Bluetooth decides home or away; GPS can only speed up leaving. Off: a GPS 'home' also counts as proof, for homes with few Bluetooth scanners or heavy app use."** OFF = today's behaviour.
- Rung 3: per-home policy, both positions safe. Named in the default-ON sense so it reuses `_PresenceKillSwitchBase` unmodified; the operator's "GPS as proof" is this switch OFF.

**Acceptance criteria**
- **Verify:** OFF → overrule tuple → `home` at person_coordinator and at all seven §6b sites (INV-3).
- **Verify:** OFF survives restart, including deferred restore.
- **Test:** `::test_switch_off_restores_gps_proof`, `::test_switch_off_effective_state_raw`; extend the presence kill-switch parametrised restore test with the new class.
- **Mutation:** ignore the switch → `::test_switch_off_restores_gps_proof` RED.
- **Live:** entity exists, state `on`. Toggling OFF then ON during an overrule moves Oji's location Home then Away within one 30 s tick.

### D3 — Docs (same commit)
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §3: new "GPS assistive (BLE leads)" paragraph covering the rule, fleet guard, boot latch, switch, `effective_person_state` and its seven sites. §1 consumer table: add the shared helper. §10 corrections:
  - "BLE-only away at 0.82 cannot flip the house because path α needs 0.9" (`person_coordinator.py:423-425`) — WRONG; α ignores confidence (`presence.py:6388`).
  - "Fleet liveness gates BLE silence for everyone" — INCOMPLETE; it is proven only via another resident's Bermuda fix (`:297-341`).
  - §2 step 0 "census_count includes BLE-located residents" — census counts any `location` not away/unknown, including a GPS-forced `home` (`camera_census.py:2683-2685`).
  - "A dead BLE fleet makes trackers unavailable" (this plan Rev 1) — WRONG; private_ble and Bermuda trackers read `not_home` while available (review F1); the fleet signal is Bermuda's active proxy count.
- Fix the `:423-425` comment (comment only). Update the card with the D0/D0b numbers.

---

## 9. Non-goals and named residuals
- No HA changes (person entities, trackers, zones, app settings, Bermuda options).
- No GPS age / freshness knob (rejected: a timeout still lets a frozen fix hold for the timeout, and BLE `not_home` is better evidence that is already present).
- No change to `_ble_fleet_live`, the matrix, row 14, I-α, STALE, path β, phone-left-behind, `TRACKING_REASON_VALUES`, confidences, WiFi axis.
- No HVAC / census / camera **logic** change. Seven raw `person.state` reads are swapped to `person_state_for_trust` (§6b); comparisons and fail-open shapes are unchanged.
- Identity vetoes (`camera_census.py:4193`, `transit_validator.py:1837`) and edge-triggered readers stay raw (§6b).
- Not enforcing the 0.82 < 0.9 comment.
- No new trip-wire (operator: no need to care about BLE misses at home).
- **Residual R1:** installs without Bermuda's proxy-count entity get no BLE-leads rule (today's behaviour).
- **Residual R2:** a partial outage that keeps ≥ 30 proxies live but blinds every scanner near one resident, for ≥ ~5-9 min across both BLE integrations, can mark that resident away (as it already can for the kids).
- **Residual R3:** for the first 6 min after every restart and every proxy-count drop, a frozen GPS still holds the person home (today's behaviour).
- **Residual R4 (restart tail):** an app user at home whose BLE trackers all stay `not_home` > 360 s after a restart reads away until BLE re-hears them. 0 of 14 app-user cases in 7.6 d (§4.3, §5.4).
- Ziri: at college (operator). His away is accurate; no card.
- Row 4 (GPS home + WiFi not_home): dropped per operator; no WiFi trackers live.

## 10. Tier
**Tier 2, elevated to 3 framing-disjoint build reviews** (presence → house state → HVAC / census
ripple; narrows the case-(b) pin; now touches seven raw readers in four files). Not Tier 3: one gate
plus a read-only helper, fail-safe to today on every non-matching input, with a kill switch.
Re-review of this Rev 2 plan before build. Build-review framings: **A** correctness across axis ×
fleet × boot combinations and the seven §6b swaps (byte-identical when not overruled); **B** lifecycle
and ripple (listener register/unsub, missed dip, restart latch, census / α / nobody-home / HVAC /
pre-arrival); **C** per-site source mutation (6 drills in D1, 7 in D1b, 1 in D2). Builder: `ura-builder`.
Deploy risk: MED.

## 11. Open questions for the operator
1. **Oracle check:** were you out on 10-19 17:50-19:34, 10-22 16:45-18:02 and 10-23 11:32-14:04? (BLE gone, GPS home.) The 10-24 10:10 start coincides with a restart; roughly when did you actually leave today?
ANSWERED 2026-10-24: Q2 row 4 dropped; Q3 dropout pre-arrival accepted (overrule sets `_person_was_away`); Q4 Ziri at college, no card; Q5 arm window re-derived to 360 s (§5.4).
