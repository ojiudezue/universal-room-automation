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

## Residual
A phantom DAYTIME hold in a guest room (fan plus MS600 radar; GB1/GB2 have no fan-immune witness) now holds a stay as well as entering one. The D4 trip-wire (`GUEST_STAY_LONG_NM_DAYS`, 28) is the backstop.

## Files
- `const.py`: `GUEST_STAY_EXIT_DAY_VETO_FRACTION`.
- `domain_coordinators/presence.py`: `_day_vetoes` and one extra conjunct on the exit test in `_refresh_guest_stay`.
- Tests: `quality/tests/test_guest_stay_producer.py` (veto keeps the stay, low day lets the night exit, boundary 4320 s / 4277 s / 4752 s of 43200 s, kill switch, fixed-exit path untouched, window-only, restart, fixture replay with and without the veto), `quality/tests/test_guest_left_button.py` (press overrides the veto).
- Docs: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §2 step 3.

## Acceptance criteria
- **Test:** `test_day_veto_keeps_stay`, `test_low_day_lets_empty_night_exit`, `test_day_veto_boundary[*]`, `test_day_veto_kill_switch`, `test_day_veto_off_on_fixed_exit`, `test_day_veto_only_inside_exit_window`, `test_day_veto_restart_same_verdict`, `test_replay_fixture_day_list_day_veto`, `test_replay_fixture_day_list` (veto off = old list), `test_press_overrides_day_veto`.
- **Verify:** neutering the veto conjunct, `>=`, the scaled gate, the any-room scan or the window bounds each turns named tests red (build report).
- **Live (no guest in the house now):**
  - L1: after the restart, `sensor.ura_presence_coordinator_house_state` attribute `guest_stay_active` is `false` and `guest_stay_basis` lists the last 3 nights with `qualifies: false` (clean period; the veto cannot hold a stay that is not on).
  - L2: no WARNING `Guest stay walk failed` in the log after the first morning walk.
  - L3 (next guest stay, event-gated): on the morning after the first empty night that follows a day the guest was in the room (day fraction ≥ 0.10 in `guest_stay_basis[-1].day_fraction` or the other guest room), `guest_stay_active` stays `true`; it goes `false` the morning after an empty night whose day reads < 0.10 in both guest rooms. Discriminates against "veto not wired" (would go false a day earlier).
  - L4 (event-gated): a "Guest left" press during a vetoed stay sets `guest_stay_active` false at once and the next morning's walk keeps it false.
