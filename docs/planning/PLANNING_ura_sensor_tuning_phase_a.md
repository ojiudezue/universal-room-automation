# PLANNING — URA-SENSOR-TUNING-1 Phase A (Rev 2, SMALL scope)

**Card:** `URA-SENSOR-TUNING-1` (`docs/planning/kanban.data.yaml:30909`)
**Tier:** 2 (feature cycle; new options surface + one service writer; no autonomous
reasserter, no new sensor, no new switch). Plan review required before build dispatch.
**Scope:** Phase A Rev 2 — a per-room **"Radar settings"** options block for Hobeian ZK/ZX
presence radars only, defaulting "Leave as is", that **sends** values on operator save
(and on operator-pressed re-apply). **Non-goal:** autonomous drift reconciliation; Phase B
dynamic fan-aware tuning.
**Date:** 2026-10-11 (Rev 2)
**Author:** ura-planner (orchestrator)
**Deliverable form:** docs only, no commit; after plan review the build dispatches on a
feature branch.

---

## Rev 2 changelog (what collapsed vs Rev 1)

Driven by the Rev 1 plan-review (§Plan review 2026-10-11, kept verbatim at bottom) and
the measurement probe at `scratchpad/radar_probe.md`. Both are load-bearing for Rev 2.

- **Dropped:** autonomous `RadarTuningReconciler`, listener-driven drift re-assert,
  exponential backoff schedule, 24h/entity/field rate cap, wake-gating,
  flap-counter/quarantine + K/W Numbers, `button.<room>_release_tuning_flap`,
  `switch.ura_sensor_tuning_enabled` kill switch, per-room `sensor.<room>_tuning_status`,
  house-wide `sensor.ura_tuning_status` roll-up, boot-time drift check with 10-minute
  debounce, "never-desensitised" guard.
- **Collapsed:** family coverage from 6+ families to one (`zigbee_zk_zx` — the only token
  that actually exists per `sensor_capability.py:378-405` and the only family the probe
  measured). LD2410, Meross MS600, Screek, Tuya TS0601, ZV: all out-of-scope with reasons
  (§Out of scope).
- **Renamed:** semantic label from "applied" → **"sent"**. The HA `number.*` state is
  Z2M's last-write cache (probe Q2–Q3), never a device read-back, so URA cannot truthfully
  say "applied" or "verified" from HA state alone. URA records WHAT IT SENT.
- **Changed invariant:** from "live equals target forever" to **"URA only sends values the
  operator set in URA; URA never writes at boot; URA never writes to unmanaged fields."**
  Drift is undetectable through the HA number entity, so the invariant is defined on the
  SEND path only.
- **Added:** explicit Wigton pre-req note — Wigton radars are not in URA rooms yet; filing
  them into `presence_sensors` and reading their models through the device registry is a
  runbook prerequisite, not a deliverable of this plan (per review Finding 2).
- **Corrected prior art:** no `number.set_value` service-call precedent exists in URA
  today (grep of `custom_components/` finds only entity-side `async_set_value` in
  `time.py`); this is a BUILD. `BOOT_SETTLE_MIN_INPUTS` is a census-count gate
  (`const.py:3811`, `presence.py:5707`) and is irrelevant here; Rev 2 does not reference
  it.

---

## Pre-flight — docs read COMPLETELY

Read end-to-end in this planning session:

- `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` — the §10 corrections ledger
  (incl. `CONF_MMWAVE_SENSORS = "presence_sensors"`, no `CONF_PRESENCE_SENSORS`; capability
  routed through `sensor_capability.py`) and the Gold patterns index.
- `docs/architecture/SENSOR_FLEET_CLASSES.md` — Hobeian ZV/ZK/ZX family definitions and
  counts, ZV motion-class (no radar knobs), do-not-use list, Meross MS600 dual-homed
  note, ESPHome LD2410 family note, combined-sensor rule (corrected 2026-10-11).

Memory bodies pulled: `feedback_label_style_guide` (≤3-word HA entity names, no nerd
words); `feedback_configurability_clarity` (named-bucket dropdowns + one-sentence
consequence text, set-once knobs in options flow, not runtime Numbers);
`feedback_parsimonious_room_config` (don't expose every internal timing constant; prune
entity clutter); `feedback_marginal_benefit_pushback` (compare margins vs the simplest
version; price ingredient risk); `feedback_config_first_before_code` (check live knob
values first).

Probe read: `scratchpad/radar_probe.md` — the three live findings that drive Rev 2
(§Measurement findings).

---

## Measurement findings (probe, 2026-10-11)

Three facts from `scratchpad/radar_probe.md`. Rev 2 is built on them; none are speculative.

1. **All Hobeian ZK/ZX/ZV units are battery EndDevices** across all three Z2M instances
   (`zigbee2mqtt`, `zigbee2mqtt2`, `zigbee2mqtt3`). Study A's ZG-204ZK:
   `powerSource: "Battery"`, `type: "EndDevice"`, 2.7 V, 100 %. Sleepy end devices do not
   respond to arbitrary polls on an orchestrator's schedule.
2. **The HA `number.*` state is Z2M's cached last-write.** 10 days of recorder history on
   `number.mmwave_zigbee_studya_motion_detection_sensitivity`,
   `..._static_detection_sensitivity`, `..._fading_time` show the same pattern on every
   HA/MQTT reconnect: `V → unavailable → unknown → V` within 2–5 min, byte-identical,
   ~20 cycles. A battery EndDevice cannot physically answer that fast on every cycle. Z2M
   is republishing its retained value, not reading the device.
3. **No spontaneous device reports.** The three number entities never changed value except
   on the two explicit operator writes (today 11:49:40). A factory reset or an
   out-of-band Z2M-UI edit would **not** surface in HA.

Combined implication: **drift is undetectable from HA for these devices.** "Applied" and
"verified" are claims URA cannot back from the HA entity it writes against. The only
honest state Phase A can report is "sent": the last write URA issued to the HA number
entity. Everything downstream of this fact (no reconciler, no drift sensor, no kill
switch, no never-desensitised guard) follows.

---

## Problem (one paragraph)

Operators tune ZK/ZX presence radars by hand in Z2M. The settings are per-device and get
forgotten; they drift silently on re-pair/factory-reset/manual Z2M edit. Phase A does the
smallest useful thing: a per-room **"Radar settings"** block in the room options flow for
ZK/ZX only, where each field defaults "Leave as is" and, on save, URA sends the chosen
values once to the HA number entities on each radar device. URA records what it sent.
URA does not loop, does not re-assert, does not claim verification. The operator's own
Z2M remains the source of truth; URA is a quiet second writer limited to fields the
operator picked in URA.

---

## Falsifiable invariant (the one property Phase A must guarantee)

> **URA will only send values that the operator set in URA for that entity.**
>
> Corollaries (each independently falsifiable):
> 1. URA never writes a field whose UI value is **"Leave as is"**.
> 2. URA never writes at boot. Writes happen only when the operator saves the options
>    flow or presses the single operator-triggered re-apply action.
> 3. URA never writes to a device that is not in a room's `presence_sensors` list, and
>    never writes to a non-ZK/ZX device (family guard `zigbee_zk_zx` only).

The Rev 1 invariant ("live equals target") is retracted because it is unobservable from
HA for these devices (probe Q2–Q3). Rev 2's invariant is defined on the SEND path only;
that path is fully observable (log scan of the service calls URA emits).

---

## Institutional context verified

### Design docs read
- `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (full) — `CONF_MMWAVE_SENSORS =
  "presence_sensors"` (§10 ledger), capability routed through `sensor_capability.py`.
- `SENSOR_FLEET_CLASSES.md` (full) — ZV is motion-class, no radar knobs; ZK and ZX
  share one family token.

### Prior-art scan (REUSE > EXTEND > BUILD) — per proposed piece

| Proposed piece | Verdict | Existing symbol | Why |
|---|---|---|---|
| Per-room "Radar settings" options block (per-sensor dropdowns) | **BUILD** on existing options-flow sub-step pattern | `config_flow.py:12524+` (capability sub-step; per-entity dropdowns) | Pattern exists; the per-field surface does not. |
| Family guard "ZK/ZX only" | **REUSE** | `sensor_capability.FAMILY_BY_MODEL_ID` → `zigbee_zk_zx` (`sensor_capability.py:378-405`); family resolver `fan_veto.resolve_sensor_family` (`fan_veto.py:81`) | Correct token (Rev 1 invented `hobeian_zk`/`hobeian_zx` — those keys do not exist). |
| Resolve the radar's own `number.*` entities from the `presence_sensors` binary_sensor | **REUSE PATTERN** | `coordinator._resolve_room_switch_entity_id` (`coordinator.py:3028-3074`) walks `entity_registry → device_id → entries_for_device` | Same registry-first pattern; resolved each call, never cached as entity_id string (review Finding 11). |
| Service-call write to a `number.*` entity | **BUILD** | No URA precedent. `grep -rn 'set_value' custom_components/` finds only entity-side `async_set_value` in `time.py`; there is no `services.async_call("number", "set_value", …)` writer in URA today. Rev 1 claim ("precedent in `energy.py` / `energy_pool.py` / `energy_battery.py`") was wrong (review Finding 7a). | Trivial `hass.services.async_call("number", "set_value", …)` call. |
| "Leave as is" sentinel in options storage | **BUILD** | — | Simple: field absent from the saved dict means Leave-as-is. |
| Named-bucket labels in the options flow | **REUSE PATTERN** | `feedback_configurability_clarity`; SENSOR-FORM-PLAIN-TEXT-1 Advanced-JSON escape hatch | Buckets include the live values (motion 4/6/8, static 4/6/8) so Study A's 5/6 and Wigton's 6/6 are reachable without raw-number JSON. |
| Per-room re-apply trigger | **BUILD** (one of: service or button) — see §Parsimony pick | — | Must be operator-triggered; see §Parsimony pick. |

### Code locations surveyed
- `custom_components/universal_room_automation/domain_coordinators/sensor_capability.py:378-405` — `FAMILY_BY_MODEL_ID`, actual family tokens (`zigbee_zk_zx`, `zigbee_zv`, `ld24xx`, `generic_radar`, `pir`, `unknown`).
- `custom_components/universal_room_automation/fan_veto.py:51-120` — family resolver (model-id and model-string fallback).
- `custom_components/universal_room_automation/coordinator.py:3028-3074` — registry-first resolver precedent.
- `custom_components/universal_room_automation/config_flow.py:12254-12578` — capability options sub-step + per-entity dropdowns.
- `custom_components/universal_room_automation/const.py:480` (`CONF_MMWAVE_SENSORS`), `:559` (`CONF_SENSOR_CAPABILITIES`).
- `custom_components/universal_room_automation/time.py` — the only `set_value` reference in the repo (entity-side `async_set_value`, not a service call).

### Config-first check (step 1b)
Every field Phase A sends to already exists as an HA `number.*` entity on the device (Z2M
exposes them). Omonele can set them today by opening each device page. The gap Phase A
closes is "per-room, labelled plainly, in URA's config flow where the operator already
tunes a room" — a UI collocation gap, not a knob-does-not-exist gap. Deploying Rev 2 with
every field at "Leave as is" writes **zero bytes** (§Live impact); so the risk floor is
the UI itself.

---

## Design (SMALL)

### Writer boundary — "Leave as is" = never write

Per-sensor options block in the room options flow (Advanced step), one block per entity
in `presence_sensors` whose device family resolves to `zigbee_zk_zx`. Each field is a
dropdown with named buckets + the sentinel **"Leave as is"** (default). "Leave as is"
means the field is absent from the saved dict → URA never writes it. The operator can
flip any field back to "Leave as is" to stop URA touching it.

### Send path (the only writer)

On options save, URA diffs the previous and new saved dicts for this room, resolves each
managed field's underlying `number.*` entity through the device registry (never a cached
entity_id string — review Finding 11), and emits **one**
`hass.services.async_call("number", "set_value", {"entity_id": …, "value": …})` per
changed field. That's it. URA logs the emit at INFO ("sent"). URA does not read back,
does not schedule a re-check, does not retry (the probe shows a retry on a sleepy end
device would just overwrite Z2M's cache again without proving anything).

Second trigger: an operator-pressed **re-apply** (see §Parsimony pick below).

### What URA never does (Rev 1 → dropped)
- No listener on the number entities. No `last_updated` wake proxy (the probe shows these
  entities only change on operator writes — a listener would never fire from the device).
- No boot-time write. On HA restart, URA emits nothing; the operator's last-saved values
  are still in Z2M's retain and come back on reconnect.
- No "drift" sensor, no "applied" sensor, no house roll-up, no kill switch, no flap
  counter, no backoff schedule, no 24h rate cap. None of these defend against anything
  observable; they only defend against the autonomous reasserter Rev 2 does not have.
- No bulk apply across rooms. Each room is edited in its own options flow.

### Parsimony pick — single service, not per-room buttons

Options considered for the operator-triggered re-apply:
- **(A) `button.<room>_reapply_radar_settings` per room with managed fields.** Visible on
  the room's dashboard; one-click. Cost: one new button entity per room (potentially
  ~8 rooms if all ZK/ZX are managed) that is pressed roughly once per factory-reset
  event (rare).
- **(B) One service `universal_room_automation.reapply_radar_settings` with
  `room_entry_id` as a required field.** No new entities. Callable from Developer Tools,
  a dashboard button-card, or a one-off script. Cost: operator discoverability.

**Pick: (B) single service.** Rationale from `feedback_parsimonious_room_config`: do not
mint ~8 button entities for a rare operator action. The service shows up in Developer
Tools alongside every other URA service, is documented in the README, and keeps the
room's entity list uncluttered. If post-ship evidence shows operators are copying the
service call to dashboards anyway, the Phase A.1 extension is a thin button that calls
the service — additive, no rework.

### Named-bucket labels (D2)

Buckets per field. Values chosen so the live settings in use (Study A: motion 5, static
6; Wigton: motion 6, static 6, fading 120 s, distance ≤ 4 m) are **reachable from the
buckets without touching Advanced JSON** (review Finding 6 fix direction):

- **Motion sensitivity** (raw 0–10 on ZK/ZX): `Leave as is` · `Low (4)` · `Medium (6)` ·
  `High (8)`.
- **Still-person sensitivity** (raw 0–10): `Leave as is` · `Low (4)` · `Medium (6)` ·
  `High (8)`.
- **How far it watches** — Range buckets. Raw units/limits must be read from the live
  `number.*` entity min/max/step at build (standard ZG-204ZK `detection_distance` is
  metres with 0.5 m or 0.1 m step depending on firmware; the build reads
  `state.attributes["min"]`, `max`, `step` from the live entity on first open of the
  options flow). Proposed labels (metres, confirmed at build): `Leave as is` ·
  `Short (3 m)` · `Standard (4 m)` · `Long (6 m)`. If the live entity's `max` is lower
  than 6 m, Long clips to `max` and the label updates.
- **Hold time after last movement** — longer hold **never misses a person**; shorter hold
  risks releasing while someone is still present. Buckets (direction: longer = safer
  against false-release, delays release when the room empties): `Leave as is` ·
  `Short (30 s)` · `Standard (60 s)` · `Long (120 s)` · `Very long (300 s)`.

One-sentence consequence text under each dropdown, per `feedback_configurability_clarity`
and `feedback_label_style_guide` (≤3 words in the dropdown title; no `hysteresis`,
`debounce`, `substrate`, `tier`, `failsafe` in any copy). Advanced-JSON escape hatch
mirrors `SENSOR-FORM-PLAIN-TEXT-1`.

**Not in the bucket set:** `anti_interference` — the field exists on ZK/ZX, but the
operator-facing semantics are not independently verified (review Finding 6). Deferred to
Phase A.1 with a verified label.

---

## Out of scope — the families Rev 1 claimed and why they're excluded

- **Hobeian ZV (zigbee_zv):** motion-class per `SENSOR_FLEET_CLASSES.md` Rule 1; has no
  "radar knobs" to send.
- **ESPHome LD2410 (`ld24xx`, and the custom ESPHome ones that resolve to `unknown` per
  PRESENCE §10 item 9):** no 1–10 sensitivity knob; exposes per-gate energy thresholds
  (0–100 where higher = **less** sensitive), with inverted direction vs the Hobeian
  buckets. Dropping LD2410 avoids writing inverted-meaning values (review Finding 6b).
- **Meross MS600 (`generic_radar`, native and Matter):** Matter cluster is read-only;
  native-meross_lan writability of the distance target is unverified. Deferred.
- **Screek / Seeed / Inovelli (`generic_radar`):** writable field set unknown; not
  measured.
- **Tuya TS0601 at Wigton:** no `tuya_ts0601_radar` family token exists in URA. The
  Wigton units' writable `number.<u>_motion_detection_sensitivity` suffixes match ZK, so
  they may already resolve to `zigbee_zk_zx` once filed into rooms. See §Wigton
  prerequisite.

## Wigton prerequisite (not a deliverable)

Per review Finding 2 and `AUDIT_motion_sensors_live_models.md:105-111`: Wigton URA rooms
hold only three ECB501 ecobees today, and URA is disabled at Wigton
(`RUNBOOK_wigton_ura_reenable.md:3`). The 17 Wigton radars are in no `presence_sensors`
list. Phase A can be developed and shipped against the main house ZK/ZX fleet. **Filing
Wigton's radars into their room's `presence_sensors` and confirming their family
resolves to `zigbee_zk_zx` is a Wigton runbook step**, tracked under the Wigton re-enable
work, not under this plan. Phase A's acceptance criteria make no claim about Wigton.

---

## Deliverables

### D1 — Family-guarded field-presence detection (no defaults table)

Rev 1's `TUNING_DEFAULTS_BY_FAMILY` map is **dropped** — Phase A has no defaults, only
"Leave as is". What Phase A needs instead is: given a `presence_sensors` binary_sensor
entity, (a) resolve its device and (b) determine whether its family is `zigbee_zk_zx`
and which of the five tracked `number.*` entities are present on that device.

- Add a small helper in a new module
  `custom_components/universal_room_automation/domain_coordinators/radar_tuning.py`:
  `resolve_zk_zx_tuning_entities(hass, binary_sensor_entity_id) -> dict[str, str] | None`.
  Returns `None` if the family is not `zigbee_zk_zx`. Otherwise returns a dict of
  `{field_name → entity_id}` for the fields present on the device (motion_sensitivity,
  static_sensitivity, detection_distance, fading_time; `anti_interference` deferred).
- Uses the existing registry-first resolver pattern (`coordinator.py:3028-3074`).
- Reads the live entity's `min`/`max`/`step` for `detection_distance` so the range
  bucket labels can clip to the actual device limits.

**Acceptance Criteria**
- **Verify:** calling the helper on Study A's `binary_sensor.<studya_zk>_occupancy`
  returns a dict with four entries pointing at `number.mmwave_zigbee_studya_*`.
- **Verify:** calling on a `zigbee_zv` binary_sensor returns `None`.
- **Verify:** calling on an `ld24xx` or `generic_radar` or `unknown` binary_sensor
  returns `None`.
- **Test:** `test_resolve_returns_none_for_zv`,
  `test_resolve_returns_four_fields_for_zk`, `test_resolve_handles_renamed_entity_id`
  (resolution goes through the registry every call; no cached entity_id string).
- **Live:** none — pure resolution.

### D2 — Per-room "Radar settings" options block (Advanced)

Extend the Advanced step of the room options flow with a per-sensor "Radar settings"
sub-section rendered only for `presence_sensors` entities whose family is `zigbee_zk_zx`
(resolved via D1). Fields per sensor: motion sensitivity, still-person sensitivity, how
far it watches, hold time — each a dropdown with buckets per §Named-bucket labels, every
field defaulting **"Leave as is"**. Save path writes the chosen bucket's raw value into
the saved options dict under a key like `radar_settings[entity_id][field]`; omitted keys
mean Leave-as-is.

**Acceptance Criteria**
- **Verify:** opening a room options flow → Advanced → Radar settings shows one block
  per ZK/ZX entity, each with four dropdowns, every field at "Leave as is".
- **Verify:** rooms with no ZK/ZX entities show no Radar-settings block.
- **Verify:** labels grep-clean: no `hysteresis`, `debounce`, `provenance`,
  `substrate`, `tier`, `failsafe`.
- **Verify:** the "How far it watches" labels clip to the live entity's `max` on open.
- **Test:** `test_options_flow_radar_block_round_trips` (save → reload → values
  preserved); `test_leave_as_is_omits_key_from_saved_options`;
  `test_block_hidden_for_zv_only_rooms`; `test_range_bucket_clips_to_live_max`.
- **Live:** at main house, opening Study A → Options → Advanced → Radar settings shows
  one block with four dropdowns; setting "Motion sensitivity = Medium (6)" and saving
  issues exactly one `number.set_value` service call for
  `number.mmwave_zigbee_studya_motion_detection_sensitivity` with `value: 6`.

### D3 — Send-on-save (one service-call writer, no reconciler)

In `radar_tuning.py`, add `async_send_radar_settings(hass, room_entry_id)` that:
1. Resolves the room's current saved `radar_settings` dict.
2. For each `(entity_id, field, value)` whose value is not Leave-as-is AND differs from
   the previous saved value (diff computed by the options-flow save handler), calls
   `hass.services.async_call("number", "set_value", {"entity_id": …, "value": …},
   blocking=False)`.
3. Logs each emit at INFO (`"radar_settings: sent entity=%s field=%s value=%s"`). No
   read-back, no retry, no scheduled re-check.
4. Hook into the options-flow save as the only internal caller.

**Acceptance Criteria**
- **Verify:** saving an options change from "Leave as is" → "Medium (6)" on motion
  sensitivity emits one `number.set_value` call; the HA `number.*` state reflects 6
  within the normal Z2M echo (seconds). The log line reads "sent", not "applied" or
  "verified".
- **Verify:** saving options with every field at "Leave as is" emits **zero** service
  calls.
- **Verify:** saving options unchanged (edit→save with no changes) emits zero service
  calls.
- **Verify:** URA emits **no** `number.set_value` call at boot (restart URA; log scan
  for the service call → zero).
- **Verify (non-destruction):** manually set an UNMANAGED field value in Z2M; save the
  room options with Radar settings fields unchanged; URA emits no `number.set_value` for
  the unmanaged field over 24 h (log scan).
- **Test:** `test_send_emits_one_set_value_per_changed_field`;
  `test_leave_as_is_sends_nothing`; `test_boot_emits_nothing`;
  `test_unmanaged_field_never_written`; `test_resolves_entity_id_through_registry_each_call`.
- **Live:** at Study A, flip motion sensitivity from Medium (6) → High (8) in options;
  save; `number.mmwave_zigbee_studya_motion_detection_sensitivity` goes to 8 within
  seconds; URA log shows exactly one "sent" line.

### D4 — Service `universal_room_automation.reapply_radar_settings`

One service, registered at integration setup, with schema `{room_entry_id: str}`. Calls
`async_send_radar_settings` with a forced "diff = everything managed" so every managed
field is re-sent (bounded set: ≤ 4 fields × ≤ ~1 radar per room in Phase A). This is the
operator's recovery path after a factory reset or an out-of-band Z2M edit.

**Acceptance Criteria**
- **Verify:** calling the service from Developer Tools against a room with two managed
  fields emits exactly two `number.set_value` calls.
- **Verify:** calling the service against a room with every field at Leave-as-is emits
  zero calls.
- **Verify:** calling with an invalid `room_entry_id` logs a WARNING and emits zero
  calls.
- **Test:** `test_reapply_service_sends_all_managed_fields`;
  `test_reapply_service_noop_when_all_leave_as_is`;
  `test_reapply_service_rejects_unknown_entry_id`.
- **Live:** at Study A after setting two fields, invoke the service from Developer
  Tools; URA log shows two "sent" lines; the device page confirms the values.

### D5 — README (same cycle)

`docs/readmes/README_v<ver>.md`: prospective acceptance criteria from D1–D4; the
Live-Validation table is written back post-restart per CLAUDE.md.

**Acceptance Criteria**
- **Verify:** README committed with cycle; names the single service and the per-room
  options path; explicitly states URA does not reconcile drift and the "Leave as is"
  default.
- **Live:** README post-restart table lists each AC with observed value.

**No D6 — no AUDIT fixture.** Rev 1's D6 fixture was keyed to Wigton; Wigton is out of
scope here (§Wigton prerequisite). No defaults table in Rev 2 means nothing to diff.

---

## Knob ladder (every number named)

| Knob | Rung | Default | Why that rung |
|---|---|---|---|
| Motion-sensitivity bucket values (`4`, `6`, `8`) | **1** module const in `radar_tuning.py` | 4/6/8 | Bucket values; change should require review (safety against mis-labeling). |
| Still-sensitivity bucket values (`4`, `6`, `8`) | **1** module const | 4/6/8 | Same. |
| Range bucket metres (`3`, `4`, `6`) | **1** module const | 3/4/6 (clipped to live `max`) | Same. |
| Hold-time bucket seconds (`30`, `60`, `120`, `300`) | **1** module const | 30/60/120/300 | Same. |
| Per-room per-sensor per-field target | **2** options flow | **Leave as is** | Per-deployment structure; set-once per operator intent. |

No rung-3 live entity. No kill switch (nothing autonomous to kill). The feature's own
kill is "every field = Leave as is", which is already the default.

---

## Live impact

- **Deploy writes nothing.** Every field defaults to "Leave as is" in options storage;
  the options-flow save handler emits a service call only on a diff from the previous
  saved value. On deploy, no diff exists, so no `number.set_value` is emitted on any
  radar in either house.
- **Blast radius:** writes are bounded to the HA `number.*` entities on each room's own
  ZK/ZX radar devices. No HVAC, house-state, or actuator path is touched. Second-writer
  precedence vs Z2M is explicit: URA writes only what URA knows.
- **Wigton:** zero impact until the Wigton runbook files radars into `presence_sensors`.

---

## Non-goals / rejected options

- **Autonomous drift reconciler.** The probe shows drift is undetectable through HA's
  own number entity (Z2M cache, not device read-back). Building a reasserter against a
  cache would create a self-confirming loop and burn battery on sleepy end devices for
  no verified gain. Park trigger: ≥ 2 measured drift events in 30 days on managed
  fields, where "measured" means an independent Z2M `/get` round-trip or a bench
  factory-reset experiment.
- **"Applied" / "verified" state labels.** The HA number state is Z2M's cache; URA
  reports "sent", not "applied".
- **Phase B dynamic fan-aware tuning.** Gated on ≥ 2 weeks of post-Phase-A false-hold
  data AT a measured false-hold rate > 1/day/room AND the fan-noise Rev 2 fixes
  shipped and measured, per `feedback_marginal_benefit_pushback`.
- **ZV radar writes.** Motion-class, no knobs (SENSOR_FLEET_CLASSES Rule 1).
- **LD2410 / Meross / Screek / Tuya TS0601 writes.** Semantics unverified or inverted;
  Phase A ships against the one family it can defend.
- **Boot-time first-apply.** URA writes only on operator save or operator service call.
- **Per-room kill switch, flap counter, per-room status sensor, house roll-up,
  write-rate cap.** All defended against an autonomous reasserter Phase A does not
  build.
- **Z2M MQTT topic path.** URA writes HA number entities; Z2M mirrors.
- **Bulk apply across rooms.** Each room is edited and (if needed) re-applied
  individually; intentional friction against a batch mistake.

---

## Review classification + plan review

- **Tier: 2** (new feature, options-flow surface, one service writer, one new helper
  module, no autonomous timer or listener).
- **Not Tier 2-DB** — no `database.py` touch, no payload-shape migration, no autonomous
  cross-coordinator writer (the Rev 1 reasserter is gone; the write path is operator-triggered
  only).
- **Not Tier 3** — no shared primitive consumed by many sites; the one send path is
  behind "Leave as is" (default) and a family guard.
- Plan review MANDATORY before build dispatch (operator-coined 2026-08-11). The reviewer
  independently re-greps: `set_value` across `custom_components/` (should find only
  `time.py` entity-side), `FAMILY_BY_MODEL_ID` tokens (should find `zigbee_zk_zx`,
  not `hobeian_zk`), `BOOT_SETTLE_MIN_INPUTS` call sites (should find
  `presence.py:5707` only, confirming irrelevance here).

---

## Plan review 2026-10-11 (Rev 1, kept verbatim — the findings Rev 2 implements)

> *(Preserved below exactly as written; every must-fix is addressed above.)*

Read completely before reviewing: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`,
memory `feedback_marginal_benefit_pushback`, `feedback_parsimonious_room_config`,
`feedback_label_style_guide`, `feedback_configurability_clarity`. Greps re-run, not trusted.

**Verdict: PLAN-FIX-REQUIRED.** The direction is right. The scope is over-built for "URA records and
applies radar settings per room, plainly", and several factual claims fail a grep.

### Findings

1. **HIGH: family keys do not exist.** D1 keys `hobeian_zk`, `hobeian_zx`, `tuya_ts0601_radar`,
   `meross_ms600_native`, `esphome_ld2410`, `screek`. The real tokens are `zigbee_zk_zx` (ZK and ZX share
   one), `ld24xx`, `generic_radar` (Screek, Seeed, Inovelli, MS600 and Matter MS600 all share it), `zigbee_zv`,
   `pir`, `unknown` (`sensor_capability.py:378-405`). There is no Tuya family. The custom ESPHome LD2410s
   (Jaya, Ziri, Kitchen, Study B) resolve to `unknown` (§10 item 9). A defaults table keyed by family
   therefore cannot reach the LD2410s at all, and it lumps Screek in with MS600. **Fix:** key the fields by
   *the writable sibling entities present on the device* (suffix discovery), not by family. Keep family only
   as a guard that excludes ZV and PIR.

2. **HIGH: the Wigton fixture targets sensors URA does not own.** `AUDIT_motion_sensors_live_models.md:105-111`
   shows Wigton's URA rooms hold only three ecobee ECB501 entities and no radars, and URA is disabled there
   (`RUNBOOK_wigton_ura_reenable.md:3`). The 17 radars are in no `presence_sensors` list, so the invariant
   ("every entity listed under URA-managed tuning in a room config") covers none of them. D1's acceptance
   ("round-trips against the Wigton fixture") and D2's Live AC ("Omonele sets Game Room distance") cannot
   pass until the Wigton rooms are re-wired with radars, which belongs to the runbook and is not in this
   plan. The "Tuya TS0601" model is also unverified. Remote_tune uses the same `number.<u>_motion_detection_sensitivity`
   suffixes as Study A's ZG-204ZK, so the units may be Hobeian. **Fix:** make "Wigton radars filed into
   `presence_sensors` + models read from the device registry" an explicit prerequisite. Otherwise, rescope
   the acceptance to main-house Study A and treat Wigton as Phase A.1.

3. **HIGH: the drift oracle may be Z2M's cache, not the device.** Every drift, applied and factory-reset
   claim reads the HA `number.*` state. For a Z2M number that state is what Z2M last published, either the
   device's report or an echo of the set. Two consequences, neither handled:
   (a) After a factory reset, the device does not push its config attributes unless they are read or
   reported, so HA keeps showing the old target and Phase A reports `applied` while the device is at
   defaults. That breaks the plan's own invariant. The claim in §Prior-art ("a factory reset manifests as
   live ≠ target on the next state change") is unverified.
   (b) If Z2M echoes the set, "converged" is self-confirming.
   **Fix:** run a measure-first probe before build. On Study A, set one field through HA, then use Z2M's
   `get`/read for that attribute and compare. Record whether the HA state follows device read-back. If it
   does not, drop the "applied" claim and name the state "set by URA" (last write accepted), not "verified".

4. **HIGH: the wake proxy is wrong.** D3 arms listeners on the tuning `number/select/switch` entities and
   treats "the next `last_updated` change the entity emits" as "device awake". A config number changes
   only when its value changes, so this listener fires almost never and cannot gate a write. Whether
   ZK/ZX are sleepy battery end devices at all is unverified in the plan. **Fix:** read `power_source` from
   the device registry or Z2M for each unit. If the units are mains/USB (no sleep), delete the whole
   wake-gating and backoff machinery. If they are battery, use a sibling that reports often
   (occupancy/illuminance/linkquality on the same device) as the wake proxy.

5. **HIGH: "desensitised" direction is wrong for hold time.** §Never-desensitised lists "longer fading"
   as more desensitised. A longer fading/hold time keeps presence on *longer*: more false holds, never a
   missed person. The safety risk is a *shorter* hold together with *lower* sensitivity or *shorter* distance.
   As written, the guard would warn on Wigton's 120 s, which is the intended setting, and would pass a
   10 s hold silently. Separately, "within one bucket of the family default" is undefined when the family
   has no default (item 1), and the "10-minute restart debounce" contradicts §Non-goals "no boot-time
   apply". **Fix:** define less-sensitive per field (sensitivity ↓, distance ↓, hold ↓). Keep only the
   save-time soft warning. Drop the restart debounce: a target that was already accepted at save is
   operator intent.

6. **HIGH: the buckets cannot represent the values in use.** Motion/static `Low 3 / Medium 5 / High 7 /
   Very high 9`. Study A static = 6 and Wigton motion/static = 6 can only be set through Advanced JSON,
   so the plan's own fixtures fail the "plainly" goal. LD2410 (ESPHome) has no 1-10 sensitivity. It exposes
   per-gate energy thresholds of 0-100 where a **higher number is less sensitive**, plus a timeout, so the
   buckets would write wrong values with the meaning inverted. MS600/Screek ranges are unknown. **Fix:**
   for Phase A, buckets apply only to the Hobeian ZK/ZX fields (0-10 scale) and include the in-use values
   (for example 4 / 6 / 8), with the bucket table recorded in D1. Per-gate LD2410 is a non-goal for
   Phase A, and so are MS600 and Screek. "Ignore passing fans/airflow" claims a behaviour of
   `anti_interference` that is not verified. Use a plain neutral label ("Interference filter: On/Off")
   unless the vendor semantics are cited.

7. **MEDIUM: prior-art claims fail grep.** (a) "`number.set_value` precedent in `energy.py` /
   `energy_pool.py` / `energy_battery.py`": `grep -rn set_value custom_components/` finds only `time.py`
   (entity-side `async_set_value`) and no service-call writes to `number`. This is genuinely new;
   say BUILD. (b) `BOOT_SETTLE_MIN_INPUTS` (`const.py:3811`, not :3789) is a census-count gate in
   `presence.py:5707` and means nothing to a room reconciler. Use the room `_skip_first_automation` or the
   reconciler `_in_post_boot_grace` (`actuator_reconciler.py:393`) pattern instead.

8. **MEDIUM (marginal benefit): over-built.** Drift is asserted ("drift silently on factory-reset,
   re-pair, or manual edit"), not measured. No drift event is cited. Six deliverables add a new
   reconciler, wake-gating, an exponential backoff, a 24 h/field rate cap, flap quarantine plus a K/W
   Number pair, a release button, a kill switch, a per-room status sensor on about 43 rooms, a house
   roll-up and a defaults table. The flap/quarantine/backoff ingredients defend against a loop that only
   exists because of the auto-reassert loop. **Config-first also applies:** these fields are already
   plain, labelled HA number entities on the device page, which Omonele can use today. **Recommended
   Phase A (smallest useful version):**
   - Per-room options block (Advanced → "Sensor settings") for ZK/ZX presence radars only, with buckets
     per item 6. Default "Leave as is", stored per field.
   - **Apply on save** (one service call per set field, then read back once after ~60 s). No background
     reasserting.
   - **Visibility without a new per-room entity:** add `tuning` live-vs-target attributes to the existing
     `sensor.<room>_unavailable_entities`, or create a status sensor only in rooms that manage something.
   - **Drift = surfaced, not fought.** On restart and on a state change of a managed number, compare and
     mark `drifted`. Re-apply happens when the operator re-saves, or through one "Re-apply sensor settings"
     button. Drop the reconciler loop, backoff, rate cap, flap quarantine, K/W knobs, house roll-up
     and kill switch (no autonomous writer means nothing to kill).
   - Park auto-reassert with a trigger: "≥2 measured drift events in 30 days on managed fields".
   This covers "records and applies plainly" with one writer path that only the operator triggers.

9. **MEDIUM: ACs that do not discriminate or cannot run.** D3 Live "factory-reset ZK returns to 5": no
   one will factory-reset a live sensor, and per item 3 the HA state would not show it anyway. D4 Live
   "Study A reports `applied` with 5 managed fields" passes under the Z2M-echo failure as well (item 3b).
   **Fix:** use the Z2M read-back as the discriminating observation. For drift, use a manual edit of a
   managed field through the Z2M frontend (not HA), then confirm `drifted` appears and that no write fires
   without operator action (recommended scope), or that a reassert fires (if the full scope is kept).

10. **LOW: entity-count parsimony.** A per-room `tuning_status` sensor in all rooms, most showing
    `unmanaged`, is clutter (`feedback_parsimonious_room_config`). Create it only when the room manages a
    field, or use attributes. The `button.<room>_release_tuning_flap` label breaks the 3-word/no-nerd
    style ("flap").

11. **LOW: restart and options race.** If the full scope is kept: a cleared target while a write is
    pending must cancel the scheduled `async_call_later` handle (track and unsub on unload). An entity
    rename invalidates the cached sibling map, so resolve through the registry `device_id` each time and
    never cache the entity_id string (the same lesson as `coordinator.py:3028-3074`).

12. **INFO: live impact.** All fields default to unmanaged, so deploying writes nothing in either house.
    Main house targets are the 8 ZK/ZX units (`SENSOR_FLEET_CLASSES.md` table). Wigton: zero until item 2
    is resolved. Tier 2 is adequate *for the recommended scope*. Keeping the autonomous reasserting writer
    adds a physical second writer to devices another integration owns, so elevate that to 2-DB.

13. **OK: non-goals and the Phase B gate** are explicit and well-reasoned. The trigger is measured
    (≥2 weeks, >1 false hold/day/room, after fan-noise Rev 2 is measured). Keep them.

### Must-fix before build dispatch
1, 2, 3 (probe), 4 (read power_source), 5, 6, 7. Then either adopt the reduced scope in 8 (recommended)
or justify each dropped item with measured drift evidence.

---

## Rev 2 reconciliation table — each must-fix → where it's addressed

| Must-fix | Addressed by |
|---|---|
| 1 (family keys) | §Institutional context prior-art table: `zigbee_zk_zx` only, resolved via `sensor_capability.FAMILY_BY_MODEL_ID` and `fan_veto.resolve_sensor_family`. No invented family keys. |
| 2 (Wigton) | §Wigton prerequisite — Wigton out of Phase A scope; main-house ZK/ZX only; no Wigton AC. |
| 3 (Z2M-cache oracle) | §Measurement findings, confirmed by probe Q2–Q3. State renamed "sent"; no "applied" / "verified" claim. |
| 4 (wake proxy) | §What URA never does — no listener, no wake proxy. Probe Q1 confirms EndDevice; probe Q3 confirms the config numbers never change spontaneously. |
| 5 (desensitised direction) | Guard dropped entirely (no autonomous writer to guard). Hold-time copy corrects the direction: longer hold = never misses a person. |
| 6 (buckets can't hold in-use values) | §Named-bucket labels: 4/6/8 for motion+static; range buckets read live min/max/step; LD2410/MS600/Screek deferred; `anti_interference` deferred until semantics verified. |
| 7a (set_value precedent) | §Prior-art table: marked BUILD; cites only `time.py` entity-side `async_set_value`. |
| 7b (BOOT_SETTLE_MIN_INPUTS) | Removed; Rev 2 has no boot-time write at all. |
| 8 (over-built) | Scope collapsed to options block + one service writer + one re-apply service. Reconciler, backoff, rate cap, flap, K/W knobs, release button, kill switch, status sensors, house roll-up all dropped. |
| 9 (non-discriminating ACs) | ACs rewritten around observable send-path events (service-call emission counts, log lines, saved-dict keys), not the unobservable "applied" claim. |
| 10 (parsimony) | No per-room status sensor; no flap button; single service instead of per-room buttons. |
| 11 (restart/options race) | No `async_call_later`; nothing to cancel. Registry resolved every call. |
| 12 (second-writer elevation) | Not applicable: no autonomous second writer in Rev 2. Tier 2 is sufficient. |
| 13 (non-goals/Phase B gate) | Kept verbatim in §Non-goals. |
