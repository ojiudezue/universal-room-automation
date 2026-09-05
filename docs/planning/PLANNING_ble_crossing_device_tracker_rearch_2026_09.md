# PLANNING — BLE crossing producer: device_tracker re-architecture (rev 2)

**Card:** EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 (pivoted to re-arch)
**Tier:** 3 (delicate, cross-component, invariant-critical — the mission-critical egress-identity producer; wrong attribution = corrupted person_id).
**Rev 2:** incorporates PLAN-FIX-REQUIRED (2026-09-05): PLAN-CRIT-1 (unavailable-forges-crossing), PLAN-HIGH-1 (source_type classification), PLAN-HIGH-2 (same-phone dup-tracker phantom legs), per-slug single-use, TTL coupling, INV-EGRESS-ID validation, discriminating observability.
**Supersedes:** the `feature/ble-crossing-tracker-allowlist` approach (person.state + source-allowlist filter). Build on that branch (reuse the reviewed allowlist constant + tests); replace the listener source.

## Why (root causes)
1. Attach = 1/7314: BLE leg keyed off `person.<slug>` with a Bermuda-only gate; departures are GPS-sourced → every departure rejected.
2. **D-HIGH-1:** `person.state` is a lossy HA aggregate of ALL the person's trackers, resolved by a `last_updated` race (HA `person`; `_get_latest` picks the most-recently-updated GPS tracker). `person.oji_udezue` = 19 trackers incl. 6 stationary GPS Macs that can flip/consume the edge → real crossings later produce no leg.
3. **A-3 (HIGH):** symmetric ±330s window + legs never consumed → one person's departure leg labels ANOTHER's crossing.
4. **D-MED-1:** rejected-leg counter surfaced nowhere → the 1/7314 hid for months.

## Solution — subscribe to the body-phone device_trackers directly
Stop consuming `person.<slug>`. Subscribe to each resident's explicitly-configured body-phone **device_trackers**. A device_tracker edge is the unaggregated signal — no person-component race; stationary devices excluded by not being subscribed.

### Falsifiable invariant (Tier-3)
> For resident R, a crossing leg is recorded **iff** one of R's explicitly-configured body-phone device_trackers makes a **valid** home↔away edge, where **valid** = both old and new state ∈ {`home`, `not_home`, a zone name} (a transition where either side is `unknown`/`unavailable`/`None` is NEVER a crossing). And:
> - (a) **no** non-subscribed device (stationary, another resident's, or an offline-flapping tracker) can produce OR consume R's crossing edge;
> - (b) a real crossing event produces **exactly one** leg per (slug, direction) even when R has multiple trackers firing (dedup/refractory), and that leg attaches to **at most one** crossing (per-(slug,direction) single-use);
> - (c) a leg attaches only in the **direction-correct** window: a departure (exit) leg may only *trail* its crossing; an arrival (entry) leg may only *lead* it;
> - (d) every attached `person_id` is a canonical slug in `tracked_persons` (INV-EGRESS-ID).

Falsified by: a leg from an `unavailable`/`unknown` transition; a leg from a non-subscribed device; ≥2 legs or ≥2 attaches for one real crossing event; an attach out of direction/time; a real single-resident crossing producing no leg when its phone edge fired; an attached slug not in `tracked_persons`.

## Deliverables

### D1 — device_tracker subscription (replaces the person.state listener)
- **`const.py`:** replace the flat allowlist with a tracker→slug map `EGRESS_CROSSING_TRACKERS: Final[dict[str,str]]` (module rung; security-relevant; "requires code review to change"). Operator-confirmed (iPhones + BLE only; `okosisipadmini6_2` + `samsung_a73` EXCLUDED — occasional carries):
  - `device_tracker.phalanxiphone15promax` → `oji_udezue`
  - `device_tracker.phalanxiphone15promaxcflare` → `oji_udezue`
  - `device_tracker.iphone_oji_bermuda_tracker` → `oji_udezue`
  - `device_tracker.ezinne_iphone` → `ezinne`
  - `device_tracker.ezinne_iphone_bermuda_tracker` → `ezinne`
  - `device_tracker.jjs_iphone` → `jaya`
  - `device_tracker.private_ble_device_249050` → `jaya`
  - `device_tracker.iphone_jaya_bermuda_tracker` → `jaya`
  - `device_tracker.ziri_iphone` → `ziri`
- **Startup validation (INV-EGRESS-ID):** at registration, assert every slug value ∈ `_get_tracked_person_slugs()` (`camera_census.py:3142`); log a one-time WARNING and drop any map entry whose slug is not tracked. A stale slug must never reach `person_id`.
- **Listener:** rewrite `_register_ble_transition_listeners` to `async_track_state_change_event` on the map's KEYS (device_trackers), not `person.*`. Teardown is **unchanged** (`__init__.py:2247` register / `:4881` teardown) — say so; with a static map, registration no longer depends on `tracked_persons`, so the re-register-on-options-change concern is gone.
- **Edge handling** (the new `_on_tracker_state_change`, replacing `_on_person_state_change`):
  - **PLAN-CRIT-1 state-validity gate:** admit ONLY when BOTH `old_state.state` and `new_state.state` ∈ {`home`, `not_home`, zone-name}. If either is `unknown`/`unavailable`/`None`/`""` → DROP, increment `_ble_edge_dropped_invalid_count`. Never emit a leg from an offline/recovery transition.
  - Direction: new==`home` → `arriving`; new is a valid away value (`not_home`/zone) → `departing`.
  - slug from the map (exact key match).
  - **PLAN-HIGH-1 provenance:** classify GPS vs BLE by reading the tracker's `source_type` attribute **live at edge time** (`gps` → gps; `bluetooth_le`/`bluetooth` → ble). Explicit fallback if `source_type` absent/None (e.g. tracker unavailable): default `ble` (the tighter-window class — fail toward the conservative window). Do NOT use a name-based table: `ezinne_iphone`, `ziri_iphone`, `jjs_iphone` are `bluetooth_le` despite "iphone" names; only the two `phalanx*` are `gps`.
  - **PLAN-HIGH-2 dedup/refractory:** collapse duplicate trackers for the same physical person. When about to append a `(slug, direction)` leg, if a live leg for that same `(slug, direction)` exists within `BLE_EDGE_REFRACTORY_S`, do NOT append (first edge in the window wins) — this defeats the `promax`=home / `cflare`=not_home stale-second-edge phantom. Keep the earliest leg's timestamp.
  - Append `BleTransitionLeg(slug, direction, ts=new_state.last_changed→UTC-aware, provenance∈{gps,ble})`.
- **Acceptance:** a valid edge on `device_tracker.phalanxiphone15promaxcflare` appends one `departing` gps-leg for `oji_udezue`; a stationary Mac update produces nothing (not subscribed); an edge into/out of `unavailable` produces nothing (dropped+counted); two of Oji's trackers firing within the refractory window produce ONE leg.

### D2 — A-3 fix: asymmetric window + per-(slug,direction) single-use (site: `_resolve_ble_legs` ONLY; face windows untouched)
- **Asymmetric window** in `_resolve_ble_legs` (`camera_census.py:3803-3808`) — the ONLY site to change; the face window at `transit_validator.py:1343-1349` is NOT touched. Replace the symmetric `-ttl ≤ cross_age ≤ ttl` test with direction-keyed bounds (verify the existing `cross_age` sign against the current symmetric test before wiring):
  - **Departure (exit):** the leg must TRAIL the crossing — admit only `0 ≤ (leg_ts − crossing_ts) ≤ TRAIL`.
  - **Arrival (entry):** the leg must LEAD the crossing — admit only `0 ≤ (crossing_ts − leg_ts) ≤ LEAD`.
  - Bounds (provenance-discriminated, D-MED-2): GPS geofence lags ~100m/cadence → wider; BLE proximity → tighter.
    - `BLE_EGRESS_EXIT_TRAIL_GPS_S = 180`, `BLE_EGRESS_EXIT_TRAIL_BLE_S = 90`
    - `BLE_EGRESS_ENTRY_LEAD_GPS_S = 180`, `BLE_EGRESS_ENTRY_LEAD_BLE_S = 90`
    - (Only Oji has GPS legs; ezinne/jaya/ziri are BLE-only, so the GPS bounds govern Oji alone — state this so the builder tunes the right one.)
    - All module rung. One-line why each.
  - **TTL coupling (must-fix):** re-derive `BLE_TRANSITION_CACHE_TTL_S` off the BLE family, not the face family: `BLE_TRANSITION_CACHE_TTL_S = max(all four bounds) + 30` = 210. Add an explicit invariant/comment `TTL ≥ max(all bounds)` so a future bound bump can't be silently pruned before its window closes.
- **Per-(slug,direction) single-use:** consumption happens in a census method called from the resolver **after the attach branch commits** (`transit_validator.py:1378-1390`), and ONLY on the attach path — abstain/disagree/no-leg paths must NOT consume. On attach, remove **ALL** legs for that `(slug, direction)` from the cache (not just the one matched) — one real departure may have collapsed to one leg via refractory, but belt-and-suspenders across any residual siblings.
- **Acceptance (discriminating):** A-3 repro — Oji leaves T0 (leg trails his own crossing, attaches oji); Ezinne crosses T+200 with Oji's leg still in cache → Ezinne's crossing does NOT attach `oji_udezue` (Oji's leg PRECEDES her crossing → outside the trailing window, and/or already consumed).

### D3 — discriminating observability (replaces the non-discriminating rejected-count)
- The old `_ble_leg_rejected_provenance_count` provenance gate is GONE (subscription IS the gate); **retire it** (or repurpose to count `_ble_edge_dropped_invalid_count` from the state-validity gate — pick one, document it).
- **Mandatory** discriminating counters, surfaced as attributes on the persons-in-house sensor (alongside `egress_identity_last_attach`): legs produced per direction, attaches, abstains, and `_ble_edge_dropped_invalid_count`. This is the ONLY observable that distinguishes "working" from "dead" post-re-arch (the rejected-count reads 0 either way).
- **Acceptance:** the produced/attached/abstained counters are readable live and a query shows attaches climbing off 1/7314.

## Housekeeping (builder MUST do)
- The five existing tests driving `_on_person_state_change` with synthetic `person.*` events (`quality/tests/test_identity_fusion_d2_d3_d4.py:246,270,658,678,727`): **rewrite in place** to drive the new `_on_tracker_state_change` with `device_tracker.*` events (do not delete — they encode real behaviours). The 4 provenance-allowlist tests from the prior build likewise migrate.
- Fix the now-wrong docstrings/comments: `camera_census.py:220-236` ("a single BLE home↔away transition on `person.<slug>`") and the cache comment at `:1280-1283`.

## Non-goals / parked
- Config-flow exposure of the tracker map (module rung is deliberate — security).
- D-LOW-2 rename brittleness (inherent to explicit ids; the D3 observability catches it).
- Face/D1 sub_label bridge (separate card; face path untouched here; the same asymmetric+single-use fixes will benefit it later).
- Ziri redundancy (`iphone_ziri_bermuda_tracker` exists but not in `person.ziri` — config gap, note only; Ziri away for months).

## Tier-3 review framings (framing-disjoint, parallel)
- **A — local correctness:** map→slug, direction derivation, source_type classification + fallback, refractory dedup, leg append; every resident produces both directions where their trackers allow.
- **B — integration/lifecycle:** listener register/teardown (no leak, no double-subscribe), restart, the asymmetric-window + single-use interacting with the shared face-leg path (face attribution NOT regressed), D4 fail-safe still orthogonal, TTL≥max(bounds) holds.
- **C — test authority (per-site source mutation):** RED-on-neuter for each of {subscription admits a valid edge, unavailable-edge dropped, stationary/non-subscribed rejected, refractory dedup, asymmetric window, per-slug single-use}.
- **D — adversarial completeness:** falsify the invariant across the whole surface — unavailable-forge, non-subscribed produce/consume, double-attach, silent-drop of a real crossing, out-of-`tracked_persons` slug. Legal-config repros required.

## Acceptance criteria (cycle)
- **Test:** the D1/D2/D3 anchors, each RED-on-neuter.
- **Live:** on the next real resident departure/arrival, `person_entry_exit_events` gets a row with the correct `person_id`; the produced/attached counters move; `_ble_edge_dropped_invalid_count` catches any offline flaps.
- **Live (discriminating):** a departure attaches the departer's slug, NOT a co-present other resident's (A-3 closed); an `unavailable` flap on a phone produces no crossing (PLAN-CRIT-1 closed).
