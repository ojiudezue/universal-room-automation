# Review: NM-ACK-TTS-IGNORES-DISABLE-1 (fix/nm-ack-tts-gate @ 798f17c82)

Tier 1, single review, framing A (local correctness + blast radius). Reviewer: ura-reviewer, 2026-10-26.

## Diff
`notification_manager.py:3904-3908` adds `if not self._channel_qualifies("tts", Severity.CRITICAL): return` to `_announce_ack`, after the speakers check and before the dry-run log and `tts.speak`. Two tests were added in `quality/tests/test_safeword_window.py`. The branch merges cleanly onto develop (`git merge-tree` produced no conflicts; the custom_components diff against develop is this hunk only).

## Checks
| Check | Result |
|---|---|
| Config source | Holds. `_channel_qualifies` reads `self._config`, the same dict `_channel_ready("tts")` uses at :1766-1768. It is built `{**entry.data, **entry.options}` on update (:4154). |
| Default when key absent | Holds. `self._config.get(CONF_NM_TTS_ENABLED, False)` (:4850) defaults to silent. |
| Severity threshold | Holds. The ack is passed as CRITICAL, so any threshold of CRITICAL or lower passes when the channel is enabled. The alert path makes the same choice for safety refires (:2986). |
| No token burn | Holds. It uses `_channel_qualifies`, not `_channel_ready`, so the ack does not consume a TTS bucket token. This is the right call for a confirmation message. |
| Dry-run ordering | Holds. The gate runs before `_log_dry_run`, so a disabled channel leaves no dry-run row. A test asserts this. |
| Other TTS emitters | `_send_tts` (:2398) is called from: the alert path (:1771, gated by `_channel_ready`), the refire path (:2990, gated), and `async_test_notification` (:5376, deliberately ungated because it is an explicit operator per-channel test). No other `tts.speak` call exists in `custom_components`. |

## Findings
- **LOW / out of scope (already on the card):** both `tts.speak` sites (:2409, :3924) omit a `tts.*` entity target, so HA rejects them once TTS is enabled. The card leaves the engine choice to the operator. Not a blocker for this fix.
- **LOW / note:** `async_test_notification(channel="tts")` speaks while TTS is disabled. This is by design for an operator test and needs no action.

No CRITICAL, HIGH, or MEDIUM findings.

## Mutation (real source, detached worktree, pycache cleared, PYTHONDONTWRITEBYTECODE=1)
| Site | Mutation | Result |
|---|---|---|
| `_announce_ack` gate :3907 | `if not self._channel_qualifies(...)` -> `if False` | RED: `test_ack_announce_silent_when_tts_disabled` (1 failed / 26 passed). After restore: 27 passed, tree clean. |

## Bug classes
#53 (one missed site) is closed: every non-test TTS emitter is now gated.

## Verdict: SHIP
