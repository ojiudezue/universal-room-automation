# PLANNING — Census Toggles → Device Switches (revised post-plan-review)

**Card:** `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1`
**Tier:** **2-DB** (three framing-disjoint reviews) — elevated per plan-review
finding. Rationale: this cycle mutates the shared
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` primitive (touched by every future
cycle that wants to avoid the parent-entry reload watchdog outage) AND adds a
cross-coordinator dispatcher signal (`SIGNAL_URA_FACE_RECOGNITION_CHANGED`)
with subscribers in two different coordinators (transit_validator + presence).
Both are exactly the "regression-prone" ingredients Tier 2-DB was coined for.
**Framings:** A = correctness + INV-1 discrimination; B = reload-suppress
integrity + signal-chain discharge completeness; C = new surfaces + test
authority (default-flip live-behavior + non-hollow reload-absence assertion).

**Date:** 2026-08-18
**Author:** ura-planner
**Prior review:** `docs/reviews/code-review/census_toggles_switches_plan_review.md`
verdict PLAN-NEEDS-FIXES — every finding is addressed in-plan below (see
`§ Review-finding disposition` at end).

**Source-of-truth recommendation:** **Option (B)** — options key remains the
store; switch reads/writes it. **NO reload on toggle.** Discharge is via
allowlist + dispatcher signal. See `§ Reload-suppress + discharge` for the
load-bearing design.

---

## SCOPE (revised)

**TWO device switches only:**

| Entity ID (LOCKED) | Friendly name | conf_key | default | icon |
|---|---|---|---|---|
| `switch.ura_presence_face_matching` | Presence Face Matching | `CONF_FACE_RECOGNITION_ENABLED` | **True** (was False) | `mdi:face-recognition` |
| `switch.ura_name_people_at_doors` | Name People at Doors | `CONF_EGRESS_IDENTITY_ENABLED` | **True** (was False) | `mdi:badge-account-horizontal` |

**`switch.ura_smart_people_counting` is PARKED for this cycle** (operator +
review MED-5). `CONF_ENHANCED_CENSUS` stays exclusively in the Camera Census
options dialog. Default remains TRUE (unchanged). Trigger to revisit: **if
`__init__.py:2253` becomes re-runnable in-place** (i.e. the setup-time
`enhanced = merged_config.get(CONF_ENHANCED_CENSUS, True)` branch is refactored
to a signal-drivable rebuild). Until then, exposing it as a switch would
silently require a full parent-entry reload — the exact hazard this cycle is
designed to avoid.

### Default-flip live-behavior note (mandatory operator call-out)

Both flags default to **False** in the current shipped code but are **unset in
the live install's `entry.options`**. Consumers read
`merged.get(KEY, DEFAULT)`. When this cycle lands, the DEFAULT in code changes
False → **True** for both flags. Because the live keys are unset, **both
features FLIP ON automatically on the first tick after deploy**. This is the
intended operator behavior:

- **`CONF_FACE_RECOGNITION_ENABLED` ⇒ True:** Face-recognition-driven identity
  validation activates on next tick in `transit_validator.py:259` and
  `presence.py:2451`. Both consumers cache at boot, so activation happens the
  moment the integration reloads for the code-deploy (which is the deploy
  itself, not this switch toggling).
- **`CONF_EGRESS_IDENTITY_ENABLED` ⇒ True:** Egress-face identity fuse
  activates immediately at every reader (`camera_census._is_egress_identity_enabled`
  is fresh-read). **L2/L3 acceptance still organic-pending (Wed real
  crossing)** — see v5.81.0 README + memory
  `feedback_cross_investigation_synthesis.md`. Default-ON means validation
  happens IN PRODUCTION, with the new device switch itself as the operator's
  live kill-switch backstop.

If the operator wants a soft-launch instead of default-ON, the code default
must stay False (would revert to prior plan). Operator has explicitly chosen
default-ON.

---

## Non-Goals (parsimony ledger — revised)

- **No new sensors.** Zero new `SensorEntity` / `BinarySensorEntity`.
- **No new attributes on existing sensors.** The v5.81.0 observability attrs
  on `PersonsEnteredTodaySensor` (`egress_face_ids_active`,
  `egress_identities_stamped`) are untouched.
- **No change to what any flag DOES.** Same consumers, same reads.
- **No per-room / per-zone scope.** Integration device only.
- **No RestoreEntity.** The config-entry `options` dict is the store.
- **No reload on toggle** (this is now load-bearing; see next section).
- **No exposure of `CONF_ENHANCED_CENSUS` as a switch.** Parked with trigger
  above.
- **No hot-swap of `__init__.py:2253`.** Separate parked cycle.

**Parsimony ledger (revised):** +2 switches / **+1 new dispatcher signal**
(`SIGNAL_URA_FACE_RECOGNITION_CHANGED`) / +2 entries in
`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` / +1 entry in
`_INTEGRATION_KEY_SIGNAL_TABLE` / +0 sensors / +0 attributes / +0 new CONF_* /
+0 new module-level tunable numbers.

---

## Institutional context verified

### RELOAD-WATCHDOG-HAZARD infrastructure (2026-08-15) — LOAD-BEARING, was missed in v1 plan

`custom_components/universal_room_automation/__init__.py:5905-5949` documents
the exact mitigation this cycle MUST hook into. Verified end-to-end:

- **Real-outage history:** 2026-06-03 and 2026-08-07 — a synchronous
  Camera-Census options save cascaded a parent-entry reload to ~40 child
  entries, ~5-min event-loop stall, supervisor watchdog restart. Memory:
  `feedback_parent_entry_reload_watchdog_hazard.md`.
- **Mitigation (2026-08-15):** `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`
  (`__init__.py:5929`) + `INTEGRATION_RELOAD_SUPPRESS_ENABLED` kill-switch
  (`:5938`) + `_INTEGRATION_KEY_SIGNAL_TABLE` per-key discharge map
  (`:5947`) + `_dispatch_integration_key_signals` (`:5952`) + the branch in
  `_async_update_listener` at `:6626-6654` that checks
  `changed_keys.issubset(...)` and, when the subset holds, calls
  `_dispatch_integration_key_signals` and RETURNS without reloading.
  Snapshot bookkeeping at `_seed_integration_last_applied_options` (`:5993`).
- **v1 allowlist seed:** `{CONF_CAMERA_PERSON_ENTITIES}` only, with the
  discharge signal `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` subscribed at
  `transit_validator.py:328`.
- **Suppress-needs-a-discharge invariant (per `feedback_suppression_needs_discharge`):**
  every key added to the allowlist MUST either be a fresh-read at every
  consumer OR be paired with a discharge signal in
  `_INTEGRATION_KEY_SIGNAL_TABLE` that ALL cached consumers subscribe to.

**Consequence for this cycle:** naive `async_update_entry(entry, options=…)`
from a switch would trigger `_async_update_listener` (`__init__.py:6434`),
diff the options, fail the subset check (because
`CONF_FACE_RECOGNITION_ENABLED` and `CONF_EGRESS_IDENTITY_ENABLED` are NOT in
the allowlist today), and fall through to the ~5-min-outage reload path at
`:6663-6675`. **This is the load-bearing correctness point the v1 plan
missed.** Correct design: add both keys to the allowlist AND wire discharge
for the cached consumer (face_recognition only; egress_identity is
live-readonly by construction).

### Existing switch + persistence patterns (REUSED)

| Pattern | Exemplar (file:line) | Applicability |
|---|---|---|
| Switch writes to `entry.options` (no explicit reload from switch) | `DomainCoordinatorsSwitch.async_turn_on/off` `switch.py:419-433` | Structural precedent for the write API, BUT it explicitly calls `async_reload` — this cycle uses the WRITE half only and relies on the allowlist branch to short-circuit the listener. Do NOT copy the `async_reload` line. |
| `merged = {**entry.data, **entry.options}` read | `switch.py:416, :488` | Reused verbatim. |
| Kill-switch semantics docstring | `MemoryNMConditioningSwitch` `switch.py:607-656` | Wording precedent. |
| Signal-driven cached-consumer refresh | `transit_validator.py:322-331` (F6 config-signal listener), `_ec_switch_factory` SIGNAL_ENERGY_COORDINATOR_READY (`switch.py:789-797`) | Precedent for the new SIGNAL_URA_FACE_RECOGNITION_CHANGED wiring. |

### Consumers of the two in-scope flags (verified)

| Flag | Consumer | Read pattern | Cache? | Refresh path needed? |
|---|---|---|---|---|
| `CONF_FACE_RECOGNITION_ENABLED` | `transit_validator.py:255-260` (async_init) | `merged.get(...)` on INTEGRATION entry | **YES** — `self._face_recognition_enabled` cached at boot; `_build_and_subscribe` (`:338-349`) does NOT re-read this flag | **YES — subscribe to new signal** |
| `CONF_FACE_RECOGNITION_ENABLED` | `presence.py:2446-2454` (`async_setup`) | merged dict | **YES** — `self._face_recognition_enabled` cached at boot; no refresh path today | **YES — subscribe to new signal** |
| `CONF_FACE_RECOGNITION_ENABLED` | `presence.py:4465` | reads `self._face_recognition_enabled` | (same cache — updated by the signal handler) | (no separate subscription) |
| `CONF_EGRESS_IDENTITY_ENABLED` | `camera_census.py:2858-2870` (`_is_egress_identity_enabled`) | fresh `merged.get(...)` per call | **NO** | **NO — allowlist entry only, no signal needed** |
| `CONF_EGRESS_IDENTITY_ENABLED` | `transit_validator.py:1094` | **indirect** — via `camera_census.register_egress_face`, which itself calls `_is_egress_identity_enabled` (the reader above). Fresh per call at the ultimate reader. (v1 plan LOW: incorrectly labeled this as a direct `merged.get`.) | NO | NO |

### Config entry that holds these options

The INTEGRATION entry — `CONF_ENTRY_TYPE == ENTRY_TYPE_INTEGRATION`.
Written by `OptionsFlow.async_step_camera_census` (`config_flow.py:2956-2978`);
now ALSO written by the two new switches.

### Prior docs / memory consulted

- `docs/planning/AUDIT_integration_options_reload_classification.md`
  (FACE_REC + ENHANCED_CENSUS classified UNSAFE for legacy reload path —
  UNAFFECTED by the new suppress branch; that classification is exactly the
  reason discharge signals are mandatory when we add them to the allowlist).
- `docs/reviews/code-review/census_toggles_switches_plan_review.md` (this
  cycle's plan-review; all findings addressed below).
- `feedback_parent_entry_reload_watchdog_hazard.md` — the real 2026-06-03 /
  2026-08-07 outages.
- `feedback_suppression_needs_discharge.md` — the mandatory pairing rule.
- `feedback_hollow_test_anchors.md` — informs the non-hollow reload-absence
  assertion (D3-AC).
- `docs/readmes/README_v5.81.0.md` + `docs/reviews/code-review/egress_face_identity_review_D_refix.md`
  — egress_identity_enabled shipped as intentionally live kill-switch,
  currently default-OFF; L2/L3 still organic-pending.
- `docs/PLANNING_v3.5.2_CYCLE_6.md` — origin of `CONF_FACE_RECOGNITION_ENABLED`.

### Code locations surveyed end-to-end

- `switch.py:1-1000` (patterns + integration-entry setup branch at `:148`).
- `config_flow.py:2940-3000` (Camera Census options step — unchanged this
  cycle).
- `camera_census.py:2850-2971` (both live readers).
- `transit_validator.py:240-350` (boot-cached read, F6 rebuild that does NOT
  re-read the flag), `:1094` (indirect egress_identity path).
- `domain_coordinators/presence.py:2440-2455` (boot-cached read).
- `__init__.py:5905-6675` (RELOAD-WATCHDOG-HAZARD infrastructure + listener).
- `domain_coordinators/signals.py` (target for the new signal constant —
  same module as `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` per house style).

---

## Reload-suppress + discharge (LOAD-BEARING DESIGN)

### Design rule

Adding a key to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` deletes the ONLY
refresh path (reload) for every boot-cached consumer of that key. Per
`feedback_suppression_needs_discharge` this is only correct if EITHER:

- (a) every consumer reads the key fresh at every use, OR
- (b) a discharge signal is added to `_INTEGRATION_KEY_SIGNAL_TABLE` AND every
  cached consumer subscribes to it AND updates its cached value on receipt.

Egress-identity ⇒ path (a). Face-recognition ⇒ path (b).

### D0 — Allowlist expansion

**File:** `custom_components/universal_room_automation/__init__.py:5929`

```
INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS: frozenset[str] = frozenset({
    CONF_CAMERA_PERSON_ENTITIES,
    CONF_FACE_RECOGNITION_ENABLED,   # cycle CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1
    CONF_EGRESS_IDENTITY_ENABLED,    # cycle CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1
})
```

**File:** `custom_components/universal_room_automation/__init__.py:5947`

```
_INTEGRATION_KEY_SIGNAL_TABLE: dict[str, tuple[str, ...]] = {
    CONF_CAMERA_PERSON_ENTITIES: (SIGNAL_URA_TRANSIT_CONFIG_CHANGED,),
    CONF_FACE_RECOGNITION_ENABLED: (SIGNAL_URA_FACE_RECOGNITION_CHANGED,),
    # CONF_EGRESS_IDENTITY_ENABLED intentionally absent — fresh-read at all
    # consumers (camera_census._is_egress_identity_enabled + indirect
    # transit_validator:1094). No cached-consumer discharge needed.
}
```

Comment in code must cite the two consumer file:line pairs for face_recognition
and explicitly note egress_identity's fresh-read basis.

### D1 — New signal constant

**File:** `custom_components/universal_room_automation/domain_coordinators/signals.py`
(same module that defines `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`).

```
SIGNAL_URA_FACE_RECOGNITION_CHANGED = "ura_face_recognition_changed"
```

Contract (docstring): fired AFTER `async_update_entry` persists a change to
`CONF_FACE_RECOGNITION_ENABLED` on the INTEGRATION entry, by either the
`PresenceFaceMatchingSwitch` (direct fire in `async_turn_on/off`) OR the
`_async_update_listener` suppress branch via
`_dispatch_integration_key_signals` (belt-and-suspenders — a same-key write
from the options-flow surface must also fire it). Payload:
`(entry_id: str, key: str)` — mirrors
`_dispatch_integration_key_signals(:5971)` call shape.

**Fire sites (two, deliberate — see D3):**

1. `switch.py` — inside `PresenceFaceMatchingSwitch.async_turn_on` and
   `async_turn_off`, AFTER `async_update_entry(...)` returns:
   `async_dispatcher_send(hass, SIGNAL_URA_FACE_RECOGNITION_CHANGED, entry.entry_id, CONF_FACE_RECOGNITION_ENABLED)`.
2. `__init__.py:5947` table entry above — fired automatically by the existing
   `_dispatch_integration_key_signals` helper when the options-flow surface
   writes the key. **Idempotent by construction** — subscribers re-read the
   same fresh value from `merged` and setattr the same bool; a double-fire
   from switch + listener is harmless (both read the SAME persisted value).

### D2 — Consumer subscriptions

Both subscriptions live where the flag is currently cached at boot.

**File:** `custom_components/universal_room_automation/transit_validator.py`
around `:255-260`:

- Add subscription in `async_init` (alongside the existing
  `SIGNAL_URA_TRANSIT_CONFIG_CHANGED` connect at `:329`):
  ```
  self._face_recog_signal_unsub = async_dispatcher_connect(
      self.hass, SIGNAL_URA_FACE_RECOGNITION_CHANGED,
      self._on_face_recognition_changed,
  )
  ```
- Handler `_on_face_recognition_changed(entry_id, key)`: re-read from the
  INTEGRATION entry (same code as `:256-260`) and update
  `self._face_recognition_enabled`. `_LOGGER.info` on transition.
- Cleanup: mirror `self._config_signal_unsub` teardown at `:823-827`.

**File:**
`custom_components/universal_room_automation/domain_coordinators/presence.py`
around `:2446-2454`:

- After the initial read that sets `self._face_recognition_enabled`, register
  a dispatcher subscription tracked via the coordinator's normal unsub list
  (mirror an existing pattern in this file — presence coordinator already
  connects dispatchers under `self._unsub_dispatchers` or equivalent; use
  whatever the file's local convention is at the time of build).
- Handler re-reads from INTEGRATION entry via the same 3-line block and
  updates `self._face_recognition_enabled`. `presence.py:4465` (the
  downstream reader) sees the fresh cache on next call.
- Restart behavior: on integration restart, the initial read at
  `:2446-2454` re-primes the cache from `entry.options` (which is
  persistent). No signal needed at boot — the boot itself IS the refresh.

### D3 — Two switch entities

**File:** `custom_components/universal_room_automation/switch.py` — extend
the `ENTRY_TYPE_INTEGRATION` branch at `:148-150` to also register the two
new switches. Both attach to the integration device
(`identifiers={(DOMAIN, "integration")}`).

Class shape (single `_IntegrationOptionsSwitch` with per-instance kwargs — no
factory function needed for 2 instances):

```
class _IntegrationOptionsSwitch(SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, hass, entry, *, conf_key, default,
                 name, entity_id_suffix, icon,
                 fire_signal: str | None):
        self.hass = hass
        self._entry = entry
        self._conf_key = conf_key
        self._default = default
        self._fire_signal = fire_signal
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{DOMAIN}_{entity_id_suffix}"
        # entity_id pinned via suggested_object_id (see note)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "integration")},
            name="Universal Room Automation",
            manufacturer="Universal Room Automation",
            model="Whole House",
            sw_version=VERSION,
        )

    @property
    def is_on(self) -> bool:
        merged = {**self._entry.data, **self._entry.options}
        return bool(merged.get(self._conf_key, self._default))

    async def async_turn_on(self, **kwargs):
        await self._write(True)

    async def async_turn_off(self, **kwargs):
        await self._write(False)

    async def _write(self, value: bool) -> None:
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._conf_key: value},
        )
        self.async_write_ha_state()
        # NB: do NOT call async_reload. The
        # INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS branch in
        # _async_update_listener short-circuits reload and dispatches
        # the discharge signal via _INTEGRATION_KEY_SIGNAL_TABLE.
        # Belt-and-suspenders: fire the discharge signal here too so a
        # subscriber that connects between the update-entry call and the
        # listener execution still sees the transition. (Idempotent: the
        # listener will fire the same signal a moment later; subscribers
        # re-read the same fresh value both times.)
        if self._fire_signal is not None:
            from homeassistant.helpers.dispatcher import async_dispatcher_send
            async_dispatcher_send(
                self.hass, self._fire_signal,
                self._entry.entry_id, self._conf_key,
            )
```

Two instances registered at `switch.py:149`:

- `_IntegrationOptionsSwitch(hass, entry, conf_key=CONF_FACE_RECOGNITION_ENABLED, default=True, name="Presence Face Matching", entity_id_suffix="presence_face_matching", icon="mdi:face-recognition", fire_signal=SIGNAL_URA_FACE_RECOGNITION_CHANGED)`
- `_IntegrationOptionsSwitch(hass, entry, conf_key=CONF_EGRESS_IDENTITY_ENABLED, default=True, name="Name People at Doors", entity_id_suffix="name_people_at_doors", icon="mdi:badge-account-horizontal", fire_signal=None)`

**Entity-id pinning:** override via `suggested_object_id` (or the equivalent
HA-supported override at add-time) to `presence_face_matching` /
`name_people_at_doors` so the auto-slug from friendly name cannot drift.

**Default-value bump — code change:** update the DEFAULT constants that back
`config_flow.py:2959` and `:2976` and every consumer's
`merged.get(KEY, DEFAULT)` call site to `True`.
`DEFAULT_EGRESS_IDENTITY_ENABLED` at `const.py:2173` flips `False` → `True`.
`CONF_FACE_RECOGNITION_ENABLED` currently has no `DEFAULT_*` constant — every
call site inlines `False`; this cycle introduces
`DEFAULT_FACE_RECOGNITION_ENABLED: Final = True` in `const.py` and updates:

- `config_flow.py:2959` — `default=self._get_current(CONF_FACE_RECOGNITION_ENABLED, DEFAULT_FACE_RECOGNITION_ENABLED)`
- `transit_validator.py:259` — `merged.get(CONF_FACE_RECOGNITION_ENABLED, DEFAULT_FACE_RECOGNITION_ENABLED)`
- `presence.py:2451` — same
- Any other `merged.get(CONF_FACE_RECOGNITION_ENABLED, False)` grep-hit — replace with the constant.

Same treatment for `CONF_EGRESS_IDENTITY_ENABLED`: `DEFAULT_EGRESS_IDENTITY_ENABLED`
already exists (`const.py:2173`) — flip its VALUE to `True`; verify every call
site imports the constant (not `False` inline).

---

## Invariant (falsifiable) — reload-free version

**INV-1:** For each of the two in-scope flags, at any observation window after
a toggle has settled, ALL of the following hold **without a parent-entry
reload occurring**:

1. `entry.options[KEY]` on the INTEGRATION entry equals the switch's `is_on`.
2. The Camera Census options-flow field's default (via `_get_current`) reflects
   the same value on next open.
3. Every consumer reads back the SAME boolean:
   - `CONF_FACE_RECOGNITION_ENABLED`: `transit_validator._face_recognition_enabled`
     AND `presence._face_recognition_enabled` — both updated by the signal
     handler within one event-loop turn after the toggle.
   - `CONF_EGRESS_IDENTITY_ENABLED`: `_is_egress_identity_enabled()` returns
     the toggled value on the next call (fresh-read).
4. No sibling entity on the integration device shows a
   `last_changed`-bump caused by an entry reload during the toggle
   (unavailable→available transition or blanket state refresh).
5. Across a real HA restart, all of the above still hold — the value survives
   because the store is `entry.options`.

**Discriminating observation** (not sufficient: only 1+2 — that would also hold
under a naive-reload design; the reviewer of any future regression must be
able to distinguish the reload-free path from the reload path):

- Point 3 is the LIVE-vs-STALE discriminator for the cached consumer. Test
  `test_face_matching_signal_refreshes_cached_consumer` asserts a
  before/after change on `transit_validator._face_recognition_enabled` when
  the switch is toggled and NO reload occurs.
- Point 4 is the RELOAD-vs-NO-RELOAD discriminator. Test
  `test_face_matching_toggle_does_not_reload_parent_entry` observes the
  suppress branch's INFO log and a sibling entity's `last_changed` — NOT via
  patching `async_reload` (v1 hollow — reviewer HIGH-3).

---

## Deliverables + Acceptance Criteria

### D0 — Allowlist + signal-table wiring
- **Verify:** `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` contains all three
  keys (existing camera_person_entities + two new).
- **Verify:** `_INTEGRATION_KEY_SIGNAL_TABLE` contains
  `CONF_FACE_RECOGNITION_ENABLED → (SIGNAL_URA_FACE_RECOGNITION_CHANGED,)`
  and NO entry for `CONF_EGRESS_IDENTITY_ENABLED`.
- **Test:** `test_allowlist_contains_new_keys` — imports and asserts set
  membership.
- **Test:** `test_options_write_of_face_recog_does_not_reload` — write only
  `CONF_FACE_RECOGNITION_ENABLED` via `async_update_entry`, assert the
  listener took the suppress branch (INFO log line "in-place apply,
  suppressing reload" present) and that `async_reload` was NOT called on
  the INTEGRATION entry (observe via sibling entity's `last_changed` not
  advancing across the write — same technique the 2026-08-15 mitigation
  cycle used).

### D1 — Signal constant + contract
- **Verify:** `SIGNAL_URA_FACE_RECOGNITION_CHANGED` exists in
  `domain_coordinators/signals.py` next to `SIGNAL_URA_TRANSIT_CONFIG_CHANGED`.
- **Test:** `test_signal_payload_shape` — fire the signal from a stub, assert
  subscribers receive `(entry_id, key)` matching the emitter contract.

### D2 — Consumer subscriptions + refresh
- **Verify:** `TransitValidator.async_init` connects
  `SIGNAL_URA_FACE_RECOGNITION_CHANGED` and stores unsub in
  `_face_recog_signal_unsub`.
- **Verify:** `PresenceCoordinator.async_setup` connects the same signal and
  tracks its unsub in the coordinator's normal dispatcher-unsub collection.
- **Test:** `test_face_matching_signal_refreshes_cached_consumer` — pre-seed
  `entry.options[CONF_FACE_RECOGNITION_ENABLED] = True`; init transit
  validator; assert `_face_recognition_enabled is True`; toggle to False
  via switch; assert `_face_recognition_enabled is False` within one
  event-loop turn, WITHOUT reloading the entry.
- **Test:** `test_face_matching_signal_refreshes_presence_cached_consumer` —
  same shape for `presence._face_recognition_enabled`, including that
  `presence.py:4465` reader observes the fresh value on next call.
- **Test:** `test_face_matching_signal_unsubscribes_on_unload` — teardown
  path clears both unsubs (Bug Class #38 — untracked-listener leak).
- **Test:** `test_face_recognition_flag_repopulates_from_options_on_restart` —
  set flag ON, simulate restart (rebuild transit validator + presence
  coordinator from the persisted entry), assert cache is True at first read
  without any signal fired.

### D3 — Two switch entities
- **Verify:** After deploy, entities exist at LOCKED entity_ids
  `switch.ura_presence_face_matching` and `switch.ura_name_people_at_doors`,
  attached to the "Universal Room Automation" integration device page.
- **Verify:** Initial `is_on` on a fresh install (empty `entry.options`)
  equals the new True default for both.
- **Test:** `test_integration_options_switch_write_back_to_options` — toggle
  each switch, assert `entry.options[KEY]` reflects the new value AND
  `is_on` reflects it.
- **Test:** `test_face_matching_toggle_does_not_reload_parent_entry`
  (non-hollow): toggle `switch.ura_presence_face_matching`; assert the
  INFO log "suppressing reload" appeared AND a chosen sibling entity's
  `last_changed` timestamp did NOT advance across the toggle window
  (sibling reload would blanket-refresh state). Do NOT patch
  `async_reload` in the switch — the test proves the suppress branch
  fired, not that we bypassed it in the switch code.
- **Test:** `test_egress_identity_toggle_does_not_reload_parent_entry` —
  same shape.
- **Test:** `test_egress_identity_toggle_takes_effect_without_signal` —
  toggle switch OFF; assert `camera_census._is_egress_identity_enabled()`
  returns False on next call (fresh-read path, no signal wired).

### D4 — Options-flow field parity (Option B correctness)
- **Verify:** Camera Census options step still renders all three original
  fields (face_rec, enhanced_census, egress_identity) with their existing
  labels. New defaults are True for face_rec + egress_identity.
- **Test:** `test_options_dialog_and_switch_agree_roundtrip` — set flag OFF
  via switch; re-render options-flow schema; assert its `default` for that
  field is False (via `_get_current`). Set ON via options-flow simulation;
  assert switch `is_on` is True.

### D5 — Restart persistence
- **Test:** `test_switch_state_survives_restart` — write non-default via
  switch; rebuild config entry from persisted store; assert `is_on` reads
  the persisted value on first call.
- **Live:** Set each switch to a non-default value; restart HA; confirm both
  retain their operator-set values on the URA integration device page.

### D6 — Default-flip live behavior (mandatory operator call-out)
- **Verify:** In the release README's Live table, add a "Default-flip
  observation" row for each flag: on first tick post-deploy, verify the
  face-recognition pipeline is active and the egress-identity fuse is
  live (see Live section).
- **Live:** After deploy + integration reload (the reload from the
  code-deploy itself, not any switch toggle):
  - Confirm `switch.ura_presence_face_matching` is ON at first read.
  - Confirm `switch.ura_name_people_at_doors` is ON at first read.
  - Confirm `transit_validator._face_recognition_enabled` is True in the
    logs / via a dev-tools template that reads the coordinator attr.
  - Confirm `camera_census._is_egress_identity_enabled()` returns True.
  - **On the next real entry crossing (Wed organic window):** watch
    `sensor.persons_entered_today.attributes.egress_identities_stamped`
    increment and last-entry attr carry the URA slug (from v5.81.0
    L2 acceptance).
  - **On the next real exit crossing:** verify NO phantom guest is
    registered (L3 acceptance still organic-pending; default-ON means we
    validate in production; the switch is the operator's live backstop
    if the exit-eviction path regresses).

---

## Numbers-get-knobs placement

The two flags ARE the knobs.

- `switch.ura_presence_face_matching`: **rung 3 (live-tunable entity)** — the
  new signal makes it genuinely live. Kill-switch semantics documented on
  the entity.
- `switch.ura_name_people_at_doors`: **rung 3 (live-tunable entity)** —
  fresh-read at all consumers by design.
- `INTEGRATION_RELOAD_SUPPRESS_ENABLED` (existing kill-switch at
  `__init__.py:5938`) is the fire-axe for the whole suppress mechanism —
  unchanged. If set False, this cycle's toggles revert to the pre-suppress
  reload path (safe fall-back — the operator gets the outage back, not a
  broken flag).

---

## Cost (corrected — v1 fabricated "~5s")

The real cost of the pre-suppress reload path is **~5 minutes of parent-entry
reload cascading to ~40 child entries, historically supervisor-watchdog
triggering** (2026-06-03, 2026-08-07). **This design avoids the reload
entirely.** The cost of a toggle in this design is approximately:

- One `async_update_entry` call (persist to HA config store).
- Two dispatcher sends (switch-side + listener-side — idempotent, see D3).
- Two subscriber callbacks (transit validator + presence) each doing one
  `merged.get(...)` and one attribute set.

Sub-millisecond, no I/O beyond the config-store write HA does anyway.

---

## Files changed

| File | Change | Approx LoC |
|---|---|---|
| `custom_components/universal_room_automation/__init__.py` | +2 keys in `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS`; +1 entry in `_INTEGRATION_KEY_SIGNAL_TABLE`; imports for the new signal + CONF_* | ~10 |
| `custom_components/universal_room_automation/domain_coordinators/signals.py` | +1 signal constant `SIGNAL_URA_FACE_RECOGNITION_CHANGED` + docstring | ~10 |
| `custom_components/universal_room_automation/switch.py` | +1 class `_IntegrationOptionsSwitch` + 2 registrations in ENTRY_TYPE_INTEGRATION branch | ~90 |
| `custom_components/universal_room_automation/transit_validator.py` | +signal subscription in `async_init`, handler, unsub cleanup | ~30 |
| `custom_components/universal_room_automation/domain_coordinators/presence.py` | +signal subscription in `async_setup`, handler (updates `_face_recognition_enabled`), unsub via existing dispatcher-unsub collection | ~30 |
| `custom_components/universal_room_automation/const.py` | +`DEFAULT_FACE_RECOGNITION_ENABLED: Final = True`; flip `DEFAULT_EGRESS_IDENTITY_ENABLED` False → True | ~4 |
| `custom_components/universal_room_automation/config_flow.py:2959` | use `DEFAULT_FACE_RECOGNITION_ENABLED` constant | ~1 |
| `quality/tests/test_census_device_switches.py` (new) | D0–D6 tests | ~350 |
| `docs/readmes/README_v<next>.md` | Standard release notes; Live table with default-flip + egress crossing rows | ~50 |

No changes to `camera_census.py` (both readers were already correct).

---

## Tier 2-DB review framings (three, parallel, framing-disjoint)

- **Reviewer A — correctness + INV-1 discrimination.** Verify both switches
  round-trip through `entry.options` and read from `merged`, not from a
  mirror. Verify the two subscribers write back into the cached attribute
  and that `presence.py:4465` sees the fresh value on next call. Verify
  INV-1 discriminating observations 3 + 4 are the ones tested — not the
  cheap 1+2 pair.
- **Reviewer B — reload-suppress + signal-chain completeness.** Verify the
  allowlist expansion pairs each new key with either fresh-read consumers
  (egress) or a discharge-signal + wired subscribers (face_rec). Trace
  every producer→consumer edge for the new signal (2 fire sites × 2
  subscribers). Verify unsub cleanup on entry unload (Bug Class #38).
  Verify the listener's snapshot bookkeeping (`_seed_integration_last_applied_options`)
  advances correctly when the new keys are the only changed set.
  Verify no double-emit hazard (switch fire + listener fire) causes
  wrong behavior — write out the trace.
- **Reviewer C — new surfaces + default-flip live safety + test authority.**
  Verify the entity_id pin holds (LOCKED names). Verify the default-flip
  effect on the live install is documented in the README and reachable via
  the Live table. Verify the reload-absence test is non-hollow (observes
  sibling `last_changed`, not a patched `async_reload`). Verify tests
  drive production code paths (subscribe via real dispatcher, not a
  handler-called-directly stub). Verify the parked
  `switch.ura_smart_people_counting` decision is captured with its
  trigger.

**Pre-review baseline tag mandatory:**
`git tag pre-review-v<version> -m "Pre-review baseline"` before applying any
review fix-ups.

---

## Review-finding disposition

| Plan-review finding | Severity | Disposition |
|---|---|---|
| 1 — naive `async_update_entry` triggers listener → parent reload; missed 2026-08-15 mitigation | CRITICAL | Fixed. D0 adds both keys to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` + wires `SIGNAL_URA_FACE_RECOGNITION_CHANGED` in `_INTEGRATION_KEY_SIGNAL_TABLE`. Institutional-context section now cites the 2026-08-15 mitigation. Suppression-needs-discharge is enforced (D1/D2 signal + subscribers). |
| 2 — fabricated "~5s" reload cost | HIGH | Fixed. `§ Cost` corrects to ~5 min + supervisor-watchdog history, and states this design avoids reload entirely (cost ≈ dispatcher send). |
| 3 — hollow "does-not-reload" test (patched `async_reload`) | HIGH | Fixed. D3 test observes suppress-branch INFO log + sibling entity `last_changed` invariant across the toggle. Signal-refresh test asserts cached consumer changed WITHOUT reload. |
| 4 — INV-1 discrimination too weak | MED | Fixed. INV-1 discriminating observations 3 (cached-consumer live change) and 4 (no sibling `last_changed` bump) added; two dedicated tests. |
| 5 — scope should drop `switch.ura_smart_people_counting` | MED | Fixed. Scope reduced to 2 switches. Parked with trigger. `CONF_ENHANCED_CENSUS` stays in options dialog. |
| 6 — `transit_validator:1094` mislabeled as direct `merged.get` | LOW | Fixed. Consumer table now labels it "indirect — via `camera_census.register_egress_face` → `_is_egress_identity_enabled` (fresh)." |

## Explicit deferrals

- Exposing `CONF_ENHANCED_CENSUS` as a device switch. Trigger:
  `__init__.py:2253` becomes re-runnable in-place.
- Live hot-swap of the `__init__.py:2253` structural branch.
- Any migration to Option (A) (switch as sole source of truth). Not
  requested; the current design's INV-1 forbids divergence between
  surfaces by construction.
