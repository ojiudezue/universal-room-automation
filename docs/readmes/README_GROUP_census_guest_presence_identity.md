# Cycle-Group README — Census / Guest / Presence-Identity

**Card:** `CENSUS-IDENTITY-GROUP-README-1`
**Program cards:** `CENSUS-GHOST-DEDUP-1` → `CENSUS-ACCURACY-1` → `EXTERIOR-GUEST-FACE-FASTFOLLOW-1` → `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1` (planned) → D2 Protect corroboration (gated)
**Per-version READMEs:** [v5.79.0](README_v5.79.0.md) · [v5.80.0](README_v5.80.0.md) · [v5.81.0](README_v5.81.0.md)
**Entity inventory verified live** against the running HA instance on 2026-08-18 (house empty, residents away until Wed PM). Every `entity_id` below was confirmed to exist unless explicitly flagged.

---

## 1. What this program is / the problem it solved

The house's people-count was untrustworthy in three compounding ways, and this arc fixed them in dependency order. First, the **interior census over-counted**: an additive derivation (`identified + camera_unrecognized`) double-counted residents the cameras saw, its two dedup defences were inert (dead face-recognition + zero BLE-cancel), and a decay tail that *self-refreshed* whenever `fresh == peak` made a transient over-count effectively permanent (a measured 7h02m stuck in `guest` on 2026-08-16, 74.5% of over-count time was pure decay with no live camera evidence). Second, **guest mode misfired**: it armed off the census count (not off guest-room occupancy), and its only identity safety check — `_is_known_person_in_room` — had been silently dead since v4.7.2 (wrong coordinator lookup + non-existent attribute), so a *resident* in a guest room could arm GUEST. Third, **crossings were anonymous**: entry/exit egress events always carried `person_id=None`, so the census could never use who-actually-walked-in to firm up its identity set. The program repaired **guest correctness** (v5.79.0), then **interior count accuracy** (v5.80.0), then **egress identity** (v5.81.0), with a planned control-surface cleanup (device switches) and a gated second face source (Protect) still ahead.

---

## 2. The cycles

| Version | Cycle | What it fixed | Card | README |
|---|---|---|---|---|
| **v5.79.0** | Guest correctness | Repaired the dead `_is_known_person_in_room` oracle (canonical `person_coordinator` + real `data[name]["location"]` shape) + `GUEST_KNOWN_STICKY_S` sticky latch; inverted guest composition so **guest rooms lead** (census no longer arms GUEST); decoupled guest exit from the count; registry-based guest-room resolution; D1 pre-cancel clamp on the additive census path. | `CENSUS-GHOST-DEDUP-1` | [v5.79.0](README_v5.79.0.md) |
| **v5.80.0** | Interior census accuracy + exterior dashboards | Deleted the peak self-refresh + house-zone linear decay (instant-drop like exterior); `_2`-suffix fresh-face fix (revives the `−1` face-dedup credit, fail-closed); D3 exterior dashboards (KEEP-BOTH: deduped headline + naive floor + divergence). | `CENSUS-ACCURACY-1` | [v5.80.0](README_v5.80.0.md) |
| **v5.81.0** | Egress face-identity (D1) | Stamps `person_id` on entry/exit crossings from the freshest Frigate face; fuses that identity into the census union at **both** writers (URA-slug canonical); entry-gated register (no phantom guest on exit); behind kill switch `CONF_EGRESS_IDENTITY_ENABLED` (default OFF) + observability attrs. | `EXTERIOR-GUEST-FACE-FASTFOLLOW-1` | [v5.81.0](README_v5.81.0.md) |
| **PLANNED** | Census toggles → device switches | Promote 3 buried Camera-Census options-flow flags to one-tap device switches (`switch.ura_presence_face_matching`, `switch.ura_smart_people_counting`, `switch.ura_name_people_at_doors`). Control-surface relocation only, no behavior change. | `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1` | `docs/planning/PLANNING_census_toggles_to_device_switches.md` |
| **GATED** | D2 — Protect corroboration | Second NVR face source (UniFi Protect) adding corroboration to Frigate egress identity. Hard-gated on a real captured `ura_kp_face_probe_received` webhook payload; kill switch `PROTECT_CORROBORATION_ENABLED`, default OFF. | (part of `EXTERIOR-GUEST-FACE-FASTFOLLOW-1`) | — |

---

## 3. Entity inventory (NAME EVERYTHING)

All `entity_id`s below were grep-confirmed in `sensor.py` **and** confirmed present on the live HA instance 2026-08-18 unless flagged. Note the naming split that previously misled audit docs: the **unique_id fragment is NOT the entity_id**. The exterior sensors have unique_ids `{DOMAIN}_exterior_person_tracks_active` / `{DOMAIN}_exterior_unidentified_persons`, but their live entity_ids are `sensor.ura_security_coordinator_outside_*` (derived from the Security Coordinator device + friendly name). The old audit slugs `sensor.…exterior_person_tracks_active` / `…exterior_unidentified_persons` **do not exist as entity_ids** — do not use them.

### Interior census

| entity_id | Friendly name | Kind | Meaning | Key attributes | Cycle |
|---|---|---|---|---|---|
| `sensor.universal_room_automation_persons_in_house` | Persons In House | sensor | Deduped interior head-count (the headline count). | `identified_count`, `unidentified_count`, `count_as_of` (single ISO stamp), `peak_held`, `peak_age_seconds`/`peak_age_minutes`, `peak_refresh_suppressed_count` (self-refresh-suppression counter, live=2031), `face_lookup_missing_count` (fail-closed face-miss counter, live=12), `camera_total_pre_cancel`, `ble_cancelled_count`/`ble_by_area`/`ble_cancel_enabled`, `wifi_guest_floor`, `enhanced_census` | base; `peak_*`/`count_as_of`/`peak_refresh_suppressed_count` added v5.80.0; `face_lookup_missing_count`/pre-cancel diagnostics v5.79.0/v5.80.0 |
| `sensor.universal_room_automation_identified_persons_in_house` | Identified Persons In House | sensor | The count of interior persons with a resolved identity. | — | base (governed by arc) |
| `sensor.universal_room_automation_unidentified_persons_in_house` | Unidentified Persons In House | sensor | Interior persons seen but not identified; the value that gated guest exit before v5.79.0 D2b. | — | base (governed by arc) |
| `sensor.universal_room_automation_unidentified_persons` | Unidentified Persons | sensor | Reads `persons_in_house` to surface unidentified count (egress/census consumer). | — | base (governed by arc) |

### Egress (entry/exit crossings)

| entity_id | Friendly name | Kind | Meaning | Key attributes | Cycle |
|---|---|---|---|---|---|
| `sensor.universal_room_automation_persons_entered_today` | Persons Entered Today | sensor | Count of entry crossings today; carries egress-identity observability. | `entries` (list), `last_reset`, **`egress_face_ids_active`** (live set size), **`egress_identities_stamped`** (cumulative) | egress attrs added v5.81.0 |
| `sensor.universal_room_automation_persons_exited_today` | Persons Exited Today | sensor | Count of exit crossings today (sibling of entered-today). | `entries` (list), `last_reset` | base; identity path v5.81.0 |
| `sensor.universal_room_automation_last_person_entry` | Last Person Entry | sensor | Most-recent entry crossing. **VERIFIED IN SOURCE** (`sensor.py:4352`); not separately live-queried this pass. | — | base |
| `sensor.universal_room_automation_last_person_exit` | Last Person Exit | sensor | Most-recent exit crossing. **VERIFIED IN SOURCE** (`sensor.py:4400`); not separately live-queried this pass. | — | base |

### Exterior (property perimeter)

| entity_id | Friendly name | Kind | Meaning | Key attributes | Cycle |
|---|---|---|---|---|---|
| `sensor.ura_security_coordinator_outside_people_being_tracked` | Outside: People Being Tracked | sensor | **Deduped** exterior person count (track-based). | (state only) | base; dashboarded v5.80.0 D3 |
| `sensor.universal_room_automation_persons_on_property_exterior` | Persons On Property (Exterior) | sensor | **Naive floor** — exterior head-count from the census producer (KEEP-BOTH pairing with the deduped headline; divergence is the signal). | `confidence` (live=medium), `source_agreement` (live=single_source), `last_updated` | base; KEEP-BOTH dashboards v5.80.0 D3 |
| `sensor.ura_security_coordinator_outside_unidentified_people` | Outside: Unidentified People | sensor | Exterior persons tracked but not identified. | (state only) | base; dashboarded v5.80.0 D3 |
| `sensor.universal_room_automation_total_persons_on_property` | Total Persons On Property | sensor | Interior + exterior union. | — | base (governed by arc) |

### House state

| entity_id | Friendly name | Kind | Meaning | Key attributes | Cycle |
|---|---|---|---|---|---|
| `sensor.ura_presence_coordinator_presence_house_state` | URA: Presence Coordinator Presence House State | sensor | Authoritative house state (`away`/`home_*`/`sleep`/**`guest`**). The sensor whose value proves the guest-mode fix. | `census_count`, `face_recognized_count`, `path_alpha_gate_source`, `tracked_persons_count`, `tracked_persons_count_trusted`, `all_tracked_persons_away`, `last_veto_decision`, `veto_path` | consumes arc; `face_recognized_count`/`path_alpha_gate_source` relevant to v5.79.0/v5.80.0 |

### Guest

| entity_id | Friendly name | Kind | Meaning | Key attributes | Cycle |
|---|---|---|---|---|---|
| `sensor.ura_security_coordinator_security_authorized_guests` | URA: Security Coordinator Security Authorized Guests | sensor | The real guest sensor — sanction-checker authorized guests + expected arrivals. State is `none` or `"N guests"`. | `guests`, `expected_arrivals`, `guest_count`, `arrival_count` | base (governed by arc) |

> **Note on "the guest-count sensor":** there is **no** `ZoneGuestCountSensor` class or dedicated per-zone guest-count entity in `sensor.py`. Guest *mode* is a value of `presence_house_state` (`guest`), not a count. The authoritative guest **sensor** is `SecurityAuthorizedGuestsSensor` → `sensor.ura_security_coordinator_security_authorized_guests` (verified live). A secondary `guest_count` figure (`max(0, camera_total − ble_total)`) exists only as an **attribute** inside `binary_sensor.py:1584`, and `wifi_guest_floor` is an attribute on `persons_in_house` — neither is a standalone entity.

### Planned control switches — **NOT YET SHIPPED**

Confirmed **absent** on the live instance 2026-08-18 (a `switch` domain search for all three returned zero matches). Do not treat as live. Names LOCKED (operator-approved) per `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1`; each relocates an existing Camera-Census options-flow flag to a device switch (source of truth stays the config-entry option; switch writes it back + reloads):

| entity_id (PLANNED) | Friendly name | Kind | Backing flag | Scope |
|---|---|---|---|---|
| `switch.ura_presence_face_matching` | Presence Face Matching | switch (PLANNED) | `CONF_FACE_RECOGNITION_ENABLED` | Scoped: transit_validator + presence zone confirm ONLY (NOT a global face kill switch) |
| `switch.ura_smart_people_counting` | Smart People Counting | switch (PLANNED) | `CONF_ENHANCED_CENSUS` | Swaps the census engine — the "heavy" one; requires integration reload to apply |
| `switch.ura_name_people_at_doors` | Name People at Doors | switch (PLANNED) | `CONF_EGRESS_IDENTITY_ENABLED` | Live-readable (kill switch designed live in v5.81.0); no reload needed |

---

## 4. Controls / knobs

| Knob | Kind / rung | Default | Purpose |
|---|---|---|---|
| `CONF_EGRESS_IDENTITY_ENABLED` | options-flow bool (rung 2), kill switch | **False** | Master switch for egress face-identity (v5.81.0). When OFF the resolver returns None, register is a no-op, normalization is skipped → both census fuse sites byte-identical to pre-cycle. To be promoted to `switch.ura_name_people_at_doors`. |
| `FACE_MATCH_WINDOW_S` | module constant (rung 1) | 60 | Freshness window for the face recognized on a crossing camera's stem; older → `person_id=None` (v5.81.0). |
| `EGRESS_FACE_UNION_TTL_S` | module constant (rung 1) | 300 | TTL of the `egress_face_ids` set unioned into the census identity set (v5.81.0). |
| `GUEST_KNOWN_STICKY_S` | module constant (rung 1) | 120 | Sticky latch absorbing BLE room-location flap in the repaired identity re-check; `0` disables the latch (base check still runs) (v5.79.0). |
| `GUEST_BOOT_SEED_MIN_RESIDUAL_S` | module constant (rung 1) | 300 | Minimum dwell that must remain after a boot-seed so an erroneous seed can't fire instantly; `≥ threshold` disables the seed, `0` disables only the clamp (v5.79.0). |
| `CONF_CENSUS_HOLD_INTERIOR` | options-flow (rung 2) | 3 min | Governs *when* interior decay starts. v5.80.0 D1 changed the decay *shape* (instant-drop), not this hold; may be tuned 3→1 via options, no code. |
| `CONF_FACE_RECOGNITION_ENABLED` | options-flow bool (rung 2) | — | Scoped face-matching flag (transit_validator + presence confirm). To be promoted to `switch.ura_presence_face_matching`. |
| `CONF_ENHANCED_CENSUS` | options-flow bool (rung 2) | — | Selects the additive (enhanced) census engine. To be promoted to `switch.ura_smart_people_counting`. |
| `PROTECT_CORROBORATION_ENABLED` | kill switch (GATED, planned) | **False** | Master switch for the gated D2 Protect second-source corroboration. |

Retired: `CENSUS_DECAY_STEP_SECONDS` (tombstoned in v5.80.0 — its only reader was the deleted decay slope). `CENSUS_PEAK_SUSTAIN_SECONDS` / `DEFAULT_CENSUS_HOLD_INTERIOR_MINUTES` remain as the latch/hold constants referenced by the v5.79.0 analysis.

---

## 5. Open / gated / parked

**Gated — D2 Protect corroboration.** Second NVR face source (UniFi Protect), hard-gated on a real captured `ura_kp_face_probe_received` webhook payload (`webhook_id ura_kp_face_probe`, local-only POST to `http://192.168.13.13:8123/api/webhook/ura_kp_face_probe`). Operator ruling: **no cron** — the probe automation fires the event + logs the payload on the next family-room recognition; evaluated as a session-pickup gate once the recorder holds the payload. Kill switch `PROTECT_CORROBORATION_ENABLED` default OFF.

**Planned — device switches.** `CENSUS-TOGGLES-TO-DEVICE-SWITCHES-1` (Tier 2 plan on file at `docs/planning/PLANNING_census_toggles_to_device_switches.md`). Three `SwitchEntity` on the integration device; source-of-truth = config-entry option (Option B) with reload for the two boot-cached consumers. One plan review then build.

**Parked fast-follows:**
- `EGRESS-INTERIOR-COUNT-REINFORCE-1` — reinforce the interior head-count from egress-derived identity. Gated on D1 (v5.81.0) accuracy landing organically.
- `EXTERIOR-DWELL-LOITER-1` — exterior circling/dwell-loiter detection; shares the `_2`-suffix face-ID revival (a real dependency on v5.80.0 D2), revisit once face-ID is confirmed live-resolving.

**Open live-validation items (organic-pending, residents return Wed PM):**
- **v5.79.0 L3/L8** — the discriminating dead-oracle proofs: a **resident** physically in a designated guest room (Guest Bedroom 1 or Upstairs Guestroom) must **not** arm GUEST (boot path L3 + steady-state L8). Cannot be produced against an empty house.
- **v5.80.0 L3/L4** — fresh-face revival (`face_recognized_count > 0` on occupancy; `face_lookup_missing_count` interpreted, carded `CENSUS-FACE-MISS-WATCH-1` — 12/tick on an empty house) and census-vs-ground-truth accuracy.
- **v5.81.0 L2/L3** — flip `CONF_EGRESS_IDENTITY_ENABLED=True`, then confirm a real entry crossing carries the resident's URA slug (`egress_identities_stamped` increments; stale-face crossing → `person_id=None`) and a resident **exiting** raises no phantom identified/guest (`egress_face_ids_active` flat on exits).

Each per-version README carries its own post-restart validation table; L1 (boot-clean / dormant / observable) is PASS on all three, and each cycle stays open until the occupancy-gated criteria land.
