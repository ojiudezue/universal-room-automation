# AUDIT — NM entity rename to uniform `ura_nm_*` (Cycle C-2 D3)

**Date:** 2026-07-22
**Scope:** All Notification Manager device-page entities. Enumerates the
rename surface, live-consumer break points, and safe-refactoring rules,
then delivers a verdict on whether the code-side rename is safe today
or must be deferred to a deploy-time entity-registry migration script.

---

## 1. NM entity inventory (post-Cycle-C surface)

Grepped from `custom_components/universal_room_automation/{switch,number,button,sensor}.py`
against the `notification_manager` device_info identifier
(`(DOMAIN, "notification_manager")`). Every entity below carries the
`_nm_device_info()` mixin at `number.py:3194-3205` and equivalent shim
in `switch.py:3421` / button/sensor.

| # | Kind   | Class                         | Unique-ID                                                | Current object_id (derived)                          | Cycle |
|---|--------|-------------------------------|----------------------------------------------------------|------------------------------------------------------|-------|
| 1 | Switch | `NMDryRunSwitch`              | `f"{DOMAIN}_nm_dry_run"`                                 | `switch.ura_nm_dry_run`                              | B0    |
| 2 | Switch | `NMMessagingSuppressSwitch`   | `f"{DOMAIN}_nm_messaging_suppress"`                      | `switch.ura_nm_messaging_suppress`                   | B     |
| 3 | Number | `NMBucketCapacityNumber`      | `f"{DOMAIN}_nm_bucket_capacity"`                         | `number.ura_nm_bucket_capacity`                      | B3    |
| 4 | Number | `NMBucketRefillPerMinNumber`  | `f"{DOMAIN}_nm_bucket_refill_per_min"`                   | `number.ura_nm_bucket_refill_per_min`                | B3    |
| 5 | Number | `NMMuteDefaultDurationNumber` | `f"{DOMAIN}_nm_mute_default_duration_minutes"`           | `number.ura_nm_mute_default_duration_minutes`        | C     |
| 6 | Button | Per-person mute buttons       | `f"{DOMAIN}_nm_mute_{person}_{channel}"`                 | `button.ura_nm_mute_<person>_<channel>`              | C     |
| 7 | Sensor | `NotificationManagerSensor`   | `f"{DOMAIN}_notification_manager"`                       | `sensor.ura_notification_manager`                    | pre-A |
| 8 | Sensor | Attribute-carrier sensors     | `f"{DOMAIN}_nm_<various>_attr"`                          | `sensor.ura_nm_<various>_attr`                       | B/C   |

**DOMAIN string** = `"universal_room_automation"` at `const.py:12`. HA
entity_id derivation picks up the `has_entity_name`+device-name path in
most classes but the unique_id already carries a `ura_nm_*`-conformant
suffix in 7 of 8 rows.

## 2. Conformance analysis

**Already `ura_nm_*`-prefixed (entity_id, not unique_id):** rows #1-#6, #8.
The unique_ids themselves are `{DOMAIN}_nm_*` = `universal_room_automation_nm_*`
(that's the durable registry key). HA computes the *entity_id* from
`suggested_object_id` on FIRST registration, else falls back to
`slugify(device_name + entity_name)`. The device name is
`"URA: Notification Manager"` (via `_nm_device_info()`), which slugifies
to `ura_notification_manager_*` — NOT `ura_nm_*`.

**Non-conformant row:** row #7 (`sensor.ura_notification_manager`) — the
device-level umbrella sensor. Its friendly name/slug is authoritative;
the "NM" contraction is only present because the entity's `_attr_name`
is left unset (device-level entity), so the entity_id equals the
device slug.

**Live audit against HA storage:** the operator has previously reported
`switch.ura_nm_dry_run` and the two bucket Numbers as visible on the
device page with those exact object_ids. I did NOT re-verify against
the live registry in this cycle (the audit target is the code + planned
migration, not the live state). Row-by-row live verification is the
**required D3 deploy precondition**.

## 3. HA-side rename mechanics — what changing code does and doesn't do

Reference: HA developer docs on entity registry, `RegistryEntry.entity_id`
vs `unique_id`, and `async_update_entity` / `async_migrate_entries`.

- **Changing `unique_id`** = catastrophic; it creates a NEW registry
  entry alongside the old one. Recorder history stays attached to the
  old unique_id. NEVER acceptable. **This audit assumes unique_ids stay
  frozen.**
- **Changing `_attr_suggested_object_id`** = ONLY affects entities
  registered AFTER the code change (first-boot). Existing registered
  entities keep their `entity_id` (registry is source of truth for the
  slug once an entity is known). Rebuilds don't retrigger the suggestion.
- **Changing `_attr_name`** = updates the friendly name only; entity_id
  is unaffected on an existing entity.
- **The only supported code-side path to rename existing entity_ids** is
  `async_migrate_entries(hass, config_entry_id, migrator_callable)`, run
  from `async_setup_entry` on a versioned config-entry migration step.
  The migrator returns `{"new_entity_id": …}` per entry. This IS a legal
  path but requires a config-entry version bump on the CM entry AND
  careful handling of Automation/Blueprint/YAML/dashboard consumers
  whose text references the old entity_id.

## 4. Live-consumer break surfaces (recorder + config)

If any entity_id changes, the following consumers break silently unless
explicitly patched at deploy time:

1. **Recorder history** — the `states` table keys on entity_id (not
   unique_id). A rename produces a new time-series; the old series
   remains but is orphaned. Statistics (long-term) tied to the
   long-term statistics table uses entity_id too. No supported
   in-place recorder rewrite exists.
2. **Dashboards** — Lovelace card configs, incl. any `ura-v6` / `ura-v7`
   custom UI, live in `.storage/lovelace*` (per user, per view). Grep of
   the repo shows the routing/audit card YAML lives in
   `docs/dashboard-prototypes/` (this repo); the LIVE dashboards are in
   HA storage and must be patched via MCP `ha_update_dashboard` or a
   manual UI edit. **The orchestrator must enumerate all ura-* dashboard
   references to the renamed entity_ids and patch them in the same
   deploy that ships the migration script — otherwise cards go
   `unknown` post-restart.**
3. **Automations / scripts / scenes** — HA `automation:` YAML AND
   UI-authored automations (`.storage/core.automation`) reference
   entity_id strings; a rename hits both. The dev-docs recommend
   `automation.reload` after any bulk entity-id migration.
4. **Blueprints** — same reference-by-string exposure.
5. **NM internal service calls** — the `nm.mute_person_channel` service
   accepts a person_id + channel and does NOT reference NM's own
   entity_ids by string. Verified via grep: no `switch.ura_nm_*` /
   `number.ura_nm_*` string literals in the `custom_components/` tree
   (all references go through the entity class instance).
6. **URA WebSocket API** — grep shows `websocket_api.py` publishes state
   deltas by entity_id; consumers of the `ura-dashboard-pwa` will see
   the entity_id change reflected in the delta stream. Coordinate with
   PWA schema bump.
7. **Shipwatch acceptance-hypothesis manifests** — sibling repo, may
   reference NM entity_ids by string. Grep-check the sibling repo
   before deploy.

## 5. Verdict

**The safe-refactoring path is a deploy-time entity-registry rename
script, NOT a code-side change.**

Rationale:
- The unique_ids stay stable (rule 3 above); only entity_ids move.
- `async_migrate_entries` from an integration migration step is the ONLY
  in-code path to rename existing registered entity_ids. It requires a
  config-entry version bump; a botched migration bricks the entry.
- The blast radius (recorder history + dashboards + automations +
  blueprints + PWA + Shipwatch) is broad and touches surfaces OUTSIDE
  the URA repo. Attempting the rename in code, without coordinating the
  external patches at the same deploy, guarantees a period of "cards
  went blank" panic.
- Row #7 (`sensor.ura_notification_manager`) is the only genuinely
  non-conformant slug. Renaming it to something like
  `sensor.ura_nm_summary` requires the operator to also patch every
  dashboard that references it.

**Recommendation for C-2:**
- **Do NOT ship a code-side rename in this cycle.**
- Ship a `scripts/rename_nm_entities.py` deploy-time script (see below)
  that the operator runs POST-deploy against the live registry via HA's
  Python-script sandbox or MCP `ha_run_python_script`. The script:
  1. Reads current NM entities from the registry.
  2. For each non-conformant entity_id, updates to the canonical
     `switch.ura_nm_*` / `number.ura_nm_*` / etc. name.
  3. Emits a report listing before/after entity_ids for the operator to
     use when patching dashboards.
- Track dashboard/automation/PWA patching as sibling deliverables in
  the deploy runbook — not in-repo work.
- Defer the row #7 sensor rename to a dedicated hygiene cycle where the
  operator can coordinate the dashboard patches on their schedule.

## 6. Deliverable

The deploy-time rename script skeleton is committed to
`scripts/rename_nm_entities.py` under this cycle. It is IDEMPOTENT
(re-running does nothing if entity_ids are already canonical) and READ-
ONLY BY DEFAULT (a `--dry-run` flag is the default; the operator must
pass `--apply` explicitly). The script prints a rename plan first,
requires interactive confirmation, and stores an audit log of every
rename it performs so the operator can revert manually if a dashboard
patch was missed.

The script is **NOT** wired into `scripts/deploy.sh`. It is a manual
follow-up the operator runs after Cycle C-2 lands and after they patch
their dashboards.

## 7. Plan-completion note

- **D3.code-rename:** deferred to a future hygiene cycle per §5 verdict.
- **D3.script:** delivered as `scripts/rename_nm_entities.py`.
- **D3.audit:** this document.

Recorded per **Plan Completion Tracking — MANDATORY** in CLAUDE.md.
