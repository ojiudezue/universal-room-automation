# v5.103.73: fan recheck runs in bedrooms and media rooms by day

Card: JAYA-FAN-STILL-PHANTOM-1. It was parked, and its revival trigger fired on 2026-10-12: a 2 h daytime phantom hold in Jaya Bedroom with Jaya away and no recheck.

Plan: `docs/planning/PLANNING_fan_recheck_bedroom_still_risk_veto_scope.md`. **Tier 2:** a plan review plus 3 framing-disjoint reviews (`docs/reviews/code-review/fan_recheck_veto_scope_review_{A,B,C}.md`).

**Deploy risk: LOW-MEDIUM.** The fan recheck is now admitted in more rooms by day. Fallback: the per-room "fan recheck" switch.

## Operator intent

> "No blanket refusal outside sleep house mode. Let recheck run when phone says elsewhere... if the room doesn't know where her phone is. Can refuse when BLE has her in the room... Except during sleep."

## Changes (`presence_fan_recheck.py`)

- **Sleep refusal widened.** Bedrooms and media rooms are refused the recheck in `home_night`, `sleep` and `waking`. This applies at arm time, in the arm-delay re-check, and now **mid-flight**: an ARMED or PAUSED room is cancelled as OCCUPIED_CONFIRMED with the fan restored ON when the house enters a sleep state (Review B-1).
- **Removed: the all-day `high_still_risk` veto,** on both the Tier-1 L2 path and the Tier-0/2 path. By day, bedrooms and media rooms are treated like any other room.
- **"BLE has her in the room" (L1) now includes the room's configured scanner areas.** The new `_l1_persons` counts trustworthy persons resolved to any URA room whose area is in this room's `CONF_SCANNER_AREAS`. It applies at arm time and mid-flight.
  - Example: Jaya Bedroom ← Jaya Bathroom.
  - This deliberately differs from room-level `ble_persons`, which uses an exact resolved-location match.
- **Unchanged:**
  - the L2-adjacent veto;
  - the window factors (bedroom ×2, ZK ×2, so Jaya's window is 240 s);
  - the 900 s cooldown, the rate cap and the kill switches.

## Tests

- Cycle files: 127 passed.
- Full name-diff at 02880ec69 vs b716228e9: **CLEAN, 0 NEW / 0 GONE** (12 failing, all pre-existing).
- Mutation:
  - builder drills M1–M12;
  - Review C: 33 sites, with gaps closed in 02880ec69;
  - orchestrator: the mid-flight sleep cancel mutated, 6 tests went RED, then restored.

## Validated 2026-10-20

Restarts carrying this build: 02:05 CDT (07:05:40Z, recorder run 1199) and 09:59 CDT (14:59:25Z, run 1200). Evidence comes from the 09:59 boot unless marked. Read-only checks (ha-mcp, the recorder DB, the URA DB via `ssh ha`).

| Criterion | Result | Evidence |
|---|---|---|
| Install and load | PASS | `/config/custom_components/universal_room_automation/manifest.json` version `v5.103.75` (it carries .73 and .74). `ha_get_integration`: 50/50 URA entries `loaded`. `system_log` ERROR filter for URA: 0 entries. error_log after boot has WARNING-level boot transients only (sensors unavailable for 60s, census cameras unavailable, HA deprecation notices). |
| Veto counter: no `high_still_risk` key | PASS | `sensor.jaya_bedroom_jaya_bedroom_bedroom_4_fan_recheck_state` attribute `fan_recheck_veto_counts = {room_paused: 2}` (02:05 boot: `{room_paused: 5}`). No `high_still_risk` key on either boot. |
| `sleep_state` counts only in home_night/sleep/waking | Not yet exercised | No `sleep_state` veto key on either boot. Jaya Bedroom was paused (`switch.jaya_bedroom_automation` off since 07:06Z), so `room_paused` vetoes every evaluation first. In-suite only. |
| Organic: `fan_recheck_outcome` row for `room:jaya_bedroom` | Not yet exercised | `memory_episodes` with `episode_type='fan_recheck_outcome'` since 07:05Z: only `room:study_a` (2 rows, last 12:26Z). Jaya cannot qualify while paused. Re-check after the room is unpaused. |

Restart: installed now, **restart held** (today's restart budget is used). It goes with the next approved restart.
