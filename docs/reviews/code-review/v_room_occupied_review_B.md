# Review B — ROOM-OCCUPIED-ENTITY-REGISTRY-RESOLVE-1 (e037ff441 + 4761b7919, base d882f2d07)

Framing B: HVAC integration, lifecycle, restart, registry timing, NM. HVAC_ARCHITECTURE_STATE_OF_PLAY.md read in full (§10 ledger included); nothing here contradicts it.
Tests (clean export of 4761b7919): 6 cycle/affected files, 102 passed.

**Verdict: SHIP**

| Sev | Site | Finding |
|---|---|---|
| LOW | room_entities.py `_maybe_page` / `_last_page_day`; `_stuck_signal_nm._LATCHES` | Both dedup latches live only in RAM. A miss that persists past the 600 s boot window pages HIGH again after every restart on the same day. During a restart storm that means repeated pages. Bug class: suppression needs a discharge (here the discharge is too weak). Quiet hours are left to NM routing; the resolver does not check them. |
| LOW | room_entities.py `_entry_for_slug`, `room_entry_id_for_name` | Each call walks every room entry and slugifies each one (~47). These paths run from the NM conditioning, memory_facade and memory_baseline (hourly) callers, not from the HVAC tick. The fan guard uses the entry_id carried on RoomFanState, so it costs one registry dict lookup. Acceptable. |
| INFO | hvac_fans.py `_read_room_occupied_state` | Boot: the entity registry is loaded from storage before integrations set up, so existing rooms resolve even before their platforms load. A brand-new room returns None and the guard fails open (OFF allowed). That matches the old behaviour, where the name-built id did not exist. Net change: rooms with a non-derivable id (Foyer, Media) are now actually guarded, as intended. |
| INFO | rename / re-id | Not cached. The registry follows entity_id renames, and RoomFanState.entry_id is rebuilt from the live entry at each discovery (never persisted). If a room_name rename breaks a slug-path reader, the miss is now counted and paged, where before the reader went blind silently. Pre-existing: rooms are frozen at discovery (§9.8). |
| INFO | async | `hass.async_create_task` is called from the resolver. Every caller is on the event loop (memory_baseline fold is async; the fan guard runs in the loop). memory_baseline/facade DB writes are unchanged (`upsert_memory_baseline`, same calls). |
| INFO | other HVAC funnels | grep of hvac*.py and fan_veto for name-built `*_occupied`/humidity/temperature ids: none left. The W1-A funnels, arrester, pre-arrival and sweep read `any_room_hvac_occupied` / coordinator data, not entity ids. |
| INFO | NM conditioning | Humidity for a room location goes through the registry. co2/tvoc and non-room locations use the counted name fallback, which never pages. Every MEMORY_BASELINE_ALLOWLIST slug matches exactly one live room (fixture). |
