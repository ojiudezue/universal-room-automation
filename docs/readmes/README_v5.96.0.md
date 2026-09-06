# v5.96.0 — Egress identity: BLE ENTRY crossing producer (the naming finally fires)

**Card:** EGRESS-BLE-PROVENANCE-GATE-DROPS-DEPARTURES-1 (rev5, entry-only). Under the 6.0.0 IDENTITY-DRIVEN AUTONOMY arc.
**Tier:** 3 — 3 plan-reviews (each FIX-REQUIRED, all fixed in-plan) + 3 framing-disjoint build reviews (A ship / B+D fix-required) + consolidated fix-up + orchestrator independent mutation-verify. MINOR: first working egress `person_id` attach.

## Problem
Egress `person_id` attached on **1 of 7,314** crossings all-time. Root causes (measured, not assumed): the BLE crossing leg keyed off `person.<slug>` — a lossy HA aggregate resolved by a `last_updated` race across all of a person's trackers (a stationary Mac could win/consume the edge) — behind a Bermuda-only provenance gate that dropped every GPS-sourced departure. Neither BLE nor face was naming crossings.

## What shipped (ENTRY-ONLY v1)
Re-architected the crossing producer to subscribe **directly to each resident's `source_type==bluetooth_le` device_trackers** (runtime-derived from `person.<slug>.device_trackers` — no hardcoded list, no CONF), escaping the person.state race and structurally excluding wall tablets / Macs / GPS phones. Measured (D0) that BLE is the clean signal (both directions, zero unavailable churn; GPS had 355 unavailable flaps) and that the BLE `home` edge **leads** the door crossing by ~105s → an entry LEAD window resolves within the existing +45s read.
- **`BLE_EGRESS_ENTRY_LEAD_S = 180`** (module rung; from D0 median +105 / p75 +151).
- **Sticky bluetooth_le classification** — a tracker that ever classified BLE stays subscribed through transient `unavailable` (HA drops `source_type` when unavailable); `unavailable→home` is admitted as an arrival. Critical for Oji (single BLE tracker).
- **Boot-race self-heal** — derive on HA-started + re-derive on the census tick; a late-loading tracker is picked up, never orphaned; never latches a failed/empty derivation.
- **Per-(slug,direction) single-use** consumption on the attach path only (no cross-crossing re-use).
- **Cross-resident guard** — abstains (records ambiguity) rather than silently mislabeling when a tracked resident has zero BLE trackers.
- **Discriminating observability** on the persons-in-house sensor: legs produced / attached / abstained / dropped-invalid / dropped-benign / derived-tracker map.
- **EXIT is deferred** to `EGRESS-EXIT-IDENTITY-BACKFILL-1` (the departer's `not_home` edge lags the crossing ~369s, past the resolve window → backfill design).

## Reviews (framing-disjoint, each caught what the others missed)
- Plan-review ×3: killed a self-defeating sustain gate (would have made attach=0), the `_read_source_inventory` misreuse, and set the entry/exit split from D0.
- Build A (correctness): SHIP. Build B: the map-latch-on-failed-subscribe + untracked listener leak. Build D (adversarial): the `unavailable→home` double-drop + cross-resident mislabel. All fixed in one consolidated pass; every load-bearing site RED-on-neuter (orchestrator re-verified the sticky classification + the D-2 guard independently).

### Acceptance criteria
- **Verify:** a resident's BLE `home` edge within 180s before a door crossing attaches their `person_id`; a wall tablet / GPS / non-BLE change never produces a leg; a departing edge never attributes in v1.
- **Test:** 33 fusion tests incl. the rev5 + fix-up anchors, each RED-on-neuter.
- **Live:** post-restart, the next real arrival writes a `person_entry_exit_events` row with the correct `person_id` (off the 1/7314 baseline); the produced/attached counters move; `_ble_edge_dropped_invalid_count` catches offline flaps.

## Non-goals / deferred
Exit naming (`EGRESS-EXIT-IDENTITY-BACKFILL-1`), the Frigate MQTT sub_label bridge (`FRIGATE-SUBLABEL-FACE-BRIDGE-1`), the flapping-face veto (parked phantom). Face path untouched.

## Live Validation — post-restart (to record as `Validated <date>`)
- Next real arrival for a resident → correct `person_id` on the crossing row; observability counters non-zero.
- A BLE tracker blip to `unavailable` does NOT drop the resident's subscription (sticky).

---

## Validated 2026-09-05 (post-restart boot-load; organic attach pending)

HA restarted ~19:27 CDT; v5.96.0 loaded. Producer **armed and correct**:

| Check | Result | Evidence |
|---|---|---|
| bluetooth_le trackers derived (no stationary devices) | **PASS** | `sensor.*_persons_in_house` `ble_crossing_trackers_derived` = `[ezinne_iphone, ezinne_iphone_bermuda_tracker, iphone_jaya_bermuda_tracker, iphone_oji_bermuda_tracker, private_ble_device_249050, ziri_iphone]` — all 6 are bluetooth_le; every wall tablet / Mac / GPS phone excluded; Oji's single BLE tracker present. |
| observability counters present | **PASS** | `ble_legs_produced/attached/abstained/edge_dropped_invalid/edge_dropped_benign/departing_edge_seen` all present, all 0 (clean boot, nobody home — state 0). |
| clean boot | **PASS** | error_log scan: only benign WARNINGs (Envoy deferred re-validation, HVAC boot-settle timeout, TLS notices); no URA ERROR/traceback; no BLE-producer exception. |
| correct person_id attach on a real arrival | **PENDING (organic)** | `egress_identity_attach_rate_24h=0`, `egress_identity_last_attach={}` at boot — proves on the next real resident arrival; watch the produced/attached counters + a `person_entry_exit_events` row with a non-null `person_id`. |
| sticky subscription survives an `unavailable` blip | **PENDING (organic)** | verify a BLE tracker blip does not drop `ble_crossing_trackers_derived` membership. |

Note `jjs_iphone` (jaya, bluetooth_le) was absent from the derived set at boot (it was `unavailable` → no `source_type`); jaya remains covered by `private_ble_device_249050` + `iphone_jaya_bermuda_tracker`, and the sticky classification will admit `jjs_iphone` once it reports available.

---

## Validated 2026-09-06 (LIVE — real attaches confirmed)

The entry producer attached real crossings, off the 1/7314 baseline:
- `person_entry_exit_events` last 24h: **6 rows with a non-null person_id** — `jaya` 03:19 (garage return), `jaya` 18:33, `ezinne` ×2 15:26 (all `direction=entry`).
- Live `egress_identity_last_attach`: `person=jaya, provenance=ble, direction=entry, signed_lag=-31.8s` (BLE edge led the crossing ~32s, inside the 180s LEAD window), `agreement_class=single_source`.
- `ble_legs_produced=2, ble_legs_attached=1` on the most recent arrival.

**PASS** — BLE entry attribution fires correctly on real resident arrivals. (The matched crossing camera is the front `doorbell_lite`, not the garage, for Jaya's garage return — the BLE leg names *who*; the camera is whichever egress crossing fell in the window. Identity correct.)
