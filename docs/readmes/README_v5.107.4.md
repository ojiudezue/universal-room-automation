# v5.107.4 — A camera face alone no longer unlocks

**Card:** LOCK-REGIME-FACE-ARRIVAL-CORROBORATION-1 (related PERIMETER-FP-STREET-NOISE-1 D10.5,
FACE-SOURCE-REGISTRY-DISCOVERY-1).
**Tier:** 2 (operator-approved build 2026-11-08). Unlock path, so it touches safety, but the change only removes a
release path. It adds none. No DB, config or entity change.
**Version:** PATCH.

## Why
`security_lock_regime.on_person_arriving` released the garage remote lockouts and the away lock
(`master_bedroom_lock`) on any `SIGNAL_PERSON_ARRIVING` for a person who was really away (`_really_away`, ≥ 15 min
`not_home`). Presence fires that signal with `source: camera_face` whenever any zone camera recognises a face
(`presence.py` `_handle_face_arrival`). Frigate face labels can name the wrong resident: on 10-24 Jaya was labelled
"Oji" while Oji was abroad. Oji was really away, so a face like that passed the gate and could unlock.

## What changed
| Item | What |
|---|---|
| Face gate | `on_person_arriving` reads the payload `source`. For `camera_face` it also requires an independent arrival edge for the SAME person (`_face_arrival_corroborated`). Without one it logs at INFO and returns. The gate covers both the garage and the away-lock releases. `_really_away` is still required. |
| Arrival edge | A live `person.<slug>` `not_home → home` edge recorded by the regime's existing person listener, OR a Bermuda move (`previous_location ≠ location`, method `bermuda`) into an entry area: the HA area of an egress camera or of a configured door-interior neighbour (transit validator). The edge must be ≤ 120 s from the face and not inside the 600 s after lock-regime setup. Restore edges (`old_state` None), `unavailable → home` flaps and `not_home → <zone>` are not arrivals. |
| Shared helper | New `arrival_edges.py`: the v5.107.0 D10.5 rule extracted from `perimeter_alert.py` (`live_arrival_slug`, `edge_in_window`, `bermuda_arrival_into`, `nonface_arrival_source`, `area_slug_of_entity`) plus `door_entry_areas` for the lock regime. `perimeter_alert` now delegates to it. Its behaviour is unchanged: the 153 perimeter FP tests pass on both base and branch. |
| Unchanged | `ble`, `geofence` and source-less arrivals; every P1 / P5 / house-state release; the perimeter alert gates. |

### Review A fix-up (same cycle)
- **MED-1, Bermuda moves last the whole window, on either side of the face.** PersonCoordinator overwrites
  `previous_location` on every tick (`person_coordinator.py:1083`), so before this fix a move was visible for one
  update (~30 s), and a face that came first was never looked at again. Now:
  - The lock regime listens to PersonCoordinator updates. It subscribes at setup, re-resolves on each person event,
    boot recheck and face, follows a reload's new coordinator, and unsubscribes at teardown.
  - Every Bermuda move is stamped in the shared helper (`arrival_edges.record_bermuda_moves`, at most 8 stamps per
    person, `BERMUDA_MOVE_STAMPS_PER_PERSON`, rung 1).
  - A move within 120 s before the face counts even after the live data has moved on.
  - A face with no arrival edge is held. A later Bermuda move by the SAME person re-checks it ONCE, judged at the
    face's time. A held face is dropped after 120 s.
  - **Perimeter D10.5 is unchanged:** it passes no stamps. Perimeter decides at dispatch time and has no re-check
    path, so the stamps would change a time-sensitive alert. Revisit only if the narrow perimeter window is shown to
    cost real de-escalations.
- **MED-2, lock-side boot floor.** The lock uses a boot exclusion of `max(PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S,
  GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S)`, so a perimeter retune to 0 can no longer let a boot-stamped Bermuda restore
  corroborate an unlock. The coupling is commented on both constants.
- **LOW-1, entry areas are the UNION of every door group.** The scope is all egress-camera areas plus every
  configured door-interior neighbour. The face payload carries no camera, so the area can't be narrowed per face.
  Presence knows the camera (`_handle_face_arrival(camera_entity, ...)`), but most faces come from INTERIOR zone
  cameras (family_room, master_hallway), which belong to no door group. Narrowing would need a camera → door-group
  map that does not exist for interior cameras. That work was not cheap, so the scope is documented rather than
  narrowed.
  - **Residual:** a same-person Bermuda hop into any neighbour room counts, still bounded by `_really_away`. It needs
    the person's own phone in the house while GPS reads away for 15 min or more.
- **MED-3 (Bermuda reload / flap):** probed separately, not acted on here.

### Knobs (REUSED, rung 1, `const.py`)
- `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` = 120 s, the corroboration window. If it is 0, a face never releases a lock.
- `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` = 600 s, the post-setup exclusion. On the lock side it is floored at
  `GARAGE_LOCKOUT_BOOT_ARRIVAL_WINDOW_S`.

The lock regime reuses the perimeter's knobs on purpose (operator 2026-11-08: one rule). The window moves both
consumers. The boot exclusion can only make the lock stricter.

### Consequences (accepted by design)
- **Tracker leg.** A live tracker arrival already releases through P1 by itself, and it leaves `_really_away` False.
  So for locks the deciding corroborator is the Bermuda entry-area move: Bermuda places the person in the garage or
  foyer while GPS still reads `not_home`, within 120 s on either side of the face. A face after a tracker arrival is
  a no-op.
- **No egress config.** A house with no egress cameras and no door neighbours has no entry areas. Faces never release
  there. That is the fail-safe direction.
- **Restart.** Within 600 s of setup a face never releases. Real tracker arrivals still release through P1.

## Tests
`quality/tests/test_lock_face_arrival_corroboration.py` (33). It covers:
- face + same-person Bermuda entry move releases;
- face + configured-neighbour area releases;
- face + tracker edge (corroborated, P1-owned release);
- face only, with the person really away 60 min: no release;
- face + another person's BLE or tracker arrival: no release;
- interior hop, no move, no transit validator and a non-Bermuda record: no release;
- window 119/120/121 and boot-exclusion 599/601 literals;
- `_really_away` still required;
- away lock: face only vs face + BLE;
- `ble`/`geofence`/None sources unchanged;
- window 0 and not-set-up never corroborate;
- `door_entry_areas`.

In `test_sc_garage_lockout.py`, `test_camera_face_after_real_absence_releases` became
`..._without_arrival_edge_does_not_release`. Its oracle flipped by design. `test_perimeter_fp_gates.py` gained
`test_egress_gate_tracker_not_home_to_zone_pages` and `test_egress_gate_non_bermuda_record_pages`, which close two
pre-existing coverage gaps; both also pass on the base code.

Mutation drills: 28 sites in the build (13 lock regime, 12 shared helper, 3 perimeter wire-in) plus 21 in the review
fix-up (stamps, listener lifecycle, held-face re-check, boot floor), each RED on neuter. The fix-up added 17 tests (50
in the file).

## Live validation

### Validated 2026-11-10

Read 2026-11-10 ~02:10-02:20 CST, HA running v5.108.1 (manifest), restart 01:04 CST. Read-only. This release (v5.107.1 through v5.107.6) first ran at that restart. Logging caveat: the integration logger is `log_level: WARNING`, so every INFO marker in these criteria is never written to the HA log, and `ha_get_logs` cannot show it. Log absence is therefore NOT evidence for or against these criteria.

Deployed code check: `domain_coordinators/security_lock_regime.py` is present on the HA host, with the face gate at `:850` and the held re-check at `:1099`. Both INFO lines are at `:853` and `:1100`. The lock timelines below come from `ha_get_history` and `ha_get_logs` logbook.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | `held` INFO lines only for faces with no edge; no unlock at those times | NOT-YET-OBSERVABLE | No held or corroborated line can be read (INFO). No face arrival since restart. Lock timeline 18:00 Nov 9 to 02:15 Nov 10: `lock.konnected_f0f5bd523b00_lock` and `lock.ratgdov25i_dbfe2a_lock_remotes` go `unlocked` → `unavailable` (01:02:53) → `unlocked` (01:02:57), a reconnect flap at restart; `lock.master_bedroom_lock` shows `unlocked` at both window ends with no change between. The logbook carries no URA context, so these are not attributed to the regime. |
| 2 | Resident car arrival still unlocks the garage lockouts | NOT-YET-OBSERVABLE | No `not_home → home` arrival since restart. The regime's `last_action` entity was not located by search. |
| 3 | `arriving_signal` release after `camera_face` dispatch has a corroborating edge | NOT-YET-OBSERVABLE | No `arriving_signal` release since restart. |
| 4 | Perimeter D10.5 `face+ble` / `face+person_tracker` still reported | NOT-YET-OBSERVABLE | No perimeter alert since restart. |
| 5 | In-suite only: 10-24 mislabel shape | IN-SUITE ONLY | `test_face_only_person_really_away_no_release`. Cannot be produced live. |

**Verdict 2026-11-10:** 0 PASS, 0 FAIL, 4 NYO, 1 in-suite. **Doc contradiction for the operator:** `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` §1 calls the SC lock regime "NOT deployed", but the deployed tree has `domain_coordinators/security_lock_regime.py`. Whether the lockouts should be engaged overnight was not determined here. The garage remotes show no transition from 18:00 to 02:15 apart from that restart flap (state `unlocked`). The 02:15 to 06:00 part of the window is not read yet.

## Not done (tracked)
- Flipping `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` and setting the `Oji=oji_udezue` face alias, the card's
  `next` step 2. Both live on the FACE-SOURCE-REGISTRY-DISCOVERY-1 branch (`feature/face-source-registry`), which is
  not merged into develop. Do it in that cycle now that this gate exists.
