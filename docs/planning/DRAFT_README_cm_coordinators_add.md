# DRAFT README — Add coordinators one by one (CM-COORDINATORS-ADD-ONE-BY-ONE-1, Phase A + B)

Plan: `docs/planning/PLANNING_cm_coordinators_add_one_by_one.md`. Phase C (hide devices/entities
of coordinators that are not added) is NOT in this build.

## What changes

- **Enabled switches tell the truth.** Every coordinator has one default in
  `COORDINATOR_ENABLED_DEFAULTS` (`const.py`). The 8 registration gates in `__init__.py`, the
  Enabled switch, NM `enabled` and the music-following kill switch all go through
  `coordinator_gate.coordinator_should_run`. Before: on a fresh install the Energy, HVAC and
  Notifications switches read ON while those coordinators were not running.
- **New installs start with only Presence added** (and running). Everything else is added from the
  Coordinator Manager.
- **Existing installs: nothing starts or stops.** A one-shot migration (runs at integration setup,
  even with the Domain Coordinators switch off) writes each coordinator's current run state
  explicitly and marks the running ones as added. Sentinel: `coordinators_added_migration_done`
  on the CM entry.
- **Coordinator Manager > Configure** now shows:
  - **Add a coordinator** — lists coordinators not yet added. Picking one opens its settings
    (Safety, Security, Energy, Climate (HVAC) tuning, Notifications) or a one-screen confirm
    (Presence, Music following, Appliances). It is added only when you save. Closing the dialog
    adds nothing. Adding Climate or Security also adds Presence.
  - Settings for **added** coordinators only.
  - **Remove a coordinator** — stops it. Its settings are kept; adding it again restores them.
  - Signal responses and Optimizer, as before.
- **First add turns on Domain Coordinators** if it was off (that is the one parent reload). With
  it already on, add/remove schedules one parent reload, same as the Enabled switch.
- A coordinator that is not added shows its Enabled switch as unavailable (attribute
  `added: false`); turning it on does nothing until it is added.
- The integration "Add coordinator" entry now says to use Coordinator Manager > Configure > Add a
  coordinator.
- **Entitlement hook** (`entitlements.can_use_coordinator`): allows everything today. Called from
  the Add step (deny = abort with the reason) and from the run gate (deny = not run, logged once,
  repair issue `coordinator_not_entitled_<id>`).

## Live acceptance (to fill after deploy)

| Check | Expected | Result |
|---|---|---|
| Main house: registered coordinator set before vs after | identical | |
| Main house CM options | `coordinators_added` = running set; sentinel true | |
| Second home: Energy/HVAC/NM Enabled switches | `off` with no operator action (if their keys were never written) | |
| Second home: add Security from the CM menu | Security Enabled `on`, security sensors available | |
| CM menu on second home | HVAC settings not listed until added | |

## Not done

- Phase C (defer entity/device creation) — held, Tier 3, evidence trigger in the plan.
- `AUDIT_onboarding_first_run_path.md` step 8 / Stage D row correction — that file is not on this
  branch (untracked in the main checkout); correct it there.
- Full registration-block run (real `async_setup_entry`) is not exercised in tests; gate binding is
  proven by an AST test (each of the 8 sites calls the helper with its id) plus mutation drills.
