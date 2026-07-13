# PLANNING — Zone Delete Prune Name-Collision Hotfix

**Cycle:** Zone-delete prune guard + migration mint guard (+ optional dispatch snapshot)
**Branch base:** `develop`
**Tier classification:** **Tier 2** (two framing-disjoint reviews + live validation)
**Predecessor:** v5.14.0 (`PLANNING_zone_delete.md`, `README_v5.14.0.md` L3, `docs/reviews/code-review/v5.14.0_labels_and_zone_delete.md` §B)

---

## Executive summary

v5.14.0 shipped a Zone Delete flow. Deleting the **husk HOUSE zone** `"Entertainment + Master Suite"` on 2026-07-12 correctly purged its config entry, DB rows, and entity/device registry — but the `SIGNAL_ZM_ZONES_UPDATED` prune handler in `hvac.py` **also popped the LIVE merged HVAC zone `zone_1`** whose displayed `zone_name` is the same compound string (built by `hvac_zones.py:297-301` when two ZM house zones share one thermostat). HVAC logic for `zone_1` (Study B / Master Suite thermostat `climate.thermostat_bryant_wifi_studyb_zone_1`) went inert 14:29 → 19:42 until a bare restart re-derived it via `async_discover_zones` (`hvac.py:492`, discovery-only-at-setup). The persisted `_zone_state_store` was also rewritten without `zone_1`, but that is harmless since restore does not create zones.

Root cause is architectural conflation: **house zones (ZM config entries) and HVAC merged zones (thermostat-keyed `zone_N`) are separate tiers by design.** One HVAC zone legitimately maps to N house zones (`hvac_zones.py:297-301`). The v5.14.0 name-fallback prune (`hvac.py:1720-1729`) treats them as the same namespace.

Recovery is fully automatic on restart; no repair machinery is required. This cycle is **prevention-only**: (D1) prune-guard so the HVAC handler cannot pop a merged zone whose thermostat is still claimed by any surviving house zone; (D2) migration mint-guard so the boot migration at `__init__.py:133-148` cannot mint a phantom compound-name house zone (which is how the 2026-07-12 husk was born); (D3, optional) carry the CONFIRM-time `zone_id` snapshot into the dispatch payload to eliminate a resolve-drift window between confirm and dispatch.

---

## Institutional context verified

### Anchors re-verified 2026-07-12

- **Prune handler + name fallback** — `custom_components/universal_room_automation/domain_coordinators/hvac.py:1680-1747`. Fallback loop `:1720-1729` matches by exact `zone_name` OR by `deleted_name in [parts of "A + B"]`. Persisted rewrite at `:1748+` uses zone_id-only (already safe).
- **Discovery is setup-only** — `hvac.py:492` (`await self._zone_manager.async_discover_zones()`). Zones removed from `ZoneManager._zones` after setup are not re-derived until the next `async_setup`. This is why the outage lasted until restart.
- **Compound name construction** — `domain_coordinators/hvac_zones.py:297-301`: `existing.zone_name = f"{existing.zone_name} + {zm_zone_name}"` when two ZM zones share `CONF_ZONE_THERMOSTAT`. Compound-name is legitimate; not a bug.
- **Boot mint migration** — `__init__.py:95-159`. Scans room entries for CONF_ZONE strings not covered by an existing ENTRY_TYPE_ZONE and calls `async_init(...)` to create one. No guard against compound names, dead zone names, or names that collide with a live HVAC merged display name.
- **Dispatch site** — `config_flow.py:7634-7645`. Calls `_resolve_zone_id_for_delete(zone_name)` AFTER `_delete_zone_locked` returns. Confirm-time zone_id (captured in `summary["zone_id"]` at `:7669`) is NOT threaded into the dispatch payload.
- **Resolve helper** — `config_flow.py:7333-7372`. For a husk (no thermostat, `has_thermostat=False`) returns `(None, "husk")`. The `" + "` split match at `:7365-7366` will resolve the husk NAME to the live merged HVAC `zone_1` if the husk is queried with `has_thermostat=True` — this is the same aliasing the prune handler exhibits, on the config-flow side. Read for D3 impact.

### Prior planning + review docs consulted

- `docs/planning/PLANNING_zone_delete.md` — v5.14.0 build spec.
- `docs/reviews/code-review/v5.14.0_labels_and_zone_delete.md` §B — three-reviewer Tier 2-DB findings including R4/B-HIGH-1 (persisted-store rewrite) that introduced the prune handler. The name-collision case was NOT modelled by any of A/B/C reviewers.
- `docs/readmes/README_v5.14.0.md` L3 — Zone Delete "Validated 2026-07-11" entry (deleted a different, non-husk zone; the collision case did not fire during that validation).

### Memory bodies pulled

- `project_session_pickup_2026_07_11.md` — records the husk-zone delete as an open UI item; today (07-12) it exercised the collision.

### Proposed additions — REUSED vs NEW

| Item | Status | Cite |
|---|---|---|
| Prune handler guard predicate | **REUSED surface** — extend `_handle_zm_zones_updated` (`hvac.py:1680`); no new signal, no new sensor. | `hvac.py:1720-1729` |
| Surviving-house-zone lookup | **REUSED** — iterate ZoneManager config surface via same `_find_zone_manager_entry` pattern the config-flow already uses (`config_flow.py:7394`). | `config_flow.py:7394-7411` |
| Migration mint guard | **REUSED** — extend `_migrate_zone_names_to_entries` loop body (`__init__.py:133-148`); no new function, no new CONF. | `__init__.py:95-159` |
| Dispatch snapshot field | **REUSED** payload key `deleted_zone_id`; value source changes from post-mutation re-resolve to confirm-time `summary["zone_id"]`. No new payload key. | `config_flow.py:7637-7641`, `:7669` |
| Test file | **NEW** `quality/tests/test_zone_delete_prune_guard.py` — no equivalent exists (grep: no `test_zone_delete*` under `quality/tests/`). |

### Bug classes at play (from `docs/QUALITY_CONTEXT.md`)

- Cross-tier namespace collision (name aliasing between house-zone tier and HVAC-merge tier).
- Resolve-drift between confirm-time and dispatch-time reads (candidate new class if D3 is taken).
- Boot migration minting phantom entries from stale config strings (candidate variant of Bug Class #47 canonical resolution).

---

## Tier classification — why Tier 2, not Tier 1

Tier 1 (single review) is tempting because each deliverable is a small, localized guard. Reject:

1. **The predecessor cycle was Tier 2-DB and still shipped this collision.** Three framing-disjoint reviewers all missed the cross-tier aliasing because none was framed on "the prune subscriber's namespace assumption." A single reviewer here is likely to repeat that blind spot.
2. **Blast radius is HVAC-wide.** A wrong guard predicate either (a) fails to prune a real deleted zone (persistence bug returns) or (b) prunes a live merged HVAC zone (today's incident recurs). Both are silent until a thermostat stops actuating.
3. **D2 touches a boot path** that runs on every startup for every install. A wrong predicate here can silently drop legitimate migration mints on other users' configs.

Tier 2 with **explicitly disjoint framings**:

- **Reviewer A — correctness + edge cases of the guard predicates.** Compound with 3+ parts (`"A + B + C"`), thermostat entity casing, husk with a thermostat CONF that no longer resolves, ZM entry absent (legacy), Unicode/whitespace normalization of names.
- **Reviewer B — cross-tier + lifecycle.** House-zone vs HVAC-zone tier separation preserved end-to-end; discovery-only-at-setup implication; restart resilience (does the persisted store survive a guarded prune?); does the migration guard log clearly enough that an operator can find the phantom?; does D3's snapshot vs D1's guard double-protect or does one make the other redundant?

Elevation to Tier 2-DB is not warranted: no DB DAO changes, no schema migration, no payload-shape change to a persisted record (D3 changes an in-memory dispatch payload only, and only the value source, not the key set).

---

## Falsifiable invariant

**Invariant I:** *For any dispatched `SIGNAL_ZM_ZONES_UPDATED` with `deleted_zone_name=N`, the HVAC prune handler MUST NOT remove a `ZoneManager` zone `Z` whose `CONF_ZONE_THERMOSTAT` matches the `CONF_ZONE_THERMOSTAT` of ANY surviving ENTRY_TYPE_ZONE (or ZM-embedded zone config) other than the one being deleted.*

Reviewer B's job includes stating this invariant back in falsifiable form and proposing a legal-config repro that would break it if the guard were absent (the 2026-07-12 husk delete IS that repro; use it as the anchor test case).

---

## D1 — Prune-handler guard (HVAC-side)

### What to build

Extend `_handle_zm_zones_updated` at `custom_components/universal_room_automation/domain_coordinators/hvac.py:1680`:

1. When entering the **zone_id-unknown / name-fallback path** (`:1720-1729`), before popping any candidate `zid`, resolve the candidate's `CONF_ZONE_THERMOSTAT` via `ZoneManager` zone state (`zs.thermostat` / equivalent — verify field name during build) OR via a lookup back through the ZM config entry.
2. Gather the set of surviving house-zone thermostat entities: iterate `hass.config_entries.async_entries(DOMAIN)` for `ENTRY_TYPE_ZONE` entries (**excluding** the just-deleted one, which is already removed by the time dispatch fires — verify) and, if present, the surviving `zones` dict inside the ZM options entry.
3. **Skip the pop** if the candidate zone's thermostat is claimed by any surviving house zone. Log at WARNING: `"HVAC prune guard: skipping merged zone_id=%s (name=%r) because thermostat=%s is still claimed by surviving house zone(s)=%s"`. Do NOT prune the persisted store either (D1 must also gate the `_rewrite_zone_state_store` rewrite for that `zone_id`).
4. **zone_id-known path** (`:1716-1718`) — when `deleted_id` was carried in the payload, the guard is still applied (belt-and-suspenders): if the payload's `deleted_id` corresponds to a merged HVAC zone whose thermostat is claimed by surviving house zones, skip and WARN. This closes the drift path where a bad snapshot could arrive.

### Acceptance criteria

- **Verify:** Deleting a husk house zone whose name equals a live HVAC compound name emits the WARNING log, leaves `ZoneManager._zones` unchanged, and leaves `_zone_state_store` intact.
- **Verify:** Deleting a genuine, non-compound house zone whose name matches a real solo HVAC zone (the ONLY house zone claiming that thermostat) still prunes normally (guard must not over-fire).
- **Test:** `test_zone_delete_prune_guard.py::test_husk_delete_does_not_prune_shared_merged_zone` + `::test_solo_delete_still_prunes`.
- **Test:** `::test_guard_applies_to_zone_id_known_path` (payload carries a wrong `deleted_zone_id` pointing at a shared merged zone — guard blocks).
- **Live:** Operator creates a disposable house zone "TestGhost" (no thermostat) plus a real house zone whose thermostat is shared into a merged HVAC display name that HAPPENS to contain "TestGhost" (or simulate by temporarily renaming). Delete "TestGhost". Confirm `sensor.ura_hvac_coordinator_zone_1_*` remains live (attributes update within 60s) and log shows the guard WARNING.

---

## D2 — Migration mint-guard

### What to build

Extend `_migrate_zone_names_to_entries` at `custom_components/universal_room_automation/__init__.py:133-148`:

1. Before the `async_init` call, compute the set of **live HVAC merged zone display names** from `hass.data[DOMAIN]["hvac_coordinator"].zone_manager.zones` if the HVAC coordinator is already up. If it is not up yet (boot-order dependent), fall back to computing the set of compound-name candidates from ZM config: any string of the form `A + B` where both `A` and `B` are existing `existing_zone_names` (case-insensitive).
2. **Skip minting** if the room-derived `zone_name` matches either set. Log at WARNING: `"Zone migration: refusing to mint phantom zone %r (matches live HVAC merged display name / compound of existing zones=[%s, %s]); leaving room CONF_ZONE untouched — operator must clean up the room's zone assignment"`.
3. Do NOT modify the room entry's `CONF_ZONE` string; that is a separate cleanup surface (call out in the log so operator knows where to look).

### Guard-predicate analysis (for reviewers)

Two candidate predicates, each with a failure mode:

- **P1 (conservative):** skip if `zone_name == any live HVAC merged display name`. Fails if HVAC coordinator has not finished discovery when migration runs — false negative, husk mints anyway.
- **P2 (structural):** skip if `" + " in zone_name` AND every part (split on `" + "`, stripped) matches an existing ZONE entry name (case-insensitive). Fails if two legitimate house zones legitimately want a shared compound name — but operator cannot create that today because the config flow does not let you type `" + "` as a zone-name separator (verify during build; if false, add a validator).

**Recommendation:** Apply **P1 OR P2** (union). P1 catches the exact live-collision case; P2 catches the boot-order edge case. Union is safe because both predicates only refuse to mint — worst case, operator sees a WARNING and cleans up the room CONF_ZONE manually.

### Acceptance criteria

- **Verify:** On a fresh boot where a room carries a stale compound CONF_ZONE (e.g. `"Entertainment + Master Suite"`) and both `"Entertainment"` and `"Master Suite"` exist as ZONE entries, migration logs the WARNING and does NOT create a zone config entry.
- **Verify:** On a fresh boot where a room carries a legitimately-new zone name (single word, not a compound of existing zones), migration mints as before.
- **Test:** `test_zone_migration_mint_guard.py::test_compound_of_existing_zones_skipped` + `::test_novel_name_still_minted` + `::test_live_hvac_display_name_skipped_when_coordinator_up`.
- **Live:** After deploy, verify HA startup logs contain no new "Migrating zone" line for the previously-husked compound name; if any room still carries the stale CONF_ZONE, the WARNING appears once.

---

## D3 (OPTIONAL) — Dispatch snapshot consistency

### Problem

`config_flow.py:7637` re-runs `_resolve_zone_id_for_delete(zone_name)` AFTER `_delete_zone_locked` has already mutated config and reloaded. Between confirm (`_summarize_zone_deletion` at `:7669` captured `summary["zone_id"]`) and dispatch, the ZM options entry has been rewritten and reloaded — the resolve function's view of the world can differ:

- **Confirm-time:** husk → `(None, "husk")`.
- **Dispatch-time:** after reload, the coordinator may still be up but the deleted zone entry gone; resolve returns `(None, "husk")` again — matching. But under a shared-thermostat / compound case, if config rewrite altered the surviving zones' compound naming, the split-match at `config_flow.py:7365-7366` could map the deleted `zone_name` to a live `zone_id` OR fail to map an id it captured at confirm time.

Threading `summary["zone_id"]` into the dispatch payload eliminates the second read entirely.

### What to build

- In `_delete_zone` (the caller at `:7583+` — verify signature during build), pass the `summary` dict through to the caller of `_delete_zone_locked` so `summary["zone_id"]` survives lock release, then use that value at `:7637-7641` instead of calling `_resolve_zone_id_for_delete` again.
- Keep the guard from D1 as the load-bearing correctness gate; D3 is defense-in-depth.

### Acceptance criteria

- **Verify:** Dispatch payload's `deleted_zone_id` equals `summary["zone_id"]` for every code path.
- **Verify:** The second `_resolve_zone_id_for_delete` call at `:7637` is removed (grep proves it).
- **Test:** `test_zone_delete_dispatch_snapshot.py::test_dispatch_payload_carries_confirm_time_zone_id` — inject a shim that flips ZM state between confirm and dispatch; assert dispatched `deleted_zone_id` matches confirm-time value.
- **Live:** Re-run the disposable-zone deletion; log line `"Zone delete signal dispatched: zone=%r zone_id=%r"` matches the confirm-time value from the prior `"Zone delete starting:"` log.

### Recommendation

**Take D3.** It is small, localized to two lines in `config_flow.py`, closes a real drift window, and gives Reviewer B a cleaner story (single source of truth for `zone_id`).

---

## Files touched

| File | Deliverable | Nature |
|---|---|---|
| `custom_components/universal_room_automation/domain_coordinators/hvac.py` | D1 | Extend `_handle_zm_zones_updated` (`:1680-1747` + persisted-store rewrite) |
| `custom_components/universal_room_automation/__init__.py` | D2 | Extend `_migrate_zone_names_to_entries` (`:133-148`) |
| `custom_components/universal_room_automation/config_flow.py` | D3 | Thread `summary["zone_id"]` from `_delete_zone_locked` caller into dispatch (`:7611-7641`) |
| `quality/tests/test_zone_delete_prune_guard.py` | D1 | NEW |
| `quality/tests/test_zone_migration_mint_guard.py` | D2 | NEW |
| `quality/tests/test_zone_delete_dispatch_snapshot.py` | D3 | NEW |
| `docs/readmes/README_v<next>.md` | close | pre-deploy scaffold, post-live write-back |

No CONF_*, no new sensors, no signal changes, no schema changes.

---

## Test plan

Under `PYTHONPATH=quality python3 -m pytest quality/tests/ -v`:

- **D1 unit tests** — fixture builds a fake `ZoneManager` with a merged `zone_1` whose `zone_name == "Entertainment + Master Suite"` and `thermostat == "climate.thermostat_bryant_wifi_studyb_zone_1"`; separate surviving ENTRY_TYPE_ZONE fake entries for `"Entertainment"` and `"Master Suite"` both claiming that thermostat. Dispatch payload `{"deleted_zone_name": "Entertainment + Master Suite", "deleted_zone_id": None}` → assert `zone_1` remains, log at WARNING contains guard string.
- **D1 negative test** — solo zone `zone_2` (single house zone, single thermostat); delete it → assert prune happens.
- **D2** — construct room entries with CONF_ZONE = compound; construct ZONE entries for both parts; run migration → assert no `async_init` for the compound; assert WARNING logged.
- **D3** — monkeypatch `_resolve_zone_id_for_delete` to return different values at confirm vs dispatch; assert dispatch payload uses confirm-time value.

Baseline diff: tag `pre-review-<next-version>` before any review-fix commit.

---

## Rollback

Both guards are purely refusal-to-act paths. Rollback = revert the three commits. No DB state, no config state changed by this cycle. The 2026-07-12 outage was auto-recovered by restart, so a regression here has the same auto-recovery.

---

## Live validation (write-back into README post-restart)

- **L1 — Guard fires on collision.** Operator recreates the collision (or triggers the equivalent test-delete on a synthetic zone) and confirms `sensor.ura_hvac_coordinator_zone_1_*` attributes update within 60s post-delete; log carries the D1 WARNING.
- **L2 — Non-collision delete still works.** Delete a disposable single-thermostat zone; confirm ZM prune + persisted-store rewrite still happen; no D1 WARNING logged.
- **L3 — No phantom mint on boot.** After restart, grep HA log for `"Migrating zone"` — no line for any compound / merged-display name. If a room still carries a stale CONF_ZONE, the D2 WARNING appears exactly once.
- **L4 — Dispatch snapshot** (if D3 taken). Compare `"Zone delete starting: … zone_id=…"` and `"Zone delete signal dispatched: … zone_id=…"` lines — same value.

Cycle closes only after the README's Live Validation table is written back with observed PASS/FAIL per row and cited entity/log evidence.

---

## Open operator questions

1. **Take D3?** Recommended yes (small, defense-in-depth, cleaner story). Confirm before build.
2. **P1+P2 union for D2, or P2 only?** Union is safer but a touch more code; P2-only is enough for the observed incident. Which do you want as default?
3. **Should D2 additionally repair the room's stale CONF_ZONE** (blank it out, or set to a sentinel) rather than only logging? Repair is out-of-scope per this plan (separate surface, ripples into per-room reload) but worth deciding now so we do not re-plan.
4. **Discovery re-derive on delete** — out of scope here, but should a follow-up cycle add a lightweight "re-run `async_discover_zones` on `SIGNAL_ZM_ZONES_UPDATED`" so future prune bugs cannot cause a 5-hour inert-thermostat window? Filing as backlog unless you want it folded in.
