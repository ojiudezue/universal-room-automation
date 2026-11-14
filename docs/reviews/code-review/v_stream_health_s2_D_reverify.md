# Camera input stream health S2: framing D re-verify of the fix-up

Branch `feature/camera-input-stream-health-s2`, fix-up commit `6989c608` on top of reviews A/B/C (their HEAD `8fee2e47`; the
review commits end at `d92389e8`). Diff reviewed: `git diff d92389e8..6989c608` (fix-up only, code files read in full).
Read completely first: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. the S2 header entry and §10 #39),
`docs/architecture/SENSOR_FLEET_CLASSES.md`, `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`. No §10 claim re-asserted.

Ruling under test: "A dead input holds instead of releasing." Hard constraint: "away to be fast acting."

## Invariants, falsifiable form

1. Under any legal config, a camera dying cannot by itself move a zone occupied -> vacant, or the house to AWAY (zone
   substrate, camera tier, night limb, census).
2. A real departure reaches AWAY no later than on develop, on every AWAY path (α, β, nobody-home).
3. Every hold ends (live input `on -> off` in the same room, camera recovery, `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S`,
   0 = no hold), with no stuck level across restart or reload.
4. The census hold's AWAY-delay exposure is bounded and stated per option.

## Findings

| # | Sev | Where | Finding |
|---|---|---|---|
| D-M1 | MEDIUM | `occupancy_substrate.py:296-327` (`_kind_on_now`), `:888-893`; `camera_census.py:2072, :2204` (`_is_entity_available`) | **Invariant 1 leaks when the input goes `unavailable` together with its camera.** The hold starts only once the camera has read `unavailable` for the 120 s grace. An input event `on -> unavailable` before that is treated as live and counts as off, so the kind drops to False at t0. After the grace the hold engages but keeps `prior`, which is now False. The census drops it too, because an unavailable entity is a missing term. UniFi Protect does exactly this: on a device disconnect it sets `available=False` on every entity of the device (HA `unifiprotect/entity.py:220-240`, `connected = device.state is CONNECTED`). **Legal-config repro:** a Protect camera's `binary_sensor.<cam>_person_detected` is a room's presence input (own camera resolves to one enabled `camera.*`). The house is in SLEEP, a phone-less guest is in that room, and it is the zone's only `on` input. The camera drops off Wi-Fi, so both entities read `unavailable` in one update. The substrate kind goes off at t0, the zone empties, the census reads 0 (missing term), and nobody-home proposes AWAY on the next inference. This path is identical on develop (not a regression), and the live config does not hit it: the only camera-derived room inputs today are the three Frigate panel sensors (Study A, Kitchen, Upstairs Hallway; read from `.storage/core.config_entries`). Their availability is Frigate's MQTT topic (`frigate/__init__.py:716-768`), not the camera stream (`frigate/camera.py:321-336`), so they stay available and frozen, which is the case S2 handles. But the S2 header and §10 #39 say the invariant holds in general, and it does not. **Fix (pick one):** (a) narrow the claim in PRESENCE §S2 header + README to "an input that keeps a reading while its camera is unavailable" and card the Protect shape; or (b) at the zone tier and in the census, treat an `unavailable` reading from an input whose own camera currently reads `unavailable` as held from t0 instead of as off. |
| D-M2 | MEDIUM (operator decision input, see the exposure table below) | `camera_census.py:2666-2695` (`_stream_dead_interior`), `const.py` `CAMERA_INPUT_STREAM_DEAD_HOLD_MAX_S` | **One constant governs both the zone hold and the census hold.** A "~30 min census hold" option therefore needs a second rung-1 constant, e.g. `CAMERA_INPUT_STREAM_DEAD_CENSUS_HOLD_MAX_S`, read only in `_stream_dead_interior` through a census-specific expiry. Today `entity_stream_view` folds the room tracker's single `_hold_expired_now`, so the split is not a one-line change. The census option also does not control β or nobody-home: if the dead input is a substrate-mapped room input, the ZONE hold (4 h) blocks those paths whatever the census option is. |
| D-L1 | LOW | `camera_census.py:2143-2158` | **The zone hold reaches path α through census divergence corroboration.** `_any_zone_occupied_snapshot()` reads tracker `mode == "occupied"`, so a zone held by a dead camera "corroborates" a divergent Frigate/binary count and keeps the higher one. That can hold `unidentified_count >= 1`. The doc line "path α reads neither zone occupancy nor the substrate" (S2 header, "What stays fast") is therefore incomplete. Reaching it needs a live camera on a second platform that reads a non-zero count while the other platform reads less. The effect is bounded by the 4 h zone hold, and it is no worse than develop, where the frozen input held the zone forever. Fix: add one clause to the doc. |
| D-L2 | LOW | `occupancy_substrate.py:927-942` (`_is_live_end`) | A live sensor that the room tier has chatter- or stuck-quarantined still counts as a "live end" at the zone tier, because the substrate ignores room exclusions (STEP-EXCLUDE-4, unchanged). A chattering sensor's `on -> off` therefore releases a dead-camera hold early. It errs toward vacancy, but only on a working-but-noisy sensor in the same room, never on the camera itself. Accept by name or card it. |
| D-L3 | LOW (test scope) | `quality/tests/test_camera_stream_health_s2.py:805-832` | `test_real_departure_away_not_slowed_by_hold` passes `census_count=0, unidentified_count=0` by hand. It proves α ignores `any_zone_occupied`, which is true. It does not cover the case where a dead camera froze a body count, which is the delay the operator is choosing a bound for. The doc's "what stays fast" sentence relies on this test, so state the census caveat next to it (the header already does in its next sentence). |
| D-L4 | LOW (UNVERIFIED onset) | n/a (Frigate server behaviour) | Whether Frigate publishes `person` off / count 0 when a camera's fps drops to 0 is unverified. If it does, a Frigate camera dying looks like a live end inside the 120 s grace, and invariant 1 leaks the same way as D-M1. Discriminating probe: in the recorder, take a past `camera.<frigate cam>` `unavailable` episode and check whether its `_person_occupancy` / `_person_count` changed within 0-120 s of the camera's edge. The S1 card's observed frozen-panel `on` suggests it does not (it stays frozen). |

## Exposure of the census hold (invariant 4)

Definitions:
- T = the camera's first `unavailable` room tick. The room polls every 30 s, and that tick also starts the hold clock.
- The input is "dead" at T + 120 s (grace).
- D = when everyone leaves, with the dead camera frozen on a body count ≥ 1.
- AWAY paths that read the counts: nobody-home (`census_count == 0`, `presence.py:1253`), α (`unidentified_count == 0 and face_recognized_count == 0`, `:1300-1305`), β (`unidentified_count == 0 and census_count == 0`, `:1378-1382`).

All three AWAY paths are blocked while the frozen count is counted. The hold ends on the first room tick (≤ 30 s) at or after T + H. The census reads the view on its next periodic run, and a count change triggers inference at once (`presence.py` `_handle_census_update`, `old_unidentified != ...`).

| Option | Extra AWAY delay on a real departure (α path, all trackers away) | Can a camera death alone fire AWAY? |
|---|---|---|
| 4 h (as built) | max(0, T + 14400 s − D) + ≤ 30 s + one census period. Worst case ≈ 4 h, when everyone leaves just after the camera dies. Likely shorter for a Frigate count camera: the pre-existing stuck-camera watchdog discounts a non-zero count unchanged ≥ `CONF_STUCK_CAMERA_HOURS` (default 3 h) when the camera's area has no interior corroboration (`camera_census.py:2819-2918`). The room tier excludes the dead input (S1), so the area has none, and the hold is effectively ~3 h for Frigate count cameras. UNVERIFIED end to end (not drilled). | No, except D-M1's `unavailable`-input shape. |
| ~30 min (needs a separate constant, D-M2) | max(0, T + 1800 s − D) + ≤ 30 s + one census period, worst ≈ 30 min. | Yes, after 30 min. A guest seen only by that camera, with every resident tracker away, lets α fire at T + 30 min. |
| No census hold (H_census = 0) | ≤ T + 150 s − D when D < T + 150 s, else 0 (identical to a live camera). | Yes, at T + ~150 s through α, in the guest-only-seen-by-that-camera shape (the S2 first build's B-M2 finding, now for α rather than nobody-home). |
| develop (reference) | Unbounded: develop reads the frozen sensor raw for as long as the stream is dead. | No. |

On every row, β and nobody-home are additionally held by the ZONE hold (4 h) whenever the dead input is a room input in the substrate. A frozen face sensor keeps `face_recognized_count` for ≤ `CENSUS_FACE_RECOGNITION_WINDOW_SECONDS` (1800 s) on every option; that is pre-existing and not stream-aware (the S2 header names it as not covered).

## Checks that hold

- **Live-end rule: flapping and attribute-only updates.** `_is_live_end` (`occupancy_substrate.py:927-942`) needs old `on` and new `off`, plus a live view. These do not release: attribute-only `on -> on` / `off -> off`, `on -> unavailable`, `unavailable -> off`, and an event from a dead input. Mutation drills on this worktree (cache cleared, `PYTHONDONTWRITEBYTECODE=1`, S2 test file only, tree restored, `git status` clean apart from the builder's untracked `.claude/s2fix_drill.py`):
  - dropping the `old == "on"` test fails `test_zone_sibling_dead_input_holds_until_live_end`;
  - returning True for a dead input fails `test_zone_dead_input_event_does_not_end`.
- **Holds end (invariant 3).**
  - Live end: `_release_room_holds` (`:371-402`) releases the other held kinds of the room and does nothing when nothing is held.
  - Recovery and 4 h: the room tick's flip set includes `hold_expired_now ^ prev_expired` (`coordinator.py:2640-2651`), which drives `recheck_entities`.
  - `H = 0`: `(now - since) >= 0`, so the input is released at once (`camera_stream_health.py:281-287`).
  - Camera tier: `released` is skipped, and a recovered camera is resynced from its live state (`presence.py:837-866`).
  - Kill switch: `is_dead` is never True, so every view is None.
  - Restart or reload: everything is RAM. The frozen input counts as live until grace, then is held again. Each restart or reload extends a hold by ≤ grace + 4 h (documented, B-L5).
  - Refresh: the seed passes `prior=pre_reset` (`:477-481`) and keeps a held level, while views are re-read fresh.
  - I found no reachable state where a kind stays True with no held input and no `on` input.
- **Event-loop cost is bounded.** Each `_stream_view` call folds over the room coordinators (`camera_stream_health.py:364-397`, about 40 attribute calls). One substrate event costs (siblings + 1) views. A live end adds at most 3 kinds × the house entity map. The camera tier asks the getter only for a camera that holds or was ignored. The census asks once per interior camera per run. No I/O, no awaits.
- **HVAC D6 Source 3** (`presence.py:2482-2489`): a held or released dead camera confirms nothing, so the 4 h D6 failsafe can release a zone held by a dead camera. This matches HVAC doc §3.2 and its 2026-11-14 header.

## Invariant checklist

| Invariant | Verdict |
|---|---|
| 1. A camera death alone cannot empty a zone or fire AWAY | **LEAK** (D-M1, legal config, not live; develop-identical). Holds for inputs that keep a reading (the live Frigate panels). Onset for Frigate unverified (D-L4). |
| 2. A real departure is no slower than develop | **PASS.** Every S2 hold is bounded where develop was unbounded. Relative to "no census hold", the 4 h census hold delays α by up to 4 h (table above). |
| 3. Every hold ends, nothing stuck across restart / reload | **PASS** (bounded extension per restart, documented). |
| 4. Census exposure quantified | Done (table). One constant serves both tiers (D-M2). |

## Verdict

**SHIP**, conditional on the doc fix-up below. I found no CRITICAL or HIGH. D-M1 is a pre-existing gap and does not apply to the live config, but the S2 header, README and §10 #39 currently claim invariant 1 in general. Must-fix before deploy (documentation only, ≤ 30 lines):

1. D-M1: narrow the invariant claim to inputs that keep a reading, and card the `unavailable`-with-camera shape (Protect device disconnect).
2. D-L1: one clause noting that the zone hold can reach α through census divergence corroboration.
3. D-M2: record for the operator that a 30-min census option needs its own constant, and that β / nobody-home stay on the zone hold whatever the census option.
