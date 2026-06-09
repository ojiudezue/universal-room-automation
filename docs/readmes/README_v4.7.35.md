# URA v4.7.35 — Optimization Coordinator Phase 2 (LLM Tier-2, provider-agnostic)

**Release date:** 2026-06-09
**Tier:** Tier 2-DB (three framing-disjoint reviews + live validation; payload-shape DB trigger: `created_by=tier2_llm` provenance lane)
**Scope:** Adds the LLM reasoning tier on top of Phase 1's deterministic loop. Claude (or any `ai_task.*` backend) reasons over the raw substrate + Phase-1 dimensions and emits findings that flow through the **same autonomy chokepoint** as deterministic findings — gated, never unguarded. Still ships at **L1 Shadow** by default.

**Planning doc:** `docs/planning/PLANNING_OPTIMIZATION_COORDINATOR_v2_agentic.md` (Phase 2)
**Review doc:** `docs/reviews/code-review/v4.7.35_optimization_coordinator_phase2_llm.md`
**Depends on:** v4.7.34 (Phase 1). Recommend deploying + live-validating v4.7.34 first.

---

## Headline Changes

- **New file `domain_coordinators/optimization_llm.py`** — `OptimizationLLMTier` + `OptimizerContextCorpus`. Invoked once per optimizer cycle when the finding-set changed (delta-trigger) AND under the daily premium cap AND an `ai_task.*` entity is configured.
- **Provider-agnostic** via `ai_task.generate_data` with a configurable `entity_id` — works across Claude / OpenAI / Google / local Ollama. Structured output parsed/validated; malformed rows skipped, good rows kept.
- **Cost levers (stacked):** provider selection incl. local ($0); cheap-triage→premium routing (triage OFF by default until an explicit cheap backend is set); delta-trigger gate; hard rolling-24h premium cap (seeded from DB so a restart can't bypass it); ≤24KB corpus + 16KB prompt bound.
- **Chokepoint reuse:** every LLM-proposed action goes through Phase-1's `_apply_action` — autonomy ladder, confidence gate, rate-cap, quiet-hours, kill-switch, device/config allowlists, OverrideArrester handshake. The LLM is just another finding *source* (`created_by="tier2_llm"`). No bypass path.
- **Editable system prompt:** stored in CM `entry.options` (multiline field), persists across reboot; reset = clear the field → in-code `OPTIMIZER_LLM_SYSTEM_PROMPT` const default. Conservative, anti-hallucination, provider-portable v0.

## New config (CM entry options — 5 keys)

`CONF_OPTIMIZER_LLM_TASK_ENTITY` (default `ai_task.claude_ai_task`), `CONF_OPTIMIZER_LLM_TRIAGE_ENTITY` (default empty = no triage; recommend `ai_task.ollama_ai_task`), `CONF_OPTIMIZER_LLM_SYSTEM_PROMPT` (editable; empty → const), `CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H` (default 24), `CONF_OPTIMIZER_SAFETY_DENY_ENTITIES` (default empty — entities the optimizer must never actuate, enforced at the chokepoint). All in `OPTIONS_RELOAD_SUPPRESS_KEYS` (no CM reload on change).

## Review fix-up (Tier 2-DB, commit `b65f19e`)

No CRITICAL bypass. Fixed in-cycle: premium cap now restart-safe (DB-seeded); LLM `target_entity` validated against the snapshot (anti-hallucination); `action_class` derived from the service domain (not LLM-supplied); code-enforced safety/security entity deny-list; `service_data` key allowlist; triage off-by-default + uncapped warning; LLM confidence soft-clamped ≤0.85; corpus/prompt size bounds; ai_task timeout. See review doc.

## Known limitations (by design / deferred)

- The `coordinator_optimization` config-flow step (Phase 1 + 2 keys, ~10 fields) currently renders **raw machine keys** — translations are a tracked follow-up (does not affect function).
- Safety deny-list is operator-configured (`CONF_OPTIMIZER_SAFETY_DENY_ENTITIES`); auto-enumeration of Safety/Security-coordinator-owned entities is a follow-up.
- Anthropic `cache_control` is not surfaced by HA `ai_task` today; the `# === STABLE CONTEXT ===` markers are forward-compat scaffolding only.

---

## Live Validation (Review D) — prospective criteria, to be populated post-restart

- **Verify:** `optimization_llm` loads; no import/registration errors post-boot.
- **Verify:** LLM tier invokes only when the finding-set changed (delta gate) — confirm via the prior/new-signature debug log; it does NOT call `ai_task` every cycle.
- **Verify (cost cap restart-safe):** after a restart within the same 24h, the premium-invocation count is seeded from DB, not reset to 0.
- **Verify (provider-agnostic):** set `CONF_OPTIMIZER_LLM_TASK_ENTITY=ai_task.ollama_ai_task`, confirm findings still parse (structured output round-trips on a local backend).
- **Verify (L1 inertness):** an LLM-proposed action at L1 logs `applied_outcome=shadow_dry_run` with ZERO real service calls; `created_by=tier2_llm` rows present in `optimization_findings`.
- **Verify (anti-hallucination):** if the LLM ever names an off-snapshot entity, it's rejected (INFO log), not dispatched.
- **Verify:** zero URA ERROR logs attributable to `optimization_llm` post-boot.

| Criterion | Observed | Source |
|---|---|---|
| (TBD post-deploy) | | |
