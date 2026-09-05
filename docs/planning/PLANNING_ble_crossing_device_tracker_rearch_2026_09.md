# PLANNING — BLE crossing producer: device_tracker re-architecture (rev 4)

**Card:** EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 (pivoted to re-arch)
**Tier:** 3 (mission-critical egress-identity producer; wrong attribution = corrupted person_id).

## Rev history (why this shape)
- **rev1/2:** device_tracker re-arch to escape the `person.state` last_updated race (D-HIGH-1); + A-3 (wrong-person mislabel), INV-EGRESS-ID, observability.
- **rev3:** operator-directed BLE-ONLY — source = resident device_trackers with `source_type == bluetooth_le`, GPS excluded (measured BLE-ONLY-SUFFICIENT; GPS is the flappy/unavailable source). Reuse existing machinery, no hardcoded map.
- **rev4 (this — after 3rd plan-review, PLAN-FIX-REQUIRED):**
  - **DROP the produce-time sustain/debounce gate entirely.** It was self-defeating (R3-1 CRIT): identity resolves once at crossing+`ENTRY_WINDOW_SECONDS`=45s (`transit_validator.py:1070/1109` → `_resolve_direction` → `_resolve_egress_face_identity` at :1688 → INSERT at `database.py:3915`, no backfill). A leg delayed 180s lands ~135s after the only read → `person_id=None` forever. Flap-filtering is DEFERRED to a measured follow-up (see Deferred).
  - **A-3 primary fix = per-(slug,direction) single-use consumption**, not the asymmetric window. With BLE-only, edges land near the physical crossing (not GPS-lagged), so the A-3 GPS-lag repro is largely mooted; single-use closes the residual.
  - **Window bounds are MEASURED (D0), not asserted.** The face family carries probe medians in-source; the BLE family must too. Keep the EXISTING symmetric `_resolve_ble_legs` window until D0 sets the numbers; asymmetric direction is DEFERRED (R3-7: a bermuda arrival may trail, not lead — unverified).
  - Correct the reuse claim (R3-3): `_read_source_inventory` is a PersonCoordinator method with NO `bluetooth_le` branch — it is the READ PATTERN only; add a NEW census helper.
  - Add the boot-ordering re-register path (R3-4) and the home-boundary gate (R3-5).

## Root cause recap
Attach=1/7314 because the BLE leg keyed off `person.<slug>` (a lossy HA aggregate, GPS-race D-HIGH-1) with a Bermuda-only provenance gate that dropped GPS-sourced departures. BLE-only device_tracker subscription escapes both.

## Falsifiable invariant (Tier-3)
> For resident R, a crossing leg is recorded **iff** one of R's `source_type==bluetooth_le` device_trackers makes a **home↔away boundary** edge (`home` ∈ {old,new} and old≠new, both sides ∈ {home,not_home,zone}); no `unknown`/`unavailable`/`None` side, and no zone→zone (both-away) edge, ever produces a leg. (a) No non-`bluetooth_le` device (wall tablet/Mac/GPS phone) can produce or consume R's edge; (b) one real crossing attaches at most one `person_id`, per-(slug,direction) single-use; (c) every attached `person_id` ∈ `tracked_persons`.

## D0 — MEASURE the BLE-edge↔crossing lag (probe first, gates D2 numbers)
One-shot read-only recorder probe: for each resident's `bluetooth_le` tracker, the signed lag (BLE edge ts − nearest egress crossing ts) per direction, over 14d. Set `BLE_EGRESS_*` window bounds from the measured medians/spread (mirror the face family's in-source probe medians at `const.py:2204-2206`). If arrivals trail rather than lead, the window stays symmetric. Put the numbers in this doc before D2 lands.

## D1 — BLE device_tracker subscription (runtime-derived), re-sourcing the existing listener
- **NEW census helper `_derive_ble_crossing_trackers() -> dict[str,str]`** (tracker_id→slug): for each slug in `_get_tracked_person_slugs()` (`camera_census.py:3142`), read `person.<slug>.attributes["device_trackers"]`, keep each tracker whose live `state.attributes.get("source_type","").lower() == "bluetooth_le"`. Cite `person_coordinator._read_source_inventory` (`person_coordinator.py:206-243`) as the READ PATTERN only — it is a PersonCoordinator method with no bluetooth_le branch, NOT reusable directly. Live-verified set: oji=`iphone_oji_bermuda_tracker` (ONLY one — no redundancy); ezinne=`ezinne_iphone`,`ezinne_iphone_bermuda_tracker`; jaya=`private_ble_device_249050`,`iphone_jaya_bermuda_tracker`; ziri=`ziri_iphone` (away).
- **INV-EGRESS-ID:** slugs are from `_get_tracked_person_slugs()` by construction; assert + drop any non-tracked, one-time WARNING.
- **Re-source the EXISTING `_register_ble_transition_listeners`** (`camera_census.py:3814`) to `async_track_state_change_event` on the derived tracker ids (was `f"person.{slug}"`). Reuse its `_ble_transition_unsubs` teardown (`__init__.py:4881`). Keep the function general (operator: don't permanently narrow it).
- **Boot-ordering re-register (R3-4, the bootcache class):** registration now depends on reading `source_type` at setup — a device_tracker integration loading AFTER URA yields `state is None` → that tracker silently unsubscribed for the process (fatal for oji, who has ONE BLE tracker). Fix: derive on `EVENT_HOMEASSISTANT_STARTED` AND re-derive on the periodic census tick with a set-diff → idempotent re-register of any newly-appearing trackers; one-line WARNING if a tracked slug derives ZERO bluetooth_le trackers.
- **Edge handler** (re-sourced `_on_person_state_change`, rename `_on_crossing_tracker_state_change` everywhere incl. Housekeeping):
  - **State gate (R3-5 + PLAN-CRIT-1):** admit ONLY when `old!=new`, `"home" ∈ {old,new}`, and BOTH sides ∈ {`home`,`not_home`,zone-name}. Reject (count `_ble_edge_dropped_invalid_count`) if either side is `unknown`/`unavailable`/`None`/`""`. This preserves today's home↔away-boundary guarantee and blocks zone→zone forged legs.
  - Direction: new==`home` → `arriving`; else (valid away) → `departing`. slug from the derived map.
  - Append `BleTransitionLeg(slug, direction, ts=new_state.last_changed→UTC-aware, provenance="ble")` immediately (no delay).
- **Acceptance:** a home↔away edge on `iphone_oji_bermuda_tracker` appends one leg for `oji_udezue`; a gps tracker / wall tablet is never subscribed → nothing; an `unavailable` edge → nothing (counted); a `Work→Gym` zone→zone edge → nothing; a BLE tracker that loads after URA is picked up on the next census tick (not orphaned).

## D2 — A-3 fix: per-(slug,direction) single-use consumption (site: `_resolve_ble_legs` + attach path)
- Keep the EXISTING window in `_resolve_ble_legs` (`camera_census.py:~3798`) but set its magnitude from D0. Asymmetric direction DEFERRED.
- **Single-use:** consumption in a census method called from the resolver ONLY on the attach branch (`transit_validator.py:1378-1390`) — NOT abstain/disagree/no-leg. On attach, remove ALL legs for that `(slug, direction)`.
- **TTL:** keep `BLE_TRANSITION_CACHE_TTL_S` ≥ max(window bounds)+slack; re-derive off the BLE family, comment the relation. (No sustain term now.)
- **Acceptance (discriminating):** two residents crossing close together attach to THEMSELVES, not each other; after an attach, the slug's legs are gone (no double-attach).

## D3 — discriminating observability (D-MED-1)
- **Retire** `_ble_leg_rejected_provenance_count` (subscription is now the gate) AND rewrite the two tests that assert it (`test_identity_fusion_d2_d3_d4.py` ~:270, ~:658) against the new counters. (R3-11: retire, not repurpose.)
- Surface on the persons-in-house sensor: legs produced per direction, attaches, abstains, `_ble_edge_dropped_invalid_count`. This is the ONLY observable distinguishing working from dead post-re-arch, and it feeds the Deferred flap decision.

## Deferred (measured follow-ups — do NOT build on spec)
- **Flap/sustain filter** — only if D3 observability shows flap-driven WRONG attaches in production. The camera-crossing ±window + single-use already gate most flap (a flap not near a real crossing attaches to nothing). Card with an evidence trigger.
- **Asymmetric direction window** — only if the D0 probe shows a clear directional asymmetry worth it.

## Reuse ledger (per the presence-infra inventory)
REUSE: `_register_ble_transition_listeners` machinery + teardown; `_get_tracked_person_slugs`; `_resolve_ble_legs` TTL cache; `BleTransitionLeg`; the `_read_source_inventory` READ PATTERN (not the classifier). BUILD-NEW (justified): `_derive_ble_crossing_trackers` (no existing bluetooth_le per-tracker filter); the boot-ordering re-register; the home-boundary gate; single-use; observability counters.

## Tier-3 review framings (framing-disjoint, parallel)
- **A — local correctness:** derivation helper (source_type filter), home-boundary gate, direction, leg append, single-use.
- **B — integration/lifecycle:** re-register/teardown, boot-ordering re-derive (no orphaned tracker; oji's single-tracker case), restart, no double-ingest, face-leg path untouched, D4 fail-safe orthogonal, TTL≥bounds.
- **C — test authority (per-site source mutation):** RED-on-neuter for {bluetooth_le filter admits, gps/wall-tablet excluded, unavailable dropped, zone→zone dropped, home-boundary required, single-use, boot-race re-derive}.
- **D — adversarial completeness:** falsify the invariant across the whole surface (non-ble produce/consume, double-attach, forged zone→zone leg, orphaned-at-boot silent-miss, out-of-tracked_persons slug). Legal-config repros.

## Acceptance criteria (cycle)
- **D0:** window bounds recorded from measured lag.
- **Test:** the D1/D2/D3 anchors, each RED-on-neuter.
- **Live:** next real resident departure/arrival → `person_entry_exit_events` row with correct `person_id`; produced/attached counters move; `_ble_edge_dropped_invalid_count` catches any offline flaps.
- **Live (discriminating):** a departure attaches the departer, NOT a co-present resident; a wall-tablet/GPS change produces no crossing.
