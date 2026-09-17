# PLANNING — HVAC Zone Conditioning Demand (kind-at-edge, per-room hold, OR aggregation, night-trust in scope, DPM caller-side point-gate)

**Card:** `HVAC-ZONE-CONDITIONING-DEMAND-1` (step 4 of `HVAC-SUPPLE-SEQUENCE-1`)
**Tier:** **3** (operator-elevated — trust-hierarchy edit; comfort AND energy impacting).
**Status:** Round 3 revised — all plan-review CRIT/HIGHs resolved. HIGH-2 un-pended: the write-path inventory returned and identifies the seam as a caller-side point-gate in `_async_apply_preset_overrides` (setpoints written from `get_preset_for_house_state`, silently overwriting a caller-narrowed `effective_preset` at the setpoint layer while leaving `preset_mode` untouched). Folded as **D9**. Ready for final adversarial-completeness plan pass, then build dispatch.
**Companions (read first):**
- `docs/planning/PROPOSAL_hvac_conditioning_demand_2026_09_16.md`
- `docs/planning/AUDIT_hvac_conditioning_demand_supersession_and_reuse_2026_09_16.md`
- Card key `NIGHT_MEASUREMENT_2026_09_16` (7 nights fused-signal continuity — Master + Jaya only; see §MED-2)
- `AUDIT_thermostat_write_paths_2026_09_16` (**RETURNED** — feeds D9 / §0b resolution). Finding: wire write at `hvac.py:2568` IS funnelled through `emit_set_temperature`; what bypasses is caller-side preset composition — the DPM re-runs `get_preset_for_house_state` and writes SETPOINTS ONLY, overwriting any per-zone `effective_preset` narrowed upstream (e.g. by D7).
- Zone_1 oscillation trace — cross-verifies that a caller-side point-gate does NOT shorten HVAC-PRESET-FLAP-1's suppression window.
- Dependency card `ZIRI-PRESENCE-SENSOR-DEAD-1` — insurance context for the (collapsed) D8, not its proof.

Revision history: round 0 (initial), round 1 (CRIT-1 sibling / HIGH-1 options-flow / HIGH-2 swap verdicts / MEDs), round 2 (Option B, D7 + full D8), round 3 (kind-at-edge, D8 collapsed, per-line + full consumer enumeration, DPM seam pending), **round 3-rev (this — HIGH-2 un-pended; D9 DPM caller-side point-gate added; INV-1 no longer footnotes an unresolved seam)**.

---

## 0. Falsifiable invariant (Tier 3 — TWO conjunctive properties)

Reviewer D (§5) must falsify EITHER under any legal-config repro.

> **INV-1 (comfort / night safety):** *No sleeping resident's own bedroom ever falls to `away` overnight.*
> For any zone Z containing a bedroom-typed room R with (a) some `zone_persons` phone reading `home` in the 22:00-08:00 window, and (b) `binary_sensor.<R>_occupied` continuously `on` from some pre-sleep timestamp into the night, **the delivered conditioning for Z's thermostat MUST NOT resolve to `away`** at any tick between continuous-hold start and 06:00, regardless of transient un-occupied reads on R. "Delivered conditioning" — meaning both `effective_preset` AND the DPM writer's setpoint composition (D9): a preset preserved upstream must not be overwritten by baseline setpoints from `get_preset_for_house_state` downstream.

> **INV-2 (energy / promptness):** *An empty zone retreats promptly at night.*
> For any zone Z where `zone.any_room_hvac_occupied == false` (fused-signal denominator) for a continuous `vacancy_grace` window (live 10 min), **INCLUDING under `self._house_state in FAN_TRUST_STATES`**, **delivered conditioning** (preset AND setpoint composition) transitions to `away` within one loop tick after grace expires. **Precondition:** `zi == True` (`self._zone_intelligence_enabled`, `hvac.py:1781`); when Zone Intelligence is disabled, INV-2 is not a claim of this cycle.

**Subordinate corollaries:**
- Aggression = **absolute** on the daytime conditioning path (Stage A / D1): hallway-typed rooms never contribute to `any_room_hvac_occupied`.
- Grace-hold is **inherited** — `hvac_occupied` rides purely on the grace-held `STATE_OCCUPIED`. Kind information is consulted **only at rising edges**, never as a live AND (§CRIT-1 resolution below).
- **Fused-signal precondition on D7 AND D9:** the night-trust guard and the DPM setpoint gate both read the D1 sibling `zone.any_room_hvac_occupied`, built on grace-held `STATE_OCCUPIED`. **NEVER a raw substrate read** at either site.
- Adopt and retreat timers never stack (`CONF_HVAC_ZONE_ENTRY_DWELL` default flips to 0 the same cycle per-room `CONF_HVAC_VACANCY_HOLD` ships).
- **Generalization (§MED-1):** zero room-name / entry-id literals on the D1/D7/D8/D9 code path; a never-occupied dwelling room cannot arm any hold and its zone retreats normally.

---

## 0a. Night-trust decision — Option B, FINAL

Operator chose **Option B** (2026-09-16). Night-trust in scope. D7 reads the fused D1 signal; D8 provides a bounded night tail-hold for dwelling room_types; D9 gates the DPM setpoint writer on the same fused signal. Round-1 CRIT-2 is CLOSED.

**Reversal note (`project_zone_away_when_occupied_home_night_gap`, 2026-06-05 Zone-1 flap).** The 2026-06-05 fix broadened night-trust to preserve home-flank presets whenever any `zone_persons` phone read `home`, regardless of room occupancy. D7 narrows this: preservation is contingent on `zone.any_room_hvac_occupied` (fused). The 2026-06-05 failure mode was the resident's own room degrading mid-sleep; the fused signal's measured continuity (worst gap 2.4 min ≪ 10-min grace, Master + Jaya only — see §MED-2) plus the D8 dwelling-room night tail-hold are what keep INV-1 whole in that mode. **HVAC-PRESET-FLAP-1 interaction (§MED-4):** D7 does not aggravate the night away-flip HVAC-PRESET-FLAP-1 damps, and D9's caller-side point-gate is verified by the zone_1 oscillation trace to NOT shorten HVAC-PRESET-FLAP-1's suppression window — D9 SKIPS a write, it does not add one. **DST (§MED-4):** the wall-clock hour constants from round 2 are DELETED — D8 and D9 gate on `FAN_TRUST_STATES` (D8) or on `zone.any_room_hvac_occupied` (D9), not wall-clock. DST moot.

---

## 0b. HIGH-2 — RESOLVED (round 3-rev): DPM writer is a caller-side point-gate → D9

The write-path inventory (`AUDIT_thermostat_write_paths_2026_09_16`) returned. Finding:

- The DPM writer's WIRE write at `hvac.py:2568` (`await emit_set_temperature(...)`) IS already funnelled through the emit chokepoint (guards, freeze-floor, arrester suppression, throttle).
- **What bypasses is CALLER-SIDE preset composition.** `_async_apply_preset_overrides` at `hvac.py:2479` re-runs `self._preset_manager.get_preset_for_house_state(self._house_state)` at :2479 and reads `get_seasonal_setpoints(target_preset)` at :2518, producing baseline setpoints from house state directly. A per-zone `effective_preset` narrowed upstream (e.g. by D7 to `away`) is silently overwritten at the setpoint layer, while `preset_mode` is left untouched — the classic setpoint-vs-mode split.

**Conclusion:** HIGH-2 is NOT a chokepoint gap (the wire write already flows through the chokepoint) and NOT abstraction-owned (the `HVAC-THERMOSTAT-ABSTRACTION-1` cycle addresses `set_hvac_mode`, a different verb). It is a **step-4-B caller-side point-gate** and belongs in this cycle. Enumerated as **D9** (§2 below).

---

## 1. Institutional context verified (REUSE-or-BUILD per piece)

| Piece | Verdict | Prior art | Notes |
|---|---|---|---|
| Kind on the D1 path | **NOT USED (Stage B, deferred)** | n/a | D1 needs NO substrate kind method. Transit handled by circulation exclusion (hallway room_type); within-room kind-aware dwell/transit discrimination is Stage B (§6 non-goal). The round-3 `last_edge_kind_for` citation was WRONG (no such method; `occupancy_substrate.py:736 last_edge_entity_for` returns an entity_id) — and moot, since the kind read is dropped entirely. |
| Kind-active raw read | **AVOID as live gate** | `occupancy_substrate.py:732` `is_kind_active` — docstring: *"the current RAW bool"* | Banned as a live AND on D1/D7/D9 paths. Grep-provable. |
| Grace-held `STATE_OCCUPIED` | **REUSE (load-bearing D1 input)** | Set `coordinator.py:3581-3585`; ARM `coordinator.py:2925-2938` | D1 = grace-held `STATE_OCCUPIED` AND room_type != hallway, with per-room tail-hold. |
| Per-room tail-hold pattern | **REUSE (shape)** | `CONF_FAN_VACANCY_HOLD` `const.py:966`; `DEFAULT_FAN_VACANCY_HOLD=300` `const.py:1153`; consumer `automation.py:2164` | `DEFAULT_HVAC_VACANCY_HOLD` single home in `const.py`. |
| Zone occupancy confidence | **REUSE (unchanged)** | `presence.py:2057` / Source-4 `presence.py:2150` counts `rc.occupied` | No-swap. |
| Zone OR aggregation | **REUSE + add sibling** | `hvac_zones.py:148` `any_room_occupied` | Add `any_room_hvac_occupied` sibling. |
| Population point | **ADD SIBLING (never swap)** | `hvac_zones.py:546` | Add `RoomCondition.hvac_occupied` adjacent to `.occupied`. |
| Night-trust branch (D7 site) | **REUSE (single early guard)** | `hvac.py:2027-2040` | See D7. |
| DPM setpoint composition (D9 site) | **REUSE (add caller-side guard)** | `_async_apply_preset_overrides` `hvac.py:2479-2580` — per-zone loop at :2486; `target_preset = get_preset_for_house_state(...)` at :2479; `get_seasonal_setpoints` at :2518; emit at :2568 | See D9. |
| Suppression-log fire semantics | **REUSE (unchanged)** | `_night_trust_logged` log-once cache | D7 early guard does not fire the cache on non-firing. |
| `FAN_TRUST_STATES` | **REUSE** | `hvac_const.py` | D7 and D8 both key on it. |
| ROOM_TYPE tables | **REUSE (pattern) + BUILD** | `ROOM_TYPE_TIMEOUTS` `const.py:1171` | New: `ROOM_TYPE_HVAC_HOLD` (day) + `ROOM_TYPE_HVAC_HOLD_NIGHT` (D8). |
| `hallway` enum | **BUILD (safe additive)** | Enum `const.py:421-429`; selectors `config_flow.py:1387` AND `:10410-10420` | Both edited. |
| `CONF_HVAC_VACANCY_HOLD` per-room | **BUILD** | `CONF_FAN_VACANCY_HOLD` template. | |
| Per-room HVAC-occupancy entity | **BUILD** | No equivalent. | ~43 entities. |
| Fast sub-loop (Stage D fast-in) | **DEFERRED** | `_solar_follow` `energy.py:1382` | Non-goal. |

**Code locations surveyed for this revision (all files above, plus for D9):** `hvac.py:2470-2580` (`_async_apply_preset_overrides` — confirms `target_preset` derived from `self._house_state` at :2479, seasonal setpoints at :2518, emit at :2568; egress-pause and arrester gates present at :2492 and :2506).

---

## 2. Deliverables

### D1 — Per-room HVAC-occupancy producer (CRIT-1 resolution: kind at EDGE, not live AND)

**Signal semantics:**

```
# State per room (in the D1 producer):
#   hvac_armed[room] : bool           # rising-edge attribution latch
#   hvac_tail_until[room] : datetime  # falling-edge tail expiry

def value_for(room) -> bool:
    if room_type(room) == "hallway":
        return False                                # aggression = absolute
    st = coordinator.data.get(STATE_OCCUPIED)       # GRACE-HELD, load-bearing
    if st and not prev_state_occupied[room]:
        # NO kind read. Transit is handled by circulation exclusion
        # (room_type=="hallway" -> False above), NOT by per-edge kind.
        # Within-room kind-aware dwell/transit discrimination is Stage B
        # (deferred non-goal, §6). hvac_occupied rides purely on the
        # grace-held STATE_OCCUPIED + tail. This is what fully closes
        # CRIT-1: is_kind_active / any substrate kind method is never on
        # the D1 live path.
        hvac_armed[room] = True
        hvac_tail_until[room] = None
        return True
    if hvac_armed[room]:
        if st:
            return True                              # NO kind read here
        if hvac_tail_until[room] is None:
            hvac_tail_until[room] = now + effective_hold(room)
        if now < hvac_tail_until[room]:
            return True
        hvac_armed[room] = False
        return False
    return False
```

**Load-bearing property:** once armed by a rising `STATE_OCCUPIED` edge, `hvac_occupied` rides purely on `STATE_OCCUPIED` + tail. A raw mmWave blip that leaves the grace-held `STATE_OCCUPIED` intact does NOT drop `hvac_occupied` — CRIT-1 raw-drop failure mode closed.

**Sibling field:** ADD `RoomCondition.hvac_occupied` at `hvac_zones.py:546`. ADD `zone.any_room_hvac_occupied` at `hvac_zones.py:148`. Originals UNCHANGED.

**D1 acceptance:**
- **Verify:** grep confirms `is_kind_active` NOT called on the D1 live path.
- **Verify:** `RoomCondition.occupied` / `any_room_occupied` byte-identical for every non-preset consumer (§2a).
- **Verify:** producer-mutation drill leaves `_execute_vacancy_sweep` / fans / covers / Source-4 unaffected.
- **Test:** `test_d1_arms_on_state_occupied_rising_edge`
- **Test:** `test_d1_holds_through_raw_kind_blip` — CRIT-1 discriminator. Force `is_kind_active(room,"mmwave")=False`, `STATE_OCCUPIED` held; `value_for==True`.
- **Test:** `test_d1_falls_after_tail_expires`
- **Test:** `test_d1_hallway_never_arms`
- **Test:** `test_d1_never_occupied_room_does_not_arm` (MED-1)
- **Test:** `test_d1_no_room_name_literals` (MED-1)
- **Live (discriminating):** unmeasured bedroom with a blip-prone mmWave — `binary_sensor.<bedroom>_hvac_occupied` stays `on` across blip; attr `armed_by_kind` shows arming kind.

### D2 — Per-room HVAC-occupancy diagnostic entity

`binary_sensor.<room>_hvac_occupied`. Attrs: `armed`, `armed_by_kind`, `tail_expires_at`, `room_type`, `hvac_vacancy_hold_s`, `night_tail_active`, `source`.

Removed vs round 2: `night_leniency_active` / `night_leniency_expires_at` (arm-state-machine machinery deleted with D8 collapse).

### D3 — `ROOM_TYPE_HVAC_HOLD` (day) + `CONF_HVAC_VACANCY_HOLD` + single-home default

`DEFAULT_HVAC_VACANCY_HOLD = 60` in `const.py` only. `ROOM_TYPE_HVAC_HOLD` mirrors `ROOM_TYPE_TIMEOUTS`. Read `.get(type, DEFAULT_HVAC_VACANCY_HOLD)`.

### D4 — `hallway` enum + reclassify 6 rooms + BOTH selector lists + 5 `ROOM_TYPE_*` tables

Selectors `config_flow.py:1387` AND `:10410-10420`. Tables: `ROOM_TYPE_TIMEOUTS`, `ROOM_TYPE_RECHECK_FACTOR`, `ROOM_TYPE_FAILSAFE_DURATIONS`, `ROOM_TYPE_BLE_HOLD_CAP_*`, `ROOM_TYPE_FEATURE_DEFAULTS`, plus `ROOM_TYPE_HVAC_HOLD` and `ROOM_TYPE_HVAC_HOLD_NIGHT`. MED-b: (b-i) new-rooms-only or (b-ii) 6-hallway runbook step.

### D5 — Retire zone-level `zone_entry_dwell` (default 3 → 0)

`hvac_const.py:377` flip. Keep entity one release with LEGACY comment.

### D6 — Documentation-only retreat-semantics preservation

Block comment at `hvac.py:1786-1791` names `any_room_hvac_occupied`. Also document `zone_presence_state` denomination shift (per row 7 in §2a).

### D7 — Night-trust gate: SINGLE early guard on FUSED `any_room_hvac_occupied`

Immediately after the `FAN_TRUST_STATES` test at `hvac.py:2027`, insert ONE guard:

```
if effective_preset == "away" and self._house_state in FAN_TRUST_STATES:
    if not zone.any_room_hvac_occupied:
        pass                     # let `away` stand; DO NOT touch _night_trust_logged
    else:
        # UNCHANGED — home_persons build, log-once cache, veto path byte-identical.
        home_persons = [ ... ]
        if home_persons:
            effective_preset = <preserved>
            self._night_trust_logged.add(zone_id)
```

- Guard's non-firing does NOT emit `_night_trust_logged`. Separate diagnostic counter (`_zones_retreated_via_d7_guard`) may be added; do NOT overload the log-once cache.
- All-trackers-away veto path byte-identical.

**D7 acceptance:** unchanged from round 3 (grep no raw reads; `_night_trust_logged` subset property; empty-zone retreat test; occupied-bedroom preserved test; fused-not-raw CRIT-1 cross-check; INV-1 live check on unmeasured bedroom; INV-2 live check on empty guest wing).

### D8 — Night VARIANT of ROOM_TYPE_HVAC_HOLD (collapsed)

`ROOM_TYPE_HVAC_HOLD_NIGHT` in `const.py`; D1's `effective_hold(room)` picks the night table when `self._house_state in FAN_TRUST_STATES`:

```
def effective_hold(room) -> int:
    if self._house_state in FAN_TRUST_STATES:
        base = ROOM_TYPE_HVAC_HOLD_NIGHT.get(room_type, DEFAULT_HVAC_VACANCY_HOLD_NIGHT)
    else:
        base = ROOM_TYPE_HVAC_HOLD.get(room_type, DEFAULT_HVAC_VACANCY_HOLD)
    return per_room_override(room, base)
```

Self-gating: tail can only extend an existing D1 arm; discharge is inherent (natural expiry). Sizing = operator-checkpoint decision (bedroom 30-45 min, common_area 10-15, media_room 30-45, generic 10-15, others 0). Reframed as insurance for unmeasured rooms; no "REQUIRED / Ziri-as-proof" claim.

**D8 acceptance:** unchanged from round 3 (single-home constant; `effective_hold` house-state aware; no pre-arm/continuity/cap/restart; extends-only-when-armed; day vs night table selection; hallway zero; mid-window departure via natural expiry; INV-1/INV-2 live discriminators).

### D9 — DPM writer caller-side point-gate on FUSED `any_room_hvac_occupied` (HIGH-2 resolution, NEW)

**What.** Inside `_async_apply_preset_overrides` at `hvac.py:2479-2580`, add a caller-side guard in the per-zone loop (around :2515-2520, before `get_seasonal_setpoints`): when the zone is empty in the fused HVAC denomination (`zone.any_room_hvac_occupied == false`), the DPM MUST NOT compose home-baseline setpoints from `target_preset` and MUST NOT emit them to the thermostat for that zone. Sketch (exact placement pinned at build):

```
# Per-zone loop begins at hvac.py:2486.
# Existing gates at :2492 (egress-paused) and :2506 (arrester suppress) remain unchanged.
zone_overrides = all_overrides.get(zone_id, [])

# D9: caller-side point-gate. INV-1/INV-2 delivered conditioning.
# When the zone is empty in the HVAC denomination, DO NOT overwrite a
# caller-narrowed effective_preset with home-baseline setpoints.
# target_preset here is derived from self._house_state (not zone-scoped);
# writing baseline_cool/heat here would silently defeat D7's retreat.
if not zone.any_room_hvac_occupied:
    # Optional: increment a diagnostic counter (e.g. _dpm_skipped_empty_zones)
    continue

baseline = self._preset_manager.get_seasonal_setpoints(target_preset)
...
```

**Placement rationale:**
- BEFORE `get_seasonal_setpoints` at :2518 — the guard should cost nothing (no baseline compute, no override resolve, no throttle read, no arrester suppress). The existing egress-pause guard at :2492 and arrester-hold gate at :2506 already sit at this early point in the loop; D9 slots in next to them.
- AFTER the egress-pause gate (:2492) and the arrester-hold gate (:2506) — these are more specific protections that should still short-circuit first for their intended reasons; D9 is the general "empty zone" case.

**Fused-signal precondition:** D9 reads `zone.any_room_hvac_occupied` (the D1 sibling). NEVER `zone.any_room_occupied` (lighting-fused — a hallway crossing 15 min ago would keep DPM writing baseline), NEVER a raw substrate entity. Grep-provable in review; if the D9 diff contains any read of `zone.any_room_occupied` inside the DPM loop, it's a ship-stop.

**What D9 explicitly does NOT do:**
- Does NOT touch the wire-write chokepoint at :2568 (`emit_set_temperature`) — the chokepoint is already correct per the write-path inventory.
- Does NOT change `preset_mode`; the DPM does not write mode at this site. D9 is a setpoint-composition skip.
- Does NOT introduce a new time source, hour constant, or wall-clock read.
- Does NOT interact with `HVAC-THERMOSTAT-ABSTRACTION-1` (that cycle addresses `set_hvac_mode`, a different verb).
- Does NOT shorten HVAC-PRESET-FLAP-1's suppression window — it SKIPS a write; the flap suppression is about NOT writing on damped-flap conditions, so skipping is aligned. Verified against the zone_1 oscillation trace.

**D9 acceptance:**
- **Verify:** grep the D9 diff — inside the `_async_apply_preset_overrides` per-zone loop, the added guard reads `zone.any_room_hvac_occupied` and NOT `zone.any_room_occupied`; no `is_kind_active` and no raw substrate reads.
- **Verify:** the guard sits BEFORE `get_seasonal_setpoints` (:2518) and AFTER the arrester-hold gate (:2506). Both existing gates remain byte-identical.
- **Verify:** the wire chokepoint at :2568 is byte-identical pre/post.
- **Test:** `test_d9_skips_setpoint_write_on_empty_zone` — zone with `any_room_hvac_occupied=false`, house state `home_day` (target_preset would normally be `home`); assert `emit_set_temperature` is NOT called for that zone; assert `_last_emitted_range` for that zone is unchanged.
- **Test:** `test_d9_writes_setpoint_on_occupied_zone` — zone with `any_room_hvac_occupied=true`; assert normal setpoint composition + emit proceeds (guard does not regress the happy path).
- **Test (empty zone + active EC dynamic override, HIGH-2 required):** `test_d9_empty_zone_with_ec_dynamic_override_no_write` — zone empty in HVAC denomination AND an EC/dynamic override present in `zone_overrides`; assert D9 short-circuits BEFORE `get_seasonal_setpoints` and `emit_set_temperature` is not called. The point-gate must run regardless of whether an override is queued — an override for a preset that D7 has already narrowed to `away` upstream should not resurrect a home-baseline write. Rationale: the override machinery is a modifier on TOP of baseline; if there is no legitimate baseline to modify (empty zone), no write should happen.
- **Test:** `test_d9_reads_fused_not_lighting` — force `zone.any_room_occupied=true` while `zone.any_room_hvac_occupied=false` (e.g. hallway occupied, no dwelling room); assert D9 STILL short-circuits. **Under the wrong-fix failure mode** (D9 reads `any_room_occupied`), this test fails.
- **Test:** `test_d9_does_not_touch_wire_chokepoint` — mutation drill: verify `emit_set_temperature`'s arguments (guards, freeze-floor, arrester) are unchanged when D9 is disabled and the emit does happen.
- **Live (INV-1 discriminator):** unmeasured bedroom zone under `home_night` with D7 retreat armed AND DPM decision tick fires — the thermostat's setpoint does NOT swing to home-baseline. Observable via the setpoint-history recorder.
- **Live (INV-2 discriminator):** empty guest wing at 03:00 — no `emit_set_temperature` fires from `_async_apply_preset_overrides` for that zone; `_last_emitted_range[zone_guest]` unchanged across the DPM tick. **Under the wrong-fix failure mode** (D7 in scope but D9 missing), the guest wing would receive a home-baseline setpoint write moments after the D7 preset retreat — observable divergence.

---

## 2a. Per-site SWAP / NO-SWAP verdicts

**Rule of thumb:** swap iff the site is on the code path from `zone.any_room_occupied` to `effective_preset` mutation OR the DPM setpoint composition OR the retreat-timestamp basis feeding those decisions. All lighting / fan / cover / confidence reads stay on lighting-fused.

| # | Site | Reads | Verdict | Reasoning |
|---|---|---|---|---|
| 1 | `hvac.py:1794` preset flip | `any_room_occupied` | **SWAP** to `any_room_hvac_occupied` | The one conditioning-decision site. |
| 2a | `hvac_zones.py:556` `zone.last_occupied_time = now` | timestamp write | **SWAP basis** — write when `any_room_hvac_occupied` | Input to preset-flip grace timer. HVAC denomination. |
| 2b | `hvac_zones.py:557` `zone.vacancy_sweep_done = False` | flag reset | **NO-SWAP** — keep lighting-fused | Vacancy sweep is a LIGHTING actuator; blanket swap would leave hallway lights on. |
| 2c | `hvac_zones.py:560` `zone.continuous_occupied_since = now` | timestamp write | **SWAP basis** | Consumed by D6 stale branch, must match. |
| 2d | `hvac_zones.py:563` `zone.current_session_start = now` | timestamp write | **NO-SWAP** — keep lighting-fused | Consumed by `_zone_entry_dwell` at :1997; lighting-timing flap-guard, not HVAC decision. |
| 2e | `hvac_zones.py:564-566` `else:` resets | resets | **MIRROR each write's verdict** — split into two guards | Build task: refactor the single if/else into two guards keyed by denomination. |
| 3 | `hvac.py:1997` `_zone_entry_dwell` | `any_room_occupied` | **NO-SWAP** | Block retired (D5 default 0); lighting semantics one release. |
| 4 | `hvac.py:1814-1820` D6 stale branch | `any_room_occupied` + `continuous_occupied_since` | **SWAP** to HVAC denomination | Co-located with preset flip. |
| 5 | `hvac.py:2027-2040` night-trust (D7) | added `any_room_hvac_occupied` | **NEW guard** | Not a swap. |
| 5b | `hvac.py:~2515` DPM per-zone loop (D9) | added `any_room_hvac_occupied` | **NEW guard** | Not a swap; caller-side point-gate. |
| 6 | `hvac.py:3469` `_expire_pre_arrival_zones` | `any_room_occupied` | **NO-SWAP** | "Person arrived in ANY room" — hallway crossing legitimately clears. |
| 7 | `hvac.py:3625-3643` `zone_presence_state` | both | **SWAP both to HVAC denomination** | Pairing risk — must match `last_occupied_time` denomination (2a SWAPped). Diagnostic entity now reports HVAC-side occupancy (matches intent). |
| 8 | `hvac_predict.py:578` pre-cool | `any_room_occupied` / `rc.occupied` | **SWAP** | Conditioning-side prediction. |
| 9 | `hvac_predict.py:1368` pre-cool | same | **SWAP** | Same. |
| 10 | `hvac_override.py:2282` preset override | conditioning-side | **SWAP** | Same decision path as preset flip. Verify per-room vs zone-level at build. |
| 11 | `hvac_override.py:2433` preset override | conditioning-side | **SWAP** | Same. |
| 12 | `optimization.py:2412` `continuous_occupied_since` consumer | timestamp read | **NO-SWAP of read** — write source (2c) is SWAPPED | Semantic shift documented in build changelog. |
| 13 | `hvac_zones.py:349` seed writer (ZM path) | seed write | **NO-CHANGE** | Denomination-neutral (past-grace under either). |
| 14 | `hvac_zones.py:418` seed writer (legacy path) | seed write | **NO-CHANGE** | Same. |
| 15 | `hvac.py:3149-3220` `_execute_vacancy_sweep` | iterates rooms unconditionally | **NO-CHANGE** | No per-room `.occupied` read; light kill is downstream of the preset flip. |
| 16 | `hvac_fans.py:1477` `_read_room_occupied_state` | `rc.occupied` | **NO-SWAP** | Fan-OFF suppression — lighting hold correct. |
| 17 | `hvac_fans.py:755, 986` | `rc.occupied` | **NO-SWAP** | Fan semantics unchanged. |
| 18 | `hvac_covers.py:626` cover-close | held `STATE_OCCUPIED` | **NO-SWAP** | Longer hold correct. |
| 19 | `presence.py:2150` Source-4 | `rc.occupied` | **NO-SWAP** | Evidence-source counter; silent shift undesired. |
| 20 | `hvac_egress.py:483` | build to verify | **PRESUMPTION NO-SWAP** | Egress fan-adjacent. |
| 21 | `hvac.py:1787` comment | n/a | doc update | Name both fields. |
| 22 | `hvac.py:1808` | verify at build | **PRESUMPTION NO-SWAP** | Explicit at build. |
| 23 | `hvac.py:3462, 3627` | :3462 verify; :3627 covered by row 7 | **PRESUMPTION NO-SWAP** for :3462 | Explicit at build. |
| 24 | `hvac_zones.py:584` | verify at build | **PRESUMPTION NO-SWAP** | Explicit at build. |

Every SWAP requires an explicit changelist line naming site + reasoning.

---

## 3. Code supersession triage

Zero-DELETE. S1 default flip (D5); S3 sibling (not swap); S4/S5/S6/S7 documentation; S8 re-grep at build. D9 is additive — no supersession.

---

## 4. Knob ladder

| Knob | Home | Rationale |
|---|---|---|
| `ROOM_TYPE_HALLWAY` enum | Config/options flow | Per-deployment classification. |
| `ROOM_TYPE_HVAC_HOLD` (day) | Module constant `const.py` | Reviewed code change. |
| `ROOM_TYPE_HVAC_HOLD_NIGHT` (D8) | Module constant `const.py` (single home) | Safety-adjacent; operator checkpoint values. |
| `CONF_HVAC_VACANCY_HOLD` per-room (day) | Config/options flow | Rare per-room tune. |
| `DEFAULT_HVAC_VACANCY_HOLD` (60s) | Module constant `const.py` | Reviewed code change. |
| `DEFAULT_HVAC_VACANCY_HOLD_NIGHT` | Module constant `const.py` | Reviewed code change. |
| `binary_sensor.<room>_hvac_occupied` | Diagnostic entity | Observability. |
| `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` 3 → 0 | Module constant | D5. |
| `hvac_vacancy_grace_minutes` (live 10) | Existing Number entity | Unchanged. |
| D9 point-gate | No knob — hard-coded skip on `zone.any_room_hvac_occupied == false` | Safety property; not tunable. |

**Removed vs round 2:** `NIGHT_CONTINUOUS_HOLD_LENIENCY_MINUTES`, `NIGHT_LENIENCY_START_HOUR`, `NIGHT_LENIENCY_END_HOUR`.

---

## 5. Tier 3 review protocol (FOUR framing-disjoint reviews + plan-review pair)

**Plan reviews (before build).** TWO framing-disjoint:
- **PR-1 completeness.** Re-enumerate every consumer of `any_room_occupied` / `rc.occupied` / `last_occupied_time` / `continuous_occupied_since` and cross-check §2a. Verify no wall-clock time source on D1/D7/D8/D9. Verify no room-name/entry-id literals on D1/D7/D8/D9. Verify D9's placement (before `get_seasonal_setpoints`, after arrester gate) is stated exactly.
- **PR-2 adversarial build-prediction.** Named risks: (a) live-AND on `is_kind_active`; (b) `ROOM_TYPE_HVAC_HOLD_NIGHT` doubled into `hvac_const.py`; (c) :557 / :563 swapped by pattern-matching; (d) `_night_trust_logged` overloaded; (e) wall-clock hours reintroduced; (f) **D9 wired to `any_room_occupied` (lighting) instead of `any_room_hvac_occupied` (fused)**; (g) **D9 placed after `get_seasonal_setpoints` — wasted work and possible ordering hazard with arrester suppress**.

**Build reviews (four framing-disjoint, parallel):**
- **A — local correctness.** D1 state machine; §2a per-site verdicts; D3/D8 single-home constants; D4 five-tables `.get()` safety; **D9 read is `any_room_hvac_occupied`, placement is before `get_seasonal_setpoints`**.
- **B — state-machine + cross-coordinator integrity.** Retreat unchanged; hold vs grace never stack; D7 does not overload `_night_trust_logged`; D8 self-gating; **D9 does not touch the wire chokepoint at :2568 and does not shorten HVAC-PRESET-FLAP-1's suppression window** (verified by zone_1 oscillation trace); pre-arrival unaffected.
- **C — test authority via per-site source mutation.** Each SWAPPED site (rows 1, 2a, 2c, 4, 7, 8, 9, 10, 11) gets its own mutation drill; also **mutate D9 read from `any_room_hvac_occupied` to `any_room_occupied` — the row-5b test must fail**; also mutate `last_edge_entity_for` — a D1 arm-attribution test must fail.
- **D — adversarial completeness (falsify INV-1 AND INV-2).** Starting attempts:
  1. Unmeasured bedroom → INV-1 hold? (MED-1)
  2. Phone flakes home/away/home; D1 armed continuously → INV-1 hold?
  3. HA restart at 03:00 — collapsed D8 has no arm state; verify restart is a no-op.
  4. Two-bedroom zone: one armed, one empty → INV-2 fires only when both clear.
  5. Corridor at 03:00 → hallway short-circuits; zone stays `away`.
  6. **DPM writer bypass (was HIGH-2, now D9):** with D9 in place, can INV-1 still be broken via a DPM path around the effective_preset? Reviewer D must enumerate any other caller-side setpoint composition path (grep for `get_seasonal_setpoints` / `get_preset_for_house_state` uses outside `_async_apply_preset_overrides`). If a second such path exists that reads only house-state and writes setpoints, it needs an equivalent gate.
  7. Empty zone + active EC dynamic override — D9 short-circuits before the override is considered; assert no write.
  8. Zone with `zi == False` (MED-3) — INV-2 not claimed; verify plan does not implicitly assert it.

**Orchestrator independent verification before ship:** re-grep every `any_room_occupied` / `any_room_hvac_occupied` / `is_kind_active` usage; re-run source mutations on D1 (re-introduce live-AND), D7 (read lighting-fused), and D9 (read lighting-fused); confirm specific tests fail.

**Operator checkpoint BEFORE deploy:** INV-1 + INV-2 proofs, D8 sizing, D9 empty-zone-with-override test result, Reviewer D findings.

---

## 6. Non-goals (explicit)

- Fast-in Stage D loop.
- Whole-zone soft-posture / partial-vote aggression.
- Stage B stillness refinement.
- Stage C guest-as-zone-person.
- Auto-migration of the 6 hallway rooms.
- Delete of `CONF_HVAC_ZONE_ENTRY_DWELL` entity/field (deferred one release).
- Making `ROOM_TYPE_HVAC_HOLD_NIGHT` operator-tunable via number entity.
- Wall-clock hour constants for a night window.
- SWAPs at non-preset sites without an explicit changelist entry.
- **Changing `set_hvac_mode` write path.** That belongs to `HVAC-THERMOSTAT-ABSTRACTION-1`; D9 is setpoint-composition-only.
- **Changing the wire chokepoint at `hvac.py:2568`.** The write-path inventory confirms it is already correct.

---

## 7. Source disagreements resolved

1-4 unchanged.
5. Round-2 D1 formula vs plan-review CRIT-1: kind at rising edge only.
6. Round-2 D8 vs plan-review CRIT-2: collapsed to night ROOM_TYPE variant.
7. **NEW — Round-3 HIGH-2 (DPM writer) pending vs round-3-rev inventory:** the write-path inventory returned; the DPM's wire write IS at the chokepoint, but caller-side preset composition bypasses `effective_preset`. Resolution: **caller-side point-gate at `hvac.py:~2515`, added as D9** (not an abstraction cycle, not a chokepoint change).

---

## MED clarifications (folded)

- **MED-1** zero room-name/entry-id literals on D1/D7/D8/**D9** paths; live check on unmeasured bedroom.
- **MED-2** measurement scope is Master + Jaya only; every other bedroom UNMEASURED.
- **MED-3** INV-2 claimed only when `zi == True`.
- **MED-4** D7 does not aggravate HVAC-PRESET-FLAP-1 damping; D9 SKIPS writes (aligned with flap-suppression semantics); DST moot.

---

## Dependencies

- `ZIRI-PRESENCE-SENSOR-DEAD-1` — context for D8, not pre-req.
- `AUDIT_thermostat_write_paths_2026_09_16` — RETURNED; drove D9 disposition.
- Zone_1 oscillation trace — cross-verifies D9 does not shorten HVAC-PRESET-FLAP-1 suppression.

---

## Summary of round-3-rev changes

- **HIGH-2 un-pended and resolved as D9.** Write-path inventory identifies the seam as caller-side preset composition inside `_async_apply_preset_overrides` (:2479 target_preset; :2518 seasonal setpoints), NOT a chokepoint gap. D9 adds a caller-side point-gate BEFORE `get_seasonal_setpoints`, AFTER the arrester-hold gate, reading `zone.any_room_hvac_occupied` (fused). Wire chokepoint at :2568 untouched. Empty-zone + active EC dynamic override test enumerated.
- **INV-1 restated** — the "delivered conditioning" phrasing now points to D9 (setpoint composition) rather than a footnote to an unresolved HIGH-2.
- **Non-goals updated** — DPM point-gate exclusion REMOVED (now delivered); `set_hvac_mode` write path and wire chokepoint added as explicit non-goals to keep the surface tight.
- **Reviewer D** gains attempts (6) and (7) targeting D9 correctness and the "other caller-side setpoint composition path" enumeration.
- All prior round-3 fixes preserved: kind at edge (CRIT-1); D8 collapsed (CRIT-2/OC); full §2a table inlined with per-line splits (BP-1/BP-2); D7 exact insertion pinned (BP-5); MED-1..MED-4.

## Deliverable list (final)

- **D1** grace-held `STATE_OCCUPIED` + kind-at-edge + tail-hold producer; sibling `RoomCondition.hvac_occupied` + `zone.any_room_hvac_occupied`.
- **D2** per-room `binary_sensor.<room>_hvac_occupied` diagnostic entity.
- **D3** `ROOM_TYPE_HVAC_HOLD` (day) + `CONF_HVAC_VACANCY_HOLD` + `DEFAULT_HVAC_VACANCY_HOLD` single home.
- **D4** `hallway` enum + BOTH selector lists + 5 legacy `ROOM_TYPE_*` tables + reclassify 6 rooms.
- **D5** `DEFAULT_ZONE_ENTRY_DWELL_MINUTES` 3 → 0 (entity retained one release).
- **D6** documentation-only retreat-semantics preservation.
- **D7** night-trust single early guard on FUSED `any_room_hvac_occupied`.
- **D8** `ROOM_TYPE_HVAC_HOLD_NIGHT` (night variant of D3, self-gating via D1 arm).
- **D9** DPM writer caller-side point-gate: skip setpoint composition + emit when `zone.any_room_hvac_occupied == false`; placement before `get_seasonal_setpoints`, after existing arrester gate; wire chokepoint untouched.

## Pending

- None. HIGH-2 resolved as D9. All CRIT/HIGH plan-review findings folded.
