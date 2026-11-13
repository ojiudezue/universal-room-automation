# PLANNING: house-state ARRIVING stops releasing the garage lockout

Card: LOCK-RELEASE-ON-ARRIVING-BODY-EVIDENCE-1 (`docs/planning/kanban.data.yaml:34770`, parent FACE-ARRIVAL-REBUILD-1).
Evidence: `docs/planning/AUDIT_arriving_on_body_evidence_2026_11_13.md` (the go/no-go probe; measure-before-build is
satisfied by it, plus the small D0 below). Tier 3.

**Status: rev 2 (2026-11-13).** Applies both Tier-3 plan reviews:
`docs/reviews/code-review/PLAN_lock_release_arriving_review_build_prediction.md` (F1-F22) and
`docs/reviews/code-review/PLAN_lock_release_arriving_review_completeness.md` (H1-H3, M1-M7, L1-L6). §12 maps every
finding to its change. The security auto-follow deliverable (rev 1 D2) moved to a parked sibling section (§13).
Must be build-ready before the operator returns (~11-16) and turns the garage lockout back on.

Operator constraint (card): "Feeling locked out is a nasty feeling." No real arrival may lose its release.

---

## 0. Institutional context verified

### 0.1 Read before planning (rev 2 closes the rev 1 gap)

| Doc | How read | Relevance |
|---|---|---|
| `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` | **completely** (1,026 lines), rev 2 | §1 rows 83-91 (lock regime consumers), row 97 (`person_state_for_trust` is the trust reader), §2 (ARRIVING producer, boot settle), §7 (INV-LOCK-1 guest yield), §8 (boot settle gate), §10 ledger #29, #33, #34. No ledger claim is re-asserted here |
| `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` | **completely** (925 lines), rev 2 | §4.5 (lock-regime face arrivals, held edges do not corroborate), §5.5(a) (identity never actuates; de-escalation needs ≥ 0.9). This cycle touches no identity path |
| `docs/architecture/SENSOR_FLEET_CLASSES.md` | completely | ARRIVING's zone leg is room occupancy (ZV motion-class, ZK/ZX radar, fan phantoms); confirms "body evidence" is not identity |
| `docs/planning/AUDIT_arriving_on_body_evidence_2026_11_13.md` | full | counts, lag table, fix shape §7, replay sets §7 (a)/(b) |
| Both plan reviews | full | §12 fix table |
| `docs/QUALITY_CONTEXT.md` | #53, #56, #62, #63 | one missed site; trip-wire channel coverage; hollow anchors; one knob two jobs |
| `docs/readmes/README_v5.108.16.md` | full | `arrival_source_needs_corroboration`, `face_input_corroborated` |
| `PLANNING_sc_garage_remote_lockout.md`, `PLANNING_lock_suspicious_arrival_hold.md` | release sections; hold plan §347-348 | `_edge_decision` origin, S1-S5, the hold; hold plan says LOCK-REGIME-BOOT-REALLY-AWAY-1 fires on the same trigger |
| Kanban `LOCK-REGIME-BOOT-REALLY-AWAY-1` (`kanban.data.yaml:34318`, parked) | full card | trigger "garage lockout ON" = this cycle's event; dispositioned in §9.1 |

**Doc vs code contradictions found (code wins; D5 fixes the docs):**
1. Presence doc §1 row 83 and §7 line 677 list the lock regime as releasing on "WAKING / HOME_* / ARRIVING" without
   the `reason != none` condition on HOME_* (`security_lock_regime.py:861-864`). Known since rev 1.
2. `docs/Coordinator/GUEST_MODE.md:119` and `docs/Coordinator/SECURITY_COORDINATOR.md:566` say ARRIVING releases;
   `SECURITY_COORDINATOR.md:118` documents `ARRIVING -> DISARMED` (still true; D2 is parked). L4.
3. Presence doc §1 row 90 marks the suspicious-arrival hold "NOT deployed"; the identity manual §4.5 says shipped
   v5.108.13, and `_held_edges` / `_on_hold_confirm` are on develop (`security_lock_regime.py:249, :1321`). D5 updates the
   row's marker.

### 0.2 Code surveyed (read, not grepped), rev 2 re-read on develop 519af938

- `security_lock_regime.py`: 525-540 (store load precedes `_boot_rebuild`), 595-660 (`_boot_rebuild`, `_on_boot_recheck`
  BOOT_UNKNOWN -> SLEEP/VACATION at :648/:650), 672-700 (teardown), 740-797 (SC-disable release, `reason = NONE` at :767),
  798-873 (`on_house_state_changed`, `_edge_decision`, `_set_engage_reason`), 878-974 (`_boot_recheck_regime`, `ended` at
  :914-917, `_arrival_since_setup`), 977-995 (`_on_guest_clock`: sets `reason` directly at :993, bypassing
  `_set_engage_reason`), 1062-1100 (hazard :1072, kill switch :1099), 1197-1232 (`_process_person_edge`), 1321-1367 (hold
  confirm, `_arrival_counts`, `_really_away`), 1585-1716 (`_release`, `_after_release` :1693-1716), 1718-1855 (unlock,
  read-back, `_notify_failure`, `_garage_failure_coro`), 1856-1946 (`_request_engage`, `engage_predicate`,
  `_async_engage`: `lock.lock` issued at :1915-1918 with no await after the predicate), 1948-2040 (re-engage, backstop),
  2477-2532 (`_spawn`, store), 2611-2630 (`snapshot`, merged into the SC sensor at `sensor.py:7362`).
- `presence.py` 2678-2700 (boot-settle `override_set` dispatch), 8332-8339 (inference dispatch), 9225-9322 (the one
  dispatch helper; payload `old_state`, `new_state`, `trigger`, `confidence`). `house_state.py:283` (override adapter
  trigger `override_set`).
- `person_coordinator.py:130-151` (`person_state_for_trust`: overruled -> `not_home`, no coordinator -> raw).
- `const.py:2791-2801` (exterior-person severity by house state), `:3895-3902` (boot windows, read-back 20 s, 1 retry).
- `number.py:4483-4492` (arrival hold Number, max 60 s).
- Tests: `test_sc_garage_lockout.py` :172-178, :512, :892-897, :2329, :2512; `test_sc_garage_lockout_review_c.py` :52,
  :209; `test_house_state_rung2a.py` :209, :383, :457-474; `_lockout_harness.py`, `_lock_arrival_replay.py`.

### 0.3 REUSE-or-BUILD per piece

| Piece | Verdict | Where |
|---|---|---|
| Person-path release on a resident `-> home` edge | REUSED unchanged | S1 `security_lock_regime.py:1218-1221`; hold `:1259-1348`; really-away `:1355` |
| Proximity / approach-zone release | REUSED unchanged | `:1224`, `:1348`, `:1566` |
| Morning backstop | REUSED unchanged | `_schedule_backstop` `:2021`, `_on_backstop` `:2034` |
| Episode boundary = engage | REUSED: `_set_engage_reason` `:875` is the existing choke point for live, boot-window and boot-recheck engages; the guest clock is routed through it (byte-identical: same reason write + `_schedule_backstop`) |
| Store persistence | REUSED, payload extended by two keys | `_store_payload` `:2483`, `_load_away_store` `:2502`, `_save_store` |
| NM HIGH from the regime | REUSED shape | `_garage_failure_coro` `:1837-1849` (`hazard_type`, `location` dedup key), `_spawn` `:2477` |
| `_record` decision rows | REUSED | `:2533` |
| Trust-level person state | REUSED `person_state_for_trust` (`person_coordinator.py:130`) | only reader in this cycle: D4b's house-believed-empty check is NOT a level read; no level read of person state is added to D1/D3/D4 (F4 resolved by removal, §12) |
| "Arrival since setup" | REUSED `_arrival_since_setup()` `:969` | recorded on the boot-recheck row only (diagnostic); never a release condition |
| Taint `_arrival_taint` + saw flag `_episode_saw_arriving` | NEW. `grep -rn "taint\|saw_arriving\|arriving_hold" custom_components/` = 0 hits |
| Flag clear helper `_end_episode_arrival_flags()` | NEW (one helper, F11/M3) |
| Engage counter `engage_seq` | NEW. `grep -n "engage_seq\|engage_count\|last_engage" security_lock_regime.py` = 0 hits. `release_gen` cannot serve (bumped only by releases, `:1587`, `:761`; F2/H3a) |
| Failure-NM stamp `_failure_nm_at: dict[str, float]` | NEW (D4 dedup with `lockout_release_failed`, H3b) |
| Still-locked timers `_still_locked_unsubs: dict[str, Callable]` | NEW |
| `_resident_home_edges`, `resident_home_evidence()` | **MOVED to §13 (D2 sibling)**. With F1's fix nothing in this cycle needs them |
| Constants (§6) | NEW: `grep -n "TRIPWIRE\|STILL_LOCKED\|UNCORROBORATED\|UNCOUNTED" const.py` = 0 matches |
| Config-flow / Number entities | NONE added |

**Config-first check:** no setting removes ARRIVING from the release set. `GARAGE_LOCKOUT_ARRIVAL_HOLD_S` acts on person
edges only. The lockout and auto-follow are off today; the operator turns the lockout on at ~11-16. Code is required.

---

## 1. Problem

`presence.infer` moves AWAY -> ARRIVING on `census_count > 0 or any_zone_occupied` (`presence.py:1347-1370`) with no
identity. `_edge_decision` returns `release` for `arriving` whatever the reason (`security_lock_regime.py:865-866`), and
a `house_state:*` release ends the episode (`_after_release` `:1695-1705`: reason NONE, re-engage and backstop
cancelled, manual-unlock memory cleared). HOME_* releases again for any `reason != none` (`:861-863`). Measured: 2,642
AWAY -> ARRIVING edges since 03-12, 6.4% real arrivals, 32.8% with no resident evidence, 68.5% driven by zone sensors
with census 0. In 16 of 17 exact real arrivals the resident's tracker edge led ARRIVING (median 35 s); the person path
already releases on it. Zero access releases have fired because every switch was off.

Out of scope here but named: auto-follow maps `arriving -> DISARMED` at 0 s (`security.py:193`); auto-follow is off and
has never fired (§13). Exterior-person alerts drop to LOW on ARRIVING (`const.py:2799`; §9.2).

---

## 2. Falsifiable invariants

**Definitions.** *Engaged*: `reason` in {sleep, guest_night, vacation, boot_unknown}. *Tainted episode*: the regime has
observed ARRIVING since the episode's last boundary, by any of: a house-state edge with `new_state == "arriving"` or
`old_state == "arriving"` (trigger not `override_set`) while engaged; a restored `garage_arrival_taint`; `_boot_rebuild`
finding the restored house `away` or `arriving` with a lockout `locked`; the boot recheck finding house `arriving` while
engaged. *Episode boundary*: `_set_engage_reason` (every engage, live, boot-window or boot-recheck, and the guest clock
routed through it), `_boot_rebuild` / `_on_boot_recheck` rebuilding to SLEEP or VACATION, and every `reason = NONE`
write (`:767`, `:1072`, `:1099`, `:1701`, `:1708`).

**INV-ARR (the one D must break).** With the garage lockout kill switch ON, in a tainted engaged episode, no
`_release` call with trigger `house_state:*` or `boot_recheck` writes an unlock (non-empty `written`) or ends the
episode, unless the trigger is `house_state:waking` (reachable only from SLEEP; reason sleep-like) or the edge's
payload trigger is `override_set` (an operator action). Releases on `person:*`, `approach_zone:*`, `proximity:*`,
`arriving_signal`, `backstop`, `hazard`, `kill_switch_off`, `sc_disabled` are outside INV-ARR and unchanged.
Breaking it means: a legal config + an edge/time/restart sequence that ends in such an unlock.

Rev 1's escape (a) ("a resident `-> home` edge within the window") is deleted (F1): the person path IS the release, and
a later HOME_* in the same episode has nothing to release.

**INV-REAL (regression guard, unchanged).** With the kill switch ON, a lockout `locked`, SC alive, and a resident
`person.*` edge that `_arrival_counts` accepts (`:1350`), an unlock is issued within `hold_s + 1 tick` of the edge,
whatever the house state and whatever the edge order relative to ARRIVING. The cycle must not weaken it.

**INV-REAL-B (new, the residual made visible; M5).** With the kill switch ON and engaged, a resident `unknown` /
`unavailable` -> `home` edge that `_arrival_counts` rejects while the house reads `away` or `arriving` produces, if a
lockout still reads `locked` `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S` later and no engage was issued in between, exactly
one NM HIGH (`hazard_type = "lockout_locked_resident_uncounted_return"`). This is a page, not a release (decision §11
Q4). Before this cycle the house ARRIVING edge released that case.

**INV-PAGE (D4).** After an S1 person release call with the kill switch ON, if a lockout still reads `locked`
`LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S` after the call, no `lock.lock` was issued after the call, and no
`lockout_release_failed` NM for that entity was sent after the call, exactly one NM HIGH
`lockout_locked_after_arrival` is sent.

---

## 3. Producer and consumer checks

### 3.1 Producer: house state ARRIVING
- Arithmetic: `has_people = census_count > 0 or any_zone_occupied`, then `if current_state == AWAY: return ARRIVING`
  (`presence.py:1347-1370`); also VACATION -> ARRIVING (`house_state.py:122-125`). Identity-free on both legs.
- Health: zone leg carried a Back Hallway phantom epoch (Jul-Aug); census leg an October cluster. Since v5.108.1,
  SLEEP -> AWAY entries are 0 (audit §5).
- Fire check: 2,642 ARRIVING edges in 8 months; 13 since 11-07.
- Boot: dispatches are suppressed while boot settle is pending (`presence.py:9249-9258`); the only boot-time dispatch
  is an `override_set` (`:2690-2698`). So the regime can miss the ARRIVING edge and first see `arriving -> HOME_*`
  (H2), or see nothing and find house `arriving` at the recheck (`test_sc_garage_lockout.py:175`). Both are covered by
  the taint definition (§2).
- Decision: producer NOT changed (HVAC, NM, lighting keep it). Policy moves into the access consumer.

### 3.2 Producer: resident `-> home` edge (the release path that remains)
- `_on_person_event` -> optional hold -> `_process_person_edge` S1 (`:1218-1221`). Counts `not_home` / named zone ->
  home always; `unknown/unavailable -> home` only if really away ≥ 15 min, inside 600 s of setup, or no real transition
  seen since setup.
- Health: one GPS tracker per resident since 11-11; 17/17 recent real arrivals had a GPS edge (audit §4.2). Trailing
  case 8632 (11-12 16:43): ARRIVING led Ezinne GPS by 45 s; under this plan the release lands at her edge, 45 s later
  than today.
- Fire check: S1 has fired 0 times live (switch off). D4 is its trip-wire once the switch is on.
- Gap (M5): a resident whose departure was never seen (phone unavailable while leaving, `_last_real` stays `home`)
  returns `unavailable -> home`; `_really_away` is False (`:1365-1366`); no S1. D4b pages it (INV-REAL-B). D0 measures
  how often this shape occurs.

### 3.3 Consumers of house-state edges with access effect (forward trace)

| Consumer | file:line | Today on ARRIVING | After this cycle |
|---|---|---|---|
| Edge release | `on_house_state_changed` `:808-811` via `_edge_decision:865` | release + episode end (even with reason NONE, F19) | engaged: `arriving_hold`, taint set; reason NONE: `none` |
| HOME_* release | `_edge_decision:861-863` | release when reason != none | tainted: `arriving_hold`; `override_set`: release as today |
| Boot recheck | `_boot_recheck_regime:912-929` | house `arriving` + BOOT_UNKNOWN + locked -> release | `arriving_hold` (no release, ever); tainted HOME_* -> `arriving_hold` |
| Manual-unlock memory | `:812-816`, `:914-923` | ARRIVING / HOME_* end the episode | ARRIVING and tainted HOME_* do not (incl. the boot `ended` expression, F6/M7) |
| Security auto-follow | `security.py:193`, `:1452-1453` | DISARMED at 0 s | **unchanged** (§13 parked; auto-follow off) |
| Exterior-person severity | `const.py:2799` via `perimeter_alert.py:95` | LOW | **unchanged** (§9.2, card) |
| Away lock, door locks | `SIGNAL_PERSON_ARRIVING` / `lock.unlock` on person/proximity/hazard/teardown | none | unchanged |

---

## 4. Deliverables

Build order: D0 (probe, parallel) -> D1 -> D3 -> D4 -> D5. D1 + D3 + D4 gate the lockout re-enable.

### D0: one-shot read-only probe (measure the D4b shape before building it)

`ura-prober`, read-only, over the URA DB `house_state_log` (all time) and the HA recorder (7 days): count resident
`person.*` `unavailable|unknown -> home` transitions (a) while house state is `away` / `arriving`, and (b) while house
state is `sleep` / `home_night` (the false-page population if (a)'s condition were widened). Also replay audit §7 (a)
and (b) sets through `quality/tests/_lock_arrival_replay.py` decision logic offline if the probe can.

#### Acceptance criteria
- **Verify:** report in `AUDIT_arriving_on_body_evidence_2026_11_13.md` §8 (appended) with both counts and the
  window. Go/no-go for D4b: (a) > 0 in the window, or the probe shows phone-unavailable departures exist at all; and
  the (a)-condition false-page estimate is < 1 per week. If (a) is 0 and no unavailable departure exists in 7 days,
  D4b still ships (cheap, page-only) but its README names the measured rate.
- **Live:** n/a (offline).

### D1: lock regime: a tainted episode never releases on house-state edges

All in `domain_coordinators/security_lock_regime.py`.

1. **State.** `self._arrival_taint: bool = False` and `self._episode_saw_arriving: bool = False` (D3's flag). Both
   persisted (store keys `garage_arrival_taint`, `garage_episode_saw_arriving`; added to `_store_payload`; loaded in
   `_load_away_store`, missing or non-bool -> False). Every change calls `_save_store()`. Counters
   `self.arriving_holds: int = 0`.
2. **Set sites** (two separate assignment statements at each site, one per flag, so a drill can remove one):
   - `on_house_state_changed`: read `old = payload["old_state"]`, `trig = payload["trigger"]` (dict or attr access as
     for `new`). If `self.reason != REASON_NONE` and `trig != "override_set"` and (`new == "arriving"` or
     `old == "arriving"`): set both flags. This runs BEFORE `_edge_decision` and BEFORE every early return in the
     method. `old_state == "arriving"` closes H2 (boot-settle-suppressed ARRIVING, first seen edge `arriving -> HOME_*`).
   - `_boot_rebuild`: after `reason` is rebuilt to BOOT_UNKNOWN, if the restored house is `away` or `arriving`, set
     both flags (a lock found locked while the house reads empty or arriving is an excursion; H2 / F5).
   - `_boot_recheck_regime`: if house is `arriving` and reason != NONE, set both flags before `_edge_decision` (H1 / F5).
3. **One clear helper** `_end_episode_arrival_flags()` (clears both, saves when either was True). Called at:
   `_set_engage_reason` (top), `_on_guest_clock` (route its `reason` write + `_schedule_backstop` through
   `_set_engage_reason(REASON_GUEST_NIGHT, cfg)`: byte-identical, since that helper does exactly those two things for a
   sleep-like reason), `_boot_rebuild` when it rebuilds SLEEP / VACATION, `_on_boot_recheck` `:648` / `:650`, and every
   `self.reason = REASON_NONE` write: `:767` (SC disable), `:1072` (hazard), `:1099` (kill switch off), `:1701`
   (`_after_release` episode end), `:1708` (vacation person arrival). The build adds a test that greps every
   `self.reason = ` assignment in the module and asserts each is either inside `_set_engage_reason` or immediately
   followed by the helper (structural guard, Bug Class #53), in addition to the behavioural tests.
   **Never cleared** by `person:*`, `approach_zone:*`, `proximity:*`, `arriving_signal` releases (F1), nor by ARRIVING
   or HOME_* edges, nor by `_request_engage` (re-engage keeps the episode).
4. **`_edge_decision(new, cfg, *, override: bool = False)`.** `on_house_state_changed` passes
   `override = (trig == "override_set")`; the boot recheck passes False.
   - `new == "arriving"`: `override` -> `("release", None)` (today's behaviour for an operator override);
     `reason != NONE` -> `("arriving_hold", None)`; else `("none", None)`. The unconditional release is deleted (F19:
     an ARRIVING with reason NONE no longer unlocks a hand-locked lockout; README names it).
   - `new in _HOME_STATES`, after the existing guest-yield branch: if `reason != NONE` and `self._arrival_taint` and not
     `override` -> `("arriving_hold", None)`; otherwise unchanged.
   - `waking` unchanged (releases on sleep-like reason; only reachable after SLEEP, whose engage cleared the taint, or
     via a boot-suppressed SLEEP: accepted exception in INV-ARR).
5. **`on_house_state_changed` branch for `kind == "arriving_hold"`:** `self.arriving_holds += 1`;
   `self._record("arriving_hold", trigger=f"house_state:{new}", written=[], extra={"reason": self.reason, "old_state": old})`;
   return. It must NOT call `_clear_manual_unlock`. The existing `kind == "none"` branch (`:812-816`) keeps clearing the
   memory for HOME_* / waking with reason NONE (no episode).
6. **`_boot_recheck_regime`:**
   - `ended = kind == "release" or (kind not in ("guest_yield_hold", "arriving_hold") and (house in _HOME_STATES or house == "waking"))`
     (`"arriving"` removed from the tuple; `arriving_hold` excluded; F6 / M7).
   - New branch `elif kind == "arriving_hold": decision = "arriving_hold"` (no act). House `arriving` therefore never
     releases at boot, with or without a resident reading `home` (M2: the "resident reads home" rule is deleted, not
     narrowed). The boot-recheck row adds `extra["arrival_since_setup"] = self._arrival_since_setup()` for diagnosis.
7. **Snapshot keys** (`snapshot()` `:2611`, merged into the SC sensor at `sensor.py:7362`):
   `lock_regime_arriving_taint`, `lock_regime_episode_saw_arriving`, `lock_regime_arriving_holds`.
8. Update the `_edge_decision` docstring and the INV-LOCK-1 comment at `:857` (it lists ARRIVING as releasing).

No change to: `_release` arithmetic, S1-S5, hold, proximity, backstop, re-engage, away lock, hazard, kill switch.

**Behaviour changes to tell the operator (README; corrected per F12 / L5):**
- *Night arrival after a false AWAY* (SLEEP -> AWAY -> ARRIVING -> HOME_NIGHT, resident returns): the resident's own
  edge unlocks (as today when it leads). ARRIVING and HOME_NIGHT no longer end the episode, so the morning backstop
  stays scheduled and a remembered manual unlock is kept. The 900 s re-engage timer runs but is abandoned with
  `house_not_sleep` while the house reads HOME_NIGHT (`_reengage_row_fails` `:1957-1960`, no retry `:2008-2015`). What
  re-locks is the next live HOME_NIGHT -> SLEEP engage edge, the same as today.
- *Phoneless arrival in an engaged episode* (guest, dead phone, excluded person): no release on ARRIVING or later
  HOME_*. It waits for a resident edge, proximity, the morning backstop (sleep-like reasons, incl. `boot_unknown` after
  any restart), a manual unlock, an `override_set` HOME_* (manual house-state override), or the kill switch.
- *VACATION*: if the house state leaves VACATION through ARRIVING (body evidence, e.g. a house-sitter), HOME_* is held;
  if it later reaches SLEEP, that engage edge restarts the episode (reason `sleep`, taint cleared) and the next WAKING
  releases. While the house reads VACATION there is no backstop; a restart while it reads HOME_* rebuilds
  `boot_unknown`, which is sleep-like, and the backstop runs (immediately if past its hour).
- *GUEST -> HOME_* guest exit* inside a tainted episode is held (F18); before this cycle it released.
- *ARRIVING with no episode* (reason NONE) no longer unlocks a lockout locked by hand (F19).
- *Resident whose departure was never seen* returning `unavailable -> home`: no release (as before this cycle except
  that ARRIVING used to cover it); D4b pages.

#### Acceptance criteria
- **Verify:** SLEEP engage; SLEEP -> AWAY -> ARRIVING, no person edge -> 0 unlock calls; `reason == "sleep"`;
  `last_action.action == "arriving_hold"`; backstop still scheduled; taint and saw flag True.
- **Verify:** then ARRIVING -> HOME_NIGHT -> HOME_* time edges -> 0 unlocks; the backstop at its hour unlocks once.
- **Verify (F1 shape, discriminating):** engaged, ARRIVING (taint), Oji `not_home -> home` at +45 s -> unlock with
  trigger `person:person.oji`; taint STILL True; a HOME_* edge 2 h later -> `arriving_hold`, 0 extra calls, episode not
  ended (`reason == "sleep"`). Under rev 1's clear-on-every-release it would release and D3 would page.
- **Verify:** 16/17 shape (edge before ARRIVING) and 8632 shape (+45 s after) both unlock at the edge; with the hold
  triggered (stale source) at edge + hold.
- **Verify (discriminating vs "release merely delayed"):** VACATION episode, VACATION -> ARRIVING -> 6 h of HOME_* edges
  -> 0 unlocks.
- **Verify (H2):** restart with house restored `away` and a lockout `locked` -> `_boot_rebuild` sets BOOT_UNKNOWN and
  the taint; a dispatched `arriving -> home_night` edge (no ARRIVING edge ever seen) -> `arriving_hold`; boot recheck at
  120 s -> decision `arriving_hold`; 0 unlocks.
- **Verify (H1/M2):** restart with house restored `arriving`, a resident reading `home` -> boot recheck decision
  `arriving_hold`, 0 unlocks (rev 1 released here).
- **Verify (persistence):** two rigs sharing one `DictStore`: rig 1 engaged + ARRIVING (taint saved); rig 2 boots with
  house HOME_DAY and the lockout locked -> boot recheck `arriving_hold`, 0 unlocks.
- **Verify:** manual unlock remembered survives an ARRIVING edge, a tainted HOME_* edge, and (restart variant) a
  tainted HOME_* boot recheck.
- **Verify (M3 stale-taint repro):** VACATION -> ARRIVING -> HOME_DAY -> GUEST, guest clock engages GUEST_NIGHT -> taint
  False after the clock; next morning HOME_DAY releases.
- **Verify:** `override_set` HOME_DAY in a tainted episode releases (today's behaviour); `override_set` ARRIVING releases
  and does not set the taint.
- **Verify:** reason NONE + lockout locked by hand + ARRIVING -> 0 unlocks.
- **Verify (replay, F21):** audit §7 (a) (10-14..10-18 cluster + edge 8623) through `_lock_arrival_replay.py` -> 0
  `lock_regime_release` rows with a `house_state:*` trigger; §7 (b) (8545-8632) -> each real arrival released by
  `person:*`.
- **Test:** `test_lock_release_arriving.py::test_body_only_arriving_does_not_release_sleep`,
  `::test_arriving_then_home_star_chain_holds_until_backstop`, `::test_person_release_keeps_taint_later_home_star_held`,
  `::test_vacation_tainted_home_edges_never_release`, `::test_real_arrival_edge_before_arriving_releases`,
  `::test_real_arrival_edge_after_arriving_releases_8632_shape`, `::test_real_arrival_with_stale_source_hold_releases_after_hold`,
  `::test_named_zone_to_home_releases`, `::test_boot_settle_suppressed_arriving_old_state_taints`,
  `::test_boot_rebuild_away_locked_taints`, `::test_boot_recheck_arriving_never_releases_even_resident_home`,
  `::test_taint_persisted_across_restart_two_rigs`, `::test_manual_unlock_memory_survives_arriving`,
  `::test_manual_unlock_memory_survives_tainted_boot_recheck`, `::test_guest_clock_clears_taint`,
  `::test_every_reason_none_site_clears_flags` (parametrised: SC disable, hazard, kill switch, `_after_release`,
  vacation person arrival), `::test_reason_assignments_structurally_guarded`, `::test_override_set_bypasses_taint`,
  `::test_reason_none_arriving_no_unlock`, `::test_guest_yield_hold_unchanged_with_taint`,
  `::test_replay_body_only_cluster_zero_house_releases`, `::test_replay_real_arrivals_release_by_person`.
- **Test changes to existing files (each listed in the build commit with old/new expectation; deleting one is a review
  finding):**
  - *Real flips* (ARRIVING releasing IS the property under test): `test_sc_garage_lockout.py:172-178`
    (`test_boot_recheck_releases_boot_unknown_lock_when_arriving` -> asserts `arriving_hold`, 0 unlocks, renamed
    `..._holds_...`); `:512` (drop the `arriving` param; keep `waking` / `home_day`); `:892-897`
    (`test_arriving_releases` -> asserts no release while engaged, plus a reason-NONE variant).
  - *Trigger swaps* (ARRIVING is only an incidental second release proving another property; F14): `:2512` (failed
    spawn does not leave the latch stuck: use a fresh resident `not_home -> home` edge, or a `waking` edge after
    `sleep`), `test_sc_garage_lockout_review_c.py:209` (latch clears after read-back exhaustion: same swap). Each
    swapped test must still fail when its original property is broken; review C drills one of them.
  - *No change:* `test_sc_garage_lockout.py:2329`, `test_sc_garage_lockout_review_c.py:52` (verify during build; if
    either asserts an ARRIVING unlock, treat it as a swap and list it).
  - `test_house_state_rung2a.py` is untouched in this cycle (auto-follow unchanged, §13).
- **Live:** in-suite only while the switch is off (L6). After the operator turns the lockout on: snapshot attributes
  `lock_regime_arriving_taint` / `_episode_saw_arriving` / `_arriving_holds` exist on
  `sensor.ura_security_coordinator_security_armed_state`; on the first body-only ARRIVING in an episode,
  `lock_regime_garage_lockout_last_action.action == "arriving_hold"`; real arrivals show `person:*` triggers. A
  `decision_log` scan for `lock_regime_release` with context `house_state:arriving` is meaningful only after the switch
  is on (it is trivially empty before).

### D3: trip-wire: an unlock on a house-state trigger in a tainted episode pages NM

1. In `_release`, AFTER the entity loop and `_after_release` (so `written` is known), compute
   `violation = bool(written) and (trigger.startswith("house_state:") or trigger == "boot_recheck") and saw_before`,
   where `saw_before` is `self._episode_saw_arriving` captured at the TOP of `_release` (before `_after_release` clears
   it). Exempt `house_state:waking` and edges the caller marks as override (pass `override=True` through
   `_release(..., override=...)` from `on_house_state_changed` only; default False). If `violation` and
   `LOCK_RELEASE_UNCORROBORATED_TRIPWIRE_ENABLED`: `self.uncorroborated_releases += 1`,
   `_record("uncorroborated_release", ...)`, and `_spawn` one NM HIGH: `hazard_type="lock_release_uncorroborated"`,
   `location="garage_lockout:house_state"`, title "Garage lockout released without a resident arrival", message names
   the trigger, the reason and `self._last_house_edges` (a `deque(maxlen=4)` of `(new, old, trigger, ts)` appended in
   `on_house_state_changed`; F20).
2. It observes, never blocks. Expected steady state: zero fires. Independence from the gate: the saw flag has its own
   set statements (§D1 item 2), so removing the taint set (M3) or neutering the gate (M1/M2) leaves D3 seeing it. Both
   flags share the clear helper; a clear-site bug is covered by `test_every_reason_none_site_clears_flags`, not by D3
   (stated so nobody claims more).
3. Boot channel covered: the saw flag is persisted and also set by `_boot_rebuild` / `_boot_recheck_regime` (F5/H1).
4. Snapshot key `lock_regime_uncorroborated_releases`.

#### Acceptance criteria
- **Verify:** with D1's ARRIVING branch mutated back to `release`, the body-only fixture with the lockout locked fires
  exactly one NM HIGH `lock_release_uncorroborated`, and the release still happens.
- **Verify:** real-arrival chain (edge, ARRIVING, HOME_*) fires 0.
- **Verify:** release with nothing locked (`written == []`) never pages (F7/L2).
- **Verify (boot channel, two rigs + DictStore, no direct flag assignment):** rig 1 engaged + ARRIVING; rig 2 boots with
  house `arriving` and the D1 boot `arriving_hold` branch mutated to release -> 1 page.
- **Verify:** `house_state:waking` release in an episode whose saw flag is set (boot-suppressed SLEEP) -> 0 pages;
  `override_set` HOME_* release -> 0 pages.
- **Test:** `test_lock_release_arriving.py::test_tripwire_fires_on_house_state_unlock_when_gate_bypassed`,
  `::test_tripwire_silent_on_real_arrival_chain`, `::test_tripwire_silent_when_nothing_written`,
  `::test_tripwire_covers_boot_recheck_channel_two_rigs`, `::test_tripwire_waking_and_override_exempt`,
  `::test_tripwire_disabled_by_constant`. Seams: patch `_edge_decision`'s return or edit one branch; never assign
  `_episode_saw_arriving` / `_arrival_taint` directly (F17, Bug Class #62).
- **Live:** `lock_regime_uncorroborated_releases` present and 0; no NM rows with `hazard_type =
  lock_release_uncorroborated` after the switch is on.

### D4: trip-wire: a resident arrived (or came back uncounted) and the lockout is still locked

1. **Engage counter.** `self.engage_seq: int = 0`, incremented in `_async_engage` immediately before the
   `lock.lock` call (after `_engage_inflight[ent] = ...`, still with no await between predicate and call; INV-2
   unchanged). `release_gen` is not used (F2/H3a).
2. **Failure stamp.** `_notify_failure` writes `self._failure_nm_at[ent] = self._ts()` at entry (garage policy only).
3. **D4a schedule.** In `_process_person_edge`, immediately AFTER the S1 `self._release(f"person:{pid}", ...)` call
   returns: if the kill switch is on and `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S > 0`, capture `anchor = self._ts()` and
   `seq = self.engage_seq`, cancel any existing `_still_locked_unsubs[pid]`, and schedule
   `self._call_later(hass, STILL_LOCKED_S, functools.partial(self._on_still_locked, pid, anchor, seq, "arrival"))`
   (`@callback`, partial, never a lambda; F22). The timer anchor is the S1 call, which is after the hold (F3).
4. **D4b schedule (INV-REAL-B).** In the same resident branch, when `new_val == "home"`, `old_val in _UNREAL_STATES`,
   `_arrival_counts(...)` is False, the kill switch is on, `self.reason != REASON_NONE`, and the house reads `away` or
   `arriving`: record `arrival_uncounted`, increment `self.uncounted_returns`, and schedule the same timer with kind
   `"uncounted"`.
5. **`_on_still_locked(pid, anchor, seq, kind)`:** pop the handle; return if torn down, kill switch off, or
   `self.engage_seq != seq`. For each lockout entity reading exactly `locked` (unavailable skipped): skip it if
   `_failure_nm_at.get(ent, 0) >= anchor` (the failure NM already told the operator; H3b dedup); otherwise send one NM
   HIGH: kind `arrival` -> `hazard_type="lockout_locked_after_arrival"`, title "Garage still locked after <name> got
   home"; kind `uncounted` -> `hazard_type="lockout_locked_resident_uncounted_return"`, title "<name> may be locked out
   of the garage" (message: their phone was offline when they left, so the arrival did not count; unlock from the app).
   `location=f"garage_lockout:{kind}:{pid}"`. Increment `self.still_locked_pages`.
6. Teardown unsubscribes every `_still_locked_unsubs` handle (next to `_held_edges`). Not persisted (a restart drops a
   pending check; named).
7. Snapshot keys `lock_regime_still_locked_pages`, `lock_regime_uncounted_returns`.

#### Acceptance criteria
- **Verify:** S1 `_release` call neutered (only that call), resident edge with the lockout locked -> NM HIGH
  `lockout_locked_after_arrival` at `STILL_LOCKED_S` after the edge.
- **Verify:** normal release (lock reads `unlocked` by then) -> no NM.
- **Verify (F2 repro):** reason NONE, lockout unlocked, resident edge at T; SLEEP engage edge at T+30 locks -> no NM
  at T+90 (`engage_seq` moved).
- **Verify:** a second resident's S1 at T+30 does not silence a stuck first lockout (rev 1's `release_gen` would).
- **Verify (H3b dedup):** unlock fails twice -> exactly one `lockout_release_failed` page and no D4 page.
- **Verify (D4b):** engaged, house `away`, resident `_last_real == home`, edge `unavailable -> home` rejected -> page
  `lockout_locked_resident_uncounted_return` at `STILL_LOCKED_S`; same edge with house `home_night` -> no page.
- **Verify:** `STILL_LOCKED_S - GARAGE_LOCKOUT_READBACK_S * (GARAGE_LOCKOUT_READBACK_RETRIES + 1) >= 30` (test asserts the
  inequality; 30 s covers two blocking unlock calls; F3/H3b).
- **Test:** `test_lock_release_arriving.py::test_still_locked_after_arrival_pages`,
  `::test_still_locked_silent_after_unlock`, `::test_still_locked_silent_after_later_engage`,
  `::test_still_locked_not_silenced_by_second_resident_release`, `::test_still_locked_dedups_release_failed_nm`,
  `::test_uncounted_return_pages_when_house_away`, `::test_uncounted_return_silent_when_house_home`,
  `::test_still_locked_cancelled_on_teardown`, `::test_still_locked_window_zero_disables`,
  `::test_still_locked_bound_exceeds_readback_chain`.
- **Live:** in-suite until a real arrival with the switch on; README states it.

### D5: docs in the same commit
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`: §1 row 83 and §7 line 677 (ARRIVING no longer releases; HOME_* does not
  release in a tainted episode; real arrivals release by the person path; uncounted returns page); row 90 marker
  (hold shipped v5.108.13); add a §10 ledger entry: "ARRIVING releases the garage lockout" is wrong after this cycle.
- `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5: one paragraph (house state is not identity; access needs a resident edge).
- `GUEST_MODE.md:119`, `SECURITY_COORDINATOR.md:566-568` (L4). `SECURITY_COORDINATOR.md:118` gets a note that the
  auto-follow ARRIVING disarm is unchanged and parked (§13).
- README: the behaviour changes in D1, D3/D4 trip-wires, §13 status, the Live table.

---

## 5. Emission / decision-site enumeration (re-run independently by both plan reviews; complete)

`grep -n "self\._release(" security_lock_regime.py`:

| Site | Trigger | In scope? | Change |
|---|---|---|---|
| `:810` `on_house_state_changed` | `house_state:{new}` | yes | D1 gate; D3 observes |
| `:929` boot recheck (`functools.partial`) | `boot_recheck` | yes | D1 item 6; D3 observes |
| `:1058` `_apply_arrival` | `arriving_signal` | no (person path) | none; never clears taint |
| `:1071` `on_hazard` | `hazard` | no | reason NONE `:1072` -> clear helper |
| `:1098` kill switch off | `kill_switch_off` | no | `:1099` -> clear helper |
| `:1221` S1 | `person:{pid}` | release path | D4a schedule; never clears taint |
| `:1224` approach zone | `approach_zone:{pid}` | no | none |
| `:1348`, `:1566` proximity | `proximity:{sid}` | no | none |
| `:2039` backstop | `backstop` | discharge | `_after_release` `:1701` -> clear helper |
| `:779` SC-disable loop | direct `lock.unlock` | no | `:767` -> clear helper |
| `:1786` read-back retry | inherits trigger | no | none |

`self.reason = ` writes: `:630/:632/:634` (`_boot_rebuild`), `:648/:650` (`_on_boot_recheck`), `:767`, `:876`
(`_set_engage_reason`), `:911` (guest-night boot rebuild in recheck; same episode, no clear), `:993` (guest clock ->
routed through `_set_engage_reason`), `:1072`, `:1099`, `:1701`, `:1708`. `:935` / `:950` call `_set_engage_reason`.
`_edge_decision` callers: `:807`, `:912`. Auto-follow disarm `security.py:1453` (unchanged). `SIGNAL_HOUSE_STATE_CHANGED`
producer: `presence.py:9314-9322` (inference `:8332`, boot-settle override `:2693`).

House-state paths into HOME_* while engaged: ARRIVING -> HOME_* (tainted, held); boot-settle-suppressed ARRIVING then
`arriving -> HOME_*` (old_state taints, held; H2); AWAY -> HOME_* (override only, `override_set`, releases as today);
GUEST -> HOME_* (held if tainted, F18); HOME_* -> HOME_* (held while tainted); WAKING -> HOME_DAY (after SLEEP, taint
cleared). Restart with house restored HOME_* and no taint in the store: untainted; boot recheck releases a
BOOT_UNKNOWN lock as today (`:885-887`). This is outside INV-ARR because the regime never observed ARRIVING (residual
§9.3).

---

## 6. Numbers and knobs

| Name | Value | Rung | Why | Off value |
|---|---|---|---|---|
| `LOCK_RELEASE_UNCORROBORATED_TRIPWIRE_ENABLED` (NEW) | True | 1, `const.py` | safety observer; changing it should need review. No window: with F1 the trip-wire needs no evidence window, which removes the F15/L3 coupling | False = D3 off; D1 unaffected |
| `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S` (NEW) | 90 | 1 | anchored at the S1 call (post-hold); must exceed read-back × (retries + 1) = 40 s plus ≥ 30 s for two blocking unlock calls; 90 is about when a resident at the door notices | 0 = D4a and D4b off |
| `GARAGE_LOCKOUT_ARRIVAL_HOLD_S` | 5 | 3 (Number, existing, max 60) | unchanged; not in D4's bound (anchor is after the hold) | 0 = no hold |
| `GARAGE_LOCKOUT_REENGAGE_DELAY_S` | 900 | existing option | unchanged | existing |
| `GARAGE_LOCKOUT_BLIP_MIN_AWAY_MIN` | 15 | 1, existing | unchanged; defines D4b's "uncounted" set | n/a |
| Morning backstop | live 60 | 3, existing | the bounded discharge for a tainted sleep-like episode | existing |

Every evidence window for auto-follow (`..._EVIDENCE_WINDOW_S`, `..._ARRIVING_CORROBORATION_WINDOW_S`) lives in §13.

---

## 7. Per-site anchors and mutation drills (review C runs these; the builder pre-runs them)

| # | Site | Mutation | Test that must go RED |
|---|---|---|---|
| M1 | `_edge_decision` arriving branch | return `("release", None)` when engaged | `test_body_only_arriving_does_not_release_sleep`; `test_tripwire_fires_...` asserts the NM (GREEN-with-page) |
| M2 | `_edge_decision` HOME_* taint check | delete the condition | `test_arriving_then_home_star_chain_holds_until_backstop`, `test_vacation_tainted_home_edges_never_release` |
| M3 | taint set in `on_house_state_changed` (new == arriving) | remove the taint statement only | M2's tests; `test_tripwire_fires_...` still pages (D3 independence) |
| M3b | taint set on `old_state == "arriving"` | drop the old-state disjunct | `test_boot_settle_suppressed_arriving_old_state_taints` |
| M4 | taint key in `_store_payload` | drop it | `test_taint_persisted_across_restart_two_rigs` (two rigs, one `DictStore`) |
| M5 | boot recheck `arriving_hold` branch | release instead | `test_boot_recheck_arriving_never_releases_even_resident_home`; `test_tripwire_covers_boot_recheck_channel_two_rigs` pages |
| M6 | `arriving_hold` branch | call `_clear_manual_unlock` | `test_manual_unlock_memory_survives_arriving` |
| M6b | boot `ended` guard | drop `"arriving_hold"` from the exclusion | `test_manual_unlock_memory_survives_tainted_boot_recheck` |
| M7 | clear helper call at `:1072` (one representative reason-NONE site) | remove the call | `test_every_reason_none_site_clears_flags[hazard]` |
| M7b | clear helper in `_set_engage_reason` | remove | `test_guest_clock_clears_taint` |
| M7c | F1 guard: clear helper wrongly added to `_after_release` arrival branch | add the call | `test_person_release_keeps_taint_later_home_star_held` |
| M8 | `_boot_rebuild` away/arriving taint set | remove | `test_boot_rebuild_away_locked_taints` |
| M9 | saw-flag set in `on_house_state_changed` | remove the saw statement only | `test_tripwire_fires_...` (no page) |
| M10 | saw-flag store key | drop | `test_tripwire_covers_boot_recheck_channel_two_rigs` |
| M11 | D3 `written` guard | drop `bool(written)` | `test_tripwire_silent_when_nothing_written` |
| M12 | D4a schedule | remove the `_call_later` | `test_still_locked_after_arrival_pages` |
| M13 | `engage_seq` increment | remove | `test_still_locked_silent_after_later_engage` |
| M14 | D4 failure-stamp dedup | drop the `_failure_nm_at` test | `test_still_locked_dedups_release_failed_nm` |
| M15 | D4b schedule | remove | `test_uncounted_return_pages_when_house_away` |
| M16 | S1 `_release` (INV-REAL anchor, pre-existing) | delete the call | `test_real_arrival_edge_before_arriving_releases`, `..._after_arriving_releases_8632_shape` |
| M17 | `override` bypass | ignore `override` | `test_override_set_bypasses_taint` |
| M18 | swapped test `:2512` original property | break the spawn-latch clear | the swapped test still goes RED |

Restore and `git status` clean after every drill; `PYTHONDONTWRITEBYTECODE=1` and clear `__pycache__` (stale-pyc memory).
No test may assign `_arrival_taint`, `_episode_saw_arriving` or `engage_seq` directly; seams are a patched return or a
neutered call (F17).

---

## 8. Config-extreme and combinatorial tests

All in `quality/tests/test_lock_release_arriving.py` on `_lockout_harness.py`; the real-hass file
`test_sc_garage_lockout_real_ha.py` gets one end-to-end copy of the body-only fixture and the 8632 fixture.

| Case | Expectation |
|---|---|
| hold = 0 and hold = 60 (Number max), edge before/after ARRIVING | INV-REAL; release at edge / edge + hold; D4 anchored after hold, no false page |
| `security_lockout_excluded_persons` = everyone (no residents) | ARRIVING never releases; sleep-like reasons: backstop releases; VACATION: nothing releases until switch/hazard/override (L5); D3/D4 silent |
| reason `guest_night` + guest toggle + ARRIVING in window, then the yield edge | no release; `guest_yield_hold` record type unchanged |
| reason `vacation`, VACATION -> ARRIVING -> HOME_* -> SLEEP -> WAKING | held until WAKING releases (F12b) |
| reason `boot_unknown` + ARRIVING | held; backstop releases |
| kill switch ON -> OFF in a tainted episode | OFF releases once, reason NONE, flags cleared (INV-5 unchanged). (Rev 1's "OFF during ARRIVING, ON after" row deleted: vacuous, F13) |
| `LOCK_RELEASE_UNCORROBORATED_TRIPWIRE_ENABLED` False | D3 silent; D1 unaffected |
| `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S` = 0 | D4a/D4b off |
| re-engage delay 0 / max after a night person release with ARRIVING following | re-engage per the knob (abandoned if house not SLEEP); ARRIVING never cancels it; taint stays |
| ARRIVING -> AWAY -> ARRIVING flap x5, then a resident edge | 0 releases during the flap; exactly 1 at the edge |
| restart between ARRIVING and HOME_* (taint persisted) | boot recheck holds |
| restart during boot settle, ARRIVING suppressed, first edge `arriving -> home_night` (H2) | held |
| SC disable during a tainted episode, re-enable | flags cleared at `:767` |

---

## 9. Non-goals, scoped-out items, residuals

- No change to presence `infer` or the ARRIVING producer.
- No identity / face requirement for any release; no change to the face corroboration gate.
- No change to the away lock, door-lock unlocks, hazard egress, proximity, backstop arithmetic.
- No new config-flow field or Number entity.
- Not turning the lockout or auto-follow on (operator's decision on return).
- Security auto-follow: unchanged in this cycle (§13, parked sibling).

### 9.1 Parked `LOCK-REGIME-BOOT-REALLY-AWAY-1` (M4): sequenced after this cycle, not absorbed
Its trigger (lockout ON) fires with this cycle. Interaction: after D1, `_arrival_counts` / `_really_away` (`:1350-1367`)
is the only house-independent release for `unknown/unavailable -> home`, and ARRIVING is no longer a fallback.
Tightening M-2 (ii) naively would drop post-restart `unavailable -> home` arrivals with no release. Disposition, to be
written on that card by the orchestrator: (1) plan it next, Tier 2; (2) its fix must scope the tightening to
camera-derived arrivals (`arrival_source_needs_corroboration`) or prove INV-REAL with a joint restart test
(`unavailable -> home` resident after a restart, past 600 s, really away before the restart -> unlock); (3) D4b covers
the miss as a page if the tightening ships first. Absorbing it here would add a recorder-seed ingredient to a Tier-3
cycle for a face path that is off by default (`FACE_ARRIVAL_INTERIOR_ENABLED` False).

### 9.2 Exterior-person severity on body-only ARRIVING (M6): scoped out, card needed
`const.py:2799` maps `arriving` to LOW (AWAY = CRITICAL), consumed by `perimeter_alert.py:95`. A body-only ARRIVING
therefore softens exterior-person alerts with no identity, which conflicts with manual §5.5(a) (de-escalation needs
≥ 0.9 identity). Not fixed here (different consumer, different blast radius: alert routing, not access). Card to mint
(orchestrator, adjacency sweep first; grep of the board for `SEVERITY_BY_HOUSE_STATE` = 0 hits):
`EXTERIOR-PERSON-SEVERITY-ARRIVING-BODY-ONLY-1`, Tier 2, fix shape: treat `arriving` like the state it came from
(`old_state`) unless a resident edge exists, or map it to the AWAY row.

### 9.3 Residuals (named, accepted)
- A restart whose boot-settle window swallows the WHOLE AWAY -> ARRIVING -> HOME_* excursion, with the house restored
  HOME_* and no taint saved: the boot recheck releases a BOOT_UNKNOWN lock as today (`:885-887`). The regime cannot
  observe an ARRIVING it was never told about. Bounded: needs the excursion entirely inside boot settle.
- A pending D4 check is lost on restart.
- Phoneless arrivals in a VACATION episode with the house still reading VACATION have no backstop (unchanged).
- Rescue release for uncounted returns is parked (§11 Q4); revival trigger: D4b pages on a real arrival.

Parked (rev 1, unchanged): "require a named identity or an independent edge for every ARRIVING-driven release".
Revive if resident tracker edges stop leading ARRIVING, measured by D4a firing.

---

## 10. Tier

Tier 3. Triggers: a release value threaded through a state machine with several decision sites (edge, boot recheck,
manual-unlock memory, store, eleven `reason` writes) where one missed site is a silent unlock (Bug Class #53);
access-safety impact; operator constraint against lockout. Plan review: the two Tier-3 reviews are done; rev 2 applies
them; a focused re-review of §2, §4 D1 items 2-6 and §12 is recommended before build (rev 2 changed the clear rule and
added the boot sets). Build: `ura-super-builder` in a worktree. Code review: four framings A/B/C/D, D attacking INV-ARR
with legal-config repros including restarts; orchestrator re-greps §5 (`self._release(` and `self.reason = `) and re-runs
M1, M3b, M5, M7c, M16 before ship; operator checkpoint before deploy (back ~11-16; lockout stays off until then).

---

## 11. Operator decisions (none block the build; defaults are what gets built)

1. **Night re-lock after a person release.** The resident's edge unlocks; the 900 s re-engage only fires if the house
   is back in SLEEP; in practice the next HOME_NIGHT -> SLEEP edge re-locks, as today. The episode now stays open
   until morning (backstop, manual-unlock memory kept). **Recommendation: keep.**
2. **House-sitter / phoneless person during VACATION or a night episode.** No remote-open on ARRIVING; they get in by a
   resident's phone edge, the morning backstop (sleep-like), a manual house-state override to HOME_*, the HA app, or
   the switch. If the house leaves VACATION and later reaches SLEEP, the next WAKING releases. **Recommendation: accept;
   for a planned house-sitter, turn the lockout off or add them as a tracked person.**
3. **Security auto-follow ARRIVING disarm (rev 1 D2).** Parked as a sibling plan (§13). **Recommendation: keep
   auto-follow off; revive §13 when you want auto-follow on.**
4. **Uncounted returns (phone offline when leaving).** Page (D4b) or rescue-release? **Recommendation: page.** A rescue
   release keyed on "house away/arriving + unavailable -> home" re-opens the phantom hazard for a sleeper whose phone
   flaps during a false AWAY; D0 measures the shape.

---

## 12. Fix table (rev 1 -> rev 2)

| Finding | Change in rev 2 |
|---|---|
| F1 (HIGH) | Taint cleared only at episode boundaries (§2 definition, D1 item 3); never on person/approach/proximity/arriving_signal releases; INV-ARR escape (a) deleted; M7c guards it; new test `test_person_release_keeps_taint_later_home_star_held` |
| F2 (HIGH) / H3a | `engage_seq` bumped at `lock.lock` in `_async_engage`; D4 compares it; captured after the S1 call; F2 repro test; second-resident test |
| F3 (HIGH) / H3b | Timer anchored at the S1 call (post-hold); bound = read-back × 2 + 30 s margin, asserted in-test; dedup against `lockout_release_failed` via `_failure_nm_at` |
| F4 (HIGH) | No level read of person state remains in D1/D3/D4 (boot recheck never releases on `arriving`; D3 needs no evidence). The level leg moves to §13 with `person_state_for_trust` required |
| F5 (HIGH) / H1 | Saw flag persisted; also set by `_boot_rebuild` (house away/arriving) and `_boot_recheck_regime` (house arriving); boot test uses two rigs + `DictStore`; no direct flag assignment |
| F6 / M7 | `ended` excludes `arriving_hold`; drill M6b; restart test |
| F7 / L2 | D3 pages only when `written` is non-empty; M11 |
| F8, F9, F10, M1, L1 | D2 moved to §13 with these findings attached as requirements |
| F11 / M3 | One helper `_end_episode_arrival_flags`; called in `_set_engage_reason`, guest clock (routed through it), boot rebuild/recheck SLEEP/VACATION, and all five `reason = NONE` writes; structural guard test; drills M7/M7b |
| F12 / L5 | Behaviour text and §11 Q1/Q2 rewritten (re-engage needs SLEEP; VACATION releases via SLEEP -> WAKING; restart rebuilds `boot_unknown` only when the house no longer reads SLEEP/VACATION) |
| F13 | §8 row deleted; replaced by ON -> OFF in a tainted episode |
| F14 | Test list split into real flips (`:172`, `:512` param, `:892`) and trigger swaps (`:2512`, review_c `:209`); rung-2a items move with D2 (§13: swap `:383`, flip `:209` / `:457-474`) |
| F15 / L3 | Coupling removed: D3 has no window (boolean kill switch); evidence windows live only in §13 |
| F16 | `boot=True` flag dropped with `resident_home_evidence` (moved to §13) |
| F17 | §7 bans direct flag assignment; M4/M10 two-rig; drills added for saw-flag set, `ended`, engage suppression, override |
| F18 | Guest exit held in tainted episodes: named in README; manual override exempt via `override_set` (D1 item 4) |
| F19 | Named in README; test `test_reason_none_arriving_no_unlock` |
| F20 / L4 | Snapshot keys for taint, saw flag, holds, trip-wire counters; `_last_house_edges` ring for the D3 message; D5 adds GUEST_MODE.md, SECURITY_COORDINATOR.md and the `:857` comment |
| F21 | Replay ACs from audit §7 (a)/(b) via `_lock_arrival_replay.py` |
| F22 | D4 timers: `@callback` + `functools.partial`; unsubscribed at teardown |
| H2 | Taint also set on `old_state == "arriving"`; `_boot_rebuild` taints a restored away/arriving house; §8 case; §5 enumerates the path; the fully-swallowed excursion is a named residual (§9.3) |
| M2 | Boot "resident reads home" release deleted (not narrowed); `_arrival_since_setup()` recorded only |
| M4 | §9.1 disposition: sequence next, scope the tightening, joint restart test |
| M5 | INV-REAL-B + D4b page; D0 probe; rescue release parked (§11 Q4) |
| M6 | §3.3 row + §9.2 card `EXTERIOR-PERSON-SEVERITY-ARRIVING-BODY-ONLY-1` |
| L6 | Every Live row marked in-suite until the switch is on |

**Rejected or narrowed:**
- **M5's suggestion to arm the still-locked check at every `arriving_hold`** (rejected as stated): with a sleeper home
  during a phantom ARRIVING (48.6% of ARRIVING edges are false-AWAY corrections), "a resident reads home and a lockout
  reads locked" is the normal state, so it would page on most phantoms. Narrowed to an uncounted `unavailable/unknown
  -> home` edge while the house reads away/arriving (D4b).
- **F12(c) as written** ("a restart rebuilds `boot_unknown`"): true only when the house no longer reads SLEEP or VACATION
  at boot (`_boot_rebuild:629-634`); a house still reading VACATION rebuilds `vacation` (no backstop). Text uses the
  precise form.
- **F9's "re-check once on the regime's S1 stamp write"**: carried into §13 as one option, not adopted as the design;
  §13 lists it beside the simpler "evidence at the signal" gate for the sibling plan to decide.

---

## 13. Parked sibling: security auto-follow ARRIVING disarm (rev 1 D2)

**Status: PARKED, not built in this cycle.** Recommended default pending the operator: keep `security_auto_follow` off
(it is off, never fired, audit §6). Revival trigger: the operator wants auto-follow on. Then it becomes its own Tier-2
plan (`PLANNING_security_autofollow_arriving_evidence.md`, topic-named) with ONE plan review.

Rev 1 design (kept for the sibling): keep `"arriving": DISARMED` (removing it strands ARMED_AWAY after a real return,
HOME_* is unmapped `security.py:184-188`); gate the fire on resident evidence; pending disarm discharged by a later
resident non-camera arrival. It needs `_resident_home_edges` (stamp at the S1 write) and a public
`resident_home_evidence()` on the regime (fail closed when torn down).

Findings the sibling plan must resolve (all from the two reviews of rev 1):
- **F4:** the level leg ("a resident reads home") must use `person_state_for_trust(hass, pid)` and exclude `_held_edges`;
  edge readers stay raw.
- **F8 / M1:** the pending stamp must survive ARRIVING -> HOME_* (ARRIVING dwell ~60 s, HOME_* unmapped): clear it
  only on an intent for a mapped arm target (away / vacation / guest / waking), on expiry, or teardown. Test ARRIVING ->
  HOME_DAY at +60 s then geofence at +90 s -> disarm.
- **F9:** discharge must not trust raw `SIGNAL_PERSON_ARRIVING(geofence)` (stale-source blips, ledger #33). Options:
  require `resident_home_evidence()` True at the signal, or re-check once at the regime's S1 stamp write. Define the
  ordering between SC's arriving handler and the regime's `_on_person_event`.
- **F10 / M1:** `_handle_person_arriving_signal` is a sync `@callback`; `handle_disarm` is async. Reuse the
  `async_call_later(0, _fire_state_driven_arming)` / `_house_state_debounce_unsub` path (torn down at `security.py:950`),
  not a bare task. The gate sits AFTER the `new_armed == old_state` no-op check (`security.py:1430`).
- **F10 / L1 (rev 1 D3.2):** the auto-disarm trip-wire must name BOTH disarm call sites (fire path and discharge path),
  and must not recompute evidence through the same `resident_home_evidence()` as the gate (#56); exclude or separately
  instrument the discharge path.
- **F15 / L3:** separate constants: `SECURITY_AUTO_FOLLOW_ARRIVING_EVIDENCE_WINDOW_S` (gate) and the pending window;
  no sharing with any lock-regime trip-wire.
- **Tests to change when it ships (F14):** `test_house_state_rung2a.py:383` (de-escalation NM is MEDIUM: swap ARRIVING
  for `waking`), real flips at `:209` and `:457-474` (`arriving -> DISARMED` with no person evidence).

Until then: a body-only ARRIVING with auto-follow ON would disarm. The README states it, and the operator's §11 Q3
answer gates turning auto-follow on.
