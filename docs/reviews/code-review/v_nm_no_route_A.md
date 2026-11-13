# Review A (correctness + edge cases): fix/nm-no-route (NM-NO-CHANNEL-FIRED-1)

Branch HEAD df8e323a. Merge-base with develop = 2d49a262 (develop has since moved to a9d2bcb5; diff taken three-dot `develop...HEAD`). Evidence doc: `docs/planning/AUDIT_nm_no_channel_fired_2026_11_13.md`. Ran only `quality/tests/test_nm_no_channel_fired.py` (18 passed).

## Findings

| # | SEV | Site | Finding | Bug class |
|---|---|---|---|---|
| A1 | MEDIUM | `notification_manager.py` `_record`/audit hook (`bucket_outcome == NM_BUCKET_NO_CHANNEL_FIRED`, ~5479) + `_maybe_fire_no_route_tripwire` | Trip-wire and `delivery_rate` count EVERY `no_channel_fired` row, including **immediate-pref** recipients whose gates are above the alert severity. That is configured policy (gate HIGH means "don't send me MEDIUM"), not a routing hole. Repro (legal config, portability): a second person with `delivery_pref=immediate`, all gates HIGH; ~43 sub-HIGH alerts/day (the live rate in the audit) -> >=20 no_channel_fired/24h -> a daily HIGH "URA alerts reaching nobody" alert and `delivery_rate` near 0. The audit's proposal (c) scoped the trip-wire to severity >= MEDIUM; the build counts LOW too. In THIS house (single digest-pref recipient) it does not fire post-fix, so not a live regression. Fix: count only digest-pref recipients (the real hole), or label immediate-pref sub-gate drops with a distinct outcome (e.g. `below_gate`). | #63 coincidental equality (policy drop vs routing hole share one label) |
| A2 | LOW | `notification_manager.py:2176-2182` | Fallback is skipped when ANY channel is muted for the recipient, including a channel that is not a digest channel. Repro: digest-pref person, digest_channels [whatsapp, imessage], pushover muted 30 min, MEDIUM alert -> no fallback row -> `no_channel_fired` (alert lost, the exact symptom this cycle fixes). Suggest: skip only if all of the recipient's `digest_channels` are muted. | edge case |
| A3 | LOW | `_route_branch_label` (~5326) vs fallback guard `_matrix_branch == "legacy_fallback"` | A sparse matrix with no row for this severity is labelled `matrix_default`, but `_route_for_recipient` routes it through legacy. So matrix `{CRITICAL: {...}}` + MEDIUM alert + gates HIGH -> no fallback -> dropped. A missing matrix row is not explicit silence. Documented label semantics (A-MED-2) make this a design choice; flag only. | #53-adjacent |
| A4 | LOW | `notification_manager.py` `_fire_digest` (~5624 / ~5658) | `_last_digest_flush` is stamped with a fresh `utcnow()` AFTER `_deliver_digest` awaits network sends. A no-route row written between the count query and that stamp is counted in neither flush. Capture `now` before the count query and stamp that local. | capture-before-await |
| A5 | LOW | `quality/tests/conftest_db.py:114,126` | New regex now also matches `energy_midnight_snapshot`'s split f-string; the pre-existing 2000-char backward tuple window then bleeds the adjacent `energy_daily` tuple list in. Verified by running old vs new extractor over every table: `energy_midnight_snapshot` gains 6 spurious columns (`predicted_consumption_kwh`, `avg_temperature`, `prediction_error_pct`, `adjustment_factor`, `predicted_consumption_source`, `billing_source`) on top of its 3 real ones. `notification_log` (+6 real) and `person_entry_exit_events` (+1 real) are correct. Fixture schema is now a superset of prod for that table. Harmless to current tests, but it breaks the "fixture = production schema" guarantee. Fix: stop the backward walk at the nearest `for ... in [` list (or the previous `ALTER TABLE`). | fixture fidelity |

## Cleared (holds because)

- Fallback conditions: only `effective_pref == digest` (HIGH/CRITICAL forced immediate at ~1963, so fallback is sub-HIGH only), `not _digest_queued` (entry-reset per recipient at ~2042, set at all 4 channel queue sites), DB present, legacy branch. Hazard override and matrix are excluded via the label. Correct.
- Fallback row reaches the digest: `get_pending_digest` (`database.py:4925`) does not filter by channel; `mark_digest_delivered` sweeps it; the CRITICAL-only readers (ack/cooldown) never see it (sub-HIGH). Channel label `digest` is not in any channel-keyed reader.
- Audit outcome: `accepted` > `digest_queued` > `no_channel_fired`, with `delivered` still `1 if fired else 0`. A digest-queued recipient is no longer counted as no-route. Correct.
- Heartbeat: `count_no_route_since` filters `message='[audit]'`, outcome, `dry_run=0`, person. Timestamps are `utcnow().isoformat()` on both sides (`database.py:4821`), so the string compare is valid. Restart fallback window is 24 h. Non-heartbeat path can't produce an empty body before the append (pending or opt_section is non-empty there). Singular/plural is right.
- delivery_rate: denominator `attempts + no_route`, zero guard kept, dry-run rows excluded at the increment. Units are mixed (per-channel attempts vs per-recipient no-routes), which is acceptable for a health percentage.
- Trip-wire: kill switch `<= 0`; window prune is strict `>`; threshold `>=`; cooldown = window; the stamp is set before the inner `async_notify`, so the nested call's own `_maybe_fire` returns at the cooldown check (no recursion). Anomaly write is try/except-wrapped. The HIGH alert reaches companion (gate HIGH) in the live config. If every gate is CRITICAL, the trip-wire alert itself no-routes. That limit is inherent and acceptable.
- None handling: `count_no_route_since` returns 0 on error; `_last_digest_flush.get` falls back.

## Verdict

**SHIP** with recommended follow-ups. No CRITICAL/HIGH. A1 (MEDIUM) is not live in this house's config, but it should be fixed in-cycle per the fix-LOWs policy before the trip-wire is relied on across installs. A2, A4 and A5 are small and worth folding into the same fix-up.

| SEV | Found |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 1 |
| LOW | 4 |

## Fix-up (2026-11-13)

| # | Disposition | Change | Test | Drill (neuter -> RED) |
|---|---|---|---|---|
| A1 | FIXED | `_emit_audit_row(routing_hole=...)`; the call site passes `not (effective_pref == IMMEDIATE and not _router_allowed)`. An immediate-pref recipient whose router allowed nothing (gates above severity, mutes, explicit matrix) is its own policy: the audit row stays `no_channel_fired`, but `_no_route_count`/`delivery_rate` and the trip-wire are not fed. The trip-wire deque only takes MEDIUM+; LOW holes still count toward `delivery_rate`. | `test_immediate_pref_policy_drop_not_counted`, `test_immediate_pref_router_allowed_but_unsent_is_a_hole`, `test_low_no_route_counts_rate_but_not_tripwire` | call-site `routing_hole=True` RED; `not _router_allowed` -> True RED; hook `and routing_hole` -> True RED; MEDIUM+ guard -> True RED |
| A2 | FIXED | The fallback is skipped only when EVERY digest channel is muted. With an empty digest-channel selection, the check covers all known channels (the legacy first-wins chain). There is no global-mute concept in NM; the all-channels case covers it. | `test_non_digest_channel_mute_does_not_block_fallback`, `test_one_of_two_digest_channels_muted_still_queues`, `test_active_mute_is_respected` (now mutes both digest channels) | revert to `any(... NM_CHANNELS_KNOWN)` RED; `all`->`any` RED; set -> KNOWN RED |
| A3 | LEFT | Documented design choice (sparse matrix row is labelled `matrix_default`). | - | - |
| A4 / B1 | FIXED | `_flush_now` is captured before `count_no_route_since`; the window fallback and the `_last_digest_flush` stamp both use it. | `test_no_route_during_delivery_lands_in_next_flush` | stamp `utcnow()` after delivery RED |
| A5 | FIXED | `conftest_db` f-string tuple walk is bounded at the previous `ALTER TABLE` in the window. Whole-table extractor diff vs develop: `notification_log` +6 and `person_entry_exit_events` +1 (as intended). Two further changes are both corrections. `energy_midnight_snapshot` now gains only its 3 REAL columns (`counter_import_last`, `counter_export_last`, `billing_source_today`, database.py ~2264); they were missing before because the old regex did not match the split f-string, and the 6 energy_daily bleed columns are gone. `ac_reset_state` LOSES a pre-existing spurious `settled_reason`, which had bled from the adjacent `ac_ramp_events` tuple. | `TestSchemaExtractorNoBleed` (3 tests) | drop the bound -> 2 RED |
| B2 | LEFT | Restart re-report is display-only; accepted. | - | - |
| B3 | NOT FIXED | Pre-existing mark race; operator to card. | - | - |

Tests: the cycle file (27) plus NM siblings and every `conftest_db`/`real_schema_db` consumer: 734 + 227 passed. All drills restored; `git status` was clean apart from the intended edits.
