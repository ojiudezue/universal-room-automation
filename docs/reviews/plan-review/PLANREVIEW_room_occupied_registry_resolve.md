# PLAN REVIEW: room entities resolved through the registry (ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1)

Plan: `docs/planning/PLANNING_room_occupied_registry_resolve.md` (develop c56d0828; reviewed on c5cd29c0, plan unchanged).
Tier 2 plan review, two framings: (1) completeness, (2) goal fidelity (G). Read first, completely:
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §4.2b, §10 ledger). Nothing below re-asserts a §10 claim.
No pytest run; live data read-only from `/Users/okosisi/ha-config/.storage/core.entity_registry` + `core.config_entries`.

**Verdict: FIX-PLAN.** The core design is right and the live numbers hold. Five plan edits are needed before build
(F1-F5); none needs an operator ruling except F6.

## Verified (holds)

- **Live numbers re-derived, exact match.** 47 room entries; registry row for all 4 keys in 47/47. Slug
  (`memory_facade._slugify`) resolves occupied 37, temperature 40, humidity 35, unavailable_entities 38. Plain
  `lower().replace(" ","_")` resolves occupied 36 (the extra miss is Ziri, as §0.1 says). The 10 occupied-miss rooms are
  exactly the plan's set (Guest Bedroom 1 Bathroom, Guest Bedroom 2, Jaya Bedroom, Media, Master Bath Toilet, Master
  Hallway, Up Guestbedroom Closet, Guest Bedroom 2 Hallway, Foyer, Master Closet).
- **Name facts.** 0 duplicate room_names; 0 rooms whose options room_name differs from data; 1 title != room_name
  (`Jaya Bedroom (Bedroom 4)` / `Jaya Bedroom`). Uniqueness is enforced case-insensitively at create
  (`config_flow.py:2197`) and rename (`config_flow.py:12432-12438`), and rename writes through to data + title
  (`config_flow.py:12445-12460`).
- **unique_id contract.** `entity.py:34` `f"{entry_id}_{entity_type}"`; keys confirmed: occupied `binary_sensor.py:294`,
  temperature `sensor.py:735`, humidity `sensor.py:774`, unavailable_entities `sensor.py:1819`. Trap the builder must not
  fall into: Sensor Presence keeps key `presence` (`binary_sensor.py:828`), not its display name.
- **Dropping `title` in fan_veto is safe.** Every caller passes `CONF_ROOM_NAME`: `actuator_reconciler.py:218-220`,
  `automation.py:3229-3232`, `hvac_fans.py:923`, `:2364`.
- **R7/R8 slug fallback deletion has no live delta.** `switch.*_automation` and `_override_occupied` resolve 47/47 by
  registry AND by slug, so the fallback never decides today.
- **HVAC ripple.** The guard (`hvac_fans.py:1886`) sits only on HVAC-tier OFF writes; per §4.2b only Fan Mode Follow
  thermostat rooms reach it. Plan §0.2's claim (no miss room is HVAC-owned) matches the doc's ownership rule; not
  re-read live here.

## Framing 1 — completeness

| # | SEV | Finding | Evidence | Fix in plan |
|---|---|---|---|---|
| F1 | MEDIUM | **INV-RE's key set does not cover its own readers.** INV-RE fixes K = {occupied, temperature, humidity, unavailable_entities}, but R6 reads `camera_person_detected` and R7/R8 read switch suffixes (automation, override_occupied/vacant, cover_automation, ai_automation...). As written, D4 is outside the falsifiable invariant and a reviewer cannot falsify it. | `fan_veto.py:392-396,405`; `coordinator.py:3248,3264,3271`; `switch.py:5417` | Restate K as "any key URA registers under `{entry_id}_{key}`" and list the keys per reader. |
| F2 | MEDIUM | **R5/R4 co2 and tvoc are not URA room entities.** NM maps `high_co2`/`high_tvoc` to signals `co2`/`tvoc` and reads `sensor.{slug}_{signal}` (`notification_manager.py:1812-1826`). No URA sensor registers key `co2` or `tvoc` (only `illuminance` among the extra sensor keys, `sensor.py:800`); 0 `sensor.<room>_co2/_tvoc` entities exist in the live registry. D3's "resolve `{signal}` through D1" therefore always misses for these signals, feeding the D5 miss counter. It is masked today only because the baseline never learns co2/tvoc (`memory_baseline.py:117-140`), so the live read is never reached. | as cited | Scope D1 lookups to the 4 learned keys; co2/tvoc either read the room's CONFIGURED sensor from the entry, or are declared out of scope with a card. Never count them as misses. |
| F3 | MEDIUM | **Two Live criteria do not discriminate or can't run.** D2 Live: "`ha_eval_template` call of the resolver path" is not possible (a template cannot call a Python helper), and "the diagnostics dump in D5" does not exist (D5 defines only an attribute). D4 Live: toggling Master Closet's Automation switch passes on old AND new code, because switches already resolve 47/47 by slug. | plan §4 D2, D4; live registry | D2: expose the resolved ids for the 10 miss rooms as a diagnostic attribute (or log line at boot) and check it. D4: drop it as a discriminator, or pick the fan_veto `camera_person_detected` lookup in a miss room (Foyer, Media...), which does change. |
| F4 | LOW | **Missed compliant prior art.** `presence.py:6082-6084` already resolves `{entry_id}_occupied` through the registry (guest D5 rooms); `_ble_corroboration.py:51` is another registry reader. The NEW-justification ("three registry copies") undercounts; presence 6083 should be cited as REUSE and migrated onto D1 or left with a reason. | as cited | Add to §1 table. |
| F5 | LOW | **Unnamed reused constant and unnamed table.** §5 reuses "the existing 600 s boot window constant used by presence" without a name (several 600 s constants exist: `const.py:936,1082,2712`; presence `RESIDENT_RETURN_BOOT_WINDOW_S`). D3 Live says "the URA DB baselines table"; the writer is `upsert_memory_baseline` into `metric_baselines` (`database.py:10901`). | as cited | Name both. |
| F7 | LOW | **Slug-to-entry mapping can be ambiguous.** Name uniqueness is case-insensitive on the raw string, not on `_slugify` output ("Study-A" and "Study A" both slug to `study_a`). `room_entry_id_for_slug` needs a defined tie rule (return None + count, not first match). Also `memory_baseline._is_room_suppressed` (`memory_baseline.py:56-80`) matches rooms by slug from `coord.room_name`; D3 should route it through the same mapping so the quality gate and the sampler agree. | as cited | Add the tie rule and the sibling. |

Other sites found by the re-enumeration and correctly out of scope: `optimization.py:2655,3305` (camera-derived
`*_person_occupancy` ids, C2 cluster), `person_coordinator.py:1790-1798` (card cited), `button.py:396-459` (export file
names, not entity ids), `fan_veto.py:562` / `memory_writers.py:73` (node keys, URA-owned).

**Tier.** Tier 2 is defensible: no schema, payload, or write primitive change; the guard has no live actuation delta
(§0.2), and D3's new `metric_baselines` writes are 3 rows per cycle for one room. But the standing policy (CLAUDE.md,
2026-06-08) elevates trust-hierarchy ripple, and this plan changes one helper read by an HVAC guard, the presence AWAY
fan veto, and every room's automation gates. **Recommend: keep Tier 2 for the plan, run three build reviews (add a
mutation framing C)**, because the failure mode is one site still building an id, which is exactly what per-site mutation
catches. The guard newly blocking fan-off is the INTENDED behaviour (fail-open was the defect), so it is not by itself a
reason for 2-DB.

## Framing 2 — goal fidelity (G)

Operator rule (CLAUDE.md:117-124): resolve through the registry; a string test only as "a logged, counted last-resort
fallback"; "Unacceptable to do the latter anymore."

| # | SEV | Finding | Evidence | Fix |
|---|---|---|---|---|
| F6 | MEDIUM (operator yes needed) | **R5 keeps a name-built read with no counter.** "A location that names no room keeps today's path" leaves `sensor.{location_slug}_{signal}` in place, uncounted and unlogged. That is the exact residual the rule forbids unless it is a counted fallback. | plan §4 D3; `notification_manager.py:1802-1826` | Either remove the fallback (no room → no conditioning) or make it counted + logged and get the operator's yes in the plan. |
| F8 | MEDIUM | **Name lookup where the entry is already in hand.** D1 resolves by `room_entry_id_for_name` everywhere, including callers that hold the entry: `actuator_reconciler` (`self.coordinator.entry`), `automation.py` (room config), R7/R8 (`self.entry`). The name hop is the weak link: `hvac_fans` registers `_room_fans` keyed by the boot-time name (`hvac_fans.py:464`), so after a rename and before the reload, the old name resolves to None and the guard fails open. Passing `entry_id` where it exists removes the name match entirely. | as cited | D1 takes `entry_id` first; name lookup only for callers that have no entry (NM location, memory node slug). Carry `entry_id` on `RoomFanState`. |

What the plan gets right on G: no slug fallback in D1, no cache, deletes the three existing fallbacks, counts misses with
a trip-wire, and the C5-music / person / camera residuals each have an owning card. Memory node ids stay as URA-owned
keys (allowed).

## Must-fix before build

F1, F2, F3, F6 (operator answer recorded in the plan), F8. F4, F5, F7 are one-line plan edits; fix in the same pass.

## Summary statistics

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 5 (F1, F2, F3, F6, F8) |
| LOW | 3 (F4, F5, F7) |

Bug classes: #53 computed-but-not-consumed / one-missed-site (F1, F4, F7); #62 hollow anchor risk in non-discriminating
Live criteria (F3); name guessing (REGISTRY-NOT-NAMES-1) residual (F6, F8).
