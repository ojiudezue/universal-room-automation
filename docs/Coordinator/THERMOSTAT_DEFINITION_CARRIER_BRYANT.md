# Thermostat Definition — Carrier / Bryant (via `ha_carrier` v2.28.4)

**Status:** discovered-behaviour spec for the Bryant/Carrier Infinity zone thermostats served by the
HACS `ha_carrier` integration (`dahlb/ha_carrier`) as installed on the live system, forensic snapshot
2026-09-26. Read this together with `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §5, §6,
§7, §10.

**Purpose:** ground the Carrier implementation of the W1-B per-brand thermostat definition. Every
claim below cites its source file:line (path `/Users/okosisi/ha-config/custom_components/ha_carrier/`,
same tree that ships as v2.28.4) or a dated live measurement / recorder read. Anything not proven is
marked **UNVERIFIED** and must be verified before code depends on it.

**Scope:** Bryant is a Carrier badge — same firmware / same cloud / same integration; the
integration itself is brand-agnostic within the Infinity family. This spec covers both.

---

## 0. Fingerprint — how to detect that this definition applies

| Signal | Source |
|---|---|
| HA integration domain `ha_carrier` on the climate entity's config entry | `const.py:8` `DOMAIN = "ha_carrier"` |
| Climate entity class `Thermostat` (subclass of `CarrierClimate`) | `climate.py:276-317` |
| `preset_modes` list contains `resume` (advertised in addition to the zone's activity types) | `climate.py:317-318` `_attr_preset_modes = [...activities...] + ["resume"]` |
| Extra state attribute `hold_activity` present | `climate.py:261-269` |
| Service `ha_carrier.set_activity_setpoint` registered | `climate.py:91-104` (upstream PR #427) |

The Carrier strategy must key on `ha_carrier` (domain), NOT on the entity name. Any other integration
that also advertises `resume` is a different strategy — see the generic default in the planning doc.

---

## 1. Preset write — `climate.set_preset_mode(preset)`

**Behaviour:**
- `preset == "resume"` -> the integration calls `resume_schedule` (`climate.py:405-416`) and forces
  a coordinator refresh. This DROPS any active hold and hands the zone back to its comfort
  schedule.
- `preset in {home, away, sleep, wake, vacation, manual}` -> the integration calls
  `set_config_hold(activity_type=preset, hold_until=self._hold_until)` and optimistically applies
  the hold to the local `_config_zone` (`climate.py:418-438`).
- `hold_until` is `None` (indefinite) when the config-entry option `infinite_holds` is True, else
  the next scheduled activity time (`climate.py:382-396`). **Live: `infinite_holds=True`**
  (const default, `const.py:19-20`; live config entry confirmed §8).

**Key hazard already known to URA (v5.103.2 resume-then-pin, `hvac_setpoint.py:288-410`):** if the
zone is sitting on an anonymous `manual` hold, the cloud will keep the *manual profile's setpoints*
and DISCARD the new preset NAME. Clearing with `resume` before pinning is what makes named writes
stick. See §6.

**Named preset -> setpoints mapping:** the `home / away / sleep / wake / vacation` presets each
correspond to a Carrier "activity profile" stored server-side. The setpoints returned to HA after
the pin come from `_config_zone.find_activity(preset)` (`climate.py:435-438`), i.e. the comfort
profile associated with that activity — NOT from any URA-supplied value. Writing a preset does not
push new setpoints; the profile's own setpoints ride along.

**UNVERIFIED:** the exact `hold_until` behaviour when `infinite_holds=False` after a preset write —
whether the zone drops out of hold at the next scheduled activity time or holds indefinitely with a
displayed expiry. Live is `True` so this does not matter today, but do not assume.

---

## 2. Raw setpoint write — `climate.set_temperature(target_temp_low, target_temp_high)`

**Behaviour** (`climate.py:467-537`):
1. Resolves the values against system mode (COOL: only high used; HEAT: only low used; HEAT_COOL:
   both). Missing values are filled from the MANUAL activity profile (`:486-496`).
2. Calls `set_config_manual_activity(...)` -> **rewrites the MANUAL activity profile's setpoints**
   server-side.
3. Calls `set_config_hold(activity_type=MANUAL, hold_until=_hold_until)` -> sets the zone hold to
   MANUAL.
4. Optimistically applies to `_config_zone` AND to the manual activity profile locally
   (`:529-537`).

**Consequence — invariant:** every raw setpoint write forces the zone into an anonymous `manual`
hold. There is no "just change the number without a hold" via this verb. This is the reason S5 nudge
start and S6 nudge restore (both raw setpoints, `hvac_override.py:4423`, `:4595`) leave the zone in
`manual` mid-borrow and rely on the closing preset write to name it again.

**Failure mode carried to URA (§9.1 state-of-play):** after a raw-setpoint borrow returns, the
integration can serve a lagging status (§4) that says `preset_mode=manual` while `hold_activity` is
already the named preset, and URA books that as a human override.

---

## 3. Raw setpoint write, no-hold variant — `ha_carrier.set_activity_setpoint`

**Provenance:** upstream feature, PR #427 by Evan Weaver, merged 2026-08-31, commit `4d833486` (see
state-of-play §5 / C15). Ships in v2.28.4 as installed via HACS from `dahlb/ha_carrier` @285f915;
HACS updates preserve it. The literal string "PATCH" in `climate.py:91-104` and `:540` is upstream's
own wording, not a local mutation.

**Behaviour** (`climate.py:539-596`):
- Registered as an entity service, not a platform verb (`climate.py:91-104`).
- Edits the setpoints of the CURRENT activity — whatever the zone is presently on — in place, via
  `set_config_activity(activity_type=current.type, ...)`.
- **Does NOT touch `hold_activity` or `current_status_activity_type`.** Explicit comment
  (`climate.py:591`): "deliberately do NOT touch any hold_* / current_status_activity_type".

**Consequence — the "no-hold nudge" option:** URA can nudge setpoints on an already-named-hold zone
without laundering the hold through MANUAL. Cheap and attractive on the surface.

**Interrupted-edit hazard (load-bearing, do NOT overlook):** because this verb MUTATES the named
activity profile itself, an interrupted borrow leaves the comfort profile PERMANENTLY changed until
someone writes it back. If a URA restart, HA restart, network partition, or exception hits between
the nudge write and the intended restore write, the "Home" profile is now `home + 1.5°F` forever.
The stock `set_temperature` path is safer for interruption because it changes the MANUAL profile
(unused after the pin) and the named profiles stay intact.

**Design implication for W1-B:** if the Carrier strategy adopts `set_activity_setpoint` as a
no-hold nudge, restore MUST be attempted at multiple safety points (per-cycle sweep + boot audit)
against a persisted snapshot of the pre-write profile setpoints. Or: leave nudges on
`set_temperature` (today's path) and adopt `set_activity_setpoint` only for a specific future need.
Not URA's problem to solve tonight — but naming the trade explicitly.

**UNVERIFIED:** whether an HA-driven `set_activity_setpoint` also opens a post-write intercept guard
(§5); read of `_write_local_state` chain not done end-to-end.

---

## 4. Read model — what HA (and URA) sees back

### 4.1 `preset_mode` — from the STATUS feed, LAGS
`_preset_mode()` returns `_config_zone.current_status_activity(status_zone).type.value`, i.e. the
activity the STATUS feed says is current (`climate.py:158-172`, exposed at `:247`). The status feed
setpoints "go stale" — the integration's own comment (`climate.py:222-229`): the periodic full poll
refreshes the status zone; the realtime websocket keeps temperature current but "lets the status set
points go stale". So after a write, `preset_mode` can lag until the next full reconcile.

### 4.2 Setpoints displayed — from the STATUS-NAMED activity
`_update_entity_attrs` reads `target_temperature_high/low` from
`_current_activity() or _status_zone` — i.e. the activity that STATUS names, resolved against
CONFIG (`climate.py:222-240`). Two consequences:
- If STATUS lags on `manual`, the displayed setpoints are the MANUAL activity profile's setpoints —
  which still carry the last raw write's values (the nudge's 78/70).
- The setpoint numbers themselves come from CONFIG (the comment says CONFIG tracks changes
  promptly), so they refresh even while the *name* is stale.

### 4.3 `hold_activity` — from the CONFIG feed, PROMPT
Extra state attribute at `climate.py:261-269`: `_config_zone.hold_activity.value`. CONFIG is
updated on every write (both `set_preset_mode` and `set_temperature` set `_config_zone.hold_activity`
optimistically, `:432` and `:530`), so this is the authoritative "what hold is the thermostat
carrying right now". URA already reads this in one place — the `_needs_resume_first` gate
(`hvac_setpoint.py:181-226`) — with the explicit warning "NOT authoritative for anything else".

**Coherence rule that W1-B must ship** (§5 state-of-play + card `HVAC-PRESET-LOCKOUT-ESCAPE-1`
`SOURCE_VERIFIED_2026_09_26_status_vs_config`): treat `preset_mode == "manual"` as a real human hold
ONLY when `hold_activity == "manual"` too. Disagreement (`preset_mode == "manual"` but
`hold_activity` names a preset) is a status-lag artifact of URA's own recent write; the correct
action is to re-assert the snapshot preset, not to book an override.

### 4.4 `hvac_mode` — from `_config_zone.mode` mapped to HA modes
`climate.py:181-194`. Prompt on write via optimistic local mutation (`:379-380`), reconciled by
polls / websocket.

### 4.5 `hvac_action` — from `_status_zone.conditioning`
`climate.py:200-216`: `HEATING` / `COOLING` / `IDLE` / `OFF` / `FAN`. Straight from the status feed
— what the equipment is actually doing. URA D5 duty-cycle reads this (§9 state-of-play `AWAY_CAUSE_ATTRIBUTED_2026_09_17`).

### 4.6 `next_activity_time` — from CONFIG
Exposed as an extra attr (`climate.py:271`); the recorder history of this value is what dated the
schedule removal (§5 state-of-play).

---

## 5. Refresh / latency model — corrects URA's rough "42-79 s" number

**Coordinator polling** (`carrier_data_update_coordinator.py:130-143`):
- `update_interval = DEFAULT_UPDATE_INTERVAL_MINUTES = 30` (`const.py:46`).
- The socket is the fast path for temperature; polls fill in the rest.

**Full reconcile floor** (`const.py:47-52`; `carrier_data_update_coordinator.py:145-160`):
- `FULL_RECONCILE_INTERVAL_MINUTES = DEFAULT_UPDATE_INTERVAL_MINUTES * 4 = 120 min`. In steady
  state most polls only refresh energy; every fourth (120 min) forces a full pull. This is the
  hard ceiling on how long a dropped websocket delta can silently strand a status field.

**Post-write intercept window** (`const.py:53-59`; `carrier_data_update_coordinator.py:162-296`):
- `POST_WRITE_INTERCEPT_WINDOW_MINUTES = 5`. For 5 minutes after each successful write, the
  coordinator RE-ASSERTS reverted control fields on the written target (`_reassert_control`,
  `_reassert_zone`), keyed by `(system_serial, zone_api_id)`. Snapshots activity_type +
  heat/cool_set_point at write time; if a later websocket message reverts any of them, the local
  state is put back. This is the integration's own defense against Carrier's cloud replaying the
  pre-write snapshot.

**Websocket** (`carrier_data_update_coordinator.py:12`, `:660-687`) — realtime deltas keep
temperature current; the coordinator relies on it between polls.

**Reconciliation of the state-of-play "42-79 s" claim (§2 state-of-play, cited from
`hvac_override.py:147-150`):** that number is URA's measured *effective* refresh window observed
during v5.103.2's resume-then-pin work — a mix of websocket + optimistic local writes + partial
polls under load. The integration's declared cadence is 30 min normal / 120 min full reconcile.
The 42-79 s figure is empirical, not a scheduled interval, and it MAY narrow or widen under
different traffic — treat it as advisory, not a design invariant. UNVERIFIED whether URA's
suppression window and the ha_carrier post-write intercept window compose safely; state-of-play
§9.1 already reads them as fighting each other.

**Implication for a "no-op write suppression":** the funnel's own `_last_emitted_range` cache
(`hvac.py:521`) can compare an intended write against the last emitted value cheaply. But comparing
against LIVE ground truth means either accepting the lag or forcing a refresh — both cost. Prefer
the local-cache path.

---

## 6. Anonymous vs named hold — the invariant that governs W1-B

A **named hold** = `hold_activity ∈ {home, away, sleep, wake, vacation}`. A **anonymous hold** =
`hold_activity == "manual"`. Distinction:
- Named holds re-use the server-side activity profile's setpoints.
- Anonymous holds carry the *manual profile*'s setpoints, which any raw setpoint write mutates.

**Write-verb effects on hold state:**
| Verb | End state |
|---|---|
| `set_preset_mode("home"|"away"|"sleep"|...)` on an already-named-hold zone | named hold (accepted directly) |
| `set_preset_mode("home"|...)` on an anonymous-hold zone WITHOUT `resume` first | **name discarded** — hold stays `manual`, setpoints become the profile's setpoints (measured live 2026-09-16 §5 state-of-play + `hvac_setpoint.py:324-354`) |
| `set_preset_mode("home"|...)` on an anonymous-hold zone WITH `resume` first | named hold (v5.103.2) |
| `set_preset_mode("resume")` | no hold — zone follows vendor schedule |
| `set_temperature(...)` (stock) | anonymous `manual` hold at the requested setpoints |
| `set_activity_setpoint(...)` (PR #427) | hold state UNCHANGED (whatever it was), current activity's setpoints mutated in place |
| `set_hvac_mode(...)` | hold state UNCHANGED |

**Live-vendor-schedule footnote (§10 C12 state-of-play):** `resume` briefly hands the zone to the
Bryant schedule between the resume and the pin. Zone_1 has one remaining 06:00 Home entry; zones
2/3 still run 4-entry schedules. Working assumption is that the operator will reduce schedules
further; until then any resume-then-pin issued near a schedule boundary races a live vendor write.
This is not a bug to fix in URA — it is a caveat the definition must call out.

---

## 7. What Carrier does NOT expose (and W1-B must not assume)

- No "who wrote this?" attribution. Every change reaches HA via the integration; user vs URA vs
  cloud replay vs vendor schedule cannot be distinguished from the recorder context (measured
  2026-09-25, §4.3 state-of-play).
- No hold-expiry attribute independent of `hold_until`; with `infinite_holds=True` that is always
  `None`.
- No API to query "the schedule the thermostat is running". `next_activity_time` names the *next*
  transition; the shape of the schedule itself is only visible in the Bryant app / on the
  thermostat face (§9 state-of-play answer).
- No "reject if newer" semantics. Late writes clobber older ones; the coordinator's post-write
  intercept is the only guard.

---

## 8. Live config — the values we actually run against

| Fact | Live value | Source |
|---|---|---|
| `ha_carrier` version | 2.28.4 | `const.py:5` |
| `CONF_INFINITE_HOLDS` option | **True** | config entry option (state-of-play §8) |
| `DEFAULT_UPDATE_INTERVAL_MINUTES` | 30 | `const.py:46` |
| `FULL_RECONCILE_INTERVAL_MINUTES` | 120 | `const.py:52` |
| `POST_WRITE_INTERCEPT_WINDOW_MINUTES` | 5 | `const.py:59` |
| Zones | `climate.thermostat_bryant_wifi_studyb_zone_1`, `climate.up_hallway_zone_2`, `climate.back_hallway_zone_3` | state-of-play §1 |
| Zone_1 schedule remaining | one 06:00 Home 70/76 entry (post 2026-09-20 11:39 removal) | recorder `next_activity_time` |
| Zones 2/3 schedules | 4-entry (06/08/17-18/22) | recorder |
| Preset modes advertised per zone | `[home, away, sleep, wake, vacation, manual, resume]` | live-verified 2026-08-21, `climate.py:317-318` |

---

## 9. Every UNVERIFIED item, gathered

1. **`hold_until` semantics with `infinite_holds=False`** — §1. Not exercised live.
2. **Whether `ha_carrier.set_activity_setpoint` opens a post-write intercept guard** — §3. Requires
   reading `_write_local_state` end-to-end and confirming it calls `begin_post_write_intercept`.
3. **Whether the physical thermostat was actually in `manual` during the stranded post-return
   windows** — §9.1 state-of-play. All we have is what `ha_carrier` reported; we do not have a
   thermostat-face read from the incident times.
4. **Whether URA's 5-second suppression window and the integration's 5-minute post-write intercept
   compose safely** or fight — §5 + state-of-play §9.1. Independent verification needed under
   W1-A telemetry.
5. **Whether the 42-79 s effective refresh window (URA's measurement) generalises** — §5. It is
   empirical, not a scheduled interval.
6. **Timing of the resume-vs-pin race against a live vendor schedule near a schedule boundary**
   (e.g. 05:59-06:01 on zone_1) — §6 / §10 C12. UNVERIFIED whether this has ever actually caused a
   misfire live.
7. **`set_activity_setpoint` interruption behaviour end-to-end** — §3. Not empirically tested.

---

## 10. What this definition owes W1-B (see companion planning doc)

The Carrier strategy MUST implement, and its tests MUST discriminate:
1. **Preset write** = resume-then-pin when `hold_activity == "manual"` AND entity advertises
   `resume`; direct pin otherwise. Already shipped in `emit_set_preset_mode`
   (`hvac_setpoint.py:288-410`) — the strategy will lift it, not rewrite it.
2. **Borrow return** = **presets-only** when the snapshot preset is a named profile. No preceding
   raw setpoint write — the named profile carries its own setpoints.
3. **Manual coherence** = classify `preset_mode == "manual"` as a human hold ONLY when
   `hold_activity == "manual"` too. Disagreement inside a post-write ownership window is URA's
   echo -> re-assert snapshot.
4. **URA-owned / stale hold reclaim** = a hold whose values match a URA-recent write, or a hold
   past its own timeout knob, is reclaimable by URA regardless of the `manual` label.
5. **No-op write suppression** = the funnel skips a write whose (verb, args) match its last-sent
   record for the entity; the funnel owns `_last_emitted_range` (moves it off `hvac.py:521`).

Anything the strategy does not know how to answer (unknown brand, unfamiliar hold shape) falls
through to the generic default = direct pin, no clear, no coherence assumption.
