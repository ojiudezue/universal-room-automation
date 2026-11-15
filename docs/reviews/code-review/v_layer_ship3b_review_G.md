# Layer ship 3b: review G (goal fidelity)

Branch `feature/layer-ship3b` (base d0a38ad9, 3 commits). Spec: c86b6c74 `PLANNING_person_awareness_layer_ship3.md` §6.
Read: ura-arc skill, charter goals + drift #15, arc map, cards DEAD-CAMERA-TWIN-COVERAGE-1, DUAL-LENS-PACKAGE-CHANNEL-MEMBERSHIP-1,
NVR-WITNESS-CONSOLIDATION-1 (operator_2026_11_14 fields). No pytest run (read-only).

## Findings

| Sev | Finding | Evidence |
|---|---|---|
| MEDIUM | **The empty-house anchor block is NOT driven by "every NVR lost it".** The operator's approved design ("Smart. Do it") names three consumers of camera-dead: the camera-down page, the hold-released alarm, and the empty-house anchor block. 3b delivers the first two through `physical_camera_dead` (readers: pages and diagnostics only, `camera_twin_health.py:24`, `:1008`). The anchor still reads per-device holds, so a dead Frigate whose Protect twin is live can still block the anchor for up to the cap. The plan says this (§6.0 "drift #15 stays open for holds and the anchor") and ties it to option A / card B. But the Q11 quote on the card ("pages + house-level camera health; coverage parked") does not mention the anchor. So the operator may not know the anchor part of the "Smart. Do it" design is deferred. | spec §6.0, §6.5; card `operator_2026_11_14_q11` |
| LOW | Garage Doorbell Lite (room S2) and garage_a / garage_b (owner group pages) page as room-input health. That fits "door coverage stays on cards", because the page comes from a room reading the device, not from door-camera health. The plan already flags it for the checkpoint. Confirm it with the operator, since a doorbell page will look like door coverage. | spec §6.0 |
| LOW / none | U one-member groups are paged only while `CAMERA_STREAM_UNWATCHED_STAMPS_ENABLED` is on. This matches the spec kill-switch matrix (§6.7 row True/False/True), and the knob ships True (`const.py:6094`). No live U one-member group exists. The product is unchanged. | `camera_twin_health.py:510`, `:600` |
| LOW / none | Takeover episode end: the episode ends only after a member is LIVE for one grace (`_group_alive`, `camera_twin_health.py:686-695`). The spec said it ends after the gate has been False for one grace. The builder's version is stricter: a new owner's immature stamps cannot close an adopted episode and send a false "visible again" LOW. This also matches the LOW text. The pages delivered are the same. | `:686-695` |

## Constraints

| Constraint | Result |
|---|---|
| Registry, not names | PASS. Devices come from registry `device_id` and pairing from the registry `platform` check. The only string tests are `startswith("camera.")` domain checks (`:306`, `:519`, `:990`). The dual-lens `_3` suffix was deliberately refused and carded. |
| BLE trust unchanged | PASS. The diff has no BLE or Bermuda edits. The hold is camera-only. |
| Door / perimeter out of scope | PASS. The 9 readerless pairs are left to PERIMETER-RING-CAMERAS-STREAM-WATCH-1 and W2. The garage pages are the LOW above. |
| No shadow mode | PASS. All knobs ship True (`const.py:6089-6107`). |
| 6.0.0 gate | PASS. No identity actuation is added. |

## Operator decisions

| Operator said | Delivered |
|---|---|
| "if even one nvr has the cam it doesn't count as dead" | Yes for pages: the group gate needs every member LOST (§6.5). |
| Option A, card B | Yes. No reader substitutes a twin. DEAD-CAMERA-TWIN-COVERAGE-1 is carded with its revival trigger. |
| Q12 symmetric with Frigate | Yes. Same constants and code. The two named differences are carded or pre-existing. |
| "...and the empty-house anchor block" | Deferred via option A (MEDIUM above). |

## Verdict

**SHIP (goal fidelity)**, with one checkpoint item: tell the operator in plain words that the anchor block still uses per-device holds until card B (DEAD-CAMERA-TWIN-COVERAGE-1), and get a yes, or a yes plus a card for it. Confirm the garage doorbell paging at the same checkpoint.
