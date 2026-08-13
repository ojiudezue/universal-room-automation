# PLANNING — Room/Zone rename write-through (ROOM-NAME-DESYNC-1)

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

> **I1 — For every loaded URA config entry, every name-consuming code path
> resolves the SAME room/zone name, and an options-flow rename is observed by
> every path within a single reload cycle.**

Concretely, for every ROOM entry `e`:

- `e.data[CONF_ROOM_NAME] == e.options.get(CONF_ROOM_NAME, e.data[CONF_ROOM_NAME])`
  immediately after `async_update_entry` returns from the options-flow rename
  handler, and identically after a boot migration on entries that predate the
  fix. Same clause for ZONE entries with `CONF_ZONE_NAME`.
- After a rename save, `ZonePresenceTracker.room_names`,
  `OccupancySubstrate` bucket keys, `_room_to_zone`, `_fan_entity_to_room`,
  and `PresenceHouseStateSensor.extra_state_attributes[<zone>].fan_on_rooms`
  all agree on the new name (proven by driving a rename in-suite against real
  code and asserting substrate edges arrive at the tracker).

**How to falsify:** produce a legal-config code path that reads a name field
from `entry.data` or from a merged `{**data, **options}` and yields a
different string than another consumer of the same entry after a rename.
D's job is to find that path — including in pre-existing modules the diff
does not touch.

---

## 2. Institutional context verified

### Greps run + counts

- `rg 'CONF_ROOM_NAME|CONF_ZONE_NAME' custom_components/universal_room_automation`
  → **125 occurrences across 19 modules**; ~96 read sites outside
  `config_flow.py`/`const.py`.
- `rg 'room_name' custom_components/universal_room_automation` → **1173
  occurrences across 36 modules** (superset — includes local variables and
  log fields; the CONF grep above is the authoritative call-site count).
- `rg '\{\*\*.*data.*\*\*.*options|\{\*\*.*options.*\*\*.*data'
  custom_components/universal_room_automation` → **50+ merged-dict
  constructions** across `config_flow.py`, `select.py`, `switch.py`,
  `button.py`, `sensor.py`, `binary_sensor.py`, `coordinator.py`,
  domain coordinators. Options-first merge is the dominant idiom.
- `rg 'entry\.(data|options)\.(get|\[)[^)]*(ROOM_NAME|room_name|ZONE_NAME|zone_name)'`
  → the three conventions the audit named:
  - **data-first / data-only** (the bug): `presence.py:2868` tracker keying;
    `button.py:157,179,338,363,505`; `binary_sensor.py:228,296,321`;
    `config_flow.py:937,1090,2824,7961,8717` (label + zone filters).
  - **options-first (merged)** (the substrate convention):
    `occupancy_substrate.py:197-202`; `select.py:69,345`;
    ~50 `{**data, **options}` sites in `config_flow.py`.
  - **data-OR-options explicit fallback** (rare / third convention):
    `config_flow.py:7818-7822` for `CONF_ZONE_NAME` (data-first with
    options fallback) — a fourth mismatch shape hiding in the zone rename
    step itself.

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
  suppression allowlist (`OPTIONS_RELOAD_SUPPRESS_KEYS`) is a discharge
  surface the write-through must be checked against (rename must still
  trigger the reload — see D1).
- `feedback_context_wide_scoping` — the name key threads rooms + zones +
  house + HVAC; enumeration below covers all four tiers.

### Design docs read

- Coordinator design docs are silent on name resolution (the bug is
  cross-coordinator by construction — no single doc owns it).

### Code locations surveyed end-to-end during scoping

- `custom_components/universal_room_automation/config_flow.py:9108-9165`
  (room `async_step_basic_setup` — the actual rename entry point;
  options-flow `async_create_entry(data=merged)` writes to `entry.options`,
  never touches `entry.data`).
- `config_flow.py:7797-7955` (zone `async_step_zone_rooms` — legacy zone
  entries: writes options at 7938; ZM-owned zones renamed via
  `_auto_mirror_to_siblings` at 7916 — different path).
- `config_flow.py:2160-2170` (initial room create — seeds `entry.data`
  with `CONF_ROOM_NAME`, `CONF_ROOM_TYPE`, `CONF_AREA_ID`).
- `domain_coordinators/occupancy_substrate.py:190-220` (merged read; bucket
  keyed by merged name).
- `domain_coordinators/presence.py:2864-2876` (tracker resolves
  `entry.data.get(CONF_ROOM_NAME)` — the read that starves).
- `__init__.py` (grep of `async_migrate_entry` returns 0 — the integration
  has no migration harness today; boot migration in D2 must add the shape
  or run as an idempotent pass in `async_setup_entry`).

---

## 3. ROOT SHAPE — accessor migration vs write-through: adjudication

**RECOMMENDATION: WRITE-THROUGH (D1) + BOOT MIGRATION (D2) + INVARIANT
TEST (D3). Do NOT undertake the accessor migration in this cycle.**

Grounds:

| axis | accessor migration | write-through |
|---|---|---|
| touch surface | ~96 read sites across 17 modules; ≥3 conventions to unify (data-first, merged options-first, data-OR-options fallback); every convention flipped is a regression risk against un-tested paths | 2 write sites (room `basic_setup`, legacy zone `zone_rooms`) + 1 boot migration + 1 invariant test |
| failure mode | one missed site keeps the bug alive AND now the "right" answer is convention-dependent, making the next diverging site harder to detect | one missed WRITE site keeps `data` stale for that path, but every reader still converges (options == data by construction) — the class is killed at the producer, not the N consumers |
| reload suppression | orthogonal | must verify `CONF_ROOM_NAME` / `CONF_ZONE_NAME` are **not** in `OPTIONS_RELOAD_SUPPRESS_KEYS` (checked: they are not — grep in §2). A rename SHOULD trigger reload; write-through preserves that. |
| operator model | "every reader must know the merge rule" — leaky | "the two fields are always equal; readers are byte-identical to today" — internal |
| test authority | must retrofit tests to prove every reader picked up the accessor | one integration test drives the real options flow and asserts data followed (§D3) |

**Bug Class #53 shape recognition:** the accessor migration is exactly the
"computed-but-not-consumed" trap — a canonical helper that a subset of
call sites happen to still bypass. Write-through inverts the shape: the
producer guarantees equality, so consumer conventions become irrelevant.

**Non-adopted parked idea (record, don't build):** a single
`get_room_name(entry)` / `get_zone_name(entry)` helper module remains a
legitimate hygiene refactor to reduce the three read conventions to one.
Trigger to revisit: any future field where a data/options desync is not
fixable at the producer (e.g., an operator-editable list where the write
is external), OR if a post-fix audit finds a new consumer relying on a
merged-only value that ISN'T under a write-through. Until then, the
write-through discharges the operator's ask ("rename and be correct")
with the smaller blast radius.

**Operator decisions needed (aim zero):** none. The audit's own §Q5 lists
write-through as the smaller kill. Recommendation is unanimous with prior
art. Proceeding without a checkpoint.

---

## 4. Independent consumer enumeration (re-run for reviewers)

Every path that reads a room/zone name from a config entry, classified by
convention. Reviewers MUST re-run the greps in §2 to confirm nothing was
missed; the list below is the current planner's enumeration, not gospel.

### 4.1 Room-name readers

| convention | site | consumed for |
|---|---|---|
| data-only | `presence.py:2868` (`ZonePresenceTracker.room_names`) | zone-tier occupancy, away path, WAKING gate, fan machinery |
| data-only | `button.py:157,179,338,363,505` | button entity labels/logs |
| data-only | `binary_sensor.py:228,296,321` | binary-sensor labels |
| data-only | `config_flow.py:937,1263,7961,9753` | flow dropdown labels |
| data-only | `config_flow.py:8717` | zone-membership filter |
| merged (options-first) | `occupancy_substrate.py:197-202` (bucket key + dispatch) | substrate → tracker edges |
| merged | `select.py:69,345`; `switch.py` numerous; ~50 `{**data, **options}` sites in `config_flow.py` | entity labels, per-room reads |
| merged | `presence.py:3000-3023` (`_discover_room_sensors`); `presence.py:~3240-3285` (`_discover_room_fans`) | room register / fan wiring |
| coordinator | `coordinator.py:853, 970, 1020, 1372` | substrate bucket queries, diagnostics |

### 4.2 Zone-name readers (legacy zone entries — ENTRY_TYPE_ZONE)

| convention | site |
|---|---|
| data-only | `config_flow.py:1090, 2824, 8717` |
| data-OR-options explicit | `config_flow.py:7818-7822` |
| merged | most other zone-entry consumers |

### 4.3 Fields NOT in scope (record, do not touch)

- ZM-owned zones (`zones` dict inside the Zone Manager entry): renamed via
  `_auto_mirror_to_siblings` (config_flow.py:7916) — different mechanism,
  and the audit did not implicate it. Leave as-is.
- `CONF_ROOM_TYPE`, `CONF_AREA_ID`, `CONF_ZONE` (per-room zone
  assignment): seeded in `entry.data` at create, editable via options,
  same drift shape in principle — but no live reader join-keys against
  them across coordinators the way `CONF_ROOM_NAME` does. Out of scope for
  this cycle. Follow-up: audit for the same drift after D3's invariant
  test framework lands (§7 non-goals).

---

## 5. Deliverables

### D1 — Options-flow rename writes through to `entry.data` atomically

**Change:** at the two rename save sites, before/within the same
`async_update_entry` call, patch `entry.data` when the name field is
present in the payload and differs from `entry.data`.

**Sites:**

1. `config_flow.py:9112-9128` (`OptionsFlow.async_step_basic_setup` — the
   room rename). Today: `return self.async_create_entry(title="",
   data=merged)` (which writes options only). Change: if `CONF_ROOM_NAME`
   in `user_input` and differs from `self._config_entry.data.get(
   CONF_ROOM_NAME)`, call `self.hass.config_entries.async_update_entry(
   self._config_entry, data={**self._config_entry.data, CONF_ROOM_NAME:
   user_input[CONF_ROOM_NAME]})` **before** the `async_create_entry`
   (options save). One reload will fire — verified against
   `OPTIONS_RELOAD_SUPPRESS_KEYS`: `CONF_ROOM_NAME` is not in the
   allowlist, so a normal reload cycle is expected and correct here.
2. `config_flow.py:7938` (legacy zone rename via `async_update_entry`).
   Add `data={**zone_entry.data, CONF_ZONE_NAME: zone_name}` to the
   same call.

**Class coverage:** the two name fields (`CONF_ROOM_NAME`,
`CONF_ZONE_NAME`) are the only fields the enumeration in §4.3 confirms
have a live cross-coordinator join-key shape. Other data/options twins
are recorded as follow-up, not folded in.

**Acceptance criteria:**

- **Verify:** rename a test room via the real options flow in-suite;
  `entry.data[CONF_ROOM_NAME] == entry.options[CONF_ROOM_NAME] == new
  name` when the coroutine returns.
- **Verify:** exactly one reload dispatch per save (no double-reload
  regression from the extra `async_update_entry`). Assert via a spy on
  the update-listener.
- **Test:** `tests/config_flow/test_room_rename_writethrough.py::
  test_room_rename_updates_data_and_options`,
  `::test_zone_rename_updates_data_and_options`,
  `::test_room_rename_no_double_reload`.

### D2 — One-shot boot migration syncing existing desyncs

**Change:** on `async_setup_entry` (or via `async_migrate_entry` if a
version bump is preferred — the integration has none today; simpler to
run as an idempotent pass at setup), for every entry with
`CONF_ENTRY_TYPE in {ENTRY_TYPE_ROOM, ENTRY_TYPE_ZONE}`, if the options
name is set and differs from the data name, call
`async_update_entry(entry, data={**entry.data, <name_key>: options[
<name_key>]})`. Log at INFO for each sync applied.

**Idempotence:** the check is `options[name] != data[name]`, so entries
already in agreement (including the three hand-synced 2026-08-13 rooms)
are no-ops.

**Coverage:** the class enumerated in D1 (rooms + legacy zones). ZM-owned
zones (§4.3) are out of scope; the audit did not implicate them.

**Acceptance criteria:**

- **Verify:** on a fixture with a desynced room, one INFO log line + data
  updated; on a fixture with agreement, zero updates + zero log lines.
- **Verify:** run the migration twice on the same fixture — second run
  is a full no-op (zero `async_update_entry` calls).
- **Test:** `tests/test_setup_room_name_migration.py::
  test_migration_syncs_desynced_room`, `::test_migration_noop_when_in_sync`,
  `::test_migration_covers_legacy_zone_entries`,
  `::test_migration_idempotent_second_run`.
- **Live:** after deploy, grep HA log for the migration INFO lines. The
  three hand-synced rooms produce ZERO lines (already in sync). Zero
  desyncs surfaced = expected on the live instance (hand-sync already
  applied); the test authority for coverage lives in fixtures.

### D3 — Invariant test + runtime desync surfacing

**Two parts:**

**D3a — In-suite invariant test.** Drive the real options-flow rename
against a real config-entry fixture (NOT a monkeypatched shortcut —
per `feedback_hollow_test_anchors`), assert:

- `entry.data[CONF_ROOM_NAME] == entry.options[CONF_ROOM_NAME]` after save.
- After the room reload cycle, a `SIGNAL_SUBSTRATE_KIND_CHANGED` dispatch
  for the renamed room reaches `_on_substrate_kind_changed` and is NOT
  dropped as "unknown room" (the exact failure mode from
  presence.py:3082-3090 the audit named). Assert via a spy on
  `tracker.update_room_occupancy`.

The **falsifier drill:** revert D1 (delete the `data=` payload from the
D1 `async_update_entry`); the D3a test MUST turn red. If it stays green,
the anchor is hollow (Bug Class #53 shape again) and must be strengthened
before ship.

**D3b — Runtime desync diagnostic.** Cheap boot-time check inside
`async_setup_entry` (post-D2 migration): iterate ROOM/ZONE entries; if
any still show `options[name] != data[name]` (only possible via a manual
`.storage` edit after the migration ran), fire an NM note via the
existing `_stuck_signal_nm` shape (kind = `room_name_desync`, per-day
dedup) naming the entry_id + both strings. This surfaces future manual
edits without a code change ever needing to look at logs.

**Acceptance criteria:**

- **Test:** `tests/presence/test_rename_invariant.py::
  test_rename_reaches_tracker` (drives real flow + real presence
  coordinator; asserts substrate edge lands).
- **Test:** `tests/presence/test_rename_invariant.py::
  test_falsifier_drill_reverting_writethrough_reddens_this_test` —
  a documented mutation the reviewer can re-run (see §8 Review C).
- **Sensor:** none new; the runtime check emits an NM note, which the
  existing NM surface already renders (no new dashboard field).
- **Live:** on a running instance with all entries in sync, ZERO
  `room_name_desync` NM notes fire post-boot. To positively demonstrate
  the diagnostic works, manually flip one entry's `.storage` after
  restart and confirm the NM note appears within the boot check's window
  (documented in the README live-validation section).

---

## 6. Knob ladder

**Zero knobs.** Every number/threshold/behavior in this cycle is invariant
(the two fields must be equal — no operator-tunable slack). The one
choice — whether to also add a `get_room_name` accessor — is a code
refactor decision, not a runtime knob, and is parked per §3.

Recording per `Numbers Get Knobs`: nothing to record.

---

## 7. Non-goals

- **Accessor migration** across the ~96 read sites (§3 recommendation).
- **CONF_ROOM_TYPE / CONF_AREA_ID / CONF_ZONE data-options drift audit**
  — recorded as follow-up; not folded in to avoid scope creep.
- **ZM-owned zones (`zones` dict) rename hardening** — different code
  path (`_auto_mirror_to_siblings`); not implicated by the audit.
- **Extending the runtime diagnostic to a dashboard sensor** — NM note
  is sufficient for the manual-edit-after-migration case, which is the
  only residual after D1+D2.
- **Rewiring `presence.py:2868` to merged options-first as a
  defense-in-depth belt-and-suspenders** — deliberately declined; the
  audit's Q5 rung-2 accessor idea is what §3 already parked. Doing it
  half-way (one file) creates a convention split without killing the
  class.

---

## 8. Three review framings (Tier 2-DB)

Run in parallel; do NOT share framings — that is the point of the tier.

- **Review A — Data integrity + write-path correctness.** D1's
  `async_update_entry(data=...)` semantics: does it fire an extra
  update-listener? Does it race with the following `async_create_entry`
  options save? Are options and data guaranteed to converge on the same
  string (no title/whitespace normalization asymmetry)? Restart survival:
  after D2 migration + restart, does the post-restart setup path re-run
  D2 harmlessly? Enumerate the fields that `entry.data` gets seeded with
  at initial create (config_flow.py:2160-2170) and confirm none of them
  are silently reverted by the write-through.
- **Review B — Migration correctness + cross-coordinator signal chain.**
  For each of the currently-hand-synced 3 rooms, trace the substrate →
  tracker signal path end to end BEFORE and AFTER D1+D2 apply against a
  hypothetically re-desynced fixture; prove the tracker `room_names`,
  `_room_to_zone`, `_fan_entity_to_room`, and
  `PresenceHouseStateSensor` attrs all pick up the new name after ONE
  reload cycle. Verify OPTIONS_RELOAD_SUPPRESS_KEYS still triggers reload
  on rename (regression protection). Confirm STUCK-SENSOR-1's future
  exclusion path (which will key rooms via the substrate) is unaffected
  by this cycle's shape.
- **Review C — Test authority + falsifier drills.** For D3a: independently
  author the invariant assertion (do NOT reuse the builder's test body).
  Run the documented falsifier drill (revert D1) and confirm the test
  actually reddens; if it stays green, C flags as DO-NOT-SHIP (hollow
  anchor). For D2: mutate the migration's `!=` check to always return
  False (no-op) and confirm the D2 idempotency test reddens. For D3b:
  mutate the `_stuck_signal_nm` call site and confirm the runtime-desync
  test reddens.

Live validation (Review D, post-restart): follow the standard Tier 2-DB
Review D shape — pick a real test room, rename via the options flow live,
verify (a) `entry.data` and `entry.options` agree in `.storage/
core.config_entries`, (b) `sensor.zone_<zone>_rooms_occupied` picks up the
new name within one reload, (c) `binary_sensor.<room>_occupied` attrs
show non-empty `substrate_kinds` / `last_edge_entity` after next real
motion (the audit's proof that the tracker is no longer starved), (d) NM
log shows zero `room_name_desync` notes, then flip a `.storage` name
manually and confirm the NM note appears at next restart. Fill the
README's `Validated <date>` results table with the observed evidence.

---

## 9. Sequencing / interaction notes

- **STUCK-SENSOR-1 (planned):** its corroboration-gated exclusion keys
  rooms via the substrate, which after this cycle will resolve names
  correctly by construction. Ship this BEFORE STUCK-SENSOR-1 so its
  test suite can rely on the invariant. STUCK-SENSOR-1 is separately
  blocked on SENSOR-CAPABILITY-1 fixture supplements, so the ordering
  is naturally satisfied.
- **The 2026-08-13 hand-sync** of Jaya Bedroom / Upstairs Guestroom /
  Down Guest Bathroom means the live instance is currently NOT bleeding.
  This cycle is preventive against future renames + a clean-up for any
  latent .storage-edit case. No urgency-driven shortcut is authorized:
  full Tier 2-DB, all three framings, live validation, README write-back.
- **`async_migrate_entry` vs setup-time pass:** the integration has no
  `async_migrate_entry` today (grep of `__init__.py` returned zero
  matches). D2 is scoped as an idempotent pass at `async_setup_entry`
  (or a small helper called from it) rather than introducing a version
  bump — smaller blast radius and lets a fresh boot re-verify. Reviewer
  A may push back and prefer the migration harness; that is an
  A-adjudicable style call, not a correctness call.

---

## 10. Files touched (planner enumeration; builder verifies)

- `custom_components/universal_room_automation/config_flow.py` (D1 — two
  rename save sites at 9112-9128 and 7938; ~20 LoC).
- `custom_components/universal_room_automation/__init__.py` (D2 — boot
  migration pass + D3b runtime desync NM emit; ~40 LoC).
- `tests/config_flow/test_room_rename_writethrough.py` (D1 tests — new).
- `tests/test_setup_room_name_migration.py` (D2 tests — new).
- `tests/presence/test_rename_invariant.py` (D3 tests — new; drives real
  options flow + real presence coordinator).
- `docs/readmes/README_v<next>.md` (pre-deploy; live-validation table
  filled post-restart per CLAUDE.md README write-back requirement).
