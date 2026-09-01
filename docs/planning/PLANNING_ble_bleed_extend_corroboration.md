# PLANNING — BLE-BLEED-EXTEND-SLEEP-1: opt-in per-room BLE-hold cap (read-site default, CONF_WET_ROOM schema mirror)

**Card:** `BLE-BLEED-EXTEND-SLEEP-1`
**Thread:** presence-fusion + per-room config surface
**Tier:** **2-DB+** (config surface + presence-fusion path; config-entry options round-trip — NOT RestoreEntity).
**Precedent:** BLE-WARM-CREATE-1 (v5.66.0) fixed the CREATE path; this cycle fixes the EXTEND path.
**Bug classes:** Coincidental Equality Masks a Concept Split (Class #63) — a shared duration was reused across separate policies; ALSO — Rev-4 uncovered the SAME class in production config-flow defaults: the `if CONF_* not in user_input` template at `config_flow.py:991-996` for `ROOM_TYPE_TIMEOUTS` is DEAD (voluptuous fills the Optional schema default BEFORE the step re-enters). Trust-Hierarchy Ripple — unbounded BLE-solo extend refreshes a timeout other consumers trust. Suppression Needs a Discharge — P24 leg (ii) exempts BLE from the failsafe knock-down.

> **Rev 5 (2026-09-01) — SUPERSEDES Rev 1, Rev 2, Rev 3, Rev 4. Build-ready.**
>
> Rev 4's design (per-room toggle, room-type default) is correct. Two CRITICALs on HOW the default is applied were the last blocker:
>
> **CRIT-1** — the setup-default template we were mirroring (`config_flow.py:991-996`, the `if CONF_OCCUPANCY_TIMEOUT not in user_input` block) is **dead code**. voluptuous fills the `vol.Optional(..., default=DEFAULT_OCCUPANCY_TIMEOUT)` schema slot before the step re-enters, so `not in user_input` is always False. Ground truth: `sensor.laundry_closet_occupancy_timeout_remaining` and `sensor.guest_bedroom_1_occupancy_timeout_remaining` both peak at 300.0 (the raw `DEFAULT_OCCUPANCY_TIMEOUT`), not their `ROOM_TYPE_TIMEOUTS` values (closet=120, bedroom=900). Bathrooms coincidentally read 300 because that happens to be their `ROOM_TYPE_TIMEOUTS` value too — the coincidence masked the bug. **`ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` applied through that template would never fire.**
>
> **CRIT-2** — the ~40 EXISTING rooms predate the new field; `_get_config(CONF_BLE_HOLD_CAP_ENABLED, False)` returns False for all of them, so the founding Master Bathroom case ships INERT and L2 fails. And an options-flow default of False actively PINS the wrong value if a bathroom entry is opened+saved untouched.
>
> **One fix collapses both:** apply the room-type default at the **read site** (`_get_config(..., ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(self._room_type, False))`), and mirror the **`CONF_WET_ROOM` schema-default pattern** (`config_flow.py:1909, :1927, :10520-10525`) in setup + options for the pure OVERRIDE surface. The toggle becomes an override, not a stored default; existing rooms activate immediately, no migration.
>
> This is the last revision. Read-only outside this plan doc.

---

## 1. Institutional context verified

### 1.1 The pinned root cause (unchanged)

Master Bathroom's 7.3 h BLE phantom evaded the 60-min P24 failsafe because of **leg (ii)** at `coordinator.py:4180-4182`:

```python
and data.get(STATE_OCCUPANCY_SOURCE) not in ("camera", "ble")
```

with the intent-comment at `:4120-4127`: *"a BLE chain-hold is *evidence of presence*, not a stuck sensor, and force-vacating them AND latching `_failsafe_fired` would lock the visibly-present person out of subsequent override ticks."* All the arithmetic is present (`_became_occupied_time` accumulates across BLE overrides; `_get_failsafe_duration_seconds()` returns 3600 s for `bathroom`); only leg (ii) prevents the check. The BLE chain-extend site: `ble_allowed = False` initializer at `coordinator.py:3713`; `if BLE_CHAIN_HOLD_ENABLED:` at `:3714`; `chain_unbroken = ...` at `:3715`; `ble_allowed = chain_unbroken` at `:3716`; admit at `:3719-3722`; seed-if-None at `:3738-3739`; else at `:3751`.

### 1.2 Why Rev-4's setup-default application would not have fired (CRIT-1, class #63 in the config-flow template itself)

The template at `config_flow.py:991-996`:

```python
if CONF_OCCUPANCY_TIMEOUT not in user_input:
    room_type = user_input.get(CONF_ROOM_TYPE, ROOM_TYPE_GENERIC)
    self._data[CONF_OCCUPANCY_TIMEOUT] = ROOM_TYPE_TIMEOUTS.get(
        room_type, DEFAULT_OCCUPANCY_TIMEOUT,
    )
```

is **dead**. `CONF_OCCUPANCY_TIMEOUT` is declared as a `vol.Optional(..., default=DEFAULT_OCCUPANCY_TIMEOUT)` earlier in the schema — voluptuous fills the field to `DEFAULT_OCCUPANCY_TIMEOUT` before the step's `user_input is not None` branch runs, so `not in user_input` never evaluates True. Ground truth: `sensor.laundry_closet_occupancy_timeout_remaining=300.0` and `sensor.guest_bedroom_1_occupancy_timeout_remaining=300.0` — both peak at the raw default (300), not their type-keyed `ROOM_TYPE_TIMEOUTS` values (closet=120, bedroom=900). The bathroom case masks the bug because `ROOM_TYPE_TIMEOUTS[bathroom]` also happens to be 300 (Class #63 in the wild).

Consequence for Rev 4: `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(...)` inside a mirrored `if CONF_BLE_HOLD_CAP_ENABLED not in user_input` block would ALSO be dead. Rev-4's T-CAP-CONFIG-DEFAULT was a hollow anchor — it hand-built a dict bypassing voluptuous, so it would pass in-suite while production was broken. Fixed in Rev 5 §3.2 + §5 D4.

### 1.3 Why Rev-4's stored default of False on existing rooms is wrong (CRIT-2)

The ~40 rooms already on disk have no `CONF_BLE_HOLD_CAP_ENABLED` in either `entry.data` or `entry.options`. Rev-4 `_get_config(CONF_BLE_HOLD_CAP_ENABLED, False)` returns False for all of them → the cap is inert on the founding Master Bathroom → L2 fails at ship. And a bathroom entry opened in options and saved untouched with a `default=False` schema slot would persist False, pinning the wrong policy.

**The fix is to apply the room-type default at the READ SITE:**

```python
self._get_config(
    CONF_BLE_HOLD_CAP_ENABLED,
    ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(self._room_type, False),
)
```

- Existing rooms: no key set anywhere → `_get_config` returns the room-type default. Master Bathroom becomes cap-ON immediately. Bedrooms remain cap-OFF (`bedroom` not in the default map). Zero migration.
- New rooms: same read-site fallback until the operator explicitly overrides.
- Options-flow save: the schema uses the same room-type-aware default (per §3.2), so an untouched save writes the room-type default explicitly — but even if the operator saves the field absent, the read site still resolves correctly.

### 1.4 The correct config-flow template (CONF_WET_ROOM), verified live

Grep for room-type-aware Boolean schema defaults returned `CONF_WET_ROOM`, which uses the **schema-default** approach (not the dead `if not in user_input` approach). Verified in source:

- **Setup step** (`config_flow.py:1908-1909`):
  ```python
  room_type = self._data.get(CONF_ROOM_TYPE)
  wet_default = (room_type == ROOM_TYPE_BATHROOM)
  ```
  and at `:1927`: `vol.Optional(CONF_WET_ROOM, default=wet_default): selector.BooleanSelector(),`
- **Options step** (`config_flow.py:10519-10525`):
  ```python
  room_type = self._get_current(CONF_ROOM_TYPE)
  wet_default = bool(
      self._get_current(
          CONF_WET_ROOM,
          room_type == ROOM_TYPE_BATHROOM,
      )
  )
  ```

Rev 5 mirrors this pattern for `CONF_BLE_HOLD_CAP_ENABLED` (with `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(room_type, False)` where the wet template writes `room_type == ROOM_TYPE_BATHROOM`).

### 1.5 Institutional greps for the three new symbols (unchanged from Rev 4)

- `CONF_BLE_HOLD_CAP_ENABLED` — NEW. Prior-art template: `CONF_WET_ROOM` (per §1.4) is the correct shape; the CONF_FAN_CONTROL_ENABLED / CONF_HUMIDITY_FAN_CONTROL_ENABLED family (`const.py:958,1022,1051`) is the naming shape.
- `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` — NEW. No prior art for a room-type→bool default map (`CONF_WET_ROOM` inlines the check as `room_type == ROOM_TYPE_BATHROOM`; a MAP is more explicit and supports closet). Structural sibling: `ROOM_TYPE_FAILSAFE_DURATIONS` at `const.py:1183`.
- `BLE_HOLD_CAP_DURATIONS` — NEW. Structural sibling: `ROOM_TYPE_FAILSAFE_DURATIONS`.

**REUSED:**
- `_became_occupied_time` — set `coordinator.py:3543`, seeded on BLE admit `:3738-3739`, cleared at TRUE VACANCY FINALIZE `:4249`.
- `_get_config(key, default)` — `coordinator.py:617-627` — the canonical options→data→default read; used to compute the effective toggle at cap-check time.
- `BLE_CHAIN_HOLD_ENABLED` kill-switch — `const.py:575`.
- `_fire_max_active_failsafe_nm` shape — `coordinator.py:218-239`. We do NOT reuse the function; a sibling `_fire_ble_hold_cap_nm` with `kind="ble_hold_cap"` mirrors the shape.

### 1.6 Prior docs / memories consulted
- `docs/planning/AUDIT_mmwave_only_rooms_2026-07-31.md:41-53` — six no-PIR rooms (Game Room, Jaya Bedroom, Living Room, Study A, Study B, Master Bedroom) — none are bathroom/closet, so the room-type-default-ON set never intersects the no-PIR-eviction risk.
- `docs/planning/PLANNING_ble_extend_not_create.md`, `docs/readmes/README_v5.66.0.md` — BLE-WARM-CREATE-1 D-MEDIUM-1 restart-pin.
- `docs/readmes/README_v4.5.15.md` — failsafe per-room-type lookup precedent.
- `docs/planning/AUDIT_detector_silence_and_restart_causes.md` — P24 leg (i)/(ii)/(iii) derivation.
- Memories: `feedback_coincidental_equality_masks_concept_split`, `feedback_suppression_needs_discharge`, `feedback_do_robust_fix_not_bandaid_and_card`, `feedback_hollow_test_anchors`, `feedback_mutation_verification_pycache_staleness`, `feedback_parsimonious_room_config` (per-room toggle only; durations stay module-const), `feedback_read_consumers_before_asserting_function` (the CRIT-1 dead-template diagnosis).

### 1.7 Design docs read
- `docs/Coordinator/HOUSE_MANUAL.md` §107-108 (per-room-type failsafe durations). Rev 5 requires a one-paragraph manual delta.

### 1.8 Code locations surveyed end-to-end
- `coordinator.py:3175-3226` (source assembly), `:3510-3570` (primary occupancy), `:3623-3760` (BLE chain-extend — surgery site), `:4106-4249` (P24 + TRUE VACANCY FINALIZE), `:218-247`, `:617-627`, `:629-647`.
- `config_flow.py:985-997` (dead template — documented), `:1908-1909, :1927` (CONF_WET_ROOM setup template — CORRECT), `:10519-10525` (CONF_WET_ROOM options template — CORRECT).
- `const.py:575, :958, :1022, :1051, :1177-1188`.
- `quality/tests/test_ble_extend_not_create.py` (full — extended; harness-injection fix per D4).
- `quality/tests/test_hvac_vacancy_sweep_manual_on_guard.py:373` (`HVACCoordinator.__new__(HVACCoordinator)` bare-instantiation precedent — used by the T-CAP-READ-SITE-DEFAULT harness to instantiate a real `UniversalRoomCoordinator` without triggering `async_config_entry_first_refresh`).

---

## 2. Problem statement

Master Bathroom held `STATE_OCCUPIED=True, STATE_OCCUPANCY_SOURCE="ble"` for ~7.3 h across 08-29 with no body signal — root cause per §1.1. Blast: truth corruption reaches zone roll-up → HVAC/load-shed/guest-mode; regime_detector rows.

**Non-regression contract:** no eviction of the six no-PIR-room sleepers, no eviction of a real bather on a still soak. Rev 5 satisfies both by construction: no-PIR rooms are exclusively non-bathroom/closet types (audit-verified) and default cap-OFF; bathroom cap duration is chosen long enough for real soaks (§5 D1).

---

## 3. Fix

### 3.1 Surgery — `coordinator.py:3713-3716`

Replace the `ble_allowed = False` initializer + `if BLE_CHAIN_HOLD_ENABLED: ... ble_allowed = chain_unbroken` block. Builder writes final wording; reviewer verifies against the invariant in §4.

```python
ble_allowed = False
if BLE_CHAIN_HOLD_ENABLED:
    chain_unbroken = self._last_occupied_state
    if chain_unbroken:
        # BLE-BLEED-EXTEND-SLEEP-1 (Rev 5): per-room opt-in BLE-hold cap.
        # Read-site room-type default: existing rooms (no field on disk)
        # resolve to ROOM_TYPE_BLE_HOLD_CAP_DEFAULT[room_type] with no
        # migration. Config/options surface (config_flow.py) is a pure
        # OVERRIDE with a matching schema default (CONF_WET_ROOM template).
        cap_enabled = self._get_config(
            CONF_BLE_HOLD_CAP_ENABLED,
            ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(self._room_type, False),
        )
        if not cap_enabled:
            ble_allowed = True                              # today's behavior
        elif self._became_occupied_time is None:
            ble_allowed = True                              # D-MEDIUM-1 fail-open
        else:
            duration = (now - self._became_occupied_time).total_seconds()
            cap_seconds = self._get_ble_hold_cap_seconds()
            ble_allowed = duration <= cap_seconds
            if not ble_allowed:
                self.hass.async_create_task(                # noqa: untracked-ok
                    _fire_ble_hold_cap_nm(
                        self.hass, room_name,
                        duration / 60, cap_seconds / 60,
                    ),
                )
```

**Reviewer anchors:**
- Inside `if BLE_CHAIN_HOLD_ENABLED:` — top-level kill preserved.
- `_get_config(...)` (`coordinator.py:617-627`) with room-type-default fallback resolves existing rooms + new rooms + explicit overrides uniformly.
- `_became_occupied_time is None` → admit (D-MEDIUM-1 pin).
- Rejection path falls through to the existing `else` at `:3751` — `data[STATE_BLE_PERSONS]` still populated for diagnostics.
- `ble_allowed=False` → next tick `_last_occupied_state=False` → `chain_unbroken=False` → cap self-arms via chain break.
- **No `_failsafe_fired` write.** Cap is refusal-to-refresh; Tier-1 fire re-asserts occupancy cleanly.
- **P24 block byte-preserved** at `:4106-4235`.

### 3.2 Config-flow + options-flow (CONF_WET_ROOM schema-default template)

Drop any `if CONF_* not in user_input` mirror (the `:991-996` template is dead — §1.2). Use schema-default:

- **Setup** (adjacent to `CONF_WET_ROOM` block starting at `:1908`):
  ```python
  room_type = self._data.get(CONF_ROOM_TYPE)
  ble_cap_default = ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(room_type, False)
  # ...
  vol.Optional(
      CONF_BLE_HOLD_CAP_ENABLED, default=ble_cap_default,
  ): selector.BooleanSelector(),
  ```
- **Options** (adjacent to `CONF_WET_ROOM` options block at `:10519`):
  ```python
  room_type = self._get_current(CONF_ROOM_TYPE)
  ble_cap_default = bool(
      self._get_current(
          CONF_BLE_HOLD_CAP_ENABLED,
          ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(room_type, False),
      )
  )
  # ...
  vol.Optional(
      CONF_BLE_HOLD_CAP_ENABLED, default=ble_cap_default,
  ): selector.BooleanSelector(),
  ```

An untouched save writes the room-type default explicitly; the READ SITE remains the source of truth because it uses the same fallback.

### 3.3 Freshness — DECIDED (no conjunct)

The cap has NO PIR-freshness conjunct. Operator brief: "long cap" substitutes for freshness. No-PIR rooms are protected by the toggle defaulting OFF for their room types. Too-short cap self-heals on any next Tier-1 fire (primary branch re-occupies). See §11 for the rejected alternative.

### 3.4 NM `kind` — DECIDED (`ble_hold_cap`)

New helper `_fire_ble_hold_cap_nm(hass, room_name, minutes, limit_min)` — sibling of `_fire_max_active_failsafe_nm` at `:218-239`, `kind="ble_hold_cap"`, distinct diagnosis (*"room {name}: BLE-hold cap fired after {minutes:.0f} min ({limit_min:.0f} min limit) — pure-BLE-source hold ended without body-signal corroboration"*), distinct remedy (*"if the room is expected to hold BLE-only presence for longer periods (e.g. still bather), raise `BLE_HOLD_CAP_DURATIONS` or set `CONF_BLE_HOLD_CAP_ENABLED=False` in options; if this fires while the room is empty, investigate adjacent-room BLE bleed (scanner topology)"*), `title_override` carrying room + duration for audit-row attributability (preserves the P24 diagnosability pattern). Per-day latch is keyed on `(kind, room_name)`, so BLE-cap fires do NOT suppress a same-day P24 knock-down NM on the same room. See §11 for the rejected shared-kind alternative.

---

## 4. Falsifiable invariant

Let `E := self._get_config(CONF_BLE_HOLD_CAP_ENABLED, ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(self._room_type, False))`.

**(A) When `E == False`:** the BLE chain-extend leg's refresh behavior is byte-identical to pre-cycle code (`ble_allowed = chain_unbroken`).

**(B) When `E == True`:** the leg MUST NOT refresh `STATE_TIMEOUT_REMAINING` when `(now - self._became_occupied_time) > _get_ble_hold_cap_seconds()`. Restart mid-hold with `_became_occupied_time is None` fails OPEN (admit). A room with any Tier-1 sensor firing this tick is NEVER evaluated by the cap (primary branch owns the tick).

**(C) READ-SITE DEFAULT resolves correctly.** For an existing room whose config entry has NO `CONF_BLE_HOLD_CAP_ENABLED` key in either `entry.data` or `entry.options`, `E == ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(self._room_type, False)`. This must be observable at read time without any migration or options-flow visit. Corollary: on the shipping fleet, all bathroom + closet rooms present as cap-ON on the first tick post-restart; all other room types (including the six no-PIR rooms) present as cap-OFF.

**(D) SCHEMA DEFAULT** mirrors the CONF_WET_ROOM template — the schema `default=` slot for `CONF_BLE_HOLD_CAP_ENABLED` in setup AND options resolves to `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(room_type, False)`. Not the dead `if CONF_* not in user_input` template.

**Falsifiers:**
- **A:** toggle OFF sensor-trace replay differs from pre-cycle baseline in the BLE-extend `STATE_TIMEOUT_REMAINING` writes.
- **B (phantom):** 08-29 Master Bath replay does NOT drop within one polling interval after `_became_occupied_time + cap_seconds`.
- **B (real-bather):** cap-ON room with periodic Tier-1 fires drops at cap.
- **C:** any existing bathroom entry reads `E == False` at first tick post-restart; any existing bedroom/study/media/common-area entry reads `E == True`.
- **D:** the config-flow schema shows the wrong default for a chosen room_type when the form is presented (bathroom shows unchecked; bedroom shows checked).

---

## 5. Deliverables

### D1 — Constants (`const.py`)

```python
CONF_BLE_HOLD_CAP_ENABLED: Final = "ble_hold_cap_enabled"

# Room-type default resolved AT READ SITE (coordinator._get_config
# fallback) AND at schema-default slot (config_flow + options, using
# the CONF_WET_ROOM template, NOT the dead :991-996 if-not-in-user_input
# template). Existing rooms activate immediately without migration.
ROOM_TYPE_BLE_HOLD_CAP_DEFAULT: Final = {
    ROOM_TYPE_BATHROOM: True,
    ROOM_TYPE_CLOSET:   True,
    # bedroom / common area / study / media / garage / utility / generic
    # / infrastructure: default False (protects no-PIR sleepers per
    # AUDIT_mmwave_only_rooms_2026-07-31.md:41-53).
}

# Per-room-type cap duration. DECOUPLED from ROOM_TYPE_FAILSAFE_DURATIONS
# (Class #63 defense — separate policy shapes).
DEFAULT_BLE_HOLD_CAP_SECONDS: Final = 2 * 3600  # 120 min
BLE_HOLD_CAP_DURATIONS: Final = {
    ROOM_TYPE_BATHROOM: 2 * 3600,   # 120 min
    ROOM_TYPE_CLOSET:   2 * 3600,   # 120 min
    # Other room types fall through to DEFAULT_BLE_HOLD_CAP_SECONDS
    # if a future operator opts the toggle ON for them.
}
```

**Duration policy — 120 min for bathroom, closet, and default (operator-decided).** A phantom is bounded to ~120 min instead of the observed 7.3 h (~73% reduction of the observed excess). A too-short cap self-heals on any next Tier-1 fire (primary branch re-occupies) — the harm is a transient off during perfect stillness, not a lockout. Uniform 120 min keeps the mental model simple and gives real bathers headroom.

**Rung** (per `feedback_numbers_get_knobs`): toggle at the config/options rung (per-room, operator-settable); durations at the module rung (change-requires-review — per-room dial would balloon config per `feedback_parsimonious_room_config`).

### D2 — Config-flow + options-flow (`config_flow.py`)

- Setup: room-type-aware schema-default per §3.2, adjacent to the `CONF_WET_ROOM` block at `:1908-1927`.
- Options: schema-default with `self._get_current(...)` fallback to the same room-type default, adjacent to the `CONF_WET_ROOM` options block at `:10519-10525`.
- **Do NOT add an `if CONF_BLE_HOLD_CAP_ENABLED not in user_input` block** (that template is dead — §1.2).

### D3 — Coordinator surgery (`coordinator.py`)

- Add `_get_ble_hold_cap_seconds(self) -> int` — structural mirror of `_get_failsafe_duration_seconds` at `:629-647`:
  ```python
  def _get_ble_hold_cap_seconds(self) -> int:
      from .const import (
          BLE_HOLD_CAP_DURATIONS, DEFAULT_BLE_HOLD_CAP_SECONDS,
      )
      return BLE_HOLD_CAP_DURATIONS.get(
          self._room_type, DEFAULT_BLE_HOLD_CAP_SECONDS,
      )
  ```
- Add `_fire_ble_hold_cap_nm(hass, room_name, minutes, limit_min)` — sibling of `_fire_max_active_failsafe_nm` per §3.4.
- Replace the block at `:3713-3716` per §3.1 sketch.

### D4 — Test authority additions (`quality/tests/test_ble_extend_not_create.py` + siblings)

**Harness fixes (C1-HIGH-4 remediated):**
- The source-extraction exec must inject `_fire_ble_hold_cap_nm` AND `_get_ble_hold_cap_seconds` AND the read-site fallback (`CONF_BLE_HOLD_CAP_ENABLED`, `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT`) into the exec namespace. Deliberately omit one in a scratch run to confirm the tests error out (proves the injection is load-bearing).
- Extend `_FakeSelf` (`:110-`) with `_get_ble_hold_cap_seconds()` returning a fixture-injected seconds value AND a `_get_config` that returns fixture-injected bools per key.

**New tests (durations in `_get_ble_hold_cap_seconds` are INJECTED — the literal 5400 / 7200 / etc. is arbitrary, chosen for test speed, and the const-value assertion below anchors the production number separately):**

- **T-CAP-OFF (invariant A):** cap OFF, session `_became_occupied_time = now - 10 h`, BLE continuous, no Tier-1 → admit. Byte-identity vs pre-cycle.
- **T-CAP-ON-EVICT (invariant B, phantom replay):** `room_type="bathroom"`, cap ON, injected `_get_ble_hold_cap_seconds` returns e.g. 5400 (test-injected — literal arbitrary), `_became_occupied_time = now - (5400+1)`, BLE continuous, no Tier-1 → reject. Next tick with `_last_occupied_state=False` also rejects.
- **T-CAP-ON-SUSTAIN (invariant B, just-under):** same setup, `_became_occupied_time = now - (5400-1)` → admit.
- **T-CAP-DEFAULT-DURATION (per-room-type fallthrough):** `room_type="bedroom"`, cap ON (test-forced), no bedroom entry in `BLE_HOLD_CAP_DURATIONS` → helper returns `DEFAULT_BLE_HOLD_CAP_SECONDS`. Past → reject; under → admit.
- **T-CAP-RESTART (D-MEDIUM-1 pin):** cap ON, `_became_occupied_time is None`, `chain_unbroken=True`, BLE present → admit; seed at `:3738-3739` populates `_became_occupied_time = now`.
- **T-CAP-NM-DISTINCT (two-path observation, replaces hollow anchor):** on the T-CAP-ON-EVICT edge, capture both NM stubs' call histories (`_fire_ble_hold_cap_nm` AND `_fire_max_active_failsafe_nm`). Assert only `_fire_ble_hold_cap_nm` was invoked and its args carry room+minutes+limit; then orchestrate a separate P24-knock-down of the same room the same day (via the `_fire_max_active_failsafe_nm` stub) and assert distinct latch keys (`(kind, room_name)`) — no suppression collision.
- **T-CAP-READ-SITE-DEFAULT (invariant C, real-coordinator unit test — NEW SIBLING FILE `quality/tests/test_ble_hold_cap_read_site_default.py`).** **Precedent (corrected):** the previously-cited `test_v4515_closet_bathroom_failsafe.py:64-86` block is `_load_const_dict()` — an importlib `spec_from_file_location` const-loader that instantiates NO coordinator (Bug Class #62 — a hollow-anchor shape, exactly what Rev 5 repudiates). It cannot exercise `_get_config` (which reads `self.entry.data` / `self.entry.options`) and would force a fallback to a `_FakeSelf`, reproducing the Rev-4 CRIT-2 hollow anchor. **Use `test_hvac_vacancy_sweep_manual_on_guard.py:373` as the real-coordinator instantiation precedent** — `HVACCoordinator.__new__(HVACCoordinator)` bare-alloc, then hand-populate the minimum attribute surface a method-under-test reads. Mirror it here:
  ```python
  # Real coordinator, no async_config_entry_first_refresh cost.
  coord = UniversalRoomCoordinator.__new__(UniversalRoomCoordinator)
  coord.entry = _StubEntry(data={}, options={})  # existing-room case
  coord._room_type = ROOM_TYPE_BATHROOM
  # Real _get_config method (from coordinator.py:617-627) reads
  # entry.options → entry.data → default fallback.
  assert coord._get_config(
      CONF_BLE_HOLD_CAP_ENABLED,
      ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(coord._room_type, False),
  ) is True
  ```
  Repeat with `_room_type = ROOM_TYPE_BEDROOM` (data={}, options={}) → assert False. Repeat with `_room_type = ROOM_TYPE_BATHROOM` and `entry.options = {CONF_BLE_HOLD_CAP_ENABLED: False}` → assert False (explicit override respected). The assertion MUST call `coord._get_config(...)` on the real coordinator — a `_FakeSelf` here fails Review C.
- **T-CAP-SCHEMA-DEFAULT (invariant D — sibling file `quality/tests/test_ble_hold_cap_schema_default.py`):** DRIVE THE VOLUPTUOUS SCHEMA to prove the schema-default actually reaches production, not a hand-built dict. Construct the setup step's `data_schema` with `self._data[CONF_ROOM_TYPE] = ROOM_TYPE_BATHROOM` and assert `data_schema({})[CONF_BLE_HOLD_CAP_ENABLED] is True`; with `ROOM_TYPE_BEDROOM` assert False. Repeat for the options-flow schema using the `self._get_current(...)` fallback. Additionally validate the OLD template's deadness: hand-build a fake step where `CONF_BLE_HOLD_CAP_ENABLED` is `vol.Optional(..., default=False)` and call `if CONF_BLE_HOLD_CAP_ENABLED not in user_input` — assert the branch is never taken (regression pin against the dead-template class of bug — one anchor is enough).
- **T-CAP-OPTIONS-ROUNDTRIP (config-entry, NOT RestoreEntity):** existing entry with cap ON, opened in options and saved untouched → entry.options gets `CONF_BLE_HOLD_CAP_ENABLED=True` explicitly (schema-default wrote it). Toggled False and saved → coordinator's next `_get_config` read returns False. HA restart (config-entry reload) preserves the value.
- **T-CAP-DURATION-CONST (real-dict anchor for mutation anchor #3):** `assert BLE_HOLD_CAP_DURATIONS[ROOM_TYPE_BATHROOM] == 7200` and `assert BLE_HOLD_CAP_DURATIONS[ROOM_TYPE_CLOSET] == 7200` and `assert DEFAULT_BLE_HOLD_CAP_SECONDS == 7200`. Real dict, no `_FakeSelf`.

**Mutation anchors (subprocess-isolated with `.pyc` cleared per `feedback_mutation_verification_pycache_staleness`):**
1. Mutate the read-site default fallback to `False` (drop the `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(...)` argument) → T-CAP-READ-SITE-DEFAULT bathroom-True assertion MUST go red.
2. Mutate the schema `default=ble_cap_default` to `default=False` (setup step) → T-CAP-SCHEMA-DEFAULT setup bathroom assertion MUST go red.
3. Mutate `BLE_HOLD_CAP_DURATIONS[ROOM_TYPE_BATHROOM]` to a different value → T-CAP-DURATION-CONST MUST go red (real-dict anchor, no `_FakeSelf` masking).
4. Mutate the duration comparator to always False (`ble_allowed = False` when cap ON) → T-CAP-ON-SUSTAIN MUST go red.
5. Mutate the `_fire_ble_hold_cap_nm` call to a no-op → T-CAP-NM-DISTINCT MUST go red.

**Regression pins (unchanged, MUST stay green):** `test_extend_path_ble_holds_still_body_when_chain_unbroken`, `test_sleep_hold_pin_chain_extends_past_motion_window`, `test_pin_restart_midhold_chain_readmits_without_inprocess_tier1`, `test_ble_block_skipped_when_failsafe_fired`.

### D5 — Producer / Consumer map (README pre-deploy)

**Producer:** the gated `ble_allowed` at `coordinator.py:3713-…`. Dependencies: read-site `_get_config` with room-type default (`CONF_BLE_HOLD_CAP_ENABLED` per-room override + `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT` type default), `_became_occupied_time` (P24-maintained), `_get_ble_hold_cap_seconds()`. **Consumers of `STATE_OCCUPIED` when source would have been `"ble"`:** zone `_room_occupied` roll-up → house-state contribution → HVAC preset selection, load-shed gates, guest-mode gates; regime_detector / duty-cycle detector rows; in-room actuation. Direct beneficiaries: cap-ON rooms; indirect: their zone/house rollups.

### D6 — Doc deltas
- `docs/Coordinator/HOUSE_MANUAL.md` — one paragraph adjacent to the failsafe section documenting the BLE-hold cap, its toggle, its distinct duration map, and its distinctness from P24.
- `docs/readmes/README_v<version>.md` — pre-deploy write + Live-table write-back per the mandatory rule.

---

## 6. Non-goals

- P24 failsafe block byte-preserved (`coordinator.py:4106-4235`).
- BLE CREATE path unchanged (`:3714-3716` remains chain-only).
- No `_failsafe_fired` write on cap edge.
- No sleep/house-state coupling.
- No `_last_mmwave_time` tracker.
- No per-room DURATION field (module-const only).
- No camera-extend leg change (`:3592-3621` — no phantom shape observed).
- **Not migrating existing config entries.** Read-site default handles them.

---

## 7. Acceptance criteria (DISCRIMINATING)

### Verify (in-suite)
All T-CAP-* tests green. All five mutation anchors flip the specified test red under subprocess isolation with `.pyc` cleared. Existing BLE-WARM-CREATE-1 suite green.

### Live (post-deploy)
| # | Criterion | How to check |
|---|---|---|
| L1 | Integration loads, zero URA errors post-restart. | HA `system_log` search. |
| L2 | **Founding case (Master Bathroom, cap ON via read-site default — no options visit).** Recorder MUST show `binary_sensor.master_bathroom_occupied` transition off within one polling interval of `_became_occupied_time + BLE_HOLD_CAP_DURATIONS[bathroom]` while `person_coordinator.get_persons_in_room("Master Bathroom")` continues to return a sleeper. ~7 h all-night hold shape MUST NOT reappear. **Cross-check:** the room's config entry has NO `CONF_BLE_HOLD_CAP_ENABLED` key in `entry.data` or `entry.options` — the read-site default fired. | Recorder + `.storage/core.config_entries`. |
| L3 | **No-PIR-room non-eviction discriminator.** Master Bedroom (no PIR, `bedroom` type → cap defaults OFF at read site). Recorder MUST show continuous occupancy across the same sleep window. **Cross-check:** entry has no `CONF_BLE_HOLD_CAP_ENABLED` and coordinator's runtime `_get_config` returns False (bedroom not in the default map). If Master Bedroom drops, the read-site default policy is broken. | Recorder + config entry + coordinator introspection. |
| L4 | **Tier-1-unprovenanced occupied-time sweep.** 7 days post-deploy, per room, total occupied minutes where `STATE_OCCUPANCY_SOURCE ∈ {"ble","timeout"}` AND no Tier-1 sensor fired inside the last `2 × occupancy_timeout`. For cap-ON rooms this MUST NOT exceed the room's `BLE_HOLD_CAP_DURATIONS` in any single continuous span. Cap-OFF rooms: diagnostic-only baseline. | Recorder cross-tab. |
| L5 | **Real-occupant preservation (cap ON, Tier-1 active).** Cap-ON rooms with periodic Tier-1 firings retain occupancy across the cap duration; source stays in {"motion","mmwave","occupancy_sensor","timeout"}. | Recorder sweep. |
| L6 | **NM diagnostic honesty.** Any BLE-cap NM shows `kind=ble_hold_cap` with distinct diagnosis/remedy (NOT the PIR-stale text). Any same-day P24 knock-down NM in the same room fires INDEPENDENTLY. | NM audit table on `kind`. |
| L7 | **Restart mid-hold** (D-MEDIUM-1 pin). Post next HA restart, BLE-held rooms re-admit on first tick. | Recorder around next restart. |
| L8 | **Config-entry options round-trip** (config-entry storage, NOT RestoreEntity). For a bathroom whose options are opened and saved untouched, `entry.options[CONF_BLE_HOLD_CAP_ENABLED]` is written True by the schema-default. For a bathroom whose options were saved False before deploy, `entry.options[CONF_BLE_HOLD_CAP_ENABLED]` remains False after restart (explicit override respected). | `.storage/core.config_entries`. |

Each PASS row cites the observed entity/attribute value or DB row per README write-back.

---

## 8. Tier 2-DB+ review plan — BUILD-READY

**Design cleared** (Rev 5 confirm-review: CRIT-1, CRIT-2, and the HIGH on the T-CAP-READ-SITE-DEFAULT precedent all resolved). Remaining risk lives in the build, not the design. No further plan-review required.

- **Review A — local correctness + P24 non-interference + read-site default.** Verify toggle-OFF is byte-identical to pre-cycle code. Verify `_get_ble_hold_cap_seconds()` reads the per-room-type map with the correct default fallthrough. Verify fail-open on `_became_occupied_time is None`. No `_failsafe_fired` write. P24 block unchanged. **Verify the READ-SITE FALLBACK is passed to `_get_config` on EVERY invocation** — a bare `_get_config(CONF_BLE_HOLD_CAP_ENABLED, False)` slip would silently regress every existing room to cap-OFF (CRIT-2 shape).
- **Review B — config surface + cross-coordinator + no-flap + boundary (config-entry storage, NOT RestoreEntity).** Verify setup + options both use the CONF_WET_ROOM schema-default template (`:1909, :1927, :10520-10525`), not the dead `:991-996` template. Verify config-entry options round-trip: coordinator's next `_get_config` read reflects the saved value. Enumerate `STATE_OCCUPIED` / source=`ble` consumers; confirm cap-triggered drops present as clean vacancy transitions, no flap (chain-break-next-tick), no camera-extend or `_failsafe_fired` skip interference. **Do NOT frame this as RestoreEntity** — the value lives in `entry.options`/`entry.data`, read via `_get_config`.
- **Review C — test authority + mutation + real-vs-mock discriminator + schema-driven anchor.** Verify T-CAP-SCHEMA-DEFAULT actually invokes voluptuous (`data_schema({})`), not a hand-built dict — a hand-built assertion is exactly what CRIT-1 says is a hollow anchor. **Verify T-CAP-READ-SITE-DEFAULT instantiates a REAL coordinator via the `UniversalRoomCoordinator.__new__` pattern (mirror `test_hvac_vacancy_sweep_manual_on_guard.py:373`) and asserts through the real `coord._get_config(...)` method — a `_FakeSelf` at this test point is an automatic Review-C fail** (that was the exact hollow-anchor shape the previously-cited `test_v4515_closet_bathroom_failsafe.py:64-86` const-loader would have forced). Verify all five mutation anchors flip the specified test red under subprocess isolation with `.pyc` cleared. Verify no test couples to wall-clock. Verify `_FakeSelf` gains both new methods so no attribute access silently short-circuits in the tests that DO use it (T-CAP-OFF / T-CAP-ON-EVICT / T-CAP-ON-SUSTAIN / T-CAP-DEFAULT-DURATION / T-CAP-RESTART / T-CAP-NM-DISTINCT).

**Orchestrator independent verification before ship:** grep `data[STATE_TIMEOUT_REMAINING] = self._occupancy_timeout` — the BLE-block site inside the gated branch is the only match in the extend region. Grep callers of `_fire_max_active_failsafe_nm` — exactly one (P24 block at `:4224`). Grep callers of `_fire_ble_hold_cap_nm` — exactly one (new cap site). Grep `_get_config(CONF_BLE_HOLD_CAP_ENABLED` — exactly one, and it MUST pass the `ROOM_TYPE_BLE_HOLD_CAP_DEFAULT.get(...)` fallback (regex-check for the identifier in the second argument). Re-run mutation anchor #1 by hand.

**Live Validation (Review D):** post-restart, run L1-L8; write results into `README_v<version>.md`.

---

## 9. Files touched

- `custom_components/universal_room_automation/const.py` — three new symbols per D1.
- `custom_components/universal_room_automation/coordinator.py` — surgery at `:3713-3716`; new helpers `_get_ble_hold_cap_seconds` (near `:629`) and `_fire_ble_hold_cap_nm` (near `:218`).
- `custom_components/universal_room_automation/config_flow.py` — setup + options schema-default per §3.2 (CONF_WET_ROOM template).
- `quality/tests/test_ble_extend_not_create.py` — new T-CAP-OFF, T-CAP-ON-EVICT, T-CAP-ON-SUSTAIN, T-CAP-DEFAULT-DURATION, T-CAP-RESTART, T-CAP-NM-DISTINCT; harness-injection fixes.
- `quality/tests/test_ble_hold_cap_read_site_default.py` — NEW sibling. Real-coordinator T-CAP-READ-SITE-DEFAULT via `UniversalRoomCoordinator.__new__` (`test_hvac_vacancy_sweep_manual_on_guard.py:373` precedent). Also carries T-CAP-DURATION-CONST.
- `quality/tests/test_ble_hold_cap_schema_default.py` — NEW sibling, voluptuous-driven T-CAP-SCHEMA-DEFAULT + dead-template regression pin.
- `quality/tests/test_ble_hold_cap_options_roundtrip.py` — NEW sibling (or extend existing config-entry test harness if grep finds one) — T-CAP-OPTIONS-ROUNDTRIP.
- `docs/Coordinator/HOUSE_MANUAL.md` — one-paragraph delta per D6.
- `docs/readmes/README_v<version>.md` — pre-deploy write + Live-table write-back.

Read-only during this plan: `person_coordinator.py`, `presence_coordinator.py`, `regime_detector.py`, `house_state.py`, `domain_coordinators/_stuck_signal_nm.py` (verify `(kind, key)` dedup shape only).

---

## 10. Camera-override leg — noted, out of scope

`coordinator.py:3592-3621` has the same structural exposure (source="camera" also exempt from P24 leg (ii)); no phantom shape observed on that path. If observed later, the same opt-in-cap pattern extends trivially.

---

## 11. Superseded designs / rejected alternatives

- **Rev 1** — sleep-window body-corroboration alone.
- **Rev 2** — belt-and-suspenders A + B.
- **Rev 3** — blanket reuse of `_get_failsafe_duration_seconds()` (false-evicts no-PIR sleepers + long-soak bathers; test harness defects).
- **Rev 4** — per-room toggle + room-type default via the `if CONF_* not in user_input` template — **dead in production** (CRIT-1); stored default False strands existing rooms (CRIT-2).
- **T-CAP-READ-SITE-DEFAULT via `test_v4515_closet_bathroom_failsafe.py:64-86` precedent** — rejected. That block is `_load_const_dict()`, an importlib const-loader with NO coordinator (Bug Class #62 hollow-anchor shape); builder would fall back to `_FakeSelf` and reproduce Rev-4 CRIT-2. Correct precedent is the `UniversalRoomCoordinator.__new__` pattern mirrored from `test_hvac_vacancy_sweep_manual_on_guard.py:373`.
- **Freshness Option F2** (leg-(iii)-style PIR-freshness spare inside the cap): rejected — operator brief is "long cap," no-PIR rooms already default OFF; F2 adds a second predicate + test branch for no measurable gain.
- **NM Option N2** (shared `kind="max_active_failsafe"` latch): rejected — misleading diagnostics (MED-1) + per-day suppression collision with P24 (MED-2).
