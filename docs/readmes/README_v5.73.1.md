# URA v5.73.1 — CRITICAL re-pages carry their image (NM-REPAGE-IMG-1)

Tier-1 hotfix. Operator ruling (2026-08-12): *"Intermittency on correctness is a bug"* — an
image-bearing CRITICAL alert must carry its image on **every** page, not just the first. The
unack-CRITICAL 5-minute re-page loop previously resent text only, even though the snapshot file
persisted on disk.

## Change (~35 LoC production)

- `_enter_alerting()` stashes `snapshot_url` / `snapshot_path` on `_active_alert_data`.
- `_repeat_alert()` re-attaches them on all four transports (Pushover `attachment_url`, Companion
  `data.image`, WhatsApp `media_path`/`media_url`, iMessage BB-v0.6 `attachment`/`media_url`).
- File-existence check runs off-loop (`async_add_executor_job(os.path.exists, …)`); missing file →
  DEBUG log, drop path only, re-page proceeds text-plus-url or text-only. Never blocks or crashes
  the re-page.
- Persistence round-trip carries the snapshot fields **plus an alert-identity stamp**
  (`active_alert_snapshot_created_at`): a post-restart recovered unack CRITICAL re-attaches its
  image only when identities match; mismatch or legacy blob → skip merge (prevents a stale
  snapshot from a previously-acked alert grafting onto a different recovered alert).

## Review

1 adversarial review (Tier 1): **SHIP**, 0 CRIT/HIGH, 2 LOW — both fixed in-cycle (the two bullets
above: executor offload, identity check). Wire-in anchor drilled twice (pre- and post-fix-up):
transport-kwarg neuter reds `test_repage_reattaches_snapshot_on_whatsapp_and_imessage`
(1 failed / 4 passed), restored green. Suite: 8767 passed, 21 pre-existing failures (byte-identical
set to baseline), 0 new.

## Acceptance criteria

- **Test:** `quality/tests/test_nm_repage_image.py` (5 tests: re-attach both channels, missing-file
  fallback, wire-in anchor, identity-match merge, identity-mismatch/legacy skip).
- **Live:** loads, zero URA errors post-restart.
- **Live (organic):** next unacknowledged CRITICAL security alert — the 5-min re-pages carry the
  same photo as the original page on WhatsApp AND iMessage (counts alongside the FRIGATE-RETIRE-1
  Gate-1 window; a ghost-free F2 era may make unack CRITICALs rare — criterion stays open until one
  occurs organically).

## Live Validation

### Validated 2026-08-12 (v5.73.1 boot, 15:02 CT)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| L1 | Loads, zero URA errors | **PASS** | error_log search `universal_room` post-restart: WARNINGs only, all boot-transient (rooms holding state 60s); ERRORs in window all third-party (SPAN/Shelly/Denon boot noise) |
| L2 | HACS installed = available | **PASS** | HACS: installed_version v5.73.1 = available_version v5.73.1, pending_update false |
| L3 | Re-page carries image, both channels | **PASS on WhatsApp (organic 2026-08-14); FAIL on iMessage** | Next unacknowledged CRITICAL — 5-min re-pages must carry the original photo on WhatsApp + iMessage. In-suite the wire-in is mutation-anchored twice (transport-kwarg neuter → 1 named test red, restored green) |
| L4 | No stale-snapshot bleed across restart | **In-suite only** | Requires a crash-ordered restart between DB-ack and persistence save to occur live — proven by identity-mismatch + legacy-blob tests instead |

Context: deployed same day as the FRIGATE-RETIRE-1 window-open; L3's organic case counts within
the Gate-1 observation window (a ghost-free F2 era may make unack CRITICALs rarer — criterion
stays open until one occurs).
