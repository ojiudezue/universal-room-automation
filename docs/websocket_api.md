# URA Observability WebSocket API (v5.17.0)

Three read-only Home Assistant WebSocket commands over URA's observability
tables. Feeds the PWA M4 alerts + activity feeds without polling.

**Auth.** Inherits HA websocket auth. Authenticated user is sufficient;
admin is NOT required.

**Invariant.** Zero writes. `_db_read()` sets `PRAGMA query_only=ON`.
Every command clamps `limit` to `WS_MAX_PAGE_SIZE = 200` **server-side
before SQL execution**, regardless of the client-supplied value.

**Filters.** Every filter binds `?` placeholders. Column names are
hard-coded allowlists — no user input is ever interpolated into SQL.

**Cursor semantics.** `cursor` is the `id` of the last row returned by
the prior page. The server responds with rows whose `id < cursor`,
ordered `id DESC`. `next_cursor` in the response envelope is the
smallest `id` in the current page (feed it back as `cursor` for the next
page).

**Response envelope (D1 + D2):**
```json
{
  "rows":        [ { ...row... }, ... ],
  "next_cursor": 4523,        // or null when no more rows
  "page_size":   50,          // rows the server actually returned
  "capped":      false        // true if client-supplied limit was clamped
}
```

---

## severity mapping (anomaly_log)

`anomaly_log.severity` is stored as **numeric strings** `'0'..'4'`
(observed live 2026-07-13). The WS filter accepts EITHER the numeric
value or a human name alias; the DAO maps names → numbers at the
boundary before SQL execution.

| name       | number |
|------------|--------|
| `info`     | `'0'`  |
| `warning`  | `'1'`  |
| `error`    | `'2'`  |
| `critical` | `'3'`  |
| `fatal`    | `'4'`  |

`ura_activity_log.importance` is stored as **names**
(`info` / `notable` / `warning` / `critical` / `debug`) and is filtered
as-is (no mapping).

---

## `ura/logs/anomalies`

Paginated read of `anomaly_log`.

**Request schema:**
```jsonc
{
  "id": <int>,
  "type": "ura/logs/anomalies",
  "since":          "2026-07-13T00:00:00+00:00",   // optional ISO8601
  "until":          "2026-07-14T00:00:00+00:00",   // optional ISO8601
  "coordinator_id": "presence",                    // optional
  "severity":       "warning",                     // optional; name or '0'..'4'
  "anomaly_type":   "regime_shift",                // optional
  "resolved":       false,                         // optional
  "cursor":         4711,                          // optional; id from prior page
  "limit":          50,                            // optional; default 50, cap 200
  "columns":        ["id","timestamp","severity"]  // optional projection
}
```

**Allowlisted columns:** `id`, `timestamp`, `coordinator_id`, `scope`,
`metric_name`, `observed_value`, `expected_mean`, `expected_std`,
`z_score`, `severity`, `sample_size`, `house_state`, `context_json`,
`resolved`, `resolution_notes`, `anomaly_type`, `correlation_id`,
`recovery_at`, `person_id`, `room_id`, `entity_id`. Deprecated
`event_class` is NOT exposed.

**wscat example:**
```
wscat -c ws://homeassistant.local:8123/api/websocket
> {"type":"auth","access_token":"<LLAT>"}
> {"id":1,"type":"ura/logs/anomalies","severity":"warning","limit":5}
```

---

## `ura/logs/activity`

Paginated read of `ura_activity_log`.

**Request schema:**
```jsonc
{
  "id": <int>,
  "type": "ura/logs/activity",
  "since":       "2026-07-13T00:00:00+00:00", // optional ISO8601
  "until":       "2026-07-14T00:00:00+00:00", // optional ISO8601
  "coordinator": "presence",                  // optional
  "room":        "master_bedroom",            // optional
  "zone":        "1",                         // optional
  "importance":  "notable",                   // optional; name-valued
  "cursor":      4711,                        // optional
  "limit":       50,                          // optional; default 50, cap 200
  "columns":     ["timestamp","description"]  // optional projection
}
```

**Allowlisted columns:** `id`, `timestamp`, `coordinator`, `action`,
`room`, `zone`, `importance`, `description`, `details_json`,
`entity_id`.

**wscat example:**
```
> {"id":2,"type":"ura/logs/activity","coordinator":"presence","limit":10}
```

---

## `ura/logs/subscribe`

Live push on new activity/anomaly rows. Bridges the existing
`SIGNAL_ACTIVITY_LOGGED` dispatcher signal to the WS connection. No
polling, no per-event DB re-query, no writes.

**Request schema:**
```jsonc
{
  "id": <int>,
  "type": "ura/logs/subscribe",
  "streams":      ["anomalies","activity"], // optional; default both
  "coordinator":  "presence",               // optional server-side filter
  "min_severity": "warning"                 // optional; name or '0'..'4'
}
```

Server first responds with `{ "id": N, "type": "result", "success": true }`.
Subsequent events are pushed as
`{ "id": N, "type": "event", "event": { "event": <row-payload> } }`.

Disconnect (or standard `unsubscribe_events`-shaped teardown) removes the
dispatcher listener automatically via
`connection.subscriptions[msg_id]`.

**wscat example:**
```
> {"id":3,"type":"ura/logs/subscribe","streams":["activity"]}
< {"id":3,"type":"result","success":true,"result":null}
< {"id":3,"type":"event","event":{"event":{"coordinator":"presence",...}}}
```

---

## Constants (custom_components/universal_room_automation/const.py)

| Constant                              | Value              |
|---------------------------------------|--------------------|
| `WS_MAX_PAGE_SIZE`                    | `200` (server cap) |
| `WS_DEFAULT_PAGE_SIZE`                | `50`               |
| `WS_COMMAND_ANOMALIES`                | `ura/logs/anomalies` |
| `WS_COMMAND_ACTIVITY`                 | `ura/logs/activity`  |
| `WS_COMMAND_SUBSCRIBE`                | `ura/logs/subscribe` |
| `WS_ANOMALY_SEVERITY_NAME_TO_NUMBER`  | see mapping table  |
