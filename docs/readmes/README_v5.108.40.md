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

## Validated 2026-11-24 (restart ~22:37 CST, URA back 22:38)

The operator overrode the no-restart-while-sleeping rule ("Don't hold ship it"). The house was in Sleep, and house
state came back as `sleep` at 22:38:14.

| Criterion | Result | Evidence |
|---|---|---|
| Install | PASS | Marketplace `installed_version` v5.108.40; config check valid |
| Boot | PASS | 50/50 URA config entries `loaded`; system_log for the integration has warnings only, no errors. The one notable warning (`Zone-kWh seed UNRESOLVED`, 3 zones) is the known boot warning on card HVAC-ZONE-KWH-SEED-WARN-WORDING-1, not from this release |
| CM menu has "Rule writing model" | PASS | Coordinator Manager options menu ends with `room_rules_model` |
| Model step shows the stored value | PASS | `room_rules_ai_task_entity` form default `ai_task.claude_ai_task`; flow aborted, nothing saved |
| Optimizer form has no model field | PASS | `coordinator_optimization` LLM section lists only task entity, triage entity, prompt and daily cap; flow aborted |
| Check your rule is a menu | PASS | Study A (room rules off) > Room rules > Run an automation > submit: `room_rule_confirm` menu = `room_rule_save_turn_on`, `room_rule_save`, `room_rule_change_wording` (turn-on first because the switch is off) |
| Change the wording | PASS | returned to `room_rule_automation` with the same fields; flow aborted, nothing saved |
| Save adds the rule / end-to-end run of one Run-an-automation rule | NOT RUN | Saving a live rule in an occupied, sleeping house was not done unattended; owed at the next attended session (card AI-ROOM-RULES-TRUST-REPAIR-1) |
| Model change without reload | NOT RUN LIVE | Proven in-suite (key still in the reload-suppress set, suppression tests pass); not exercised live to avoid changing a live setting |
| Alert audit rows | PENDING (organic) | Since restart, no `no_channel_fired` rows (one stuck_signal MEDIUM `digest_queued`). Since 11-24 00:00 CST, 1 `no_channel_fired` row, before the restart. The discriminator is the deploy `--revisit` check over the following days |

HA Core memory 3 minutes after boot: 2.85 GB (`ha core stats`), against 5.03 GB before the restart. Host available
memory 3.4 GB, swap 2.4 of 3.9 GB used. This is the baseline for HA-CORE-MEMORY-GROWTH-1.
