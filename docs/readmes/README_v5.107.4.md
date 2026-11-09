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

### Knobs (REUSED, rung 1, `const.py`)
- `PERIMETER_EGRESS_FACE_NONFACE_WINDOW_S` = 120 s, the corroboration window. If it is 0, a face never releases a lock.
- `PERIMETER_EGRESS_ARRIVAL_BOOT_EXCLUDE_S` = 600 s, the post-setup exclusion.

The lock regime reuses the perimeter's knobs on purpose (operator 2026-11-08: one rule). Changing either one moves both
consumers.

### Consequences (accepted by design)
- **Tracker leg.** A live tracker arrival already releases through P1 by itself, and it leaves `_really_away` False.
  So for locks the deciding corroborator is the Bermuda entry-area move: Bermuda places the person in the garage or
  foyer while GPS still reads `not_home`. A face after a tracker arrival is a no-op.
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

Mutation drills: 28 sites (13 lock regime, 12 shared helper, 3 perimeter wire-in), each RED on neuter.

## Live acceptance criteria
- **Live:** after restart, `grep "Lock regime: camera_face arrival for"` in the HA log shows INFO lines only for faces
  with no arrival edge. There is no unlock in the `lock.konnected_f0f5bd523b00_lock` /
  `lock.ratgdov25i_dbfe2a_lock_remotes` / `lock.master_bedroom_lock` history at those timestamps.
- **Live:** the next resident arrival by car (GPS `not_home → home`) still unlocks the garage lockouts. The lock
  regime's `last_action` reads `release`, trigger `person:person.<x>` or `arriving_signal`.
- **Live (discriminator):** an `arriving_signal` release that follows a `camera_face` dispatch must have a
  same-person Bermuda move into Garage / an egress or door-neighbour area, or a `person.*` `not_home → home`, within
  120 s before it (recorder). Before this fix, a face-only release had neither.
- **Live:** perimeter D10.5 decisions on `gate_decisions_by_camera` still report `face+ble` / `face+person_tracker` as
  before.
- **In-suite only:** the 10-24 mislabel shape (face names an away resident, no edge) cannot be produced on demand
  live; `test_face_only_person_really_away_no_release` pins it.

## Not done (tracked)
- Flipping `FACE_SOURCE_PRESENCE_ARRIVAL_DISAMBIGUATED` and setting the `Oji=oji_udezue` face alias, the card's
  `next` step 2. Both live on the FACE-SOURCE-REGISTRY-DISCOVERY-1 branch (`feature/face-source-registry`), which is
  not merged into develop. Do it in that cycle now that this gate exists.
