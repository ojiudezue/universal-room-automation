# URA v5.16.3 — Write-Verification Persistence Rider

**Type:** Rider on the v5.16.x write-verification cycle
**Commits:** 15d31bd2 (persistence + honest attrs), 59994400 (docstring precision), 94badc02 (framing-C test-authority fix-up)
**Branch:** develop

## What this rider does

### (a) Write-verification state persists across restarts
The write-verification commanded ledger and verified records now persist via
the existing sqlite KV store (keys `wv_commanded_ledger` / `wv_verified_records`):
- **10h staleness guard** — KV payloads older than 10 hours are discarded, not restored.
- **No-clobber** — a fresh post-boot verification outcome is never overwritten by a
  restored (older) record.
- **`restored: true` flag** on restored records, visible in sensor attributes, so live
  validation can distinguish restored state from freshly-earned state.
- **Preserved timestamps** — restored ledger entries keep their original command
  timestamps, so a restored entry can never false-supersede a fresh command.

### (b) Honest commanded-vs-planned reserve attrs on battery_strategy
`sensor.ura_energy_coordinator_battery_strategy` gains:
- **`current_commanded_reserve`** — read from the cloud/write leg (what was actually
  commanded), not the planner's intent.
- **`park_floor_source`** — `commanded` vs `planned_fallback`, making it explicit when
  the park floor derives from a verified command vs the plan alone.

### (c) Corrupt-KV-payload hardening
A non-str `status` in a restored KV payload is normalized to `no_data` instead of
propagating a corrupt type into the verification state machine.

## Review trail
- Framings A/B: ura-reviewer-std (Opus) — **SHIP**.
- Framing C (mutation / test-authority, Fable): **FIX-FIRST** → resolved by 94badc02.
  Executed mutation table: 4 load-bearing restore-path mutations, all **RED** (a
  specific test fails per mutation); +12 tests; zero new suite failures vs baseline
  (36 failed / 14 errors pre-existing, unchanged).

## Shipwatch acceptance

```yaml
shipwatch:
  project: ura
  version: v5.16.3
  deployed: 2026-07-13
  hypotheses:
    - id: H1
      claim: "update.universal_room_automation_update installed_version == v5.16.3"
      oracle: ha_recorder
      confirm_after: 15m
    - id: H2
      claim: >
        Post-restart, sensor.ura_energy_coordinator_battery_strategy attrs
        last_verified_write_reserve_soc (and sibling last_verified_write_* surfaces)
        are NON-NULL after the first verified write matures — verification state
        survives restart instead of resetting to no_data.
      oracle: ha_recorder
      confirm_after: 4h
    - id: H3
      claim: "park_floor_source attr present and in [commanded, planned_fallback]"
      oracle: ha_recorder
      confirm_after: 15m
```

## Live Validation — Validated 2026-07-14

Post-restart observations (restart ~21:06 CDT 2026-07-13; checks 21:10-21:16 CDT):

| ID | Check | Result | Evidence |
|---|---|---|---|
| L1 | Deploy healthy | **PASS** | `update.universal_room_automation_update` installed_version == v5.16.3; `sensor.ura_presence_coordinator_presence_house_state` available (state `away`, known cold-boot value — HouseStateMachine boots AWAY by design); error_log scan: only 3 URA ERROR lines, all at 21:08 boot window ("DB write worker did not process request within 35s" — known boot-transient write-queue congestion), zero after boot settled |
| L2 | Restored WV attrs | **AS-EXPECTED (null)** | `last_verified_write_*` all `{status: no_data, restored: false}`. This is CORRECT on this first post-deploy boot: the persistence code shipped in v5.16.3 itself, so the outgoing v5.16.2 process never wrote the `wv_commanded_ledger` / `wv_verified_records` KV keys — there was nothing to restore. Restore path is proven in-suite (framing-C: 4 executed mutations all RED, +12 tests). Live proof of restore lands on the NEXT restart after a verified write matures — tracked by Shipwatch H2 |
| L3 | Honest reserve attrs | **PASS (honest nulls)** | `park_floor_source: planned_fallback` (valid enum member); `current_commanded_reserve: null` — honest, since no reserve command has been issued this boot (Envoy was still warming up at check time; `envoy_available` flipped false→true at 21:16, strategy mode still `unknown` pending first cycle). The null-until-commanded behavior is exactly the honesty this rider ships |

Boot transients seen and dismissed: 3× DB write-worker 35s timeouts at 21:08 (census snapshot ×2, environmental data ×1) — boot-window write-queue congestion, no recurrence in subsequent scans. `battery_strategy` state `unknown` with reason "Envoy unavailable — holding" during Envoy warmup (~110s discovery) — resolves on first post-warmup strategy cycle.
