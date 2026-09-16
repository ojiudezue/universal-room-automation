# AUDIT — HVAC Conditioning Demand: Supersession + Prior-Art Reuse

**Companion to:** `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`
**Scope:** SOURCE sweep (HVAC + presence/dwell/hold code), end-to-end. Read-only.
**Card:** `HVAC-ZONE-CONDITIONING-DEMAND-1` · Tier 2-DB · pre-build
**Mandate:** proposal §10a — "absolutely no new machinery where we don't need
it… prior art, context-wide audits, so we don't rework things we've already done."

Files read end-to-end or in the relevant span:

- `custom_components/universal_room_automation/domain_coordinators/hvac.py`
  (init ~L160-540; per-zone preset loop ~L1750-2000; fan/pre-arrival wiring)
- `custom_components/universal_room_automation/domain_coordinators/hvac_zones.py` (entire)
- `custom_components/universal_room_automation/domain_coordinators/hvac_const.py`
  (grace / dwell / fan-hold constants)
- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py`
  (searched for occupancy consumption)
- `custom_components/universal_room_automation/domain_coordinators/presence.py`
  L680-733 (`provenance_for`, fan-interference hold), L2055-2160
  (`check_zone_occupancy_confidence`)
- `custom_components/universal_room_automation/domain_coordinators/occupancy_substrate.py`
  L732-770 (`is_kind_active`, `get_room_kinds`)
- `custom_components/universal_room_automation/coordinator.py`
  L534-540 (occupancy_timeout wiring), L2900-2940 (grace_hold source), L3350-3460
  (mmWave-sole suppression + fan-phantom gate), L3560-3640 (grace_hold consumer)
- `custom_components/universal_room_automation/const.py` L960-975, L1150-1200
  (`CONF_FAN_VACANCY_HOLD`, `ROOM_TYPE_TIMEOUTS`, room-type tables)

---

## (i) Supersession sweep — three-bucket triage

Rule: "dead ≠ delete." Every candidate below is a *hypothesis* — verify with a
consumer grep before removing anything. Buckets: **DELETE** (dead AND useless AND
ideally a footgun), **KEEP + WIRE** (dead but *should* be consumed — a gap, not
debt), **KEEP + DOCUMENT** (dead today, plausibly-useful design axis).

| # | Item | File:line | Bucket (proposed) | Superseded-by | Reason / notes |
|---|---|---|---|---|---|
| S1 | `_zone_entry_dwell` field on HVACCoordinator + preset-loop check "session_start < dwell → continue" | `hvac.py:466` (init), `hvac.py:1986-1996` (consumer); config in `hvac_const.py:377-378` (`CONF_HVAC_ZONE_ENTRY_DWELL`, `DEFAULT_ZONE_ENTRY_DWELL_MINUTES=3`); UI in `config_flow.py:5870, 6421-6424`; entity in `number.py:417-494` (`ZoneEntryDwellNumber`) | **KEEP + DOCUMENT** (do NOT delete on ship) | Per-room dwell-to-enter on the new HVAC-occupancy signal | Proposal A′-2 says *retire* to avoid dwell-stacking with the per-room dwell. But the entity is operator-facing and the option is live-editable (default **3 min**, not 5 as the proposal states — verify §8 of the proposal against `hvac_const.py:377`). Wire-time treatment: set default to 0 (disables the loop check) once per-room dwell is live, deprecate the number entity label to "legacy — see per-room HVAC hold," and leave the field for one release before deletion. **Footgun check:** if left non-zero AND per-room dwell also non-zero, they *add*, exactly the flap the proposal wants gone — so the ship must ship the default-to-0 in the same cycle as the per-room dwell, not later. |
| S2 | `ZoneState.current_session_start` field + reset logic | `hvac_zones.py:108-109` (declaration), `hvac_zones.py:562-566` (reset on vacancy) | **KEEP + WIRE** (or DELETE with S1) | Same as S1 | Only consumer today is the S1 dwell check (`hvac.py:1991`). Follows S1's fate — no independent value. |
| S3 | HVAC's read of `RoomCondition.occupied` (the lighting-held signal) as the zone occupancy input | `hvac_zones.py:48` (field), `hvac_zones.py:546` (populate from `coordinator.data["occupied"]`), `hvac_zones.py:148` (`any_room_occupied = any(r.occupied ...)`) | **KEEP + WIRE** (do NOT delete) | New HVAC-occupancy signal per room feeds `RoomCondition` (or a sibling field) | This is the SIGNAL SWAP, not a deletion. `any_room_occupied` has **12+ HVAC-path consumers** — `hvac.py:1787,1808,1990,3462,3627`, `hvac_override.py:2282,2433,2267ff`, `hvac_predict.py:578,1368`, `hvac_zones.py:584,555`, `hvac_egress.py:483`, `hvac_fans.py:755,986`, `presence.py:2152`. Deleting `RoomCondition.occupied` is not viable; **repointing its population source** (line 546) to the new HVAC-occupancy view is the whole ripple surface. That aggregation is the single mutation point A′ hinges on. |
| S4 | The "redundant second hold" (proposal §10a): zone-level `vacancy_grace` (10-15 min) stacked on top of the room-level `occupancy_timeout` (300-900s) that produced `RoomCondition.occupied` in the first place | Room hold: `coordinator.py:534-536` (`_occupancy_timeout`), consumed at `coordinator.py:3595, 3613-3624`. Zone hold: `hvac.py:1758-1791` (`grace_minutes` gate against `zone.last_occupied_time`); constants `hvac_const.py:374-375` (`DEFAULT_VACANCY_GRACE_MINUTES=15` — proposal cites 10; verify) | **KEEP + DOCUMENT** — do NOT delete | The new per-room HVAC hold (fan-hold pattern) subsumes ONE of the two, not both | A′-3 explicitly says *keep* `vacancy_grace` as the zone-level exit timer and let the per-room HVAC hold be *short* (bridge mmWave dropout, not a second retreat timer). So the "second hold" is not fully removable; what CAN come off is the *conflation* — today the room's lighting hold determines when HVAC sees the room clear, then HVAC waits ANOTHER 10-15 min. Under A the room's HVAC hold is separately tuned (short by default), and only ONE long timer (`vacancy_grace`) sits above it. Documentation change more than a code delete. |
| S5 | mmWave-sole suppression latch (creation direction) | `coordinator.py:3356-3363` (`_mmwave_demoted_latch` clears `any_sensor_active` when mmwave-sole) | **KEEP + DOCUMENT** | Kind-aware HVAC input reads mmWave-present *directly*, not through the fused `any_sensor_active` | This gate protects the LIGHTING path from mmwave phantom firing. It stays load-bearing there. The proposal's Stage B (mmWave stillness input) reads mmwave from `occupancy_substrate.is_kind_active(room,"mmwave")` (proposal §6), which BYPASSES this gate by design — so the gate neither helps nor hurts the HVAC path. No code change; document that the HVAC-occupancy input is intentionally out-of-band of the mmwave-sole demotion. |
| S6 | Fan-transition creation-suppression gate | `coordinator.py:3370-3521` (`FAN_TRANSITION_SUSPECT_WINDOW_S` gate; clears `any_sensor_active` for CREATION only) | **KEEP** (unchanged) | n/a | Same argument as S5: HVAC-occupancy is a *separate* view. This gate protects the room's occupancy from a fan-flip phantom for the LIGHTING path; HVAC path reads its own signal. No delete; may want a companion note in the gate's block comment. |
| S7 | `presence.py:697-705` fan-interference hold extension on the fused OR view | `presence.py:697-705` (`_room_occupied` derived view extends via `_fan_interference_hold_until`) | **KEEP** | n/a — HVAC-occupancy view may want a *different* policy | Load-bearing for `check_zone_occupancy_confidence` (see proposal §9). If HVAC-occupancy reads the same helper the hold rides free (fine); if HVAC reads `is_kind_active` directly it bypasses the extension. Neither is wrong; document which one the new signal takes and why. |
| S8 | Any dead HVAC-occupancy-adjacent code from prior cycles (proposal §10a mentions "S14 was already removed; verify no siblings linger") | Sweep target — no siblings found in this pass under `hvac_zones.py` or `hvac.py`. `iter_canonical_hvac_zones` at `hvac_zones.py:788` is a live helper (Bug Class #36 prevention), not a supersession candidate. | n/a | n/a | Recorded as **no finding**; re-verify at build time. |

**Zero DELETE items is a legitimate outcome** (per project doctrine — a "clean" supersession
sweep). The changes are population-source swaps (S3) + default flips (S1) + block-comment
updates (S4/S5/S6). The proposal's framing of "what comes OFF" is largely *behavior-neutral
retirement of a defaulted-off knob* (S1), not a code delete — set S1 default to 0 the same
cycle you ship per-room dwell or the two holds stack and defeat fast-in.

**One footgun called out:** shipping the per-room HVAC dwell without also defaulting
`CONF_HVAC_ZONE_ENTRY_DWELL` to 0 leaves both stacked. This is exactly the class of
"code stacked on top of code that is now unnecessary" the operator flagged in §10a.

---

## (ii) Prior-art reuse — REUSE-or-BUILD verdicts

For every mechanism the proposal implies, a verdict with file:line. **Trust nothing —
these were re-greped in this session.**

| Mechanism (proposal ref) | Verdict | Existing prior art (file:line) | Notes |
|---|---|---|---|
| Kind-aware presence read (mmWave vs PIR vs occupancy) — §5 Stage A input, §6 modality scan | **REUSE** | `occupancy_substrate.py:732` `is_kind_active(room, kind) -> bool`; `occupancy_substrate.py:747` `get_room_kinds(room)`; module registered at `hass.data[DOMAIN]["occupancy_substrate"]` (see `presence.py:2592`). Live consumers already: `music_following.py:528-545`, `binary_sensor.py:669`, `presence.py:3270`. | Zero new wiring for HVAC to consume. Bypasses mmWave-demotion latch (S5) by design — HVAC gets the *raw kind* view. |
| Zone-boundary per-kind provenance — §5, §A′ | **REUSE** | `presence.py:707` `provenance_for(room)` — projected dict of TIER1_KINDS (motion/mmwave/occupancy), fan-interference-hold aware (§S7). | Already feeds `OccupiedBinarySensor` D5 attrs. Suitable for HVAC's per-room HVAC-occupancy computation if the fan-hold *inclusion* is desired; use `is_kind_active` directly for a fan-hold-*excluded* view. Pick one deliberately and document in the plan. |
| Per-room, per-consumer secondary hold pattern — §5 Stage A "the fan-hold pattern" | **REUSE** | `const.py:966` `CONF_FAN_VACANCY_HOLD` / `const.py:1153` `DEFAULT_FAN_VACANCY_HOLD=300`; consumer `automation.py:2164-2173`; parallel constant + consumer inside HVAC's own fan machinery at `hvac_const.py:821` and `hvac_fans.py:1280-1327`. | Two definitions of `DEFAULT_FAN_VACANCY_HOLD` (300s) exist — the root `const.py:1153` and the HVAC-local `hvac_const.py:821`. Adding a `CONF_HVAC_VACANCY_HOLD` per room should follow the ROOT-`const.py` shape and be read by HVAC via the same import ladder to avoid a third copy (Bug Class #33 sibling). |
| Zone occupancy confidence — §9 "extend, don't reinvent" | **REUSE + EXTEND** | `presence.py:2057` `check_zone_occupancy_confidence(zone) -> (confirmed, possible)`. Reads `_last_motion_time`, `person_coord.get_persons_in_zone`, camera person, multi-room count. Live consumer `hvac.py:1826`. | Extension surface if the D6 stuck-signal branch should be evaluated on the NEW HVAC-occupancy signal instead of the old `any_room_occupied`. Not necessarily needed — check if the D6 stuck-signal semantics still hold under the new input, or extend Source-4 to count HVAC-occupied rooms rather than lighting-occupied. |
| Sensor-unavailability fail-open (`grace_hold`) — §10a mandate "must be preserved" | **REUSE (untouched)** | `coordinator.py:2925-2938` (grace_hold ARM), `coordinator.py:3581-3585` (grace_hold consumption emits `STATE_OCCUPANCY_SOURCE = "grace_hold"`, holds prior `_last_occupied_state`). | The new HVAC-occupancy view MUST inherit grace_hold semantics or *any_room_occupied* will drop on sensor blip. Easiest correct path: the new signal is derived from the SAME room-level `data[STATE_OCCUPIED]` (grace-held) plus a kind-aware second filter — never from raw entity states. Do not open a new grace path. |
| Pre-arrival machinery (geofence / BLE / camera_face → person→zone) — §5 Stage C | **REUSE + EXTEND** | `hvac.py:469-471` `_pre_arrival_zones` / `_pre_arrival_persons` / `_pre_arrival_start`; `hvac.py:509-513` `_pre_arrival_enabled`, `_pre_arrival_sources = ["geofence","ble","camera_face"]`; `hvac.py:531-535` `_pre_arrival_triggers_today`. Signal-driven, not tick-driven. | Stage C's "guest-as-zone-person" plugs into `_pre_arrival_persons`; the exemption already exists at `hvac.py:1993` (`zone_id not in self._pre_arrival_zones`). |
| Fast sub-loop pattern (60 s HVAC fast-in) — §5 Stage D | **REUSE (pattern)** | `energy_const.py:996` `SOLAR_FOLLOW_TICK_S: Final[int] = 60`; `energy.py:1369-1385` `_register_solar_follow_timer()` → `async_track_time_interval(_solar_follow._tick, timedelta(seconds=60))`. Independent from the coordinator's main 5-min tick. | Copy the *pattern*, not the code — Stage D's fast-in tick is a **new** `async_track_time_interval` registered from HVAC init, evaluating a slim "hot-and-occupied" check. New constant `HVAC_FAST_TICK_S = 60` in `hvac_const.py`. New teardown wiring in HVAC's shutdown path (mirror `_solar_follow_timer_unsub`). Two-cadence-per-coordinator is proven; three won't be a Herd if independently jittered. |
| Defaults-by-type table (proposal Stage A "b — ROOM_TYPE_HVAC_HOLD") | **REUSE (pattern) + BUILD (new table)** | `const.py:1171-1181` `ROOM_TYPE_TIMEOUTS`. Precedent pattern; every read uses `.get(type, DEFAULT)` (`coordinator.py:695`, `config_flow.py:1381`, `presence_fan_recheck.py:1102`). New-value safety (§Stage A c "hallway") verified by this idiom. | Add `ROOM_TYPE_HVAC_HOLD` mirroring the shape. Cost is one const dict + a `.get()` at the HVAC-signal producer. |
| `hallway` value on the `room_type` enum — Stage A(c) | **BUILD (safe additive)** | Enum values live in `const.py:421-429` (`ROOM_TYPE_*` constants); selector in `config_flow.py:1387`. | Additive; all consumers `.get(type, DEFAULT)` (no KeyError risk). Migration is operator-driven reclassification of the 6 hallways. |
| `CONF_HVAC_VACANCY_HOLD` per room (Stage A "a — expose the entity") | **BUILD** | No equivalent per-room HVAC hold field found. `CONF_FAN_VACANCY_HOLD` is the shape template. | New per-room CONF; add to room config flow (mirror `CONF_FAN_VACANCY_HOLD` placement); read at the population site (`hvac_zones.py:546` area). |
| Per-room HVAC-occupancy sensor entity — Stage A "a — must be observable" | **BUILD** | No existing per-room HVAC-occupancy entity. `OccupiedBinarySensor` (lighting-fused) is sibling, not equivalent. | Additive; ~43 entities. Small blast radius. Consider whether to expose as `binary_sensor.<room>_hvac_occupied` (mirrors `<room>_occupied`) or as an attribute on the existing sensor first; the entity form matches the operator's "must be observable" mandate. |
| Zone-level aggregation of HVAC-occupied rooms — Stage A′ (OR entry, MAX exit) | **REUSE (existing OR) + BUILD (retreat semantics)** | The OR is `hvac_zones.py:148` `any_room_occupied`. The retreat semantics currently live in the `grace_minutes` gate at `hvac.py:1786-1791` — that path already implements "zone conditions until last-room-clear + vacancy_grace." | A′-1 (OR) is *already* the existing shape; A′-3 (retreat stays zone-level `vacancy_grace`) preserves it. The only *change* is the input to `RoomCondition.occupied` (S3). A′-2 (retire zone-level dwell) is S1's default-to-0. Net: aggregation build is smaller than the proposal implied — it is largely a source-swap. |

**Nothing in the proposal implies rebuilding a mechanism that already exists undetected.**
The only "watch out" is the double-`DEFAULT_FAN_VACANCY_HOLD` constant already noted; a
new `CONF_HVAC_VACANCY_HOLD` should not add a third.

---

## Highest-value findings (summary for operator)

1. **Zero DELETE items** — no dead-and-useless code identified for removal. The
   re-architecture is largely a **population-source swap** at `hvac_zones.py:546`
   (`RoomCondition.occupied` is fed from a new HVAC-occupancy view instead of the
   lighting-fused `coordinator.data["occupied"]`) plus a **default flip** on the live
   `CONF_HVAC_ZONE_ENTRY_DWELL` knob.
2. **One footgun (S1):** if per-room HVAC dwell ships without defaulting
   `CONF_HVAC_ZONE_ENTRY_DWELL=0` in the SAME cycle, the two dwells stack and defeat
   fast-in. This is exactly the "code stacked on code" the operator flagged. Fold the
   default flip into the build; retire the entity label a release later; delete a
   release after that.
3. **The A′ aggregation build is smaller than it looks** — the OR is already
   `any_room_occupied` (`hvac_zones.py:148`); the zone-level retreat is already
   `vacancy_grace` (`hvac.py:1786-1791`). Only the *input* to the OR changes.
4. **`RoomCondition.occupied` has 12+ HVAC-path consumers** — the population-source
   swap is the entire ripple surface. Any plan that adds a *parallel* field
   (`RoomCondition.hvac_occupied`) instead of swapping the input to `.occupied` must
   enumerate and migrate all 12 consumers, or the swap is incomplete. Recommendation:
   **swap the input** to the existing field where semantics allow, and add a
   `hvac_occupied` sibling only if a lighting-vs-HVAC distinction on the same room is
   required at the same tick (Stage B or later).
5. **Proposal §8 default check:** the proposal cites `vacancy_grace = 10 min` and
   `zone_entry_dwell = 5 min`; source has `DEFAULT_VACANCY_GRACE_MINUTES=15`
   (`hvac_const.py:374`) and `DEFAULT_ZONE_ENTRY_DWELL_MINUTES=3` (`hvac_const.py:377`).
   Either the live install has overridden defaults or the proposal's "live reference
   numbers" section needs re-verifying against `.storage` before Stage 0.
6. **`DEFAULT_FAN_VACANCY_HOLD` defined twice** (`const.py:1153` and
   `hvac_const.py:821`) — do not add `DEFAULT_HVAC_VACANCY_HOLD` in both places.
   Pick the root `const.py` home.
7. **Grace-hold preservation is not a design decision — it's an inheritance rule.**
   Any new HVAC-occupancy view derived from raw `substrate.is_kind_active` without
   layering `grace_hold` will drop occupancy on a sensor blip. The safe shape is
   "kind-aware filter *on top of* room `STATE_OCCUPIED`" (which already carries
   grace-hold), never "kind-aware view of raw entity states."
8. **Fast-in prior art is proven** (§Stage D) — `_solar_follow` at
   `energy.py:1382` + `energy_const.py:996` is a clean template. Copy the pattern,
   don't build a new abstraction; the tick-wheel remains parked per operator ruling.

---

## Doc path

`/Users/okosisi/Code/universal-room-automation/docs/planning/AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md`
