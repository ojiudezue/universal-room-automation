# DRAFT: NM-SECURITY-IMAGE-SUBHIGH-NO-ROUTE-1 (sub-HIGH perimeter alerts with a photo reached nobody)

Unversioned draft; it gets a version number when it is batched into a release.

## Problem

`async_notify` (`domain_coordinators/notification_manager.py`) computes
`_force_immediate_for_security_image` (`hazard_type in NM_SECURITY_HAZARDS and bool(snapshot_path or snapshot_url)`, ~1704-1707).
In the per-recipient loop (~2075-2081) this forces `effective_pref = IMMEDIATE`, including for a digest-preference
recipient. With the live channel gates (companion HIGH, Pushover, WhatsApp and iMessage CRITICAL), a MEDIUM or LOW
alert fires nothing. The NM-NO-CHANNEL-FIRED-1 digest fallback (~2291) required `effective_pref == DIGEST`, so it was
skipped as well. The audit row came out `bucket_outcome='no_channel_fired'` and nobody got the alert. Live data showed
6 `perimeter_alert` LOW rows on 11-23 and 49 since 11-14.

## Change

`notification_manager.py`, just before the fallback block: a new local, `_image_forced_from_digest`, is true when all of these hold:
- the recipient's own `delivery_pref == NM_DELIVERY_DIGEST`
- `_force_immediate_for_security_image`
- severity is not CRITICAL or HIGH, so the image rule was the only thing forcing IMMEDIATE
- `not fired_for_person`. This is the existing per-recipient list of channels that actually sent, the same variable the audit row uses for `accepted`.

The fallback condition now begins `(effective_pref == DIGEST or _image_forced_from_digest)`. All its other clauses are
unchanged: `not _digest_queued`, `database`, `_matrix_branch == "legacy_fallback"`, and not every digest channel muted.
It reuses `NM_DIGEST_FALLBACK_CHANNEL`. No new knobs.

Unchanged: HIGH/CRITICAL with a photo is still sent immediately with the photo. A recipient whose own preference is
immediate is still logged as an honest `no_channel_fired`.

Not addressed (out of scope): during quiet hours, a digest-preference recipient whose alert was forced IMMEDIATE by the
image rule still hits the DND `continue` (~2098-2130, `dnd_suppressed_security_image`) before this fallback runs.

## Tests

`quality/tests/test_nm_no_channel_fired.py::TestSecurityImageSubHighFallback`:
- `test_subhigh_snapshot_digest_pref_queues_digest_row[MEDIUM|LOW]`: one `digest` row, audit `digest_queued`
- `test_high_snapshot_sends_immediately_no_digest_row`: companion gets the snapshot, no digest row, `accepted`
- `test_subhigh_snapshot_channel_fired_no_digest_row`: a channel fired, so no fallback
- `test_immediate_pref_subhigh_snapshot_unchanged`: no row, `no_channel_fired`
- `test_all_digest_channels_muted_no_row`
- `test_explicit_matrix_silence_respected`
- `test_high_snapshot_no_route_keeps_preexisting_behaviour`: HIGH is forced by severity, not by the image rule, so
  this card does not change it

Mutation drills (each neuters one conjunct, then the file is restored): dropping `or _image_forced_from_digest` turns
both MEDIUM and LOW parametrisations of the digest-row test RED. Dropping `not fired_for_person` turns
channel_fired_no_digest_row RED. Replacing the `delivery_pref` conjunct with True turns immediate_pref_unchanged RED.
Dropping the severity conjunct turns high_snapshot_no_route RED.

## Live acceptance (post-deploy)

- `notification_log` audit rows for `perimeter_alert` with `bucket_outcome='no_channel_fired'` = 0 after the restart,
  for digest-preference recipients.
- New LOW/MEDIUM perimeter alerts appear as `channel='digest'`, `delivered=0` rows, then as `delivered=2` after the
  next digest flush. Their audit rows show `digest_queued`.

## Known limits (from reviews A and B, 2026-11-24, both SHIP)

- The digest line is text only: digest rows do not store the snapshot, so the photo is lost for these alerts. Text in
  the digest beats reaching nobody.
- The fallback also covers a channel that was tried and failed (for example a WhatsApp send that errored writes a
  `delivered=-1` row and nothing in `fired_for_person`), so that recipient gets the digest row too. `get_pending_digest`
  reads only `delivered = 0`, so nothing is sent twice. No test pins this case.
- Quiet hours: the DND skip (`notification_manager.py` ~2098-2130) runs before the fallback, so a sub-HIGH image alert
  for a digest-preference recipient during quiet hours is still dropped. 0 occurrences in the last 14 days (every
  overnight perimeter audit row was HIGH/CRITICAL); tracked on the card as a residual.
- A caller-supplied route reason (for example `enriched_llmvision`) overwrites the image-forced label in the audit row,
  so analytics cannot tell which `digest_queued` rows came from this fix (pre-existing).
