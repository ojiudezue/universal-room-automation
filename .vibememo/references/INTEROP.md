# VibeMemo Interop Protocol

> How multiple tools coordinate when writing to `.vibememo/`.

## Problem

A developer might have Claude Code running in a terminal and other tools watching files. Without coordination, they'll create duplicate entries, corrupt the index, or produce conflicting narratives.

## Design Principles

1. **Last writer wins is unacceptable.** The tool with the richest context should win.
2. **Append-only is safe.** Multiple tools can append entries. Only one should update narratives.
3. **File-based coordination.** No external services, no databases. Everything in `.vibememo/`.
4. **Graceful degradation.** If locking fails, entries are still captured (possibly duplicated). Dedup later.

## Session Ownership

Only one tool "owns" a session at a time.

### Session file: `.vibememo/.session`

```json
{
  "session_id": "claude_20260415_143022_a7f2",
  "tool": "claude_code",
  "pid": 12345,
  "started_at": "2026-04-15T14:30:22Z",
  "last_heartbeat": "2026-04-15T15:02:00Z"
}
```

**Rules:**
- The first tool to start creates `.vibememo/.session`
- Other tools read it and operate as **secondary writers**
- Session owner updates narratives at consistency checkpoints
- Secondary writers can append entries but do NOT update narratives
- If `last_heartbeat` is >5 minutes old, the session is considered abandoned and can be claimed

## File Locking

### Lock file: `.vibememo/.lock`

Before writing to `index.json` or any entry file:

1. Check if `.vibememo/.lock` exists
2. If it exists and `acquired_at` is >30 seconds old, consider it stale and delete it
3. If it exists and is fresh, wait 1 second and retry (max 5 retries)
4. If lock is available, write to `.lock.tmp`, rename to `.lock` (atomic)
5. Perform the write operation
6. Delete `.lock`

## Gitignore

These files should be in `.gitignore`:

```
.lock
.lock.tmp
.session
.events
.events.*
.vibememorc
```
