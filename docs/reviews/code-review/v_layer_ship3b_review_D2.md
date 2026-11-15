# Layer ship 3b, review D2: adversarial completeness re-verification after the fix-up

Branch `feature/layer-ship3b` @ 7897f0aa (worktree `.claude/worktrees/builder-ship3b`). Fix-up diff `dacab04c..7897f0aa`,
whole ship `d0a38ad9..7897f0aa`. Spec `c86b6c74:docs/planning/PLANNING_person_awareness_layer_ship3.md` §6.
Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 through #41) and
`docs/architecture/SENSOR_FLEET_CLASSES.md`; earlier reviews A, B, D, G. No ledger claim re-asserted. No pytest (instructed).
Paths: `csh` = `domain_coordinators/camera_stream_health.py`, `cth` = `domain_coordinators/camera_twin_health.py`.

## 1. MEDIUMs: closed?

| Finding | Re-run repro against 7897f0aa | Verdict |
|---|---|---|
| D-M1 (same-tick S1 + S2 double HIGH) | CM reload at t0+1900 s, owner gone, `POLICY_PAGE`. `_evaluate_hold_pages` runs before the S1 loop (`csh:387`) and puts the key in `_hold_due_keys` whether or not the S2 send is in flight (`csh:506-510`); the S1 loop skips a due key (`csh:401-405`). S2 reads ALREADY_SENT, `mark_paged` latches `_hold_paged`, later ticks skip through `csh:397`. Singleton NOT_SENT variant: the key stays due every tick, so S1 stays skipped. | CLOSED |
| D-M2 (disabled room drops a camera out of U) | Disabled "Playroom": `cth:502-503` skips `disabled_by`, so the device leaves Wr; `binary_sensor.playroom_person_occupancy_2` from the census list enters U, the house tracker stamps it, `entity_stream_view` holds then releases, and a U singleton is in scope (`cth:670-673`), so the owner pages. SETUP_ERROR / MIGRATION_ERROR are skipped too (`cth:504-506`). | CLOSED (see L3 for setup_retry) |
| D-M3 / A-M1 / B-M1 (no camera manager: rooms suppress, nobody pages) | Discovery raises, so `_sets_ready` is never True and `_not_ready_since` is None. `room_page_policy` → `in_map` → `pages_device` False (`cth:390`) → `not_ready_defer` measured from `_setup_at` (`cth:405-410`) → DEFER below 600 s, then PAGE (`csh:1004-1009`). Rooms page S2 at their own cap, or at owner setup + 600 s if that comes later. | CLOSED for room-watched devices (see L2 for U-only devices) |

## 2. The bounded DEFER (A-M1, differs from the brief)

- **Bound:** a not-ready stretch defers at most `CAMERA_TWIN_BOOT_SETTLE_S` from its start. The start is owner setup, or the first owner tick that marks not-ready (`_mark_not_ready`, `cth:412-415`). A short pre-stretch is possible when the sets are ready but the camera manager is already popped: `not_ready_defer` returns True (`cth:403-404`) until the next owner tick, which is at most `CAMERA_TWIN_HEALTH_TICK_S` (30 s) later and starts the clock. **Worst-case room page delay: 600 + 30 s owner tick + 30 s room poll ≈ 660 s** on the shipped constants. It scales with the rung-1 settle (3600 s gives about 3660 s). Out-of-scope groups page at once (`cth:394` then `not_ready_defer` with sets ready and the camera manager present → False → PAGE).
- **Reset:** the defer clock resets only on a ready → not-ready edge. Between such edges the owner is ready and `pages_device` is True, so the defer cannot by itself keep an outage silent. A flapping not-ready stretch moves the clock forward but never extends one stretch past the bound.
- **What can still hide or delay a page:** the owner's own clock, not the DEFER (LOW-1 below). The B-L2 fix clears `_notlive_since` / `_live_since` on every re-ready (`cth:483-492`). In ready windows rooms SUPPRESS, so after each owner-observed not-ready blip the owner restarts the group's S2 clock at (re-stamp + `min cap`).

The DEFER is justified (a plain PAGE gives a false HIGH after each CM reload while a Protect twin covers) and is bounded. Accepted, with LOW-1 fixed or carded.

## 3. Completeness re-enumeration (fix-up surfaces)

| Surface | Check | Result |
|---|---|---|
| `_SEND_INFLIGHT` (`_stuck_signal_nm.py:339-350`) | add before the await, discard in `finally` (a cancel discards too); the second sender of the same key gets NOT_SENT → `mark_not_sent` → retry, then ALREADY_SENT. Owner and room share the pure S2 key, so a concurrent pair of sends cannot deliver two. | PASS. The pre-existing cancel-inside-`async_notify` gap (NM delivered, no latch, then the room pages the same key in the owner-absent window) is documented at `:94-98`; LOW-4. |
| `stuck_signal_dispatch_ready` at the send sites | Room S1 `coordinator.py:2678`, room S2 `:2750`, owner `_send` `cth:999-1001`. Grep of `begin_send` / `fire_stuck_signal_ex` / `send_page_and_mark` finds no fourth site. It reads the same `hass.data[DOMAIN]["notification_manager"]` as `fire_stuck_signal` (`_stuck_signal_nm.py:208, 310`). Recoveries are ungated, which is correct: with NM off no latch could be set. | PASS |
| A-L4 own-camera latch adoption | `_member_own_keys` uses `own_camera_entity_for_device`, the same canonical camera a room's fallback key (`coordinator.py:2843` → `page_camera_key` with no device registry → own camera, `csh:908`) produces. Adoption covers both `_start_episode` (`cth:752-755`) and the sweep (`cth:784-785`); the LOW goes out at `_end_episode` (`cth:985-988`). | PASS |
| D-L2 `adopt_group_s1` | Room key `(GROUP_S1_KEY, _gkey)` with `_gkey` = the pure key; owner key = `_group_page_key` over the same registry, so the keys are equal. Adopted → the input's episode and day are latched (no second HIGH). At the end the room sends both LOWs unless policy SUPPRESS; then the owner's sweep adopts through `_any_latched` (owner S1 key) and recovers. A removed input drops the adoption (`csh:419`). | PASS |
| `_DEAD_ENTRY_STATES` | SETUP_ERROR / MIGRATION_ERROR excluded; setup_retry / not_loaded kept. A normal reload goes through not_loaded → in progress → loaded, never setup_retry, so excluding setup_retry would cost no flap. A room whose first refresh keeps failing sits in setup_retry with no coordinator. | LOW-3 |
| per-tick `_pure_groups` cache | Every caller of `_group_page_key` / `_start_episode` / `_ensure_episode` is inside `_evaluate_groups` (grep). The cache is dropped in the `finally` at `cth:468-471`; nothing builds it outside a tick. | PASS |
| stamp pruning (`cth:771-777`) | Prunes only devices outside scope ∪ episodes. An episode keeps its group observed, so the S2 clock of a live episode is never pruned. A transient U shrink (a census list briefly empty; scope uses the new U, not sticky) can only reset a pre-episode grace. | PASS |
| re-ready stamp clear (`cth:483-492`) | It clears the stamps of groups with an open, unpaged episode as well. | LOW-1 |
| room recoveries during DEFER | A room recovers only what it latched itself (`_hold_paged`, `_paged_episode`, adopted); a recovery of an already-cleared latch is a no-op. | PASS |

## 4. Findings

**LOW-1. Owner clock restarts on every owner-observed not-ready blip; repeated blips can keep an all-lost outage silent.** Bug class: suppression without discharge.
`cth:483-492` (B-L2 fix) with SUPPRESS in ready windows (`csh:1006-1007`). Repro (legal; nothing but integration-entry reloads):
- Setup: the playroom Frigate + Protect W1 pair is in the map with a room input, caps 900 / 900.
- Both NVRs lose the camera at t0.
- At t0+600 s the integration (parent) entry reloads across one owner tick: `camera_manager` is popped (`__init__.py:5904`), that tick marks not-ready, and rooms DEFER.
- At t0+630 s the owner is ready again: stamps are cleared, and the device re-stamps at t0+630.
- The owner sends S2 at about t0+1560 s, not t0+900. The rooms' own S2 (due at t0+930) is SUPPRESSED.

If parent reloads that each span an owner tick come every < ~930 s, no HIGH is ever sent. A reload that completes between two owner ticks causes no clear. This is the same class the doc already accepts for restart and room reload ("can extend a hold by up to grace + the cap"), but here only the owner resets while the rooms' clocks keep running.
Fix (small): skip the clear when the not-ready stretch was shorter than `CAMERA_INPUT_STREAM_DEAD_GRACE_S`, or keep `_notlive_since` for devices in an open episode.

**LOW-2. U-only devices get no hold and no page while the camera manager is absent.** Bug class: degraded-mode gap.
`_compute_sets` returns not-ready without a camera manager (`cth:479-482`), so `house_tracker_for` gives None (`cth:578-584`) and no U singleton is in scope. Repro: `CameraIntegrationManager.async_discover` raises at setup (`__init__.py:2937-2948`), and the foyer Frigate camera (live U, a zone camera, no room input) dies. D6 Source 3 reads it raw, as on develop, and no page is sent. The census is absent in that state too (it is created in the same try), so only the zone readers are exposed. This is develop parity, not a regression. Card it, or compute U from the zone list without the camera-manager gate.

**LOW-3. A room stuck in setup_retry keeps its devices in Wr with no watcher.** This is the D-M2 shape for a persistent `ConfigEntryNotReady` from `async_config_entry_first_refresh`. It needs a room whose update raises on every attempt. Adding `setup_retry` to `_DEAD_ENTRY_STATES` costs no reload flap (§3), and sticky U covers recovery.

**LOW-4 (pre-existing, documented).** A send cancelled inside `nm.async_notify` at owner teardown can deliver without setting a latch, so the room pages the same key in the owner-absent window: two HIGHs. The comment at `_stuck_signal_nm.py:94-98` names it. Latching before the await, rolled back on a definite failure, would close it. Card.

**Carried, unchanged:** D-L1 (non-input entity on a watched device, latent) and D-L3 (rung-1 caps above NM_AFTER give S1 + S2).

## 5. Invariant checklist

| Invariant | Verdict |
|---|---|
| INV-DEAD-INPUT (a dead-camera input is held, then released at the cap; never counted live while dead, never as zero) | PASS on the reachable shapes (D-M2 closed). Residuals: LOW-2 (no camera manager, U entities), LOW-3 (setup_retry room), D-L1 latent |
| INV-DEAD-CAMERA: fires only when all NVRs lost | PASS (owner gate `_group_dead` + latest-loss clock, `cth:835-841`; rooms SUPPRESS in map) |
| INV-DEAD-CAMERA: always fires when all lost | PASS for rooms (bounded DEFER, worst delay ≈ 660 s on shipped constants). Eventual for the owner, except LOW-1 under repeated tick-spanning parent reloads; LOW-2 for U-only devices with no camera manager |
| INV-DEAD-CAMERA: at most one HIGH per episode | PASS (D-M1 via `_hold_due_keys`, D-L2 via `adopt_group_s1`, A-L4 own-key adoption, `_SEND_INFLIGHT`). LOW-4 pre-existing; dissolve gives a LOW, then a per-device HIGH (by design) |

## 6. Verdict

**SHIP.** All three MEDIUMs are closed against the new code, and the bounded DEFER is sound. LOW-1 is a ~5-line fix worth doing in-cycle under fix-LOWs-in-cycle; LOW-2, LOW-3 and LOW-4 should be fixed or carded.
