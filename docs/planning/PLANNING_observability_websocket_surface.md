# PLANNING — Observability WebSocket Surface (PWA M4 Prerequisite)

**Cycle name:** observability-websocket-surface
**Target version:** TBD (next minor after v5.16.x)
**Tier:** Tier 2 (feature cycle + new surface, DB-adjacent read-only)
**Falsifiable load-bearing invariant:**
> The WS surface performs ZERO writes to the URA database, and no single command invocation can return more than `WS_MAX_PAGE_SIZE` rows (default 200) regardless of arguments or crafted input.
Reviewer B must falsify this by (a) grepping the surface for any code path that reaches `self._db()` (write queue) rather than `self._db_read()`, and (b) crafting a call with `limit=1_000_000` and confirming the server-side cap wins.

---

## 1. Context

**Problem.** URA's observability tables — `anomaly_log` (`database.py:752`, verified 2026-07-13) and `ura_activity_log` (`database.py:1163`, verified) — are populated but **unreachable by any UI**. Grep confirms URA registers ZERO `homeassistant.components.websocket_api.websocket_command` handlers today. The PWA M4 milestone (alerts + activity feeds) is blocked on this surface.

**Adjacent prior art already in-repo (REUSED, not new):**
- `UniversalRoomDatabase._db_read()` — `database.py:298`. Opens transient `aiosqlite` connection, sets `PRAGMA busy_timeout=30000` **and `PRAGMA query_only=ON`** — the query_only pragma is a load-bearing safety net that hard-fails any accidental write attempted through this path. This is the read primitive the new WS handlers MUST use.
- `UniversalRoomDatabase._db()` — `database.py:233`. Write-queue path. WS handlers MUST NOT touch this.
- `UniversalRoomDatabase.get_recent_activities(limit)` — `database.py:5550`. Existing minimal reader for `ura_activity_log` (no filters, no cursor). Shape guide for D2, but the new DAO needs filters + cursor pagination.
- `UniversalRoomDatabase.get_recent_optimization_findings(limit)` — `database.py:5251`. Same shape as D2's reader (illustrates the row→dict pattern with `aiosqlite.Row`).
- `SIGNAL_ACTIVITY_LOGGED` — `activity_logger.py:22`, `domain_coordinators/signals.py`. Dispatcher signal fired on every activity-log write; consumed today by sensors (`sensor.py:11172`, `12663`, `13161`, `13650`). This is the natural bridge for D3 (push subscription).
- Indexes present on `anomaly_log`: `idx_anomaly_timestamp`, `idx_anomaly_coordinator`, `idx_anomaly_scope`, `idx_anomaly_severity` (`database.py:769-776`). Good coverage for the D1 filters.
- Indexes present on `ura_activity_log`: `idx_activity_log_timestamp`, `idx_activity_log_coordinator` (composite: `coordinator, timestamp`) (`database.py:1175-1177`). Adequate for D2's primary filters; `room` and `zone` filters will scan within a coordinator+time-bound page, which is acceptable at cap size 200.

**No prior WS commands to conflict with.** Grep of `custom_components/universal_room_automation/**/*.py` for `websocket_api`, `websocket_command`, `async_register_command` returns only frontend bundle JS strings — zero Python matches. This is a greenfield surface within URA.

---

## 2. Institutional context verified

**Greps run (2026-07-13):**
- `rg -tpy 'websocket_api|websocket_command|async_register_command' custom_components/universal_room_automation` → **0 Python matches.** Confirms no existing WS commands to extend. NEW surface.
- `rg 'anomaly_log|ura_activity_log' custom_components/universal_room_automation/database.py` → schema at 752 / 1163, existing reader at 5550, writers at 4922 / 6089. Reader-side is thin (one function).
- `rg 'async def (get_|fetch_|read_|query_)' custom_components/universal_room_automation/database.py` → 60+ read DAOs; all go through `_db_read()`. Pattern established.
- `rg 'SIGNAL_ACTIVITY_LOGGED'` → dispatched by `activity_logger.py:120` on every write; consumed by sensors. **REUSED for D3.**
- `rg '^async def async_setup\b' custom_components/universal_room_automation/__init__.py` → **not present.** URA only has `async_setup_entry`. WS command registration must therefore happen either (a) at first-entry setup (guarded by a module-level "registered once" flag), or (b) by adding a real `async_setup(hass, config)` — see §5 registration lifecycle.

**Prior planning docs consulted:**
- `docs/ROADMAP_v11.md` (skim) — v3.12.0 AI Automation M4 diagnostics context (line 163); v4.7.x PWA-consumable surfaces (line 455). No prior PWA-M4 WS plan filed.
- `docs/planning/` (glob) — no existing `PLANNING_*websocket*` or `PLANNING_*observability*` docs. Confirmed greenfield.

**Memory bodies pulled:**
- `project_v4712_live.md` — Anomaly discriminator (`anomaly_type` column) is canonical post-v5.0; deprecated `event_class` was to be dropped. The D1 handler MUST expose and filter on `anomaly_type` (not `event_class`).
- `project_optimizer_db_write_flood_incident_2026_06_09.md` — Bug Class: SIGNAL_ACTIVITY_LOGGED fan-out combined with per-row DB writes = incident. D3 subscription design MUST NOT re-emit a write on any inbound message.

**Design docs read:**
- None per-coordinator; this cycle sits above domain coordinators (integration-level surface).

**Code locations surveyed end-to-end during scoping:**
- `custom_components/universal_room_automation/database.py:230-340` (write/read primitives)
- `custom_components/universal_room_automation/database.py:723-778` (anomaly_log schema + indexes)
- `custom_components/universal_room_automation/database.py:1161-1180` (ura_activity_log schema + indexes)
- `custom_components/universal_room_automation/database.py:5251-5567` (existing reader DAOs as shape guides)
- `custom_components/universal_room_automation/activity_logger.py` (SIGNAL_ACTIVITY_LOGGED dispatch)
- `custom_components/universal_room_automation/__init__.py:1-80, 1119` (no async_setup; only async_setup_entry)

**For every proposed addition — REUSED vs NEW:**
| Proposed | Status | Cite |
|---|---|---|
| `_db_read()` read primitive | REUSED | database.py:298 |
| `aiosqlite.Row` → dict pattern | REUSED | database.py:5271 |
| `SIGNAL_ACTIVITY_LOGGED` bridge for D3 | REUSED | signals.py; activity_logger.py:22 |
| `get_recent_activities` limit-only DAO | REUSED as shape; NEW filtered/paginated variant needed | database.py:5550 |
| `get_recent_optimization_findings` shape | REUSED as shape guide | database.py:5251 |
| New DAO `query_anomalies(...)` (filtered + cursor) | NEW — no existing reader with filters over `anomaly_log`; existing writers only | grep results |
| New DAO `query_activity(...)` (filtered + cursor) | NEW — `get_recent_activities` has no filters/cursor | database.py:5550 |
| `WS_MAX_PAGE_SIZE = 200` constant | NEW — no existing cap constant in const.py for WS surface | grep const.py: no `WS_` prefix hits |
| `websocket_api.websocket_command` handlers | NEW — no existing WS surface in URA | grep result |
| Module-level `_ws_commands_registered` guard | NEW — needed because setup happens per-entry | see §5 |

---

## 3. Deliverables

### D1: `ura/logs/anomalies` — paginated anomaly-log query

**WS command name:** `ura/logs/anomalies`
**Schema (voluptuous, validated by `@websocket_api.websocket_command`):**
```python
{
    vol.Required("type"): "ura/logs/anomalies",
    vol.Optional("since"): str,               # ISO8601; server rejects non-ISO
    vol.Optional("until"): str,               # ISO8601
    vol.Optional("coordinator_id"): str,
    vol.Optional("severity"): vol.In(["info","warning","critical"]),
    vol.Optional("anomaly_type"): str,        # v4.7.12 canonical column
    vol.Optional("resolved"): bool,
    vol.Optional("cursor"): int,              # last-seen id from prior page
    vol.Optional("limit"): vol.All(int, vol.Range(min=1, max=200)),
}
```

**DAO:** new `UniversalRoomDatabase.query_anomalies(**filters, cursor: int|None, limit: int) -> list[dict]` in `database.py`. MUST:
- Use `_db_read()` only.
- Build the SQL with **parameterized placeholders** for every filter (no f-string interpolation of user values). Column names are hard-coded (whitelist), not derived from input.
- Order by `id DESC` (monotonic autoincrement + timestamp-correlated, unlike `timestamp` which is TEXT ISO string — id ordering is cheaper and stable).
- Apply `WHERE id < :cursor` when `cursor` provided.
- Apply `LIMIT min(limit, WS_MAX_PAGE_SIZE)` — server-side cap wins over client value.
- Include `next_cursor = min(id in page)` in the response envelope so the PWA can fetch the next page.

**Response envelope:**
```json
{
  "rows": [ { "id": 4711, "timestamp": "...", "coordinator_id": "...", "scope": "...",
              "metric_name": "...", "observed_value": 1.2, "expected_mean": 0.9,
              "expected_std": 0.1, "z_score": 3.0, "severity": "warning",
              "sample_size": 42, "house_state": "home", "context_json": "...",
              "resolved": false, "resolution_notes": null, "anomaly_type": "regime_shift" } ],
  "next_cursor": 4523,
  "page_size": 200,
  "capped": false
}
```
`capped: true` when the requested `limit` was reduced by `WS_MAX_PAGE_SIZE`.

**Column set:** the 15 columns of `anomaly_log` (`database.py:753-767`) plus `anomaly_type` (added by v4.7.12 ALTER). Deprecated `event_class` is NOT exposed (per v5.0 drop plan).

### D2: `ura/logs/activity` — paginated activity-log query

**WS command name:** `ura/logs/activity`
**Schema:**
```python
{
    vol.Required("type"): "ura/logs/activity",
    vol.Optional("since"): str,
    vol.Optional("until"): str,
    vol.Optional("coordinator"): str,
    vol.Optional("room"): str,
    vol.Optional("zone"): str,
    vol.Optional("importance"): vol.In(["debug","info","warning","critical"]),
    vol.Optional("cursor"): int,
    vol.Optional("limit"): vol.All(int, vol.Range(min=1, max=200)),
}
```
**DAO:** new `query_activity(...)` mirroring D1's discipline (parameterized, `_db_read`, id-cursor, hard cap).
**Column set:** the 9 columns of `ura_activity_log` at `database.py:1163-1173`.
**Response envelope:** same shape as D1.
**Index note:** `idx_activity_log_coordinator(coordinator, timestamp)` covers coordinator+time queries; `room`/`zone` are unindexed but only scanned within the capped page. Acceptable at cap=200.

### D3: `ura/logs/subscribe` — live push (BUILD, not deferred)

**Justification for building not deferring:** the plumbing is trivial — `SIGNAL_ACTIVITY_LOGGED` already fires on every anomaly + activity write (`activity_logger.py:120`). Wiring a `@websocket_api.async_response` subscription handler that bridges dispatcher → connection.send_message is ~40 LoC and removes the PWA's polling loop.

**WS command name:** `ura/logs/subscribe`
**Schema:**
```python
{
    vol.Required("type"): "ura/logs/subscribe",
    vol.Optional("streams"): vol.All(list, [vol.In(["anomalies","activity"])]),
    # server-side filter on push (optional; PWA can also filter client-side):
    vol.Optional("coordinator_id"): str,
    vol.Optional("min_severity"): vol.In(["info","warning","critical"]),
}
```
**Implementation pattern:** register a dispatcher listener via `async_dispatcher_connect(hass, SIGNAL_ACTIVITY_LOGGED, _on_event)`. On disconnect (WS client goes away), the `connection.subscriptions[msg["id"]]` unsub callback (returned by `async_dispatcher_connect`) is invoked automatically by HA's websocket_api framework. **No new writes on inbound message** — invariant §1.
**Payload discipline:** the dispatched dict from `activity_logger.py:120` is already small (single row). Push it through unmodified; **do NOT re-query the DB per event** (that was the v5.0-v5.2 write-flood shape and would defeat the point).

If D3 is deferred at review: PWA should poll D1 + D2 at 15s cadence with `since=last_seen_timestamp`.

### D4: Docs

**File:** `docs/websocket_api.md` (new).
**Contents:** the three command schemas verbatim, response envelopes, cursor semantics ("cursor is the id of the last row you saw; server returns rows with `id < cursor`"), the hard cap constant, auth model (HA websocket auth inherited; no admin required), and a copy-pasteable `wscat` example per command.

---

## 4. Files to change

| File | Change |
|---|---|
| `custom_components/universal_room_automation/const.py` | ADD `WS_MAX_PAGE_SIZE = 200`, `WS_COMMAND_ANOMALIES = "ura/logs/anomalies"`, `WS_COMMAND_ACTIVITY = "ura/logs/activity"`, `WS_COMMAND_SUBSCRIBE = "ura/logs/subscribe"`. |
| `custom_components/universal_room_automation/websocket_api.py` (NEW) | The three `@websocket_api.websocket_command` handlers + registration function `async_register_ws_commands(hass)`. |
| `custom_components/universal_room_automation/database.py` | ADD `query_anomalies(...)` near line 5251 (alongside other read DAOs), ADD `query_activity(...)` near line 5550. |
| `custom_components/universal_room_automation/__init__.py` | In `async_setup_entry`, on first-entry setup only (guarded by a module-level `_WS_REGISTERED` flag), call `async_register_ws_commands(hass)`. See §5. |
| `docs/websocket_api.md` (NEW) | D4. |
| `quality/tests/test_websocket_api.py` (NEW) | Tests — see §7. |

---

## 5. Registration lifecycle

HA `websocket_api.async_register_command(hass, handler)` is **process-global** — registering the same command name twice raises. URA has multiple config entries (integration entry + zone entries + coordinator manager); `async_setup_entry` runs per-entry.

**Design:** module-level `_WS_REGISTERED: bool = False` guard in `websocket_api.py`. `async_register_ws_commands(hass)` is idempotent: if flag is set, return. Called from `async_setup_entry` after the integration-entry branch. On `async_unload_entry`, do **NOT** unregister — HA has no public API for that and the surface is read-only and cheap; commands survive reload of the config entry. Flag is process-scoped, so a full HA restart re-registers fresh.

**Alternative considered + rejected:** add a real `async_setup(hass, config)` to `__init__.py`. Cleaner conceptually, but adds a code path currently absent and would need CONFIG_SCHEMA plumbing. Guard-flag approach is a smaller diff and idempotent by construction.

---

## 6. Constraints + safety

- **Zero writes.** All handlers use `_db_read()` which sets `PRAGMA query_only=ON` — a hard-fail if any INSERT/UPDATE/DELETE leaks in. This is the load-bearing safety net for the invariant.
- **Hard row cap.** Every DAO clamps `limit` to `WS_MAX_PAGE_SIZE` server-side before SQL execution. Reviewer B must verify with `limit=10_000_000`.
- **Injection safety.** Every filter uses `?` placeholders. Column names hard-coded. Enum-valued filters (`severity`, `importance`) validated by voluptuous `vol.In(...)`. Date filters validated by `datetime.fromisoformat` in the DAO (reject unparseable → 400-equivalent WS error).
- **Auth.** Inherits HA websocket auth (user must be authenticated). **Not** `@websocket_api.require_admin` — anomaly/activity feeds are legitimate read-only user data; admin-gating would break the PWA for non-admin household users.
- **Volume.** Cap × command-rate × client-count is the exposure. At 200 rows × ~1KB/row × PWA-poll 15s = ~13KB/s per client, well within HA websocket capacity. D3 push avoids poll entirely.
- **No new event bus traffic.** D3 uses the existing `SIGNAL_ACTIVITY_LOGGED` — no new signals defined.

---

## 7. Tests (acceptance-driven)

`quality/tests/test_websocket_api.py`:
- `test_anomalies_command_returns_rows_matching_direct_read` — insert 3 rows via DAO, invoke WS handler, assert response rows equal a direct `_db_read` SELECT.
- `test_anomalies_command_respects_hard_cap` — insert 500 rows, request `limit=10000`, assert `len(rows) == 200`, `capped is True`.
- `test_anomalies_filters_are_parameterized` — filter with `coordinator_id="foo'; DROP TABLE anomaly_log;--"`, assert no rows AND table still exists (falsifies injection).
- `test_anomalies_cursor_pagination` — walk 3 pages of 100 rows via cursor, assert no overlap and no gaps.
- `test_activity_command_row_shape_matches_schema` — assert every column in `ura_activity_log` DDL (`database.py:1163`) is either in the response or explicitly excluded (documented).
- `test_ws_surface_performs_zero_writes` — patch `_db()` to raise; call each handler with a fuzzed input matrix; assert no exception (i.e. handlers never reach `_db()`).
- `test_subscribe_pushes_on_signal_activity_logged` — fire `SIGNAL_ACTIVITY_LOGGED` on the bus, assert handler enqueued a message on the mock connection.
- `test_subscribe_unsubscribes_on_disconnect` — simulate WS disconnect, assert dispatcher listener removed (no leaked subs).
- `test_ws_commands_registered_once_across_multiple_entries` — call `async_setup_entry` twice, assert `async_register_command` invoked only once (guard flag works).

---

## 8. Acceptance criteria (per deliverable)

### D1: anomalies WS command
- **Verify:** WS command registered at `ura/logs/anomalies` (call `list_websocket_commands` fixture — appears in registry).
- **Verify:** `limit=10000` returns ≤200 rows with `capped: true`.
- **Verify:** SQL-injection payload in `coordinator_id` returns [] and does not alter the DB.
- **Test:** functions listed in §7 pass.
- **Live:** post-deploy, connect via `wscat` to `ws://homeassistant.local:8123/api/websocket`, authenticate, send `{"id":1,"type":"ura/logs/anomalies","limit":5}`, receive up to 5 rows; cross-check equal to `sqlite3 universal_room_automation.db 'SELECT * FROM anomaly_log ORDER BY id DESC LIMIT 5;'`.

### D2: activity WS command
- **Verify:** same shape as D1 (registered, capped, parameterized).
- **Test:** §7 tests pass.
- **Live:** wscat sends `{"id":2,"type":"ura/logs/activity","coordinator":"presence","limit":10}`; rows returned match direct sqlite SELECT with the same WHERE.

### D3: subscribe push
- **Verify:** subscribe returns a `result` frame with success, then subsequent `event` frames on new activity/anomaly writes.
- **Verify:** disconnect removes the dispatcher listener (no growth in dispatcher signal listener count).
- **Live:** open wscat, subscribe, trigger a test activity write from a URA button; observe the pushed event within 1s.

### D4: docs
- **Verify:** `docs/websocket_api.md` exists and includes all three schemas + a wscat example per command.
- **Live:** PWA team confirms they can implement M4 against the doc without asking clarifying questions (async check).

---

## 9. Review plan

**Tier 2 — 2 framings, parallel:**

- **Reviewer A (correctness + pagination + injection safety):**
  Verify every filter is parameterized. Verify cursor + `id DESC` correctness under interleaved inserts. Verify voluptuous enum guards. Verify the `capped` flag matches the server-side clamp. Try `since` = malformed ISO, `limit` = -1, 0, "abc", 2**31, negative cursor. Confirm `query_only=ON` is in effect for the read connection at the moment the SQL runs.
- **Reviewer B (lifecycle + auth + volume + invariant):**
  Falsify the invariant: prove there is NO code path in `websocket_api.py` that reaches `_db()` or any `INSERT/UPDATE/DELETE`. Craft `limit=1_000_000` and verify server-side cap wins. Verify the registration guard is race-free across concurrent first-time entry setups (two entries adding simultaneously). Verify D3 unsubscribe path on disconnect. Verify no admin-gating regression for non-admin users. Verify no new `_db()` submissions on inbound messages (write-flood incident lesson).

**Pre-review baseline tag:** `git tag pre-review-v<version> -m "Pre-review baseline for observability WS surface"`.

**Live validation (Review 3):** post-restart wscat runs above (D1/D2/D3 Live rows). Write-back into `README_v<version>.md` as PASS/FAIL table with observed row counts and cross-check values.

---

## 10. What is explicitly OUT of scope

- Writes of any kind, including `resolve anomaly` — read-only surface. A future `ura/logs/resolve` write command is a separate cycle.
- Historical export / bulk download — capped page size is the contract.
- Auth beyond HA's default — no per-user row filtering, no per-room ACLs. If the household needs those, that's a downstream cycle.
- Frontend / PWA code — this cycle ships the URA-side contract only.

---

## 11. Open operator questions

1. **Should D3 (subscribe push) be in v1, or ship D1+D2 first and add D3 next release?** Plan currently says build D3 (~40 LoC, dispatcher already in place). Confirm.
2. **Cap value.** Plan sets `WS_MAX_PAGE_SIZE = 200`. PWA M4 alerts feed and activity feed — is a 200-row page enough to fill the initial dashboard view, or should we set 500?
3. **`anomaly_type` filter values.** Do we want a `vol.In([...])` whitelist of anomaly types (safer, but couples this cycle to the current enum) or free-string (looser, but tolerates future emitter additions)? Plan currently says free-string.
4. **Admin-only or user-level?** Plan recommends user-level (household PWA users are typically not admin). Confirm.
5. **Non-integration entries (zone / coordinator-manager).** Guard flag ensures single registration regardless of which entry sets up first. OK to leave the trigger site in `async_setup_entry` rather than adding an `async_setup(hass, config)`?
