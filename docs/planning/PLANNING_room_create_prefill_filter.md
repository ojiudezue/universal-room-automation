# PLANNING — Room create area-prefill detritus filter

Card: ROOM-CREATE-AREA-PREFILL-DETRITUS-1 (thread rooms, tier 2, status planned)
Author: ura-planner · 2026-10-10 · **Rev 2** 2026-10-10 (post plan review) · unversioned (not shipped)
Review tier: Tier 2 (two framing-disjoint reviews, plan review REQUIRED before build dispatch).

**Rev 2 note:** every finding in `## Plan review 2026-10-10` is applied below.
Historic Rev 1 text (D3 scope, D4 sensor, "main-house clean" claim, token
rule, D2 drill, rule-5 clause, single-room step anchor) has been edited in
place. See `## Rev 2 changelog` at bottom for the diff summary.

Operator origin (2026-10-10, Wigton bulk create): *"This is detritus from
bulk create. It needs a card to stop it."* Seen first on main-house Master
Closet onboarding 2026-10-09 (`auto_switches` filled with Sonoff detach
switches + plugs); at Wigton the House room was pre-filled with URA's OWN
domain switches (`switch.universal_room_automation_domain_coordinators`,
`switch.ura_name_people_at_doors`, `switch.ura_presence_face_matching`),
and the mmWave sensors' `switch.*_anti_interference` landed in every room's
`auto_switches` — URA then toggled those with occupancy.

Operator rule (2026-10-10): **Sonoff "detach" relay-mode switches must
NEVER appear in any URA config.** They are device-configuration knobs
masquerading as switch entities. (Rev 2 correction: the main-house
"detach" relays are **sonoff** `minir4m` entities, not Shelly — see F5.)

## Config-first check (CLAUDE.md step 1b)

Is this a knob turn? No. The two live installs already carry the symptom
in persisted room config; the only way to "turn a knob" is operator
hand-cleanup, which was done at Wigton 2026-10-10 but will recur on every
new area-pick, every new install, and on any room edit that re-prefills.
A code fix at the prefill *and* consumer sites is required. No new
operator-visible knob is added by this cycle (see knob ladder §).

## Institutional context verified

### Prior-art scan (code / plans / memory)

Three-surface scan per CLAUDE.md ("tier2+ prior art scan"). Every piece
proposed below is tagged **REUSE** (cite file:line) or **NEW** (why nothing
equivalent exists).

**Code — the area-prefill pipeline already exists; filter is partial:**

- `_get_area_entities(area_id, domain, device_class)` at
  `config_flow.py:1210` — single source of area entities for every prefill
  site. Already excludes: `disabled_by`, `hidden_by`,
  `entity_category is not None` (CONFIG+DIAGNOSTIC), and a helper-platform
  denylist `{template, group, helper, input_*, counter, timer, schedule}`
  (`:1240`). Does **NOT** exclude `platform == DOMAIN` (URA's own
  entities) and has no name-token denylist. **This is the one place the
  shared filter extends** (REUSE + extend).
- `_rank_area_candidates(...)` at `config_flow.py:1277` — PURE
  ranking/dedup helper. Already consumes
  `AUTODETECT_NAME_DENYLIST` (`const.py:1739`) as a **ranking tiebreak
  only** (`:1338` — `denyed` sorts last, does not drop). REUSE for
  ranking; NOT the correct hook for exclusion.
- `_area_prefill(...)` at `config_flow.py:~1750` — single producer of the
  `prefill` dict consumed by `area_sensor_defaults` / `area_device_defaults`
  (`:224` / `:254`). All domains route through `_multi()` / `_single()`
  which call `_get_area_entities` → `_rank_area_candidates`. REUSE.
- `area_device_defaults(prefill)` at `config_flow.py:254` — what
  `devices_confirm` stores on unchanged submit; wired at
  `config_flow.py:2421` (`_multi(CONF_AUTO_SWITCHES, advanced_if_empty=True)`).
  REUSE (no change).
- `async_step_devices` (single-room path) at `config_flow.py:2636` /
  `:2707` — `area_switches = self._get_area_entities(area_id, "switch")`
  then `default=area_switches or []`. REUSE (no change — it reads through
  the filtered helper). **Rev 2 (F9):** gets its own form-default test.
- `AUTODETECT_NAME_DENYLIST` at `const.py:1739` — module-constant tuple of
  lowercased substrings. REUSE unchanged (it is a ranking tiebreak with
  different semantics; new gate uses a SEPARATE constant — knob ladder §).
- Bulk create path `build_area_room_data` at `config_flow.py:265` and
  `_plan_bulk_rooms` at `:1804` — both consume `_area_prefill` output.
  Fixing the central helper fixes bulk + single identically.
- Consumer `automation.py:1919` `_control_auto_switches` reads both
  `CONF_AUTO_DEVICES` (`:1926`) and `CONF_AUTO_SWITCHES` (`:1927`) and
  merges them before dispatch — **no sanity gate**. This is where the
  Wigton harm (mmWave `anti_interference` toggled with occupancy)
  physically occurred. Sibling sites: `automation.py:1949`
  `_control_manual_switches_off` (merges `CONF_MANUAL_DEVICES` +
  `CONF_MANUAL_SWITCHES`); shared-space `automation.py:4162`
  (`CONF_AUTO_SWITCHES`) and `:4173` (`CONF_MANUAL_SWITCHES`). **NEW:
  runtime guard — ONE helper, applied at all four sites.**
- `platform == DOMAIN` check pattern already exists at
  `config_flow.py:11475`, `:11744`, `:11779`, `:11844` (used by other
  options paths to filter URA's own entities out of selectors). REUSE.

**Plans — no prior planning doc touches this surface.** Grep of
`docs/planning/PLANNING_*.md` and `AUDIT_*.md` for `auto_switches` /
`anti_interference` / `detach` / `AUTODETECT_NAME_DENYLIST` returns zero
hits. Adjacent cycles that modified this file touched geography; none
touched the exclusion contract.

**Memory — nothing relevant.** `MEMORY.md` grep: zero hits.

**Design docs read end-to-end:** `docs/VISION_v7.md` §room-config;
`config_flow.py` around every cited site; `automation.py` around the
four actuation sites.

### Measure-before-build (D0, blocks D1–D4)

See `## D0 result` for the measurement that justified the name backstop.

## Falsifiable invariants (what Tier-2 review must verify)

**INV-PREFILL (strict — prefill is the primary chokepoint):** For any
area with entities {E₁…Eₙ}, after this cycle,
`_area_prefill(area_id)["switches"] / ["lights"] / ["fans"] / ["covers"]`
contains **no** entity Eᵢ for which any of the following holds:

1. `Eᵢ.platform == DOMAIN` (URA's own entities), OR
2. `Eᵢ.entity_category in {CONFIG, DIAGNOSTIC}`, OR
3. `Eᵢ.disabled_by is not None` or `Eᵢ.hidden_by is not None`, OR
4. `Eᵢ.platform in HELPER_PLATFORMS` (pre-existing), OR
5. name-token match: `re.search(rf"(^|_){re.escape(tok)}($|_)",
   object_id)` for any `tok` in `AUTODETECT_NAME_DENYLIST_PREFILL`.
   (Rev 2 F8: the redundant `AND entity_category is None` clause has
   been dropped — rule 2 already wins when the integration sets it.)

**INV-CONSUMER (narrower — Rev 2 F2):** `automation._actuatable_ids(...)`
(the new helper) and its four call sites emit `turn_on` / `turn_off`
only to a target set S′ ⊆ the stored config list where S′ excludes any
id that, against the LIVE entity registry, violates **rule 1
(`platform == DOMAIN`), rule 2 (`entity_category` is CONFIG/DIAGNOSTIC),
or rule 5 (name-token regex)**. Rules 3 and 4 are prefill-only — they
would silently break legitimate operator configs at runtime (hidden-but-
automated relays; deliberate `input_boolean` / `template` / `group`
targets per `_control_auto_switches` docstring at `automation.py:1920`).
A `disabled_by` call is already a HA no-op. Rejected ids log once per
`(entry_id, entity_id, rule_id)` at WARNING grep-anchored
`URA-PREFILL-DETRITUS-GUARD`.

**Falsifier each reviewer MUST attempt** in each framing: construct a
fake area holding (a) a `switch` entity whose `platform == DOMAIN`,
(b) a Sonoff detach switch (metadata per D0), (c) a Z2M
`anti_interference` switch, (d) a plain controllable Shelly plug — assert
`_area_prefill(...)["switches"]` contains exactly {d}; assert
`_actuatable_ids([a, b, c, d])` returns exactly `[d]`. For INV-CONSUMER,
additionally construct (e) a hidden plain relay and (f) an
`input_boolean` — both MUST survive the runtime guard.

## Non-goals

- Not changing dedup / ranking policy in `_rank_area_candidates`.
- Not changing `CONF_MANUAL_SWITCHES` prefill (`default=[]` today at
  `config_flow.py:2710`; no prefill, no detritus). The D3 runtime guard
  DOES cover `CONF_MANUAL_SWITCHES` because `automation.py:1949` and
  `:4173` are in-scope.
- Not touching HVAC / door-sensor / weather prefills.
- Not building a UI Repairs flow — deferred to a follow-up card. D4 in
  Rev 2 is a one-shot boot-time structured log, not an entity.
- **Rev 2 F3 correction — main house is NOT already clean.** A read-only
  scan of `core.config_entries` vs the registry finds `Kitchen Hallway
  Garage` → `CONF_AUTO_SWITCHES` includes
  `switch.dimmer_wifi_matter_tapo550d_garagekitehenhallway_auto_update_enabled`
  (tplink, `entity_category=config`) — a firmware-auto-update knob URA
  toggles with occupancy. D4's boot scan will enumerate this and any
  siblings; cleanup is still operator-driven (no silent config
  migration), but the boot log now gives the operator a complete list on
  one restart instead of a per-room hunt.
- No migration of persisted configs.

## Deliverables

### D0 — MEASURE: entity-registry probe (read-only)

See `## D0 result — measured 2026-10-10` below. **DONE.** Verdict:
name-token backstop REQUIRED.

### D1 — Shared exclusion filter in `_get_area_entities`

**REUSE + extend** `config_flow.py:1210` `_get_area_entities`. Add
exclusions (strict prefill set — INV-PREFILL rules 1 + 5):

1. `entry.platform == DOMAIN` → skip. (Pattern REUSED from
   `config_flow.py:11475`.)
2. Name-token regex: for each `tok` in `AUTODETECT_NAME_DENYLIST_PREFILL`,
   if `re.search(rf"(^|_){re.escape(tok)}($|_)", object_id)` matches →
   skip. No `entity_category is None` precondition (F8).

Pre-existing rules 2 (`entity_category not None`), 3 (hidden/disabled),
and 4 (helper platforms) continue to apply at the prefill layer — the
Rev 1 doc already had them.

#### Acceptance Criteria

- **Verify:** `_area_prefill(area_id_X)["switches"]` for a fake area
  holding {URA-domain switch, Sonoff detach, Z2M anti_interference,
  plain plug} returns `[plain_plug_entity_id]`.
- **Verify:** `_area_prefill(area_id_X)["lights"]` unchanged for a
  plain-light fixture.
- **Test (regex pins — F5):** `test_name_token_regex_matches`:
  - MUST match: `switch.mmwave_zigbee_jayabedroom_anti_interference`,
    `switch.minir4m_mastercloset_detach`,
    `switch.<...>_do_not_disturb`, `switch.<...>_child_lock`,
    `switch.<...>_indicator`.
  - MUST NOT match: `switch.65_mini_led_power` (homekit TV power —
    the F5 false-positive discriminator),
    `switch.switch_shelly2pmgen3_wifi_dnguestroom_light`,
    `switch.detachable_cover_cam` (hypothetical — `detach` must only
    match as a whole token, not a prefix).
- **Test:** `test_get_area_entities_excludes_ura_domain`,
  `test_get_area_entities_excludes_name_token_backstop`,
  `test_get_area_entities_keeps_plain_actuators` in
  `quality/tests/test_config_flow_area_prefill.py`.
- **Test (mutation):** comment out the DOMAIN check → URA-domain-switch
  test FAILS; comment out the name regex → detach-switch test FAILS;
  restore → suite green.
- **Test (F9 — single-room step):** `test_async_step_devices_form_default_
  excludes_contraband` drives the single-room `async_step_devices`
  (`config_flow.py:2636`) with a fake area, asserts the returned
  `data_schema`'s `CONF_AUTO_SWITCHES` default equals `[plain_plug]`.
- **Live:** on next room create via area pick, `devices_confirm` form's
  `CONF_AUTO_SWITCHES` default is EMPTY (or contains only plain
  actuators). Verified by one options-flow walk per install.

### D2 — Bulk-create path parity

No code change expected — fixing the central helper fixes bulk by
construction. The deliverable is a test that pins parity **with a
drill that can actually fail (F6).**

#### Acceptance Criteria

- **Test:** `test_build_area_room_data_switches_excludes_contraband`:
  construct a fake area with the four-entity set; call
  `build_area_room_data(name="X", room_type="general", area_id=...,
  prefill=_area_prefill(area_id))`; assert
  `data[CONF_AUTO_SWITCHES] == [plain_plug]`.
- **Test (mutation — F6, REWRITTEN):** comment out the **D1 DOMAIN
  check** in `_get_area_entities`. The bulk-create parity test
  (`test_build_area_room_data_switches_excludes_contraband`) MUST go
  RED on the URA-domain-switch fixture. Restore → green. This proves
  the bulk path routes through the shared gate (the previous "must
  still PASS" drill proved nothing — Hollow-anchor class).
- **Live:** post-restart, pick two areas in bulk-create at the main
  house; neither resulting room's stored config contains any
  contraband id.

### D3 — Consumer-side runtime guard (ONE helper, FOUR sites — F1)

**NEW** in `automation.py`:

```python
def _actuatable_ids(self, ids: list[str]) -> list[str]:
    """INV-CONSUMER rules 1+2+5 against the LIVE entity registry.
    Dedup-logs rejections at WARNING with grep-anchor
    URA-PREFILL-DETRITUS-GUARD per (entry_id, entity_id, rule_id)."""
```

Called at all four actuation sites (verified at Rev-2 planning time
against `develop`):

| # | File:line | Config keys read | Notes |
|---|---|---|---|
| 1 | `automation.py:1919` (`_control_auto_switches`) | `CONF_AUTO_DEVICES` (`:1926`) + `CONF_AUTO_SWITCHES` (`:1927`), merged at `:1933` | Guard the MERGED `devices` list before `_safe_service_call`. |
| 2 | `automation.py:1949` (`_control_manual_switches_off`) | `CONF_MANUAL_DEVICES` + `CONF_MANUAL_SWITCHES`, merged | Same pattern. |
| 3 | `automation.py:4162` (shared-space exit) | `CONF_AUTO_SWITCHES` | Shared-space fixture required. |
| 4 | `automation.py:4173` (shared-space exit) | `CONF_MANUAL_SWITCHES` | Same shared-space fixture. |

`coordinator.py:1368` is a read-only conflict-detection superset — NOT a
call site, not guarded.

Dedup via an instance-level `set[tuple[entry_id, entity_id, rule_id]]`
on the automation instance (lifetime = instance; restart WARNING per
id is operator-useful).

#### Acceptance Criteria

- **Verify:** with a stored config containing a URA-domain switch, a
  Sonoff detach switch, AND a Z2M `anti_interference` switch,
  `_control_auto_switches(True)` dispatches `homeassistant.turn_on`
  with ONLY plain actuators in `entity_id`. One WARNING per rejected
  id, not per occupancy transition.
- **Verify:** a hidden plain relay AND an `input_boolean` in
  `CONF_AUTO_DEVICES` SURVIVE the runtime guard (F2 — rules 3+4 do
  NOT apply at runtime).
- **Test:** FOUR per-site mutation tests — one per row of the table
  above. For each row N: a scenario-specific test
  (`test_site_N_filters_contraband_at_runtime`) that drives the real
  method path with a shared-config fixture containing one piece of
  contraband that site N touches; comment out the `_actuatable_ids`
  call at site N (leave the other three intact) → test for site N goes
  RED; restore → green. This is the Wire-in Anchor rule.
- **Test:** `test_actuatable_ids_logs_once_per_entity` — dedup set
  prevents re-logging across repeated transitions in-session.
- **Test:** `test_actuatable_ids_preserves_helper_platforms_and_hidden`
  (F2 regression — explicit survival of `input_boolean`, template
  switch, `hidden_by != None` plain relay).
- **Live:** post-deploy, grep core logs for
  `URA-PREFILL-DETRITUS-GUARD`. Each line names (entry_id, entity_id,
  rule_id). Expected non-zero at main house (`Kitchen Hallway Garage`
  tapo auto_update_enabled, Wigton residual if any missed by
  hand-cleanup).

### D4 — One-shot boot/setup detritus scan (REPLACES Rev-1 sensor — F4)

**NEW** in each room's integration setup (`__init__.py`
`async_setup_entry` or the room setup helper — builder picks the
single lowest point in setup that has the stored config and the
registry both ready). On entry setup, scan the stored config lists
once:

Scanned keys: `CONF_AUTO_DEVICES`, `CONF_AUTO_SWITCHES`,
`CONF_MANUAL_DEVICES`, `CONF_MANUAL_SWITCHES`, `CONF_LIGHTS`,
`CONF_NIGHT_LIGHTS`, `CONF_FANS`, `CONF_HUMIDITY_FANS`, `CONF_COVERS`
(builder confirms the exact set via a 5-minute grep sweep in build
step 0 and lists them in the build brief).

For each `(room_entry_id, entity_id)` violating INV-CONSUMER rules
1 / 2 / 5 (same rule set as D3 — operator may legitimately keep
hidden or helper-platform targets), emit **one** WARNING per
`(entry_id, entity_id, rule_id)` with grep-anchor
`URA-PREFILL-DETRITUS-GUARD` and fields: `room_name`, `entity_id`,
`rule_id`, `config_key`. **No new entity, no sensor, no restore
state.** The log IS the surface.

#### Acceptance Criteria

- **Verify:** at main house, boot log contains ≥1
  `URA-PREFILL-DETRITUS-GUARD` line naming `Kitchen Hallway Garage`
  and `switch.dimmer_wifi_matter_tapo550d_garagekitehenhallway_auto_
  update_enabled` with `rule_id=config_category`.
- **Verify:** at Wigton (hand-cleaned), boot log is quiet (0 lines)
  or lists only residuals the operator missed.
- **Test:** `test_boot_scan_logs_once_per_pair_per_rule` — construct
  two rooms with overlapping contraband; assert exactly N log lines,
  no duplicates.
- **Test:** `test_boot_scan_rule_enum_is_{ura_domain, config_category,
  name_backstop}` — the rule enum carries exactly these three values
  (F2: no `helper_platform` / `hidden_or_disabled` in the runtime
  enum).
- **Live:** one grep after restart tells the operator every poisoned
  config across both installs in one pass; no waiting for occupancy
  transitions.

## Numbers Get Knobs — ladder

Only one new "number" lands this cycle: the token list for the prefill
backstop. Named module constant, not a Number/Options knob.

- `AUTODETECT_NAME_DENYLIST_PREFILL` (NEW, `const.py`, module-constant,
  **Rung 1**). Separate from the existing `AUTODETECT_NAME_DENYLIST`
  (`const.py:1739`, a *ranking* tiebreak). New constant is a *gate*
  with different blast radius.
- **Finalised token set (Rev 2 F5 + F7):**
  ```python
  AUTODETECT_NAME_DENYLIST_PREFILL = (
      "detach",            # Sonoff relay-mode knob (14 main-house entities)
      "anti_interference", # Z2M mmWave config switch (8 main / 17 Wigton)
      "do_not_disturb",    # Alexa / Tuya / Roborock quiet-mode
      "child_lock",        # Dreo / other appliance child-locks
      "indicator",         # Z2M status-LED enables with entity_category=None
  )
  ```
- **F5 — `led` is DROPPED entirely.** D0 showed every real LED knob
  carries `entity_category=config` already (sonoff/smlight/tplink: 30
  entities). The only `_led` substring hit without a category was
  `switch.65_mini_led_power` on homekit — a TV power switch, a FALSE
  positive. Substring-matching `led` would toggle TV power with
  occupancy. Regex whole-word still wouldn't match `_led_power`, but
  dropping `led` removes the trap entirely and the config-category
  rule 2 catches the legitimate LED knobs.
- **F5 — `_led` as end-anchor is DROPPED** for the same reason: no
  surviving contraband needs it; the regression surface is non-zero.
- **F5 — `detached` / `relay_mode` / `night_mode` / `beep` /
  `button_lock` are DROPPED** from the Rev 1 speculative list. D0 did
  not find any such entity landing in a config today. Rung 1 means
  adding one later is a reviewed code change — cheap, correct default.
- **F7 — decided-and-EXCLUDED candidates, with reasoning:**
  - `panel_sound` (dreo) — EXCLUDED. Carries `entity_category=config`
    on every main-house instance; rule 2 already blocks it from
    prefill, and the operator may legitimately control appliance
    beep from an automation. Zero evidence of it landing in a
    config.
  - `display_auto_off` (dreo) — EXCLUDED. Same reasoning.
  - `*_water_detection_enabled` (ac_infinity) — EXCLUDED. Config-
    category already; disabling it is a deliberate operator choice,
    not a safety-neutral toggle to carpet-automate.
  - `sleep_mode` (adaptive_lighting) — EXCLUDED. This IS a switch
    operators intentionally schedule; name-matching it would be a
    functional regression for adaptive_lighting users (Rev 2 does
    not ship URA breaking adaptive_lighting).
  - If any of these later turns up in a stored config (D4 boot scan
    will reveal it), the token is added in a one-line follow-up
    cycle. Rung 1 reserves exactly this discretion for review.
- No new config-flow / options field. No new Number / Select / Switch
  entity.
- Kill-switch: setting `AUTODETECT_NAME_DENYLIST_PREFILL = ()` reverts
  to pre-cycle name behaviour; the DOMAIN filter remains active
  (operator stated it is non-optional).

## Edge cases + QUALITY_CONTEXT.md classes

- **Stale data source (QC #7):** D3 and D4 both read the LIVE entity
  registry at call time.
- **Enum / string mismatch (QC #22):** `entry.platform` compared to
  `DOMAIN` constant (REUSED pattern).
- **Observation mode gating (QC #23):** none.
- **Untracked background tasks:** none. D3 is synchronous per-call;
  D4 is one-shot at setup.
- **Concurrent reload race:** registry read is synchronous and
  per-call; no cached state across reload.
- **Hollow anchors (QC #62):** F6-rewritten D2 drill is now mutation-
  anchored on the DOMAIN check with a RED-on-mutate requirement; D3's
  four per-site drills enforce real wiring per site.
- **Bug Class #53 (computed-but-not-consumed):** F1 enumerates all
  four actuation sites, each with its own test; the shared helper
  closes the Rev-1 three-site leak.

## Review protocol (Tier 2)

Plan review (ONE adversarial pass) — **DONE 2026-10-10**, findings
applied in this Rev 2. Builder may dispatch after re-reading this
revised doc end-to-end.

Build review (TWO parallel passes, framing-disjoint):

- **Reviewer A — correctness + edge cases:** per-site filter logic;
  mutation drill ran per-site; token regex pin-tests behavioural (not
  source greps); D4 boot-scan rule-enum is exactly 3 values.
- **Reviewer B — async/lifecycle + runtime guard integrity:**
  `_actuatable_ids` dedup set lives on automation instance (not
  module-global); no listener leak; registry read is non-blocking on
  the hot occupancy path; D4 one-shot does not re-fire on reload.

Live validation (post-deploy, write back into README):
`URA-PREFILL-DETRITUS-GUARD` log lines at boot (D4) and at
occupancy-event rejections (D3); one options-flow walk at each
install verifying contraband is NOT in `CONF_AUTO_SWITCHES` default.

## Plan completion tracking (post-build)

To be filled by builder: list every D0–D4 item and its status
(SHIPPED / DEFERRED / DROPPED with reason), plus any HA Repairs
follow-up card (deferred by this plan).

## D0 result — measured 2026-10-10 (orchestrator, entity registries of both installs)

| Token match | Platform | entity_category | Main | Wigton |
|---|---|---|---|---|
| detach | sonoff | **None** | 17 | – |
| anti_interference | mqtt (Z2M) | **None** | 8 | 17 |
| do_not_disturb | alexa_devices | **None** | 24 | – |
| child_lock | dreo | **None** | 4 | – |
| indicator | mqtt (Z2M) | **None** (4) / config (30 main, 17 Wigton) | 34 | 17 |
| do_not_disturb | tuya / tuya_local / alexa_media / roborock / robovac | config | 107 | – |
| status_light | unifiprotect / sonos | config | 24 | 11 |
| led | sonoff / smlight / tplink | config | 30 | – |
| `_led` false positive | homekit_controller | None | – | 4 (`switch.65_mini_led_power` = a TV's power — NOT a settings switch) |

**Verdict: name-token backstop REQUIRED** — the two contraband classes
that actually landed in room configs (Sonoff `detach`, Z2M
`anti_interference`) both carry `entity_category=None`. An
entity_category filter alone would have blocked neither. Tokens are
matched as whole `_`-delimited words on the entity_id object_id via
`re.search(rf"(^|_){re.escape(tok)}($|_)", oid)` (Rev 2 F5), never as
substrings. `led` is excluded (false-positive risk +
category-already-covered). Final set: `{detach, anti_interference,
do_not_disturb, child_lock, indicator}`.

## Plan review 2026-10-10

Reviewer: ura-reviewer (Tier-2 adversarial plan pass, read-only). Not HVAC; state-of-play doc not applicable. All claims re-grepped on `develop`.

**Verdict: PLAN-FIX-REQUIRED** (2 HIGH, 4 MEDIUM, 3 LOW). The D1 prefill choke point holds; the problems are in D3's scope and rules, and the "no live contraband" claim.

### Verified (holds)
- **Prefill choke point.** Every area-based switch, light, fan or cover prefill reads `_get_area_entities` (`config_flow.py:1210`): `_area_prefill` `_multi` (`:1752-1757`) feeds `area_device_defaults` (`:254`), which feeds devices_confirm and `build_area_room_data`; the single-room `async_step_devices` calls it at `:2633-2636`. The `CONF_MANUAL_SWITCHES` default is `[]` (`:2710`). `CONF_HUMIDITY_FANS` is `[]` (`:259`). The other full-registry scans in config_flow (`:1419` weather, `:3230` AI-rule entity hints, `:11474/11743/11777/11843`) do not fill actuator lists. No separate area autodetect for lights or switches exists in lighting/, coordinator or `room_setup`.
- **The DOMAIN filter in the shared helper also covers the sensor buckets** (14 callers). For example, URA's own temperature or illuminance sensors in a House area will stop prefilling. This is wanted. The plan should say it, because the docstring at `:1233` warns against shrinking the defaults.
- D0 blocks D1, and the D0 table justifies the name backstop.

### Findings
1. **HIGH — D3 misses 3 of 4 actuation sites (Bug Class #53).** Plain `self.config.get` reads of the contaminated lists happen at:
   - `automation.py:1919` `_control_auto_switches`, which ALSO merges `CONF_AUTO_DEVICES` (`:1926`);
   - `automation.py:1949` `_control_manual_switches_off`, which reads `CONF_MANUAL_DEVICES` plus `CONF_MANUAL_SWITCHES`;
   - `automation.py:4162` shared-space `CONF_AUTO_SWITCHES`;
   - `automation.py:4173` shared-space `CONF_MANUAL_SWITCHES`.

   `coordinator.py:1368` is a read-only conflict-detection superset and does not actuate. **Fix:** put the guard in ONE helper applied at all four sites. List all four in D3, and give each its own call-neuter mutation test. The anchor at `:4162` alone needs a shared-space fixture.
2. **HIGH — The D3 runtime rules 3 and 4 would break legitimate operator configs.** `_control_auto_switches` explicitly supports multiple domains, including input_boolean, template and group (docstring `automation.py:1920`). Rejecting `helper_platform` at runtime would silently stop deliberately chosen `input_boolean` or template-switch automations. Rejecting `hidden_by` would stop entities the operator hid from dashboards but still automates, which is common for relays. A call to a disabled entity is already a no-op. **Fix:** the runtime guard applies ONLY rule 1 (`platform == DOMAIN`), rule 2 (`entity_category` CONFIG/DIAGNOSTIC) and rule 5 (name tokens). Rules 3 and 4 stay prefill-only, where they already live. Restate INV-CONSUMER to match, and drop `helper_platform` and `hidden_or_disabled` from the D4 rule enum.
3. **MEDIUM — The non-goal "main house is already clean" is false.** A read-only scan of the main-house `core.config_entries` against the registry finds `Kitchen Hallway Garage` → `auto_switches` = `switch.dimmer_wifi_matter_tapo550d_garagekitehenhallway_auto_update_enabled` (tplink, `entity_category=config`). This is live contraband. URA toggles a firmware-auto-update knob with occupancy. **Fix:** see finding 4 for the replacement deliverable. Correct the non-goal text.
4. **MEDIUM — Replace D4 (the new sensor) with a one-shot setup-time scan (parsimony).** A sensor that counts rejections only fills when an occupancy transition reaches a guarded site. It adds an entity, attributes and a restore question for a value whose only consumer is a human reading it once. **Fix:** at room setup, run the same predicate over the stored lists (auto/manual switches and devices, lights, night_lights, fans, humidity_fans, covers) and log WARNING `URA-PREFILL-DETRITUS-GUARD` once per (entry, entity, rule). Live validation becomes one log grep at boot that reports every poisoned config on both installs, with no need to wait for an occupancy event. D4 is dropped, and no new entity is added. If the operator later wants it on a dashboard, a Repairs issue (already deferred) is the right surface.
5. **MEDIUM — Whole-word matching is underspecified and wrong for multi-word tokens.** "`_`-delimited whole word" cannot match `anti_interference`, `do_not_disturb` or `child_lock` if it is implemented as `tok in oid.split("_")`. **Fix:** specify the matcher as a regex: `re.search(rf"(^|_){re.escape(tok)}($|_)", object_id)`. Pin it with tests:
   - must match `switch.mmwave_zigbee_jayabedroom_anti_interference` and `switch.minir4m_mastercloset_detach`;
   - must NOT match `switch.65_mini_led_power` or `switch.switch_shelly2pmgen3_wifi_dnguestroom_light`.

   Drop `led` entirely: the D0 data shows every real LED knob is already `entity_category=config`. Correct the plan's framing too. On the main house the "detach" switches are **sonoff** (14 entities, e.g. `switch.minir4m_mastercloset_detach`), not Shelly. All 95 main-house Shelly switches are `switch_N` / `swN` / `light` relays plus `aioshelly_ble_integration` (config-category). No Shelly `detached` variant exists today, so a `detached` token is speculative. Leave it out unless a registry shows one (rung 1, so adding it costs one code change).
6. **MEDIUM — The D2 mutation drill is hollow (#62).** It "must still PASS", so it cannot fail and proves nothing. **Fix:** replace it with a call-neuter on the D1 DOMAIN check, and require `test_build_area_room_data_switches_excludes_contraband` to go RED. That proves bulk routes through the gate.
7. **LOW — Candidate tokens.** The D0-backed set is `{detach, anti_interference, do_not_disturb, child_lock, indicator}`. The main-house registry also shows uncategorised config-like switches: dreo `panel_sound` and `display_auto_off`, ac_infinity `*_water_detection_enabled`, and adaptive_lighting `sleep_mode`. None of these landed in a config. Note them as known-and-deliberately-excluded, or add `panel_sound`. Decide this in the plan rather than leaving it to the builder.
8. **LOW — INV-PREFILL rule 5's clause "AND entity_category is None" is redundant** with rule 2. It is harmless, but it makes the falsifier's fixture matrix look larger than it is. Simplify the wording.
9. **LOW — The single-room `async_step_devices` (`:2636`) uses the raw, unranked helper output.** That is fine for this cycle, because the filter lives in the helper. Add one test that drives that step's form default, so the single-room path has its own anchor and does not rely only on `_area_prefill`.

### Checklist
| Item | Result |
|---|---|
| (1) Prefill choke point single | PASS |
| (2) Consumer guard complete | **LEAK**: 3 of 4 sites missing (F1) |
| (3) Invariant falsifiable | PASS for prefill; INV-CONSUMER needs restating per F1 and F2 |
| (4) Token rule vs D0 | FIX (F5) |
| (5) `platform==DOMAIN` covers URA entities | PASS: URA registers 666 main-house switches under platform `universal_room_automation` |
| (6) Knob ladder / sensor | Rung 1 correct; drop the sensor (F4) |
| (7) ACs discriminate / non-goals | FIX (F3, F6) |
| (8) Existing-config cleanup | FIX: add the setup-time report (F4); live contraband exists (F3) |

## Rev 2 changelog

Applied 2026-10-10 by orchestrator (Opus 4.7). Every plan-review finding
addressed:

- **F1 (HIGH) — Consumer guard scope.** D3 restated: ONE helper
  `_actuatable_ids(...)` applied at FOUR sites — `automation.py:1919`
  (incl. `CONF_AUTO_DEVICES` merge at `:1926`), `:1949`, `:4162`,
  `:4173`. Each site has its own mutation-anchored test. Table added
  with per-site config keys. `coordinator.py:1368` explicitly noted as
  non-actuating.
- **F2 (HIGH) — Runtime rule set narrowed.** INV-CONSUMER rewritten to
  apply ONLY rules 1 (`platform==DOMAIN`), 2 (`entity_category` CONFIG/
  DIAGNOSTIC), and 5 (name tokens). Rules 3 (hidden/disabled) and 4
  (helper platforms) stay prefill-only. New regression test
  `test_actuatable_ids_preserves_helper_platforms_and_hidden`. D4 rule
  enum reduced to `{ura_domain, config_category, name_backstop}`.
- **F3 (MEDIUM) — "Main house clean" claim corrected.** Non-goals and
  prose updated: `Kitchen Hallway Garage`'s `auto_switches` contains
  `switch.dimmer_wifi_matter_tapo550d_garagekitehenhallway_auto_update_
  enabled` (tplink, config-category). D4 boot scan is the surface for
  enumerating all residuals in one pass.
- **F4 (MEDIUM) — D4 sensor REPLACED by boot/setup scan.** No new
  entity. One-shot per `(entry_id, entity_id, rule_id)` WARNING at
  room setup with grep-anchor `URA-PREFILL-DETRITUS-GUARD` and fields
  `room_name, entity_id, rule_id, config_key`.
- **F5 (MEDIUM) — Token matcher specified as regex** `re.search(
  rf"(^|_){re.escape(tok)}($|_)", object_id)` with pinned
  match/non-match tests including the `switch.65_mini_led_power`
  false-positive discriminator. `led` DROPPED. Framing corrected to
  **sonoff** (not Shelly) `detach`. Speculative tokens (`detached`,
  `relay_mode`, `night_mode`, `beep`, `button_lock`) dropped.
- **F6 (MEDIUM) — D2 mutation drill rewritten.** Removed the hollow
  "must still PASS" variant; new drill comments out the D1 DOMAIN
  check and requires `test_build_area_room_data_switches_excludes_
  contraband` to go RED.
- **F7 (LOW) — Candidate tokens decided in-plan.** Final set:
  `{detach, anti_interference, do_not_disturb, child_lock, indicator}`.
  Explicit reasoning recorded for the four EXCLUDED candidates (dreo
  `panel_sound` / `display_auto_off`, ac_infinity
  `*_water_detection_enabled`, adaptive_lighting `sleep_mode`) —
  category-covered or legitimately operator-controlled.
- **F8 (LOW) — Redundant clause dropped.** INV-PREFILL rule 5 no
  longer carries `AND entity_category is None`.
- **F9 (LOW) — Single-room step anchor added.** New test
  `test_async_step_devices_form_default_excludes_contraband` drives
  the `config_flow.py:2636` form and asserts the `CONF_AUTO_SWITCHES`
  default equals the filtered list.
- **Housekeeping.** Prior-art scan corrected (sonoff vs Shelly);
  consumer-site list in Code § re-grepped on `develop` at Rev-2 time
  and now matches the F1 table.
