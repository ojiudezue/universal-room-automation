# Review: KANBAN-SHIP-FLOW-CARDS-1 (branch fix/kanban-ship-flow-cards @ 6da6cab1)

Tier 1, framing A (local correctness + edge cases). Base: develop fc75a6b3 (verified with `git merge-base`). Tooling only: `scripts/kanban_ship.py` and `quality/tests/test_kanban_ship.py`.

**Verdict: SHIP.** No CRITICAL, HIGH or MEDIUM findings. Three LOWs, all fail-safe (the card is reported or left unchanged, never corrupted).

## Evidence
- `quality/tests/test_kanban_ship.py`: 24 passed.
- Real-board drill on a copy of `docs/planning/kanban.data.yaml`. All 13 column-0 flow cards were passed to `mark_shipped_text`. Result: 0 unedited. A semantic YAML diff over every card shows only `status` -> `shipped_organic` and `shipped_version` -> `v<ver>` changed on those 13. Every other card and top-level key is identical, apart from the expected `meta.last_reconciled`. The text diff is 14 lines (13 flow lines plus last_reconciled). `kanban_render.py --data <copy>` rendered without error.
- Re-emission fidelity: the board's flow lines are JSON, so every scalar is already quoted. `yaml.safe_load` creates no datetime objects, so the `default=str` path never runs on the real board. ints, lists, nested dicts and unicode (`ensure_ascii=False`) round-trip unchanged.
- Boundaries (`_find_card_blocks`, kanban_ship.py:284-293):
  - A flow card followed by a block card splits correctly: ('A',1,3), ('B',3,7).
  - A nested `  - {"id": ...}` inside a block card is NOT detected as a card. `_FLOW_CARD_START_RE` is anchored at `^- \{`, column 0. The block card is still edited and the nested id is reported as unknown.
  - A last flow card is closed by the top-level-key scan.
- `record_arc_cuts_text` on a flow card produces valid YAML with `arc_cut_v9_9_9` inside the mapping. Quotes in the reason survive because JSON handles the escaping.
- Post-push safety: `cmd_mark_shipped` (kanban_ship.py:481-492) only WARNs about unedited or unknown ids and still returns 0. deploy.sh:369-372 runs it under `set +e`, and arc cuts are guarded with `||`.
- Tests drive production paths: `kanban_ship.mark_shipped_text`, `_find_card_blocks`, `record_arc_cuts_text` and the CLI against a copy of the real board. No logic is hand-copied.

## Findings
| Sev | Where | Finding | Class |
|---|---|---|---|
| LOW | kanban_ship.py:349 (`end - start == 1`) | A flow card followed by a blank or comment line gets a range longer than 1, so it is reported as unedited even though it could be edited. It fails safe (WARN), and the current board has none. Possible fix: allow trailing lines in the range when they are blank or comments only. | false-negative edge |
| LOW | kanban_ship.py:155-159 | `record_arc_cuts_text` silently `continue`s when `_edit_flow_card_line` returns None, so a failed arc cut on a flow card is not reported. This is the same silent-skip shape the cycle fixed for mark-shipped. | #53-adjacent (silent skip) |
| LOW | kanban_ship.py:249 | Re-emitting a flow line drops any trailing `# comment` on that line and normalises quoting to JSON. No current flow line has a trailing comment. | fidelity |

Recommend fixing LOW 2 in-cycle (2-3 lines); the other two are optional.

## Fix-up (orchestrator, overnight 2026-11-11)
- LOW-1 fixed: a flow card followed only by blank/comment lines is now edited (test_flow_card_followed_by_blank_and_comment_is_edited).
- LOW-2 fixed: record_arc_cuts_text warns on stderr when it cannot edit a flow card (test_record_arc_cuts_reports_uneditable_flow_card).
- LOW-3 (trailing `# comment` on a flow line is dropped on rewrite) deferred: no flow line on the board carries one; documented here.
- test_kanban_ship.py: 26 passed.

| Severity | Found | Fixed | Deferred |
|---|---|---|---|
| CRITICAL/HIGH/MEDIUM | 0 | 0 | 0 |
| LOW | 3 | 2 | 1 |

Bug class: silent skip on an unrecognised record format (a writer that `continue`s without reporting) — same family as QUALITY_CONTEXT's silent-no-op classes.
