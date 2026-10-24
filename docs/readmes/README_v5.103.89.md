# v5.103.89: Envoy reserve oracle phase 2 + Halo panel channel (off by default)

Two cycles ship together (operator 10-24: "wait for Halo but deploy when ready").

| Cycle | Card | Tier | Deploy risk |
|---|---|---|---|
| EC reserve oracle phase 2 | EC-ENPHASE-CONNECTIVITY-RESILIENCE-1 (plan `docs/planning/PLANNING_ec_reserve_oracle_phase2.md`) | 3 (four framing-disjoint reviews, three re-review rounds of D, orchestrator mutation verify, operator checkpoint 10-24) | MEDIUM (battery-reserve writes and their verification only) |
| Halo S1b NM panels channel | WALLPANEL-URA-NOTIFY-1, S1b (plan `docs/planning/PLANNING_wallpanel_integration.md`) | 2-DB (reviews A/B/C, fix-up, C re-drill) | LOW (switch defaults OFF; no behaviour change until turned on) |

## 1. EC reserve oracle phase 2

### Problem
The Enphase cloud reserve value (`enphase_ev`) goes stale for hours and drops a same-value write silently while a change is pending (upstream barneyonline/ha-enphase-energy#960). URA trusted it as the oracle, so: a stuck reserve was not released (10-23: battery held at 98% while the house imported ~6 kW for 4.5 h); 15/15 CRITICAL "write not applied/reverted" pages in the replay week were false; episodes re-sent the same value 102 and 66 times.

### Changes
- **Trusted local witness (D1):** `WriteVerifier.trusted_local_reserve` reads the native Envoy reserve (`sensor.envoy_482543015950_reserve_battery_level`) with a low-SOC ratchet guard (`RESERVE_LOCAL_LOW_SOC_MARGIN_PCT`=5, `RESERVE_LOCAL_RATCHET_SPAN_PCT`=20); fails closed. `_reserve_action` compares the target against it; attain-bypass base uses URA intent, never the enforced reading.
- **Re-send gap (rule G):** `RESERVE_RESEND_MIN_GAP_S`=900 gates lowering/same-value re-sends; never gates a raise. ≤12 writes/h unchanged.
- **Nudge (D2):** a value Enphase would silently drop is sent ±1 (11 for 10, 99 for 100), at most once per gap; all four `force_redispatch` sinks carry it. Nudge-aware ledger consumers (watchdog ladder, stand-down, conduct exception) and the ledger-anchor pair rule (`ledger_anchor_moves`) keep the ladder working under nudges and EVSE overlay stamps.
- **Cloud-stale classification (D3):** when the local witness confirms the command, verification records CLOUD_STALE instead of paging CRITICAL.
- **Enforced-mismatch alert (D4):** local ≠ desire for 2700 s → HIGH, once per day.
- **Stream tier not built** (D0-P5 NO-GO; `RESERVE_STREAM_WITNESS_ENABLED=False`).
- Deviations B1–B13, B7b, B7c and the commanded-ledger consumer table: plan §13.7.

### Falsifiable invariant (Tier 3)
No reachable path lowers an in-flight charge reserve below URA's intent, and no reserve write is later or more frequent than pre-cycle. Reviews found 4 HIGH (two lowered 80→50 after restart / via a both-legs-unavailable blip; two broke the watchdog ladder, one under EVSE hold) — all fixed with mutation-anchored tests; final D: SHIP. Orchestrator mutated the HIGH-1 base site (3 RED) and the overlay anchor (RED).

### Known limits (accepted, operator Q3)
- Local witness down (~7%, incl. daily 04:06–04:20Z) + stale cloud → stuck reserve undetected, as today. D4 dwell restarts across that outage.
- Stamps are RAM-only: after a restart mid-episode the release waits for the next landed write.
- Under an EVSE hold a refused write takes up to 16 writes before stand-down (= pre-cycle).

## 2. Halo S1b NM panels channel

- New `nm_panel_entities.py`: `switch.ura_nm_panel_channel` (default **off**), `number.ura_nm_panel_lease_ttl_min` (default 30, range 1–240).
- NM delivers alerts to Halo wall panels via `halo.indicate` with leases (lease id = sorted room slugs), targeted to the source room, its zone (`PresenceCoordinator.get_room_zone`), adjacency, or house-wide for life-safety hazards; released on ack/clear/preempt/kill-switch; panel rows written `acknowledged=1` so they never become the active CRITICAL; panels health isolated (degraded after 3 errors).
- **Accepted behaviour:** leases that have no NM episode ride their TTL instead of being released — every HIGH/MEDIUM panel notification, and a CRITICAL newcomer delivered while an unacked life-safety alert holds the slot. Such a panel can stay lit up to the TTL after the cause clears. Lower `number.ura_nm_panel_lease_ttl_min` to shorten it.
- Review C re-drill: 152 mutants, all RED except 5 documented equivalents (M87, M88 alone, M89, M28, M80b).

## 3. NM: one ack clears every outstanding CRITICAL

Card: NM-MULTI-ALERT-TRACKING-1 (follow-up to v5.103.88).

Operator 10-24: "Why is one ack not clearing multiple alerts." v5.103.88 acked only the slot alert, leaving older unacked CRITICALs (e.g. the 02:20 envoy alert behind perimeter alerts) to need more acks and to be re-raised at restart.
- `async_acknowledge(bulk_authority=...)` + `database.acknowledge_all_criticals(cutoff, exclude_hazards)`: one write acks every unacked non-audit CRITICAL row up to the moment the ack began (cutoff taken before any await), and releases each episode's Halo lease. Works while NM is idle/cooldown too (slot state untouched).
- **Authority:** ack button, `acknowledge_notification` service, companion action → clear all. Safe word from an authorized/companion sender → all; from others → all except security hazards (`NM_SECURITY_ACK_HAZARDS`: intruder, security_state_change, exterior_person, envoy_write_verification). Plain "ack" text → slot alert only, as before.
- Review (1 pass, correctness + safety): FIX-REQUIRED HIGH (low-authority ack cleared security CRITICALs) + MED (late cutoff swallowed a concurrent CRITICAL) — both fixed, 8 mutation drills RED.
- **Live:** next button/companion ack → zero unacked CRITICAL rows in `notification_log`.

## Tests
Full suite on merged develop: see deploy line. EC: `test_ec_reserve_oracle_phase2.py` (+ pause/release hygiene, drain precedence). Halo: `test_nm_panel_channel.py`, `test_nm_panel_entities.py` (NM slice 416 passed).

## Not done
- EC: D6 (pending attribute) parked; stream witness parked; upstream #960 filed.
- Halo: S2+ (alert-light flash, voice satellite announcements) not in this cycle.

## Live acceptance criteria (prospective)
- **EC Live:** no ERROR from energy/write-verify after restart; strategy sensor exposes `reserve_reference_source`, `reserve_last_landed(_at)`.
- **EC Live:** next reserve change → `reserve_write` rows carry `reserve_reference_source`; no repeated identical writes inside 900 s.
- **EC Live, organic:** zero false CRITICAL `envoy_write_verification` pages when the local witness confirms; CLOUD_STALE rows instead.
- **Halo Live:** `switch.ura_nm_panel_channel` = off, `number.ura_nm_panel_lease_ttl_min` = 30 after restart; NM health has no `panels` errors.
- **Halo Live (operator-run, plan steps 1–7):** with switch on, a test leak lights only targeted panels; ack releases them.
