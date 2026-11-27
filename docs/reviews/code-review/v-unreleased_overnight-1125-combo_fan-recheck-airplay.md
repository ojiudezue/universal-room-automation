# Review: overnight-1125 combo (fan-recheck reload suppress + MF AirPlay non-transferable)

Branch `origin/combo/overnight-1125` @ 715018364, diff `develop...origin/combo/overnight-1125`.
Tier 1, framing A (local correctness + blast radius). Read-only review; pytest not run (suite running separately).

Presence doc: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` was read in the fan-recheck sections (§5/§6 item 3, lines 35-36, 600-744) and searched for "recheck". It was not read cover to cover. Nothing in this diff contradicts it.

## Verdict: SHIP

## Fix 1: PRESENCE-FAN-RECHECK-RELOAD-SUPPRESS-1

Holds:
- The 8 literals match `const.py:908-1038` exactly. `test_literals_match_const` pins this.
- `_timing_config` (`presence_fan_recheck.py:1293-1330`) re-scans the CM entry options on every call with no cache. All consumers call it at use time:
  - eligibility: `:537`, which feeds ticks at `:588` and max_per_hour at `:661`
  - arm delay: `_enter_armed` `:735`
  - spindown, window and hvac_suppress: `_enter_paused` `:812`, `:822`
  - window and family factor for the outcome row: `:994`, `:1006`
  - family scaling: through `_family_factor` / `_effective_window_s` (`:1488` and following), which take the passed-in `timing`
  - cooldown: `_enter_cooldown` `:1086`
- No other module reads these keys. `git grep CONF_FAN_RECHECK_` finds only `config_flow.py` (writer) and the `__init__.py:2635` orphan-Number cleanup (unique_id strings, not option reads).
- Captured-at-arm semantics: arm delay, spindown, window and cooldown durations are fixed when that state is entered. A save changes the next transition, not an in-flight timer. Acceptable. Before this fix the reload tore down in-flight state, so this is less disruptive.
- `mmwave_history_ticks` slices a ring of fixed `maxlen=10` (`coordinator.py:588/595`). The options selector caps it at max=10 (`config_flow.py` ~5438), so a live change cannot outgrow the ring.
- `max_per_hour` is compared against `ctx.attempts` at use time (the deque `maxlen=10` is pre-existing and the same as before).
- Mechanism (`__init__.py:8899-8956`): `changed_keys` is a value-normalised diff of the snapshot against the new options. Only keys that changed count, so the unchanged `fan_recheck_enabled` and other Presence-step keys that are re-persisted do not force a reload. A save that changes a suppressed key AND an unsuppressed key still reloads in full (legacy, correct). `_NO_LIVE_ATTR_KEYS` membership puts the keys into `applied` (`:8601`), so the snapshot advances. Without it the snapshot would keep the old value and re-diff on every save.
- NumberSelector float vs stored int: `47.0 == 47` in `_norm_cm_opt`, so there is no spurious change.
- trust_sensors_ok exclusion is correct. It is read only from the merged ROOM entry (`presence_fan_recheck.py:722-724`) and is written by the room options step (`config_flow.py:2813`).

## Fix 2: MF-MA-PATH-NON-MA-SOURCE-1

Holds:
- The gate (`music_following.py:2631`) runs in the automatic decision path after source and target resolution and BEFORE `_cancel_reversal_watch`, preferences and `_transfer_then_release`. That covers the MA, join and generic paths, so no fade or play_media happens first.
- It reads `from_state = states.get(rec.source_player)`, the room's configured primary player. If that is the linkplay entity, `source="AirPlay"` matches `MF_NON_TRANSFERABLE_SOURCES`. If it is the MA twin, `media_content_id="wiimu_airplay"` or `"AIRPLAY"` matches the content prefix. The twin's state is not consulted when the linkplay entity is primary, and it does not need to be.
- False matches: MA URIs (`library://`, `spotify:`, `media-source://`, `http(s)://`, `apple_music://` etc.) cannot start with `airplay` or `wiimu_airplay`. Only an id literally beginning "airplay" (any case) matches.
- Lower-casing only widens the existing Sonos prefixes (`x-sonos-htastream:`, `x-rincon-stream:`, already lower-case) to upper-case variants. It never narrows them.

## Findings

| # | Sev | Where | Finding | Class |
|---|---|---|---|---|
| A-L1 | LOW (pre-existing) | `music_following.py:3814-3838` `manual_transfer` | The manual transfer path never calls `_non_transferable`. A manual move of AirPlay, TV or line-in still ducks the source and sends a URI the target cannot play. The plan claims "every path"; that holds for automatic moves only. Card it, or add the gate after the `source_playing` stamp. | #53 one-missed-site |
| A-L2 | LOW (pre-existing, adjacent) | `__init__.py` OPTIONS_RELOAD_SUPPRESS_KEYS | `fan_recheck_enabled` (the master, saved on the same Presence step and mirrored live into `hass.data` at `config_flow.py:5213-5218`) is not suppressed, so toggling it alone still reloads the CM even though the value is already live. Candidate for the same set. Not a regression. | reload hygiene |

No CRITICAL, HIGH or MEDIUM findings.

## Test anchoring (by reading)

- `test_fan_recheck_reload_suppress.py` drives the real `_async_update_listener` and the real `_timing_config`.
  - Removing a key from OPTIONS_RELOAD_SUPPRESS_KEYS makes it fall through to reload, so `create_task` is called once and the test goes RED.
  - Removing it from `_NO_LIVE_ATTR_KEYS` leaves it out of `applied`, the snapshot keeps the old value, and `snap[key]==value` goes RED.
  - Anchored per key through parametrize, with a discriminator (a non-allowlisted key reloads).
- MF tests:
  - Reverting the `"airplay"` source turns `test_mf_airplay_source_skipped_before_ma` RED.
  - Reverting `"wiimu_airplay"` turns the wiimu test RED.
  - Reverting `.lower()` or the `"airplay"` prefix turns the uppercase test RED.
  - The regression test pins that a real MA queue still takes the MA path.
  - All four assert no side effects.
- `test_part2_ec_hc_writeback.py` pins the EXACT suppress set (`EXPECTED_SUPPRESS_KEYS`) and its cardinality (141 → 149), so adding 8 keys must update both. Its AST loader and the three sibling loaders (`test_cm_reload_suppression`, `test_reload_watchdog_hazard`, `test_room_options_reload_suppression`) exec only whitelisted assignments. The frozensets now splat `*_FAN_RECHECK_TIMING_KEYS`, so the name must be in each keep-set or the loader would NameError. These are mechanical, required edits.

## Stats

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL | 0 | - | - |
| HIGH | 0 | - | - |
| MEDIUM | 0 | - | - |
| LOW | 2 (pre-existing) | 0 | 2 (recommend card) |

| Bug class | Count |
|---|---|
| #53 computed-but-not-consumed / one-missed-site | 1 |
| Reload hygiene (allowlist gap) | 1 |

QUALITY_CONTEXT: no new class.
