# Review A+B: EXTERIOR-SEAM-FILE-LOADER-1 (feature/exterior-seam-loader @ 091f35da)

Base: merge-base(develop, 091f35da) = 6d49f879 (verified). Targeted tests: 41 passed.

## A: correctness
- **Allowlist source is correct.** `_seam_known_cameras` (exterior_track_linker.py:445) uses the installed linker allowlist, or else the PerimeterAlertManager's staged `_perimeter_allowlist` (perimeter_alert.py:775). Keys come from `_camera_key_for_sensor` (perimeter_alert.py:2172), normalized again here. PAM sets up before the linker (__init__.py:3503 vs 3563), so RULE 1 is active at boot.
- **Live file prediction: VALIDATES**, verdict `ok (1 warning(s): ... ['sonoffwindow'] ...)`. The live config has 11 perimeter cameras and 5 egress cameras. That matches the live `allowlist_camera_count: 16`. The 16 inferred keys were run through `validate_seam_spec` against the live file: errors=[], 1 RULE-2 warning (sonoffwindow is not ringed). Caveat: the key names were inferred from the entity registry (the 16 = 16 count agrees), and the diagnostic does not list key names. Confirm live after deploy.
- Derived egress-adjacent set from the live file = (armcrest, front_side_ptz, g5_bullet, rear_ptz, utilities_ptz). The skips make it wider than the obvious neighbours. That is expected from the derivation, but it changes `approach` classification compared with the const. Note it in the README.
- The fallback is never empty. Absent file = const. Rejected file = previous graph kept. File with no exterior egress keeps the const egress set (:541).
- `_classify` reads `self._egress_adjacent` (:899). No other consumer reads the const graph or egress set outside the linker (grep). `neighbors()` at :1093 reads the installed `_adjacency`.

## B: lifecycle
- The blocking read goes through the executor (:466). The loader never raises.
- Reload race: the graph is swapped as one dict assignment after the await, on the event loop. Concurrent presses each install a complete result, so no partial state. Open tracks keep their past links. That is harmless.
- Restart / config-entry re-setup: `async_setup` reloads the file every time. Nothing is persisted.
- Button: added to the CM-entry list (button.py:52) next to SendTestPerimeterAlertButton. It uses the same security_coordinator device, whose CM-entry parent is _devices.py:143. Registration happens. The entity_id is pinned to `button.ura_reload_exterior_seams`.
- Wire-in: `async_load_seam_file` is called from async_setup (:334) and the button. `seam_status` is called from sensor.py:4512. `_install_const_seams` and `_read_seam_file` are called internally. All have production callers.

## Findings
| SEV | file:line | Finding | Class |
|---|---|---|---|
| LOW | exterior_track_linker.py:300-334 | The Frigate consumer is registered before `await async_load_seam_file()`. Events that arrive during the executor read link on the const graph. The comment says "before the first event can link", which is false. Fix: load before `register_frigate_consumer`, or correct the comment. | ordering |
| LOW | exterior_track_linker.py:507 | When a file is rejected, `seam_file_sha256` shows the rejected file's hash while `seam_source` still names the previous graph. This is arguably intended (it makes an edit visible), but it is undocumented. | display semantics |
| LOW | test_exterior_seam_loader.py:196-225 | The button test constructs the entity but does not assert that it is in the CM `async_setup_entry` list. A removed line would stay GREEN. | #62-adjacent |

No CRITICAL/HIGH/MEDIUM.

**Verdict: SHIP.** The LOWs are optional in-cycle fixes.
