# PLANNING — Room/Zone rename write-through (ROOM-NAME-DESYNC-1)

**Rev-2** (plan review fix-up 2026-08-13, addressing C1-C4 HIGH + M1-M3 MED
+ L2). Scope-expanding change: **CONF_ZONE folded into D1** per C4 (same
class, verified reader at aggregation.py:502).

**Tier:** 2-DB (elevated: shared join-key threading through presence ↔ substrate ↔
room coordinator ↔ HVAC ↔ ~17 modules; failure mode is one missed site — Bug
Class #53 shape; parent audit already prescribes Tier 2-DB minimum).
**Card:** ROOM-NAME-DESYNC-1 (docs/planning/kanban.data.yaml).
**Parent audit (READ FIRST):** docs/planning/AUDIT_zone_tier_divergence.md.
**Operator direction:** *"We should be able to rename rooms and be correct."*
Structural fix. The 2026-08-13 hand-sync of the three known rooms is a
mitigation, not a fix, and creates ZERO urgency-driven shortcuts.

---

## 1. Falsifiable invariant (state up front — D falsifies exactly this)

> **I1 — For every loaded URA config entry, every name-consuming (and every
> zone-assignment-consuming) code path resolves the SAME string, and an
> options-flow rename or zone-reassign is observed by every path within a
> single reload cycle.**

Concretely, for every ROOM entry `e` and every ZONE entry `z`:

- `e.data[CONF_ROOM_NAME] == e.options.get(CONF_ROOM_NAME,
  e.data[CONF_ROOM_NAME])` immediately after the rename handler's single
  combined `async_update_entry` call returns (§D1 recipe), and identically
  after the D2 boot migration on pre-existing desyncs. Same clause for
  `CONF_ZONE_NAME` on zone entries and for `CONF_ROOM_NAME`,
  `CONF_ZONE_NAME`, **and `CONF_ZONE`** on rooms.
- After a rename save, `ZonePresenceTracker.room_names`,
  `OccupancySubstrate` bucket keys, `_room_to_zone`, `_fan_entity_to_room`,
  `PresenceHouseStateSensor.extra_state_attributes[<zone>].fan_on_rooms`,
  **and the aggregation-tier zone assignment (`aggregation.py:502`,
  `:964`, `:1014`, `:3839-3840`, `:6060`)** all agree on the new value
  (proven by driving a rename in-suite against real code and asserting
  substrate edges arrive at the tracker and the aggregation reader picks
  up the new zone).

**How to falsify:** produce a legal-config code path that reads a
name/zone field from `entry.data` (or from a merged construction) and
yields a different string than another consumer of the same entry after
a rename or zone reassignment. D's job is to find that path — including
in pre-existing modules the diff does not touch.

---

## 2. Institutional context verified

### Greps run + counts

- `rg 'CONF_ROOM_NAME|CONF_ZONE_NAME' custom_components/universal_room_automation`
  → **125 occurrences across 19 modules**; ~96 read sites outside
  `config_flow.py`/`const.py`.
- `rg 'room_name' custom_components/universal_room_automation` → **1173
  occurrences across 36 modules** (superset — includes local variables and
  log fields; the CONF grep above is the authoritative call-site count).
- `rg 'CONF_ZONE\b' custom_components/universal_room_automation/aggregation.py`
  → 6 reader sites (502, 964, 1008-comment, 1014, 3839-3840, 6060). Five are
  code readers; **the pre-existing convention split lives here too**:
  - **data-first + options fallback** (mirrors the presence.py:2868 bug
    shape): `aggregation.py:502` — `data.entry.data.get(CONF_ZONE) or
    data.entry.options.get(CONF_ZONE)`.
  - **options-first + data fallback**: `aggregation.py:964`, `:1014`,
    `:6060`.
  - **both, compared** (rare correct form): `aggregation.py:3839-3840`.
- `rg '_ROOM_SUPPRESS_KEYS'` → `__init__.py:6147-6161`. **CONF_ZONE is in
  the suppress set** (line 6151). This means an options-only zone
  reassignment does NOT trigger a reload; combined with the data-first
  reader at aggregation.py:502, the drift persists indefinitely — the
  exact starvation shape the cycle exists to kill.
- `rg '\{\*\*.*data.*\*\*.*options|\{\*\*.*options.*\*\*.*data'
  custom_components/universal_room_automation` → **50+ merged-dict
  constructions** across `config_flow.py`, `select.py`, `switch.py`,
  `button.py`, `sensor.py`, `binary_sensor.py`, `coordinator.py`,
  domain coordinators. Options-first merge is the dominant idiom.
- `rg 'entry\.(data|options)\.(get|\[)[^)]*(ROOM_NAME|room_name|ZONE_NAME|zone_name)'`
  → the three name conventions the parent audit named (data-only,
  merged options-first, data-OR-options explicit fallback).
- `rg 'add_update_listener' custom_components/universal_room_automation/__init__.py`
  → **four setup registration sites: 3655, 3805, 4055, 4168**. D2's
  ordering constraint must hold at all four (§D2 checklist).

### Initial-create paths are synced at birth (L2)

The initial config-flow create sets `entry.data` from the user_input dict
(config_flow.py:2160-2170 for rooms; 7943-7955 for legacy zones), so
`entry.options` is empty at birth and the readers all resolve to the data
value trivially. Drift arises exclusively at RENAME / REASSIGN time in
the options flow. This is why D2 migration is expected to be a full no-op
on any freshly-created entry AND on the three 2026-08-13 hand-synced
rooms.

### Prior planning docs consulted

- `docs/planning/AUDIT_zone_tier_divergence.md` (full read — the bug of
  record; §Q5 prescribes the two-rung fix, this doc scopes the code rung).
- `docs/planning/AUDIT_away_transition_2026_08_13.md` (parent audit,
  §F2/§Follow-up 5 — how the divergence surfaced in a live away transition).
- Kanban `STUCK-SENSOR-1` card (sequencing — its exclusion policy keys
  rooms via the substrate; must not race the rename fix).

### Memory bodies pulled

- `feedback_no_fabrication` — "verify in source; don't invent." Every write
  site and read site cited here is a grep result, not a mental model.
- `feedback_suppression_needs_discharge` — the options-flow reload
  suppression allowlist (`_ROOM_SUPPRESS_KEYS`) is a discharge surface;
  CONF_ZONE living IN that allowlist is what makes the reassignment drift
  invisible today. See §D1 site 3 for the interaction.
- `feedback_context_wide_scoping` — the name key threads rooms + zones +
  house + HVAC + aggregation; enumeration below covers all five tiers.

### Design docs read

- Coordinator design docs are silent on name resolution (the bug is
  cross-coordinator by construction — no single doc owns it).

### Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/config_flow.py:9108-9165`
  (room `async_step_basic_setup` — the actual rename entry point;
  options-flow `async_create_entry(data=merged)` writes to `entry.options`,
  never touches `entry.data`).
- `config_flow.py:7797-7955` (zone `async_step_zone_rooms`): three
  branches — ZM-owned (out of scope), legacy zone via
  `async_update_entry` at 7938, **and a THIRD write site at 7943-7955
  (`async_create_entry` else-branch — see §D1 site 3)**.
- `config_flow.py:2160-2170` (initial room create — see L2 note above).
- `domain_coordinators/occupancy_substrate.py:190-220` (merged read;
  bucket keyed by merged name).
- `domain_coordinators/presence.py:2864-2876` (tracker resolves
  `entry.data.get(CONF_ROOM_NAME)` — the read that starves).
- `aggregation.py:502, 964, 1014, 3839-3840, 6060` (CONF_ZONE readers —
  now in scope per C4).
- `__init__.py:3655, 3805, 4055, 4168` (the four `add_update_listener`
  registration sites — D2 ordering).
- `__init__.py:6147` (`_ROOM_SUPPRESS_KEYS` — the reload-suppression set;
  D1 write-through must remain compatible with this).
- `__init__.py`: `rg 'async_migrate_entry'` returns 0. The integration
  has no `async_migrate_entry` today; D2 runs as an idempotent setup-time
  pass. **Reviewer-A direction verbatim: no VERSION bump absent a
  schema-shape change** (M3). The write-through does not change the
  shape — it makes two existing keys agree — so the version stays.

---

## 3. ROOT SHAPE — accessor migration vs write-through: adjudication

**RECOMMENDATION: WRITE-THROUGH (D1) + BOOT MIGRATION (D2) + INVARIANT
TEST (D3). Do NOT undertake the accessor migration in this cycle.**

Grounds:

| axis | accessor migration | write-through |
|---|---|---|
| touch surface | ~96 name-read sites across 17 modules + ~5 CONF_ZONE reader sites, ≥3 conventions to unify | 3 write sites (room `basic_setup`, legacy zone `zone_rooms` update-branch AND create-branch) + 1 boot migration + 1 invariant test |
| failure mode | one missed site keeps the bug alive AND now the "right" answer is convention-dependent, making the next diverging site harder to detect | one missed WRITE site keeps `data` stale for that path, but every reader still converges (options == data by construction) — the class is killed at the producer |
| reload suppression | orthogonal | CONF_ROOM_NAME / CONF_ZONE_NAME are NOT in `_ROOM_SUPPRESS_KEYS` (rename triggers reload — correct). **CONF_ZONE IS in `_ROOM_SUPPRESS_KEYS`** — the write-through fixes the drift without needing to remove the suppression, because both data and options are now written by the same call and readers converge regardless of reload. |
| operator model | "every reader must know the merge rule" — leaky | "the twin fields are always equal; readers are byte-identical to today" — internal |
| test authority | must retrofit tests to prove every reader picked up the accessor | one integration test drives the real options flow and asserts data followed (§D3) |

**Bug Class #53 shape recognition:** the accessor migration is exactly the
"computed-but-not-consumed" trap. Write-through inverts the shape: the
producer guarantees equality, so consumer conventions become irrelevant.

**Non-adopted parked idea (record, don't build):** a single
`get_room_name(entry)` / `get_zone(entry)` helper module remains a
legitimate hygiene refactor. Trigger to revisit: any future field where a
data/options desync is not fixable at the producer (e.g., an
operator-editable list where the write is external).

**Operator decisions needed:** zero. Proceeding without a checkpoint.

---

## 4. Independent consumer enumeration (re-run for reviewers)

### 4.1 Room-name readers (§ audit + rev-1 enumeration; unchanged)

See rev-1 §4.1 — 96 sites across three conventions. Not re-listed here.

### 4.2 Zone-name readers (legacy zone entries)

See rev-1 §4.2.

### 4.3 CONF_ZONE readers on room entries (NEW in rev-2 per C4)

| convention | site | consumed for |
|---|---|---|
| data-first + options fallback (**bug shape**) | `aggregation.py:502` | zone-tier aggregation lookup |
| options-first + data fallback | `aggregation.py:964, :1014, :6060` | zone-tier readers (correct today by luck of convention) |
| compared explicitly | `aggregation.py:3839-3840` | rare — options and data compared |
| suppress set | `__init__.py:6151` (CONF_ZONE in `_ROOM_SUPPRESS_KEYS`) | reload is skipped when only CONF_ZONE changes → data drift is permanent under options-only writes |
| room writer (options-only) | `config_flow.py:7869, 7882` (zone-rooms handler mutating a room's `CONF_ZONE` when the zone is renamed or the room reassigned) | this is exactly where drift is created |

### 4.4 Fields NOT in scope (record, do not touch)

- ZM-owned zones (`zones` dict inside the Zone Manager entry): renamed via
  `_auto_mirror_to_siblings` — different mechanism, not implicated.
- `CONF_ROOM_TYPE`, `CONF_AREA_ID`: same drift shape in principle but no
  live cross-coordinator join-key reader depends on them. Follow-up.

---

## 5. Deliverables

### D1 — Options-flow rename/reassign writes through to `entry.data`

**Per-site recipe (C1 — SINGLE combined call per site; NO second entry
write; folds M1 title= into the same call):**

The recipe for each site is:

```python
new_name = user_input[CONF_ROOM_NAME]        # or CONF_ZONE_NAME
merged_options = {**self._config_entry.options, **user_input}
merged_data = {
    **self._config_entry.data,
    CONF_ROOM_NAME: new_name,                # or CONF_ZONE_NAME
}
self.hass.config_entries.async_update_entry(
    self._config_entry,
    data=merged_data,
    options=merged_options,
    title=new_name,
)
# End the flow WITHOUT a second entry write:
return self.async_abort(reason="reconfigure_successful")
```

**Why `async_abort` and not `async_create_entry`:** HA's OptionsFlow
`async_create_entry(title=..., data=...)` internally calls
`hass.config_entries.async_update_entry(entry, options=data)` — a
SECOND write, which would fire the update-listener twice (C1 build
prediction: builder writes two sequential updates). `async_abort`
terminates the flow with no additional entry write. Verify against
`homeassistant.config_entries.OptionsFlow` in the installed HA version
before shipping; if the current HA release added a "no-op if data
unchanged" short-circuit, prefer that AND still spec `async_abort` as
the belt.

*Reviewer-A verify:* cite the HA source file:line for the
OptionsFlow contract used (`async_abort` on an options flow is safe /
completes cleanly; no options are persisted from an aborted options
flow). If A cannot cite it, escalate as a plan-review finding — do not
proceed on assumption.

**Sites (three, per C3):**

1. **Room rename** — `config_flow.py:9112-9128`
   (`OptionsFlow.async_step_basic_setup`).
   - Fields to write through: `CONF_ROOM_NAME`, `CONF_ZONE` (per C4).
   - Listener behavior: `_ROOM_SUPPRESS_KEYS` (init.py:6147) excludes
     `CONF_ROOM_NAME` (reload fires) but INCLUDES `CONF_ZONE` (reload
     suppressed). The write-through is safe under BOTH cases because the
     options change and the data change happen in the same
     `async_update_entry` call; whether the listener reloads or applies
     in-place, both fields are already coherent by the time any consumer
     runs.
2. **Legacy zone rename — update branch** — `config_flow.py:7938`.
   - Field: `CONF_ZONE_NAME`.
   - Convert the existing `async_update_entry(zone_entry,
     options=new_zone_options)` into
     `async_update_entry(zone_entry, data={**zone_entry.data,
     CONF_ZONE_NAME: zone_name}, options=new_zone_options,
     title=zone_name)`.
   - Listener behavior: standard reload (CONF_ZONE_NAME not suppressed).
3. **Legacy zone rename — create-entry else-branch** — `config_flow.py:7943-7955`
   (C3 finding).
   - Reachability: this else-branch runs when `zm_result` is falsy AND
     `_selected_zone_entry_id` is falsy — i.e., a zone-flow save
     without a resolved zone entry ID at save time. Call-graph tracing
     from `async_step_zone_rooms` shows the branch is reached via the
     initial zone create/reconfigure path when `_selected_zone_entry_id`
     was not set upstream. **We choose to fix, not prove-unreachable**
     (belt): the risk of proving unreachable and being wrong is exactly
     the drift the cycle exists to kill; the fix is 3 lines.
   - Recipe: replace `async_create_entry(title="", data={...})` with
     the standard combined-call recipe above against `zone_entry`.

**Class coverage:** the three fields (`CONF_ROOM_NAME`,
`CONF_ZONE_NAME`, `CONF_ZONE`) are the only fields the enumerations in
§4 confirm have a live cross-coordinator join-key shape.

**Acceptance criteria:**

- **Verify:** rename a test room via the real options flow in-suite;
  `entry.data[CONF_ROOM_NAME] == entry.options[CONF_ROOM_NAME] == new
  name` when the coroutine returns; **`entry.title == new_name`** (M1).
- **Verify:** reassign a test room's `CONF_ZONE` via the options flow;
  `entry.data[CONF_ZONE] == entry.options[CONF_ZONE]` when the coroutine
  returns. aggregation.py:502 reads the new value on next tick.
- **Verify:** EXACTLY ONE `_async_update_listener` invocation per save
  (no double-reload regression). Assert via a spy on the update-listener
  registered in `__init__.py:_async_update_listener`.
- **Verify:** the options-flow context ends cleanly after `async_abort`
  (no HA framework warning; the flow does not appear as "in progress"
  after the coroutine returns).
- **Test:** `tests/config_flow/test_room_rename_writethrough.py::
  test_room_rename_updates_data_options_and_title`,
  `::test_room_zone_reassign_updates_data_and_options`,
  `::test_zone_rename_update_branch_updates_data`,
  `::test_zone_rename_create_branch_updates_data`,
  `::test_room_rename_single_listener_invocation`,
  `::test_zone_rename_single_listener_invocation`.

### D2 — One-shot boot migration syncing existing desyncs

**Ordering constraint (C2 — checklist Reviewer-A verifies at each site):**

The migration pass MUST run BEFORE `entry.add_update_listener(
_async_update_listener)` at **all four** setup registration sites:

- [ ] `__init__.py:3655` (integration entry setup branch) — migration
      call placed above line 3655 in the same branch.
- [ ] `__init__.py:3805` (room entry setup branch) — migration call
      placed above line 3805.
- [ ] `__init__.py:4055` (zone entry setup branch) — migration call
      placed above line 4055.
- [ ] `__init__.py:4168` (other/fallback setup) — migration call placed
      above line 4168.

Rationale: an `async_update_entry` from the migration BEFORE the
listener is registered cannot fire the listener → cannot cascade a
reload during setup → cannot trigger the parent-reload-watchdog hazard
(memory: `feedback_parent_entry_reload_watchdog_hazard`). Ordering
alone is sufficient.

**Explicit non-addition:** a per-entry "setup-in-progress" guard is
NOT required if the four-site ordering holds. Do not add both — the
guard would be dead defense and adds a state field for the builder
to keep in sync.

**Change:** helper `_migrate_room_zone_name_writethrough(hass, entry)`
in `__init__.py`. Called at the top of each of the four setup branches
BEFORE listener registration. For `entry.entry_type in
{ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE}`, for each key in
`(CONF_ROOM_NAME, CONF_ZONE_NAME, CONF_ZONE)` that is present in
`entry.options` and differs from `entry.data`, call
`hass.config_entries.async_update_entry(entry, data={**entry.data,
<key>: entry.options[<key>]})` and log INFO. Skip keys that don't
apply to the entry type (rooms don't have CONF_ZONE_NAME, zones don't
have CONF_ROOM_NAME/CONF_ZONE).

**Idempotence:** the check is `options[key] != data[key]`, so entries
already in agreement (including the three hand-synced 2026-08-13 rooms)
are no-ops.

**Acceptance criteria:**

- **Verify:** fixture with a desynced room → one INFO log line per
  desynced key + data updated.
- **Verify:** fixture with agreement → zero updates + zero log lines.
- **Verify:** run the migration twice on the same fixture → second run
  is a full no-op (zero `async_update_entry` calls).
- **Verify:** the migration's `async_update_entry` call at setup time
  does NOT fire `_async_update_listener` (listener not yet registered).
  Spy on the listener; assert zero invocations during setup.
- **Test:** `tests/test_setup_room_name_migration.py::
  test_migration_syncs_desynced_room_name`,
  `::test_migration_syncs_desynced_zone_assignment`,
  `::test_migration_syncs_legacy_zone_entry_name`,
  `::test_migration_noop_when_in_sync`,
  `::test_migration_idempotent_second_run`,
  `::test_migration_runs_before_update_listener_at_all_four_sites`.
- **Live:** post-deploy, grep HA log for the migration INFO lines. The
  three hand-synced rooms produce ZERO lines (already in sync).

### D3 — Invariant test + runtime desync surfacing

**D3a — In-suite invariant test.** Drive the real options-flow rename
against a real config-entry fixture (NOT a monkeypatched shortcut),
assert:

- `entry.data[CONF_ROOM_NAME] == entry.options[CONF_ROOM_NAME]` after
  save; same for `CONF_ZONE` reassignment.
- After the room reload cycle, a `SIGNAL_SUBSTRATE_KIND_CHANGED`
  dispatch for the renamed room reaches `_on_substrate_kind_changed`
  and is NOT dropped as "unknown room" (presence.py:3082-3090).

**Reload-await mechanism (M2 — no green-flaking race):** the test MUST
NOT assert substrate → tracker delivery until the reload triggered by
the rename has completed. Two acceptable mechanisms; the builder picks
one and cites the HA hook used:

1. `await hass.async_block_till_done()` after the flow save AND after
   the presence coordinator's setup-complete signal (subscribe to
   `SIGNAL_PRESENCE_READY` — or the equivalent existing dispatch — via
   `async_dispatcher_connect` and await the future). Two barriers, not
   one, because `async_block_till_done` alone races with scheduled
   reloads.
2. Await the specific `ConfigEntry.async_wait_for_state` or equivalent
   "loaded" future exposed on the reloaded entry.

If neither hook exists, the test spies on the tracker's
`update_room_occupancy` and asserts under a bounded `async_timeout`
(≤5s) — but a spy-with-timeout is inferior; prefer barrier mechanisms.

**Falsifier drill (Review C reruns as gate):** revert D1 site 1 (delete
`data=` from the room rename `async_update_entry`); D3a's rename test
MUST turn red. Revert D2 (make `!=` always False → no-op); D2's
idempotency-under-desync test MUST turn red. Green under either
mutation = hollow anchor, DO NOT SHIP.

**D3b — Runtime desync diagnostic.** Cheap boot-time check inside
`async_setup_entry` (post-D2 migration): iterate ROOM/ZONE entries; if
any still show `options[key] != data[key]` for any of the three fields,
fire an NM note via the existing `_stuck_signal_nm` shape (kind =
`room_name_desync`, per-day dedup) naming the entry_id + field + both
strings. Catches future manual `.storage` edits.

**Acceptance criteria:**

- **Test:** `tests/presence/test_rename_invariant.py::
  test_rename_reaches_tracker_after_reload_barrier`,
  `::test_zone_reassign_reaches_aggregation_after_reload_barrier`,
  `::test_falsifier_drill_reverting_writethrough_reddens_this_test`
  (documented mutation the reviewer re-runs — see §8 Review C).
- **Sensor:** none new; NM note surface reused.
- **Live:** on a running instance with all entries in sync, ZERO
  `room_name_desync` NM notes fire post-boot. Manually flip one entry's
  `.storage` after restart and confirm the NM note appears at next
  boot check (documented in README live-validation section).

---

## 6. Knob ladder

**Zero knobs.** Every value in this cycle is invariant (twin fields
must be equal — no operator-tunable slack). The `get_room_name`
accessor question is a code-refactor decision, not a runtime knob, and
is parked per §3.

---

## 7. Non-goals

- **Accessor migration** across the ~96 read sites (§3).
- **CONF_ROOM_TYPE / CONF_AREA_ID data-options drift audit** —
  follow-up.
- **Removing CONF_ZONE from `_ROOM_SUPPRESS_KEYS`** — orthogonal; the
  write-through makes the suppression compatible with correctness.
- **ZM-owned zones (`zones` dict) rename hardening** — different code
  path, not implicated.
- **`async_migrate_entry` harness / VERSION bump** (M3, Reviewer-A
  direction verbatim): no VERSION bump absent a schema-shape change.
  The write-through does not change the shape; it makes two existing
  keys agree. D2 stays as an idempotent setup-time pass.
- **Dashboard sensor for desync** — NM note is sufficient.
- **Rewiring `presence.py:2868` or `aggregation.py:502` to
  belt-and-suspenders merged reads** — deliberately declined; the audit's
  Q5 rung-2 accessor is what §3 parks. Half-migration creates a
  convention split without killing the class.

---

## 8. Three review framings (Tier 2-DB)

Run in parallel; do NOT share framings.

- **Review A — Data integrity + write-path correctness.** For each of
  the three D1 sites, verify the combined `async_update_entry(data=,
  options=, title=)` semantics: does it fire the update-listener EXACTLY
  ONCE? Cite the HA source path for the OptionsFlow `async_abort`
  contract and for whether `async_update_entry` short-circuits on
  no-op-diff. For D2, walk the checklist in §D2 for each of the four
  `add_update_listener` sites and confirm ordering. Confirm no VERSION
  bump. Enumerate fields `entry.data` gets seeded with at initial create
  (config_flow.py:2160-2170) and confirm none are silently reverted by
  the write-through.
- **Review B — Migration correctness + cross-coordinator signal chain.**
  Trace substrate → tracker AND aggregation-tier `CONF_ZONE` readers
  BEFORE and AFTER D1+D2 apply against re-desynced fixtures for each of
  the three fields. Prove `tracker.room_names`, `_room_to_zone`,
  `_fan_entity_to_room`, `PresenceHouseStateSensor` attrs,
  `aggregation.py:502` zone lookup all pick up the new value after ONE
  reload cycle. Verify CONF_ZONE-in-`_ROOM_SUPPRESS_KEYS` interaction:
  after the combined write, does the apply-in-place branch reach both
  data and options coherently? Confirm STUCK-SENSOR-1's future
  exclusion path is unaffected.
- **Review C — Test authority + falsifier drills.** For D3a: independently
  author the invariant assertion (do NOT reuse the builder's test body).
  Run the documented falsifier drills (revert D1 site 1, revert D1 site
  3, revert D2 idempotency check) and confirm each reddens exactly the
  test named for it; if any stays green, C flags as DO-NOT-SHIP (hollow
  anchor). For D3b: mutate the `_stuck_signal_nm` call site and confirm
  the runtime-desync test reddens. Verify the reload-await barrier
  (M2) is a real barrier and not a bare `async_block_till_done` (which
  races reloads).

Live validation (Review D, post-restart): pick a real test room; rename
via options flow live; verify (a) `entry.data`, `entry.options`, and
`entry.title` agree in `.storage/core.config_entries`; (b) rename
propagates to substrate/tracker/aggregation within one reload;
(c) `binary_sensor.<room>_occupied` attrs show non-empty
`substrate_kinds`/`last_edge_entity` after next real motion (audit's
tracker-un-starved proof); (d) reassign the same test room's CONF_ZONE
via options; confirm `aggregation.py:502`-driven zone sensors pick up
the new assignment on the next tick (NO reload expected because CONF_ZONE
is suppressed — but the data twin is now current, so the read is
correct); (e) NM log shows zero `room_name_desync` notes; flip a
`.storage` name manually and confirm the NM note appears at next
restart. Fill README's `Validated <date>` table.

---

## 9. Sequencing / interaction notes

- **STUCK-SENSOR-1:** ship this BEFORE STUCK-SENSOR-1 so its test suite
  can rely on the invariant. Naturally satisfied — STUCK-SENSOR-1 is
  blocked on SENSOR-CAPABILITY-1 fixtures.
- **The 2026-08-13 hand-sync** means the live instance is not currently
  bleeding. No urgency-driven shortcut: full Tier 2-DB, all three
  framings, live validation, README write-back.
- **`_ROOM_SUPPRESS_KEYS` interaction (CONF_ZONE):** the write-through
  is deliberately designed to work WITH the suppression — both twin
  fields written in the same call, so whether the listener reloads or
  applies-in-place, both readers see the new value.
- **No VERSION bump** (M3): D2 is a setup-time idempotent pass, not
  `async_migrate_entry`. Reviewer-A direction verbatim.

---

## 10. Files touched (planner enumeration; builder verifies)

- `custom_components/universal_room_automation/config_flow.py` (D1 —
  three rename save sites at 9112-9128, 7938, 7943-7955; ~30 LoC).
- `custom_components/universal_room_automation/__init__.py` (D2 helper
  + insertion at four setup sites 3655/3805/4055/4168 above the
  `add_update_listener` line; D3b runtime desync NM emit; ~60 LoC).
- `tests/config_flow/test_room_rename_writethrough.py` (D1 tests — new).
- `tests/test_setup_room_name_migration.py` (D2 tests — new; includes
  the four-site ordering test).
- `tests/presence/test_rename_invariant.py` (D3 tests — new; drives real
  options flow + real presence coordinator + real aggregation reader,
  with the M2 reload-await barrier).
- `docs/readmes/README_v<next>.md` (pre-deploy; live-validation table
  filled post-restart).
