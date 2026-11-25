# v5.108.40: batched release (room rules screens, sub-HIGH photo alerts reach the digest, music test leak)

Released 2026-11-24. One restart; the operator cleared shipping on 2026-11-24 ~18:55. PATCH bump.

Cards: AI-ROOM-RULES-TRUST-REPAIR-1, NM-SECURITY-IMAGE-SUBHIGH-NO-ROUTE-1, TEST-MUSIC-SYSMODULES-LEAK-1.

## 1. Room rules screens (AI-ROOM-RULES-TRUST-REPAIR-1, the three screen picks deferred from v5.108.39)

These use the operator's default picks (keep / B / B), unvetoed since 11-20.

1. **"When" stays on Describe a rule.** There is no code change because the dropdown was already there. You pick when
   the rule runs, and the model writes only what it does. Two tests now pin this.
2. **Rule writing model has its own menu item.** The Coordinator Manager options menu lists "Rule writing model"
   after Optimizer (`async_step_room_rules_model`), and the Optimizer AI settings no longer include it. The stored
   setting is the same (`room_rules_ai_task_entity`), so your choice carries over without a migration. Saving the
   Optimizer form keeps it, and it stays reload-suppressed.
3. **Check your rule is a plain menu.** The menu has two choices, "Save" and "Change the wording". When room rules are
   off in the room, "Save and turn on room rules here" comes first, and plain "Save" leaves the switch off.
   "Change the wording" saves nothing. It returns a described rule to Describe a rule with your text kept, and a
   Run-an-automation rule to the automation step.

Review (Tier 1, framing A): SHIP, with two LOW notes and no change made:
- The "room rules are off" note repeats above the turn-on choice.
- A blank model falls back to HA's default model, as before.

The builder ran 10 per-site mutation drills, and every one turned its named test RED.

## 2. Sub-HIGH outdoor alerts with a photo reach the digest (NM-SECURITY-IMAGE-SUBHIGH-NO-ROUTE-1)

**Problem.** An outdoor person alert that carries a photo was forced to "send now". The phone and message channels
only accept HIGH or CRITICAL, so a MEDIUM or LOW alert sent nothing. The v5.108.17 digest fallback did not apply
either, because it required the delivery choice to be "digest". The alert reached nobody: 49 `no_channel_fired`
rows from 11-14 to 11-21, and 6 on 11-23.

**Change.** `notification_manager.py` (~2297-2307) adds `_image_forced_from_digest`, which is true when all of these
hold:
- the recipient's own preference is digest;
- the photo rule forced IMMEDIATE;
- the severity is below HIGH;
- nothing fired for that recipient.

When it is true, the existing fallback writes the digest row. Every other guard still applies (no double queue, the
matrix branch, digest channel mutes). There are no new knobs. HIGH and CRITICAL alerts with a photo still go out
immediately with the photo.

**Known limits** (reviews A and B, both SHIP):
- The digest line is text only, so these alerts lose their photo.
- A channel that was tried and failed also triggers the fallback. Only `delivered=0` rows are read, so nothing is sent
  twice.
- In quiet hours, the DND skip runs before the fallback. This happened 0 times in 14 days and stays as a residual on
  the card.

**Tests.** `test_nm_no_channel_fired.py::TestSecurityImageSubHighFallback` has 8 tests, and 4 builder mutation drills
turned RED. Orchestrator re-drill on 2026-11-24: neutering `or _image_forced_from_digest` turned both MEDIUM and LOW
digest-row tests RED. After the line was restored, 38 passed and the tree was clean.

## 3. Test-only: music-following test no longer leaks stub modules (TEST-MUSIC-SYSMODULES-LEAK-1)

`test_music_following_coordinator.py` replaced `domain_coordinators.base` (and siblings) in `sys.modules` at import
and never restored them, which broke class-identity checks in later test files. Its approach:
- it snapshots every touched key before the swap and restores them after the imports;
- a module-scoped autouse fixture re-installs the stubs only while this file runs;
- two guard tests check by identity marker.

A mutation drill (neutering the restore) turned both guards RED. Production code is unchanged.

## Tests

Each branch was run on its own against develop with a full-suite name-diff (`scripts/suite_namediff.py`), and each
showed 0 NEW and 0 GONE:
- music: 23849 passed;
- alerts: 23855 passed;
- room-rules: 23854 passed.

The merged develop (745fa8e8d) had a full name-diff against 4bc0fcbed before deploy: 23864 passed, 0 failed,
0 NEW, 0 GONE.

## Live validation (prospective)

- **Coordinator Manager > Configure:**
  - the menu has "Rule writing model";
  - it opens with the current value (expect `ai_task.claude_ai_task`);
  - the Optimizer LLM section has no model field.
- **A room > Room rules > Run an automation > Check your rule:**
  - it shows exactly Save and Change the wording;
  - Save adds the rule to Your rules.
- **End-to-end run.** One Run-an-automation rule fires on its "When" and logs a decision row. This uses no Claude
  call, because Claude AI Task is locked until 12-01.
- **Model change without reload.** Changing only the rule writing model does not reload any room entries.
- **Alert audit rows.** After the restart, `notification_log` has no `bucket_outcome='no_channel_fired'` rows for
  `perimeter_alert` digest-preference recipients. New LOW/MEDIUM perimeter alerts appear as `channel='digest'` rows
  with audit `digest_queued`.
- **Boot.** URA loads with all room entries set up, and the log has no new errors from `config_flow` or
  `notification_manager`.
