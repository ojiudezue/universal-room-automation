# Review D (adversarial completeness, diff-blind): LOCK-RELEASE-ON-ARRIVING

Branch `feature/lock-release-arriving` @ 30b80831, base `develop...HEAD` (three-dot). Plan rev 3
`docs/planning/PLANNING_lock_release_on_arriving.md`. Tier 3, framing D.

Read first, completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger #1-#35),
`IDENTITY_FUSION_CAMERAS_MANUAL.md`, `SENSOR_FLEET_CLASSES.md`. No ledger claim is re-asserted below.
No code edited, no suite run (D framing; repros are traced against source).

## Surface re-enumerated (whole module + callers, not the diff)

- `self._release(` in `security_lock_regime.py`: :878 house edge, :1047 boot recheck (partial), :1184
  arriving_signal, :1197 hazard, :1225 kill switch, :1349 S1, :1362 approach zone, :1600 / :1818
  proximity, :2375 backstop. Direct `lock.unlock`: :828 SC-disable loop, :2055 `_async_unlock`, :2792
  away-lock disable. Outside the module: `security.py:2336` hazard egress loop over `_lock_entities`
  (doors, not lockouts). No service, button or other caller unlocks a lockout. Matches plan §5.
- `self.reason = ` writes: :663/:666 (+clear), :671 (allowlisted BOOT_UNKNOWN), :691/:694 (+clear),
  :815 (+clear), :972 (`_set_engage_reason`), :1022 (allowlisted guest-night), :1198, :1226,
  :2031, :2039 (+clear). Complete; no unlisted write.
- House-edge producers: `presence._dispatch_house_state_change` (inference, boot-settle
  `override_set`), `house_state.set_override` (`override_set`), `clear_override` (`override_clear`),
  `force_state` (no dispatch). `transition()` clears an active override inline (`house_state.py`
  ~:251). `infer()` proposes ARRIVING only from AWAY (`presence.py:1368-1370`); AWAY -> HOME_* /
  GUEST are valid machine edges but no inference path proposes them (override only).

## Findings

| ID | SEV | Where | Finding |
|---|---|---|---|
| D-M1 | MEDIUM (must-fix: falsifies stated INV-PAGE / INV-REAL-B) | `security_lock_regime.py:1432-1434` | The R2-7 "human re-lock" skip reads `State.last_changed > anchor_wall`, which also moves on `unavailable -> locked`. Repro (legal, kill switch ON, SLEEP engaged): lockout `lock.garage_a_lockout` reads `unavailable` at T (ESPHome/WiFi reconnect); Oji `not_home -> home` at T. S1 `_release` skips the entity (:1865-1871: unreal, warned, no spawn, no failure NM); D4a scheduled. At T+20 the device reconnects reading `locked` (last_changed T+20). At T+90 `_on_still_locked`: locked, no failure stamp, `changed > anchor_wall` -> skip. No release, no page: a resident locked out silently, the exact case D4 exists for. Same miss when the read-back sees `unavailable` (treated as success, :2113-2115) and the device then returns `locked`. Fix: skip only on an observed `unlocked/unlocking -> locked` transition after the anchor (stamp it in `_on_lockout_event`, which already listens), not on `last_changed`. Test: unavailable at edge, `locked` at +20, page at +90. Bug class: coincidental equality masking a concept split (#63): "state changed after anchor" != "someone re-locked". |
| D-L1 | LOW (fix in-cycle) | `_boot_recheck_regime` :1029/:1047 + `_check_uncorroborated` :1905-1911 | Builder's edge, confirmed and adjudicated. Restored taint + house restored `waking` + BOOT_UNKNOWN (SLEEP never seen live, e.g. a cold boot whose settle swallowed SLEEP) -> `_edge_decision("waking")` -> release with trigger `boot_recheck` -> D3 pages HIGH "released without a resident arrival". **Not a real access leak:** WAKING is reachable only from SLEEP (`house_state.py` VALID_TRANSITIONS), the same evidence class as the exempt `house_state:waking`, and BOOT_UNKNOWN's backstop releases at sleep_end + backstop_min anyway. Reachable only for a restart inside [sleep_end, sleep_end + backstop_min] (after the deadline `_boot_rebuild` fires the backstop at 0 s, trigger `backstop`, before the recheck). **Decision: treat boot-recheck `waking` like `house_state:waking`.** Keep the release; exempt it in D3 (pass the house to `_check_uncorroborated` or use trigger `boot_recheck:waking`), and add "or the boot recheck reading `waking`" to INV-ARR's exception. Otherwise a false HIGH page and INV-ARR's wording is broken. |
| D-L2 | LOW (name in README; optional page) | `_boot_rebuild` :672-677, `_boot_recheck_regime` :1050-1053 | **INV-REAL holds as stated** (edge path S1/hold/`_arrival_counts`/`_really_away` byte-identical; every resident edge `_arrival_counts` accepts still calls `_release`). But the operator-level claim "no real arrival loses its release" fails for an arrival with NO observed edge: HA restart or SC reload spanning a real night return while the house read `away` (e.g. SLEEP engaged 23:00, residents leave 01:00 (SLEEP -> AWAY), restart 01:30, return 01:40 before the regime re-subscribes, or during a reload while `_torn_down`). Boot rebuild taints (restored `away`), the recheck holds, no person edge -> no S1, no D4a, no D4b (needs an `unavailable -> home` edge). Develop released at the recheck (house ARRIVING/HOME_*). Discharge: morning backstop, kill switch, manual. Not in plan §9.3 (which names only the reverse case and R2-5 stale restore). Suggest a boot page (not a release): tainted boot hold + restored house `away` + a resident now reading `home` + lockout `locked` -> one HIGH NM. Restored `away` with a resident home is strong evidence of a gap arrival (nobody-home needs census 0, alpha needs trackers away). |
| D-L3 | LOW (accepted residual, observability) | `_set_engage_reason` :971 | Plan §4 / §11 Q2 accept "VACATION -> ... -> SLEEP restarts the episode; WAKING releases". Adversarial shape: during a real vacation a phantom zone sensor (measured Back Hallway epoch) drives AWAY -> ARRIVING -> HOME_* (held) -> SLEEP at sleep hours (has_people from the same phantom) -> engage clears the taint -> next morning `house_state:waking` releases, then nothing re-locks by day; repeats nightly. Strictly better than develop (released at ARRIVING), but D3 is blind to it because the SLEEP engage launders the taint. Suggest carrying `_episode_saw_arriving` across a SLEEP engage whose previous reason was VACATION (D3 only, not the gate), or state the daily-unlock consequence plainly in the README. |
| D-H1 (pre-existing, card) | HIGH, not introduced by this cycle | `_boot_rebuild` :668-680 + `_backstop_delay_s` :509-510 | VACATION lock released by any daytime restart. Repro: operator selects VACATION while still home (override; inferred HOME_DAY). Everyone leaves: nobody-home proposes AWAY (`presence.py:1180-1189`, current = effective VACATION != AWAY), `transition()` accepts from inferred HOME_DAY and clears the override; dispatch `vacation -> away` -> `_edge_decision` none, reason stays `vacation`. Any restart after today's backstop deadline and before sleep_start: restored house `away` -> reason `boot_unknown` (sleep-like) -> `_schedule_backstop(allow_immediate=True)` -> 0 s -> `_release("backstop")` -> garage unlocked mid-vacation. Develop behaves the same (the cycle only adds the taint, which the backstop ignores). The operator deploys while travelling, so restarts during vacations are real. Card: persist the engage reason (or a vacation episode mark) and rebuild `vacation` from it; never degrade a vacation lock to `boot_unknown`. Gate before relying on the lockout during travel. |
| D-L4 (pre-existing) | LOW | `_boot_rebuild` :652-660 | A lockout not yet available at setup (ESPHome/ratgdo still connecting) counts as "nothing locked": reason stays NONE and (new, R2-4) the restored taint is cleared. If the house is awake at the 120 s recheck, `_edge_decision` gives `none`, so the lock stays `locked` with reason NONE: no backstop, no house release, no D4b (needs reason != NONE). Only person edges / proximity / switch discharge it. Develop's only extra discharge was an unconditional ARRIVING (F19, accepted). Card: at the recheck, a lockout reading `locked` with reason NONE should rebuild BOOT_UNKNOWN as `_boot_rebuild` would have. |

Cleared (holds because):
- **AWAY -> HOME_* without ARRIVING**: valid machine edge but `infer()` never proposes it (`presence.py:1368-1370`); only `set_override` (operator, `override_set`, exempt by design) or `override_clear` (not exempt: tainted -> held, untainted -> develop behaviour).
- **Hidden ARRIVING behind an override**: `transition()` clears the override on the first inferred transition and presence dispatches it, so an inferred ARRIVING is always dispatched with `new_state == "arriving"`.
- **Boot-settle-suppressed ARRIVING**: `old_state == "arriving"` taint (:865) plus `_boot_rebuild` / recheck taints cover every observable residue; fully swallowed excursion with restored HOME_* stays the named §9.3 residual.
- **Double restart**: taint persisted (`_store_payload` :2829), loaded before `_boot_rebuild` (:565 vs :626); BOOT_UNKNOWN write keeps it; HA's Store flushes the 1 s delayed save on final write, teardown flushes on reload.
- **Guest clock**: routed through `_set_engage_reason` (:1120); byte-identical write + backstop.
- **SC disable / kill switch / hazard mid-episode**: each writes NONE then clears (:815, :1226, :1198); OFF -> ON never re-engages (INV-5).
- **Two residents / hold max 60 s**: S1 per person unchanged; D4 timers keyed by pid, anchored after the hold, deduped per lock per `engage_seq`.
- **Daytime tainted boot**: BOOT_UNKNOWN backstop at 0 s releases (trigger `backstop`, outside INV-ARR), so the boot hold bites only between sleep_start and the morning deadline.
- **`override_set` from `ura.set_house_state`**: any caller (incl. a user automation) is treated as operator; pre-existing trust, unchanged.

## Invariant checklist

| Invariant | Verdict |
|---|---|
| INV-ARR | PASS on every reachable house-edge path; one wording break (D-L1, boot recheck `waking`, not an access leak). |
| INV-REAL | PASS as stated (edge-based). Operator-level "no real arrival loses its release" leaks for edge-less gap arrivals (D-L2). |
| INV-REAL-B | LEAK via D-M1 (an `unavailable -> locked` flap inside the window suppresses the page). |
| INV-PAGE | LEAK (D-M1, concrete repro). |

## Verdict: FIX-REQUIRED

Must-fix: **D-M1** (replace the `last_changed` re-lock test with an observed `unlocked -> locked`
stamp; add the unavailable-flap test). Fix in-cycle: **D-L1** (exempt boot-recheck `waking` in D3,
amend INV-ARR). Name in README: D-L2, D-L3. Card (pre-existing, outside the diff): D-H1 (priority
before the lockout is relied on during travel), D-L4.

| Severity | Found | Must-fix | In-cycle | Card / README |
|---|---|---|---|---|
| HIGH (pre-existing) | 1 | 0 | 0 | 1 |
| MEDIUM | 1 | 1 | 0 | 0 |
| LOW | 4 | 0 | 1 | 3 |

Bug classes: #63 coincidental equality (D-M1); #53-adjacent episode-boundary laundering (D-L3);
restart/boot rebuild state loss (D-H1, D-L2, D-L4).
