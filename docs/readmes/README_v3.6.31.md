# v3.6.31 — NM Config Flow Navigation Fix

**Date:** 2026-03-04
**Scope:** Hotfix — makes all 4 Notification Manager config steps reachable via chained navigation

---

## Problem

The Notification Manager config flow had 4 steps implemented in code:
1. **Channels** — enable/severity per channel (Pushover, Companion, WhatsApp, TTS, Lights)
2. **Persons** — per-person entity, credentials, delivery preference, digest times
3. **Quiet Hours** — house state toggle or manual start/end times
4. **Cooldowns** — per-hazard-type cooldown durations

Only step 1 (Channels) was reachable from the Coordinator Manager options menu. Steps 2–4 existed as methods with full UI schemas and translations but had no navigation path — the channel step called `async_create_entry()` immediately on submit, saving only channel config and never advancing.

## Fix

Chained the 4 steps sequentially using a `_nm_pending` accumulator:

```
CM Menu → Notifications (channels)
  → Submit → Persons
    → Submit → Quiet Hours
      → Submit → Cooldowns
        → Submit → async_create_entry(all accumulated config)
```

Each step merges its `user_input` into `self._nm_pending`. Only the final cooldowns step calls `async_create_entry()` with the complete merged config.

## Files Changed

| File | Change |
|------|--------|
| `config_flow.py` | Chain 4 NM steps: channels→persons→quiet→cooldowns→save via `_nm_pending` accumulator |
| `const.py` | Version bump to 3.6.31 |

## Testing

- Full suite: 686 tests passing, 0 failures
