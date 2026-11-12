# Plan review: PLANNING_lock_suspicious_arrival_hold.md (rev 1)

Reviewer: ura-reviewer, adversarial plan review (Tier 2 elevated), 2026-11-12.
Base: `develop` @ `0e60e0f8`. Read-only; nothing built or committed.
Mandatory reading done: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (complete, §0-§11 + §10
ledger #1-#32) and `docs/architecture/SENSOR_FLEET_CLASSES.md` (complete). No ledger claim re-asserted.
HA source read: `.venv-ha/.../homeassistant/components/person/__init__.py` `_update_state`, `_parse_source_state`,
`_get_latest`, start-up path.

**Verdict: REVISE (small).** The core rule (stale `source` at the edge) survives the attack: I found no
reachable real-arrival shape on a live (non-boot) edge where the source tracker did not change at the edge.
The holes are in the hold mechanics and in two overclaims. None needs a redesign. Fix them in the plan
before the build is dispatched.

---

## 1. Unlock-path re-enumeration (own greps)

`git grep '"unlock"'` over `custom_components/` on develop finds exactly four unlock call sites:
`security_lock_regime.py:757` (disable), `:1472` (`_async_unlock`, every `_release`), `:2189`
(away-lock disable), `security.py:2335` (hazard egress unlock, smoke/fire/CO only, not arrival-driven).
Every `_release(` / `_away_release(` caller in `security_lock_regime.py`:

| Caller | Line | Arrival-driven? | Plan coverage |
|---|---|---|---|
| `on_house_state_changed` (ARRIVING always; HOME_* if reason != NONE) | :788 via `_edge_decision` :815-851 | indirectly (R3) | out of scope, named (S11) |
| `_boot_recheck_regime` | ~:927 | house-state | out of scope (S12) |
| `_apply_arrival` P2 garage + away | :1018, :1020 | yes | D3 (S6-S8) |
| `on_hazard` | :1031, :1034 | no | n/a |
| `on_kill_switch_changed` | :1048, :1058 | no | n/a |
| `_on_person_event` person / approach zone | :1129, :1132 | yes | D2 (S1, S2) |
| `_on_distance_event` | :1328 | yes | D4 (S9) |
| `_on_backstop` | :1788 | no | n/a |
| `_away_boot_discharge` | :1882 | restore | out of scope (S10) |
| `_away_on_person` | :1918 | yes, ANY `home` reading incl. attribute-only `home -> home` events | D2 (S3) |

Perimeter D10.5 (`perimeter_alert.py:5081-5083`) also stamps blip edges through `live_arrival_slug`, but it
only de-escalates an alert; not an unlock. The plan's S1-S12 list is complete for unlocks. Good.

## 2. Stale-source rule attack (HA `person._update_state`)

HA rule: any non-GPS `home` wins (latest by `last_updated`), else the latest GPS by `last_updated`, else the
latest non-home; `unavailable`/`unknown` ignored. Shapes tried:

| Shape | Result |
|---|---|
| BLE-only person (Jaya, Ziri): private_ble or Bermuda goes `home` | The tracker that went home is the only non-GPS home, so it is the source. Age ~0. Cleared. |
| Bermuda home before private_ble (or the reverse) | The first one makes the edge, fresh. The second one only switches `source` (no state edge). Cleared. |
| BLE tracker already `home` while GPS goes home | Impossible while the person reads `not_home`: a non-GPS home would already have made the person home. Cleared. |
| Phone GPS `unavailable -> home` (Ezinne 11-12) | Fresh. Cleared (this is the case that refuted rule (a)). |
| Real arrival where the phone app drops `unavailable` at Wi-Fi handoff and a second GPS device at home becomes source | Held, as designed. If BLE reads home inside H, the person stays home (non-GPS wins), so there is no revert and it confirms at H. Delay <= H. Needs >= 2 GPS. Accepted. |
| **HA start** (`EVENT_HOMEASSISTANT_START`, person `__init__.py` ~:470-482): the person waits for START, then `_update_state`. Tracker states were written during bootstrap, earlier | If the restored person state differs (restored `not_home`, tracker now `home`), the START edge has `old_state != None` and src_age = START minus the tracker's setup write. That can be well over 10 s on this host. **Held H, then confirmed.** See F4. |
| Person config edit (add a tracker in the UI): `_async_update_config` -> `_update_state` | Same shape as HA start: possibly stale, so held H. Rare. LOW. |
| Live predicate at non-edge times (D3/D4): person home since 10:00 via BLE, phone GPS went home 09:58, BLE drops at 14:00 so the source falls back to the phone | Predicate reads True (age 120 s) while the person really is home. Harmless: the person reads `home`, so `_really_away` is False and develop would not release either. Note it in the plan. |

Conclusion: on live edges the rule holds 0 real arrivals. The exceptions are the start-up edge and the
config-edit edge (F4).

## 3. Findings

**F1 (MEDIUM): same-state events during a hold are unspecified, and the likely build defeats the hold.**
§5.2 has two branches: "revert" (`new_val == held.old_val`) and "any other value". `_on_person_event`
(`security_lock_regime.py:1097-1138`) receives attribute-only `home -> home` events, because HA's person writes
on every source/lat/lon/accuracy change. `_away_on_person` (:1910-1918) releases on each of them. Under the
plan text, an attribute event inside H (source switch, iPad accuracy refresh: the R1 shape) is "any other
value". It cancels the hold and is processed with `old_val := not_home`, so it releases at once. That defeats
the hold for every stale `home` with an intermediate attribute write. **Fix:** state that an event with
`new_val == held.new_val` keeps the hold and is otherwise ignored, so the held body runs once, at confirm. Add
`test_attribute_only_event_keeps_hold` and a mutation drill for it.

**F2 (MEDIUM): fixture authority. The replay never exercises HA's real source selection or `last_changed`
semantics.** D6 drives `_lockout_harness.py` with synthesised person states built from the probe's `src_age`
column, so a predicate that reads `last_updated` instead of `last_changed`, or reads the wrong attribute, can
pass it whenever the harness builds both fields the same way. **Fix:** add one real-HA test (pattern
`test_sc_garage_lockout_real_ha.py`) with the real `person` component and two GPS trackers. Drop the phone to
`unavailable` and assert: held, no unlock, revert drops it. Add a BLE-only person's `not_home -> home` that
releases in the same callback, and an attribute-only refresh of the stale tracker (bumps `last_updated` only)
that stays held. The predicate should also read the event's `new_state`, not `hass.states.get(pid)`, at the
D2 site, for determinism.

**F3 (LOW-MEDIUM): the away-lock dwell can fire inside a hold and consume `_away_attempted` for the whole
outing.** Repro: every listed person has been `not_home` for 299.5 s and the dwell is due at T. A stale blip
lands at T-0.5 and is held, so no state moves and the timer stays armed. At T, `_on_away_dwell` ->
`_async_away_engage` calls `_set_attempted()` (:2015) before `away_lock_predicate`. The predicate reads live
`home` and returns `not_all_away` (:1943), so the engage is dropped. The revert at T+0.6 cancels the hold and
skips the body, so `_away_rearm` never runs. The away lock never engages for this outing. On develop the blip
clears the attempt and the revert re-arms. This breaks INV-H3 ("state equal to a run where neither happened").
**Fix:** on cancel, call `_away_rearm(cfg)` and restore the attempt marker, or have `_on_away_dwell` defer to
the hold's expiry while `_held_edges` is non-empty. Test it.

**F4 (LOW-MEDIUM, operator bar): INV-H2 and R2 overclaim.** R2 says boot ages are "about 0", so the predicate
is fail-open at boot. That is wrong for the person START edge (§2 table): a real arrival during a restart
whose restored person state was `not_home` is held H before the P1 release. That is a real-arrival delay,
which is what the operator's bar forbids. It is bounded (5 s) and rare, but the plan must name it. **Fix:**
either exempt edges inside `_in_boot_arrival_window()` from the hold (that window already treats every edge
as an arrival, M-2 (i)), or name the delay in R2 and INV-H2. Exempting is my recommendation: it keeps
"real arrivals never wait" literally true, and boot blips are already accepted by M-2. The live
discriminator ("non-zero hold count with no second GPS device = false hold") must also exclude the boot
window, or a restart will trip it.

**F5 (LOW): the D3 drop loses a non-face signal if the hold is cancelled by something other than the
revert (R4).** Under F1's fix, the only non-revert cancel is a different state (zone, unreal). Name the shape
(phone `unavailable` at handoff with BLE `not_home`, then the phone returns `not_home`): that is a revert, so
the edge is lost only when the next real edge comes. Accepted. Add one sentence saying that a dropped
`ble`/`geofence` signal is not replayed on cancel, by design.

**F6 (LOW): D4 synthetic hold.** "Create one keyed to `person.last_changed`, `old_val` from `_last_real`"
can replay a body for an edge that was already processed (`_last_real` = home). Effects are a no-op for the
garage, and only an any-`home` away release (harmless), but say so and test it. `_person_for_sensor` returning
None (a proximity sensor named after a device tracker, valid HA config; portability) bypasses the gate and
releases. Either resolve a tracker-named sensor to its person or name the gap.

**F7 (LOW): confirm-time config.** §5.2 passes `cfg` captured at hold time into
`_process_person_edge`. Re-read `self._cfg()` at confirm. A resident/exclusion/away-person list changed
inside H should apply, and `_release` already re-reads.

**F8 (LOW): reload during a hold** drops a held real (boot or 2-GPS) arrival. The new instance sees no edge
(`old is None` path). The boot recheck catches it only via the house state. Name it in §9; with F4's
exemption the boot case disappears.

**F9 (LOW): citations.** `_NO_LIVE_ATTR_KEYS` is at `__init__.py:7382` (approach radius at :7395).
`OPTIONS_RELOAD_SUPPRESS_KEYS` is at :7525 (approach radius at :7702). The plan labels :7397 as
RELOAD_SUPPRESS and :7704 as NO_LIVE_ATTR, which is backwards. `arrival_edges.py` is at the package root, not
in `domain_coordinators/`.

**F10 (LOW): knob naming.** `number.ura_garage_lockout_arrival_hold` also governs the away (door) lock. The
description should say "garage lockout and away lock". The ladder is otherwise right: H at rung 3 (0 = off,
develop), M at rung 1 (a classifier boundary with a 7-order gap). Both suppress-list entries are required and
already tested by D5.

**F11 (LOW, scope note):** the same blips feed `security.py:2410-2418` expected-arrival sanction (a 5-min
"expected entry" window per blip, when `CONF_SECURITY_ON_ARRIVAL_ADD_EXPECTED` is on). That is a security
weakening, not a lockout. The §7 follow-up card should carry it explicitly with priority, not as "HVAC/music".

## 4. Hold/replay mechanics: cleared items

- Original-timestamp replay: `_really_away` (:1145-1157) and `_arrival_counts` take `now_ts`, so passing
  `edge_ts` is consistent. `_release` stamps `releasing_set` with `_ts()` (confirm time). That is correct,
  because re-engage timing should run from the actual unlock.
- Revert-skip for S3 (`_away_not_home_since` reset at :1897-1899) is correctly identified and has a
  discriminating test.
- Face corroboration: moving the `_arrival_edges` stamp into the deferred body closes the blip-corroborates-
  face path. A face that arrives inside H goes to `_pending_faces` and is not re-checked at confirm, but the
  P1 confirm is a superset. Fine.
- D3 superset claim holds for both `not_home -> home` (P1 always counts) and `unavailable -> home` (both
  paths use `_really_away`).
- Concurrency: holds are per pid. A second person's edge is independent. A same-pid zone change inside H
  cancels and reprocesses. OK.
- Teardown: adding held timers to `async_teardown` and checking `_torn_down` at confirm is sufficient.

## 5. Acceptance criteria

They discriminate. D2's exact-stamp assertion separates "revert processed" from "revert skipped". D6
separates "held real" from "instant real" by same-callback release. Missing: F1 test, F2 real-HA test, F3
dwell-in-hold test, F4 boot-edge test (either "exempt" or "held H", whichever is chosen), and mutation drills
for F1 and F3.

## Summary

| Sev | Count | Findings |
|---|---|---|
| HIGH | 0 | |
| MEDIUM | 2 | F1, F2 |
| LOW-MEDIUM | 2 | F3, F4 |
| LOW | 7 | F5-F11 |

**REVISE.** Must-fix in the plan before build: F1, F2, F3, F4. The LOWs are one-line plan edits.
