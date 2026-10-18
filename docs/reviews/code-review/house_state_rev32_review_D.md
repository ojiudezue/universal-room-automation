# Sleep-mask Rev 3.2 build: Review D (adversarial completeness, diff-blind)

**Branch:** `2244661c3` (detached worktree `rev32-review-D`). **Diff base:** `dad3bf6e7...2244661c3` (three-dot; base verified as the plan's stated build base).
**Read first, completely:** `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. the §10 ledger #1-#22), `docs/architecture/SENSOR_FLEET_CLASSES.md`, plan §R3.2 / §R3.1 / §R3. No ledger claim is re-asserted here.

## Invariant in falsifiable form

> With `const.ZONE_OCCUPANCY_PER_ENTITY_ENABLED = True`, for every room r listed in a zone tracker's `room_names`, after any substrate callback, boot-settle release (with reconcile), or lifecycle refresh returns: `tracker_room(r) == any(on(e) for e in E(r))`, except while a fan-interference hold extends True. No reachable sequence (on, off, unavailable, unknown, removed, renamed, room deleted, refresh failure) leaves a tracker room True after all of E(r) are off, or False while some e in E(r) is on.
> With the switch False, every dispatch, tracker state, inference result and NM is identical to `dad3bf6e7`.

Falsified by: a legal config plus an event sequence that leaves some tracker's room disagreeing with E(r), or a switch-off path that differs from `dad3bf6e7`.

## Findings

### D-M1, MEDIUM: a room listed in two zones is left permanently stuck on in the second zone

The boot reconcile writes it and no live edge ever clears it. Bug classes: #53 (one missed site, routing scope) and suppression without discharge.

**Mechanism:**
- Live edges route through `tracker_for_room(room)`, which returns ONE tracker: the first zone that lists the room (`presence.py:3641`, `:1937-1961`; `_room_to_zone` is first-writer-wins at `:3460-3471`).
- The new `_reconcile_trackers_to_substrate` walks every tracker's `room_names` (`presence.py:2361-2370`). It therefore writes the substrate's True slots into the second zone's tracker as well.
- No later off-edge ever reaches that second tracker. The room stays occupied there until the next restart, and the next restart re-sticks it if the sensor is on at boot.

**Repro.** I ran it with `SubstrateWorld` on the real substrate, tracker and `_run_inference`, in a scratch test that I have since deleted:
- Setup: zones `{"Z1": ["Master Bedroom"], "Z2": ["Master Bedroom"]}`, a ZX on and a ZV off at boot, house HOME_DAY, census 0, no trackers. Then release, reconcile, and the ZX goes off.
- **Switch ON:** Z1 raw=False, **Z2 raw=True**, state `home_day` (nobody-home is blocked by an empty house).
- **Switch OFF:** Z1=False, Z2=False, state `away` / `nobody_home`.

**Reachability:**
- Two zones listing one room is legal through a legacy `ENTRY_TYPE_ZONE` entry plus a ZM zone. `_discover_zones` builds both kinds of tracker (`presence.py:3375-3460`), and `_sync_room_zone_to_zm` only dedups the ZM dict.
- It is also reachable through the ZM add-zone flow (`config_flow.py:~2098-2133`), which writes the room into the new zone without removing it from the old one, until the room's next setup-time `_sync_room_zone_to_zm` dedup.
- The code itself calls this "pathological config, first-writer-wins". Before this cycle the second zone simply never saw the room, which is a quiet loss. Now it is a stuck-on with no discharge.

**Consequences:**
- nobody-home and β are blocked for the life of the process.
- The −0.4 consensus term is pinned (the HVAC-CONSENSUS-GATE-PIN-1 surface).
- A Z2 AWAY override is auto-cleared.
- With trusted trackers and Frigate dark, D4d pages it after 7200 s. On Wigton S0 nothing pages.

**Fix (one guard):** in `_reconcile_trackers_to_substrate`, skip a room unless `self.tracker_for_room(room_name) is tracker`. That gives the same routing rule as the live path. Add an anchored test: two zones, one room, on at boot then off, and the second zone reads False. This is cheap and closes a stuck path this cycle introduced, so it is **must-fix**.

### D-M2, MEDIUM: a runtime room rename drops a sleeper at night with the switch ON, while `dad3bf6e7` held it

The plan's "D4c.2 is a strict improvement" claim (§R3.1.8 R1-F11, R3.1.9) is wrong relative to the reviewed branch. Bug class: coincidental equality masking a concept split. The D-H1 live limb was also silently covering ZONE-ROOM-NAME-DRIFT-1 at night.

**Mechanism:**
- After an options rename, the tracker keeps the old name (R1-F11).
- The refresh's D4c.2 walk sends False edges for the old name (`occupancy_substrate.py:600`).
- The new name's edges find no tracker (`presence.py:3641-3648`).
- On `dad3bf6e7` the D-H1 limb read live sensor state through `tracker._entity_to_room`, which was registered at discovery under the OLD name, so the sleeper stayed held. With the switch ON that limb is gated off (`presence.py:4116`).

**Repro (run, then deleted):**
- Setup: Master Suite = [Master Bedroom], ZX on, ZV off, house SLEEP at 02:00, census 0. Release, then set the entry's `room_name` to "Primary Bedroom" and refresh.
- **ON:** tracker raw=False, then `sleep -> away`, `veto=nobody_home`.
- **OFF:** raw=True, `sleep`.

**Scope:**
- This is a regression only against `dad3bf6e7`. Deployed `develop` has no D1, so its night nobody-home already fires.
- The window lasts until presence re-discovers (restart).
- By day the two branches are equivalent, except that OFF keeps a stuck-True old name, which is worse in the other direction.

**Action:**
- Correct the plan and README claim ("strict improvement by day; at night it removes the limb's accidental cover").
- Raise ZONE-ROOM-NAME-DRIFT-1 on the board with this night consequence.
- Not ship-blocking, provided the operator acks it with PICK R3-1.

### D-L1, LOW: D4d is also inert on THIS house when every resident is LOST, not only on Wigton S0

`held` requires `tracked_count > 0` (`presence.py:4253`), and LOST residents are excluded from the trusted denominator (`presence.py:6318-6343`).

- With all phones LOST and Frigate dark, α is starved, β is blocked by the indoor guard, and nobody-home is blocked while a multi-sensor phantom (Jaya LD2410 with the fan on) reads on. The house is held with no page.
- The pre-D4 wipe released it by accident.
- This is the same gap class as WIGTON-STUCK-ZX-NO-PAGE-1. Extend that card's text to cover it, or key D4d on β's LOST-admitted denominator later.
- No code change in this cycle.

### D-L2, LOW: the census zone limb lets the holding sensor manufacture census ≥ 1, which silences D4d

`_any_zone_occupied_snapshot` (`camera_census.py:2369-2406`, call `:2091`) corroborates a Frigate/binary divergence when any zone is occupied. The higher count is then kept, and it feeds `unidentified_count = camera_total - identified` (`:2463`).

**Chain:** a camera ghost divergence plus a phantom Tier-1 hold gives census 1. That blocks α (unidentified ≠ 0) and nobody-home, and D4d's `census == 0` conjunct is False. So the hold is never paged.

- This is not an arithmetic double count. It is one piece of evidence counted twice: the sensor is both the holder and the corroborator.
- Plan row 7 accepts the direction by name. R3.1.7's sentence "census 0 means no unidentified body" omits this coupling, and only that sentence needs fixing.
- No code change.

### D-L3, LOW: a cross-room duplicate entity loses its night cover in the second room

This only matters when the second room is in a different zone, and the config already triggers a WARN.

- The substrate keeps the first claim (`occupancy_substrate.py:252-268`). On `dad3bf6e7` the D-H1 limb covered the second room's zone through `register_entity`.
- The same regression shape as D-M2, but on a config that is already warned. Accept and note it.

## Probes cleared (holds because)

| Probe | Verdict | Evidence |
|---|---|---|
| Dead `_handle_occupancy_change` writer | PASS | It has no subscriber. The only references are its def (`presence.py:5192`) and a comment (`:5734`). The DEAD docstring was added. |
| Every tracker writer | PASS | `update_room_occupancy` is the sole writer of `_room_provenance`. Its callers are reconcile `:2368` (see D-M1), seed `:3606/:3615`, live `:3649` and the dead `:5231`. No production path writes kind=None True, so the `tier1` sentinel cannot survive D4b's pop. |
| Every substrate writer | PASS | `_raw_state` is written by setup seed/prune, the refresh scratch seed + swap + prune, and the handler. The refresh body is await-free (lock is the only await). Callbacks run inside `async_set` (`async_track_state_change_event` `run_immediately`), so sibling `hass.states` reads are coherent. |
| unavailable to on, no edge | PASS | The handler recomputes the OR from the payload plus siblings. During settle, raw is updated and replayed, and reconcile pops True→False (`presence.py:2389-2402`). On the reload path (gate born released, `:2609`), substrate setup, release and `_discover_room_sensors` run in that order with no gap. |
| Entity rename via the registry | PASS (strict improvement) | HA `async_remove(force_remove=True)` (`helpers/entity.py:1569`) fires `new_state: None`. D4c.1 counts it off and releases the kind (on `dad3bf6e7` it stuck True). The new id is untracked at both tiers (URA has no rename write-through; grep shows only camera_census / transit_validator listen to registry updates). That is pre-existing. A disabled entity takes the same path. |
| Same entity under two kinds | PASS | Precedence keeps one kind (`occupancy_substrate.py:216-243`). Seed and live share `_kind_on_now` over that map. |
| Same entity in two rooms | PASS at zone-truth level | E(r) is defined after dedupe. Deleting the first claimant reclassifies to the second, and the refresh re-seeds and emits the edge. See D-L3 for night cover. |
| Room in two zones | **LEAK** | D-M1. |
| Outdoor zone | PASS (accepted) | It feeds `any_zone_occupied` and so blocks nobody-home, not β (`presence.py:6392-6402`). D4d pages Patio while Frigate is dark, as R3.1.7 accepts. |
| Capability overrides | PASS | The substrate classifies by CONF list only (`_KIND_TO_CONF`) and never reads `CONF_SENSOR_CAPABILITIES`. No override kind means "ignore". Zone-tier ignorance of room-tier exclusions is PICK R3-2 (STEP-EXCLUDE-4). |
| Stuck-on empty house, α live | PASS | α reads no zone term (ledger #12). INV-NO-EMPTY-HOUSE-HOLD-WHEN-ALPHA-LIVE holds. |
| Stuck-on, cameras dark | PASS with gaps | D4d `held` and the per-episode latch reset on non-held ticks (`:4264-4267`), and the per-day latch is in `fire_stuck_signal`. Gaps: D-L1 (all LOST), D-L2 (census corroboration), Wigton S0 (carded). |
| Daytime nobody-home / β newly blocked | PASS (intended) | Only while a registered sensor reads on. Measured cost in D0 §R3.5.2: 0 delayed departures with α live. |
| WAKING gate after the forcing-line removal | PASS | `_zone_night_rooms` with the switch ON mirrors `_derived_mode` (BLE, then `_has_sensors`, then `_room_occupied` incl. the hold, then camera; `:4086-4131` vs `:756-782`). So the SLEEP holder set equals the `raw_occupied` set and `any(raw_occupied)` carries it. The manual OCCUPIED override no longer forces the gate (R3-F1, intended; the backstop discharges it). |
| Removed room (`async_remove_entry`) | PASS | Gated "removed" dispatch, then refresh, then the snapshot-room walk (`occupancy_substrate.py:595-613`). Step 6 has already pruned, so `cur` = False. |
| Refresh failure | PASS | The scratch seed swaps only after the subscribe succeeds (`:526-566`). Retry is one-shot. |
| Kill switch False byte-identity | PASS by inspection | Every new site is gated. The seed rewrite through `_kind_on_now` gives the same OR as the old loop: the state None / unavailable / unknown cases are all off, and the cross-room filter comes from the desired map. |

## Invariant checklist

| Invariant | Result |
|---|---|
| INV-ZONE-ROOM-TRUTH | **LEAK** (D-M1: room in two zones). Otherwise PASS. |
| INV-NO-STUCK-THROUGH-REMOVAL | PASS (entity delete, CONF removal, room delete). D-M1 is a stuck path through boot, not through removal. |
| INV-SLEEP-NOT-EMPTY | PASS on the tracker definition. Real-world gap D-M2 (rename) is outside the tracker's domain. |
| INV-NIGHT-RAW-EQUALS-RAW | PASS |
| INV-SLEEP-HOLD-BOUNDED (b) | PASS |
| INV-BYTE-ID-SINGLE | PASS |
| INV-KILL-BYTE-ID | PASS |
| INV-NO-EMPTY-HOUSE-HOLD-WHEN-ALPHA-LIVE | PASS. Coverage notes D-L1 and D-L2. |

## Bug-class tally

| Class | Findings |
|---|---|
| #53 one missed site / routing scope | D-M1 |
| Suppression without discharge | D-M1 |
| #63 coincidental equality masking a split | D-M2, D-L3 |
| Coverage / observability gap | D-L1, D-L2 |

## Verdict: **FIX-REQUIRED**

**Must-fix:**
1. **D-M1.** Route the boot reconcile through the owner tracker (`tracker_for_room(room) is tracker`), with an anchored two-zone test.

**Should-fix (doc only, same commit):**
- D-M2: correct the "strict improvement" claim and add the night consequence to ZONE-ROOM-NAME-DRIFT-1.
- D-L1: extend WIGTON-STUCK-ZX-NO-PAGE-1 to the all-LOST shape.
- D-L2: amend the R3.1.7 census sentence.

The tree was left clean. The scratch probes were deleted and `git status` is empty apart from this file.
