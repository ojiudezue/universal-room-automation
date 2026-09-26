# Thermostat Definition — Carrier / Bryant (via `ha_carrier` v2.28.4)

**Rev 2 — 2026-09-26 (folds W1-B build-prediction + completeness plan reviews, incl. C20 refutation
of the status/config coherence premise, C16 shared-guard wipe, C17 TTL correction, and F16 spec
corrections).**

**Status:** discovered-behaviour spec for the Bryant/Carrier Infinity zone thermostats served by the
HACS `ha_carrier` integration (`dahlb/ha_carrier`) as installed on the live system.
**Read together with:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §1, §2 (C18), §5, §6,
§7 (C17), §9.1 (C20), §10 (C15/C16/C17/C20).
**Sources cited absolutely:** paths under
`/Users/okosisi/ha-config/custom_components/ha_carrier/` (`climate.py`, `const.py`,
`carrier_data_update_coordinator.py`). Version constant `const.py:5` = `"2.28.4"`.
**All claims not proven live are marked UNVERIFIED.** Anything the operator disputes gets a §10
correction row.

---

## 0. Fingerprint — how to detect this strategy applies

Detection is by **entity-registry `platform` field**, NOT by integration name string match on
attributes and NOT by entity_id. Look up the entity in `hass.data['entity_registry']` (or via
`homeassistant.helpers.entity_registry.async_get`) and read `RegistryEntry.platform`. A value of
`ha_carrier` means the Carrier strategy applies. Cache the strategy per BRAND, keyed by that
platform string — the operator's account carries THREE single-zone systems (each system a distinct
Carrier device), all under one integration platform, so two different Carrier climate entities
share ONE strategy instance. Do NOT cache a fallback (generic default) — a transient registry miss
must not permanently poison a Carrier entity into the generic path.

| Signal | Source |
|---|---|
| Registry platform `ha_carrier` | HA entity registry |
| HA integration domain `ha_carrier` on the entity's config entry | `const.py:8` `DOMAIN = "ha_carrier"` |
| Climate entity class `Thermostat` (subclass of `CarrierClimate`) | `climate.py:276-317` |
| Extra state attribute `hold_activity` present | `climate.py:261-269` |
| Service `ha_carrier.set_activity_setpoint` registered | `climate.py:91-104` (upstream PR #427) |
| `preset_modes` includes `resume` | `climate.py:317-318` |

**Live account shape (C16 / F9):** ONE `ha_carrier` account, THREE Carrier SYSTEMS, each with ONE
zone (zone_1/zone_2/zone_3 map to distinct systems on this install). The post-write guard
(§5) is keyed `(system_serial, zone_api_id)` and covers each system independently, but the
account-level websocket / coordinator refresh IS SHARED — a `resume` or full-refresh action against
any system can wipe intercept state on the others (see C16 wipe triggers below).

---

## 1. Preset write — `climate.set_preset_mode(preset)`

**Behaviour** (`climate.py:398-438`):
- `preset == "resume"` -> integration calls `resume_schedule` (`:405-416`), sets
  `coordinator.data_flush = True`, and forces an `async_refresh`. This DROPS any active hold and
  hands the zone back to its comfort schedule. **Wipe hazard (C16):** the flush + refresh is
  account-wide — any live post-write intercept guards for OTHER zones/systems on this account can
  be wiped by the resulting reconcile pass. See §5.
- `preset in {home, away, sleep, wake, vacation, manual}` -> integration calls
  `set_config_hold(activity_type=preset, hold_until=self._hold_until)`, then optimistically applies
  the hold to the local `_config_zone` (`:431-438`).
- `hold_until` is `None` (indefinite) when the config-entry option `infinite_holds` is True, else
  the next scheduled activity time (`:382-396`). **Live: `infinite_holds=True`**
  (`const.py:19-20` default; live config entry option confirmed §8 state-of-play).

**Known hazard already partially mitigated by v5.103.2 resume-then-pin (`hvac_setpoint.py:288-410`):**
if the zone is sitting on an anonymous `manual` hold, the cloud will keep the *manual profile*'s
setpoints and DISCARD the new preset NAME. Clearing with `resume` before pinning is what makes
named writes stick. The funnel decides whether to resume by reading `hold_activity` — but that
attribute may not yet reflect a just-written hold, so the "do I need to resume?" decision is
racy (see §6 and §9 UNVERIFIED items).

**Named preset -> setpoints mapping:** the `home / away / sleep / wake / vacation` presets each
correspond to a Carrier "activity profile" stored server-side. After a preset write, HA re-reads
setpoints via `find_activity(preset)` and refreshes the local status zone from it (`:435-438`).
**ha_carrier does NOT expose the per-activity profile setpoints as attributes** on the climate
entity or elsewhere in a stable, queryable form — so URA CANNOT compare an observed manual hold's
setpoints against a named profile's setpoints from the outside (F5 / F16). This kills any
"observed setpoints equal a named profile -> it's the profile ghost" classifier as unimplementable
against the integration surface.

**UNVERIFIED:** exact `hold_until` behaviour when `infinite_holds=False`. Not exercised live.

---

## 2. Raw setpoint write — `climate.set_temperature(...)`

**Behaviour** (`climate.py:467-537`) — **TWO API calls, not one; can raise (F16 correction):**

1. Resolves values against system mode (COOL: only high used; HEAT: only low used; HEAT_COOL:
   both `target_temp_low` and `target_temp_high` must be provided). Missing values are filled
   from the MANUAL activity profile in COOL/HEAT (`:486-491`); in **HEAT_COOL, both must be
   supplied or the call `raise HomeAssistantError(...)` at `:493-496`** — URA cannot pass just one
   in HEAT_COOL mode.
2. **API call 1:** `set_config_manual_activity(heat_set_point, cool_set_point, fan_mode)` -> rewrites the MANUAL activity profile setpoints server-side (`:507-517`).
3. **API call 2:** `set_config_hold(activity_type=MANUAL, hold_until=_hold_until)` -> sets the zone hold to MANUAL (`:518-527`).
4. Optimistic local mutation: `_config_zone.hold = True`, `_config_zone.hold_activity = MANUAL`,
   `_status_zone.current_status_activity_type = MANUAL`, and the manual activity profile's own
   `heat/cool_set_point` are also updated locally (`:529-537`).

**Consequence — invariant:** every raw `set_temperature` write forces the zone into an anonymous
`manual` hold. There is no "just change the number without a hold" via this verb; that's
`set_activity_setpoint` (§3).

**Two API calls means partial-failure surface (F7):** API call 1 succeeding + call 2 failing
leaves the manual profile mutated on the server but hold state unchanged. The `auto_release_on_incomplete`
sweep at `hvac_excursion.py:1322` was written for exactly this partial-write case; the definition
must document that a `set_temperature` write is not atomic and site code must treat "the write
returned normally" as "both API calls landed" only in the happy path.

---

## 3. Raw setpoint write, no-hold variant — `ha_carrier.set_activity_setpoint`

**Provenance (C15):** upstream PR #427 by Evan Weaver, merged 2026-08-31, commit `4d833486`. Ships
in v2.28.4 as installed via HACS from `dahlb/ha_carrier` @285f915; HACS updates preserve it. The
literal "PATCH" string in `climate.py:91-104` and `:540` is upstream's own wording, not a local
mutation.

**Behaviour** (`climate.py:539-596`):
- Registered as an entity service (`climate.py:91-104`), not a platform verb — URA calls it as
  `hass.services.async_call("ha_carrier", "set_activity_setpoint", {"entity_id": ..., ...})`.
- Edits the setpoints of the **STATUS-named current activity** (`_current_activity()` at `:551`,
  which resolves through `_config_zone.current_status_activity(_status_zone)` at `climate.py:136-142`,
  i.e. keyed on `_status_zone.current_status_activity_type`) via
  `set_config_activity(activity_type=current.type, ...)`.
- Explicit comment (`climate.py:591`): "deliberately do NOT touch any hold_* /
  current_status_activity_type". Hold state UNCHANGED (whatever it was).
- **DOES open a post-write intercept guard** (F16 correction against the prior rev's UNVERIFIED
  claim): the method's final `_write_local_state()` at `:596` triggers `begin_post_write_intercept`
  via the base class, snapshotting the CURRENT activity type and current-activity setpoints. So the
  integration's own 5-min guard protects the last-written activity's setpoints against a cloud
  revert.

**Consequence — "no-hold nudge" option:** URA can nudge setpoints on an already-named-hold zone
without laundering the hold through MANUAL.

**Interrupted-edit hazard (load-bearing):** this verb MUTATES the named activity profile itself.
If a URA restart, HA restart, network partition, or exception hits between the nudge write and the
intended restore, the "Home" profile is now `home + 1.5°F` FOREVER — the vendor schedule keeps
using it, the app displays it, and there is no external way to know it was tampered with.

**Design implication for W1-B:** the operator brief (Q1) recommends KEEPING nudges on
`set_temperature` (§2) and not adopting `set_activity_setpoint` in this cycle. If a future cycle
adopts it, restore MUST be attempted at multiple safety points (per-cycle sweep + boot audit)
against a persisted snapshot of the pre-write profile setpoints — and the interruption hazard
must be spelled out in the site's card.

---

## 4. Read model — what HA (and URA) sees back

### 4.1 `preset_mode` — from the STATUS feed
`_preset_mode()` returns `_current_activity().type.value` from
`_config_zone.current_status_activity(_status_zone)` (`climate.py:136-142`, `:158-172`, exposed
`:247`). The STATUS feed's setpoints go stale between full polls (integration comment `:222-229`);
temperature is realtime via websocket but activity type / setpoints are not. So `preset_mode` can
lag until the next full reconcile.

### 4.2 Setpoints displayed — from the STATUS-NAMED activity, resolved via CONFIG
`_update_entity_attrs` (`:222-240`) reads `target_temperature_high/low` from
`_current_activity() or _status_zone`. Two consequences:
- If STATUS names `manual`, the displayed setpoints are the MANUAL activity profile's setpoints
  (which the last raw `set_temperature` write mutated).
- The numeric setpoint values come from CONFIG (the comment says CONFIG tracks changes promptly),
  so numbers refresh even when the *name* is stale.

### 4.3 `hold_activity` — from the CONFIG feed — **NOT authoritative for "who wrote this"**
Extra state attribute at `climate.py:261-269`: `_config_zone.hold_activity.value`. CONFIG is
updated on every write (`set_preset_mode` at `:432`, `set_temperature` at `:530`), so it reflects
what hold the thermostat is CURRENTLY carrying.

**CRUCIAL CORRECTION — C20 measurement 2026-09-26:** the prior rev of this doc (and the W1-B plan
rev 1) proposed classifying manual as URA's echo when `preset_mode == "manual"` disagreed with
`hold_activity` naming a preset. **That premise is refuted.** In all five zone_1 strand incidents
inspected, `hold_activity` ALSO read `manual` — same second as status in 3/5, within 5 min in the
other 2 — and stayed manual for hours (09-22 strand: 410/417 recorder samples both manual/manual).
These are GENUINE Carrier-side manual holds created shortly after URA's own borrow return, not
status-lag artifacts. **The status/config coherence rule is WITHDRAWN.** URA MUST classify
manual by PROVENANCE (does URA have an in-window write whose values match?), not by feed
coherence.

**How `hold_activity` IS used going forward:** it is a legitimate read of what hold the thermostat
carries right now — informative for logging and for the resume-decision inside the funnel — but it
is NOT a discriminator between URA-echo and genuine-human hold. A `config manual` observation
AFTER a URA NAMED preset write is always a HUMAN hold (F9): the named write set config to the
named preset; a subsequent `manual` must have been placed by something else.

### 4.4 `hvac_mode` — from `_config_zone.mode` mapped to HA modes
`climate.py:181-194`. Prompt on write via optimistic local mutation (`:379-380`), reconciled by
polls / websocket. **Mode writes DO snapshot stale status (F9 detail):** `_write_local_state` on
`set_hvac_mode` opens a system-level guard (zone_api_id=None) whose snapshot is the mode value, not
any zone-level activity — so a mode write can carry along whatever stale status the coordinator
was serving at snapshot time. URA cannot rely on the guard to keep zone activity attrs coherent
across a mode change.

### 4.5 `hvac_action` — from `_status_zone.conditioning`
`climate.py:200-216`: `HEATING` / `COOLING` / `IDLE` / `OFF` / `FAN`. Straight from status.

### 4.6 `next_activity_time` — from CONFIG
Exposed as extra attr (`climate.py:271`); recorder history of this value dated the schedule
removal (state-of-play §5).

---

## 5. Refresh / latency model — corrects URA's rough "42-79 s"

**Coordinator polling** (`carrier_data_update_coordinator.py:130-143`):
- `update_interval = DEFAULT_UPDATE_INTERVAL_MINUTES = 30` (`const.py:46`).
- Websocket is the fast path for temperature.

**Full reconcile floor** (`const.py:47-52`, `coordinator.py:145-160`):
- `FULL_RECONCILE_INTERVAL_MINUTES = 120`. Every fourth poll forces a full pull.

**Post-write intercept window** (`const.py:53-59`, `coordinator.py:162-296`):
- `POST_WRITE_INTERCEPT_WINDOW_MINUTES = 5`.
- Guards keyed `(system_serial, zone_api_id)` with a system-level mode guard `(system_serial, None)`.
- `_reassert_control` runs after each websocket message; restores reverted activity type +
  heat/cool_set_point for a guarded zone; restores mode for a guarded system.
- **Guard COVERS:** `current_status_activity_type`, `heat_set_point`, `cool_set_point` (zone),
  `config.mode` (system).
- **Guard DOES NOT COVER `hold_activity`** (F9 correction): the guard reads
  `_capture_zone_state` (`coordinator.py:210-227`) which snapshots activity_type + setpoints only.
  A cloud-side flip of `hold_activity` is NOT re-asserted by the integration. This matters
  directly to the strand mechanism: even if URA's named pin succeeded, the cloud can move
  `hold_activity` back to `manual` and the integration will not stop it.

**Wipe triggers (C16):** the intercept state is per-target, but a broad refresh can end early or
supersede all guards. Documented triggers that can effectively wipe a live guard on THIS account:
- Any `resume_schedule` call sets `coordinator.data_flush = True` and triggers `async_refresh`
  (`climate.py:414-415`). The refresh pulls fresh data on all systems.
- Full-reconcile ticks (every 120 min) pull authoritative state that overrides guarded values IF
  cloud has moved on and the guard has expired.
- Websocket disconnect / reconnect + any URA-triggered `ha_carrier` reload (URA calls it at
  `hvac.py:5328-5463`) rebuilds coordinator state fresh; existing guards are lost.
- A subsequent write to the same target UPSERTS its own guard, replacing snapshot values.

**Reconciliation of URA's "42-79 s" (C16):** that number is URA's empirical effective refresh
window observed during v5.103.2's resume-then-pin work (`hvac_override.py:147-150`). The
integration's DECLARED schedule is 30 min poll / 120 min full reconcile / 5 min post-write guard.
Treat 42-79 s as advisory, not a design invariant.

**Composition with URA's suppression (C17 correction):** URA's arrester has TWO windows —
`SUPPRESS_TTL_SECONDS = 5` for TEMPERATURE writes (deliberately short so a human at the dial is
still seen, `hvac_override.py:129`, `:141-146`) and `SUPPRESS_TTL_SECONDS_PRESET = 120` for PRESET
writes (`hvac_override.py:153`). The 5-s temperature TTL vs the 5-min ha_carrier guard vs the
40-80 s Carrier cloud refresh means URA's own late setpoint echoes can arrive OUTSIDE the URA
suppression window while STILL INSIDE the ha_carrier guard — the guard's snapshot is what the
integration will keep serving even if URA's arrester has already booked an override on the echo.
How the two windows interact under back-to-back nudge/restore writes remains **UNVERIFIED** and is
D0 of the plan.

---

## 6. Anonymous vs named hold — the invariant that governs W1-B

**Anonymous hold** = `hold_activity == "manual"`. **Named hold** = `hold_activity ∈ {home, away,
sleep, wake, vacation}`.

**Write-verb effects on hold state:**
| Verb | End state |
|---|---|
| `set_preset_mode("home"\|"away"\|"sleep"\|...)` on an already-named-hold zone | named hold |
| `set_preset_mode("home"\|...)` on an anonymous-hold zone WITHOUT `resume` first | **name discarded** — hold stays `manual`, setpoints become the manual profile's setpoints (measured live 2026-09-16 §5 state-of-play + `hvac_setpoint.py:324-354`) |
| `set_preset_mode("home"\|...)` on an anonymous-hold zone WITH `resume` first | named hold (v5.103.2 landed this) |
| `set_preset_mode("resume")` | no hold — zone follows vendor schedule; also flushes coordinator + refreshes (C16 wipe hazard) |
| `set_temperature(...)` (stock) | anonymous `manual` hold at the requested setpoints (2 API calls; can raise in HEAT_COOL when only one setpoint supplied) |
| `set_activity_setpoint(...)` (PR #427) | hold state UNCHANGED; STATUS-named activity setpoints mutated in place; opens a 5-min guard |
| `set_hvac_mode(...)` | hold state UNCHANGED; opens a system-level guard whose snapshot uses whatever stale status was current |

**Vendor-schedule race footnote (§10 C12):** zone_1 has one remaining 06:00 Home entry; zones 2/3
still run 4-entry schedules. `resume` briefly hands the zone to the vendor schedule between the
resume and the pin. Working assumption is the operator will reduce zones 2/3 schedules further;
no code-side guard in W1-B (Q2 recommendation).

---

## 7. What Carrier does NOT expose (and W1-B must not assume)

- **No writer attribution.** Every change reaches HA via the integration with no user/parent
  context (measured 2026-09-25, §4.3 state-of-play).
- **No per-activity profile setpoints as queryable attributes.** URA cannot compare an observed
  manual hold's setpoints against a named profile's setpoints from outside (§1, F5). Any
  "matches a named profile" classifier is unimplementable against ha_carrier's surface. Provenance
  (URA remembers what it wrote) is the only workable ownership signal.
- **No hold-expiry attribute independent of `hold_until`;** with `infinite_holds=True` that is
  always `None`.
- **No API to query the schedule.** `next_activity_time` names the *next* transition only.
- **No "reject if newer" semantics.** Late writes clobber older ones; the coordinator's post-write
  intercept is the only guard.
- **The post-write guard does NOT protect `hold_activity`** (§5 F9) — a cloud-side flip of the
  hold field is not re-asserted.

---

## 8. Live config — the values we actually run against

| Fact | Live value | Source |
|---|---|---|
| `ha_carrier` version | 2.28.4 | `const.py:5` |
| `CONF_INFINITE_HOLDS` option | **True** | config entry option (state-of-play §8) |
| `DEFAULT_UPDATE_INTERVAL_MINUTES` | 30 | `const.py:46` |
| `FULL_RECONCILE_INTERVAL_MINUTES` | 120 | `const.py:52` |
| `POST_WRITE_INTERCEPT_WINDOW_MINUTES` | 5 | `const.py:59` |
| Account topology | 1 account, 3 systems, 1 zone per system | recorder + `.storage/core.config_entries` |
| Zone entities | `climate.thermostat_bryant_wifi_studyb_zone_1`, `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3` | state-of-play §1 |
| Zone_1 schedule remaining | one 06:00 Home 70/76 entry (post 2026-09-20 11:39 removal) | recorder `next_activity_time` |
| Zones 2/3 schedules | 4-entry (06/08/17-18/22) | recorder |
| Preset modes advertised per zone | `[home, away, sleep, wake, vacation, manual, resume]` | live-verified 2026-08-21 + `climate.py:317-318` |

---

## 9. Every UNVERIFIED item — MUST be resolved or explicitly parked by W1-B D0

1. **The leading strand mechanism itself.** Working hypothesis (§9.1 state-of-play): the return's
   raw setpoint write creates an anonymous manual hold, and the following named pin is
   discarded/reverted because either (a) the funnel's resume decision reads `hold_activity`
   BEFORE the config feed reflects the just-written manual (race), or (b) `resume` cleared the
   hold but ha_carrier's post-write guard for the pending named-pin snapshot was wiped
   account-wide by the `data_flush` refresh (C16), or (c) the cloud reverts the named pin within
   the 42-79 s window and the guard doesn't cover `hold_activity`. **D0 of the W1-B plan is a
   one-shot read-only probe designed to discriminate (a) vs (b) vs (c) against existing
   `ac_ramp_events` + `ura_activity_log` + recorder rows.**
2. **How URA's 5-s temperature suppression and ha_carrier's 5-min guard compose** under
   back-to-back nudge/restore writes. §5. Falls out of the D0 probe.
3. **Whether the physical thermostat was actually in `manual`** during the strands. Only what
   ha_carrier reported is known; a thermostat-face read from the incident times does not exist.
   Operator can spot-check the next occurrence (§10 Q7-adjacent).
4. **Onset lag** — how long between URA's return sequence completing and the appearance of the
   config-side manual hold. D0 probe measurement.
5. **`hold_until` semantics with `infinite_holds=False`.** Not exercised live.
6. **Interruption behaviour of `set_activity_setpoint` end-to-end.** Not empirically tested; the
   spec §3 hazard is derived from source, not measured.
7. **Vendor-schedule race timing near 06:00 on zone_1.** UNVERIFIED whether it has ever misfired
   live in the resume-then-pin path.

---

## 10. What this definition owes W1-B

The Carrier strategy MUST implement, and its tests MUST discriminate:

1. **Preset write** = resume-then-pin when needed (`hold_activity == "manual"` AND entity
   advertises `resume`); direct pin otherwise. Existing code at `hvac_setpoint.py:288-410` is
   lifted into the strategy.
2. **Borrow return** = **presets-only when the snapshot preset is a NAMED profile**. No preceding
   raw setpoint write; the named profile carries its own setpoints. Snapshot preset `manual`
   falls back to setpoints+preset (there is nothing to pin cleanly onto).
3. **Manual ownership by PROVENANCE, not coherence.** An observed manual hold is URA-owned iff
   URA's last write to that entity was a `set_temperature` (or `set_activity_setpoint` if ever
   adopted) whose values match what is observed, with NO named preset write since. Coherence-based
   classification (`URA_ECHO_MANUAL` when `hold_activity` names a preset) is WITHDRAWN — C20
   measurement refutes its premise.
4. **URA-owned reclaim** = a URA-owned manual with NO active borrow is reclaimable after a
   configurable DELAY (default one decision tick; separate kill switch). Never reclaim while a
   borrow is live.
5. **No-op write suppression** only when (a) the intended values equal the last URA write to that
   entity for that verb AND (b) the observed state equals those values. Any actual write clears
   every verb's last-write record for the entity. Observed divergence from the last-write record
   clears it. Re-asserts / reclaims are exempt from suppression.
6. **Snapshot correctness** — the snapshot the return re-asserts against must be a
   provenance-aware or genuine-human read of `preset_mode`, NEVER a raw `preset_mode` attribute
   value at snapshot time (a raw read of `manual` snapshots the wrong thing).

Anything the strategy does not know how to answer (unknown brand, no `hold_activity`) falls through
to the generic default = direct pin, no clear, provenance-only ownership on the standard climate
attributes.
