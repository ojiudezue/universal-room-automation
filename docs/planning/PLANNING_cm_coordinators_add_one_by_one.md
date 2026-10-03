# PLANNING — CM-COORDINATORS-ADD-ONE-BY-ONE-1: add coordinators one at a time from the Coordinator Manager

Card: `CM-COORDINATORS-ADD-ONE-BY-ONE-1` (thread: onboarding). Status of this doc: plan, unreviewed.
Operator 2026-10-02: "Coordinators are all created and enabled when you install URA. They should be
added from the CM menu one by one. At minimum added disabled until configured. Needing to be added
1 by 1 is also a natural gate to monetize each feature. HVAC, Energy and Security are big modules."

## Tier

- **Phase A (honest defaults + start-disabled): Tier 2**, elevated to **Tier 2-DB (3 framing-disjoint
  reviews)** per standing policy — it changes the run/no-run default of Presence/Safety/Security on
  new installs and touches the shared CM setup path every coordinator flows through.
- **Phase B (CM "Add a coordinator" / "Remove a coordinator" menu + entitlement hook): Tier 2.**
- **Phase C (defer entity/device creation until added): Tier 3** — device-registry and entity-registry
  surgery across 6 platforms (`sensor`, `binary_sensor`, `switch`, `number`, `select`, `button`) on the
  CM entry. History: `docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md` (8 mistakes in v5.92.3-v5.94.1).
  Two plan reviews before build.

Marginal-benefit note: Phase A alone gives "at minimum added disabled until configured" with low
risk. Phase B gives the one-by-one experience and the monetization hook point. Phase C only removes
clutter (unavailable entities on unused coordinators). Recommend shipping A+B, and holding C behind
an evidence trigger (second-home operator reports the clutter as a real problem, or a paid tier
needs hidden devices).

## Findings — what a fresh install really creates and enables (from code)

### Entries

1. First setup of the integration entry runs `_ensure_coordinator_manager_entry`
   (`__init__.py:1073-1121`) from `__init__.py:2009-2018`, gated only by the one-shot option
   `coordinator_manager_entry_done`. **The Coordinator Manager (CM) entry is created on every install,
   unconditionally, with no questions** (`config_flow.py:3690-3697`, title "URA: Coordinator Manager").
2. The master switch `switch.*domain_coordinators` (`DomainCoordinatorsSwitch`, `switch.py:487-535`,
   on the integration device) reads `domain_coordinators_enabled` with **default False**
   (`switch.py:518`). The whole coordinator runtime is gated on it (`__init__.py:3195`). So the audit is
   right on this point: on a fresh install **no coordinator runs** until the master switch is turned on.

### Coordinator run defaults once the master switch is ON (registration gates)

| Coordinator | Registration read | Default | Runs on fresh install after master ON? |
|---|---|---|---|
| Presence | `__init__.py:3322` | True | YES |
| Safety | `__init__.py:3353` | True | YES |
| Security | `__init__.py:3367` | True | YES (with empty lock/entry/camera lists) |
| Music Following | `__init__.py:3411` | True | YES |
| Energy | `__init__.py:3514` | **False** | no |
| Appliance | `__init__.py:3810` | True | YES |
| HVAC | `__init__.py:3821` | **False** | no |
| Notification Manager | `__init__.py:4151` | **False** | no |

### The real defect: the Enabled switches lie for Energy, HVAC and NM

`CoordinatorEnabledSwitch.is_on` (`switch.py:694-698`) is:

```python
return merged.get(self._conf_key, True)
```

It defaults **True for every coordinator**, while the registration gates for Energy, HVAC and NM
default **False**. On a fresh install (key absent from CM options) all eight "Enabled" switches show
**ON**, but Energy, HVAC and NM are not running. This is a display-truth split (Bug Class #63
territory: two defaults that agree on the operator's own house because the keys were written long
ago, and disagree on any fresh install). It explains the operator's observation "all created and
enabled" and the audit's claim "HVAC/Energy default off": both are true at different layers. The
audit's install guide step 8 ("confirm the HVAC Coordinator switch is off (its default)") is
**wrong** — on a fresh install it reads ON.

Toggling one of these switches writes the key explicitly, so after the first toggle the two layers
agree. That is why the operator's main house never shows the split.

### Entities and devices created regardless of enablement

- `switch.py:220-330`: for the CM entry, 8 `CoordinatorEnabledSwitch` entities (each creating its
  coordinator's device: presence/safety/security/music_following/energy/appliance/hvac/
  notification_manager) plus NM, Security, Energy-observation and other switches — **unconditional**.
- `sensor.py:186+`, `binary_sensor.py:136+`, `number.py:56+`, `select.py:66+`, `button.py:43+`: CM-entry
  entity lists are built **unconditionally**; no read of any `*_coordinator_enabled` key in platform
  setup (grep of `sensor.py` for `coordinator_enabled|_COORDINATOR_ENABLED` = 0 hits). Entities for a
  coordinator that is not registered resolve `manager.coordinators.get(<id>)` to None and show
  unavailable/default (e.g. `binary_sensor.py:2863`, `select.py:819`, `number.py:2455-2459`).
- So every coordinator device and all its entities exist on every install, even with the master
  switch OFF.

### Other surfaces

- `entry_type_select` menu offers `add_coordinator` (`config_flow.py:1093`) which **aborts**
  (`config_flow.py:1116-1122`, reason `coordinator_use_options`). Dead end.
- CM options `init` menu (`config_flow.py:4153-4188`) shows all coordinator settings steps always.
- `async_step_domain_coordinators` (`config_flow.py:5011-5039`) and `async_step_coordinator_toggles`
  (`config_flow.py:9442-9477`) are no longer reachable from any menu (replaced by switches; comments at
  `config_flow.py:4138`, `:4155`).
- No settings step writes an enable key: grep of `config_flow.py` for `CONF_HVAC_ENABLED`,
  `CONF_ENERGY_ENABLED`, `CONF_NM_ENABLED` = 0 hits. The only writer is the switch.
- `CONF_COMFORT_ENABLED` (`const.py:2929`) has no registration site and no switch (KEEP + DOCUMENT;
  out of scope).
- No entitlement/license code exists in Python (grep `entitlement|license` = only bundled frontend JS).

### Second home (192.168.17.243, v5.103.18) — NOT CHECKED

This planning agent has no shell or HTTP-with-header tool in this session (only Read/Grep/Glob/
Write/WebFetch; WebFetch cannot send a Bearer header). The token file was not opened. The live check
is a **pre-build step** for the orchestrator (GET-only):

- `GET /api/states` → filter `switch.*` with `_coordinator_enabled` / `_enabled` under the URA
  coordinator devices + `switch.*domain_coordinators*`; record state.
- Predicted from code: master switch `off` unless the operator turned it on; all 8 coordinator
  "Enabled" switches `on`; Energy/HVAC/NM sensors `unavailable` or default even if master is on.
- Discriminator: if the HVAC Enabled switch reads `on` while `sensor.*hvac*` mode/status entities are
  unavailable, the split above is confirmed live. If HVAC Enabled reads `off`, the key was written
  (someone toggled it) and the split is not the explanation for that home.

## Institutional context verified

1. **Greps run + results**
   - `CONF_*_ENABLED` / `COORDINATOR_ENABLED_KEYS`: REUSED `const.py:2923-2950` (one key per
     coordinator; mapping dict already exists and is used by `domain_coordinators/manager.py:19`).
   - Enable switch: REUSED `CoordinatorEnabledSwitch` `switch.py:651-721`.
   - Master switch: REUSED `DomainCoordinatorsSwitch` `switch.py:487-535`.
   - Add entry point: REUSED `async_step_add_coordinator` `config_flow.py:1116` (currently aborts).
   - CM options menu: REUSED `async_step_init` CM branch `config_flow.py:4153-4188`.
   - Per-coordinator settings steps: REUSED (`coordinator_presence`, `_safety`, `_security`,
     `_energy`, `_hvac`, `_music_following`, `_appliance`, `_notifications`).
   - "Added" state key: **NEW** `coordinators_added` (list on CM options) — no equivalent; the
     `*_enabled` keys mean run/no-run, not "has been set up". Reusing them for both would recreate
     today's split.
   - Entitlement hook: **NEW** (no prior art in Python).
2. **Prior planning docs**: `docs/planning/AUDIT_onboarding_first_run_path.md` (Stage D, rows 104-116,
   124-125, install guide 181-190 — guide step 8 is wrong, see findings);
   `docs/planning/PLANNING_onboarding_simplify_phase2.md` S4 (changes the `add_coordinator` abort text
   to point at the switch — **conflicts with this plan's Phase B**; S4 should be dropped or reduced to
   the interim text if Phase B is not built in the same release).
3. **Memory bodies**: not pulled in this session (index lines only). Relevant per index:
   `project_single_user_no_backcompat` (2nd install live this weekend; real migrations now;
   optional integrations must degrade gracefully; visible settings over silent auto-detect),
   `feedback_label_style_guide`, `feedback_parent_entry_reload_watchdog_hazard` (enable switches
   reload the parent entry — `switch.py:707-721`), `feedback_extend_existing_never_rebuild`.
   Planner/plan-reviewer should pull bodies before build.
4. **Design docs**: `docs/architecture/DEVICE_TREE.md` and
   `docs/reviews/DEVICE_ENTITY_DEFRAG_POSTMORTEM.md` are MANDATORY for Phase C (not read in this
   session; Phase C is gated on them). HVAC state-of-play is not required: no HVAC logic changes, only
   whether HVAC is registered.
5. **Code surveyed**: `__init__.py:997-1121, 1990-2018, 3185-3420, 3505-3534, 3800-3830, 4140-4160`;
   `switch.py:175-330, 480-721`; `config_flow.py:1075-1122, 3690-3697, 4123-4240, 5011-5039,
   9442-9477`; `const.py:2905-2950`; CM-entry setup headers of `sensor.py`, `binary_sensor.py`,
   `number.py`, `select.py`, `button.py`.

## Producer / consumer check — "is this coordinator on"

- **Producers (writers):** `CoordinatorEnabledSwitch.async_turn_on/off` (`switch.py:700-721`) only.
- **Readers, trust path:** registration gates in `__init__.py` (table above), each with its own
  inline default. **Readers, display path:** `CoordinatorEnabledSwitch.is_on` with default True.
- Two readers, two defaults, one key. Fix = one default source (a dict on the key map), read by both.

## Design

### D1 — One default per coordinator; switch tells the truth (Phase A)

- Add `COORDINATOR_ENABLED_DEFAULTS` next to `COORDINATOR_ENABLED_KEYS` in `const.py` (module
  constant rung: changing a default must be reviewed). Values today: presence/safety/security/
  music_following/appliance True; energy/hvac/notification_manager False.
- `CoordinatorEnabledSwitch.is_on` reads `merged.get(key, COORDINATOR_ENABLED_DEFAULTS[id])`.
- Every registration gate in `__init__.py` reads the same dict (replace inline literals at
  `:3322, :3353, :3367, :3411, :3514, :3810, :3821, :4151`).
- Also fix `music_following.py:468` which reads the key with its own default, and
  `domain_coordinators/notification_manager.py:676` (`self._config.get(CONF_NM_ENABLED, False)`).
- Preferred shape (plan review): one helper `coordinator_should_run(cm_config, coordinator_id)` in
  `const.py`-adjacent code that every gate calls. D4's entitlement check lives inside it, so there
  is ONE site to mutate, not eight.

Acceptance criteria
- **Test:** `test_enabled_switch_default_matches_registration_default` — parametrized over all
  `COORDINATOR_ENABLED_KEYS`: with the key absent, `is_on` equals whether the coordinator is
  registered after setup.
- **Test:** mutation drill: change one registration site back to an inline literal → the test fails.
- **Live (second home):** HVAC/Energy/NM Enabled switches read `off` after deploy with no operator
  action; main house unchanged (all keys already written).

### D2 — New installs: big modules start not-added (Phase A)

- On CM entry creation (`_ensure_coordinator_manager_entry`, `__init__.py:1073-1121`, which drives
  `config_flow.py:3690`), seed CM options with
  `coordinators_added = ["presence"]` (presence is a dependency of most room behavior and has no
  required config) and explicit `*_enabled` keys: presence True, all others False.
- Safety/Security/Music/Appliance therefore no longer auto-run on a **new** install; they need to be
  added (D3). Security with empty lists does nothing useful today, so nothing is lost.
- **Existing installs (migration):** one-shot, sentinel `coordinators_added_migration_done` on the
  CM entry. **Placement (plan review, HIGH):** NOT inside the `__init__.py:3227-3300` slot — that
  slot is inside the master-switch gate (`__init__.py:3195`), so on an install with the master OFF
  (the second home today) the migration would never run and the D3 menu would show nothing added.
  Run it unconditionally in integration setup next to `_ensure_coordinator_manager_entry`
  (`__init__.py:2009-2018`), before the master gate. For every coordinator, mark it added iff its
  effective run state is True (key explicitly True, OR key absent and the D1 default is True).
  Explicit False = not added (settings kept; re-add restores). No settings-key inventory needed. Write explicit
  `*_enabled` values equal to today's effective run state. Result: **nothing that runs today stops
  running, and nothing new starts.**

Acceptance criteria
- **Test:** fresh-install fixture → after setup, only Presence registered; CM options carry the
  seeded keys.
- **Test:** migration fixture shaped like the main house (all keys explicit) → byte-identical
  registration set before vs after; sentinel set; second run is a no-op.
- **Test:** migration fixture with keys absent (pre-D1 install) → Energy/HVAC/NM stay unregistered,
  the others stay registered.
- **Live (main house):** `sensor.*coordinator_manager*` attribute listing registered coordinators is
  identical before and after deploy.

### D3 — CM menu "Add a coordinator" / "Remove a coordinator" (Phase B)

- CM options `init` menu (`config_flow.py:4157`) becomes dynamic:
  `["add_coordinator"] + [settings step for each added coordinator] + ["remove_coordinator"] + shared
  steps (signal_responses, optimization, notification sub-steps only if NM added)`.
- `add_coordinator` = menu of not-yet-added coordinators (labels per style guide: "Climate (HVAC)",
  "Energy", "Security", ...). Picking one runs the entitlement check (D4), then routes into that
  coordinator's **existing** settings step. On submit, the step's save handler appends the id to
  `coordinators_added` and sets its `*_enabled` True. Abort/back = not added, nothing written.
- Coordinators with no required config (presence, appliance, music following) can be added with a
  one-screen confirm.
- `remove_coordinator` = pick an added coordinator → confirm → remove from `coordinators_added`, set
  `*_enabled` False. **Settings are kept** (re-adding restores them). Entities stay in Phase A/B
  (become unavailable); Phase C removes them.
- The integration-level `entry_type_select` `add_coordinator` (`config_flow.py:1116`): change the
  abort to plain text pointing at "Coordinator Manager > Configure > Add a coordinator". S4 already
  shipped (5.103.36): today's `coordinator_use_options` text in `strings.json:562` +
  `translations/en.json:562` points at the master switch; Phase B rewrites both.
- Master `DomainCoordinatorsSwitch`: adding the first coordinator from the CM menu sets
  `domain_coordinators_enabled` True on the integration entry (else "add" does nothing visible).
  Keep the switch as the global kill switch.
- Enabled switch stays as a pause control for added coordinators. For a not-added coordinator, the
  switch is unavailable (Phase B) with attribute `added: false`.
- Reload: settings steps already reload via the update listener; add/remove flips a run key, which
  requires a parent reload exactly like the switch does today (`switch.py:707-721`). No new reload
  path. Known hazard: parent reload → watchdog (memory `feedback_parent_entry_reload_watchdog_hazard`);
  this is the same exposure as today's switch, not new.

Acceptance criteria
- **Test:** `test_cm_menu_lists_only_added_coordinators`.
- **Test:** `test_add_hvac_writes_added_and_enabled_on_submit_only` (abort writes nothing).
- **Test:** `test_remove_keeps_settings_and_readd_restores`.
- **Test:** `test_add_first_coordinator_turns_on_master`.
- **Live (second home):** operator adds Security from the CM menu; Security Enabled switch reads `on`,
  security sensors become available; HVAC still not listed in the settings menu.

### D4 — Entitlement hook point (design only, no enforcement)

- New module `entitlements.py` with one function
  `async def async_can_add(hass, coordinator_id) -> tuple[bool, str | None]` that returns
  `(True, None)` for every id today. Called from exactly two places: `add_coordinator` (before
  routing to the settings step; False → abort with the returned reason text) and
  `coordinator_should_run` (D1 helper; there is no registration loop — eight separate gates) (False → do not register, log once, raise a repair issue). The second call makes
  the gate hold if someone hand-edits options.
- Tiers to price later: Free = Presence, Safety, Music, Appliance; per-module = HVAC, Energy,
  Security (operator's "big modules"); NM likely free (it is plumbing other modules use).
- No license server, no token, no network call in this cycle. Ownership/verification design is a
  separate card.

Acceptance criteria
- **Test:** monkeypatch `async_can_add` to deny `hvac` → add menu aborts with the reason; existing
  added HVAC is not registered and a repair issue exists.
- **Verify:** grep shows exactly two call sites.

### D5 — Defer entity/device creation until added (Phase C, Tier 3, held)

- Each CM platform builds per-coordinator entity groups only when the coordinator is in
  `coordinators_added`. Shared CM entities (house state, coordinator manager, memory status) always.
- Removal deletes that coordinator's entities and its device via the entity/device registries.
- Needs: a per-coordinator ownership map for ~hundreds of CM entities (today they are flat lists),
  `DEVICE_TREE.md` rules (config-entry vs `via_device` axes; HA 2026.9 `via_device` RuntimeError),
  and handling for cross-coordinator entities (e.g. HVAC buttons hosted on CM, NM buttons on CM).
- Evidence trigger to build: second-home operator reports unavailable-entity clutter as a real
  problem, or paid tiers need unbought modules to be invisible.

Acceptance criteria (when built)
- **Test:** fresh install → no HVAC/Energy/Security devices in the device registry.
- **Test:** add then remove HVAC → device and entities gone; re-add → same `unique_id`s restored.
- **Live:** device count on the second home drops; main house device count unchanged.

## Non-goals

- No change to any coordinator's behavior, settings, or defaults inside its settings step.
- No license verification, payment, or remote calls.
- No deletion of `async_step_domain_coordinators` / `async_step_coordinator_toggles` in this cycle
  (onboarding phase 2 owns that triage).
- Comfort coordinator key untouched.

## Edge cases (from QUALITY_CONTEXT classes)

- **Stale data source (#7):** `cm_config` is built once per setup; migrations must run before it
  (existing pattern at `__init__.py:3227-3300`).
- **Coincidental equality (#63):** the D1 test must use the key-absent config, not the main house's.
- **Restart:** `coordinators_added` lives in CM options (persistent); no RestoreEntity.
- **Reload storms:** add/remove must write once and reload once (no double write from switch +
  flow).
- **NM dependency:** Security delegates lights to NM (`__init__.py:3402`); if NM is not added,
  delegation must fall back. Verify the existing None-NM path before Phase A ships to new installs.
- **Presence dependency:** HVAC and Security read presence; adding HVAC without Presence should
  either auto-add Presence or block with a message. Recommend auto-add (presence is seeded anyway).

## Verification steps

1. `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/ -v` (name-diff vs baseline).
2. Per-site mutation: revert each registration gate to an inline default, confirm D1 test fails.
3. Pre-deploy: read the second home's switch states (GET only) and record them.
4. Post-deploy live: table in `README_v<version>.md` with main-house registration set (unchanged)
   and second-home switch states (Energy/HVAC/NM now `off`).

## Plan-completion carry-forward

- Second-home live read was not performed by the planner (no tool). Orchestrator does it pre-build.
- Audit doc `AUDIT_onboarding_first_run_path.md` step 8 and Stage D row "HVAC already off by default"
  need correcting in the same commit as Phase A.

## Plan review (2026-10-03, one adversarial pass, Phase A+B)

Re-grepped, not trusted. Gates confirmed at `__init__.py:3322/3353/3367/3411/3514/3810/3821/4151`
with defaults T/T/T/T/F/T/F/F. `CoordinatorEnabledSwitch.is_on` default True at `switch.py:698`
confirmed; live second-home observation (all ON until manually turned off) matches.

Findings (fixed in plan above unless noted):
1. **HIGH — migration placement.** Proposed slot is inside the master gate (`__init__.py:3195`);
   never runs while master is OFF. Moved to unconditional integration setup.
2. **MEDIUM — missed readers.** `notification_manager.py:676` (default False, agrees) not listed;
   also unreachable `config_flow.py:9462-9470` defaults (leave; onboarding phase 2 triages).
3. **MEDIUM — "settings keys present" rule undefined** (no per-coordinator key inventory exists).
   Replaced by effective-run-state only; preserves exactly what runs today.
4. **MEDIUM — entitlement "registration loop" does not exist.** Folded into one
   `coordinator_should_run` helper used by all eight gates (also makes D1 one mutation site plus a
   per-gate call-neuter drill).
5. **LOW — S4 already shipped** the master-switch text; Phase B rewrites `strings.json` +
   `translations/en.json` line 562.
6. **Reload/restart: holds.** `CoordinatorEnabledSwitch` is not a RestoreEntity; state comes from
   CM options, so a reload cannot reset it once the key is explicit. The only "code default" exposure
   is key-absent, which the migration closes by writing explicit keys. Not the CPR failure shape.
7. **Note for build:** D3 "first add turns on master" writes the integration entry AND the CM entry;
   write both, then reload the parent once (no double reload).

Verdict: **BUILD-READY** (after the edits above).
