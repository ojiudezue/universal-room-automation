# v5.108.5: guest stay exit day veto

Card: `GUEST-MODE-SPLIT-VISITORS-1` (follow-up, operator approval 2026-11-10).
Evidence: `docs/planning/AUDIT_guest_onset_thresholds_and_hvac_evidence_states_2026_11_10.md` §1.3-§1.5.
Tier 2-DB (house-state exit): three framing-disjoint reviews, then live validation.

## What changes

The guest stay latch (`PresenceCoordinator._refresh_guest_stay`) used to end after min(2, n) straight empty nights, regardless of the day. In October that dropped the last real stay day: the re-entry-grace stay had n = 1, night 10-16 read 0, so the stay ended on the 10-17 morning while the guest room read 0.46 (10-16) and 0.22 (10-17) by day.

Now the empty-night exit does not fire while any guest room's non-resident day fraction is at least `GUEST_STAY_EXIT_DAY_VETO_FRACTION` (0.10) on a day paired with a night inside the exit window. The day is the same window as the entry day test (local 10:00 to the house sleep start, `guest_day_window`). The fractions come from the span read the walk already does (`presence.py:6180-6187`), so there is no new DB read and no new state. The walk stays deterministic in the DB contents, so a restart gives the same verdict.

Entry is unchanged: night 0.25, day 0.10, exit 2 nights, grace 7 days.

**Guest left button:** a press still exits at once and the veto never brings the stay back. A stay only starts on a night that begins after the press, and n counts only post-press nights, so an exit window never reaches a day from before the press.

## Knob
| Knob | Rung | Default | Why |
|---|---|---|---|
| `GUEST_STAY_EXIT_DAY_VETO_FRACTION` (`const.py:554`) | 1 (module constant) | `0.10` | House-state exit policy fitted on one stay, so a reviewed change. Same value as the entry day test (`GUEST_STAY_DAY_MIN_FRACTION`), kept separate so entry and exit can be tuned apart. **> 1 = veto off** (rev 6 exit, byte-identical). Ignored when `GUEST_STAY_EXIT_SCALES_WITH_STAY` is False (rev 5 stays exact). |

## Replay (fixture `guest_stay_r5_replay.json`, oracle = an independent pure-Python walk that reproduces the veto-off lists exactly)
| | Veto off (v5.108.1) | Veto 0.10 (this release) |
|---|---|---|
| October stay (09-27..10-17, 21 days) | 09-28..10-14, 10-16 (18) | 09-28..10-14, 10-16..10-18 (19; 10-18 is one tail day) |
| Clean period 10-19..11-08 | 0 | 0 |
| Before the stay (unlabelled) | 08-25..09-01, 09-05..09-07, 09-10, 09-16 | 08-25..09-12, 09-16 |

The pre-stay change is the audit's "pre 20": the late-August stay is held through daytime-occupied empty nights. Those days have no label (guest or resident unknown).

## Observability (review fix-up, B LOW-2)
`sensor.ura_presence_coordinator_house_state` now carries `guest_stay_day_veto_active` (bool), `guest_stay_day_veto_room`, `guest_stay_day_veto_night` and `guest_stay_day_veto_fraction`: whether the exit day veto is what holds the latch on the last walked night, and which guest room's day (the highest day fraction at or above 0.10). They are None / false when the stay is held by a qualifying night, is off, after a "Guest left" press, or after a failed first walk. Each new hold logs one INFO line `Guest stay exit held by the day veto: <room> day of night <date> read <f> >= 0.10`. `guest_stay_basis[*].day_fraction` is the day of the room with the highest NIGHT fraction, so it can read < 0.10 while the other guest room's day holds the stay; use the new attributes.

## Residual
- **Phantom daytime hold.** A phantom DAYTIME hold in a guest room now holds a stay as well as entering one. It needs only 0.10 x 12 h = 72 min of a guest-room day. GB1 and GB2 have no fan-immune witness (MS600 radar-derived motion only), and GB2 has no BLE scanner, so a resident's daytime use there is not subtracted either.
- **What bounds it.** The D4 trip-wire (`GUEST_STAY_LONG_NM_DAYS`, 28) only pages; it releases nothing. What ends a veto-only hold (no qualifying night) is the walk's window: the walk starts with the latch off `GUEST_STAY_REPLAY_NIGHTS` (35) nights back, so the stay drops once its entry night leaves the span, about 33 nights after entry. So a phantom can hold GUEST for up to about 5 weeks, with a page at 28 days.
- **Window roll-off (B LOW-1).** The same roll-off drops the `ended_on` anchor. A stay that re-entered by grace after a long veto-held stay can lose its grace, and the latch, about 6 nights later with no new evidence. It fails toward no GUEST and a restart gives the same verdict; reaching it needs a phantom-shaped hold, which D4 pages first.
- **Grace reach (A MEDIUM-1).** The veto moves the night that ends a stay later, so the 7-day re-entry grace reaches later nights: effective reach = daytime hold length + 7 days. Grace bypasses `GUEST_STAY_ENTRY_NIGHTS`, so a single night can now re-enter where it could not before. Replay (`GUEST_STAY_ENTRY_NIGHTS` 2): the 08-26 stay is held to 09-12, and night 09-16 re-enters by grace. The "no phantom chain" rule still holds (a grace stay keeps the original end as its anchor), but that end is now later.
- **Any guest room (A LOW-2, deliberate).** Entry pairs night and day in the same room; the veto takes any guest room, so daytime use of GB1 holds a GB2 stay. Replay: 0 clean-period days.
- **GUEST exposure (B LOW-3).** Each extra GUEST day carries the existing GUEST semantics: exterior-person NM severity stays at the GUEST row (MEDIUM, delivered nowhere) where HOME_DAY with no resident home is HIGH for perimeter approach / first_sighting; security re-arms ARMED_HOME each morning when `auto_follow_house_state` is on (default off); Bayesian learning and the occupancy dwell-anomaly evaluation are paused. Only the exposure grows.

## Files
- `const.py`: `GUEST_STAY_EXIT_DAY_VETO_FRACTION`.
- `domain_coordinators/presence.py`: `_veto_room` and the veto branch on the exit test in `_refresh_guest_stay`; `_guest_stay_day_veto` (display) set by the walk, cleared by the press and a failed first walk.
- `sensor.py`: the four `guest_stay_day_veto_*` attributes (review fix-up).
- Tests: `quality/tests/test_guest_stay_producer.py` (fix-up: `test_day_veto_published_and_logged`, `test_day_veto_boundary_exact_split_other_room`, `test_day_veto_hold_then_exit_then_grace_reentry`, veto assertions in `test_house_state_sensor_publishes_stay` / `test_db_error_fails_off`; veto keeps the stay, low day lets the night exit, boundary 4320 s / 4277 s / 4752 s of 43200 s, kill switch, fixed-exit path untouched, window-only, restart, fixture replay with and without the veto), `quality/tests/test_guest_left_button.py` (press overrides the veto).
- Docs: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §2 step 3.

## Acceptance criteria
- **Test:** `test_day_veto_keeps_stay`, `test_low_day_lets_empty_night_exit`, `test_day_veto_boundary[*]`, `test_day_veto_kill_switch`, `test_day_veto_off_on_fixed_exit`, `test_day_veto_only_inside_exit_window`, `test_day_veto_restart_same_verdict`, `test_replay_fixture_day_list_day_veto`, `test_replay_fixture_day_list` (veto off = old list), `test_press_overrides_day_veto`, `test_day_veto_published_and_logged`, `test_day_veto_boundary_exact_split_other_room`, `test_day_veto_hold_then_exit_then_grace_reentry`.
- **Verify:** neutering the veto conjunct, `>=`, the scaled gate, the any-room scan or the window bounds each turns named tests red (build report).
- **Live (no guest in the house now):**
  - L1: after the restart, `sensor.ura_presence_coordinator_house_state` attribute `guest_stay_active` is `false` and `guest_stay_basis` lists the last 3 nights with `qualifies: false` (clean period; the veto cannot hold a stay that is not on).
  - L2: no WARNING `Guest stay walk failed` in the log after the first morning walk.
  - L3 (next guest stay, event-gated): on the morning after the first empty night that follows a day the guest was in a guest room, `guest_stay_active` stays `true` AND `guest_stay_day_veto_active` is `true` with `guest_stay_day_veto_room` / `guest_stay_day_veto_night` naming that room and night (`guest_stay_day_veto_fraction` ≥ 0.10), and the log has one INFO `Guest stay exit held by the day veto`. It goes `false` (veto attributes cleared) the morning after an empty night whose day reads < 0.10 in both guest rooms. Discriminates against "veto not wired" (would go false a day earlier, veto attributes never set) and against a stay held by a real night (`guest_stay_day_veto_active` false).
  - L4 (event-gated): a "Guest left" press during a vetoed stay sets `guest_stay_active` false at once and the next morning's walk keeps it false.
