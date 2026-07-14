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

## Live Validation (prospective)

| ID | Check | Expected |
|---|---|---|
| L1 | Deploy healthy | installed_version == v5.16.3; presence house_state sensor available; zero URA ERROR lines post-restart |
| L2 | Restored WV attrs | last_verified_write_* attrs non-null post-restart (pre-restart state existed); `restored: true` visible on restored records |
| L3 | Honest reserve attrs | `park_floor_source` present in [commanded, planned_fallback]; `current_commanded_reserve` populated from the write leg |
