# Plan review (Tier 3, framing 1: completeness): PLANNING_lock_release_on_arriving.md rev 1

> **Pointer (HOUSE-STATE step 1a, 2026-11-13):** `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE` cited below was a dead table (imported, read nowhere) and is deleted; the live source is `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY` (`const.py`). See `PLANNING_house_state_axes_step1.md` D5 and PRESENCE state-of-play §10 #37.

Branch `plan/lock-release-arriving` @ 1e3a54ee (base develop 519af938; the diff is the plan file only).
Reviewer read COMPLETELY, before reviewing: `docs/Coordinator/IDENTITY_FUSION_CAMERAS_MANUAL.md` (926 lines),
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (1027 lines), `docs/architecture/SENSOR_FLEET_CLASSES.md`,
plus the evidence audit `AUDIT_arriving_on_body_evidence_2026_11_13.md`. This closes the planner's §0.1 read-first gap.
No corrections-ledger claim is re-asserted here. Doc vs code: the only contradiction found is the one the planner
already logged (presence doc §1 row 83 / §7 line 677 omit the `reason != none` condition on HOME_*,
`security_lock_regime.py:861-864`); D5 fixes it. Code read: `security_lock_regime.py` 417-1110, 1139-1440, 1530-2050,
2477-2630; `security.py` 165-200, 1174-1470, 2290-2530; `presence.py` 1340-1400, 2680-2710, 9225-9330;
`house_state.py` 68-140; `person_coordinator.py` 1120-1140; `const.py` 2780-2875, 3860-3905; `number.py` 4440-4495.

**Verdict: FIX-PLAN.** 3 HIGH, 7 MEDIUM, 6 LOW. The §5 release-site enumeration is complete and correct. The gaps
are in the boot/restart channel, in state-clear completeness, in D4's guard, and in D2's discharge window.

---

## 1. Independent re-enumeration

### 1.1 Every path that can unlock a garage lockout, unlock a door lock, or disarm

`grep -rn '"unlock"\|handle_disarm(\|alarm_disarm'` over `custom_components/` plus `grep -n "self\._release("`:

| Site | Trigger / source | ARRIVING-driven? | Plan §5 | Verdict |
|---|---|---|---|---|
| `security_lock_regime.py:810` edge | `house_state:{new}` | yes | listed | in scope |
| `:929` boot recheck (`functools.partial`) | `boot_recheck` | yes (house `arriving` / HOME_*) | listed | in scope, see H1, H2, M1 |
| `:1058` `_apply_arrival` | `arriving_signal` (geofence / ble / corroborated camera_face) | no; producers `presence.py:5346` (geofence), `person_coordinator.py:1132` (ble), `presence.py:5605` (camera_face) all carry a person | listed | correct |
| `:1071` hazard, `:1098` kill switch off | hazard / switch | no | listed | correct |
| `:1221` S1, `:1224` approach zone, `:1348` / `:1566` proximity | person / proximity | no | listed | correct |
| `:2039` backstop | `backstop` | no | listed | correct |
| `:779` `_garage_release_on_disable_loop` | `sc_disabled` (direct `lock.unlock`) | no | listed | correct; note it sets `reason = NONE` at `:767` without the plan's taint clear (M3) |
| `:1786` `_on_readback` retry | re-spawn of an existing release | no | not listed | fine (inherits the original trigger) |
| `:2456` / `_away_release` (`:1060, :1074, :1088, :2133, :2169`) | away lock | no (person / boot / hazard / switch) | §3.3 "away lock not on this path" | correct |
| `security.py:2336` | hazard egress unlock | no | §3.3 | correct |
| `security.py:1453` `handle_disarm(source="auto_follow")` | auto-follow `arriving` / `waking` | yes (`arriving`) | listed | in scope, see H3 |
| `__init__.py:6601` `security_disarm` service | manual | no | not listed | fine |

`_edge_decision` callers: `:807`, `:912` only (confirmed). `SIGNAL_HOUSE_STATE_CHANGED` dispatch: one helper,
`presence.py:9225-9325`, payload always has `old_state`.

### 1.2 Consumers of house-state ARRIVING / HOME_* with a security effect

grep `"arriving"` / `HouseState.ARRIVING` repo-wide. Access consumers are the two in plan §3.3. **One security
consumer is missing from §3.3:** `const.py:2791-2800` `NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE["arriving"] = "LOW"`
(AWAY = CRITICAL). A body-only ARRIVING de-escalates exterior-person alerts (M6). All other readers are non-security
(HVAC `hvac.py:2856`, `hvac_const.py:229`, aggregation layer 3, NM colour, routine forecaster, memory facade).

### 1.3 Parked-plan triggers this cycle fires

`LOCK-REGIME-BOOT-REALLY-AWAY-1` (parked, `kanban.data.yaml:34318`) has trigger "garage lockout ON", the same event this
cycle prepares for. `PLANNING_lock_suspicious_arrival_hold.md:347-348` says "its trigger fires at the same moment, so
plan it next." The plan does not mention it (M4). No other parked lock/presence item fires.

---

## 2. Findings

### HIGH

**H1. D3 cannot see the boot-recheck channel, so its Bug Class #56 coverage claim fails.**
`_episode_saw_arriving` is not persisted (D3.1 says it is an independent RAM flag), and a restored house state is never
replayed as an edge: `_dispatch_house_state_change` returns while boot settle is pending (`presence.py:9249-9258`), and
the only boot-time dispatch is an override (`presence.py:2690-2698`). The existing test shows this shape:
`test_sc_garage_lockout.py:175` (`rig.mgr.house_state = "arriving"  # restore lands late, no signal`). After a restart,
the flag is False at the 120 s recheck. So D3 acceptance bullet 3 ("D1 boot branch mutated to release, fires 1") and
`test_tripwire_covers_boot_recheck_channel` cannot pass as specified. The same holds for a persisted-taint HOME_* recheck
(M5 drill): D3 is blind there too.
Fix: persist the flag next to `garage_arrival_taint`, and/or have `_boot_recheck_regime` treat a restored house `arriving`
(or a restored taint) as "saw arriving". State this in D3.

**H2. INV-ARR leaks when the ARRIVING edge itself is never seen. The plan ignores `old_state`.**
The taint is set only when `new == "arriving"`, but the regime reads only `new_state` (`security_lock_regime.py:800-803`).
Repro (legal config, lockout on, defaults): SLEEP lockout engaged, residents asleep. False SLEEP -> AWAY at 03:00
(46 historical, rarer since v5.108.1 but legal). HA restarts at 03:05: house restored AWAY, lockouts `locked`, so
`_boot_rebuild` sets `REASON_BOOT_UNKNOWN` (`:634`). During boot settle, infer goes AWAY -> ARRIVING on a zone sensor,
and the dispatch is suppressed (`presence.py:9249`). After settle, ARRIVING -> HOME_NIGHT is dispatched with
`old_state: "arriving"`. The taint is False, so `_edge_decision("home_night")` returns `release` (reason != NONE,
`:861-863`), and `_after_release` ends the episode. The 120 s boot recheck releases on the same `_edge_decision`
(`:912, :926-929`). The house passed through ARRIVING since the engage and there is no resident edge.
Fix: also set the taint when `payload["old_state"] == "arriving"` (always present, `presence.py:9318`). Add a §8 case:
"ARRIVING suppressed by boot settle, first seen edge is arriving -> HOME_*". Separately, the plan should say whether a
boot-recheck HOME_* release of a `BOOT_UNKNOWN` lock in a house that reached HOME_* through a suppressed ARRIVING is
inside INV-ARR. Today that release is designed behaviour (`:885-887`) and is not ARRIVING-driven.

**H3. D4's guard is wrong per code, and its number fails the plan's own inequality.**
(a) `release_gen` is incremented only in `_release` (`:1587`) and the SC-disable path (`:761`). An engage never
increments it: `_request_engage` only snapshots it (`:1856-1863`). D4's "no newer engage (`release_gen` unchanged)" and
acceptance bullet 2 ("a re-engage before 90 s (`release_gen` bumped by an engage)") contradict the code.
Consequences: a resident arrives at 22:59 and a SLEEP edge at 23:00:30 engages, so at 90 s the lockout reads `locked`,
the generation is unchanged, and D4 sends a false HIGH page. Conversely, a second resident's S1 within 90 s bumps the
generation and silences a lock that is really stuck.
Fix: add an engage counter or an engage timestamp, bumped in `_async_engage` when `lock.lock` is issued, and compare
that.
(b) The plan requires `LOCK_RELEASE_ARRIVAL_STILL_LOCKED_S > hold Number max + readback + retry` and asks the build to
fail a test if it breaks. Hold max is 60 s (`number.py:4488`). Readback is 20 s (`const.py:3901`) with 1 retry
(`:3902`), so 60 + 40 = 100 s > 90 s, and the build test fails on day one. The inequality is also mis-derived: D4 is
scheduled at the S1 `_release` call, which runs after the hold (`_on_hold_confirm` -> `_process_person_edge`,
`:1340`), so the hold does not add. Pick one anchor (person edge -> ≥ 100 s plus margin; S1 call -> > 40 s plus unlock
latency) and restate the number. The overlap with `lockout_release_failed` (~40 s, `:1789`) produces two HIGH pages for
one failed unlock; state a dedup or accept it by name.

### MEDIUM

**M1. D2's discharge window is really the ARRIVING dwell (60 s), not 120 s, and a miss strands ARMED_AWAY with residents home.**
The pending stamp is "cleared by any later house-state intent". ARRIVING has a 60 s minimum dwell
(`house_state.py:131`) and moves to HOME_*, which is unmapped (`security.py:1265`, no disarm ever). A resident GPS edge
landing more than about 60 s after ARRIVING finds no pending stamp. The house then stays `armed_away` with residents
inside, which is the hazard D2.1 cites as the reason to keep the mapping. The acceptance tests (121 s expiry) hold the
house in ARRIVING, so they miss this.
Fix: let the pending stamp survive the ARRIVING -> HOME_* edge (clear it only on a mapped arm target or on expiry), and
test ARRIVING -> HOME_DAY at +60 s followed by geofence at +90 s.
Separately: `_handle_person_arriving_signal` is a sync `@callback` (`security.py:2381-2382`) and `handle_disarm` is
async (`:2503`), so "run the same `handle_disarm` path" requires a task. Specify reuse of the
`async_call_later(0, _fire_state_driven_arming)` / `_house_state_debounce_unsub` path, which is torn down at `:950`, not
a bare `async_create_task` (untracked background task).
D2 is separable and not a gate for 11-16, but it must not ship in this shape.

**M2. INV-ARR (b) and D1.4 accept "a resident reads `home`" as arrival evidence. During a sleep-like episode, that is the steady state.**
48.6% of ARRIVING edges are false-AWAY corrections with residents home (audit §3.1). `_boot_rebuild` rejects exactly
this rule (`:611-618`, review A H1: HA's restore makes residents read `home` at boot).
Repro: SLEEP lockout, false SLEEP -> AWAY -> ARRIVING, restart while house is `arriving` (boot settle slow, test `:175`
shape). Sleepers read `home`, so the recheck releases with `boot_recheck` and `_after_release` (`:1695-1705`) ends the
episode with no re-engage.
Fix: REUSE `_arrival_since_setup()` (`:969-974`, a resident release since setup), or require a `_resident_home_edges`
stamp since setup, not a live `home`. Apply the same change to D3's boot exemption.

**M3. The taint and `_episode_saw_arriving` clear sites miss non-edge engages and non-release reason resets.**
D1.1 clears on "engage-kind edges", `waking`, `_release`, hazard, kill switch, and `_after_release` NONE. It misses:
- the guest-clock engage (`_on_guest_clock` `:993-995`, not an edge);
- the boot-recheck engage (`:958-961`);
- the boot-window engage edge that only rebuilds (`:827-832`, the clear must sit before that return);
- the SC-disable path `reason = REASON_NONE` (`:767`).

Repro for a stale taint: reason VACATION, VACATION -> ARRIVING (taint) -> HOME_DAY (held) -> GUEST, then the guest
clock engages GUEST_NIGHT with the taint still set. The morning HOME_* edge is held, and release waits for the
backstop.
Fix: clear in `_set_engage_reason` / `_request_engage` and at every `self.reason = REASON_NONE` site (`:767, :1072,
:1099, :1701, :1708`) instead of listing edges. Add a mutation drill for one of them. M7 covers only `_release`.

**M4. Parked `LOCK-REGIME-BOOT-REALLY-AWAY-1` fires on the same trigger and interacts with D1.**
D1 makes `_arrival_counts` / `_really_away` (`:1350-1367`) the only house-independent arrival release. The parked card
proposes tightening M-2 (ii) (`:1362-1363`). Done naively, that would leave `unknown/unavailable -> home` arrivals after
a restart with no release, and ARRIVING is no longer a fallback. The plan must disposition the card: absorb it, sequence
it, or state the interaction and a joint test.

**M5. INV-REAL is narrower than the operator's constraint, and D4 is silent on the gap.**
INV-REAL covers only edges `_arrival_counts` accepts. A resident whose departure was never seen (phone unavailable on
leaving, so `_last_real` stays `home`) returns `unavailable -> home`. `_really_away` returns False (`:1365-1366`), so
there is no S1. Before this cycle the house ARRIVING edge released in that case; after it, the lockout stays locked
until the backstop. D4 is armed only at the S1 call, so it never fires.
Fix: name the residual in §1/README, and consider arming the "still locked" check at each `arriving_hold` (a resident
reads `home` and a lockout reads `locked` N s later -> page). That covers the arrival that counted for nothing.

**M6. Forward trace misses a security-suppress consumer of body-only ARRIVING.**
`const.py:2799` maps `arriving` to LOW exterior-person severity (CRITICAL in AWAY). Under manual §5.5(a), de-escalation
needs ≥ 0.9 identity. This can be out of scope, but it must appear in §3.3 and §9, with a card.

**M7. Boot recheck `ended` still clears manual-unlock memory on a tainted HOME_*.**
`ended = kind == "release" or (kind != "guest_yield_hold" and house in _HOME_STATES ...)` (`:914-917`). With D1, a
tainted HOME_* returns `arriving_hold`, so `ended` is True and `_clear_manual_unlock` runs (`:918-923`). That
contradicts D1 acceptance bullet 6 on the restart path. Removing `"arriving"` from the tuple (D1.4) is not enough.
Fix: `kind not in ("guest_yield_hold", "arriving_hold")`, plus a restart variant of `test_manual_unlock_memory_survives_arriving`
and a drill.

### LOW

- **L1.** D3.2 (auto-follow trip-wire) recomputes evidence through the same `resident_home_evidence()` as the D2 gate.
  That is not independent (the #56 blind spot D3.1 deliberately avoids). On the D2 discharge path, presence's geofence
  listener and the regime's `person.*` listener have no defined order, so the stamp may not exist yet: a false HIGH,
  unless the discharge path is excluded by name.
- **L2.** D3.1 pages on releases that write nothing. Repro: ARRIVING -> HOME_* held, S1 at +130 s unlocks and clears the
  taint, and a later GUEST -> HOME_* or HOME_EVENING -> HOME_NIGHT edge with reason still sleep-like gives a
  `house_state:*` release with `written=[]` and no stamp in 120 s. Gate the page on a lockout reading
  `locked` / lock-pending.
- **L3.** `LOCK_RELEASE_TRIPWIRE_WINDOW_S` is also the `resident_home_evidence` window (D1.6). Zeroing the observer
  changes the D2 gate (Bug Class #63). Use two constants or document the coupling on the knob.
- **L4.** D5 misses `docs/Coordinator/GUEST_MODE.md:119` and `SECURITY_COORDINATOR.md:118` (both state that ARRIVING
  releases/disarms) and the `_edge_decision` comment `:857`. Deliverables do not list the `snapshot()` keys (`:2611`)
  that the Live criteria read (`lock_regime_arriving_holds`, `_uncorroborated_releases`). Add one for the taint.
- **L5.** The README claim "re-engages after 900 s once the arriver settles" is imprecise. `_reengage_row_fails` needs
  house `sleep` (`:1957`) and otherwise abandons without retry (`:2008-2015`); the next SLEEP edge re-engages.
  §8 "excluded = everyone -> backstop releases" is false for VACATION (no backstop, `:877-880`). A manual override
  ARRIVING/HOME_* inside a tainted episode never releases (the payload `trigger` `override_set` is available): name it.
- **L6.** Live criteria do not discriminate while the switch is off (a `decision_log` with no `house_state:arriving`
  row is true before and after). The plan says in-suite; keep that explicit for every Live row.

---

## 3. Invariant and knob checklist

| Item | Result |
|---|---|
| INV-ARR falsifiable | YES, stated as an unlock with none of (a)-(c) |
| INV-ARR covers every channel | **LEAK**: suppressed-ARRIVING edge (H2), boot "reads home" (M2), stale taint from non-edge engages (M3) |
| INV-REAL falsifiable | YES; **narrower than the operator constraint** (M5) |
| INV-AF falsifiable | YES; the D2 design strands ARMED_AWAY outside it (M1) |
| §5 site list complete | YES (re-grep matches; the readback retry is not a new trigger) |
| HOME_* entry paths | ARRIVING->HOME_* ok; AWAY->HOME_* override ok; GUEST->HOME_* ok; boot-settle-suppressed ARRIVING->HOME_* **missing** (H2) |
| Knob ladder | `TRIPWIRE_WINDOW_S` 120 rung 1 ok (L3 coupling); `ARRIVING_CORROBORATION_WINDOW_S` 120 effectively 60 (M1); `STILL_LOCKED_S` 90 **fails the stated inequality** (H3b) |
| Acceptance discriminates | D1 bullet 4 yes; D4 bullet 2 wrong per code (H3a); D3 bullet 3 unsatisfiable (H1) |
| Parked triggers | LOCK-REGIME-BOOT-REALLY-AWAY-1 fires; undispositioned (M4) |

## 4. Must-fix in the plan before build

H1, H2, H3 (a+b), M1 (or move D2 out as the plan allows), M2, M3, M4, M5, M6, M7. LOWs: fix in the same pass where it
costs a line.
