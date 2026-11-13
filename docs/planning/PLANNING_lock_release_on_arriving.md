# PLANNING: house-state ARRIVING stops releasing the garage lockout and stops auto-disarming security

Card: LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 (`docs/planning/kanban.data.yaml:34770`, parent FACE-ARRIVAL-REBUILD-1).
Evidence: `docs/planning/AUDIT_arriving_on_body_evidence_2026_11_13.md` (the go/no-go probe; measure-before-build is
satisfied by it). Tier 3. Status: draft rev 1, awaiting the two Tier-3 plan reviews (completeness + adversarial
build-prediction). Must be build-ready before the operator returns (~11-16) and turns the garage lockout back on.

Operator constraint (card): "Feeling locked out is a nasty feeling." No real arrival may lose its release.

---

## 0. Institutional context verified

### 0.1 Read before planning

| Doc | How read | Relevance |
|---|---|---|
| `docs/planning/AUDIT_arriving_on_body_evidence_2026_11_13.md` | full | counts, lag table, fix shape §7, repro §5 |
| `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` | header corrections, §1 signal table rows 83-91, §7 (650-690), §10 ledger entries touching locks/arrivals (#29, #33, #34) | §1 row 83 and §7 line 677 state "ARRIVING releases"; both must be rewritten by this cycle (D5). Ledger #33 (away lock release is not fail-safe) and #34 (v3.19 face arrival never worked) are not re-asserted here |
| `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` | §4.5 lock-regime face arrivals (526-560) | the shared camera-derived classifier and `face_input_corroborated`; this plan does not touch identity |
| `docs/QUALITY_CONTEXT.md` | class index; #53, #56, #57 in full | #53 one missed site; #56 the tripwire must cover the boot-recheck channel, not only the edge channel |
| `docs/readmes/README_v5.108.16.md` | full | `arrival_source_needs_corroboration`, `face_input_corroborated`, security fails closed with no regime |
| `docs/planning/PLANNING_sc_garage_remote_lockout.md`, `PLANNING_lock_suspicious_arrival_hold.md` | headers + release-trigger sections | origin of `_edge_decision`, S1-S5 person path, the 5 s hold |

Honest scope note: I did not read the 925-line manual and the 1,026-line presence doc line by line; I read every
section that mentions lock regime, ARRIVING, auto-follow, or arrival edges (grep `arriving|lockout|lock regime|auto.follow`),
plus both corrections ledgers' lock/arrival entries. The plan reviewers should treat that as a gap to close.

Contradiction found (code wins, doc fixed in D5): presence doc §1 row 83 lists the lock regime as releasing on
"WAKING / HOME_* / ARRIVING" without the `reason != none` condition on HOME_* (`security_lock_regime.py:861-864`).

### 0.2 Code surveyed (read, not grepped)

- `security_lock_regime.py` 796-975 (`on_house_state_changed`, `_edge_decision`, `_boot_recheck_regime`,
  `_arrival_since_setup`), 997-1060 (`on_person_arriving`, `_apply_arrival`), 1139-1368 (person edge, hold, really-away),
  1382-1427 (`face_input_corroborated`), 1585-1716 (`_release`, `_after_release`, manual-unlock memory), 1793-1855 (NM
  failure path), 2483-2532 (store payload), 2533-2610 (`_record`).
- `security.py` 180-200 (`_HOUSE_STATE_TO_ARMED`), 1175-1200 (house-state bridge feeds the regime first), 1230-1460
  (auto-follow schedule + fire), 2382-2460 (expected-arrival corroboration from v5.108.16).
- `presence.py` 1340-1450 (`infer`: AWAY -> ARRIVING on `census_count > 0 or any_zone_occupied`; ARRIVING -> HOME_*),
  9234-9330 (single dispatch helper; payload always carries `old_state`).
- `house_state.py` 70-128 (`VALID_TRANSITIONS`: AWAY -> {ARRIVING, HOME_*, GUEST, VACATION}; VACATION -> {ARRIVING, AWAY}).
- `arrival_edges.py` 25-70, 192-215 (`arrival_source_needs_corroboration`, `live_arrival_slug` = not_home -> home only,
  `nonface_arrival_source`).

### 0.3 REUSE-or-BUILD per piece

| Piece | Verdict | Where |
|---|---|---|
| Person-path release on a resident `-> home` edge | REUSED unchanged | `_process_person_edge` S1 `security_lock_regime.py:1218-1224`; hold `:1259-1348`; really-away `:1355` |
| Proximity / approach-zone release | REUSED unchanged | `:1224`, `:1348`, `:1566` |
| Morning backstop (bounded discharge for sleep-like reasons) | REUSED | `_schedule_backstop` `:2021`, `_on_backstop` `:2034`, `number.ura_garage_lockout_morning_backstop` |
| Re-engage after an arrival release | REUSED | `_after_release` `:1706-1716`, `_schedule_reengage` `:1981`, `GARAGE_LOCKOUT_REENGAGE_DELAY_S` const.py:3869 |
| Episode memory persisted in Store | REUSED (extend payload by one key) | `_store_payload` `:2483`, `_load_away_store` `:2502`, `garage_manual_unlock` pattern |
| `_record` decision rows (`lock_regime_<action>`) | REUSED | `:2533` |
| NM HIGH notify from the regime | REUSED shape | `_notify_failure` / `_garage_failure_coro` `:1793-1855` (`nm.async_notify`, `hazard_type`, `location` dedup key) |
| Resident predicate | REUSED | `_is_resident` `:518` (person.* minus `security_lockout_excluded_persons`) |
| "Arrival edge" stamp for corroboration | NOT reused for the trip-wire: `_arrival_edges` (`:1216`) only stamps `not_home -> home` (`arrival_edges.py:57-67`), so a named-zone -> home arrival (which S1 releases on, `_arrival_counts` `:1350`) would read as "no edge". NEW `_resident_home_edges` stamp, see below |
| Auto-follow arming map + fire gates | REUSED, one new gate | `security.py:189-195`, `_fire_state_driven_arming` `:1316-1460` |
| Camera-derived source classifier | REUSED (security side, unchanged) | `arrival_edges.arrival_source_needs_corroboration` |
| `_resident_home_edges: dict[str, float]` | NEW. grep `resident_home_edge\|_resident_home` over `custom_components/` = 0 hits. Needed because the existing stamp's semantics are shared with the face gate and must not widen |
| `_arrival_taint` (episode saw an uncorroborated ARRIVING) | NEW. grep `taint\|via_arriving\|arriving_hold` = 0 hits in `security_lock_regime.py`/`security.py` |
| `resident_home_evidence()` public method on the regime | NEW, sibling of `face_input_corroborated` (`:1382`), same fail-closed contract |
| Constants (§6) | NEW: grep of `const.py` for `TRIPWIRE`, `UNCORROBORATED`, `STILL_LOCKED`, `ARRIVING_CORROBORATION` = 0 matches |
| Config-flow / Number entities | NONE added. Every new number is rung 1 (§6) |

Config-first check: is there a setting that already fixes this? No. The garage lockout switch and auto-follow are both
off today (the hazard is dormant), and the operator will turn the lockout on. No existing knob removes ARRIVING from the
release set; `GARAGE_LOCKOUT_ARRIVAL_HOLD_S` acts on person edges only. Code is required.

---

## 1. Problem (one paragraph)

`presence.infer` moves AWAY -> ARRIVING on `census_count > 0 or any_zone_occupied` (`presence.py:1347-1370`) with no
identity. The lock regime treats that edge as a release (`security_lock_regime.py:865-866`), then a release with a
`house_state:*` trigger ends the episode (`_after_release` `:1695-1705`: reason NONE, re-engage and backstop cancelled,
manual-unlock memory cleared). The HOME_* follow-on (`:861-863`) releases again for any `reason != none`, and every later
HOME_* -> HOME_* time-of-day edge does too. Security auto-follow maps `arriving -> DISARMED` with a 0 s delay
(`security.py:193`, `:1302-1306`). Measured: 2,642 AWAY -> ARRIVING edges since 03-12, 6.4% real arrivals, 32.8% no
resident evidence, 68.5% driven by zone sensors with census 0. In 16 of 17 exact real arrivals the resident's tracker
edge led ARRIVING (median 35 s) and the person path already releases on it. Zero access releases have ever fired
because every switch was off.

---

## 2. Falsifiable invariants

**INV-ARR (the one D must break).** With the garage lockout kill switch ON and a lockout engaged
(`reason` in {sleep, guest_night, vacation, boot_unknown}), no reachable sequence of house-state edges in which the house
passed through ARRIVING since the episode's last engage edge can cause `_release` to be called with a trigger of
`house_state:*` or `boot_recheck`, unless one of these holds at the call:
(a) a resident produced a counted `-> home` edge (S1) within `LOCK_RELEASE_TRIPWIRE_WINDOW_S` before the call, or
(b) the trigger is `boot_recheck` and a resident's live `person.*` state reads `home`, or
(c) the trigger is `house_state:waking` (only reachable after a SLEEP engage edge, which clears the taint; §4 D1).
Breaking it means: a legal config + an edge/time sequence that ends in an unlock with none of (a)-(c).

**INV-REAL (the operator's constraint, regression guard).** With the kill switch ON, a lockout `locked`, SC alive, and a
resident's `person.*` edge that `_arrival_counts` accepts (`:1350`), an unlock is issued within `hold_s + 1 tick` of the
edge, whatever the house state is (AWAY, ARRIVING, HOME_*, SLEEP, VACATION) and whatever the edge order relative to
ARRIVING (before, after, or with no ARRIVING at all). This holds today; the cycle must not weaken it.

**INV-AF (security, only meaningful when `security_auto_follow` is on).** Auto-follow never calls
`handle_disarm(source="auto_follow")` for house state `arriving` unless `resident_home_evidence()` is True at the fire,
or a resident's non-camera `SIGNAL_PERSON_ARRIVING` landed while the arriving disarm was pending.

---

## 3. Producer and consumer checks

### 3.1 Producer: house state ARRIVING
- Arithmetic: `has_people = census_count > 0 or any_zone_occupied` then `if current_state == AWAY: return ARRIVING`
  (`presence.py:1347-1370`). Also reachable from VACATION (`house_state.py:122-125`). Both legs are identity-free.
- Health: zone leg carried a Back Hallway phantom epoch (Jul-Aug); census leg had an October cluster during operator
  travel. Since the v5.108.1 sleep-mask fix, SLEEP -> AWAY entries are 0 (audit §5).
- Fire check: 2,642 ARRIVING edges in 8 months; 13 since 11-07.
- Decision: the producer is NOT changed. ARRIVING still drives HVAC (`hvac.py:2853-2856` skip), NM, lighting. Policy
  moves into the two access consumers (CLAUDE.md "policy lives in the consumer").

### 3.2 Producer: resident `-> home` person edge (the replacement release path)
- `_on_person_event` -> optional 5 s hold if the source tracker did not change -> `_process_person_edge` S1
  (`:1218-1221`). Counts `not_home`/named zone -> home always; `unknown/unavailable -> home` only if really away >= 15 min,
  or inside the 600 s boot window.
- Health: one GPS tracker per resident since 11-11; 17/17 recent real arrivals had a GPS edge (audit §4.2, "GPS alone
  covered every one"). The trailing case (house_state_log id 8632, 11-12 16:43): ARRIVING led Ezinne GPS by 45 s and
  Jaya BLE by 55 s. Under this plan the lockout releases at Ezinne's edge, 45 s later than today. Ezinne's edge was
  `not_home -> home`, so `_arrival_counts` returns True without the really-away test; it would not be held unless the GPS
  tracker's `last_changed` lagged the person's by > 10 s (`LOCK_ARRIVAL_STALE_SOURCE_S`), which the hold plan measured at
  0 of 40 real arrivals.
- Fire check: the S1 branch has fired 0 times live (switch off). D3's second trip-wire covers it once the switch is on.

### 3.3 Consumers of house-state edges with access effect (forward trace)

| Consumer | file:line | Effect today on ARRIVING | After this cycle |
|---|---|---|---|
| Lock regime edge release | `security_lock_regime.py:808-811` via `_edge_decision:865` | release + episode end | no release; record `arriving_hold`; set taint |
| Lock regime HOME_* release | `_edge_decision:861-863` | release when reason != none | no release while taint set |
| Lock regime boot recheck | `_boot_recheck_regime:912-929` | house `arriving` + BOOT_UNKNOWN + locked -> release | release only if a resident reads `home`; HOME_* with persisted taint -> no release |
| Lock regime manual-unlock memory | `:812-816`, `:914-917` | ARRIVING / HOME_* end the episode | ARRIVING no longer ends it; a tainted HOME_* does not end it |
| Security auto-follow | `security.py:193`, `:1302-1306`, `:1452-1453` | DISARMED at 0 s | gated on `resident_home_evidence()`, pending discharge (D2) |
| Away lock | not on this path (`SIGNAL_PERSON_ARRIVING` only, `:1059`) | none | unchanged |
| Door-lock unlocks | `lock.unlock` only on person/proximity/hazard/teardown | none | unchanged |

---

## 4. Deliverables

### D1: lock regime: an ARRIVING-tainted episode does not release on house-state edges

Changes, all in `domain_coordinators/security_lock_regime.py`:

1. **Taint state.** `self._arrival_taint: bool = False`, persisted as store key `garage_arrival_taint` (bool) in
   `_store_payload` / `_load_away_store` (missing or non-bool -> False). Set to True in `on_house_state_changed` when
   `new == "arriving"` and `self.reason != REASON_NONE` (regardless of kill switch, so the taint is correct if the switch
   is turned on mid-episode). Cleared (and saved) at: any engage-kind edge (`sleep`, `vacation`, guest-in-window), `waking`,
   every `_release` call (any trigger, after the call runs), `on_hazard`, kill switch ON -> OFF, `reason` becoming NONE in
   `_after_release`. Never cleared by ARRIVING or HOME_*.
2. **`_edge_decision(new, cfg)`** (keep the signature; it reads `self._arrival_taint`):
   - `new == "arriving"`: return `("arriving_hold", None)` when `reason != NONE`, else `("none", None)`. The
     `if new == "arriving": return "release"` branch is deleted.
   - `new in _HOME_STATES`: after the existing guest-yield branch, if `self._arrival_taint` and `reason != NONE`, return
     `("arriving_hold", None)`; otherwise unchanged (`release` when reason != none).
   - Order: the taint check sits inside the `_HOME_STATES` branch, AFTER the guest-yield branch (the yield edge's
     old_state is `guest`, never arriving; the yield must keep its own record type).
3. **`on_house_state_changed`**: set the taint (item 1) BEFORE calling `_edge_decision`. New branch for
   `kind == "arriving_hold"`: `self._record("arriving_hold", trigger=f"house_state:{new}", written=[], extra={"reason": ...})`,
   increment `self.arriving_holds`, return. It must NOT call `_clear_manual_unlock` (the episode has not ended).
4. **`_boot_recheck_regime`**: `house == "arriving"` with `reason == BOOT_UNKNOWN` and something `locked` releases only
   when `resident_home_evidence(boot=True)` is True (some resident's live `person.*` reads `home`); otherwise decision
   `arriving_no_resident`, no command. Remove `"arriving"` from the `ended` tuple at `:916`. HOME_* at boot with a
   restored `_arrival_taint` -> `_edge_decision` returns `arriving_hold` -> decision `arriving_hold`, no command.
5. **`resident_home_edge` stamp.** In `_process_person_edge`, for a resident with `new_val == "home" and old_val != "home"`
   and `_arrival_counts(...)` True, write `self._resident_home_edges[pid] = edge_ts` immediately before the S1
   `_release`. Not persisted. Used only by D3's trip-wire and by `resident_home_evidence`.
6. **`resident_home_evidence(*, boot=False) -> bool`** (public; fail closed when torn down): True if any resident has a
   `_resident_home_edges` stamp within `LOCK_RELEASE_TRIPWIRE_WINDOW_S` of now, or (any call) a resident's live `person.*`
   state is `home` and the regime has no hold pending for that person (`_held_edges`). `boot=True` additionally accepts a
   restored `home` (no `_last_real` needed).

No change to: `_release` arithmetic, S1-S5, hold, proximity, backstop, re-engage, away lock, hazard, kill-switch paths.

Behaviour changes to tell the operator (README):
- A night arrival that is the first event of an episode (house SLEEP -> AWAY earlier, resident returns) now releases via
  the person path and **re-engages** after `garage_lockout_reengage_delay_s` (900 s) once the arriver settles, instead of
  ending the episode at ARRIVING. A later HOME_NIGHT -> SLEEP re-engages anyway in most such nights.
- A phoneless arrival (guest, dead phone, excluded person) during an engaged episode no longer releases on ARRIVING. It
  waits for proximity (needs a resident's distance sensor), the morning backstop (sleep-like reasons), a manual unlock,
  or the kill switch. VACATION has no backstop: a house-sitter without a tracked phone stays locked out of the remotes
  until a resident edge or the switch. This is the intended trade, stated before build.

#### Acceptance criteria
- **Verify:** lockout engaged on SLEEP; SLEEP -> AWAY -> ARRIVING with no person edge -> 0 unlock calls; `reason` stays
  `sleep`; `last_action.action == "arriving_hold"`; backstop still scheduled.
- **Verify:** same, then ARRIVING -> HOME_NIGHT -> HOME_* time edges -> 0 unlocks; backstop at its hour unlocks once.
- **Verify:** resident `not_home -> home` before ARRIVING (16/17 shape) -> unlock within 1 tick with trigger `person:...`;
  after ARRIVING (8632 shape, +45 s) -> unlock at the edge; with the 5 s hold triggered (stale source) -> unlock at +5 s.
- **Verify (discriminating vs "release just got delayed"):** in the no-person-edge fixture, advance 6 h of HOME_* edges in
  a VACATION episode: still 0 unlocks. A merely-delayed gate would unlock at the first HOME_* -> HOME_* edge.
- **Verify:** restart with persisted taint and house HOME_DAY + BOOT_UNKNOWN locked -> boot recheck decision
  `arriving_hold`, 0 unlocks; restart with house `arriving` and a resident reading `home` -> 1 unlock (`boot_recheck`).
- **Verify:** manual unlock remembered (`garage_manual_unlock`) survives an ARRIVING edge and a tainted HOME_* edge.
- **Test:** `test_lock_release_arriving.py::test_body_only_arriving_does_not_release_sleep`,
  `::test_arriving_then_home_star_chain_holds_until_backstop`, `::test_vacation_tainted_home_edges_never_release`,
  `::test_real_arrival_edge_before_arriving_releases`, `::test_real_arrival_edge_after_arriving_releases_8632_shape`,
  `::test_real_arrival_with_stale_source_hold_releases_after_hold`, `::test_named_zone_to_home_releases`,
  `::test_taint_persisted_boot_recheck_holds`, `::test_boot_recheck_arriving_releases_only_with_resident_home`,
  `::test_manual_unlock_memory_survives_arriving`, `::test_taint_cleared_by_waking_engage_release_hazard_killswitch`,
  `::test_guest_yield_hold_unchanged_with_taint`.
- **Test inversions (deliberate, each named in the build commit):** `test_sc_garage_lockout.py`
  `::test_boot_recheck_releases_boot_unknown_lock_when_arriving` (now needs a resident `home`),
  `::test_remembered_unlock_cleared_at_episode_end_next_episode_locks[arriving]` (arriving no longer ends the episode;
  keep `waking`/`home_day`), and the `rig.edge("arriving")` release assertions near lines 895, 2329, 2512 plus any in
  `test_sc_garage_lockout_review_c.py`. The builder lists every flipped assertion with old/new expectation; deleting one
  instead of flipping it is a review finding.
- **Live:** with the switch on (after the operator turns it on), `sensor.ura_security_coordinator_security_armed_state`
  attributes `lock_regime_arriving_holds` exists (0 until a body-only ARRIVING in an episode) and
  `lock_regime_garage_lockout_last_action` shows `person:*` triggers on real arrivals; `decision_log` has no
  `lock_regime_release` row with context `house_state:arriving` after deploy.

### D2: security auto-follow: ARRIVING disarms only with resident evidence

In `domain_coordinators/security.py`:
1. Keep `"arriving": DISARMED` in `_HOUSE_STATE_TO_ARMED` (removing it would strand ARMED_AWAY after a real return,
   since HOME_* is unmapped, `:184-188`).
2. In `_fire_state_driven_arming`, after the existing gates and before the `handle_disarm` call, when
   `target_state == "arriving"`: `regime = self._lock_regime`; if `regime is None or not regime.resident_home_evidence()`,
   record suppressed `arriving_uncorroborated`, stamp `self._arriving_disarm_pending_ts = now`, and return.
3. Discharge: in `_handle_person_arriving_signal` (`:2382`), when `_arriving_disarm_pending_ts` is set, the payload source
   is not camera-derived (`not arrival_source_needs_corroboration(source)`, and `source is not None`), the person is a
   resident (`regime._is_resident` via a small public wrapper), and `now - pending_ts <= SECURITY_AUTO_FOLLOW_ARRIVING_CORROBORATION_WINDOW_S`:
   clear the pending stamp and run the same `handle_disarm(source="auto_follow")` path (through the fire gates:
   enabled, auto-follow on, observation mode, manual hold). Expiry: the stamp is ignored past the window and cleared by
   any later house-state intent (`_handle_house_state_intent` entry) and on teardown. No timer is created.
4. The `already_home` case (a resident reads `home` during a false AWAY's correction) disarms at once: the predicate's
   live-`home` leg covers it.

Marginal-benefit note: auto-follow is off and has never fired (audit §6). This deliverable is independent of D1 and is
NOT a gate for the 11-16 lockout re-enable. If the build budget is short before 11-16, ship D1+D3+D4+D5 and move D2 to a
Tier-2 sibling plan (record the move on the card). The fancier "require a named identity" variant is parked (§8).

#### Acceptance criteria
- **Verify:** auto-follow on, armed_away, AWAY -> ARRIVING with no resident evidence -> stays armed_away;
  `_state_driven_arming_last.suppressed == "arriving_uncorroborated"`.
- **Verify:** then a resident `SIGNAL_PERSON_ARRIVING(source=geofence)` within 120 s -> disarmed once; with
  `source=camera_face` -> still armed; at 121 s -> still armed.
- **Verify:** a resident already reading `home` -> ARRIVING disarms at once (false-AWAY correction).
- **Verify:** no lock regime (SC config without it) -> ARRIVING never disarms (fail closed, matches v5.108.16).
- **Test:** `test_house_state_rung2a.py::test_arriving_disarm_requires_resident_evidence`,
  `::test_arriving_pending_disarm_discharged_by_geofence_arrival`, `::test_arriving_pending_not_discharged_by_camera_face`,
  `::test_arriving_pending_expires_at_window`, `::test_arriving_disarm_when_resident_already_home`,
  `::test_arriving_no_regime_fails_closed`, `::test_waking_disarm_unchanged`. Existing rung-2a tests asserting
  `arriving -> DISARMED` with no person setup are flipped deliberately (listed in the commit).
- **Live:** `security_auto_follow` stays off (operator decision); live check is that the attribute
  `state_driven_arming_last` exists and no `auto_follow` decision rows appear. Organic proof only if the operator turns
  auto-follow on; otherwise in-suite only, stated in the README.

### D3: trip-wire: uncorroborated house-state release or auto-disarm pages NM

1. In `_release` (the single choke point for every release channel: `:810` edge, `:929` boot recheck, `:2039` backstop),
   before the kill-switch return, compute `uncorroborated = trigger.startswith("house_state:") or trigger == "boot_recheck"`
   AND `self._episode_saw_arriving` (an independent flag set on every ARRIVING edge while reason != NONE and cleared only
   at engage edges and reason -> NONE; deliberately NOT the D1 taint, so a bug in the taint cannot also blind the
   trip-wire, Bug Class #56) AND no `_resident_home_edges` stamp within `LOCK_RELEASE_TRIPWIRE_WINDOW_S` AND NOT
   (`trigger == "boot_recheck"` and a resident reads `home`). If true and the kill switch is on: increment
   `uncorroborated_releases`, record `lock_regime_uncorroborated_release`, and spawn one NM HIGH:
   `hazard_type="lock_release_uncorroborated"`, `location="garage_lockout:house_state"`, title "Garage lockout released
   without a resident arrival", message names the trigger and the last house edges. Do not block the release (the
   trip-wire observes; the gate is D1).
2. Same for auto-follow: immediately before `handle_disarm(source="auto_follow")` when `target_state == "arriving"`,
   recompute the evidence independently (stamp read via the regime's public method); if False, NM HIGH
   `hazard_type="auto_disarm_uncorroborated"`.
3. Window 0 disables both trip-wires (documented on the constant).

Expected steady state: zero fires. Under the current code (pre-D1) it would fire on any body-only ARRIVING release,
which makes it a discriminating mutation target (see §7).

#### Acceptance criteria
- **Verify:** with D1's ARRIVING branch mutated back to `release`, the body-only fixture fires exactly one NM HIGH with
  `hazard_type == "lock_release_uncorroborated"` and the release still happens (observer, not gate).
- **Verify:** a real-arrival fixture (edge -35 s, then ARRIVING, then HOME_*) fires 0 trip-wires.
- **Verify:** boot recheck with house `arriving` and a resident reading `home` releases and fires 0 trip-wires; with no
  resident `home` and the D1 boot branch mutated to release, fires 1.
- **Test:** `test_lock_release_arriving.py::test_tripwire_fires_on_uncorroborated_house_state_release`,
  `::test_tripwire_silent_on_real_arrival_chain`, `::test_tripwire_covers_boot_recheck_channel`,
  `::test_tripwire_window_zero_disables`; `test_house_state_rung2a.py::test_auto_disarm_tripwire_fires_when_gate_bypassed`.
- **Live:** `lock_regime_uncorroborated_releases` attribute present and 0; no NM rows with either hazard_type after
  deploy.

### D4: trip-wire: resident arrived and the lockout is still locked

The operator's constraint as code. On every S1 resident release call (the `_resident_home_edges` write site), schedule
one `_call_later` at `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S`; at fire, if the kill switch is on and any lockout entity still
reads `locked` and no newer engage happened (`release_gen` unchanged and no engage in flight), send NM HIGH
`hazard_type="lockout_locked_after_arrival"`, `location="garage_lockout:arrival:<person>"`, naming the person and
entity. Also fire it from the hold-cancel path? No: a cancelled hold is a blip by design. Unsub on teardown (track the
handle per person; a newer edge replaces it). This overlaps `_notify_failure` only when an unlock was attempted and
failed; it additionally covers "no unlock attempted" (e.g. a future gate that swallows S1).

#### Acceptance criteria
- **Verify:** with S1's `_release` call mutated out, a resident edge with the lockout locked -> NM HIGH at 90 s.
- **Verify:** normal release (lock reads `unlocked` by 90 s) -> no NM. A re-engage before 90 s (`release_gen` bumped by an
  engage) -> no NM.
- **Test:** `test_lock_release_arriving.py::test_still_locked_after_arrival_pages`,
  `::test_still_locked_tripwire_silent_after_unlock`, `::test_still_locked_tripwire_cancelled_on_teardown`,
  `::test_still_locked_window_zero_disables`.
- **Live:** in-suite only until a real arrival with the switch on; README states it.

### D5: docs written in the same commit
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 row 83 and §7 line 677: ARRIVING no longer releases; HOME_* does not
  release inside an ARRIVING-tainted episode; real arrivals release by the person path; add a §10 ledger entry:
  "ARRIVING releases the garage lockout" is wrong after this cycle (do not re-assert).
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5: one paragraph cross-reference (access needs a resident edge; house state alone
  is not identity).
- README for the release: the two trade-offs in D1, D2's status, the Live table.

---

## 5. Emission / decision-site enumeration (re-run independently in plan review)

`grep -n "self\._release(" security_lock_regime.py` (2026-11-13):

| Site | Trigger | In scope? | Change |
|---|---|---|---|
| `:810` `on_house_state_changed` | `house_state:{new}` | yes | D1 gate via `_edge_decision`; D3 observes |
| `:929` boot recheck (`functools.partial`) | `boot_recheck` | yes | D1 item 4; D3 observes |
| `:1058` `_apply_arrival` | `arriving_signal` (person) | no: person path, face-gated since v5.108.16 | none |
| `:1071` `on_hazard` | `hazard` | no | clears taint |
| `:1098` kill switch off | `kill_switch_off` | no | clears taint |
| `:1221` S1 | `person:{pid}` | replacement path | D1 stamp, D4 schedule |
| `:1224` approach zone | `approach_zone:{pid}` | no | none |
| `:1348`, `:1566` proximity | `proximity:{sid}` | no | none |
| `:2039` backstop | `backstop` | discharge path | D3 observes (never fires: trigger not house_state) |
| `:784` `_garage_release_on_disable_loop` | direct `_async_unlock`, not `_release` | no | none |

`_edge_decision` callers: `:807`, `:912` (both covered). Auto-follow disarm call: `security.py:1453` only
(`grep -n "handle_disarm(" security.py`). `SIGNAL_HOUSE_STATE_CHANGED` producer: one dispatch helper,
`presence.py:9314-9322` (always carries `old_state`).

House-state paths into HOME_* while an episode is engaged (D must check each): ARRIVING -> HOME_* (tainted, held);
AWAY -> HOME_* direct (valid in `house_state.py:72-79`, not proposed by `infer`; only manual override; NOT tainted unless an
ARRIVING happened earlier in the episode; releases as today: operator action); GUEST -> HOME_* (guest exit; unchanged);
HOME_* -> HOME_* (time edges; held while tainted); WAKING -> HOME_DAY (after a SLEEP engage, taint cleared).

---

## 6. Numbers and knobs

| Name | Value | Rung | Why | Off value |
|---|---|---|---|---|
| `LOCK_RELEASE_TRIPWIRE_WINDOW_S` (NEW) | 120 | 1, `const.py` | matches the D10.5 window and the operator's spec; a safety-observer window should change only by review. Kept separate from `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` so a perimeter retune cannot move it | 0 = both D3 trip-wires off; `resident_home_evidence` then uses only the live-`home` leg |
| `SECURITY_AUTO_FOLLOW_ARRIVING_CORROBORATION_WINDOW_S` (NEW) | 120 | 1 | how long a pending arriving-disarm waits for a resident non-camera arrival; covers the measured +45/+55 s trailing case with margin | 0 = ARRIVING disarms only when evidence already exists at the fire (no pending) |
| `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S` (NEW) | 90 | 1 | must exceed max hold (Number max) + `GARAGE_LOCKOUT_READBACK_S` + retry time; 90 s is the lag at which a resident at the door notices | 0 = D4 off |
| `GARAGE_LOCKOUT_ARRIVAL_HOLD_S` | 5 | 3 (Number, existing) | unchanged | 0 = no hold |
| `GARAGE_LOCKOUT_REENGAGE_DELAY_S` | 900 | existing option | now also governs night arrivals that used to end the episode | existing |
| `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` | 15 | 1, existing | unchanged | n/a |
| Morning backstop | live 60 | 3, existing | the bounded discharge for a tainted sleep-like episode | existing |

The build must check that `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S > hold Number max + readback`; read the Number's max in
`number.py` and fail a test if the inequality breaks.

---

## 7. Per-site anchors and mutation drills (review C runs these; builder pre-runs them)

| # | Site (after build) | Mutation | Test that must go RED |
|---|---|---|---|
| M1 | `_edge_decision` arriving branch | return `("release", None)` | `test_body_only_arriving_does_not_release_sleep`; `test_tripwire_fires_on_uncorroborated_house_state_release` must turn GREEN-with-NM (asserts the NM) |
| M2 | `_edge_decision` HOME_* taint check | delete the taint condition | `test_arriving_then_home_star_chain_holds_until_backstop`, `test_vacation_tainted_home_edges_never_release` |
| M3 | taint set in `on_house_state_changed` | remove the set | M2's tests |
| M4 | taint persisted in `_store_payload` | drop the key | `test_taint_persisted_boot_recheck_holds` |
| M5 | boot recheck arriving branch | release without the resident-home test | `test_boot_recheck_arriving_releases_only_with_resident_home`; `test_tripwire_covers_boot_recheck_channel` |
| M6 | `arriving_hold` branch skips `_clear_manual_unlock` | call it | `test_manual_unlock_memory_survives_arriving` |
| M7 | taint cleared in `_release` | remove the clear | `test_taint_cleared_by_waking_engage_release_hazard_killswitch` (asserts the next real-arrival-free HOME_* after a person release still releases nothing extra / taint false) |
| M8 | `_resident_home_edges` write | remove | `test_tripwire_silent_on_real_arrival_chain` (would fire) |
| M9 | D3 `_episode_saw_arriving` set | remove | `test_tripwire_fires_on_uncorroborated_house_state_release` |
| M10 | D2 auto-follow gate | delete the `resident_home_evidence` check | `test_arriving_disarm_requires_resident_evidence` |
| M11 | D2 discharge source check | accept camera sources | `test_arriving_pending_not_discharged_by_camera_face` |
| M12 | D2 window check | drop `<= window` | `test_arriving_pending_expires_at_window` |
| M13 | D4 schedule | remove the `_call_later` | `test_still_locked_after_arrival_pages` |
| M14 | S1 `_release` (INV-REAL anchor, pre-existing) | delete the call | `test_real_arrival_edge_before_arriving_releases`, `..._after_arriving_releases_8632_shape` |

Restore and `git status` clean after every drill; disable `.pyc` (`PYTHONDONTWRITEBYTECODE=1`, clear `__pycache__`)
per the stale-pyc memory.

---

## 8. Config-extreme and combinatorial tests

All in `quality/tests/test_lock_release_arriving.py` using `_lockout_harness.py` (real-hass variant
`test_sc_garage_lockout_real_ha.py` gets one end-to-end copy of the body-only fixture and the 8632 fixture).

| Case | Expectation |
|---|---|
| hold = 0 and hold = Number max, edge before/after ARRIVING | INV-REAL holds; release at edge / edge + hold |
| `security_lockout_excluded_persons` = every person (no residents) | ARRIVING never releases; backstop releases; D3 silent; README states "no residents = no arrival release" |
| reason `guest_night` + guest toggle on + ARRIVING in window, then the yield edge | no release; `guest_yield_hold` record type unchanged for the yield |
| reason `vacation`, VACATION -> ARRIVING (valid edge) with no person | no release, ever, until a resident edge / switch off / hazard |
| reason `boot_unknown` (restart mid-episode) + ARRIVING | held; backstop releases (sleep-like) |
| kill switch OFF during ARRIVING, ON afterwards | taint was still set; HOME_* after switch-on holds |
| kill switch ON -> OFF -> ON in a tainted episode | OFF releases once and clears taint (INV-5 unchanged) |
| `LOCK_RELEASE_TRIPWIRE_WINDOW_S` = 0 | D3 off; D1 unaffected |
| `SECURITY_AUTO_FOLLOW_ARRIVING_CORROBORATION_WINDOW_S` = 0 | no pending; resident-already-home still disarms |
| reengage delay 0 / max after a night person release with ARRIVING following | lock re-engages per the knob; ARRIVING does not cancel it |
| ARRIVING -> AWAY -> ARRIVING flap x5, then a resident edge | 0 releases during the flap; exactly 1 at the edge |
| restart between ARRIVING and HOME_* (taint persisted) | boot recheck holds |

---

## 9. Non-goals

- No change to presence `infer` or the ARRIVING producer (HVAC, NM, lighting keep it).
- No identity / face requirement for any release (parked, below). No change to the face corroboration gate.
- No change to the away lock, door-lock unlocks, hazard egress, proximity, backstop arithmetic.
- No new config-flow field or Number entity.
- The "auto-follow arms ARMED_AWAY during a false AWAY while residents are home" problem is not fixed here (separate
  card if wanted; D2 only makes the ARRIVING correction disarm).
- Not turning the lockout or auto-follow on; that is the operator's decision on return.
- Guest exit (GUEST -> HOME_*) release semantics unchanged.

Parked (with revival trigger): "require a named identity or an independent edge for every ARRIVING-driven release".
Marginal gain over D1 is the 1-in-17 camera-first case (45 s); marginal risk is a new reader on a 44%-attach identity
path. Revive if resident tracker edges stop leading ARRIVING (e.g. a tracker outage makes ARRIVING the only signal),
measured by D4 firing.

---

## 10. Tier

Tier 3. Triggers: a release value threaded through a state machine with several decision sites (edge, boot recheck,
manual-unlock memory, store) where one missed site (Bug Class #53) is a silent unlock; access-safety impact; operator
constraint against lockout. Plan review: two framing-disjoint reviews (completeness re-enumeration of §5 including the
HOME_* entry paths; adversarial build-prediction). Build: `ura-super-builder` in a worktree. Code review: four framings
A/B/C/D, D attacking INV-ARR with legal-config repros; orchestrator re-greps §5 and re-runs M1, M2, M5, M14 before ship;
operator checkpoint before deploy (he is back ~11-16; the lockout stays off until then, so there is no live exposure
while waiting).

Build order: D1 -> D3 -> D4 -> D5, then D2 (separable). D1+D3+D4 gate the lockout re-enable.

## 11. Open questions for the operator (none block the build)

1. Night arrivals now re-engage the lockout 15 min after the arriver settles (person-path behaviour) instead of
   staying unlocked until morning. Keep, or should a night person release end the episode? (Default: keep.)
2. VACATION episodes: a house-sitter with no tracked phone cannot open the garage by remote until you switch the
   lockout off. Acceptable?
3. Auto-follow: build D2 now, or leave auto-follow off and park D2?
