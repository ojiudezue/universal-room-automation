# URA v5.63.0 — SNAP-1: at-detection local-file snapshots

**Problem (both verified live):** perimeter alerts arrived with **no photo**, and any photo would
have been **stale**.

1. **Delivery.** NM passed `media_url` — a URL the WhatsApp integration must fetch — instead of
   `media_path`, a local file it reads. The operator's own working doorbell automation uses
   `media_path`; URA's URL form required absolute + externally-fetchable + auth-exempt and silently
   dropped the image.
2. **Staleness.** Capture fell back to the camera's live `entity_picture` plus an offset delay — a
   grab taken *after* the event. Operator: *"a shot from when it happened/fired, not seconds later
   when code runs for alerting."*

**Tier 2-DB.** Three framing-disjoint reviews found **7 HIGH** (two of them security) plus a failed
core premise. Review record: `docs/reviews/code-review/v5.63.0_snap1.md`.

## What shipped

- **Capture at the rising edge.** `_maybe_start_edge_capture` fires from `_on_perimeter_event` and
  `_on_vehicle_state_change` *before* alert-hours, egress, cooldown, in-flight, severity, or linker
  work. The handler consumes the buffered result inside a budget. Deduped by collapsed camera-key,
  TTL-bounded, LRU-capped, cancelled on teardown; the edge→consume delta is recorded on the ledger
  so the at-detection property is **measurable**, not asserted.
- **Local-file delivery** — `media_path` on WhatsApp (photos now actually arrive). Kill switch
  `PERIMETER_SNAPSHOT_KILL_LEGACY_URL` restores the byte-identical legacy URL payload on every channel.
- **Frigate event snapshots**, instance-scoped — resolves the latent bug where any camera on the
  second Frigate host could never produce a snapshot (subsumes FRIG2SNAP-1). Instance derived from
  the MQTT `client_id`; cache invalidated on 404 so a camera migrating hosts recovers.
- **Real precedence** — `PERIMETER_SNAPSHOT_ENGINE_PRECEDENCE` is now *iterated by name*; it was
  membership checks in fixed order, so reordering had no effect (my spec's error).
- **`/media/ura/snapshots`**, auth-gated, asserted outside the web-served `/config/www` using
  `realpath` on both sides; 168h age-primary retention + count backstop, debounced prune + 6h sweep,
  all I/O off the event loop.
- **Bounded capture** — one `asyncio.wait_for` budget (3s) plus an explicit aiohttp timeout, so a
  stalled camera or wedged Frigate can no longer delay the alert or hold the in-flight guard.

## Findings worth recording

| Sev | Finding | Fixed |
|---|---|---|
| HIGH | **The core premise was false** — capture ran at handler entry, after cooldown/severity/linker awaits, i.e. exactly the "seconds later" the cycle existed to eliminate | ✅ moved to the rising edge |
| HIGH | **Path traversal** — the Frigate `event_id` went from the MQTT bus into a filename unsanitized; `os.path.join` does not stop `../` and there was no containment check | ✅ sanitized at ingest + realpath containment before every write |
| HIGH | **Privacy guard bypassable** — the `/config/www` check used `abspath`, which does not resolve symlinks | ✅ `realpath` both sides, after `makedirs` |
| HIGH | **Wrong-image risk** — default (non-instance) Frigate URL tried first while `armcrest*` exists on both hosts, so an alert could carry another camera's photo | ✅ instance-scoped only on multi-instance installs |
| HIGH ×2 | Unbounded `camera.snapshot` and aiohttp GET on the alert critical path | ✅ single capture budget + client timeout |
| HIGH | **Vehicle dispatch was never wired into SNAP-1** — deep-night vehicle alerts kept the legacy URL-only shape | ✅ threaded |
| HIGH | Kill-switch test was **coincidentally green** (fixture made both engines return None anyway); the outer guard was hollow | ✅ capture-capable fixture; outer guard collapsed so each site is independently drilled |

## Known limitation

**iMessage photos are not possible.** Verified: the installed BlueBubbles integration exposes no
attachment field (`bluebubbles/__init__.py:49-90` POSTs only `{addresses, message, method}`). The
extra key is harmless — the service is registered without a schema — but iMessage remains text-only
until BB gains attachment support or a direct server-API upload path is added.
Follow-ups: `SNAP-1-followup-bluebubbles-attachment`, `SNAP-1-followup-protect-thumb` (Protect's
thumbnail does not exist yet at the moment the sensor fires — the integration buffers events behind
a wait-for-thumbnail timer, so the tier is a documented fall-through, not an oversight).

## Orchestrator-verified drills

| Drill | Result |
|---|---|
| Remove the edge-start call from `_on_perimeter_event` | **RED** — *was GREEN before the F10 fix; this is what caught the hollow wiring anchor* |
| Same for the vehicle callback | RED (also hollow before F10) |
| Keep the call, make `_maybe_start_edge_capture` a no-op | RED ×4 |
| Kill switch: inner guard, then edge-start guard, drilled separately | RED each |
| `media_path` detached / stale-path return / wrong engine tag / prune age / oldest-first | RED each |

## Acceptance criteria

- **Live:** a real perimeter alert arrives **with a photo on WhatsApp**.
- **Live:** the file lands under `/media/ura/snapshots`; nothing new appears under `/config/www`.
- **Live:** a frigate2-hosted camera resolves a snapshot (impossible before).
- **Live:** ledger shows a small `edge_to_consume_ms` — the at-detection property, measured.
- **Live:** files older than 168h are pruned.

## Live Validation

(prospective — replaced post-restart)
