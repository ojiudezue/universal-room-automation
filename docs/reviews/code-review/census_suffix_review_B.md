# Census-Suffix Fix — Review B (Consumer Blast Radius)

**Build:** `feature/census-suffix` @ `c20b86819` (CENSUS-SUFFIX-FIX: disambiguation-tolerant Frigate suffix matching)
**Reviewer framing:** consumer blast radius — count the consumers of the newly-populated `person_count_sensor` / `person_binary_sensor` fields; verify no downstream assumes the pre-fix "≤1 per camera / mostly-None" shape; verify no cache pins the pre-deploy None mapping across restart; verify _N-tolerant matching doesn't collide with prior _N handling in sibling paths (v5.46.0 `_strip_disambiguation_suffix` prior art in `camera_resolver.py`).
**Sister review:** A (correctness + edge cases).

## Verdict: SHIP

Every enumerated consumer is either (a) already threshold-tolerant to the pre-fix shape being wrong (boolean predicates on `census_count > 0`, `unidentified_count > 0`), (b) already gated by boot-settle / persistence timers that swallow the deploy-restart transient, or (c) reads the field through a lookup keyed on the REAL entity_id which the fix now stores correctly instead of silently dropping. The prior-art `_strip_disambiguation_suffix` helper (added in the 2026-08-01 operator-picked-camera bench work) is *the same helper* being reused here — no double-map, no conflict; the fix widens its application from the resolver's stem-match sites to the two strict-endswith sites in `camera_resolver._scan_device_entities` and the two legacy scanners in `camera_census.py`. No CRITICAL / HIGH / MEDIUM findings from the consumer-blast-radius framing. One LOW observation about scan-order semantics documented below.

---

## Consumer enumeration (`person_count_sensor` — the load-bearing field)

The pre-fix defect was `person_count_sensor = None` for every `_2`-suffixed Frigate camera, forcing the count path into `_is_entity_on(entity_id)` boolean fallback (max +1 per camera). Post-fix the real per-camera count (0..Frigate `max_persons`, typically ≤5) flows. Enumerated consumers:

| # | Site | Consumer semantics | Blast-radius verdict |
|---|------|--------------------|----------------------|
| C1 | `camera_census.py:1235` (`async_update_census` primary Frigate branch) | `count = _get_sensor_int(cam.person_count_sensor)`; sums into `single_source_total`. Was `+1`; now `+N`. | **Safe.** This IS the intended fix. `single_source_total` feeds cross-correlation which dedups by BLE / face IDs — a higher raw count only propagates if it can't be attributed to a known ID. |
| C2 | `camera_census.py:1404` (secondary counting path; same shape) | Same as C1. | **Safe** — same reasoning. |
| C3 | `camera_census.py:2001-2004`, `:2668-2673` (audit / recompute paths) | Same `_get_sensor_int`; used for logging / recompute snapshots. | **Safe.** No threshold. |
| C4 | `_apply_hold_decay` (`camera_census.py:2451`) — house zone with `CENSUS_PEAK_SUSTAIN_SECONDS` sustain-before-latch on UPWARD moves | The sustain-gate is exactly the machinery that protects downstream from a spurious upward jump. AT cold-boot the FIRST observation (`peak_ts is None`) latches immediately — but at cold-boot the "prior" value is 0, not the pre-deploy artificially-low value; the correct fresh count IS the correct latch. On steady-state operation, a spike is pending-latched until it sustains 15s. | **Safe.** The sustain gate absorbs the deploy-restart transition. `_pending_house_peak` semantics prevent inch-up racing. |
| C5 | `sensor.py:4934` `attrs["census_count"] = presence.census_count` (URA presence sensor attribute) | Passthrough for observability. | **Safe.** No threshold. |
| C6 | `sensor.py:5310` `PresenceCensusCountSensor` (dedicated numeric sensor) | Passthrough of `presence._census_count`. | **Safe.** Numeric surface — the sensor becoming *more accurate* is the point of the cycle. |
| C7 | `presence.py:1167` `has_people = census_count > 0 or any_zone_occupied` (house-state inference) | Boolean predicate. Was `>0` when binary fallback fired; still `>0` post-fix (just larger). No new state transition unlocked. | **Safe.** Boolean-tolerant. |
| C8 | `presence.py:1026, 1050, 1127` (SLEEP/AWAY/veto predicates on `census_count == 0`) | Boolean predicate on zero. Pre-fix and post-fix both `>0` when anyone is on-camera. If pre-fix wrongly reported >0 (binary-fallback for a `_2` camera that fires), post-fix STILL reports >0. If pre-fix wrongly reported 0 (never — binary fallback still counted 1 per on-camera), no change. | **Safe.** Boolean-tolerant; zero-preservation preserved. |
| C9 | `presence.py:5719, 5983, 6046, 6098, 6228` (TransientSignal `census_count` emission for veto/SLEEP inference) | Emits numeric value; downstream H1 gate is boolean (`census_count == 0`). | **Safe.** |
| C10 | `presence.py:2519-2544` (D6 stale-occupancy failsafe: seeds `_census_count` from `total_persons` OR restored numeric sensor at setup, only if currently 0) | Seed path runs ONLY WHEN `self._census_count == 0` (checked at :2534). Post-restart, the FIRST live census tick overrides the seed. Seed source (`house.total_persons` from DB / restored PresenceCensusCountSensor state) is unaffected by this cycle. | **Safe.** No cache of the pre-fix None mapping — the seed reads DB / restored numeric state, not `CameraInfo`. First live scan post-restart re-derives the `CameraInfo` cleanly. |
| C11 | `presence.py:4197-4201` (`_census_count = census_data["interior_count"]`) — the STATE update hook | Receives the corrected number. Fires `census_count changed` observations to the observability ring; no threshold consumer. | **Safe.** |
| C12 | `presence.py:4973` `BOOT_SETTLE_MIN_INPUTS` gate (`_census_count >= BOOT_SETTLE_MIN_INPUTS`) | A HIGHER count crosses the boot-settle threshold FASTER post-fix. The gate exists to REQUIRE evidence before leaving boot-away — faster clearance of a real settle is the desired direction. | **Safe.** Gate is a lower bound; higher accurate counts help it, don't fool it. |
| C13 | `presence.py:5750-5771` (D6 failsafe forcing AWAY when `census_count == 0` AND `any_zone_occupied`) | Predicate on zero. See C8. | **Safe.** |
| C14 | `presence.py:5846` `waking backstop` (`census_count > 0`) — boolean force-WAKE | Same shape as C7/C8. | **Safe.** |
| C15 | `check_zone_occupancy_confidence` (`presence.py:1930`) | Returns (occupied_count, confidence). Does not consume `_census_count` numeric magnitude; consumes per-zone occupancy. | **Not exposed** to this fix — the cycle doesn't touch zone-level counts. |
| C16 | `transit_validator.py:883` (uses `info.person_count_sensor` on egress infos) | Passthrough entity_id → state subscription. Now subscribes to REAL `_2` entity instead of storing None. | **Safe** — this is a strict improvement (subscription actually fires). |
| C17 | NM contextual severity on census counts | Grep across `notification_manager.py` for `census_count` returns only structural references; no threshold-on-count severity map that would misfire at higher counts. | **Not exposed.** |
| C18 | `_camera_by_entity` dict (`camera_census.py:722, 754, 821`) | Rebuilt at every scan — no persisted state; no RestoreEntity around `CameraInfo` shape. | **Safe.** No stale-mapping cache across the deploy restart. |

## Consumer enumeration (`person_binary_sensor` — the second-order field)

Pre-fix defect: `_scan_device_entities` strict `_has_any_suffix(_PERSON_SUFFIXES)` missed `_2`-suffixed binaries, leaving `person_bs = None` on the fusion source. Post-fix stores the REAL disambiguated entity_id (`sensor.foo_person_occupancy_2`).

| # | Site | Consumer semantics | Blast-radius verdict |
|---|------|--------------------|----------------------|
| B1 | `binary_sensor.py:1420, 1451` (`URAPersonBinarySensor.is_on` + attributes) | `hass.states.get(eid)` on the resolved entity_id. Pre-fix `eid = None` → skipped. Post-fix reads the real state. This is the CORRECTNESS restoration. | **Safe** — strict improvement. |
| B2 | `binary_sensor.py:1217` — `person_binary_sensor_entity_ids()` list, fed to `async_track_state_change_event` | Now includes `_2` entities so state changes actually trigger. Additive listener set; no threshold. | **Safe.** |
| B3 | `__init__.py:2276` — `_person_detection_entities` for census-trigger event listener | Same as B2; more entities watched → census recomputes on their transitions. | **Safe.** |
| B4 | `perimeter_alert.py:463, 806, 2360` (`base_bs = info.person_binary_sensor`) | Perimeter uses the real entity_id for alert dispatch. Was silently no-op on `_2` cameras. | **Safe** — strict improvement. |
| B5 | `transit_validator.py:379, 383, 879, 887` | Same shape as B4 for transit egress/interior tracking. | **Safe.** |
| B6 | `fan_veto.py` — checked; the file consumes camera-person via its own `_has_camera_person` primitive that does NOT go through `CameraInfo.person_binary_sensor`. | Not on the propagation path. | **Not exposed.** |
| B7 | v5.46.0 fused-sensor registry `_N`-suffix stem matching (per dispatch note) — grep for `fused_sensor_registry` finds no such symbol; v5.46.0 reference in `notification_manager.py:1547` is about slug-guess-fallback for notify service names, unrelated to Frigate `_N`. The `_strip_disambiguation_suffix` helper is the ONE canonical prior-art site (introduced 2026-08-01 for the operator-picked-camera bench). This cycle reuses that helper verbatim. | No double-map possible — same function, applied at additional sites the resolver previously used strict `endswith` for. Ambiguity guard `_prefer_canonical` explicitly protects the case where a device has BOTH canonical and `_N` variants (WARN + canonical wins). | **No conflict.** |

## Sanity — tonight's 10-person house / threshold-consumer step-jumps at restart

Concern: with real counts flowing, tonight's household could show census ≈ 10; does any consumer fire on a `4 → 10` abrupt step at deploy restart?

- **Guest-mode arming** (`presence.py:4744` `_guest_gate_armed`): three guards — existence (`unidentified_count > 0`), confidence gate (`_guest_require_confidence`), **persistence** (`_guest_persistence_seconds`, default measured in tens of seconds). A restart-transient higher count does not instantly arm guest mode; the persistence timer buffers. Additionally, `unidentified_count` is derived post-BLE-dedup — 10 people known via BLE = 0 unidentified.
- **House-state transitions**: predicates are boolean (`> 0` / `== 0`), not magnitude-thresholded. No new transition unlocked by 4→10.
- **NM party heuristic**: grep finds no such heuristic keyed on `census_count`. Not exposed.
- **BOOT_SETTLE**: at cold-boot the `_census_count` seed path (`presence.py:2519-2544`) reads DB `house.total_persons` OR the restored numeric sensor, NOT the pre-fix live scan — so the seed is unaffected by the fix's changed matching. The first live post-restart tick then overwrites with the corrected value; boot-settle gate `_census_count >= BOOT_SETTLE_MIN_INPUTS` is a lower bound that a higher-accuracy count only helps clear more legitimately.
- **`_apply_hold_decay` house-zone sustain-before-latch**: absorbs upward transients that don't hold for `CENSUS_PEAK_SUSTAIN_SECONDS`. Cold-boot first-observation latches immediately — the correct value.

Verdict: no threshold consumer step-fires on the restart transition.

## Restart-cache audit — does anything pin the pre-fix None mapping across the deploy?

- `_camera_by_entity` dict (`camera_census.py`) — rebuilt every scan. No persistence.
- `CameraInfo` dataclass — no RestoreEntity; no `.storage`-backed shape.
- `PresenceCoordinator._census_count` seed at setup — sources from DB `house.total_persons` OR restored `PresenceCensusCountSensor` state, both external to `CameraInfo`. Not a cache of the resolver's None output.
- Room-config resolutions run inside `_scan_device_entities` at load; no serialized `person_count_sensor` cache in config-entry data or options. Confirmed by grep across `const.py` / `config_flow.py` / `options_flow.py` — the field is not persisted.

Verdict: no None-mapping cache carries across the deploy. Post-restart re-scan produces the corrected mapping.

## Findings

### LOW-B1 — scan-order semantics changed for person_binary in resolver

`camera_resolver.py:1393-1396`: prior code was strict `if person_bs is None: person_bs = eid` (first-wins). Post-fix routes through `_prefer_canonical(person_bs, eid, ...)` which prefers the canonical over a disambiguated candidate — meaning if the FIRST entity scanned is `_2` and the SECOND is canonical, the canonical wins (order-independent for this preference axis). This is a semantics change (order-independence introduced) but:
- The `_prefer_canonical` behavior is explicitly the desired ambiguity-guard semantics — a canonical entity should never be shadowed by an accidentally-earlier-scanned disambiguated one.
- For the like-vs-like case (both canonical, or both disambiguated) the helper falls back to first-wins, preserving prior semantics for the common case.
- The change is documented and logged (WARN on ambiguity).

**No action required.** Documented here so the semantics change is on the record for the next reviewer of `camera_resolver`.

### LOW-B2 — resolver-scan for `sensor.<base>_person_count_<N>` iterates entire entity registry (legacy scanner, `camera_census.py:820-830`)

The second legacy scanner (`_scan_all_person_sensors`?) added a `for cand in ent_reg.entities.values()` loop on cache miss. This is O(N) over the full HA entity registry per Frigate binary. On a ~1000-entity install like URA this is single-digit-ms; not a hazard. Consider caching a `{base_name → count_entity_id}` map if the entity count grows. Not a ship-blocker.

## Not-in-scope (verified independent)

- Zone-migration / arrester / auto-enable dry-run / NM suppression WARNs are on `develop`-merged surfaces (`__init__.py`), NOT touched by the census-suffix commit `c20b86819`. Reviewed diff scoped to `camera_resolver.py` + `camera_census.py` + new test module only.
- Face-detect entities: unchanged (`_FACE_SUFFIXES` path still strict — face is inventory-only per D4 policy).

## Verdict recap

**SHIP.** No CRITICAL / HIGH / MEDIUM findings from the consumer-blast-radius framing. Two LOWs documented for record. Fix is a strict correctness restoration; all threshold consumers are either boolean-tolerant, gated by persistence/settle timers, or fed from external sources that don't cache the resolver's pre-fix None output.

---

*Reviewer B — consumer blast radius framing. Sister to Review A (correctness + edge cases). Cycle: CENSUS-SUFFIX-FIX @ c20b86819.*
