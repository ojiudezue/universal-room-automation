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
