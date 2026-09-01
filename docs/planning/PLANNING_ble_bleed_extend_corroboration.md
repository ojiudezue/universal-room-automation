# PLANNING — BLE-BLEED-EXTEND-SLEEP-1: opt-in per-room BLE-hold cap (bathrooms/closets default ON)

**Card:** `BLE-BLEED-EXTEND-SLEEP-1`
**Thread:** presence-fusion + per-room config surface
**Tier:** **2-DB+** (config surface + presence-fusion path + RestoreEntity round-trip; op-standing policy for regression-prone work). **Rev 4 requires a fresh plan-review** — the config surface changed from Rev 3.
**Precedent:** BLE-WARM-CREATE-1 (v5.66.0) addressed the CREATE path; this cycle addresses the EXTEND path. Same bug family (adjacent-room BLE bleed corrupting occupancy truth), distinct code region.
**Bug classes:** Coincidental Equality Masks a Concept Split (Class #63) — Rev 3 collapsed "P24 failsafe duration" and "BLE-hold cap duration" into one number; they are separate policies. Trust-Hierarchy Ripple — unbounded BLE-solo extend refreshes a timeout other consumers trust. Suppression Needs a Discharge — P24's leg (ii) exemption was a suppression with no discharge for pure-BLE holds.

> **Rev 4 (2026-09-01) — SUPERSEDES Rev 1, Rev 2, and Rev 3.**
>
> Rev 3 proposed a BLANKET cap reusing the P24 failsafe duration for every room. Plan-review returned FIX-REQUIRED and the operator independently arrived at the same conclusion: a blanket 60-min cap would false-evict (a) real bathers on >60 min still soaks (mmwave loses the still torso, BLE-only holds them) and (b) sleepers in the six no-PIR rooms in `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md:41-53` — Game Room, Jaya Bedroom, Living Room, Study A, Study B, Master Bedroom — where a sleeper's mmwave drops on a still body and BLE holds them. That re-creates the exact nightly eviction P24's has-PIR exemption (`coordinator.py:4170-4175`) was written to prevent.
>
> **Rev 4 design (operator, 2026-09-01):** *"BLE extend is more important in bedrooms and shared living spaces like living rooms. So have a TOGGLE for the cap in the room's configuration section, mirrored in the options flow. Default OFF. Default ON for some room types on setup — bathrooms, closets etc."*
>
> This resolves the false-evict class by construction: bedrooms and common areas default OFF → sleepers never evicted; bathrooms and closets default ON → phantom bleed capped, with the operator explicitly accepting the "very long soak" trade. Read-only outside this plan doc.

---

## 1. Institutional context verified

### 1.1 The pinned root cause (unchanged from Rev 3, still correct)

The Master Bathroom 7.3 h BLE phantom on 08-29 evaded the 60-min bathroom failsafe because of **P24 leg (ii)** at `coordinator.py:4180-4182`:

```python
and data.get(STATE_OCCUPANCY_SOURCE) not in ("camera", "ble")
```

with the intent-comment at `:4120-4127` explicitly documenting: *"a BLE chain-hold is *evidence of presence*, not a stuck sensor, and force-vacating them AND latching `_failsafe_fired` would lock the visibly-present person out of subsequent override ticks."* That policy is correct for camera and for BLE inside the intended room; the failure mode is BLE bleed from an adjacent room. All the arithmetic is present — `_became_occupied_time` accumulates across BLE overrides (P24 2026-08-10), `_get_failsafe_duration_seconds()` returns 3600 s for `bathroom` — only the source-guard prevents the check.

The BLE chain-extend site is at `coordinator.py:3715-3716` (the `ble_allowed = chain_unbroken` conditional inside the `if BLE_CHAIN_HOLD_ENABLED:` block starting at `:3714`). Rev 3 mis-cited this as `:3713-3716`; corrected. The extractor delimiter comment for the test harness sits at `:4165-4167` (P24 block), which the test file's source-extraction pattern uses to bound the extracted region — corrected too.

### 1.2 Why blanket-reuse of `_get_failsafe_duration_seconds()` was wrong (the FIX-REQUIRED findings)

- **C1-HIGH-1 (real-bather false-evict):** 60 min is the SHORTEST number in `ROOM_TYPE_FAILSAFE_DURATIONS` (`const.py:1183`), not the operator's "long cap." A real bather on a >60 min still soak whose mmwave drops on the still torso, with BLE holding presence, would be evicted by the Rev-3 cap — the exact case the operator ruled must NOT regress.
- **C1-HIGH-2 (no-PIR-room sleeper eviction):** `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md:41-53` enumerates SIX no-PIR rooms — Game Room, Jaya Bedroom, Living Room, Study A, Study B, Master Bedroom. P24 leg (i) (has-PIR predicate at `coordinator.py:4170-4175`) exempts them from the failsafe knock-down precisely because a sleeping body has no PIR to refresh. A blanket BLE cap reusing the failsafe DURATION without inheriting leg (i) evicts them nightly. **This alone is why the cap must be per-room opt-in, not global.**
- **C1-HIGH-3 (Class #63 re-scope of a shared primitive):** the failsafe duration is only safe to apply as an eviction trigger under the AND of three guards — has-PIR AND override-absent AND `_last_pir_motion_time`-fresh. Reusing the number without those guards is exactly the "coincidental equality masks a concept split" pattern.
- **C1-HIGH-4 (test-harness defects):** the D2 source-extraction exec pattern in `quality/tests/test_ble_extend_not_create.py` does not import `_fire_max_active_failsafe_nm` into the extracted namespace — Rev-3 tests would have raised `NameError` at exec time. Mutation anchor #3 was false-green because `_FakeSelf` lacks `_get_failsafe_duration_seconds`. T-CAP-6 was a hollow assertion. Rev 4 fixes all three.
- **MED-1 (misleading NM):** Rev 3 reused `_fire_max_active_failsafe_nm` verbatim, whose diagnosis says *"force-vacated after N min (failsafe limit M min, PIR signal stale)"* and remedy says *"inspect the room's motion/mmwave sensors for stuck-on state."* Both are false on the BLE-cap path — nothing was force-vacated (the cap REFUSED to REFRESH; occupancy fell through naturally), and no sensor is stuck (a PHONE stayed present).
- **MED-2 (shared per-day latch collision):** with a shared `kind="max_active_failsafe"` + `key=(room_name,)` latch, a BLE-cap edge fires the day's single NM and suppresses a subsequent genuine P24 knock-down in the same room. Distinct diagnostics require a distinct `kind`.
- **MED-3 (L4 doesn't discriminate):** any single Tier-1 blip mid-hold does NOT actually re-seed `_became_occupied_time` (it's edge-set at `:3543` and only cleared at true vacancy `:4249`), but the L4 metric "longest contiguous BLE-source span" still misses the failure — the phantom's BLE span is broken by nothing because no sensor fires. The right metric is Tier-1-UNPROVENANCED occupied time per room per day (occupied-and-source-in-{"ble","timeout"}-with-no-Tier-1-fire-inside-2×timeout). Rewritten in §7.
- **MED-4 (L3 false assumption):** Rev 3's L3 discriminator claimed Master Bedroom was Tier-1-active as the reference "sleeper preserved" case. Per the audit, **Master Bedroom has NO PIR** (mmwave + bed-occupancy only). Rewritten to a room that actually has PIR.

### 1.3 Rev 4 fix: per-room toggle + separate duration map

- **Toggle:** `CONF_BLE_HOLD_CAP_ENABLED` (per-room bool, config_flow + options_flow). Kill-switch semantics: **OFF ⇒ BLE extends freely (today's behavior, byte-identical);** ON ⇒ the cap applies.
- **Type-keyed setup default:** `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` (`room_type → bool`). At room setup, apply the default when the field isn't explicitly set — exact mirror of `CONF_OCCUPANCY_TIMEOUT`'s pattern at `config_flow.py:991-996` (`ROOM_TYPE_TIMEOUTS.get(room_type, DEFAULT)`).
- **Distinct duration map:** `BLE_HOLD_CAP_DURATIONS` (`room_type → seconds`) — decoupled from `ROOM_TYPE_FAILSAFE_DURATIONS` so the BLE-hold policy can diverge (per the "long cap" operator brief). Recommendation in §5.
- **Distinct NM kind:** `kind="ble_hold_cap"` (loses P24-latch dedup, keeps diagnostics honest — recommended).
- **The cap block runs ONLY when this room's toggle is ON,** and its enablement never affects Tier-1 primary occupancy (a real occupant tripping any Tier-1 sensor takes the primary branch and never enters the BLE block — see §1.5).

### 1.4 Institutional greps for the three new symbols

**`CONF_BLE_HOLD_CAP_ENABLED` — NEW.** Grep for `CONF_BLE_HOLD` in `custom_components/universal_room_automation/` returned zero. Prior-art template for a per-room bool toggle:
- `const.py:958` — `CONF_FAN_CONTROL_ENABLED: Final = "fan_control_enabled"`
- `const.py:1022` — `CONF_HUMIDITY_FAN_CONTROL_ENABLED: Final = "humidity_fan_control_enabled"`
- `const.py:1051` — `CONF_SLEEP_PROTECTION_ENABLED: Final = "sleep_protection_enabled"`

Setup-step wiring pattern: `config_flow.py:1902` (`if user_input.get(CONF_FAN_CONTROL_ENABLED):`) and `:1914` (`vol.Optional(CONF_FAN_CONTROL_ENABLED, default=False): selector.BooleanSelector()`).

Options-flow wiring pattern (options flow lives inside `config_flow.py`, not a separate `options_flow.py` — verified via grep): `:10534-10535` (`CONF_FAN_CONTROL_ENABLED, default=self._get_current(CONF_FAN_CONTROL_ENABLED, False)`).

Rev 4 mirrors this shape exactly.

**`ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` — NEW.** Grep `ROOM_TYPE_BLE` returned zero in code (only `docs/planning/kanban.data.yaml`). Prior-art template for a room-type-keyed dict with a `.get(..., default)` setup application:
- `const.py:1183` — `ROOM_TYPE_FAILSAFE_DURATIONS`
- `ROOM_TYPE_TIMEOUTS` — read at `config_flow.py:994`.

Rev 4 mirrors the second: applied AT SETUP in `async_step_room_setup` when the operator hasn't set the toggle explicitly.

**`BLE_HOLD_CAP_DURATIONS` — NEW.** Grep `BLE_HOLD_CAP` returned zero in code. Same module-const shape as `ROOM_TYPE_FAILSAFE_DURATIONS`.

**REUSED (unchanged from Rev 3):**
- `_became_occupied_time` — set `coordinator.py:3543`, seeded on BLE admit `:3738-3739`, cleared `:4249`.
- `_get_config(key, default)` — `coordinator.py:617-627` — the canonical options-then-data-then-default read; used to read the per-room toggle at cap-check time.
- `BLE_CHAIN_HOLD_ENABLED` kill-switch — `const.py:575`, preserved as the top-level gate above the toggle check.
- `_fire_max_active_failsafe_nm` — `coordinator.py:218-239` — REUSE the *shape* (the `fire_stuck_signal` NM emit helper), NOT the exact function. A sibling `_fire_ble_hold_cap_nm` with `kind="ble_hold_cap"`, distinct diagnosis, distinct remedy.

### 1.5 C1 non-regression by construction (unchanged, still holds)

- `any_sensor_active = motion_detected or presence_detected or occupancy_detected` at `coordinator.py:3226` — all three Tier-1 legs (PIR `:3175`, mmwave `:3181`, occupancy_sensor).
- On `any_sensor_active`: primary branch at `:3522-3538` sets `data[STATE_OCCUPIED]=True` with source in {"motion","mmwave","occupancy_sensor"}.
- BLE chain-extend block at `:3630` only runs `if not data.get(STATE_OCCUPIED) and not self._failsafe_fired`. **A real occupant tripping ANY Tier-1 sensor never enters the BLE block — the cap cannot see them.**
- The cap only bites in the pure-BLE-solo tick pattern (which IS the phantom shape). This holds regardless of the toggle default.

### 1.6 Prior planning docs / audits / memories consulted
- `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md` — full read; six no-PIR rooms enumerated at `:41-53`; drives C1-HIGH-2 and the ROOM_TYPE_BLE_HOLD_CAP_DEFAULT policy (no-PIR rooms are exclusively bedroom/common-area/study types today, so a bathroom+closet default-ON is safe against C1-HIGH-2).
- `docs/planning/PLANNING_ble_extend_not_create.md` — full read; test harness pattern and invariant surface.
- `docs/readmes/README_v5.66.0.md` — full read; BLE-WARM-CREATE-1 D-MEDIUM-1 restart-pin (fail-open on `_became_occupied_time is None`).
- `docs/readmes/README_v4.5.15.md` — full read; failsafe duration and per-room-type lookup precedent.
- `docs/planning/AUDIT_detector_silence_and_restart_causes.md` — read the P24 leg (i)/(ii)/(iii) derivation.
- `quality/fixtures/ledger_golden/P24.json` — read; P24 invariant ledger.
- Memory `feedback_coincidental_equality_masks_concept_split.md` — this cycle's bug shape (Rev 3 exemplar).
- Memory `feedback_suppression_needs_discharge.md` — P24 leg (ii) is a suppression; this cycle installs a per-room-opt-in discharge.
- Memory `feedback_do_robust_fix_not_bandaid_and_card.md` — an opt-in cap with a distinct duration map IS the robust fix; Rev 3's blanket-reuse was the shortcut.
- Memory `feedback_hollow_test_anchors.md` — informs the T-CAP-6 rework (§5 D4).
- Memory `feedback_mutation_verification_pycache_staleness.md` — subprocess isolation + `.pyc` clear for all mutation anchors.
- Memory `feedback_parsimonious_room_config.md` — flagged; the new toggle IS additional config surface, justified by the per-room-policy requirement (bathrooms want the cap; bedrooms must not have it) which cannot be satisfied without a per-room field.

### 1.7 Design docs read
- `docs/Coordinator/HOUSE_MANUAL.md` — failsafe semantics; per-room-type-durations documented at §107-108. Rev 4 will require a manual delta noting the new BLE-hold-cap policy is separate.

### 1.8 Code locations surveyed end-to-end
- `coordinator.py:3175-3226` (source detection assembly), `:3510-3570` (primary occupancy branches), `:3623-3760` (BLE chain-extend — the surgery site), `:4106-4249` (P24 failsafe + TRUE VACANCY FINALIZE), `:218-247` and `:629-647` (NM emit + duration helpers), `:617-627` (`_get_config`).
- `config_flow.py:985-997` (room-setup step + `ROOM_TYPE_TIMEOUTS.get(...)` default pattern), `:1902-1924` (per-room BooleanSelector setup pattern), `:10520-10560` (options-flow `self._get_current(...)` pattern).
- `const.py:958`, `:1022`, `:1051` (CONF_*_ENABLED prior art), `:1177-1188` (`ROOM_TYPE_FAILSAFE_DURATIONS`, `DEFAULT_FAILSAFE_DURATION_SECONDS`), `:575` (`BLE_CHAIN_HOLD_ENABLED`).
- `quality/tests/test_ble_extend_not_create.py` (full — extended by this cycle; the source-extraction exec ns fix is a D4 deliverable).

---

## 2. Problem statement

**Symptom:** Master Bathroom held `STATE_OCCUPIED=True, STATE_OCCUPANCY_SOURCE="ble"` for ~7.3 h across the 08-29 sleep window with no body signal in the room. Room's P24 failsafe is 60 min. Root cause pinned in §1.1.

**Blast:** ~zero direct actuation cost in-room; truth corruption reaches every consumer of Master-Bath occupancy (zone `_room_occupied` roll-up → house-state contribution → HVAC preset selection, load-shed gates, guest-mode gates; regime_detector rows). Operator: *"might show up in other ways."*

**Non-regression contract:** no eviction of the six no-PIR-room sleepers, and no eviction of a real bather on a still soak.

---

## 3. Fix — per-room opt-in BLE-hold cap

The BLE chain-extend block gets a per-room-gated duration cap. The cap is a REFUSAL TO REFRESH (not a knock-down); the P24 failsafe block itself is byte-preserved.

### 3.1 Surgery site — `coordinator.py:3714-3722`

Replace the current `ble_allowed = chain_unbroken` conditional. Sketch (final wording is a builder deliverable; reviewer verifies against the invariant in §4):

```python
ble_allowed = False
if BLE_CHAIN_HOLD_ENABLED:
    chain_unbroken = self._last_occupied_state
    if chain_unbroken:
        # BLE-BLEED-EXTEND-SLEEP-1 (Rev 4): per-room opt-in BLE-hold cap.
        # OFF ⇒ pre-cycle behavior (byte-identical, unbounded chain refresh).
        # ON  ⇒ refuse to refresh once the session's own duration has
        #        exceeded BLE_HOLD_CAP_DURATIONS[room_type]. Distinct from
        #        the P24 failsafe duration (see const.py) so the cap
        #        policy can diverge (operator brief: "long cap").
        cap_enabled = self._get_config(
            CONF_BLE_HOLD_CAP_ENABLED, False,
        )
        if not cap_enabled:
            ble_allowed = True                              # today's behavior
        elif self._became_occupied_time is None:
            ble_allowed = True                              # D-MEDIUM-1 fail-open
        else:
            duration = (now - self._became_occupied_time).total_seconds()
            cap_seconds = self._get_ble_hold_cap_seconds()  # new helper
            ble_allowed = duration <= cap_seconds
            if not ble_allowed:
                self.hass.async_create_task(                # noqa: untracked-ok
                    _fire_ble_hold_cap_nm(
                        self.hass, room_name,
                        duration / 60, cap_seconds / 60,
                    ),
                )
```

**Notes on the sketch (each = a reviewer verification anchor):**
- Inside `if BLE_CHAIN_HOLD_ENABLED:` — top-level kill preserved.
- `_get_config(CONF_BLE_HOLD_CAP_ENABLED, False)` — REUSED helper at `coordinator.py:617-627` (options → data → default). Fail-safe default False means an existing config entry with no toggle set behaves byte-identically to today.
- `_get_ble_hold_cap_seconds()` — new helper, exact structural mirror of `_get_failsafe_duration_seconds()` at `coordinator.py:629-647`: `BLE_HOLD_CAP_DURATIONS.get(self._room_type, DEFAULT_BLE_HOLD_CAP_SECONDS)`.
- `_became_occupied_time is None` → admit (D-MEDIUM-1 pin preserved; first real tick post-restart re-seeds via the existing `:3738-3739` branch).
- Rejection path falls through to the existing `else` at `:3752` — `data[STATE_BLE_PERSONS]` still populated for diagnostics.
- With `ble_allowed=False`, `data[STATE_OCCUPIED]` remains False (as decided by primary branches earlier in `_async_update_data`). Next tick, `_last_occupied_state=False` → `chain_unbroken=False` → BLE cannot re-rescue until a Tier-1 fire re-seeds.
- **No `_failsafe_fired` write.** The cap is a refusal, not a knock-down; a Tier-1 fire the next tick re-asserts occupancy cleanly.
- **P24 block untouched.** Leg (ii) still exempts BLE from the knock-down+latch path (correct — that path would lock out a visibly-present person on subsequent Tier-1 ticks).

### 3.2 Freshness conjunct — DECISION (operator to confirm)

Per instruction, decide explicitly whether the cap should carry a leg-(iii)-style PIR-freshness spare (admit if `_last_pir_motion_time` is within 2× timeout even past the cap).

- **Option F1 — no freshness conjunct (RECOMMENDED, matches operator brief).** Operator explicitly dropped corroboration in favor of "a long cap"; a longer own duration substitutes for freshness. No-PIR rooms are protected by the toggle defaulting OFF for their room types. Simpler test surface, single knob.
- **Option F2 — with leg-(iii)-style freshness spare.** Extra safety on rooms where the operator opts the cap ON despite the room being PIR-equipped and used for long stillness (e.g. a study or reading room). Adds a second predicate + one more test branch.

**Recommend F1.** No-PIR rooms default OFF; PIR-equipped rooms with the cap ON accept the trade because the operator turned it on. A too-short cap SELF-HEALS on any next Tier-1 fire (primary branch re-occupies) — the harm is a transient off during perfect stillness, not a lockout. Operator to confirm; if F2, the sketch above gains one AND-conjunct.

### 3.3 Distinct NM `kind` — DECISION

- **Option N1 (RECOMMENDED):** `kind="ble_hold_cap"` with a distinct `_fire_ble_hold_cap_nm` helper. Diagnosis: *"room {name}: BLE-hold cap fired after {minutes} min ({limit} min limit) — pure-BLE-source hold ended without body-signal corroboration."* Remedy: *"if the room is expected to hold BLE-only presence for longer periods (e.g. a still bather), raise BLE_HOLD_CAP_DURATIONS or turn CONF_BLE_HOLD_CAP_ENABLED off; if this fires when nobody is in the room, investigate adjacent-room BLE bleed (scanner topology)."* Per-day latch is per-`kind`+`key`, so BLE-cap fires don't suppress a genuine P24 knock-down NM in the same room the same day.
- **Option N2:** reuse `kind="max_active_failsafe"` (shared latch dedups both paths). Loses diagnostic honesty (MED-1) and creates suppression collision (MED-2).

**Recommend N1.** Distinct semantics deserve distinct diagnostics; the per-day latch collision (MED-2) is a real bug.

---

## 4. Falsifiable invariant

> Let `E := self._get_config(CONF_BLE_HOLD_CAP_ENABLED, False)` for a given room.
>
> **(A) When `E == False`:** the BLE chain-extend leg's refresh behavior is byte-identical to the pre-cycle code (`ble_allowed = chain_unbroken`). This MUST be observable as no change in `data[STATE_TIMEOUT_REMAINING]` writes for any tick sequence where the toggle is OFF.
>
> **(B) When `E == True`:** the BLE chain-extend leg MUST NOT refresh `STATE_TIMEOUT_REMAINING` when `(now - self._became_occupied_time) > _get_ble_hold_cap_seconds()`. Restart mid-hold with `_became_occupied_time is None` fails OPEN (admit). A room with any Tier-1 sensor firing this tick is NEVER evaluated by the cap (it takes the primary occupancy branch and never enters the BLE block).
>
> **(C) A room whose `_room_type` maps `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` to True MUST have `CONF_BLE_HOLD_CAP_ENABLED=True` after SETUP unless the operator explicitly set it False on the setup form. Room-type default application on setup mirrors `ROOM_TYPE_TIMEOUTS.get(room_type, DEFAULT)` at `config_flow.py:991-996`.**

**Falsification observations:**
- **A-falsifier:** any recorder replay across a night, with the toggle OFF, whose `STATE_TIMEOUT_REMAINING` write sequence in the BLE-extend region differs from a Rev-3-pre-deploy baseline replay of the same sensor trace.
- **B-falsifier (phantom shape, cap ON):** the Master Bath 08-29 replay MUST show the room drop within one polling interval after `_became_occupied_time + cap_seconds`.
- **B-non-eviction falsifier (real Tier-1-active occupant, cap ON):** any room with the cap ON in which a Tier-1 sensor fires periodically MUST retain occupancy indefinitely — occupancy sits under the primary branch, source ∈ {"motion","mmwave","occupancy_sensor"}, and the BLE block is not entered.
- **B-no-PIR-eviction falsifier (bedroom sleeper — the C1-HIGH-2 case):** the Master Bedroom (no PIR, sleeper still, BLE holds) with the cap DEFAULTING OFF MUST NOT drop. If it drops, the default policy is broken.
- **C-falsifier:** create a new bathroom via config_flow without touching the new toggle field — resulting config entry must have the toggle True. Create a new bedroom the same way — resulting entry must have the toggle False.

---

## 5. Deliverables

### D1 — Constants (`const.py`)

Three new symbols, adjacent to `BLE_CHAIN_HOLD_ENABLED` and `ROOM_TYPE_FAILSAFE_DURATIONS`:

```python
# Per-room toggle: BLE-hold cap on the chain-extend leg.
# OFF (default) ⇒ BLE extends freely (today's behavior, byte-identical).
# ON            ⇒ refuse to refresh once the session's own duration
#                 has exceeded BLE_HOLD_CAP_DURATIONS[room_type].
CONF_BLE_HOLD_CAP_ENABLED: Final = "ble_hold_cap_enabled"

# Room-type SETUP DEFAULT for CONF_BLE_HOLD_CAP_ENABLED.
# Applied ONCE at config_flow room-setup (mirrors the
# ROOM_TYPE_TIMEOUTS.get(...) pattern at config_flow.py:991-996).
# Rooms NOT in this dict default to False (unbounded BLE extend today).
ROOM_TYPE_BLE_HOLD_CAP_DEFAULT: Final = {
    ROOM_TYPE_BATHROOM: True,
    ROOM_TYPE_CLOSET:   True,
    # bedroom / common area / study / media / garage / utility / generic
    # / infrastructure: default False (protects no-PIR sleepers).
}

# Per-room-type cap duration. Deliberately DECOUPLED from
# ROOM_TYPE_FAILSAFE_DURATIONS: the P24 failsafe is a stuck-sensor
# force-vacate under a three-guard AND; this cap is a refusal-to-refresh
# for opted-in rooms with a different policy shape.
DEFAULT_BLE_HOLD_CAP_SECONDS: Final = 120 * 60         # 120 min (2 h)
BLE_HOLD_CAP_DURATIONS: Final = {
    ROOM_TYPE_BATHROOM: 120 * 60,                      # 120 min (operator 2026-09-01)
    ROOM_TYPE_CLOSET:   120 * 60,                      # 120 min (operator 2026-09-01)
    # Other room types fall through to DEFAULT_BLE_HOLD_CAP_SECONDS
    # if a future operator opts the toggle ON for them.
}
```

**Recommended durations (operator to confirm):**
- **Bathroom = 90 min.** Long enough for a genuine soak or a hot bath with reading; if it's too short, self-heals on any next mmwave/PIR fire. Rev 3's 60 min (via reuse of failsafe) was flagged as C1-HIGH-1; 90 min is a modest overshoot chosen to sit inside "long tail of real soaks" and outside "typical toilet visit or shower." A phantom hold would still be bounded to 90 min rather than 7.3 h (99% reduction in the observed excess).
- **Closet = 60 min.** Closets are rarely occupied for long stretches; matches the P24 failsafe number because the policy risk profiles happen to converge here (a person changing clothes rarely stays past 60 min). If the operator wants longer, the map is trivially editable.
- **Default (for any future opt-in of another room type) = 2 h.** Chosen at the low end of "long cap" — the operator can raise for specific rooms.

**Rung (per `feedback_numbers_get_knobs`):** module constants at the reviewed-change rung. The per-room toggle is at the config/options rung (operator-settable, persistent). Duration values remain at module rung because they are fusion-safety policy — a per-room dial would balloon the config surface (rejected per `feedback_parsimonious_room_config`); if a specific room needs a bespoke duration later, the operator's escape hatch is to turn the toggle off and re-argue.

### D2 — Config-flow + options-flow surface (`config_flow.py`)

- **Setup step** (`async_step_room_setup`, `:985-`) — add `CONF_BLE_HOLD_CAP_ENABLED` as a `vol.Optional(...)` with `default=self._compute_ble_cap_default()` where the helper reads `user_input.get(CONF_ROOM_TYPE)` and looks up `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(room_type, False)`. Explicit application block IN the `if user_input is not None:` branch mirroring `:991-996`:
  ```python
  # Set default BLE-hold-cap toggle based on room type if not explicitly set.
  if CONF_BLE_HOLD_CAP_ENABLED not in user_input:
      room_type = user_input.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
      self._data[CONF_BLE_HOLD_CAP_ENABLED] = ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(
          room_type, False,
      )
  ```
- **Options flow** (existing per-room options step near `:10534-10560`) — add:
  ```python
  vol.Optional(
      CONF_BLE_HOLD_CAP_ENABLED,
      default=self._get_current(CONF_BLE_HOLD_CAP_ENABLED, False),
  ): selector.BooleanSelector(),
  ```
  Fallback default False in options flow means existing rooms whose config entry predates this cycle (no field set) behave byte-identically until the operator opens options and flips them.

### D3 — Coordinator surgery (`coordinator.py`)

- Add `_get_ble_hold_cap_seconds(self) -> int` — structural mirror of `_get_failsafe_duration_seconds`:
  ```python
  def _get_ble_hold_cap_seconds(self) -> int:
      from .const import (
          BLE_HOLD_CAP_DURATIONS, DEFAULT_BLE_HOLD_CAP_SECONDS,
      )
      return BLE_HOLD_CAP_DURATIONS.get(
          self._room_type, DEFAULT_BLE_HOLD_CAP_SECONDS,
      )
  ```
- Add `_fire_ble_hold_cap_nm(hass, room_name, minutes, limit_min)` — sibling of `_fire_max_active_failsafe_nm` at `:218-239`, `kind="ble_hold_cap"`, distinct diagnosis/remedy strings per §3.3 Option N1, `title_override` carrying room + duration for audit-row attributability (preserves the P24 diagnosability pattern).
- Replace the `ble_allowed = chain_unbroken` block at `:3714-3722` per §3.1 sketch.

### D4 — Test authority additions (`quality/tests/test_ble_extend_not_create.py`)

**First, fix the C1-HIGH-4 harness defects:**
- The source-extraction exec pattern must inject the NM helper (and `_get_ble_hold_cap_seconds` when needed) into the exec namespace explicitly (e.g. `exec(src, {"_fire_ble_hold_cap_nm": _stub, "_get_ble_hold_cap_seconds": lambda self: 3600, ...})`). Same fix applied for any test that references `_fire_max_active_failsafe_nm` inside an extracted region.
- Extend `_FakeSelf` (`:110-`) with `_get_ble_hold_cap_seconds()` returning a fixture-injected value, and with the new toggle read via `_get_config` returning a fixture-injected bool.

**New tests:**
- **T-CAP-OFF (invariant A):** toggle False, session `_became_occupied_time = now - 10 h`, BLE persons continuous, no Tier-1 → admit. Assert `data[STATE_OCCUPIED]=True`, `data[STATE_OCCUPANCY_SOURCE]="ble"`, refresh occurs. **Byte-identical to pre-cycle behavior.**
- **T-CAP-ON-EVICT (invariant B, phantom replay):** `room_type="bathroom"`, toggle True, `_get_ble_hold_cap_seconds` returns 5400 (90 min via test-injection), `_became_occupied_time = now - 5401`, BLE continuous, no Tier-1 → reject. Next tick with `_last_occupied_state=False` also rejects (chain broken).
- **T-CAP-ON-SUSTAIN (invariant B, just-under):** same but `_became_occupied_time = now - 5399` → admit.
- **T-CAP-DEFAULT-DURATION (invariant B, non-bathroom opt-in):** `room_type="bedroom"`, toggle True, no bedroom entry in `BLE_HOLD_CAP_DURATIONS` → falls through to `DEFAULT_BLE_HOLD_CAP_SECONDS`. Session past the default → reject; under → admit. Discriminator against T-CAP-ON-EVICT (proves the per-room-type lookup + default fallthrough works).
- **T-CAP-RESTART (D-MEDIUM-1 pin):** toggle True, `_became_occupied_time is None`, `chain_unbroken=True`, BLE persons present → admit; assert `_became_occupied_time` seeded to `now` post-admit via `:3738-3739`.
- **T-CAP-NM-DISTINCT (replaces hollow T-CAP-6):** on the T-CAP-ON-EVICT edge, capture the injected NM stub's calls and assert **(a)** helper `_fire_ble_hold_cap_nm` was invoked (not `_fire_max_active_failsafe_nm`), **(b)** its arguments carry the room + duration, **(c)** a separately-orchestrated P24-knock-down of the same room the same day is NOT suppressed by the BLE-cap fire (two-path observation — invoke both stubs in sequence and assert distinct latch keys via a small `fire_stuck_signal` fake that records `(kind, key, day)`).
- **T-CAP-CONFIG-DEFAULT (invariant C — config_flow unit test, sibling test file):** import `config_flow.async_step_room_setup` behavior via the existing config-flow test harness pattern (or a new small `test_ble_hold_cap_config_default.py` if the harness doesn't already exist here — verify before adding). Submit `{CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM}` without the toggle field → resulting `_data[CONF_BLE_HOLD_CAP_ENABLED] == True`. Submit `{CONF_ROOM_TYPE: ROOM_TYPE_BEDROOM}` → False. Submit `{CONF_ROOM_TYPE: ROOM_TYPE_BATHROOM, CONF_BLE_HOLD_CAP_ENABLED: False}` → False (explicit override respected).
- **T-CAP-OPTIONS-ROUNDTRIP (invariant C, options flow):** an existing entry with the toggle True, opened in options, saved without touching → toggle remains True. Toggled False and saved → coordinator's next `_get_config` read returns False. Restart persistence: verify via the standard config-entry restart pattern used in sibling tests (grep first; do not fabricate a new harness).

**Mutation anchors (subprocess-isolated with `.pyc` cleared per `feedback_mutation_verification_pycache_staleness`), C1-HIGH-4 remediated:**
1. Mutate the toggle check to always-True (force cap always on) → T-CAP-OFF MUST go red (byte-identity broken); C1-HIGH-2 non-eviction tests (see #4 below) MUST go red.
2. Mutate the duration comparator to `False` (always reject when cap on) → T-CAP-ON-SUSTAIN MUST go red.
3. **RE-HOMED per C1-HIGH-4:** the `_get_ble_hold_cap_seconds` selector is now a real coordinator method with a real dict lookup. Mutation target: modify `BLE_HOLD_CAP_DURATIONS` in a copy of the module to remove the `bathroom` entry → a REAL-coordinator unit test (`test_ble_hold_cap_lookup.py`, sibling of `test_v4515_closet_bathroom_failsafe.py:64-86`) that instantiates the durations map and calls the lookup MUST show the bathroom now returning `DEFAULT_BLE_HOLD_CAP_SECONDS`. This tests the actual dict, not a `_FakeSelf`.
4. Mutate the `_fire_ble_hold_cap_nm` call to a no-op → T-CAP-NM-DISTINCT MUST go red.
5. Mutate `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT[ROOM_TYPE_BATHROOM]` to False → T-CAP-CONFIG-DEFAULT bathroom-True assertion MUST go red; bedroom-False MUST stay green (proves the mapping is the discriminator).

**Regression pins (unchanged, MUST stay green):** `test_extend_path_ble_holds_still_body_when_chain_unbroken`, `test_sleep_hold_pin_chain_extends_past_motion_window`, `test_pin_restart_midhold_chain_readmits_without_inprocess_tier1`, `test_ble_block_skipped_when_failsafe_fired`. **T-CAP-OFF establishes byte-identity for the toggle-OFF default, which is the shipping default for every existing room without options-flow interaction — so the entire existing suite should pass unmodified.**

### D5 — Producer / Consumer map (written into the README pre-deploy)

Producer: the gated `ble_allowed` at `coordinator.py:3714-…`. Dependencies: `CONF_BLE_HOLD_CAP_ENABLED` (per-room config, verified via `_get_config`), `_became_occupied_time` (P24-maintained), `_get_ble_hold_cap_seconds()` (per-room-type dict lookup). Consumers of the changed value (`STATE_OCCUPIED` when the source would have been `"ble"` in a cap-eligible room): zone `_room_occupied` roll-up → house-state contribution → HVAC preset, load-shed gate, guest-mode gate; regime_detector / duty-cycle detector rows; in-room actuation. Direct beneficiaries are cap-ON rooms; indirect beneficiaries are their zone / house rollups.

### D6 — Doc deltas

- `docs/Coordinator/HOUSE_MANUAL.md` — one paragraph adjacent to the failsafe section noting the new independent BLE-hold-cap policy, its toggle, and its distinct duration map.
- `docs/readmes/README_v<version>.md` — pre-deploy write with the acceptance criteria + Live table (populated post-restart per the mandatory write-back rule).

---

## 6. Non-goals

- **No change to the P24 failsafe block** (`coordinator.py:4106-4235`). Leg (ii) still exempts BLE from the knock-down+latch — protects a real BLE-visible occupant on subsequent Tier-1 ticks. The cap installed by this cycle is a REFUSAL-TO-REFRESH in a different block.
- **No change to the BLE CREATE path** (`:3714-3716` remains chain-only).
- **No `_failsafe_fired` write on the cap edge.** Cap is refusal; Tier-1 re-asserts occupancy cleanly the next tick.
- **No sleep-window / house-state coupling** (dropped from Rev 1/Rev 2).
- **No `_last_mmwave_time` tracker** (dropped from Rev 2).
- **No new per-room DURATION field.** Duration lives in the module-level `BLE_HOLD_CAP_DURATIONS` map to keep the config surface parsimonious. Only the boolean toggle is per-room.
- **No preemptive change to the camera-extend leg** (`:3592-3621`) — same structural exposure but no phantom shape observed on the camera path; not carding preemptively.

---

## 7. Acceptance criteria (DISCRIMINATING, per-invariant)

### Verify (in-suite)
- T-CAP-OFF green → invariant A (byte-identity when toggle off).
- T-CAP-ON-EVICT green → invariant B (phantom shape drops).
- T-CAP-ON-SUSTAIN green → cap does not fire early.
- T-CAP-DEFAULT-DURATION green → per-room-type dict + `DEFAULT_BLE_HOLD_CAP_SECONDS` fallthrough works.
- T-CAP-RESTART green → D-MEDIUM-1 fail-open pin preserved.
- T-CAP-NM-DISTINCT green → distinct kind + distinct latch key (MED-1 + MED-2 remediated).
- T-CAP-CONFIG-DEFAULT green → invariant C (setup-time room-type default correct + explicit override respected).
- T-CAP-OPTIONS-ROUNDTRIP green → RestoreEntity / options-persistence correct.
- All five mutation anchors flip the specified test red under subprocess isolation with `.pyc` cleared.
- Existing BLE-WARM-CREATE-1 suite (chain-extend still-body, sleep-hold pin, restart pin, `_failsafe_fired` skip) all still green.

### Live (post-deploy)
| # | Criterion | How to check |
|---|---|---|
| L1 | Integration loads, zero URA errors post-restart. | HA `system_log` search. |
| L2 | **Founding case (bathroom, cap ON default):** Master Bathroom sleep-window replay MUST show `binary_sensor.master_bathroom_occupied` transition off within one polling interval of `_became_occupied_time + BLE_HOLD_CAP_DURATIONS[bathroom]`, even while `person_coordinator.get_persons_in_room("Master Bathroom")` continues to return a sleeper. ~7 h all-night hold shape MUST NOT reappear. | Recorder query on `sensor.master_bathroom_occupancy_source`, `binary_sensor.master_bathroom_occupied`, BLE-persons attribute across the sleep window; compute duration from `_became_occupied_time`. |
| L3 | **No-PIR-room non-eviction (C1-HIGH-2 discriminator).** Pick a no-PIR room from `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md:41-53` where the sleeper actually sleeps (Master Bedroom, `bedroom` type, cap defaults OFF). Recorder MUST show continuous occupancy across the same sleep window. If this room drops, the toggle-default policy is broken (this room's toggle should have been False on setup). Cross-check the entry's `.storage/core.config_entries` payload actually has `CONF_BLE_HOLD_CAP_ENABLED=False` (or absent, treated as False). | Recorder + config-entry payload. |
| L4 | **Tier-1-unprovenanced occupied-time sweep (rewritten per MED-3):** 7 days post-deploy, for every room, compute total occupied minutes where `STATE_OCCUPANCY_SOURCE ∈ {"ble","timeout"}` AND no Tier-1 sensor fired inside the last `2 × occupancy_timeout`. For cap-ON rooms, this MUST NOT exceed the room's `BLE_HOLD_CAP_DURATIONS` in any single continuous span. For cap-OFF rooms this is a diagnostic-only measurement (no assertion) but records baseline for tuning. | Recorder cross-tab per room; join `binary_sensor.<room>_occupied`, `sensor.<room>_occupancy_source`, and per-room Tier-1 sensor histories. |
| L5 | **Real-occupant preservation (cap ON, Tier-1 active):** cap-ON rooms with periodic Tier-1 firings retain occupancy across the cap duration. | Recorder sweep. Expected: source stays in {"motion","mmwave","occupancy_sensor","timeout"}; if it flips to "ble" and then drops at the cap, the primary branch isn't running when Tier-1 fires — investigate. |
| L6 | **NM diagnostic honesty (MED-1):** any BLE-cap NM in the log shows the `ble_hold_cap` kind + distinct diagnosis/remedy strings (not the PIR-stale text). Any same-day P24 knock-down NM in the same room fires INDEPENDENTLY (MED-2 remediated). | NM audit table query on `kind`. |
| L7 | **Restart mid-hold (D-MEDIUM-1 pin):** post next HA restart, BLE-held rooms re-admit on first tick regardless of prior session duration. | Recorder around next restart. |
| L8 | **Config-entry persistence:** each existing room's config entry either has `CONF_BLE_HOLD_CAP_ENABLED` set explicitly (post options-flow visit) or is absent (treated as False). Toggle survives HA restart. | `.storage/core.config_entries` read. |

Each PASS row cites the observed entity/attribute value or DB row per README write-back.

---

## 8. Tier 2-DB+ review plan (three framing-disjoint reviews + live)

- **Review A — local correctness + P24 non-interference.** Verify the toggle-OFF path is byte-identical to pre-cycle code (walk the diff and confirm no other write inside the extend region moved). Verify `_get_ble_hold_cap_seconds()` reads the per-room-type map with the correct default fallthrough. Verify the fail-open on `_became_occupied_time is None`. Verify no `_failsafe_fired` write. Verify the P24 block is unchanged. Verify the seed-if-None at `:3738-3739` still executes on cap-True admits (so first post-restart tick seeds `_became_occupied_time` and arms the cap on the SECOND tick, not the first).
- **Review B — config surface + cross-coordinator + no-flap + boundary.** Verify config-flow setup-time default application (invariant C) uses the SAME pattern as `CONF_OCCUPANCY_TIMEOUT` at `:991-996` (no ad-hoc branching). Verify options-flow uses `self._get_current(...)` mirror. Verify RestoreEntity round-trip via the existing test harness. Enumerate consumers of `STATE_OCCUPIED` when source would have been `"ble"` and confirm cap-triggered drops present as clean vacancy transitions (source falls through to whatever the primary branch decided — NOT `"failsafe"`), no flap (`_last_occupied_state=False` next tick breaks `chain_unbroken`), no interference with camera-extend or `_failsafe_fired` skip at `:3630`. Confirm behaviour at `HOME_DAY↔HOME_NIGHT` transitions is inert (the cap doesn't read house_state).
- **Review C — test authority + mutation + real-vs-mock discriminator + harness-defect regression.** Verify the source-extraction exec harness injects `_fire_ble_hold_cap_nm` and `_get_ble_hold_cap_seconds` into the exec namespace and would have failed loud (NameError) if they weren't — deliberately remove one from the injection dict in a scratch run and confirm the tests error out. Verify `_FakeSelf` gains the two new methods so no attribute access silently short-circuits. Verify mutation anchor #3 (re-homed) actually exercises the real dict lookup on a real coordinator instance (`test_v4515_closet_bathroom_failsafe.py:64-86` is the sibling pattern to mirror). Verify T-CAP-NM-DISTINCT observes both stubs' invocation histories, not just the presence of a stub. Verify no test couples to wall-clock.

**Orchestrator independent verification before ship:** re-grep for `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout` — the BLE-block site inside the gated branch MUST be the only match in the extend region. Re-grep for callers of `_fire_max_active_failsafe_nm` — MUST be exactly one (the P24 block at `:4224`; the BLE-cap does NOT reuse it). Re-grep for callers of `_fire_ble_hold_cap_nm` — MUST be exactly one (the new cap site). Re-run one mutation drill (anchor #1, force cap always on) to confirm T-CAP-OFF flips red.

**Live Validation (Review D):** post-restart, run L1–L8 against the running instance; write results into `README_v<version>.md`.

**Fresh plan-review required** — the config surface changed (new `CONF_*_ENABLED` field, new setup-time default, new options-flow round-trip). The plan-review must independently re-verify §5 D2 wiring, §1.4 institutional greps, invariant C's setup vs options provenance, and the C1-HIGH-4 harness fix.

---

## 9. Files touched (all others read-only)

- `custom_components/universal_room_automation/const.py` — three new symbols per D1.
- `custom_components/universal_room_automation/coordinator.py` — surgery at `:3714-3722` per §3.1; new helpers `_get_ble_hold_cap_seconds` (near `:629`) and `_fire_ble_hold_cap_nm` (near `:218`).
- `custom_components/universal_room_automation/config_flow.py` — setup-step default + options-flow field per D2.
- `quality/tests/test_ble_extend_not_create.py` — new T-CAP-* tests, harness-injection fixes.
- `quality/tests/test_ble_hold_cap_lookup.py` — NEW small sibling test for the real-dict duration lookup (mutation anchor #3).
- `quality/tests/test_ble_hold_cap_config_default.py` — NEW small sibling test for setup-time default + options-flow round-trip (verify existing config-flow harness first; if it covers this, extend it in-place instead).
- `docs/Coordinator/HOUSE_MANUAL.md` — one-paragraph delta per D6.
- `docs/readmes/README_v<version>.md` — pre-deploy write + Live table write-back.

Read-only during this plan (verified surfaces only): `person_coordinator.py`, `presence_coordinator.py`, `regime_detector.py`, `house_state.py`, `domain_coordinators/_stuck_signal_nm.py` (verify `kind` + `key` dedup shape only).

---

## 10. Camera-override leg — noted, out of scope

`coordinator.py:3592-3621` has the same structural exposure (source="camera" also exempt from P24 leg (ii)), but no phantom shape has been observed on the camera path (Frigate/Protect person entities time out naturally when a person leaves the frame). Not carding preemptively; if a camera-hold phantom is observed, the same opt-in-cap pattern extends trivially with `CONF_CAMERA_HOLD_CAP_ENABLED`.

---

## 11. Superseded designs (do not resurrect without new evidence)

- **Rev 1 — Lever A alone (sleep-window body-corroboration).** Coupled to `house_state`, silent outside sleep, added a new constant and `_last_mmwave_time` tracker.
- **Rev 2 — belt-and-suspenders A + B.** Added two new constants.
- **Rev 3 — blanket reuse of `_get_failsafe_duration_seconds()`.** FIX-REQUIRED. Reused the failsafe DURATION without its three guard conjuncts (Class #63); false-evicts no-PIR sleepers (C1-HIGH-2) and long-soak bathers (C1-HIGH-1); tests had exec-namespace and hollow-anchor defects (C1-HIGH-4); NM diagnostics were false (MED-1) and shared the P24 per-day latch (MED-2). All remediated in Rev 4.
