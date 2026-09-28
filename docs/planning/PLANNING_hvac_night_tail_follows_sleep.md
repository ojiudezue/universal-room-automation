# PLANNING: HVAC night hold follows house Sleep

**Card:** `HVAC-NIGHT-TAIL-STARTS-TOO-EARLY-1` (workstream `HVAC-W2-OCCUPANCY-TRUTH`)
**Status:** plan. **Scope is B only.** C is PARKED on the operator's instruction of 2026-09-27: "Lets hold C."
**Base:** `develop` @ `e873d1abe` (v5.103.18 W1-B shipped)

| Deliverable | What it is | State |
|---|---|---|
| A | Config change | Done |
| D0 | Read-only probe | Planned |
| B | Selector change | Planned |
| C | Per-room start-time knob | Parked (§P) |
| Label note | Wording fixes for existing fields | Optional (§L) |

---

## 0. Institutional context verified

### What I read
- **State of play.** I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (lines 1–470). The sections that bear on this plan:
  - §3.1: the D8 night tail and per-room override knobs.
  - §3.2 and §3.3: the retreat gate, and what is live versus dormant.
  - §9.3: Jaya's still-sleeper case and her 5400 s night knob.
  - §9c: override switches ride the tail.
  - §9e: the W1-B four gates, v5.103.18.
  - §10: the corrections ledger.
- **§10 check.** This plan asserts none of the ledger's wrong claims. It relies on C24: HVAC occupancy arms and holds on the lighting `occupied` value, with a tail added. It is not a separate, faster clock.

### Operator direction (2026-09-27, verbatim)
- A: "Do it."
- B: "yes follow house state for sleep. Check on its logic"
- On clock-only sleep: "I think this is fine."
- C: first "Yes backup. If set it uses this instead of house state. Even more useful per room.", later **"Lets hold C."**

### 0.1 Config-first check
| Candidate setting | Does it solve the problem? | Evidence |
|---|---|---|
| Per-room `hvac_vacancy_hold_night` | **Partly. This is deliverable A, already done.** | The live `.storage/core.config_entries` shows 90 on the 9 common rooms and 5400 on Jaya Bedroom. The value applies all night, so it cannot change *when* the night hold starts. |
| House `sleep_start_hour` (Coordinator Manager, live value 22) | No | Tails key on `home_night`, which starts at 21:00. An earlier sleep hour would lengthen tails, not shorten them. |
| `night_start_hour` (21) | No knob exists | It is a hardcoded constructor default (`presence.py:1011`). |
| Room "Sleep Protection" `sleep_start_hour` / `sleep_end_hour` | No | Only lighting sleep protection reads these (`automation.py:871-884`). |

**Verdict:** A was the only config-level fix available. B needs a code change.

### 0.2 Prior-art scan (REUSE / BUILD) for B
| Piece | Verdict | Where |
|---|---|---|
| Tail selector | **REUSE and edit one line** | `hvac_zones.py:976-1046`, `_effective_hvac_hold_seconds`. The current rule is at `:1046`: `night_val if house_state in FAN_TRUST_STATES else day_val`. |
| Day and night tables | REUSE, unchanged | `const.py:1219-1224`, `:1230-1241` |
| Per-room overrides and night-at-least-day clamp | REUSE, unchanged | `hvac_zones.py:1019-1044` |
| Night-state tuple | **BUILD a new HVAC-local constant** | No HVAC-local tuple of `sleep`/`waking` exists. Editing `FAN_TRUST_STATES` (`hvac_const.py:919`) is ruled out by §3. |
| Display of the hold | REUSE, no edit | `binary_sensor.py:894` calls the same helper with `(room_type, house_state)`, so it picks up B automatically. |

**Plans consulted:**
- `PLANNING_hvac_zone_conditioning_demand.md`, D8 (`:178-193`). Its REUSE row (`:70`) chose `FAN_TRUST_STATES` because "D7 and D8 both key on it". This plan splits D8 away from that key and leaves D7 on it.
- `PLANNING_hvac_demand_knobs_and_observability.md` (v5.103.8), which set up the override knobs and the clamp.

**Memory consulted:**
- `project_zone_away_when_occupied_home_night_gap.md`. On 2026-06-05, the master bedroom flapped vacant at 21:25 and 21:35 during `home_night` because the radar lost a still body. This is the risk B brings back for bedrooms between 21:00 and 22:00 (§5).
- `feedback_knob_labels_user_friendly.md`.

### 0.3 House Sleep logic (the check the operator asked for)
- **Entering Sleep is clock-only.** At `presence.py:1296-1301`, any home state that reaches the branch goes to SLEEP when `_is_sleep_hour(hour)` is true.
  - `_is_sleep_hour` (`:1358-1363`) works in whole hours and wraps across midnight.
  - The AWAY rules (`:1101-1251`) run first, so an empty house never goes to Sleep.
  - A cleared GUEST exits before this branch (`:1292`).
- **Leaving Sleep is not clock-only.**
  - At `sleep_end_hour` the engine proposes WAKING.
  - `presence.py:6326-6400` vetoes that until there has been at least 90 s of sustained zone occupancy (`:181`).
  - A backstop forces WAKING at `sleep_end + 3 h` (`:187`).
  - WAKING then becomes HOME_DAY on the next inference (`:1308-1311`).
- **What this means for B.** With the live hours of 22 and 6, night holds run from 22:00 until the house actually wakes, somewhere between 06:00 and 09:00. That is the desired behaviour: people who sleep in keep their protection.
- **Manual override.** The operator can force `sleep` (`select.py:173`, `house_state.py:213`). If that change reaches HVAC's `_house_state`, night holds start at the same moment, with no new code. **UNVERIFIED:** the build must check this.
- **`home_night`** still starts at 21:00 (`presence.py:1011`, `:1350`).

---

## 1. Falsifiable invariant (INV-NT)

> For every non-hallway room R and every falling edge the producer handles while the house state is *H*:
> - the hold that gets armed is R's **night** value **if and only if** *H* ∈ `HVAC_NIGHT_HOLD_STATES` = (`sleep`, `waking`);
> - otherwise it is R's **day** value.
>
> **Corollaries:**
> - No room ever arms a night-length hold in `home_night`, `home_evening`, `home_day`, `guest`, `arriving` or `away`.
> - `FAN_TRUST_STATES` and every consumer of it are unchanged, byte for byte.

**How a reviewer breaks this:**
- Find any path that still selects the hold length by `FAN_TRUST_STATES`.
- Find any caller that computes a hold without going through `_effective_hvac_hold_seconds`.

## 2. Producer and consumer map for `hvac_occupied`

### Producer
`ZoneManager.update_room_conditions` (`hvac_zones.py:566`) runs every 5-minute decision cycle. It is called from `hvac.py:1270` at boot and from `hvac.py:1925` on every tick. For each room it calls `_compute_hvac_occupied` (`:1048-1123`), which works like this:
- A rising edge of the lighting `occupied` value arms the room (`:1075-1080`).
- While the value stays held, the room stays occupied (`:1090-1095`).
- On the falling edge, the hold length is chosen **once**, by `_effective_hvac_hold_seconds`, and stored in memory in `_hvac_tail_until` (`:1098-1113`).
- The room releases on the first tick after that expiry (`:1115-1123`).

Where the producer's inputs come from:
- Room type and override values: the config entry, read fresh on every pass (`:620-646`).
- `house_state`: HVAC's own `_house_state`, updated by the house-state signal and seeded at `hvac.py:1260-1263`.
- Hallways are excluded before this point (`:724-735`).

All of these inputs are healthy.

### Consumers
| Consumer | Site | Trust / display |
|---|---|---|
| Zone rollup `any_room_hvac_occupied` | `hvac_zones.py:178-188` | Feeds all rows below |
| `conditioning_retreat_ok`, then the row-1 preset flip | `hvac_zones.py:~1551`; `hvac.py:2320-2362` | TRUST |
| D6 stale failsafe (row 4) | `hvac.py:2437` | TRUST |
| D5 energy-shed defer | `hvac.py:2643-2706` | TRUST, plus ledger |
| D7 night-trust (only when retreat is not OK) | `hvac.py:2780-2783` | TRUST |
| Transient-room hold ledger | `hvac.py:2891-2899` | Ledger |
| D9 compose-away (DORMANT) | `hvac.py:3452-3500` | TRUST |
| `zone_presence_state` | `hvac.py:4802-4809` | Display |
| Pre-cool F8 and pre-heat F9 | `hvac_predict.py:583`, `:1420` | TRUST |
| Arrester row-10 comfort delay | `hvac_override.py:2549` | TRUST |
| `last_occupied_time` and `continuous_occupied_since` | `hvac_zones.py:771-779` | TRUST |
| Per-room attribute `hvac_vacancy_hold_s` | `binary_sensor.py:894` | DISPLAY. This is the second caller; it inherits B through the same helper. |

**What B changes for consumers:** only the hold length, and only during `home_night`. No consumer's logic changes.

## 3. `FAN_TRUST_STATES` consumers are unaffected

`hvac_const.py:919` is not edited, so every site below reads an identical tuple after B.

| Site | Use | Affected? |
|---|---|---|
| `hvac.py:52`, `:2782` | D7 zone-preset person-trust | No |
| `hvac_fans.py:505`, `:521` | Sleep-onset latch reset | No |
| `hvac_fans.py:1101` | Night speed cap | No |
| `hvac_fans.py:1206` | Bedroom fan HOLD while occupied | No |
| `hvac_fans.py:1288` | Fan vacancy person-trust | No |
| `hvac_fans.py:1511` | `FanDecisionSnapshot.sleep_state` | No |
| `presence_fan_recheck.py:70`, `:485`, `:966` | Bedroom recheck veto | No |
| `automation.py:2989` | Keeps its own local literal copy | No |
| `hvac_zones.py:1002`, `:1046` (docstrings `:574`, `:986`) | Hold selector | **Yes. This is the only change.** |

**Guard test:** assert that `FAN_TRUST_STATES == ("home_night", "sleep", "waking")`, and that the source of `_effective_hvac_hold_seconds` no longer references it.

## 4. W1-B gate interaction: none (confirmed)

The four gates (§9e) are `hvac_preset.manual_guard_verdict` plus the S1 site. They read:
- Temp Arrester Override
- immune holds
- arrester grace and compromise timers
- whether the arrester is enabled
- the borrow registry

A grep of `hvac_preset.py` for `hvac_occupied|FAN_TRUST|_effective_hvac_hold|house_state` finds only `get_preset_for_house_state` at `:119`, which is unrelated.

B changes only *when* an occupancy-driven `away` target appears during `home_night`. That target still passes through the unchanged gates; the vacancy bypass waits on (a/b) and (e) per D49. The only side effect is a few earlier `away` writes between 21:00 and 22:00, which are recorded as `climate_write` rows.

## 5. Marginal benefit and cost (pushback, recorded)

**What A already fixed.** The trigger case was the Kitchen and the other common rooms holding their zones home. They now use a 90 s night hold.

**What B adds on top of A**, between 21:00 and 22:00:
- Media rooms drop from 30 min to 2 min.
- Generic rooms, bathrooms, garages and utility rooms drop from 10 min to 1 min.
- Bedrooms drop from 30 min to 1 min.

**What B costs.** Bedrooms lose their 30-minute protection in that hour. This is the 2026-06-05 master-bedroom pattern. With C parked, the only per-room mitigation is raising that room's **day** hold, which then applies all day. The alternative is an earlier house Sleep Start Hour.

D0 sizes this exposure. The operator has approved B; D0 decides whether C's revival trigger (§P) fires.

---

## D0: Probe of home_night bedroom exposure (read-only, about 15 min)

**What it does.** Adapt `scripts/probes/hvac_night_sleeper_probe.py` into `scripts/probes/hvac_home_night_bedroom_exposure_probe.py`. Over the last 14 days, for bedroom and media rooms, count gaps in `binary_sensor.<room>_occupied` (off, then back on) that:
- started between 21:00 and 22:00, and
- lasted from 60 s to 30 min (media rooms: from 120 s).

These are exactly the gaps today's night hold absorbs and B would expose. Split the counts per room, and by whether a zone person was home.

**Acceptance**
- **Verify:** per-room counts are recorded in §11.
- **Decision rule:** if any bedroom shows at least 2 exposed gaps per week, the C revival trigger fires (§P). Report it to the operator. It does not block B.

## A: DONE (config)

`hvac_vacancy_hold_night = 90` is set on 9 common rooms: Kitchen, Dining Room, Living Room, Patio, Receiving Room, Breakfast Nook, Game Room, Exercise Room and Butler Pantry. I verified this in `.storage/core.config_entries` on 2026-09-27. The key is on the reload-suppression list, so the change caused no reload.

A stays in place after B ships. Common rooms rarely hold sleepers, and 90 s is still above the 60 s day value.

## B: Night holds only during house Sleep / Waking

### Changes
- **`hvac_const.py`:** add `HVAC_NIGHT_HOLD_STATES: Final = ("sleep", "waking")` next to `FAN_TRUST_STATES`.
  - Add a comment explaining why it deliberately differs, and pointing to this plan.
  - **Knob rung: 1 (module constant).** Which house states count as "night" for HVAC holds is a design choice. Changing it should require review, not a dashboard tweak.
  - There is no kill switch. Reverting is a one-constant change.
- **`hvac_zones.py`:**
  - `:1002`: import `HVAC_NIGHT_HOLD_STATES` instead of `FAN_TRUST_STATES`.
  - `:1046`: change the rule to `night_val if house_state in HVAC_NIGHT_HOLD_STATES else day_val`.
  - Update the docstrings at `:574-578` and `:986`.
  - **Leave unchanged:** the signature, the overrides, the clamp, and the second caller.

### Acceptance
- **Test:** `test_home_night_uses_day_hold`. A bedroom in `home_night` gets 60 s.
  - **Mutation check:** putting `FAN_TRUST_STATES` back at `:1046` must turn this test red.
- **Test:** `test_night_states_use_night_hold`.
  - `sleep` and `waking` must give 1800 s.
  - `home_evening`, `home_day`, `guest` and `arriving` must give 60 s.
- **Test:** `test_fan_trust_states_unchanged_and_not_read_by_selector`. This is the §3 guard.
- **Test:** `test_producer_home_night_arms_day_tail`. This is the wire-in anchor.
  - Drive the real `_compute_hvac_occupied` through a falling edge with `house_state="home_night"`.
  - Assert `_hvac_tail_until == now + 60 s`.
- **Test updates** (update these tests, do not delete them):
  - `test_zzz_hvac_conditioning_demand.py:241-262` (`test_d1_night_table_selection`, `test_d1_hold_tables_source_of_truth`): change the `home_night` expectation from 1800 to 60.
  - `test_v5_103_8_hvac_knobs_and_obs.py:154-170` (`test_effective_hold_clamps_night_up_to_day_pure`): switch it to `house_state="sleep"`.
    - **Why:** if it stays on `home_night`, it keeps passing but goes hollow. The day value (600) comes back, which equals the expected clamped value, so the clamp itself is never exercised.
- **Live L1** (21:00–22:00, house in `home_night`). Read the `hvac_vacancy_hold_s` attribute:
  - `binary_sensor.media_media_hvac_occupied` should read **120**. It read 1800 before B.
  - `binary_sensor.kitchen_kitchen_hvac_occupied` should read **60**. It read 90 before B.
  - If B were not applied, these would read 1800 and 90.
- **Live L2** (after 22:00, house in `sleep`):
  - Media reads 1800.
  - Kitchen reads 90.
  - `binary_sensor.jaya_bedroom_jaya_bedroom_hvac_occupied` reads 5400.
- **Live L3** (timing, from the recorder). A media room or bedroom that empties between 21:00 and 22:00 should drop `*_hvac_occupied` within about 7 minutes of `*_occupied` going off: the day hold plus one 5-minute tick.
  - A release around 30 minutes later means B is not working.
  - Common rooms cannot be judged by timing, because 60 s and 90 s look the same at a 5-minute tick. Use L1 for them.
- **Live L4** (fan behaviour unchanged). At 21:30 in `home_night`, `hvac_fans` snapshots still report `sleep_state="sleep"`, as today. The attribute is read from the fan decision snapshot or log.

### Files
- `domain_coordinators/hvac_const.py`
- `domain_coordinators/hvac_zones.py`
- Tests:
  - new `quality/tests/test_hvac_night_hold_follows_sleep.py`
  - updates to the two existing test files named above
- New probe script (D0).
- In the same commit:
  - the state-of-play §3.1 D8 row, §3.3 and header
  - `docs/readmes/README_v5.103.19.md` (PATCH version)

## 6. Tier for B alone: **Tier 1** (recommended)

**Why Tier 1:**
- It is two production files and a one-line rule change, plus a constant.
- It has no new config surface, no database or payload change, and no new caller.
- The shared primitive (`FAN_TRUST_STATES`) is deliberately left untouched.
- Its one behaviour change is operator-directed and bounded to `home_night` hold lengths.

**Protocol:**
- **One adversarial review.** The framing:
  - regression on bedroom comfort between 21:00 and 22:00;
  - independent re-enumeration of `FAN_TRUST_STATES` and hold-selector consumers;
  - hollow-test check on the updated tests.
- **Orchestrator mutation check** at `:1046`, with bytecode disabled and the file restored afterwards.
- **Live L1–L4**, written back into the README.

**When to elevate to Tier 2:** if D0 shows at least 2 exposed gaps per week in at least 2 bedrooms, and the operator still wants B without reviving C.

## 7. Non-goals
- Real sleep detection from bed sensors or activity. House Sleep stays clock-based at entry; the operator accepted this.
- Making the 21:00 `home_night` start (`presence.py:1011`) a knob. **Possible follow-up only.** It also drives fans, D7 and presence.
- Changing `FAN_TRUST_STATES`, the day and night tables, or room sleep-protection hours.
- The per-room start time (C). It is parked (§P).
- The W2 still-sleeper work: §9.3, card `HVAC-NIGHT-LENIENCY-DEGRADATION-DEFENSE-1`.

## 8. Orchestrator verification before ship
1. `git diff` shows `FAN_TRUST_STATES` untouched. The only change in `hvac_zones.py` is the import at `:1002`, the rule at `:1046`, and the docstrings.
2. Grep `_effective_hvac_hold_seconds(`. The only production callers are `hvac_zones.py:1100` and `binary_sensor.py:894`. Both inherit B.
3. The mutation at `:1046` turns `test_home_night_uses_day_hold` and the wire-in anchor red.
4. The test-name diff against `pre-review-v5.103.19` is clean.

## 9. Not done from the original scope
- **C, the per-room "night hold starts at" time.** Parked by the operator ("Lets hold C"). See §P.
- **Label rewording.** Optional; see §L.

## 11. D0 results

Run 2026-09-27 ~22:00 CDT by the orchestrator (`scripts/probes/hvac_home_night_bedroom_exposure_probe.py`), recorder span 7.7 days (includes ~1 empty-house day). Gaps in `binary_sensor.<room>_occupied` starting 21:00-21:59, 60 s-30 min (media 120 s-30 min):

| Room | Exposed gaps | Per week |
|---|---|---|
| Master Bedroom | 0 | 0 |
| Jaya Bedroom (Bedroom 4) | 1 (09-25 21:41, 22 min) | ~0.9 |
| Ziri Bedroom | 0 | 0 |
| Upstairs Guestroom | 0 | 0 |
| Guest Bedroom 1 | 0 | 0 |
| Guest Bedroom 1 Closet | 0 | 0 |
| Media | 0 | 0 |

**Decision rule:** no bedroom reaches 2/week, so C's revival trigger does NOT fire; B stays Tier 1. Residual: Jaya's one 21:41 gap would, under B, release on the 60 s day hold instead of her 5400 s night hold; if zone_2 had no other occupied room it could retreat once a week or so. Mitigations if it shows up: an earlier house Sleep Start Hour, or revive C for Jaya's room.

## §P. PARKED: C, per-room "Night hold starts at" (design kept for revival)

**Revival trigger:** a room needs its night holds to start earlier or later than the house sleep hours. For example:
- D0 shows at least 2 exposed `home_night` gaps per week in a bedroom;
- a child's bedtime falls well before the house Sleep Start Hour; or
- the operator asks for it.

**Design, ready to pick up:**
- **New config key:** `CONF_HVAC_NIGHT_HOLD_START = "hvac_night_hold_start"`.
  - NEW: grep found 0 hits for this name.
  - Knob rung 2: it goes in the room options, climate step, section `climate_backstop`.
  - UI: `TimeSelector`, with `suggested_value` set to the current value.
  - Clearable: add the key to the pop tuple at `config_flow.py:11545-11548`.
  - **UNVERIFIED:** whether a cleared TimeSelector submits the key as absent. If it does not, fall back to a `TextSelector` validated by `_parse_hhmm`.
- **Parsing:** REUSE `energy_pool._parse_hhmm` (`:73`), which accepts `HH:MM:SS`. Do NOT use `hvac_override._parse_hhmm` (`:2038`), which rejects seconds.
- **Do not reuse the room sleep-protection `sleep_start_hour`** (`const.py:1086`):
  - it couples the setting to lighting;
  - it is a whole hour, not a time;
  - it is always stored, so "blank" cannot be represented.
- **Semantics:**
  1. When set, the start time **replaces** the house state for this room; it does not extend it.
  2. The window is [*S*, *E*), where *E* = `sleep_end_hour:00`. The end is read from `presence._inference_engine.sleep_end_hour`. If that is unavailable, fall back to `DEFAULT_SLEEP_END_HOUR = 6`, not the sleep-protection `DEFAULT_SLEEP_END = 7`.
  3. The window wraps across midnight.
  4. A start before the end on the same morning (for example 02:00–06:00) is legal and does not wrap.
  5. A start later than the end in the daytime (for example 07:00) makes a 23-hour window. Log a warning once when the window exceeds 12 hours.
  6. If *S* equals *E*, the window is empty.
  7. During Sleep, when *S* is later than the house sleep time, the room uses its **day** value until *S*. After *E*, a room with *S* uses its day value even while the house is held in SLEEP.
  8. The hold length is fixed at the falling edge.
  9. Nothing is persisted across a restart.
  10. The setting has no effect in hallways.
- **Reload suppression: YES.** The producer (`hvac_zones.py:620`) and the display (`binary_sensor.py:875-878`) both rebuild the merged options on every read.
- **Must also update the display caller** (`binary_sensor.py:894`), and pass `now` and `sleep_end_hour` into it.
- **Planned tests:**
  - `test_room_start_overrides_house_state`
  - `test_room_start_later_than_house_sleep`
  - `test_room_window_ends_at_sleep_end`
  - `test_room_window_wraps_midnight`
  - `test_room_window_non_wrapping`
  - `test_room_window_empty_when_start_equals_end`
  - `test_blank_start_follows_house_state`
  - `test_seconds_format_parsed`
  - `test_garbage_start_follows_house_state`
  - wire-in anchor: `test_update_room_conditions_threads_room_start_and_sleep_end`
  - display parity: `test_display_matches_producer`
  - options round-trip
  - suppression-list membership
- **Tier on revival:** Tier 2. It adds a new config surface and a second caller to thread.
- **Label** (per the operator's 2026-07-10 label rule):
  - Label: `Night hold starts at`
  - Helper: `Optional. The time of day this room switches to its longer night hold. The night hold lasts until the house's wake-up hour (Sleep End Hour in the Coordinator Manager settings). Leave blank to follow the house: the night hold then starts when the whole house goes to Sleep. If you set a time, this room uses it instead of the house's sleep time. It has no effect in hallways.`

---

## §L. OPTIONAL: label wording on the existing hold fields

This follows the operator's 2026-07-10 rule:
- Labels are short phrases.
- Helper text is plain sentences.
- No jargon.
- Named buckets are preferred over raw numbers.

The changes below touch strings only (`strings.json` and `translations/en.json`, which stay identical; options `climate` step). They can ride with B or ship separately, as the operator prefers.

**`hvac_vacancy_hold`**
- **Current label:** "HVAC vacancy hold — day (seconds; 0 = never hold)". This is an internal name with nuance packed into the label.
- **Current helper:** uses "HVAC-occupied", "circulation" and "auto-clamped".
- **Proposed label:** `Empty-room hold (day)`
- **Proposed helper:** `After everyone leaves this room, how many seconds heating and cooling keep treating it as occupied before the zone can switch to Away. This covers quick trips out of the room. Leave blank to use the default for this room type: 60 seconds for bedrooms and living areas, 120 for media rooms. Enter 0 to never hold, which is what hallways use.`

**`hvac_vacancy_hold_night`**
- **Current label:** "HVAC vacancy hold — night (seconds; must be ≥ day, auto-clamped)". Same problems as the day field.
- **Proposed label:** `Empty-room hold (night)`
- **Proposed helper:** `The same hold, used while the house is asleep or waking up. It is longer because motion and presence sensors often miss someone lying still in bed. Leave blank to use the default for this room type: 30 minutes (1800 seconds) for bedrooms and media rooms, 15 minutes for living areas, 10 for bathrooms, garages and utility rooms, and 5 for closets. It must be at least as long as the day hold; a shorter value is raised to match.`
- This helper states B's behaviour ("while the house is asleep or waking up"). If §L ships without B, use "at night" instead.

**Error `hvac_hold_night_below_day`**
- **Current text:** names "HVAC vacancy hold (night/day)".
- **Proposed text:** `The night hold must be at least as long as the day hold. Raise the night value, or leave one of them blank to use the room type's default.`

**Section name `climate_backstop`** (the key itself is unchanged)
- **Current name:** "Climate Backstop (comfort range + thermostat fallback)". "Backstop" is jargon, and the name omits the hold fields.
- **Proposed name:** `Thermostat and empty-room hold`

**Named buckets.** These were considered and not proposed now:
- the live values (90 s and 5400 s) are not bucket values;
- a blank field already acts as the "room default" bucket;
- converting would need a schema migration.

If they are wanted later, the options would be:
- `Room default`
- `Short (1 min)`
- `Medium (15 min)`
- `Long (30 min)`
- `Very long (90 min)`

Each needs a one-sentence consequence in its helper text.

**Acceptance, if §L ships:**
- The strings in `strings.json` and `en.json` match.
- A banned-word check finds none of: `tail`, `HVAC-occupied`, `FAN_TRUST`, `house_state`, `gate`, `backstop`, `hysteresis`, `debounce`, `provenance`, `substrate`, `tier`, `failsafe`, `clamp`.
- The JSON parses, and hassfest passes.
