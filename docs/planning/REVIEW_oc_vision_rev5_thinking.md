# REVIEW — OC self-fixing-house vision rev 5 + request_fix SEED (framing 2 of 2: quality of thinking + build prediction)

Reviewed: `VISION_optimization_coordinator_self_fixing_house.md` (rev 5), `PLANNING_oc_request_fix_dispatcher_SEED.md`.
Out of scope for this pass: citation and coverage accuracy (the other reviewer has it). File:line refs below point into the vision doc.
HVAC state-of-play: not re-read for this pass. No HVAC mechanism claim is made here beyond what the vision itself states.

Verdict: **⚠️ SIMPLIFY.** The core bet is plausible for diagnosis (R0). It is not yet shown for autonomous action (R1/R2). Two CRITICAL findings (the tier gates are not enforced in code outside HA; nightly cadence conflicts with the sleep gate) and a budget estimate that is low by about 2-4x need fixing in the doc before slice 0 is dispatched.

---

## CRITICAL

### C1. "Tier gates enforced in code, not by prompt" (§8 :317, §3 :118) is false for slices 1-3 as designed
Reasoning: §5 :184 runs the agent outside HA through ha-mcp and ssh, the same tools these sessions use. Those tools carry the operator's admin token and a host shell, and `ha_call_service` can call `homeassistant.restart`, `lock.*`, the Envoy reserve, anything. The "never grantable (hard-denied in code)" list at :118-126 has no enforcement point until the in-HA dispatcher exists, and even then the agent keeps its raw ha-mcp path beside `request_fix`, so the dispatcher can be bypassed. Prompt injection through entity names, log lines or NM text (§8) then has a full-privilege path, with no operator awake.
Doc fix: add a §3 "Credential boundary" that must hold before slice 1 starts. (a) The agent runs as a dedicated non-admin HA user with its own token. (b) Its only MCP is an allowlist proxy that exposes R0 reads plus `request_fix`, and nothing else. (c) No ssh. The URA DB is a read-only copy or a `mode=ro` URI. (d) Acceptance test: from the agent's session, try each item on the never-grantable list and assert it is refused at the proxy, not by the model. Until (a)-(d) exist, the agent may run R0 only.

### C2. Nightly cadence vs the sleep gate: R2 can almost never run on schedule, and P1 is aimed at the wrong time of day
Reasoning: §4 :178 runs the loop nightly. §2 :47 says R2 never runs while the house sleeps. A nightly run lands inside sleep, so promoted R2 types only act on event-triggered runs (deploy, restart, HIGH anomaly), which happen at arbitrary times. P1 (light left on in a vacant room) matters most at night, which is exactly when it is blocked. The doc never says when R2 actions actually execute.
Doc fix: state an explicit R2 window, for example "a second short run at wake (house state leaves sleep) executes queued R2 proposals for promoted types, re-validating each target's state first". Or accept that R2 is daytime-only and drop P1 from the night use case in the text.

---

## HIGH

### H1. Promotion arithmetic: P1-P5 will mostly never reach ≥ 20 proposals at ≥ 90%, and "proposal precision" has no measurement
Reasoning:
- **Frequency.** Every P-type is a backstop for an existing URA path that already does the job (vacancy-off, fan policy, borrow release, radar apply). Proposals only arise when that path fails. Worked examples: at 1 occurrence/week a type needs about 20 weeks to promote. P4 has a 3-day check-back and one step per proposal, so 20 proposals need more than 2 months even at maximum rate, and successive steps on one knob are not independent. P5 (radar drift) and P3 (unreleased borrow) are rare, probably fewer than 1/month, which means 2+ years.
- **What gets measured.** §2a :58 promotes on "proposals at ≥ 90% precision", but a check-back (:62-66) only exists for an *executed* action. A proposal the operator never executed has no check-back. So precision is either the operator's judgement (unstated) or undefined.
- **Statistics.** 18/20 = 90% has a 95% Wilson lower bound of about 70%. Promotion at the bar certifies "probably ≥ 70%", not 90%.
Doc fix: (a) Define proposal precision as "operator accepted and executed it, and its check-back passed"; rejected or ignored proposals count as misses or are excluded, and say which. (b) Add a slice-0/R0 measurement: count candidate occurrences per P-type over the last 30 days of the DB, and give each type an expected time-to-promotion. Park any type that projects past 6 months, with a revival trigger. (c) Either lower N for low-blast types or state the CI honestly.

### H2. The budget estimate undercounts cache reads by about 4x and ignores cache writes; Haiku crosses its own 100k price cliff
Reasoning: the formula charges 1.5M cache-read tokens for 30 round-trips, which is 50k per call, i.e. only the base pack. But every turn re-reads the *growing* prefix: 60k at the start, about 360k at the end (60k plus 300k of tool results), a mean of about 210k. That gives 30 × 210k ≈ 6.3M cache-read tokens. New tool results are also cache *writes*, which are priced above base input; the formula bills them as plain input. Re-done on the doc's own prices, Sonnet comes to about $1.65+/night, about $50/month. Haiku: the prompt passes 100k after a handful of tool calls, so the "> 100k costs 5x" footnote applies to most of the run, not the edge. The doc's ≈ $2/month is wrong; plausibly $8-12. Separately, §3b :164 caps tool results at 200k tokens per run while the budget assumes 300k. One of those numbers is wrong.
Doc fix: replace the formula with Σ over turns of the prefix length, add cache-write pricing, recompute the table, and reconcile 200k vs 300k. State the corollary: the $25 cap forces either aggressive context compaction (summarise tool results, then drop them) or a hard ~100k-token run for Haiku. That makes compaction a slice-1 requirement, not an optimisation.

### H3. R1 "reload one non-URA config entry" is not uniformly silent or safe
Reasoning: reloading ZHA, Zigbee2MQTT, MQTT, Bermuda or Shelly drops many devices at once. Lights and fans flap, occupancy sensors go unavailable, and URA rooms react, all of which occupants can see at night. Reloading the Envoy/Enphase entry is the documented EC restore-poisoning incident class (2026-06-12). Cloud entries (Sonoff/Tuya) cover many devices with one reload. §8 :318 says each R1 tool checks that it is not occupant-visible, but nothing defines how a reload could know that.
Doc fix: make R1 reload an explicit **allowlist of entries** (named, each with a blast-radius note). Put energy, Zigbee/MQTT hubs, Bermuda and cloud multi-device entries in R2 or R3. Default-deny for unlisted entries.

### H4. Slice-0 eval: 12-15 cases cannot tell models apart at an 80% bar, and the zero-tolerance gates are near-uninformative
Statistics:
- n = 15, true accuracy 80%: the 95% CI on the observed score is about 55-93%.
- A model with true 70% accuracy scores ≥ 12/15 (the bar) with probability ≈ 0.30. A model with true 90% fails the bar with probability ≈ 0.06. So roughly 1 in 3 of a set of mediocre models passes.
- Telling 70% from 90% at α = 0.05 and 80% power needs about 50 cases per model (one-sided two-proportion test).
- "0 invented-evidence" observed on 15 cases bounds the true rate only below about 18% (rule of three: 3/15 = 20%).
- "≥ 95% valid tool calls" per call, over 20+ round-trips, implies P(clean run) ≈ 0.95^20 ≈ 36%. The metric is per call, but the failure mode named at :232 is per run.
Doc fix: (a) Run each case k = 3-5 times per model, which helps with sampling noise but not case diversity, and grow toward about 40 cases by mining the closed cards and READMEs. (b) Report scores with CIs and rank models by paired comparison on the same cases, not by a pass/fail threshold. (c) Score tool validity per *run* (the run completes without a malformed or looping call). (d) Call the 0-invented-evidence result "none observed in N", not proof.

### H5. Eval leakage: the context pack contains the answers
Reasoning: §3 :84-96 loads `CLAUDE.md`, the feedback memories, the kanban board and the state-of-play docs every run. These now record the solutions for most eval cases: the solar counter flap card, the v5.103.83 exit-row fix, Foyer BLE, never-fires, §9.3 C27. Live tools would also show post-fix state, since the code and DB already contain the fixes. A model that reads the board scores "correct root cause" by retrieval, not diagnosis.
Doc fix: each case freezes a **pre-incident** snapshot: repo docs, board and memory at the commit before the fix, plus recorded tool responses (a replay harness, not live ha-mcp). Add a leakage check: grep each case's context pack for its expected root-cause string and fail the case setup if it is found. Hold out about one-third of the cases, and never use them while iterating on the prompt.

### H6. Agent outside HA has no liveness, no persistence home and no missed-run handling
Reasoning: a scheduled Claude session on the Mac does not run if the Mac sleeps, the session or Samba mount is down, or the API errors. R1 check-backs and auto-demotion depend on the *next* run, so a missed run silently skips verification, and a bad R1 fix rides on unverified. Also, §8 :319 says the agent "writes nothing into the URA write queue in slice 1", but problem records, the action log and spend tracking must be stored somewhere restart-safe. The doc never says where.
Doc fix: (a) Name the store for slices 1-2, for example a SQLite file on the Mac or a repo-committed JSONL. (b) Add an in-HA dead-man trip-wire: NM if no digest heartbeat by 08:00 (No-Soak rule: trip-wires in code). (c) Rule: an R1 action whose check-back did not run within 36 h counts as a failed check-back for demotion.

---

## MEDIUM

### M1. Marginal-benefit decomposition is missing, and the simplest version is probably most of the value
- The §1 complaint is *noise*. Two of the named causes are cheap static fixes: the in-memory dedup key (persist it), and the `cycle_ok` / prediction re-emits (stop writing them). These remove about 78% of the rows on the doc's own numbers, with no agent.
- The 10-21 "agent loop" was the operator plus Opus, interactive, with the operator steering. That is evidence for *diagnosis with a human in the loop*, which R0 reproduces. It is no evidence that an unattended Haiku-tier agent acts well.
- R1's margin over "R0 proposes, operator taps in the morning digest" is a few hours of latency on non-urgent, reversible faults. R1 adds a new unattended writer and the H3 blast radius.
- R2's margin is near zero for years per H1.
Doc fix: add a §1b decomposition. Simplest = static noise fixes + an R0 nightly digest. State R1's and R2's marginal value against it. Recommended stance: commit to slices 0-1. Make R1 conditional on R0 showing faults where morning-tap latency cost something. Park R2 with a revival trigger: a P-type with ≥ 20 measured occurrences over 90 days.

### M2. Contradiction a builder will trip on: "No unified request API" (:141) vs the dispatcher paragraph (:135) and the SEED
Doc fix: delete :141 or reword it as "No unified actuation API; the thin `request_fix` dispatcher (§3, SEED) is gate/log only." Also fix the stale header at :3 ("Rev 4 adds §5b"), and add a rev-5 line to the revision history.

### M3. SEED gate order and bypass
- Budget sits last, after rate limiting. That is fine, but budget is the only gate that should also stop *R0 spend*. Put it first (cheap, global).
- The SEED never says the agent must have *no other actuation path* (ties to C1). Without that, `request_fix` is advisory.
- "Same shape" for ≥ 3 coordinators (Q6) is left undefined. Suggest: same (verb, target class, check-back type) triple.
Doc fix: add "the dispatcher is the agent's ONLY write path; the proxy enforces it" to Not-in-scope / invariants. Reorder: kill switch → budget → type known → tier vs promotion → sleep gate → rate limit.

### M4. Two R1 tools look R2/R3-adjacent
- "Re-seed a counter / baseline" (billing `reseed_cycle`) can change money figures, and EC high-water marks feed energy decisions. Under §2 :48 ("anything that costs money") that is R3.
- "Clear a stuck-sensor latch" feeds occupancy, and §3b :158 makes occupancy memory-ineligible for safety reasons.
Doc fix: re-tier counter re-seed as R2 propose-only, and add a note that clearing a latch is allowed only for sensors with no safety or security consumer.

### M5. The R0 acceptance "operator rates ≥ 80% over 1 week" is underspecified
About 7 runs might yield 5-30 diagnoses, so the 80% figure has a very wide CI, and the operator is travelling 10-14 to 10-18. A single week also misses weekly patterns.
Doc fix: require a minimum count (≥ 30 rated diagnoses). Specify the rating UI (board disposition tap per diagnosis). Extend to 2 weeks if the count is not reached.

## LOW

- L1. §5b's "Earlier record (superseded)" block (:225-231) still says "no discrete GPU" and "only ~8B CPU models feasible". Delete it, or a builder will size for the wrong hardware.
- L2. Empty responses from the 9B/27B probes (:224) should be a slice-0 entry gate ("each local candidate returns a valid tool call on a smoke prompt") so eval time isn't wasted.
- L3. Split-model scoring (:240) needs the escalation criterion defined *before* the eval. Otherwise it gets tuned on the eval set (more leakage).
- L4. The P4 check-back "metric moves the right way over 3 days" doesn't control for confounders (weather, occupancy). Name the comparison baseline, for example the same weekday or degree-day-normalized.

---

## What a builder will get wrong reading this (summary)
1. Wire the agent to the existing ha-mcp/ssh and treat the exclusion list as prompt text (C1).
2. Schedule one nightly run and never see R2 fire (C2).
3. Build eval cases from today's repo and board, so the answers are in context (H5).
4. Copy the budget formula and blow the $25 cap within the first week (H2).
5. Implement "precision" as check-back pass rate on actions, which is undefined for proposals (H1).
6. Read :141 and skip the dispatcher (M2).
