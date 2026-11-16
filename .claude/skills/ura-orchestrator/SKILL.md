---
name: ura-orchestrator
description: >
  How the URA orchestrator session runs a multi-agent arc: (A) goal-oriented forward momentum (never idle, take
  obvious defaults, page the operator for real decisions), (B) agent orchestration with verification and quality
  checks on every hand-back, and (C) consistency verification and drift correction, especially across compaction
  boundaries. Load at session start, after every compaction, before dispatching agents, and whenever a sub-agent
  hands back. Builds on ura-kanban (board) and ura-arc (charter / drift); CLAUDE.md wins over all three.
---

# URA orchestrator

Operator 2026-11-15: "Organize your evolving expertise to add A. Ensuring goal oriented fwd momentum ie don't idle and
don't wait for decisions that are obvious or page me through out and channels. B. Agent orchestration and agent
verification and quality checks. C. Consistency verification and drift correction especially across compaction
boundaries."

Sister skills: `ura-kanban` (capture, board lanes, autonomy ladder), `ura-arc` (charter, drift table, goal-fidelity
framing G). This skill is the operating loop that uses them.

## A. Forward momentum

1. **Never idle while work is eligible.** When agents are running, use the wait on independent work: write the README
   draft, reconcile the board, verify a claim, commit docs, prepare the next brief. A turn that only says "waiting"
   while a ready card exists is a miss.
2. **Take obvious defaults; do not ask.** If a decision has a recommended default that is reversible, inside an
   approved scope, and not house-visible in a new way, take it, record it on the card (`decision_<date>: took default
   X because ...`) and tell the operator in one line. Examples from 2026-11-15: option A for ambiguous crossings after
   "of course. No brainer"; door grading before interior grading; describe operator-only.
3. **Ask only what is genuinely the operator's.** Product tradeoffs (a risk reduction that changes what is delivered),
   new house-visible behaviour (a fan turning off on AWAY, cameras starting to hold room occupancy), physical facts only
   they know, deletes, money, credentials. Each ask carries a recommended default and what happens on each answer.
4. **Page through a channel when the ball is theirs.** If a decision blocks a build and the operator has gone quiet,
   send a real notification (NM page per ura-kanban, or the PushNotification tool) AND park the card
   `waiting_operator` with a verb-led `next`; then move to the next card. One open question never stalls the queue.
5. **Approval to build is approval to ship** (memory `feedback_build_permission_implies_ship`). Restart rules still
   hold: never while the house sleeps; a "clear to restart" covers the stated deploy only.
6. **Finish the arc, not the slice.** After a ship, re-read the drift table: work that was promised next (2026-11-14:
   music, step 8, interior review) must move before new detours. The layer ship that ate an afternoon is the
   counter-example (charter drift #20, repeated 11-15).

## B. Agent orchestration and verification

1. **Caps.** At most 4-5 agents at once, at most 2 builders, one full pytest suite at a time (memory
   `feedback_fewer_agents_sonnet_readonly`). Sonnet for read-only probes and review C; Opus for builders, planners and
   reviews A/B/D/G; Haiku for the validator.
2. **Every brief carries:** the exact question in the operator's words; read-first docs (state-of-play, fleet classes,
   charter); the facts already measured, so the agent does not re-derive them; the deliverable file path; the rules
   (one command per Bash call, no mkdir, helpers in `.claude/tmp` with non-stdlib names, token never printed, no
   Bermuda diagnostics, no HA state changes unless the brief says so); and the return shape (verdict + evidence).
   **Secrets in config reads:** twice on 2026-11-15 a probe printed credentials while reading `core.config_entries` /
   an integration's config (Tuya + MQTT, then Frigate). Every brief that touches config entries says: select the
   needed keys inside the script and print only those; never print `data` / `options` / diagnostics wholesale.
3. **Never trust a hand-back.** Before relaying, verify the load-bearing claim yourself with one cheap check: a
   history read, a grep, a state read, the actual test name. 2026-11-15 examples: the guest peak (re-read history),
   the 20+ paused rooms (live switch search), the validator's "CLEAN" (its extra-mode report never arrived; the
   output files were read directly).
4. **Silence is not success.** An agent whose notification says "waiting on its own background work" may never send
   its report. Check its output files or run the step yourself before declaring a gate passed.
5. **Tier-3 gates are not delegable.** The orchestrator re-greps the emission / decision sites and runs its own
   source mutation on the load-bearing site (edit, run, RED, restore, `git status` clean) before the operator
   checkpoint.
6. **Mechanical traps.** The deploy marks every `--cards` card shipped, so never pass a parent whose later phases are
   open; split a child card. YAML edits are surgical (never safe_dump the board); append text inside a quoted scalar,
   never after the closing quote. Run `kanban_render.py --check` after every board edit. HACS installs unpack for
   minutes; wait for `manifest.json` before restarting.
7. **Reviews must be framing-disjoint** and plans get reviewed before builds (CLAUDE.md). After a fix-up, a short
   spot-check of the diff, or an orchestrator re-grep when the reviewer names the exact lines, is enough; a fresh full
   review is not.

## C. Consistency and drift correction

0. **The in-flight list decides.** `docs/planning/ARC_identity_vision_census_map.md` §4a is the single ordered list of
   what runs. Nothing new gets an agent unless it is the next open row there or the operator asks. Update its status
   column at every hand-back and before every dispatch; a side finding gets a card and waits. Operator 2026-11-15:
   "I don't want it not to matter."

1. **Live findings feed plans the same cycle** (memory `feedback_live_findings_feed_plans`). A live failure gets a
   mechanism, then an amendment to every plan that assumed otherwise, then a review. A card alone is not enough.
2. **Plans are hypotheses about the house.** Before a plan's numbers are relied on, check them live. 2026-11-15:
   the plan's watched-set counts (expected the foyer only unwatched; live showed 14) came from a probe that used
   entity-else-device area while the code uses entity area only.
3. **After every compaction:** re-read the charter goals and drift table (ura-arc), the arc map, and the cards in
   `in_progress` / `review` / `waiting_operator`; check that the summary's "next step" still matches the board; check
   which agents are still running before dispatching duplicates; re-verify any fact the summary states about live
   state. The summary is lossy, so the board and the files are the record.
4. **Harmonize across plans** whenever two plans touch the same function, field, constant, contract or budget (for
   example `deconflict_house` keywords from interior vision and crossing Phase 3; vision call caps; G3 roles; grading
   tool). Resolve it in one plan and point the other at it. A periodic arc-wide harmonization report
   (`docs/planning/HARMONIZATION_*.md`) is the check.
5. **Drift table at milestones** (ura-arc rule 7): plan dispatch, approval, ship, session start, after compaction.
   Name your own drift, not only the plans'. 2026-11-15: shipping 3a/3b again ran ahead of music and step 8.
6. **Don't claim effects you have not verified.** The foyer area move was reported as "the room picks up the camera
   at restart"; it does nothing until the area-map fix ships. Say what a change does only after reading the code
   path that consumes it.
