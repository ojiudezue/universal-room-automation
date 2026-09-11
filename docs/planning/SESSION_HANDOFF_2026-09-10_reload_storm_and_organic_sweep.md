# Session Handoff — 2026-09-10 (reload storm root-cause + organic-lane drain)

## TL;DR
- **Shipped v5.100.8** (ROOM-ZONE field→ZM sync + D3 canonical-allowlist test). Live, validated.
- **Biggest open thread: the CM/parent config-entry RELOAD STORM** — root-caused as far as
  static analysis allows; **debug capture is ARMED on the live HA instance** waiting for the next
  evening reload to name the trigger. (HA is on the homelab, not the Mac — the Mac reboot does NOT
  disarm it. Only an *HA* restart would reset the debug log level.)
- **Kanban soak-exit sweep: organic lane 76 → 0** across 9 passes; the lane was a dumping ground
  for mis-filed non-shipped work. All committed to `develop`.

## What shipped this session
- **v5.100.8** — `ROOM-ZONE-FIELD-NO-SYNC-1` (room `CONF_ZONE` → ZM `zones[z].zone_rooms`,
  entry-id list; boot-reconcile backfills; **live-validated**: 41 rooms across 5 zones, each in
  exactly one) + `D3-CANONICAL-ALLOWLIST-BINARYSENSOR-1` (test fix). Orchestrator wire-in
  mutation-verified. Also carried the v8 lovelace dead-ref cleanup (51 refs, applied on restart).
- Carrier stale-detect→reload (shipped earlier) is **now live** as of the v5.100.8 restart — so
  from tonight there is a *legitimate* `ha_carrier`-entry reload source in the logs. Keep it
  separate from the CM/parent reload bug (that one = `ura_*` + room entities, NOT `ha_carrier`).

## ⚠️ OPEN #1 — Reload storm (URA-CONFIG-ENTRY-RELOAD-STORM-1, investigating)
**Symptom:** the INTEGRATION **parent** config entry reloads itself ~5×/night, **evening/overnight
local only** (09-09: 18:12/20:15/20:27/23:01/23:19 CDT). Each reload = **~198 entities**
(118 `ura_*_coordinator_*` + 80 room-tier) blip `unavailable` — the parent-reload cascade
signature. No operator action; **a code/lifecycle bug.**

**Consequence:** the reload transiently restores the onset enable switch
(`switch.ura_energy_coordinator_ev_charge_onset_overnight`) `unavailable→off→on`; a gate tick in
that `off` window takes `_evaluate_onset_gate`'s "feature off → permit" early-out
(`energy_pool.py:149`) → **releases held EV/plug chargers ~2h before the 01:00 onset**.
Last night it fired once (23:01 CDT) but `power=0W` (car not drawing) → **harmless this time**.

**Ruled out (exhaustive):** options-write cascade (NO `scheduling reload` log line →
not the `_async_update_listener` path); every direct `async_update_entry(options=)` writer
(all one-time idempotent migrations); Number/Select/Switch persistence (no recorder value change
pre-reload); SPAN reload; HA restart (`last_boot`=2026-06-07); operator; HA automations
(`grep /config`: none call `reload_config_entry`); the Carrier reload (targets `ha_carrier`,
has URA-domain safety-abort, 0 `carrier_reload` rows that night); the camera-registry path
(`camera_census.py:345-368` + `transit_validator.py:309-331` correctly *invalidate*, not reload).
**Same bug as `RELOAD-WATCHDOG-HAZARD`** (done) whose v5.99.0 fix closed only the camera-key
*options-save* parent-reload path — the storm persists via a **different, still-unidentified
trigger** (evening timing → suspected camera *availability*/IR-switch, unproven; do NOT assert).

**NEXT STEP (definitive):** debug is armed —
`logger.set_level homeassistant.config_entries=debug + custom_components.universal_room_automation=debug`
(set ~05:20 UTC 09-10; **resets on HA restart only**). After the next evening reload:
`ha_get_logs source=system_service slug=core` around the reload, read the `Unloading`/`Setting up`
lifecycle + the URA lines immediately preceding the unload → names the initiator. If still opaque,
escalate: temporary stack-trace breadcrumb at the top of `async_unload_entry` (guard to the
integration/CM entry) → deploy → next reload prints the call stack.
**Reload-signature query:** `switch.ura_energy_coordinator_ev_charge_onset_overnight` going
`unavailable` = a reload fired (check `home-assistant_v2.db` states).

## OPEN #2 — Onset gate (EVSE-CHARGE-ONSET-NOT-HELD-1, waiting_me, depends_on storm)
Gate works (holds 17:00–01:00 window, `ONSET_MAX_HOLD_H=8.0`); the only failure is the
reload-induced early release above. **Reload-resilience fix HELD per operator** ("how can you fix
what you cannot root cause") — root-cause the storm first, then fix at source; only add onset
sticky-enable resilience if still warranted.

## Closed / decided this session
- **Attain ramp tuning** (`ATTAIN-SOLAR-AGGRESSION-INVESTIGATE-1`, done): no safe change —
  the `SOLAR_CAPTURE_FACTOR` nudge BACKFIRES (it's an anti-double-count discount, not
  forecast-optimism; 21d probe: Solcast well-calibrated, capture ~0.20 so 0.5 already generous).
  **KEEP 0.5. Accept ~$140–270/yr.** Only surviving lever = grid-charge timing.
- **Grid-charge lead time** (`arbitrage_charge_lead_time_min`): probe recommended 210; **operator
  said LEAVE AT 180.** No change.
- **ROOM-AUTOMATION-MODE-SELECT-UNAVAILABLE** (done): NOT a defect — the select was deliberately
  deleted 2026-07-26; orphans since cleaned (0 orphan selects; 122/122 `switch.*_automation`
  healthy). Operator was right it was already handled.

## Kanban state (all committed to develop)
- Organic **76 → 0**. Done 80+. Applied a stale operator board-tap
  (`ZIRI-COLLEGE-PERSISTENT-AWAY-1 → investigating`, tapped 08-31). Board renders fresh
  (`kanban_render.py --check` exit 0).
- **19 `waiting_operator`** cards now visible (were buried). Concrete house bugs worth picking up:
  `KITCHEN-NIGHTLIGHT-RANGE-MISCONFIG` (night light wired to range light),
  `MEDIA-ROOM-BLINDS-OPENING` (blinds open on their own),
  `AWAY-BLOCK` (home_day held 2h with everyone away — fan→mmWave self-sustain loop),
  `ZIRI3-UNCONFIG` (recover Ziri 3 device), `ROOM-ENTITY-STALE-CONFIG` (4 config edits),
  `FROZEN-POWER` (solar-only vs shared staleness helper decision).

## Resume checklist
1. Pull core debug log after tonight's first reload → name the reload trigger (OPEN #1).
2. If trigger named → fix at source (likely a camera-availability listener still reloading, or an
   HA-core dependency reload) → then decide if OPEN #2 onset fix is still needed.
3. Otherwise pick a `waiting_operator` house bug (kitchen night-light + away-block are the
   highest-value concrete fixes).
