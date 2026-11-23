# Review D (adversarial completeness) + G (goal fidelity): crossing vision Phase 3 first set (P3-D1, P3-D5, P3-D8)

Branch `feature/crossing-p3-first` at 48d4bc94, worktree `.claude/worktrees/builder-crossing-p3`. Diff base 340bfe7f (merge-base with develop, three-dot). Spec `docs/planning/PLANNING_crossing_vision.md` at 50bffd62. Read-only; no pytest run (framing C owns that).

Read first: `docs/architecture/SENSOR_FLEET_CLASSES.md` completely; `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` header block (S1, S2, ledger, DEAD INPUT HOLDS, the new P3 paragraph); audits `AUDIT_upguest_fan_held_occupancy_2026_11_15.md`, `AUDIT_mediaroom_fan_left_on_stuck_sensors_2026_11_15.md`, `AUDIT_crossing_vision_day_2026_11_14.md`. No corrections-ledger claim is re-asserted.

**Verdict: SHIP for correctness (no CRITICAL / HIGH leak in the stated invariants). Goal: NOT MET by this ship alone (G-1, G-2). The operator should hear that before it is described as unblocking the anchor.**

## G: goal fidelity

The goal: unblock the empty-house anchor on the stuck inputs found on 11-15, so door vision can move toward feeding the census. Ground truth used: NM `notification_log` (P22 "continuously on ... excluded" rows, UTC) plus the two 11-15 audits.

| Live case | How it is excluded today | Would P3-D8 have released the anchor on 11-15? |
|---|---|---|
| Media Matter radar `binary_sensor.mmwave_motion_lux_matter_wifi_mediaroom_occupancy` | P22 `p22_continuous` from 23:41 CST 11-14 (NM 05:41Z) to the 13:53 drop | It drops out of `held`. But the room's other Tier-1 input, the Meross bit `..._sensor_presence_motion` (`motion_sensors`), is chatter in **shadow** mode (`DEFAULT_CHATTER_MODE = shadow`, `const.py:6193`), so it is never promoted and still holds whenever it reads `on`. It also flapped 1,435 times in 18.2 h with a longest quiet gap of 10.5 min, and each flap is a substrate rising edge (`_on_substrate_edge`, `crossing_vision.py:1338`, `_edge_since_sample`, `crossing_ledger.py:401/480`). The window is 900 s, so the anchor stays blocked. **No.** |
| Upguest Hobeian ZV `..._upguestroom_presence_2` (ZG-204ZV, `motion_sensors`, motion-class) | P22 only. It fired once, 12:51:52 CST (NM 18:51Z). The 13:51:48 1.8 s off pulse cleared `_sensor_on_since` (`coordinator.py:3735-3742`) and re-armed the 4 h timer. The next possible exclusion was ~18:32. Duty-cycle never applies to motion-class; chatter does not fire on 1.3-4 s pulses. | Excluded only from 12:51:52 to 13:51:48. The house went AWAY at 13:43:29, which leaves 8 min of AWAY inside the exclusion, under the 15 min window. A real visit (Matter radar) from 12:59 to 13:07 also held and produced edges. For the AWAY afternoon the ZV held the anchor as before. **No.** |

**G-1 (goal, HIGH for the arc).** On 11-15, P3-D8 would not have produced an anchor for either live case. Upguest needs the K2 off-pulse fix first: P22 must not reset on a sub-N-second off pulse. That fix is a prerequisite, not a follow-up.

**G-2 (goal, HIGH for the arc).** P3-D8 filters the anchor's held levels but not its rising edges. `_on_substrate_edge` takes kind-level edges, and the substrate does not honour room exclusions (STEP-EXCLUDE-4). A chatter-excluded input flaps by definition, so even in act mode its edges keep resetting `_t_start`. The `chatter` client in `CROSSING_VISION_ANCHOR_STUCK_CLIENTS` is therefore close to inert. Media room needs two things:
- the Meross bit in chatter act mode, or reclassified;
- an edge filter: drop a (room, kind) rising edge when every `on` input of that kind in that room is stuck-excluded.

Without both, the media room keeps blocking. This is a design gap in the plan, not a build deviation. The plan's Live criterion ("first anchor fires within RESET_S + one eval once no other holder remains") quietly assumes no other holder, and on 11-15 there was one.

The build itself keeps the operator line exactly ("stuck-excluded stops holding; a dead sensor holds"):
- release requires `state == "on"` and `view is None` (`crossing_vision.py:1319`);
- `dead_held` is never reduced, because ignored inputs are live by construction;
- `classify_held` still records the ignored input's `on` as last-good, so it holds if it later dies (`:1327-1331`);
- the camera-stream client is not in the set (`const.py:3676`);
- the label map is not read.

## D: invariants, falsifiable form

### P3-D8: "a Tier-1 input stops holding only when it reads `on`, has no stream view, and some room excludes it under p22_continuous / chatter (act) / stuck_dutycycle; otherwise it holds"

Every path into `_held_inputs`: one caller (`_on_ledger_eval`, `:1399`), one release site (`:1319-1331`), one source (`input_room_stuck_excluded`, `_ask` fold where any True wins, `camera_stream_health.py:1245`, `coordinator.py:2798`). Writers of the three clients: P22 `coordinator.py:3780`, chatter `:3094` (inside `is_act` only), duty-cycle `:3848` (inside `_promote_dutycycle_to_exclusion`, which is SLEEP / WAKING / HOME_NIGHT-gated, `:3360`). `reset_tick` (`:3772`) precedes all of them, and a paused room still ticks (no early return before it, `:3684-3772`). Exceptions inside the sweep give no opinion, so the input holds.

| Probe | Result |
|---|---|
| Dead input that is also stuck-excluded | Holds: PASS. Pinned by `test_dead_input_still_holds_even_if_stuck_excluded`, `test_stream_dead_on_input_still_holds_even_if_stuck_excluded`. |
| Label-only duty-cycle sleeper / shadow chatter | Holds: PASS. |
| Camera-stream client alone | Holds: PASS. |
| Sleeper's radar promoted `stuck_dutycycle` | Unreachable in SLEEP / WAKING / HOME_NIGHT (`:3360`). Reachable in a daytime nap (HOME_DAY, PIR corroborator off for ≥ `CORROBORATOR_DISAGREE_S`). See D-M1. |
| Read during a room tick, between `reset_tick` and promote | Sees no exclusion, so the input holds (fails safe). PASS. |

**D-M1 (MEDIUM, named residual; operator disclosure; Bug Class "safety gate on one client, not its sibling").** P22 has no house-state gate (`_p22_stuck_sensor_set`, `coordinator.py:2375-2400`; fixed 4 h, `:401`), unlike duty-cycle. A still occupant on a true presence radar is P22-excluded at 4 h. The anchor then ignores them.

Legal repro:
- A phone-less guest (not in R) sleeps or watches a film still, in a room whose only Tier-1 input is a ZK / ZX / Matter radar that reads `on` for more than 4 h with no off sample at the 30 s poll.
- The residents' rooms are either off, or P22-excluded the same way.
- No exterior camera body.
- No other rising edge for 900 s.

Then at 4 h + 15 min the anchor sets L = R and the guest drops out of the awareness count until a later crossing. Before P3-D8 the radar blocked this.

Observed rate: NM shows 4 P22 fires since late October, none on a sleeping-bedroom radar (radar off-flicker resets the timer). So the case is rare but legal. Impact today: display and shadow only (`AWARENESS_VISION_LEADS` False). It becomes census-relevant at P3-D3 / F-LEAD.

The plan text says "a sleeper's duty cycle still holds", which reads as if sleepers are safe; for P22 they are not. Fix options (operator's call):
- (a) accept and name it in the plan and the STATE_OF_PLAY paragraph;
- (b) apply the `_d2_house_state_allows` gate to the `p22_continuous` client for the anchor only.

This is not a deviation from the approved line; it is a consequence the approval may not have priced.

**D-L1 (LOW).** One input listed in two rooms: each room samples it on its own 30 s poll. Room A misses a 1.8 s pulse and P22-excludes it. Room B saw the pulse, reset its timer, and counts the input as live occupancy. Any-True-wins releases the anchor while room B holds the room occupied. Bounded and rare. Accept, or fold as "all rooms that list the input agree".

### P3-D5: "calls per local day ≤ cap across restarts"

| Attack | Result |
|---|---|
| Restart storm | Each setup holds the counter at the cap until the count lands (`_calls_counted`, `:382-388`; schedule gate `:745`). Rows are counted by `ended_at` with `json_extract` outcome IN `CALL_OUTCOMES`. PASS, except the plan-named residual: calls in flight at stop are cancelled after the 5 s teardown gather (`:506-517`, `CROSSING_VISION_TIMEOUT_S` 90), so they are billed but have no row. That is ≤ `MAX_CONCURRENT` = 2 per restart. Named in plan step 4; not a finding. |
| Slow DB | `wait_for` 30 s, retry after 60 s, then hold until midnight with a LOW page. Fails closed. PASS. |
| Midnight during rehydrate | Construction calls `_roll_day` (`:353`), so the first in-task `_roll_day` only clears the hold if the date really changed. In that case this process has run since before midnight, so no prior process made a call today. A result for the old day is discarded (`self._day == day`, `:1031`). PASS. |
| Mixed timestamp formats | The mix in the 11-14 audit is in `started_at` (crossing key, sometimes -06:00). The DAO filters on `ended_at`, which the writer has always set as `dt_util.utcnow().isoformat()` (`:1135`, since 74c92ea4). Bounds come from aware UTC `isoformat()`. In the same second, `.ffffff` sorts after `+` (0x2E > 0x2B), so the half-open compare stays exact with or without microseconds. DST is handled by `start_of_local_day(date)`. PASS. |
| Outcomes not in `CALL_OUTCOMES` | A made call ends as ok / blank / unparseable / refused (parse, `:150-245`), timeout, or error (`:961-967`). All six are counted. `no_frigate_event` / `no_clip_url` / `clustered` / `skipped_*` are not calls. A call that returns then raises in `_run` before `_record` gets a RAM count but no row; that is a narrow undercount on restart, covered by the same residual class. PASS (LOW note). |
| `_run` gate uses `_calls_today`, not `_calls_counted` (`:916`) | Benign. Every request after setup passes the schedule gate first (`:745`). Setup is synchronous from subscribe to hold (`:425-452`), so no event can interleave. |
| Cross-day write skew (call at 23:59:59, row after midnight) | `ended_at` ≥ fire time, so a restart over-counts the new day (conservative). PASS. |

**D-L2 (LOW).** Rows that `log_memory_episode` fails to write are swallowed with only a WARNING (`database.py:10800`, not via the write queue). Each one is an undercount after a restart. Same class as the plan's named residual. Note it there.

### P3-D1: "error text never carries secrets or PII into the DB or the NM page"

The text reaches the row only (`:1101-1107`). It is not in `_last`, not on any sensor attribute, and not in any NM page (grep: one consumer). The source is `str(exc)[:200]` from the llmvision service call (`perimeter_enrichment.py:451-456`). llmvision raises either `f"Request failed: {e}"` on an aiohttp exception from `session.post(url)` (`llmvision/providers.py:541`) or a parsed provider error body (`:547`). llmvision strips `?key=` only from its debug log URL (`:531`), not from that exception text.

**D-L3 (LOW).** An aiohttp exception whose `str` includes the request URL (for example an invalid-URL error on a Google-style `?key=` endpoint), or a provider 401 body that echoes a masked key, would be stored in `memory_episodes`. The same text already goes to the HA log (llmvision `_LOGGER.error`, `providers.py:209`), so this adds no new exposure class, but it persists. Cheap fix: before storing, regex-scrub `key=[^&\s]*`, `sk-[A-Za-z0-9_-]+` and `Bearer \S+`. No PII path was found: the prompt, frames and person ids are not in the error text.

## Invariant checklist

| Invariant | Verdict |
|---|---|
| P3-D8: dead input always holds | PASS |
| P3-D8: label-only / shadow chatter / camera-stream client always hold | PASS |
| P3-D8: no real occupant dropped | LEAK by design, named: D-M1 (P22 still occupant, no house-state gate); D-L1 |
| P3-D5: ≤ cap across restarts | PASS except the plan-named in-flight residual (≤ 2 per restart) and D-L2 |
| P3-D1: no secrets / PII to the DB or NM | PASS for NM; D-L3 for the DB (low probability, mirrors the HA log) |
| G: unblocks the 11-15 live stuck inputs | NOT MET (G-1, G-2) |

## Verdict

**SHIP** (correctness). No must-fix in the code as specified.

Before this ship is called "the anchor is unblocked":
1. Tell the operator G-1 and G-2. On 11-15 the anchor would still have been blocked:
   - upguest needs K2 (a P22 off-pulse debounce);
   - media needs the Meross bit in chatter act mode (or reclassified) plus a stuck-aware edge filter in `_on_substrate_edge`.
   Card both as prerequisites of P3-D3 (no silent deferral).
2. Disclose D-M1 and get the operator's call: accept, or gate P22 for the anchor in SLEEP / WAKING / HOME_NIGHT.
3. Optional LOWs: D-L3 scrub; D-L2 and D-L1 notes in the plan residuals.
