# PLANNING — Presence: GPS assistive, BLE leads (card PERSON-BLE-WINS-OVER-STALE-GPS-1)

**Status:** plan, awaiting Tier-2 plan review. No code written.
**Card:** `PERSON-BLE-WINS-OVER-STALE-GPS-1` (`docs/planning/kanban.data.yaml:32943`).
**Read first (done, completely):** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`
(all 730 lines, §0-§11 + addendum + gold patterns) and `docs/architecture/SENSOR_FLEET_CLASSES.md`.
Sensor-fleet classes are not touched by this cycle. HVAC is touched only as a downstream consumer of
house state; no HVAC code change.

**Operator intent (verbatim, 2026-10-24):** "We have to demote gps in code. And make it assistive vs
at same level as ble. But we could make it so a toggle makes it more important for ble sparse and more
app use." / "The house works well on ble. Only Ezinne even has the app. The kids don't. For now gps is
assistive not probative." / "I don't have to care about Bluetooth being missed while at home. Or prove
I do." / "Leave ha alone." / Users may turn location off or deny iOS permission, so missing GPS must
never block away. Addendum: "Make sure you understand ble prior art... For key subsystems I expect
very narrow changes unless justified. Don't act like this is green field."

---

## 1. Institutional context verified

### 1.1 Prior-art scan (code + plans + memory), REUSE-or-BUILD per piece

| Piece | Verdict | Existing symbol |
|---|---|---|
| Tracking statuses ACTIVE / STALE / LOST | **REUSED, no new status** | `TRACKING_STATUS_*` (const), stamped in `person_coordinator.py:573, 667, 767, 780` |
| Away stamp for "BLE says gone" | **REUSED** `tracking_reason="away_ble_silent_only"` (row 14) | `person_coordinator.py:426-429`; vocab `const.py` `TRACKING_REASON_VALUES` (~:197-215) |
| Away confidence | **REUSED** `BLE_SILENT_ONLY_AWAY_CONFIDENCE = 0.82` | `const.py:243` |
| S3 away side effects (`_person_lost_since`, `_lost_away_since`, `_person_was_away`) | **REUSED** verbatim | `person_coordinator.py:776-792` and `:861-873` |
| Per-tick GPS/WiFi/BLE axis read | **REUSED, unchanged** | `_read_source_inventory` `person_coordinator.py:209-295` (ignores `bluetooth_le` trackers by design, :287-289) |
| Fleet liveness gate | **REUSED, unchanged** | `_ble_fleet_live` `person_coordinator.py:297-341`, `BLE_FLEET_LIVENESS_WINDOW_S = 90` (:67) |
| Per-person BLE device_tracker evidence (`private_ble_device_*`, `*_bermuda_tracker`, source_type `bluetooth_le`) | **NEW helper** (one small pure-ish method). No existing reader: grep `bluetooth_le` in `person_coordinator.py` hits only the :287 comment; `camera_census._ble_home_by_area` / `fan_veto._ble_present_in_room` read person_coordinator data, not raw trackers. These are the same entities HA's own `person` entity already uses for Jaya and Ziri. |
| Toggle | **REUSED class** `_PresenceKillSwitchBase` (`switch.py:~3700-3838`, siblings `PresenceAwayVetoEnabledSwitch` :3871). Default ON, OFF = suppressed, RestoreEntity, deferred-restore via `SIGNAL_PRESENCE_COORDINATOR_READY`. **NEW subclass + one backing field** on PresenceCoordinator. grep `gps` in `switch.py` / `const.py` CONF_*: no GPS knob exists (only `DETECTION_METHOD_GPS` :272 and vocab comments). |
| Cross-coordinator read of a presence flag from person_coordinator | **REUSED pattern** | `person_coordinator.py:614-619` (reads `coordinator_manager.coordinators["presence"].observation_mode`) |

Greps run: `BLE_SILENT_ONLY_AWAY_CONFIDENCE|BLE_FLEET_LIVENESS_WINDOW_S|PERSON_GPS_FRESHEST_WINS_ENABLED|CONF_.*GPS|gps_as|gps_probative` over the integration; `class .*Switch` in `switch.py`; `person_coordinator` consumers repo-wide (counts: aggregation 165, sensor 63, presence 38, binary_sensor 25, camera_census 19, coordinator 12, music_following 10, transitions 5, hvac 3, fan_veto 3, presence_fan_recheck 2, bayesian 1).

### 1.2 Prior planning docs consulted
- `PLANNING_path_alpha_lost_dissolution.md` (full matrix section): origin of the 16-row matrix, the **case-(b) never-collapses-to-LOST pin** (:6, :39, :156) and row 10 GPS-only home (:75). This plan narrows case-(b) for one evidence shape; justification in §4.
- `PLANNING_person_gps_freshest_wins.md`: GPS axis = freshest real GPS reading (shipped v5.103.76). Restart note (:86): restored trackers carry boot-time timestamps. Unchanged here.
- `AUDIT_tracking_status_consumers.md` (referenced by the classifier header, :201): consumer lineage of `tracking_status`.
- `PLANNING_v4.7.14_away_state_person_tracker_trust.md` (filename + header): origin of path α veto.

### 1.3 Memory bodies
`reference_presence_state_of_play`, `reference_sensor_fleet_classes`, `feedback_ble_config_is_tuned_check_before_asserting`, `feedback_extend_existing_never_rebuild`, `feedback_measure_before_build`, `project_guest_mode_false_positive_backlog` (LOST-but-away class, adjacent, not changed).

### 1.4 Config-first check
Live config (`.storage/core.config_entries`, read 2026-10-24): `tracked_persons = [ezinne, oji_udezue, jaya, ziri]`; `person_decay_timeout` unset → default 300 s (`const.py:170`). No GPS-related URA knob exists. The only config fix would be removing the phone GPS tracker from `person.oji_udezue` in HA, which the operator ruled out ("leave HA alone") and which would remove GPS's useful away-hastening role. **Code is required.**

---

## 2. Existing BLE / person machinery — inventory (what we already have)

Everything below is current `develop`. The right-hand column says what each piece does in the
10-24 frozen-GPS case (Oji left, phone GPS frozen at `home` since the 14:02 restart, both his BLE
trackers `not_home`).

| # | Mechanism | Where | What it does | Frozen-GPS case |
|---|---|---|---|---|
| 1 | Three-tier Bermuda room resolution | `person_coordinator.py:520-660`, ladder doc :10-14 | Bermuda area sensor resolves to a room → S1 row 1, ACTIVE, `location=<room>`, `last_bermuda_update=now`. BLE always wins when it sees the phone. | Not reached: area sensor unresolved. |
| 2 | STALE decay hold | `:660-695` | Area unresolved but last Bermuda fix < `decay_timeout` (300 s): keep old room, STALE, confidence halved. Counts home for α/β while `PRESENCE_STALE_RESIDENT_COUNTS_HOME` (presence.py:6301-6316). | First 5 min after leaving: holds last room (correct and intended). |
| 3 | Person-state branch (Bermuda exists, no room) | `:697-806` | Reads `_sources` (GPS/WiFi axes), fleet liveness, runs the matrix with BLE axis `silent`, then a **three-way split on HA `person.state`**: `home` → force ACTIVE+home (:734-761); unknown → LOST `no_signal` (:762-775); else → ACTIVE+away (:776-792). | **Decisive site.** `person.state == home` (HA prefers the GPS tracker) → forced ACTIVE+home regardless of the matrix row. |
| 4 | Person-state branch (no Bermuda sensor) | `:807-887` | Same three-way split, BLE axis `MISSING`. | Same override at :832-849 (twin site). |
| 5 | 16-row matrix classifier | `_classify_matrix_row` `:343-451` | Rows 2/3/10 GPS-home → `home_ble_silent` ACTIVE+home (0.85/0.80/0.75); row 4 GPS home + WiFi not_home → home 0.5; rows 6/9 GPS away → away; row 14 BLE silent with liveness → `away_ble_silent_only` 0.82; row 16 → LOST `no_signal`. | Row 10 (GPS home, WiFi MISSING) → home 0.75. Live attrs 10-24: `home_ble_silent`, `{gps: home, wifi: MISSING, ble: indeterminate/silent}`, conf 0.75. The row stamp is moot anyway because #3 forces home. |
| 6 | BLE axis vocabulary | `:364-370` | `visible` (S1 only), `silent` (tried, nothing), `indeterminate` (silent without liveness), `MISSING`. | BLE was `indeterminate` most of the episode (see #7). |
| 7 | Fleet liveness gate | `_ble_fleet_live` `:297-341` | Fleet is "provably live" iff ANY tracked person had a Bermuda room fix within 90 s on the previous tick. Empty data → False (A-M1). | **Gap found by this plan:** liveness is proven only by *another* person being BLE-visible. When the last resident leaves, nobody is visible, so BLE degrades to `indeterminate` exactly in the last-person case. Row 14 cannot fire for that person even with no GPS. |
| 8 | GPS axis: freshest-wins | `_read_source_inventory` `:230-295` | Freshest real GPS reading; unknown never beats real. | `gps=home` (frozen fix is the only real reading). No age limit. |
| 9 | Invariant I-α | header `:203-207` | No-signal never produces an away vote. | Untouched by this plan (§3). |
| 10 | Path α AWAY | `presence.py:1229` (engine), denominator `:6346-6393` | AWAY iff all trusted persons `location ∈ {away, ""}` AND unidentified 0 AND face 0 AND camera fleet not degraded. Trusted = phone not left behind AND ACTIVE (or STALE while the D2 flag is on). **Confidence is not read** (`:6388-6391`). | Oji ACTIVE+home → `all_tracked_persons_away = False` → α blocked indefinitely. |
| 11 | Nobody-home AWAY | `presence.py:1126-1131` | `census_count == 0 AND NOT any_zone_occupied`. | Blocked: `camera_census._get_ble_persons` (`camera_census.py:2670-2687`) counts any person whose `location` is not away/unknown, so a GPS-forced `home` adds 1 to census. |
| 12 | Path β (LOST-but-away) + grace / indoor-clear / sleep exemption | `presence.py:1053-1072`, `CONF_LOST_AWAY_*` | Admits LOST-away trackers after grace with indoor guard. | Not applicable: Oji is ACTIVE, not LOST. |
| 13 | Phone-left-behind | `binary_sensor.py:2095-2270`, `presence.py:6262-6288` | Excludes a person whose phone is home without them. | Not applicable (phone left with Oji). |
| 14 | Row-14 confidence comment | `:423-425` | Says 0.82 < "path-α threshold 0.9 so solo BLE-only cannot flip house alone". | **No such threshold exists** (#10 ignores confidence). Kids already vote away on row 14 / `away_wifi_only` today. The comment is wrong; it must not be "enforced" now, because enforcing it would stop Jaya/Ziri from ever voting away. |
| 15 | BLE pre-arrival | `:601-638` | A BLE room re-fix after ≥15 min `_person_was_away` dispatches `SIGNAL_PERSON_ARRIVING`. | Never armed (no away stamp), so the real return fired nothing. |

**How the kids already work (the existing BLE-led path).** Jaya and Ziri have no GPS tracker. Their HA
`person` state comes from their `bluetooth_le` trackers. When BLE loses them, `person.state` →
`not_home` → branch #3 else-arm → ACTIVE+away (`away_wifi_only` / `away_ble_silent_only`). The probe
(§5) shows that path working every school day. **So the house already runs BLE-led for two of four
residents.** The defect is only that, for an app user, HA's `person` aggregation lets the GPS tracker's
`home` outrank the same person's BLE trackers' `not_home`, and site #3/#4 takes that at face value.

---

## 3. Falsifiable invariants

**INV-1 (the fix).** With the switch `BLE Leads Home/Away` ON (default): for any tick in either
person-state branch (#3, #4), if the person's home claim has **no non-GPS home witness**
(WiFi axis ≠ `home`) **and** the person has ≥1 `bluetooth_le` tracker in `person.device_trackers`
**and every such tracker reads `not_home`** with no `restored: true` attribute, then the person is
**never** stamped `location == "home"`. They are stamped ACTIVE + `away` + `away_ble_silent_only`.
*Falsified by* any reachable input of that shape that produces `location == "home"` (e.g. the 10-24
tuple: `person.state=home`, gps=home, wifi=MISSING, both BLE trackers `not_home`).

**INV-2 (no new away from no evidence; GPS missing never blocks away).** The new away stamp fires
**only** on affirmative BLE `not_home` from the person's own trackers. If any of the person's BLE
trackers is `home`, `unknown`, `unavailable`, `restored`, or the person has none, behaviour is
**byte-identical to today**. I-α is preserved: no `no_signal` row changes. GPS being MISSING/unknown
never adds a home witness, so it can never block away.
*Falsified by* any input where a BLE tracker is unknown/unavailable/absent and the stamp differs from
`develop`.

**INV-3 (toggle restores today).** With the switch OFF, every person stamp is byte-identical to
`develop` for every input.

**INV-4 (BLE visibility still wins).** A Bermuda room fix (S1) and the STALE hold (#2) are unchanged;
the new rule runs only inside the two `_ps_state == "home"` arms.

---

## 4. The rule — what "assistive" means, per row and at the gate

**The one change:** in both `_ps_state == "home"` arms (`person_coordinator.py:734` and `:832`),
before forcing ACTIVE+home, evaluate one predicate:

```
gps_home_overruled = (
    ble_leads_enabled                       # switch, default ON
    and sources["wifi"] != "home"           # no non-GPS home witness
    and own_ble_trackers_all_not_home(person_state)   # >=1 bluetooth_le tracker, all not_home, none restored
)
```
If true → take the existing S3 away arm verbatim (ACTIVE, `away`, `_person_lost_since` /
`_lost_away_since` stamped, `_person_was_away = True`) with `tracking_reason = "away_ble_silent_only"`
and confidence `BLE_SILENT_ONLY_AWAY_CONFIDENCE`. `tracker_sources` is published unchanged
(it will show `gps: home`, which is the diagnostic that GPS was overruled). If false → today's code.

### Per-row table (default mode). "own BLE away" = INV-1's tracker condition.

| Row / case | GPS | WiFi | own BLE trackers | Today | Default mode (switch ON) | Change? |
|---|---|---|---|---|---|---|
| S1 row 1 | any | any | Bermuda room fix | room, ACTIVE | same | no |
| STALE hold | any | any | fix < 300 s ago | last room, STALE | same | no |
| 2 / 3 | home | home | any | home 0.85/0.80 | same (WiFi is a non-GPS witness) | no |
| 4 | home | not_home | all not_home | home 0.5 (anomalous_gps_stale_local_gone) | **away, away_ble_silent_only 0.82** | **yes** (two away witnesses beat one stale GPS) |
| 4 | home | not_home | any home / unknown / none | home 0.5 | same | no |
| 10 | home | MISSING/unavail | all not_home | home 0.75 (**10-24 case**) | **away, away_ble_silent_only 0.82** | **yes** |
| 10 | home | MISSING/unavail | any home / unknown / unavailable / restored / none | home 0.75 | same (GPS corroborates when BLE has no opinion) | no |
| person.state home, GPS unknown/MISSING | unk | ≠home | all not_home | home 0.75 (fallback :435) | **away** | **yes** (home had no witness at all) |
| 6 / 9 / 8 / 11 / 13 | away | any | any | away (or row 8 GPS-lag home via WiFi) | same: **GPS away still hastens away** | no |
| 14 | MISSING | MISSING | Bermuda silent + liveness | away 0.82 | same | no |
| 16 / S6 | — | — | — | LOST no_signal / entity_missing | same (I-α) | no |

**What GPS still does (assistive):** (1) GPS `away` moves a person away in ~30 s median (card probe)
when BLE has lost them, i.e. it hastens away; (2) GPS `home` holds a person home when BLE has **no
opinion** (trackers unknown/unavailable/restored/absent: BLE fleet down, integration reloading,
person with no BLE tracker). (3) It never holds home against the person's own BLE saying `not_home`.

**Why the evidence is the person's own BLE trackers, not `_ble_fleet_live` (deviation, justified).**
`_ble_fleet_live` (#7) proves liveness only through *another* resident being visible, so it is False
exactly when the last resident leaves, which is the case we must fix. The `bluetooth_le` trackers are
the same evidence HA's `person` entity already uses as the sole source for Jaya and Ziri, so adopting
it for app users adds no failure class the house does not already carry for half its residents. A
dead BLE fleet shows as trackers `unavailable`/`unknown` (→ no change, INV-2), or, if proxies die
while the integration stays up, as `not_home` for everyone, which already moves the kids away today.
The `restored` exclusion covers the boot window, where HA restores trackers before BLE has scanned.

**Deviations from existing semantics, each justified:**
1. *Case-(b) pin narrowed* (`PLANNING_path_alpha_lost_dissolution.md:39,156`: GPS home ⇒ never away).
   That pin protects a phone on a charger with cold Bermuda. A charging phone at home still advertises,
   so its `private_ble_device` reads `home` → no change. The pin is narrowed only when BLE affirmatively
   says the phone is gone. The case-(b) "never LOST" half is untouched; we produce ACTIVE-away, not LOST.
2. *Row 4 moves from home 0.5 to away.* GPS home vs WiFi not_home was "defer" with home forced; adding
   BLE not_home makes two of three axes say away.
3. *No new status, no new tracking_reason, no new confidence.* `away_ble_silent_only` is reused because
   it is literally what happened (BLE silent → away). A distinct reason was considered and rejected:
   it adds vocabulary to `TRACKING_REASON_VALUES`, to the D3 `tracking_reason=` exclusion parser and
   to dashboards, for a diagnostic already visible in `tracker_sources.gps == "home"`.

**Timing.** Leaving with a frozen GPS: Bermuda area clears → STALE 300 s → person-state branch → away
on the first tick where both BLE trackers read `not_home` (HA's own BLE timeout, a few minutes). Expect
~5-10 min, against "never" today. GPS that updates still wins the race (~30 s).

---

## 5. D0 — measure-before-build probe (RUN 2026-10-24, read-only)

Method: `ssh ha "python3 -" < script` against `home-assistant_v2.db` (read-only URI). Window =
recorder retention, 2026-10-17 04:12 → 2026-10-24 18:47 CDT (7.6 days). Sources:
`sensor.universal_room_automation_<p>_location` (state + `tracking_reason` + `tracker_sources`, URA's
own decision record), raw BLE trackers (`device_tracker.private_ble_device_8ce182`,
`device_tracker.iphone_oji_bermuda_tracker`, `device_tracker.ezinne_iphone`,
`device_tracker.ezinne_iphone_bermuda_tracker`), GPS trackers
(`device_tracker.phalanxiphone15promaxcflare`, `device_tracker.zinny_s_iphone_15`). Scripts kept in the
session scratchpad (`probe3.py`, `probe4.py`); re-runnable.

Live tracker inventory: Oji = phone GPS + `private_ble_device_8ce182` + Bermuda tracker (+
`gold_macos_client`, source_type gps, reads `unknown`, never beats a real reading); Ezinne = phone GPS
`zinny_s_iphone_15` + BLE `ezinne_iphone` + Bermuda tracker; Jaya = BLE only; Ziri = one BLE tracker
`ziri_iphone` that is almost never seen (Bermuda area sensor 21 rows in 7 days, all unknown).

### (b) How often GPS overrides BLE-silent to home today
URA location = `home` with `tracker_sources.gps == "home"` (the S2/row-10 override), segments ≥ 2 min:

| Person | Segments | Minutes in 7.6 d | Raw BLE during them |
|---|---|---|---|
| Oji | **13** | **1,132 min (18.9 h)** | both BLE trackers `not_home` for ≥ 95% of every segment except two short ones (10-20 17:47 5 min, 10-22 09:17 8.5 min, BLE home ~50%) |
| Ezinne | 1 | 2 min | BLE home 100% (harmless) |
| Jaya / Ziri | 0 | 0 | no GPS |

Oji's segments (start CDT, length, GPS age at start): 10-19 09:37 8.5 m; **10-19 17:50 104 m (GPS 103 m
old)**; 10-20 07:26 55.5 m; 10-20 22:21 5 m; 10-21 07:30 42 m (GPS 332 m old); 10-22 16:45 77 m;
10-22 19:28 23.5 m; **10-23 11:32 152 m**; 10-23 17:33 45.5 m (GPS 354 m old); 10-24 08:45 85.6 m;
**10-24 10:10 → ongoing 520 m (the reported incident)**. Most segments contain 0-3 GPS updates; all sit
at commute / errand hours, none overnight. Every closed segment ended with a Bermuda room fix
(he came home). Ezinne's GPS behaves: her trips show as `away_gps_only` within minutes.

Reading: the frozen/lagging-GPS home is **not a one-off**. It held Oji home for ~19 h in a week, on
11 of 13 occasions while his own BLE said `not_home` the whole time.

### (a) "Prove I have to care": a resident at home but BLE-silent long enough to be marked away
Proxy for "at home" (no ground truth exists): BLE-silent episodes ≥ 5 min that start overnight
(23:00-06:00, residents presumptively home).

| Person | BLE-silent episodes ≥ 5 min, overnight | Daytime episodes |
|---|---|---|
| Oji | **0** | the 13 above (GPS-held) + 4 away segments |
| Ezinne | **0** | 7 (all with GPS away: real trips) |
| Jaya | **0** | 11; weekday 07:2x → ~18:00 (school) and evenings; already marked away today by the existing BLE-led path |
| Ziri | n/a | BLE never resolves him; stamped away all week by `away_ble_silent_only` / `away_wifi_only` (pre-existing, see §9 Q4) |

So in 7.6 days there is **no observed case of a resident at home overnight going BLE-silent for 5 min**.
Daytime truth for Oji's 13 segments is not provable from the recorder (GPS is the thing in question);
the timing pattern says real outings. The operator is the oracle for those (Q1). Jaya's daily school
episodes show the BLE-led away path already works with no complaints.

**Go/no-go:** GO. The risk the rule adds (a resident at home with phone BLE dark for minutes) has zero
overnight occurrences; the defect it removes cost ~19 h of wrong "home" in a week.

---

## 6. Producer and consumer checks

**Producer** — `person_coordinator.data[person]["location"]` / `tracking_status` / `tracking_reason` /
`confidence`, from the branches in §2 #1-#5. Dependencies and health today: Bermuda area sensors
(healthy for Oji/Ezinne/Jaya; dead for Ziri); `bluetooth_le` trackers (healthy, `home` the large
majority of rows; Oji `not_home` 23 transitions/week); GPS trackers (Oji's freezes / lags as measured;
Ezinne's healthy); HA `person` aggregation (prefers GPS; not URA's to change).

**Consumers of `location` (the value whose meaning changes from `home` to `away` in the new rows):**

| Consumer | file:line | Trust / display | Effect of the change |
|---|---|---|---|
| Path α denominator | `presence.py:6346-6393` → engine `:1229` | **trust** | Oji counted away → α can fire (still needs unidentified 0, face 0, cameras OK). Intended. |
| Census BLE-home list | `camera_census.py:2670-2687` (`_get_ble_persons`), used `:1714` | **trust** (feeds `census_count` → nobody-home `presence.py:1126`, guest gate) | Drops the frozen-GPS person from census → nobody-home can fire; GUEST arithmetic loses a phantom resident (good: fewer phantom residents never hurt the guest gate). |
| Path β | `presence.py:1053-1072` | trust | Unchanged (ACTIVE, not LOST). |
| HVAC | via `SIGNAL_HOUSE_STATE_CHANGED`; Wait-for-Presence consensus phones term; `hvac.py:1228-1236` syncs pre-arrival to person_coordinator | trust (indirect) | House can go AWAY → away presets; consensus phones term shifts. HVAC code unchanged. |
| BLE pre-arrival | `person_coordinator.py:601-638` | trust | Now armed after a frozen-GPS departure → `SIGNAL_PERSON_ARRIVING` on BLE return (correct; it never fired before). A ≥15 min daytime BLE dropout at home would also fire it (accepted; Q3). |
| Security / NM persons_home | `aggregation.py:2070-2090` (`persons_home` attr), NM targeting | display + routing | Person listed away. |
| Zone persons_home reliable signal | `aggregation.py:4494, 4634` | trust (zone veto) | Fewer false "person home" vetoes. |
| fan_veto / fan recheck / room coordinator BLE limbs | `fan_veto.py:296-320`, `presence_fan_recheck.py:672, 1168`, `coordinator.py:4060-4075, 4615-4620` | trust | Read `get_persons_in_room` (room strings); `home`/`away` are not rooms → **no effect**. |
| Music following, transitions, DB snapshot | `music_following.py:597-713`, `transitions.py:158+`, `person_coordinator.py:889-907` | display/history | Snapshot rows say `away` instead of `home`. |
| Person location sensor | `aggregation.py:5700-5760, 6038-6064` | display | Shows Away + reason `away_ble_silent_only`, sources `gps: home`. |

## 7. Emission / decision-site enumeration

Sites that force or decide `location="home"` from `person.state` (grep `_ps_state == "home"` and
`state_str == "home"` in `person_coordinator.py`):
1. `:734-761` Bermuda-exists-no-room arm — **change** (predicate before the force).
2. `:832-849` no-Bermuda-sensor arm — **change** (same helper; missing it = Bug Class #53).
3. `:435-437` matrix fallback `state_str == "home"` — reached only with GPS not home and WiFi not home;
   its result is then overwritten by site 1/2 anyway, so it is covered by the predicate at 1/2.
   **No edit**; a test pins it (`test_fallback_home_without_witness_overruled`).
4. Matrix rows 2/3/4/10 (`:381-392`) — produce the stamp that sites 1/2 then force; **no edit** (the
   predicate acts at 1/2 so the matrix stays a pure function of axes, as today).
5. S1 / STALE (`:523-695`) — **no edit** (INV-4).

---

## 8. Deliverables

### D0 — Probe (DONE, §5)
Numbers recorded above. Scripts in the session scratchpad; the builder may copy them to
`scripts/probes/presence_gps_override_probe.py` for the post-deploy re-run.

### D1 — The gate (person_coordinator.py, two sites, one helper)
- New method `_own_ble_trackers_all_not_home(person_state) -> bool`: iterate
  `person_state.attributes["device_trackers"]`; keep entities whose state attributes have
  `source_type == "bluetooth_le"`; return True iff ≥1 kept, every kept state is exactly `not_home`, and
  none has attribute `restored` truthy. Any exception → False (fail to today's behaviour).
- New method `_ble_leads_enabled() -> bool`: read `presence._ble_leads_enabled` through the
  `coordinator_manager` pattern at `:614-619`; presence missing or attribute missing → **True**
  (the default). Exception → True.
- At sites 1 and 2: if `_ble_leads_enabled() and _sources["wifi"] != "home" and
  _own_ble_trackers_all_not_home(person_state)` → execute the existing S3 away arm (factor the arm's
  body into a local helper used by the else-arm and the new path so the side effects cannot drift),
  then set `tracking_reason = "away_ble_silent_only"`, `confidence = BLE_SILENT_ONLY_AWAY_CONFIDENCE`.
- One DEBUG log line per transition into the overruled state (not per tick).

**Acceptance criteria**
- **Verify:** 10-24 tuple (`person.state=home`, GPS tracker `home`, no WiFi tracker, both BLE trackers
  `not_home`, Bermuda area `unknown`) → `location="away"`, `ACTIVE`, `away_ble_silent_only`, 0.82,
  `tracker_sources.gps == "home"`, `_person_was_away` True.
- **Verify (discriminating):** same tuple with ONE BLE tracker `home` → `location="home"` (proves the
  rule keys on BLE `not_home`, not on GPS age or on BLE silence in Bermuda). Same tuple with a BLE
  tracker `unavailable` → `home` (INV-2). With `restored: true` on the BLE trackers → `home`.
- **Verify:** WiFi tracker `home` + GPS home + BLE not_home → `home` (rows 2/3 untouched).
- **Verify:** person with no `bluetooth_le` tracker and `person.state=home` → `home`.
- **Verify:** both sites (Bermuda-exists and no-Bermuda) behave identically.
- **Verify:** matrix outputs (`_classify_matrix_row`) unchanged for all 16 rows (existing row fixtures pass unmodified).
- **Test:** `test_person_gps_assistive.py::test_frozen_gps_home_ble_not_home_goes_away`,
  `::test_one_ble_tracker_home_keeps_home`, `::test_ble_unavailable_keeps_home_ialpha`,
  `::test_ble_restored_keeps_home`, `::test_wifi_home_witness_keeps_home`,
  `::test_no_ble_tracker_keeps_home`, `::test_row4_two_away_witnesses`,
  `::test_fallback_home_without_witness_overruled`, `::test_no_bermuda_branch_twin_site`,
  `::test_side_effects_match_s3_arm` (lost_since / lost_away_since / was_away),
  `::test_pre_arrival_fires_on_ble_return_after_overrule`.
- **Mutation (framing C):** neuter site 1 → `test_frozen_gps_home_ble_not_home_goes_away` RED; neuter
  site 2 → `test_no_bermuda_branch_twin_site` RED; drop the `restored` check → `test_ble_restored_keeps_home`
  RED; drop the WiFi witness check → `test_wifi_home_witness_keeps_home` RED.
- **Live:** next time Oji leaves with the phone, within ~10 min `sensor.universal_room_automation_oji_udezue_location`
  reads Away with `tracking_reason: away_ble_silent_only` and `tracker_sources.gps` possibly `home`;
  if he is the last resident out, the house-state sensor's `last_away_branch` records the AWAY
  (`active` or `nobody_home`). Re-run the D0 probe 24 h after deploy: GPS-home segments with both BLE
  trackers `not_home` > 10 min = **0** (was 11 of 13).

### D2 — Toggle `switch.ura_presence_ble_leads_home_away` (rung 3)
- `PresenceBleLeadsEnabledSwitch(_PresenceKillSwitchBase)`: `_unique_slug = "presence_ble_leads_enabled"`,
  `_friendly_name = "BLE Leads Home/Away"`, `_backing_field = "_ble_leads_enabled"`,
  `_since_field = "_ble_leads_suppressed_since"`, icon `mdi:bluetooth`. Register next to its siblings.
- PresenceCoordinator: `self._ble_leads_enabled: bool = True`, `self._ble_leads_suppressed_since = None`
  next to `_away_veto_enabled` (`presence.py:1780`).
- Docstring / description (label style guide): **"BLE Leads Home/Away — On: a phone's Bluetooth
  decides home or away; GPS can only speed up leaving. Off: a GPS 'home' also counts as proof, for
  homes with few Bluetooth scanners or heavy app use."** Kill-switch semantics: OFF = today's behaviour.
- Why rung 3: per-home policy the operator may flip by observation (Wigton-style sparse BLE), no review
  needed to flip, both positions are safe.
- Why default ON and the inverted name: the operator's "GPS as proof, default OFF" maps to this switch
  OFF; naming it in the positive-default sense lets it reuse `_PresenceKillSwitchBase` (default ON,
  restore, deferred restore) unmodified instead of adding a default-OFF variant.

**Acceptance criteria**
- **Verify:** switch OFF → the 10-24 tuple yields `home` (INV-3); full existing person/presence suites
  green with the switch OFF.
- **Verify:** OFF survives restart (RestoreEntity) including the deferred-restore path.
- **Test:** `test_person_gps_assistive.py::test_switch_off_restores_gps_proof`,
  `test_presence_kill_switches.py` (extend the parametrized sibling list) `::test_ble_leads_restore_and_deferred`.
- **Mutation:** ignore the switch in `_ble_leads_enabled` → `test_switch_off_restores_gps_proof` RED.
- **Live:** entity exists, state `on`, attribute `suppressed_since` absent; toggling OFF then ON
  with Oji away-with-frozen-GPS moves his location Home then Away within one person tick.

### D3 — Docs (same commit)
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §3: add "GPS assistive (BLE leads)" paragraph with the rule,
  switch and the two sites. §10 corrections ledger, new entries:
  - "BLE-only away at 0.82 cannot flip the house because path α needs 0.9" (`person_coordinator.py:423-425`)
    — WRONG: path α ignores confidence (`presence.py:6388`); kids vote away on row 14 today.
  - "Fleet liveness gates BLE silence for everyone" — INCOMPLETE: it is proven only by another
    resident's Bermuda fix, so the last resident out is always `indeterminate` (`:297-341`).
  - §2 step 0 says `census_count` includes BLE-located residents; it actually includes any person whose
    `location` is not away/unknown, including a GPS-forced `home` (`camera_census.py:2683-2685`).
- Fix the code comment at `person_coordinator.py:423-425` to state what is true (no confidence threshold
  downstream). Comment-only.
- Update the card with the D0 numbers.

**Acceptance:** doc diff reviewed in the same PR; `grep -n "0.9" person_coordinator.py` no longer claims a path-α threshold.

---

## 9. Non-goals
- No HA changes (person entities, trackers, zones, companion app settings).
- No GPS age / freshness knob. Considered and rejected: a GPS timeout still lets a frozen fix hold a
  person home for the timeout, needs a number nobody can measure well (iOS update cadence varies), and
  BLE `not_home` is better evidence that is already present.
- No change to `_ble_fleet_live`, the 16-row matrix, row 14, I-α, STALE, path β, phone-left-behind,
  `TRACKING_REASON_VALUES`, confidence values, or the WiFi axis.
- Not enforcing the 0.82 < 0.9 comment (would break the kids' away path).
- Ziri never being BLE-resolved (Bermuda area 21 rows/week, all unknown) is pre-existing and out of
  scope; flagged as Q4.
- No new trip-wire: the operator ruled he does not need to care about BLE misses at home.
- No HVAC, census, or camera code changes.

## 10. Tier
**Tier 2, elevated to 3 framing-disjoint reviews (Tier 2-DB protocol)** per the standing
regression-prone policy: presence → house state → HVAC / census / security ripple, and it narrows a
long-standing operator pin (case-(b)). Not Tier 3: one decision gate at two sites, additive, fail-safe
to today's behaviour on every non-matching input, with a kill switch. One plan review before build.
Suggested build-review framings: **A** correctness + every axis combination at the two sites
(incl. restored/unavailable/no-BLE persons, row 4); **B** cross-coordinator ripple (census, α /
nobody-home, HVAC away, pre-arrival, guest gate) + restart/boot (restored trackers, switch deferred
restore); **C** per-site source mutation (the four drills in D1/D2).
Builder: `ura-builder`. Risk for deploy ranking: MED (changes when the house goes AWAY).

## 11. Open questions for the operator
1. **Oracle check on the probe:** were you out of the house on 10-19 17:50-19:34, 10-22 16:45-18:02 and
   10-23 11:32-14:04? (BLE said gone, GPS said home.) If yes, all 13 are frozen-GPS holds.
2. Row 4 (GPS home, WiFi off, BLE gone) also flips to away. No live person has a WiFi tracker today, so
   this is dormant here; OK to include?
3. A daytime BLE dropout ≥15 min while you are home would now fire the BLE pre-arrival signal on
   reconnect (HVAC pre-arrival). Accept, or should the overruled stamp skip `_person_was_away`?
   (Plan default: set it, because a real frozen-GPS departure needs pre-arrival on return.)
4. Ziri's only tracker (`ziri_iphone`) is effectively never seen, so URA has had him away all week.
   Separate card?
