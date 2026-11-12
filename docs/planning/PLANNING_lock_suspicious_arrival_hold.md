# PLANNING: hold only suspicious arrivals at the lock regime (stale-source home edges)

Card: GARAGE-REMOTE-LOCKOUT-SCHEDULE-1 residual (`INSTANCE_2026_11_12_blip_release_gap`,
`operator_decision_2026_11_12_blip`, `measured_2026_11_12_arrival_gap`).
Status: rev 1, pre-plan-review. Planner run 2026-11-12. No code, no commit, no board edit.

Operator bar: *"Feeling locked out is a nasty feeling and makes URA feel completely unreliable."*
Real arrivals must stay instant; only suspicious ones may wait.

Read in full before writing: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (all of
§0-§11, corrections ledger §10 #1-#32), `docs/architecture/SENSOR_FLEET_CLASSES.md`, and the lock
sections of `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (§1.1 S8 hold-off note at :98-103,
the SC lock regime face-arrival block at :499-507). Nothing here re-asserts a ledger claim. One
presence-doc statement this cycle changes (and must update in the same commit): §1 table, away lock
"RELEASE whenever a listed person reads `home` (any reading, restored state and short blips
included, no blip gate)".

---

## 0. Summary

- **Measured (§2):** 118 person `not_home -> home` edges 11-05..11-12. 78 are sub-second blips
  (all Oji, max 1.17 s). The best discriminator is not "a tracker dropped out" (the card's chosen
  rule) but **"the person's `source` tracker did not itself change at the edge"**: real arrivals
  have source-tracker age 0.0003 s or less; blips have 4,119 s or more. That rule holds 0 of 40
  real arrivals and catches 78 of 78 blips. The card's dropout-only rule would have held one real
  arrival (Ezinne 11-12 11:29:29, app tracker `unavailable -> home`).
- **New leak found (§2.3):** the proximity release (P5) is also fed by the blips. HA's proximity
  sensor jumped to 0 ft on 49 of the blips (the iPad's home coordinates), and each is a
  `> 1500 m -> <= 1500 m` crossing that calls `_release`.
- **Config already closed the mechanism (§1.1):** the 11-11 trim left every person with at most
  one GPS tracker. Under HA's person rule, a fallback to a stale `home` then needs a second GPS
  tracker, so it cannot happen with today's tracker sets. The code is a guard against
  re-introducing it (an iPad or Mac added to a person; other installs). It is small, and the lockout
  is still off, so it costs nothing to ship before the lockout goes on.
- **Design (§5):** one pure predicate, `stale_source_arrival`, in `arrival_edges.py`. A suspicious
  edge is held for `H` seconds, and the hold covers the full person-edge body. A revert inside the
  hold cancels the edge and its revert as a pair, with no state change. At `H`, if the person still
  reads the held state, the edge is replayed through the normal path. The signal path (P2
  geofence/ble), proximity (P5) and face corroboration see the same hold. Knob
  `number.ura_garage_lockout_arrival_hold` (default 5 s, 0 = off).
- **Tier:** 2, elevated to 2-DB review (3 framings) under the standing regression-prone policy,
  plus Tier-3-style per-site mutation drills (the failure mode is one missed site).

---

## 1. Institutional context verified

### 1.1 Config-first check (done before any design)

| Lever | Live value (REST, 2026-11-12) | Fixes it? |
|---|---|---|
| `switch.ura_security_coordinator_garage_lockout` | `off` | Lockout off, so nothing releases today. Not a fix. |
| `switch.ura_security_coordinator_away_lock` | `off` | Same. |
| `number.ura_garage_lockout_approach_radius` | `1500.0` | 0 disables P5 entirely (loses real early release). Not a fix. |
| Person tracker sets (`/config/.storage/person`) | oji: phone(gps) + 2 BLE; ezinne: app(gps) + 2 BLE; ziri: 2 BLE; jaya: 2 BLE | **Yes, for this house today.** HA `person._update_state` (`.venv-ha/.../person/__init__.py:516-559`): any non-GPS `home` wins, else the latest GPS, else the latest not_home; unavailable is ignored. With one GPS tracker, a GPS dropout falls back to BLE, and a BLE `home` there means the person was already home. The stale-home fallback needs **two GPS trackers**, which is the iPad case the 11-11 trim removed. |

Verdict: the config change already stops the measured mechanism here. Code is still warranted as a
**guard**, not a fix:
1. Adding a second GPS device to a person (an iPad, a Mac, a new phone before the old one is
   removed) silently re-opens an unlock path on a door lock.
2. Portability is a standing imperative (memory `feedback_portability_imperative`).
3. A non-blip variant exists that config cannot catch: a stale GPS tracker's attribute-only update
   (e.g. battery) bumps its `last_updated` above the phone's, and HA picks it. The person then reads
   `home` from a source whose state changed hours ago, possibly for minutes (§9 R1).

Marginal-benefit check (§8) recommends the simple rule. The fancier rule set is parked.

### 1.2 Prior-art scan: REUSE or BUILD

Greps run (2026-11-12, develop `dab556d5`):
`grep -rn '"source")' custom_components/` (2 hits: `camera_census.py:6083` builds a family tracker
set; `security_lock_regime.py:986` is the signal payload, not the person attribute);
`grep -n "^def " arrival_edges.py`; `grep -n "GARAGE_LOCKOUT_\|CONF_GARAGE_LOCKOUT" const.py`;
`grep -n "blip" const.py`; `grep -n "garage_lockout_reengage" __init__.py number.py`;
`grep -rn SIGNAL_PERSON_ARRIVING` (producers `presence.py:5281-5299` geofence, `:5628-5638`
camera_face, `person_coordinator.py:1127-1135` ble; consumers `security.py:817` -> `:2389-2393` ->
lock regime, `hvac.py:1511`, `music_following.py:281`).

| Piece | Verdict | Where |
|---|---|---|
| Edge classifier (stale source) | **BUILD, small**, a pure function in the EXISTING shared module | `arrival_edges.py` (holds `live_arrival_slug` :33, `nonface_arrival_source` :128). No existing reader of `person.attributes.source` age anywhere (grep above). |
| Person edge listener | REUSE | `security_lock_regime._on_person_event` :1097-1138 (refactored into a body function, §5.2) |
| Away-lock person edge | REUSE | `_away_on_person` :1885-1928 (called from the same body) |
| Signal path P2 | REUSE + one gate | `on_person_arriving` :975-1005, `_apply_arrival` :1007-1020 |
| Proximity P5 | REUSE + one gate | `_on_distance_event` :1309-1328 |
| Face corroboration stamp | REUSE, moved to confirm time | `_arrival_edges[slug] = now_ts` :1120-1122 (via `live_arrival_slug`) |
| Timer primitive | REUSE | `self._call_later` (injected, :170-183), the same as re-engage/backstop; teardown pattern in `async_teardown` :653 |
| 15-min blip rule | REUSE unchanged | `_really_away` :1145-1157, `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` `const.py:3774` (rung 1, stays) |
| Hold-seconds knob | **NEW** `CONF_GARAGE_LOCKOUT_ARRIVAL_HOLD_S` | No hold/dwell knob exists for the regime (const.py:3736-3776 is the full lockout block). Pattern REUSED: `_SecurityLockoutNumber` `number.py:4415-4433`, builder `:4436-4480`. Must also be added to `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:7397`) and `_NO_LIVE_ATTR_KEYS` (`__init__.py:7704`). Missing either one reloads the CM on every knob turn. |
| Stale-source bound | **NEW** rung-1 `LOCK_ARRIVAL_STALE_SOURCE_S` | Classifier boundary, not policy (§6). |
| Reverts-within-N "blip" classifier elsewhere | None | `grep blip const.py` shows only fan/PIR/Bermuda-hallway uses, none on person edges. |

Prior plans consulted: `PLANNING_sc_garage_remote_lockout.md` (P1-P5 arrival paths, H3a 15-min
rule, M-2 boot exceptions), `PLANNING_sc_lock_exclude_and_door_regime.md` (away lock: "release on
ANY home reading, releasing is fail-safe" A1), `PLANNING_ble_seen_at_home_arrival.md` (geofence =
first arrival signal), `AUDIT_ble_arrival_d0_probe.md`, `AUDIT_arrival_to_garage_open_gap.md`.
Memory bodies: `feedback_portability_imperative`, `feedback_alert_latency_over_precision` (release
latency matters), `feedback_marginal_benefit_pushback`, `feedback_measure_before_build`.
Parked sibling: `LOCK-REGIME-BOOT-REALLY-AWAY-1` (boot-window `_really_away` True). Not absorbed;
see §7.

Code read end-to-end for this plan: `security_lock_regime.py` :150-268, :586-660, :774-852,
:940-1370, :1440-1470, :1875-1932, :2130-2162, :2266-2358; `presence.py` :5258-5300, :9460-9476;
`security.py` :805-830, :2380-2420; `const.py` :3736-3776; `number.py` :4415-4480; HA
`person/__init__.py` :516-559.

---

## 2. Measurement (done; this is the go/no-go gate)

Read-only probe over the recorder (`ssh ha`, `/config/home-assistant_v2.db`, `states` +
`state_attributes`, window 2026-11-05 04:12 to 2026-11-12 ~14:30 CST). Tracker sets come from
`/config/.storage/person`, plus every tracker that appeared as a person `source` (this brings back
Oji's trimmed `okosisipadmini6_2`). Script: scratchpad `probe/p2.py`. The build commits it as
`scripts/probes/lock_arrival_edge_probe.py` (D0).

Per edge: `blip` = the person left `home` again within 10 s. `src_age` = person edge ts minus the
`last_changed` of the source tracker's current state. `unav_ago` = seconds since ANY of the
person's trackers last went `unavailable`/`unknown`.

### 2.1 Edges

| person | edges | real | blip (<10 s) | blip source |
|---|---|---|---|---|
| oji_udezue | 86 | 8 | 78 (max 1.166 s, typical 20-150 ms) | `okosisipadmini6_2` (gps, stale `home`) |
| ezinne | 16 | 16 | 0 | - |
| jaya | 9 | 9 | 0 | - |
| ziri | 7 | 7 | 0 | - |
| **total** | **118** | **40** | **78** | |

Every real edge's source tracker went to `home` at the edge (src_age at most 0.0003 s): gps 19,
bluetooth_le 21. Every blip's source tracker had last changed 4,119 s to 280,000 s earlier, and in
every blip another tracker (the phone) went `unavailable` at the same instant.

### 2.2 Confusion matrix (real held must be 0)

| Candidate rule (hold the edge iff ...) | real held | blips caught |
|---|---|---|
| every edge (flat hold, the 11-12 first proposal) | 40/40 | 78/78 |
| (a) any own tracker went unavailable/unknown within 1 s | **1/40** | 78/78 |
| (a) ... within 2 s / 5 s / 10 s | **1/40** | 78/78 |
| (b) source tracker is `source_type: gps` | 19/40 | 78/78 |
| **(c) source tracker's state unchanged for > M s at the edge (or source unknown), M = 1..600** | **0/40** | **78/78** |
| (c, M=60) AND (a, N=2) | 0/40 | 78/78 |

The (a) false hold is Ezinne 11-12 11:29:29. Her app tracker `zinny_s_iphone_15` went
`unavailable -> home` and drove a real arrival; (a) sees the dropout 0.05 s earlier and holds it.
The card's "dropout-only" decision is therefore **refuted by the data** and replaced by (c).

**Margin for (c):** real max src_age 0.0003 s, blip min 4,119 s, a gap of more than seven orders of
magnitude. `M = 10 s` sits about 33,000x above the real max and about 400x below the blip min. The
AND-combination adds nothing on this data and adds a second axis to get wrong, so it is not used.

Hold length `H`: the blip max is 1.17 s. `H = 5 s` gives 4.3x margin. Under (c), H costs nothing on
real arrivals (none are held), so the 1.9 s arrival-to-door minimum from
`AUDIT_arrival_to_garage_open_gap.md` no longer limits H.

### 2.3 Proximity (P5) is a third leak path

`sensor.madronehaos_oji_udezue_distance` (unit ft; exists since 11-07 ~12:00). Crossings from
> 4,921 ft (1,500 m) to <= 4,921 ft: **52**. **49** coincide to the millisecond with a blip edge and
read `0.0` (iPad coordinates), then return to the far value 20-70 ms later. The other 3 are real
(11-07 12:13:13 at 978 ft, 36 s **before** the person edge; 11-07 18:11:28; 11-08 13:58:39 at
52 ft, 12 s before the edge). So P5 legitimately leads the person edge on real arrivals and must
not be delayed when the person does not read `home` on a stale source.

### 2.4 Other paths checked

- House state: URA `house_state_log` 11-05..11-12 has 0 transitions with trigger `geofence_*`
  (triggers seen: periodic 41, census_update 29, deferred_retry 14, occupancy_change 8). No
  house-state release (`house_state:arriving` / HOME_*) was driven by a blip. Reasoning:
  `handle_geofence_event` schedules inference as a task (`presence.py:9471`), which reads state
  after the 20-150 ms blip has usually reverted. Not proven impossible; see §9 R3.
- Lock history over the 78 blip windows (D0 audit §3): no garage or exterior lock changed. The
  lockout and away lock were off.

---

## 3. Falsifiable invariants

- **INV-H1 (no blip unlock).** With `H > 0`: for ANY reachable path (P1 person edge, approach
  zone, away-lock person release, P2 `SIGNAL_PERSON_ARRIVING` geofence/ble, P2 camera_face via
  corroboration, P5 proximity), a person `home` (or zone) reading whose `source` tracker's state is
  older than `LOCK_ARRIVAL_STALE_SOURCE_S` at the person edge, and which reverts within `H`
  seconds, never causes `_release` or `_away_release` to issue an unlock, never stamps
  `_arrival_edges`, and never moves `_last_real`, `_away_not_home_since`, `_away_attempted`,
  `releasing_set` or `release_gen`.
  *Break it by:* finding any site that reads raw `person.state`, a `home` edge, or the arriving
  signal and reaches `_release` / `_away_release` without passing the predicate.
- **INV-H2 (reliability: real arrivals never wait).** An edge whose source tracker changed at the
  edge (age <= M) issues its release in the same callback as on develop. Replay: all 40 real edges
  release with 0 s added delay, and all 3 real proximity crossings release at the crossing.
- **INV-H3 (clean cancel).** A held edge followed, inside H, by an event back to the pre-edge
  state leaves the regime's state equal to a run in which neither event happened (the fields listed
  in INV-H1, plus no timers left).
- **INV-H4 (off = develop).** `H = 0` is byte-identical to develop on every path (golden replay).
- **INV-H5 (confirm = the original edge).** A held edge that still reads its state at H produces
  exactly the effects the same edge produces on develop, with stamps carrying the edge ts.

---

## 4. Producer / consumer map

### 4.1 Producers

| Value | Producer | Arithmetic / dependency health |
|---|---|---|
| `person.<x>.state` + `attributes.source` | HA `person._update_state` (:516-559) | Non-GPS home wins; else the latest GPS by `last_updated`; unavailable ignored. **Unhealthy case:** a stale second GPS tracker becomes the source when the fresher one drops (measured 78x) or when its attributes refresh (§9 R1). `source` is a recorded attribute (verified in `states`). |
| tracker `last_changed` | HA core state machine | Changes only when the state string changes; attribute-only updates move `last_updated` only. That is why (c) uses `last_changed`. HA restore rewrites `last_changed` to boot time (presence doc §8, §1 table note on review A H1), so at boot every age is about 0 and the predicate reads "not suspicious" (fail-open, §9 R2). |
| `SIGNAL_PERSON_ARRIVING` geofence | `presence._handle_geofence_change` :5258-5299 | Fires on every person `-> home` from non-home, with no blip gate. Measured: 79 of 86 Oji edges produced a geofence row (D0 audit §1). |
| proximity distance | HA `proximity` | Derived from person coordinates; jumps to 0 on a stale-home blip (§2.3). |
| **NEW** `stale_source_arrival(states_get, person_id, stale_s) -> bool` | `arrival_edges.py` | True iff the person reads `home` or a zone (not `not_home`, not unreal) AND (`source` missing, OR the source has no state, OR `person.last_changed - source.last_changed > stale_s`). Pure, synchronous, reads `hass.states` only. |

### 4.2 Consumers of the arrival (every site that can unlock), all in `security_lock_regime.py`

| # | Site | Line | Effect | Trust | Covered by |
|---|---|---|---|---|---|
| S1 | `_on_person_event` resident `-> home` | :1126-1129 | `_release(person:)` garage | unlock | hold (D2) |
| S2 | `_on_person_event` approach zone | :1130-1132 | `_release(approach_zone:)` | unlock | hold (D2), same predicate (zone branch) |
| S3 | `_away_on_person` home branch | :1906-1922 (from :1135) | `_away_release(person:)` + pop `_away_not_home_since` + `_clear_attempted` | unlock | hold (D2), the whole body is deferred |
| S4 | `_arrival_edges` stamp | :1120-1122 | camera_face corroboration (`_face_arrival_corroborated` :1172) | unlock (indirect) | moved inside the deferred body, stamped with edge ts (D2) |
| S5 | `_last_real` update | :1136-1138 | feeds `_really_away` (P2, unavailable->home) | unlock gate | deferred body (D2) |
| S6 | `on_person_arriving` -> `_apply_arrival` geofence / ble | :975-1020 | `_release(arriving_signal)` + `_away_release` | unlock | live predicate gate (D3) |
| S7 | `on_person_arriving` camera_face | :997-1005 | same, after corroboration | unlock | via S4 (no blip stamp) + D3 gate |
| S8 | `_on_pc_update` held-face recheck -> `_apply_arrival` | :1231-1264 | same | unlock | D3 gate sits in `_apply_arrival`, so it covers S6/S7/S8 together |
| S9 | `_on_distance_event` crossing | :1309-1328 | `_release(proximity:)` | unlock | D4 |
| S10 | `_away_boot_discharge` | :1875-1883 | `_away_release(boot_recheck:)` on home at boot+120 s | unlock | NOT covered (restore ages are about 0; §9 R2) |
| S11 | `on_house_state_changed` ARRIVING / HOME_* | :774-852 | `_release(house_state:)` | unlock | NOT covered (0 measured, §2.4, §9 R3) |
| S12 | `_boot_recheck_regime` | ~:860-946 | release to match house | unlock | NOT covered (house-state driven) |

Non-lock consumers of the same blip (`hvac.py:1511` pre-arrival, `music_following.py:281`,
`security.py` expected-arrival sanction `:2410-2418`) are out of scope (§7). The predicate is
shared so that a follow-up can gate the producer.

---

## 5. Design

### 5.1 Predicate (D1)
`arrival_edges.stale_source_arrival(states_get, person_id, stale_s)`, as in §4.1. Unknown or
missing source counts as suspicious, because the measured 11-05 07:49:15 blip had no source
history. `stale_s` comes from `LOCK_ARRIVAL_STALE_SOURCE_S` (10.0).

### 5.2 Person-edge hold (D2): one deferral point for S1-S5
- Refactor the body of `_on_person_event` after the `old is None` return (:1117-1138) into
  `_process_person_edge(pid, old_val, new_val, edge_ts, cfg)`, unchanged. The listener calls it
  directly when not holding. This is the only way to hold S1-S5 together without five gates.
- In the listener, before the body: if `H > 0`, `new_val` is `home` or a non-`not_home` real state,
  `old_val != new_val`, and `stale_source_arrival(...)` is True, then record
  `self._held_edges[pid] = HeldEdge(old_val, new_val, edge_ts, unsub=call_later(H, confirm))` and
  return. Record `arrival_hold` in the snapshot counter. No other state moves.
- A later event for `pid` while a hold is pending:
  - `new_val == held.old_val` (the revert): cancel the timer, drop the hold, and **skip the body for
    this event too**. The pair is a no-op (INV-H3). This matters for S3: without the skip, the
    revert `home -> not_home` is processed as "a real leave" and resets `_away_not_home_since`
    (:1897-1899).
  - Any other value: cancel the hold, then process THIS event with `old_val := held.old_val`, as if
    the held edge never happened. It may itself be held.
- Confirm timer at `edge_ts + H`: if `hass.states.get(pid)` still reads `held.new_val`, call
  `_process_person_edge(pid, held.old_val, held.new_val, held.edge_ts, cfg)` (INV-H5; stamps use
  `edge_ts`, releases fire now). Otherwise drop it. Check `_torn_down` first. Clear the slot before
  calling (re-entrancy).
- `async_teardown` cancels every held timer (add to the timer loop at :653).
- Not persisted. A restart during a hold loses it; boot rules then apply (§9 R2).

### 5.3 Signal gate (D3): S6-S8
In `_apply_arrival` (:1007), first line: if `H > 0` and (`pid in self._held_edges` or
`stale_source_arrival(...)`), return and count `arrival_signal_held`. Do not queue it. Why dropping
is safe: if the edge confirms, the replayed P1 body releases the garage (`_arrival_counts` is True
for `not_home -> home`) and the away lock (any home), a superset of P2's effects for the same
person. Dispatcher order does not matter: HA writes the person state before any listener or signal
runs, so the live predicate already sees the stale source even if the signal arrives before the
regime's own state listener.

### 5.4 Proximity gate (D4): S9
In `_on_distance_event`, after the crossing test and the person resolution: if `H > 0`, the person
is known, and `stale_source_arrival(person)` is True, attach `proximity_sids.add(sid)` to that
person's held edge. If there is no held edge yet, create one keyed to `person.last_changed`, with
`old_val` taken from `_last_real`. Do not release. On confirm, re-read `_last_distance_m[sid]` and
release `proximity:{sid}` only if it is still <= radius. On cancel, drop it. `_last_distance_m` is
updated as today, because distance tracking is not arrival state. A crossing with the person
`not_home` (real approach, §2.3) is never stale by definition, so it releases at once.

### 5.5 Knob (D5)
`CONF_GARAGE_LOCKOUT_ARRIVAL_HOLD_S = "garage_lockout_arrival_hold_s"`, default
`GARAGE_LOCKOUT_ARRIVAL_HOLD_S = 5`.
`_SecurityLockoutNumber(min 0, max 60, step 1, unit "s", unique_suffix
"garage_lockout_arrival_hold_s", entity_id "number.ura_garage_lockout_arrival_hold", name
"Garage Lockout Suspicious Arrival Hold", icon "mdi:timer-sand")`. Plain-language description in
strings/en.json: *"When an arrival looks like a phone-tracker glitch (the home reading came from a
device that has not moved), wait this many seconds before unlocking. Normal arrivals are never
delayed. 0 = off."* Read live via `self._num(cfg, ...)`. Add the key to `__init__.py:7397`
and `:7704`. It also governs the away lock: one knob, because it is one predicate (operator decision
11-12 "applied to every arrival edge for both").

---

## 6. Numbers and knobs

| Number | Name | Rung | Why | Kill / off |
|---|---|---|---|---|
| hold seconds H, 5 | `CONF_GARAGE_LOCKOUT_ARRIVAL_HOLD_S` / `number.ura_garage_lockout_arrival_hold` | 3 (Number) | Policy the operator may tune; measured blip max 1.17 s | 0 = no hold, develop behaviour (INV-H4) |
| stale-source bound M, 10 s | `LOCK_ARRIVAL_STALE_SOURCE_S` (const.py lock block) | 1 | Classifier boundary with a 7-order gap; tuning it should need review | none of its own; H = 0 disables |
| 15-min away rule | `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` | 1, unchanged | Guards `unavailable -> home` only; rarely tuned | 0 = every blip counts (existing) |

---

## 7. Non-goals

- Gating the producer (`presence.py:5281` geofence dispatch) for HVAC pre-arrival, music
  following and the security expected-arrival sanction. Same blips, other consumers. **Card it**
  (follow-up; reuses D1's predicate).
- House-state releases (S11/S12) and boot discharge (S10). Measured 0; see §9.
- `LOCK-REGIME-BOOT-REALLY-AWAY-1` (boot-window `_really_away`). Stays parked with its own trigger;
  its trigger (lockout ON) fires at the same moment, so plan it next.
- Changing `_really_away`, the 15-min constant, face corroboration rules, or the entry-areas
  wiring.
- A "≥ 2 GPS trackers on a person" repair/warning. Parked (§8).
- Turning the lockout or the away lock on. That is an operator action after this ships.

---

## 8. Marginal-benefit decomposition

- **Simplest** = (c) predicate + hold at the three entry points (D2-D4). It captures all measured
  blips and adds 0 delay to real arrivals.
- **Fancier, rejected for now:**
  1. A combined (a)+(c) rule. Zero extra catch on the data, and one more axis.
  2. Requiring "not suspicious" again at H (would block a long stale-source home). It risks a
     lock-out: a real arrival that lands while the person already reads `home` from a stale source
     produces no new person edge, so the lockout would never release. That is a worse failure than
     the one it fixes.
  3. A producer-side gate in presence. Wider blast radius (HVAC), and it does not cover P1/P5,
     which read raw state.
  4. A config repair warning for ≥ 2 GPS trackers. Cheap, but it nags users who want an iPad on
     their person. **Parked, revival trigger:** a confirmed hold appears in the snapshot counter
     outside a boot window (that means a stale-source home persisted ≥ H).
- Honest value statement: with today's tracker sets this guard fires 0 times. It earns its keep the
  day someone adds a second GPS device, which happened once already (the iPad, 78 false arrivals in
  4 days, 49 of them also proximity releases).

---

## 9. Residuals (named, accepted unless the operator says otherwise)

- **R1** A stale-source `home` that lasts ≥ H (attribute-refresh variant) releases at H. That is
  the same as develop, delayed by H. Not observed in the window.
- **R2** Boot: restore rewrites `last_changed`, so the predicate is blind for edges replayed at
  boot and for `_away_boot_discharge`. Unchanged from develop.
- **R3** A blip that lasts long enough for a scheduled inference to see it could produce an
  ARRIVING/HOME_* house edge that releases. 0 in 7 days; HOME_* only releases when `reason != NONE`.
- **R4** A hold drops the P2 signal instead of queueing it. If the person edge is then cancelled by
  a non-revert value (e.g. `home -> unavailable`), the arrival is lost until the next real edge. A
  real arrival is never held, so this needs a stale-source home at arrival time.

---

## 10. Deliverables

### D0: Commit the probe and the replay fixture
`scripts/probes/lock_arrival_edge_probe.py` (read-only, `ssh ha "python3 -" < ...`) emits per-edge
rows (`person, edge_ts, prev, dur, source, source_type, src_age, unav_ago`) plus the P5 crossings.
Commit its 11-05..11-12 output as `quality/tests/fixtures/lock_arrival_edges_2026_11.json` (118
edges + 52 crossings; no coordinates, ages only).
- **Verify:** fixture counts 40 real / 78 blip; 3 real / 49 blip crossings.
- **Test:** `test_lock_arrival_hold_replay.py::test_fixture_shape`.

### D1: `stale_source_arrival` predicate
- **Verify:** True for a person `home` with source age > M; False when source age <= M; True when
  the source is missing or has no state; False for `not_home` / unreal.
- **Test:** `test_arrival_edges.py::test_stale_source_*` (5 cases incl. zone, missing source).

### D2: person-edge hold (S1-S5)
- **Verify (discriminating):** blip pair (home 39 ms, revert) with H=5: no `lock.unlock` call;
  `_last_real`, `_arrival_edges`, `_away_not_home_since`, `_away_attempted`, `releasing_set`,
  `release_gen` equal before and after. Under the plausible wrong build (hold timer but revert
  processed through the body), `_away_not_home_since[pid]` moves to the revert ts, so the test
  asserts the exact stamp.
- **Verify:** a fresh-source edge releases in the same callback (the `lock.unlock` service call is
  recorded before the listener returns), not after H.
- **Verify:** a stale-source edge that persists 6 s confirms at H: one release with trigger
  `person:<pid>`, and `_arrival_edges[slug] == edge_ts` (not confirm ts).
- **Verify:** stale edge, then `home -> unavailable` inside H: hold cancelled; the `unavailable`
  event is processed with `old_val = not_home` (no stamp regression).
- **Test:** `test_lock_arrival_hold.py::test_blip_pair_noop_garage`, `::test_blip_pair_noop_away_stamp`,
  `::test_fresh_source_releases_same_callback`, `::test_stale_persisting_confirms_at_h_edge_ts`,
  `::test_hold_cancel_by_other_value`, `::test_teardown_cancels_holds`, `::test_approach_zone_stale_held`.

### D3: signal gate (S6-S8)
- **Verify:** geofence signal dispatched (before or after the regime's state listener) for a
  stale-source home: no release. A fresh-source geofence signal releases as today. A camera_face
  within 120 s after a cancelled blip is NOT corroborated (S4 never stamped).
- **Test:** `::test_geofence_signal_dropped_while_stale`, `::test_geofence_signal_before_state_listener`,
  `::test_face_not_corroborated_by_blip`, `::test_held_face_recheck_blocked_while_stale`.

### D4: proximity gate (S9)
- **Verify:** crossing to 0 ft in the same ms as a stale-source blip: no release; revert drops it.
  A crossing with the person `not_home` (the 11-07 12:13:13 shape) releases at the crossing. A
  stale hold that confirms re-reads the distance and releases only if still <= R.
- **Test:** `::test_proximity_blip_held_and_dropped`, `::test_proximity_real_approach_instant`,
  `::test_proximity_confirm_rereads_distance`.

### D5: knob
- **Verify:** `number.ura_garage_lockout_arrival_hold` on the Security Coordinator device, default
  5, persists through options, and a change does not reload the CM (keys in both `__init__` sets).
  H=0 equals develop.
- **Test:** `::test_hold_zero_is_develop_golden` (whole fixture replayed at H=0 vs develop golden),
  `test_sc_lock_exclude_options.py`-style round trip `::test_arrival_hold_number_roundtrip`,
  `::test_arrival_hold_key_in_reload_suppress_and_no_live_attr`.

### D6: replay test (the acceptance oracle)
Drive the real regime (`_lockout_harness.py`) through all 118 fixture edges and 52 crossings with
H=5, lockout and away lock engaged.
- **Verify:** 40/40 real edges and 3/3 real crossings release at 0 added delay; 78/78 blips and
  49/49 blip crossings issue no unlock; final state equals the "blips removed" run.
- **Test:** `test_lock_arrival_hold_replay.py::test_replay_real_instant_blips_never_unlock`.

### D7: docs
Update `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 (P1/P2/P5/away-lock rows: suspicious-arrival
hold; remove "short blips included, no blip gate") and add a §10 ledger entry. The entry records
that the 11-12 dropout-only decision was refuted by the confusion matrix, and that the away-lock
"no blip gate needed, releasing is fail-safe" claim is wrong for a door unlock. Also update
`IDENTITY_FUSION_CAMERAS_MANUAL.md` lock block (face corroboration ignores held edges) and the
card.

### Live criteria (post-deploy; the lockout may still be off)
- `number.ura_garage_lockout_arrival_hold` exists, reads 5.
- Lock regime snapshot attributes show `arrival_holds` / `arrival_signal_held` counters at 0, and
  `held_edges` empty after a resident's real arrival. With today's tracker sets the expected
  count is 0. Discriminator: a non-zero count with no second GPS device on any person means the
  predicate is false-holding, i.e. a real-arrival delay. Check `person.*.source` at that edge.
- Organic (when the lockout is on): every resident arrival's lockout release time equals the
  person edge time (within 1 s) in the activity log. A release H seconds after the edge with a
  fresh source = FAIL.

### Mutation drills (framing C; each must turn a named test RED)
1. Delete the D2 hold branch: `test_blip_pair_noop_garage` fails.
2. Process the revert through the body: `test_blip_pair_noop_away_stamp` fails.
3. Stamp `_arrival_edges` at listener time instead of confirm: `test_face_not_corroborated_by_blip` fails.
4. Remove the D3 gate: `test_geofence_signal_dropped_while_stale` fails.
5. Remove the D4 gate: `test_proximity_blip_held_and_dropped` fails.
6. Invert the predicate threshold (`<` for `>`): `test_replay_real_instant_blips_never_unlock` fails (real held).
7. Confirm with confirm-time ts: `test_stale_persisting_confirms_at_h_edge_ts` fails.
8. Drop the key from `_NO_LIVE_ATTR_KEYS`: `test_arrival_hold_key_in_reload_suppress_and_no_live_attr` fails.

---

## 11. Tier

**Tier 2, elevated to Tier 2-DB review (3 framing-disjoint reviews) + live validation**, per the
standing regression-prone policy: door-unlock actuation, two lock policies, and a refactor of the
shared person-edge body. Also mandatory: the eight per-site mutation drills above (Tier-3 framing-C
style), because the failure mode is one missed site (Bug Class #53).
Suggested framings: A = predicate + hold state machine correctness (cancel/confirm/re-entrancy, H=0
golden); B = cross-path completeness (S1-S12 re-enumerated independently, dispatcher ordering,
teardown/restart); C = test authority by mutation + replay fixture. One adversarial plan review
before build (Tier 2 rule). Not Tier 3: no cost/safety state machine shared with other
coordinators, and the default direction of every hold is "unlock a few seconds later", never
"never unlock".
