# Plan Review — Known-Person Annotation Pipeline v1 (rev-2)

- **Plan under review:** `docs/planning/PLANNING_known_person_annotation.md` @ commit `58ca0d9f7` (rev-2, folded D3 stranger-alert leg).
- **Reviewer framing:** Tier 2-DB adversarial pre-build pass — independently re-enumerate emission sites, NM hazard-consumer surfaces, and stranger-leg guard bypass paths; verify with greps not with the plan's own citations.
- **Load-bearing invariant under adversarial test:** INV-KP clauses (a)-(e), with special attention to (e) — stranger leg is strictly additive; base dispatch is never delayed, blocked, mutated, or dedup'd by any code path in the stranger leg.
- **Verdict:** **FIX-PLAN-FIRST.** One CRITICAL (NM hazard-consumer enumeration is incomplete for the new `exterior_unknown_person` type — introduces silent routing / safeword / demotion divergences). Two HIGH (INV-KP(e) ordering proof is under-specified against HA async semantics; stranger-leg dispatch reuse hand-waves a private closure). Three MEDIUM. Two LOW. No new operator decisions surfaced beyond the three the plan already flags as inline-resolvable.

Fix all CRITICAL + HIGH in the plan before build dispatch. MEDIUMs may be fixed in the plan or accepted as builder-time TODOs with explicit acceptance-test coverage.

---

## Institutional-context re-verification (greps re-run, plan claims spot-checked)

Verified independently — plan is correct on these:

1. **`perimeter_enrichment.py` shape exists** at `custom_components/universal_room_automation/perimeter_enrichment.py` — the CONSOL-1 adapter the plan mirrors 1:1 is real. REUSE claim confirmed.
2. **Insertion point `perimeter_alert.py:1362-1366` is current.** Verified: `_do_dispatch` is defined at approximately L1366, immediately after the CONSOL-1 enrichment block that terminates around L1362 with the `route_reason` composition. Plan's stated insertion coordinates are accurate.
3. **`tracked_persons`** — orchestrator has already verified live (4 persons, current). Not re-probed here.
4. **`CONF_KNOWN_PERSON_*` / `CONF_FACE_*` / `CONF_PERSON_ANNOTATION_*` / `CONF_STRANGER_*` returned zero hits** — confirmed via `grep -n` on `const.py`. All 8 CONF_* / rung-3 knobs the plan proposes are legitimately NEW.
5. **`NM_HAZARD_EXTERIOR_PERSON = "exterior_person"`** defined at `const.py:1467`; used as the base hazard in the existing dispatch (`perimeter_alert.py` around L1379). REUSE for the base is unaffected.

Findings below concern surfaces the plan DID NOT enumerate.

---

## CRITICAL

### CRIT-1 — New `hazard_type=exterior_unknown_person` bypasses THREE downstream NM decision surfaces the plan is silent on

The plan proposes a NEW `NM_HAZARD_EXTERIOR_UNKNOWN_PERSON = "exterior_unknown_person"` for the stranger-leg emission, and says it dispatches "via the SAME NM path the base alert uses". It does NOT enumerate the hazard-consumer surfaces that gate on hazard_type membership. Independent grep of the NM code reveals at least THREE membership-gated surfaces the new hazard will silently miss:

1. **`NM_SECURITY_HAZARDS` (`const.py:1509-1512`)** — a frozenset containing exactly `{exterior_person, exterior_vehicle}`. It gates:
   - **Force-immediate delivery** (`notification_manager.py:1368`) — security-class alerts bypass rate/dedup and dispatch immediately. The stranger emission — the LOAD-BEARING purpose of the whole D3 leg — will NOT get force-immediate treatment unless added.
   - **Safeword window scope** (`notification_manager.py:1445, 1471`) — the operator's "duke Nh" perimeter-tuning window suppresses ONLY hazards in `NM_SECURITY_HAZARDS`. A stranger alert would leak *through* an active safeword window intended to quiet perimeter noise — the exact opposite of operator intent. Cross-reference: `PLANNING_safeword_window.md` invariant I2 ("perimeter-only" — perimeter is *defined* as this set).
   - **Force-immediate lookup for security class** (`notification_manager.py:1709`) — recipient selection / bypass paths.

2. **`MEMORY_INELIGIBLE_HAZARD_TYPES` (`const.py:3685-3691`)** — defense-in-depth allowlist against memory-driven severity demotion. Contains `"exterior_person"` explicitly. A new `"exterior_unknown_person"` NOT in this set could, on a future widening of the operative allowlist, become demotion-eligible — silently softening the stranger alert. This is precisely the failure mode the frozenset was constructed to prevent; the plan must extend it.

3. **`NM_HAZARD_EXTERIOR_PERSON_SEVERITY_BY_HOUSE_STATE` (`const.py:1542-1553`)** and the `NM_HAZARD_EXTERIOR_PERSON_CONTEXTUAL_SEVERITY(...)` resolver (`const.py:1556`). Plan §D3 says severity is "per existing house-state severity map, at a doorbell-appropriate tier (probably one notch above)" — this is not a spec, it is a wish. The stranger emission needs EITHER (a) its own severity map (`NM_HAZARD_EXTERIOR_UNKNOWN_PERSON_SEVERITY_BY_HOUSE_STATE`) OR (b) a resolver that composes off the existing one plus a delta. Silence in the plan = builder invents = review-time surprise.

**Why CRITICAL, not HIGH:** the safeword-window leak in particular is a policy inversion — the operator uses "duke Nh" precisely to quiet perimeter noise during expected activity (contractor, delivery, gardening). A stranger emission that bypasses that window fires the alert the operator was silencing. This is a false-stranger UX regression the plan's guard machinery cannot catch because the leak is at the NM layer, not the guard layer.

**Fix in the plan:** add an explicit "NM hazard-consumer enumeration" subsection to §D3 that, for each of the three sets above (and any others uncovered by a fresh `grep -rn NM_SECURITY_HAZARDS\|MEMORY_INELIGIBLE_HAZARD_TYPES\|NM_HAZARD_EXTERIOR_PERSON` sweep), declares whether the new hazard type joins the set or does not, WITH RATIONALE. At minimum: join `NM_SECURITY_HAZARDS` (correctness — force-immediate, safeword scope) and `MEMORY_INELIGIBLE_HAZARD_TYPES` (defense-in-depth). Severity resolution requires an explicit spec, not "probably one notch above." The Reviewer-B framing in §Tier line 15 explicitly names "every perimeter emission site + no accidental suppression" — extend it to "every hazard-consumer set" so this gap is caught in review even if not fixed in the plan.

---

## HIGH

### HIGH-1 — INV-KP(e) "AFTER the base dispatch has been enqueued to NM" is under-specified against actual HA async ordering

Plan §D3 says the stranger leg is "scheduled AFTER the base dispatch has been enqueued to NM" and §Falsifiable-invariant clause (e) requires that "no code path in the stranger leg — including its guard evaluation, its identity re-read, or its escalation dispatch — can delay, block, mutate, dedup, or replace the base alert."

Verified via `perimeter_alert.py` L1436-1440: the base dispatch runs inside `_do_dispatch`, which is a **local closure** invoked either directly (`await _do_dispatch()`, if `delay_s <= 0`) or scheduled via `hass.async_create_task(_do_dispatch())` (if `delay_s > 0`).

Adversarial construction against the plan's spec:

- **If the stranger leg is scheduled via `hass.async_create_task(...)` immediately after the base's `async_create_task`**, task-start ordering is FIFO on the loop but **completion order is not guaranteed** — the base dispatch awaits `nm.async_notify(...)` (network / cross-coord signal), and any await inside that hop can hand the loop back to the stranger-leg task. The stranger leg can then observe / mutate NM state (cooldowns, dedup keys) *before* the base has finished delivering. "Enqueued" is doing all the work in the plan's sentence and is not a defined async milestone.
- **If the stranger leg is `await`ed inline after the base**, the plan's "never delay base" claim fails on any timeout / long guard-eval path (up to `stranger_leg_identity_attempt_timeout_s`, default likely 10s), because the enclosing coroutine holds `_dispatch_in_flight` until the whole thing returns. See `perimeter_alert.py` L1433: the `finally` that discards `_dispatch_in_flight` gates the NEXT trigger on this camera. A 10s stranger wait blocks the cooldown-key release, which will suppress a legitimate second person-detection.
- **If the stranger leg is scheduled from a callback attached to the base's task done-callback**, the plan should say so; today it doesn't.

The plan's live acceptance criterion — "temporarily raise `stranger_leg_identity_attempt_timeout_s` to 30s, trigger a doorbell event, confirm base timestamp is unchanged" — is a good falsifier for the base-alert-latency slice but does NOT cover the `_dispatch_in_flight` blocking slice or the interleaved-state-mutation slice.

**Fix in the plan:** state the exact scheduling primitive (probably `hass.async_create_task(_stranger_leg_evaluate(...))` fired after — but not awaited by — the base's `async_create_task` / await path), and specify that the stranger leg MUST NOT hold or observe `_dispatch_in_flight`, MUST NOT touch base cooldowns, and MUST NOT interleave with the base's `_do_dispatch` execution window. Reviewer D's INV-KP(e) proof obligation should call out `_dispatch_in_flight` by name as a state the stranger leg is forbidden to read or hold. Add a live acceptance criterion: with `stranger_leg_identity_attempt_timeout_s=30s`, back-to-back doorbell events at t=0 and t=6s BOTH produce a base alert (the second must not be suppressed by a still-held `_dispatch_in_flight` from the first).

### HIGH-2 — Stranger-leg dispatch path hand-waves reuse of `_do_dispatch`

Plan §D3 "Stranger emission shape" says the stranger fires "via the SAME NM path the base alert uses (no new dispatch code path — reuse `_do_dispatch` or its equivalent)."

Verified: `_do_dispatch` is a **local closure** defined inside `_async_handle_perimeter_trigger` (`perimeter_alert.py:1366`). It closes over `cooldown_key`, `severity`, `title`, `message`, `hazard_type`, `entity_id`, `snapshot_url`, `snapshot_path`, `route_reason`, `nm`, `self`. It is NOT reachable from anywhere outside its enclosing function. "Reuse `_do_dispatch`" is not implementable as written.

Two viable shapes; the plan must pick one:

1. **Extract `_do_dispatch` to a method** (e.g. `self._dispatch_to_nm(...)`) taking the composed kwargs explicitly, then call it from BOTH the base path and the stranger path. This is the cleanest reuse but is a refactor of a currently-shipped surface — deserves a plan callout and adds to the Reviewer-B mutation-neuter drill list.
2. **Duplicate the minimal `nm.async_notify(...)` call in a stranger-only dispatcher** with its own `_kwargs` composition and its own logging. Simpler in blast radius but violates the "one dispatch shape" property the plan implicitly assumes and requires the plan to acknowledge two emission sites in the wire-in enumeration.

**Fix in the plan:** pick a shape, name the site, and add it to §D3's acceptance list (wire-in-anchor test for the stranger-emission call site — the plan already lists this at line 262 but it needs a concrete callee to point at).

---

## MEDIUM

### MED-1 — `stranger_leg_confidence_floor` default is "D0-driven" but D0(a) does not include a confidence-distribution probe

Plan §D3 gate 5 requires the producer's confidence attribute to clear `stranger_leg_confidence_floor` before firing on an unknown-verdict identity, with default "D0-driven, likely 0.60". But D0(a) probes producer *presence* and D0(b) probes *latency + name/unknown state distribution*; neither collects a confidence-attribute histogram. The default is therefore invented, not derived.

Fix in the plan: add D0(a.iii) — for each Frigate face producer discovered, enumerate the confidence attribute (attribute name(s), min/mean/p50/p95 over the 30-day window, distinct-value count for "unknown" vs recognized). Add same for UP if attribute is present. Absent this, the "D0-driven" claim on this knob is fictional and the default becomes a builder trap.

### MED-2 — "Producers that don't expose confidence" branch is deferred with two mutually incompatible options

Plan §D3 gate 6: "Producers that don't expose confidence (probe in D0) either bypass this gate (fire on any unknown) OR the operator picks a per-producer default at D0 review — plan review must adjudicate."

This is exactly the "two-options-when-one-is-correct" class the CIRCLING-LABEL-1 plan review just flagged in the last cycle. Plan review should adjudicate here, not push it to build:

Recommended: **fail-CLOSED with an explicit per-producer opt-in**. If a producer does not expose a confidence attribute, the leg does NOT fire on that producer's unknown verdicts unless the operator sets a per-producer override (`CONF_STRANGER_LEG_NO_CONFIDENCE_PRODUCERS: list[str]`, default empty). Consistent with the plan's own fail-CLOSED rationale for guard exceptions (§D3 Rejected alternatives) — a producer without confidence has *less* signal than one with a low-confidence-but-passing verdict, and firing on it is at least as risky as an exception.

Fix in the plan: pick the recommended shape or an alternative, add the CONF_* to the knobs table with rung/kill semantics, and delete the "adjudicate at build" language.

### MED-3 — D3 stranger-leg cooldown key does not compose against the base cooldown key

Plan §D3 says cooldown is "per `(camera, "stranger_leg")` per `stranger_leg_cooldown_s`". Base cooldown (verified in `perimeter_alert.py`) is on `cooldown_key` derived from `_camera_key_for_sensor(entity_id)` — a *camera-key* fusion, not a raw entity_id (accounts for multi-sensor cameras). If the stranger leg keys off `entity_id` or `camera_entity_id` directly, a doorbell with a person + object sensor fusion will get two independent stranger-leg cooldowns.

Fix in the plan: state that the stranger cooldown key uses `_camera_key_for_sensor(entity_id)` in the tuple, matching base fusion. One-line clarification.

---

## LOW

### LOW-1 — Route-reason composition undefined for `annotated + enriched`

Plan §D1 line 166 offers two options for the compound case ("prefer `NM_ROUTE_REASON_ENRICHED_AND_ANNOTATED` (or compose as a stamped tuple — pick one shape; enumerate route reasons in the plan review)").

Adjudication: **compose as a fixed enum** — `NM_ROUTE_REASON_ANNOTATED`, `NM_ROUTE_REASON_ENRICHED`, `NM_ROUTE_REASON_ENRICHED_AND_ANNOTATED`, `NM_ROUTE_REASON_ENRICHMENT_FAILED_FALL_THROUGH` (existing). Reason: `route_reason` is a single scalar field in NM (`notification_manager.py:596, 1484`), consumed by dashboards. A tuple would require every consumer to normalize; a fixed enum is one line of composition at the emission site. Add the new const to `const.py` alongside the existing CONSOL-1 route reasons at L1526-1533.

### LOW-2 — Snapshot handling for the stranger emission is unspecified

The base dispatch carries `snapshot_url` and `snapshot_path` (verified L1382-1383). The stranger emission's `message` spec includes "snapshot URL" but D3 does not say whether it reuses the base snapshot (same file, no re-capture — likely correct) or captures its own. Should be one line. Confirming reuse also confirms the privacy invariant — no new snapshot write path (LAN-only, no /config/www staging) is introduced.

---

## Privacy check (rev-2 binding decision #1)

Scanned the plan for any snapshot / photo write path outside the existing NM `snapshot_url` / `snapshot_path` fields. Found none:
- The annotation adapter reads producer entity state only (`sensor.<x>_last_recognized_face`, UP attrs).
- The stranger emission proposes to reuse base snapshot (per LOW-2 clarification).
- No path writes reference photos anywhere; no path writes to `/config/www`.
- llmvision is explicitly excluded from the identity path per rev-2.

Privacy invariant holds as-scoped. LOW-2's clarification closes the last ambiguity.

---

## Sanity checks (spot-checked, all PASS)

- **D0 numeric thresholds pre-stated:** 50%/80% ship, 30-50%/60-80% conditional, <30%/<60% park. PASS (measure-before-build discipline satisfied).
- **Knob ladder placement:** all 8 new knobs have rung, home, default, kill semantics. PASS.
- **Wire-in anchor tests required for BOTH legs:** §D1 test bullet + §D3 test bullet. PASS.
- **Non-goals explicit:** vehicle leg, interior face, cloud identity, phase-2 machinery, by-edit shape — all fenced. PASS.
- **Falsifiable invariant stated up front:** INV-KP (a)-(e). PASS; clause (e) needs the HIGH-1 tightening but the framing is correct.
- **Discharge on the stranger-leg wait:** timeout → fire or drop-with-ledger, exception → fail-CLOSED. PASS.

---

## Summary table

| # | Severity | Class | One-line |
|---|---|---|---|
| CRIT-1 | CRITICAL | NM hazard-consumer enumeration incomplete | New `exterior_unknown_person` silently bypasses NM_SECURITY_HAZARDS (force-immediate + safeword window), MEMORY_INELIGIBLE_HAZARD_TYPES, and severity resolver. |
| HIGH-1 | HIGH | Async ordering under-specified | "Enqueued to NM" is not a defined milestone; stranger leg can interleave with base `_do_dispatch` and can hold `_dispatch_in_flight` on the inline shape. |
| HIGH-2 | HIGH | Dispatch reuse hand-waves a private closure | `_do_dispatch` is a local closure inside `_async_handle_perimeter_trigger` — not reachable from a stranger-leg emission site. Pick extract-to-method or duplicate-nm-call. |
| MED-1 | MEDIUM | D0 does not probe confidence distribution | `stranger_leg_confidence_floor` default is invented, not D0-derived. |
| MED-2 | MEDIUM | "Two options, pick at build" | No-confidence-producer branch: adjudicate to fail-CLOSED with opt-in list. |
| MED-3 | MEDIUM | Cooldown-key fusion drift | Stranger cooldown key must use `_camera_key_for_sensor(entity_id)` to match base fusion. |
| LOW-1 | LOW | Route-reason composition undefined | Use a fixed enum (four values), not a tuple. |
| LOW-2 | LOW | Stranger-emission snapshot handling unspecified | Reuse base snapshot; state it. |

---

## Verdict

**FIX-PLAN-FIRST.** Fix CRIT-1, HIGH-1, HIGH-2 in the plan text before build dispatch. MED-1/2/3 and LOW-1/2 should be fixed in the plan for cleanliness, but each has a clear default the reviewer has already proposed — a plan revision that accepts these defaults inline is sufficient. No new operator turns required.

Post fix-in-plan: dispatch builder against a Tier 2-DB cycle with the three framing-disjoint reviewer axes as spec'd, extended per CRIT-1 (Reviewer B enumerates every hazard-consumer set) and HIGH-1 (Reviewer D calls out `_dispatch_in_flight` and interleaving explicitly in the INV-KP(e) falsification obligation).
