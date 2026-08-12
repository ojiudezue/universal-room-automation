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

(prospective — to be replaced with the Validated table post-restart)
- Zero URA errors post-restart; NM device + entities present.
- Organic: first unack-CRITICAL re-page carries the image on both channels.
