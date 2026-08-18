# Plan Review — Census Toggles → Device Switches

**Reviewed doc:** `docs/planning/PLANNING_census_toggles_to_device_switches.md`
**Tier:** 2 (single adversarial plan review pre-build)
**Reviewer:** ura-reviewer (plan-review pass)
**Date:** 2026-08-18
**Verdict:** **PLAN-NEEDS-FIXES** — 1 CRITICAL, 2 HIGH, 3 MEDIUM/LOW. Do not dispatch a build until CRIT + HIGHs are answered in the plan.

---

## Independent verification — consumer table (re-run of the plan's greps)

`grep -rn CONF_FACE_RECOGNITION_ENABLED\|CONF_ENHANCED_CENSUS\|CONF_EGRESS_IDENTITY_ENABLED custom_components/`
plus `grep _face_recognition_enabled\|egress_identity` in the cached-consumer files.

| Flag | Consumer file:line | Read shape | Cached? | Refresh path today |
|---|---|---|---|---|
| `CONF_FACE_RECOGNITION_ENABLED` | `transit_validator.py:259` (async_init) | `merged.get(..., False)` → `self._face_recognition_enabled` | boot-cached; used at 546, 768, 419 | none — needs entry re-setup |
| `CONF_FACE_RECOGNITION_ENABLED` | `presence.py:2451` (`async_setup`) | merged → `self._face_recognition_enabled` | boot-cached; used at 4465 | none — needs re-setup |
| `CONF_ENHANCED_CENSUS` | `camera_census.py:2970` (`_is_enhanced_census_enabled`) | `merged.get(..., True)` | live per-call | fresh every tick |
| `CONF_ENHANCED_CENSUS` | `__init__.py:2253` (setup branch) | `merged.get(..., True)` | structural (only read at setup) | none — needs re-setup |
| `CONF_EGRESS_IDENTITY_ENABLED` | `camera_census.py:2866` (`_is_egress_identity_enabled`) | `merged.get(..., DEFAULT)` | live | fresh every call |
| `CONF_EGRESS_IDENTITY_ENABLED` | `camera_census.py:1886, 2889, 2943, 3657` | via `_is_egress_identity_enabled()` | live | fresh |
| `CONF_EGRESS_IDENTITY_ENABLED` | `transit_validator.py:1094` | via `census._is_egress_identity_enabled()` (indirect) | live | fresh |

**Result:** consumer enumeration in the plan is COMPLETE. Reload-vs-live classification matches. Small imprecision only: plan says `transit_validator.py:1094` reads the merged dict directly — it actually calls `census._is_egress_identity_enabled()`. Same live-read effect; note for accuracy.

---

## Reload-target verification — the critical finding

The plan's precedent (`DomainCoordinatorsSwitch`, `switch.py:425/433`) reloads `self._entry.entry_id`, which for `ENTRY_TYPE_INTEGRATION` IS the URA **parent** integration entry. That is precisely the entry documented in `~/.claude/projects/.../feedback_parent_entry_reload_watchdog_hazard.md` as having caused a **~5-minute HA-core outage on 2026-06-03** (parent-reload → cascading child re-setup → event-loop stall → supervisor watchdog restart). A second empirical incident on **2026-08-07** produced the 2026-08-15 mitigation cycle: the newly-added integration-entry branch in `_async_update_listener` (`__init__.py:6608-6668`) plus the allowlist `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py:5929`, v1 = `{CONF_CAMERA_PERSON_ENTITIES}` only) and `_dispatch_integration_key_signals`. **None of the three census keys are on that allowlist.**

This flips the plan's dismissive "no NEW hazard" framing on its head — see PLAN-FINDING-1.

---

## PLAN-FINDING-1 (CRITICAL) — Double-reload / update-listener collision; `requires_reload=False` is dead code

**Mechanism.** `async_update_entry(entry, options=…)` fires all update listeners registered on `entry` (HA core behavior; URA registers `_async_update_listener` at `__init__.py:4393` for the INTEGRATION entry). Trace what happens when `_IntegrationOptionsSwitch` toggles:

1. Switch calls `hass.config_entries.async_update_entry(entry, options={..., KEY: v})`.
2. HA notifies update listeners → `_async_update_listener` runs.
3. `entry_type == ENTRY_TYPE_INTEGRATION` branch at `__init__.py:6608` computes `changed_keys = {KEY}`.
4. `changed_keys.issubset(INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS)` is **False** for all 3 census keys (allowlist contains only `CONF_CAMERA_PERSON_ENTITIES`).
5. Falls through to the tail `hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))` at `__init__.py:6672`. **Parent-entry reload fires.**
6. Meanwhile the switch (if `requires_reload=True`) awaits its OWN `async_reload` — double reload for face-matching + smart-counting; single reload for name-people-at-doors that the plan claims does NOT reload.

**Consequences:**
- **D3 acceptance criterion "Toggling `switch.ura_name_people_at_doors` does NOT trigger a reload" is FACTUALLY UNACHIEVABLE** as designed. The switch's `if self._requires_reload:` skip is dead code — the update listener beats it to the reload.
- **The plan re-exposes the operator to the exact hazard the 2026-08-15 cycle just mitigated for one key**, but for THREE new keys AND promotes the toggle to a casual device-tile control (higher fire rate than the current options-flow submit).
- The proposed `test_name_people_at_doors_switch_does_not_reload` test will only "pass" if it patches `async_reload` in a way that misses the listener-scheduled task — i.e., it will be a hollow anchor (see feedback_hollow_test_anchors).

**Required plan edit (choose one; option A strongly preferred):**

- **(A) Co-opt the 2026-08-15 suppress mechanism.** Add all three keys to `INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` with proper discharge signals in `_INTEGRATION_KEY_SIGNAL_TABLE`, matching the pattern established for `CONF_CAMERA_PERSON_ENTITIES`. Wire consumers:
  - `CONF_EGRESS_IDENTITY_ENABLED`: no signal needed (both consumers already live-read) — allowlist alone suffices; discharge tuple = `()`.
  - `CONF_FACE_RECOGNITION_ENABLED`: needs a new `SIGNAL_URA_FACE_RECOGNITION_CHANGED` subscribed at `transit_validator.py:~340` and `presence.py:~2455` to re-run the same merged.get read into `self._face_recognition_enabled`. Structurally identical to the transit-config discharge — small, testable, and eliminates the reload entirely.
  - `CONF_ENHANCED_CENSUS`: BLOCKED — the `__init__.py:2253` setup-time branch is structural; there is no in-place equivalent without refactor. So this key CANNOT be safely added to the allowlist without additional work. Two options: (i) keep this switch OPTIONS-ONLY (do not ship a switch for it — see also PLAN-FINDING-5); or (ii) treat it as an explicit "reload on toggle" surface with UX warning (see option B).
  Then the switch simply does `async_update_entry` — no explicit `async_reload` — and the listener's suppress branch handles the correct behavior.

- **(B) If shipping as specced, correct the plan honestly:** state that ALL three switches trigger the parent-entry reload (via the listener fall-through), delete the `requires_reload` parameter as misleading, delete the `test_..._does_not_reload` acceptance criterion, add a warning to each switch's docstring + friendly-name description ("Toggling reloads the integration; may cause a multi-minute HA outage"), and update the README's Live-Validation table accordingly. This is worse product than (A) but at least it isn't a false claim.

---

## PLAN-FINDING-2 (HIGH) — Watchdog-hazard downplay + fabricated `~5s` cost

D3 says: *"The user-visible cost is one HA reload (~5s) per toggle of this specific switch"* and *"no NEW hazard is introduced. If the operator observes the watchdog trip on toggle, that is a pre-existing hazard applying to at least 8 other switches and is out of scope here."*

Both statements are wrong given fresh evidence in-repo:
- The empirical outages of record are ~5 MINUTES (2026-06-03 during v4.7.18.3 live-validation; 2026-08-07 which triggered the 2026-08-15 mitigation cycle) — off by ~60×.
- The hazard is not merely "pre-existing"; the current cycle is the FIRST to promote these three keys from Configure → Camera Census → Submit (rare, deliberate) to a device-page tile (casual, frequent). Higher fire rate against the same hazard IS new blast radius even with an identical per-fire mechanism.
- The 2026-08-15 mitigation was scoped narrowly (one key) specifically because the audit classifies these three as `UNSAFE` for in-place apply without cached-consumer refactor. The plan's Institutional Context cites that audit but does not carry its conclusion forward to the reload cost.

**Required plan edit:** correct the cost number to "~5 minutes worst case, per feedback_parent_entry_reload_watchdog_hazard"; drop the "no new hazard" framing; explicitly connect this cycle to the 2026-08-15 hazard-mitigation code, and either extend that mechanism (preferred, PLAN-FINDING-1(A)) or disclose the risk in the switch UX + README.

---

## PLAN-FINDING-3 (HIGH) — D3 test `test_name_people_at_doors_switch_does_not_reload` is hollow / infeasible

Direct consequence of FINDING-1. As specified ("patch `async_reload`; toggle switch; assert it was NOT called") the test can only pass if it patches the switch method's reference to `async_reload` in isolation, missing the listener-scheduled task — i.e., it proves nothing about production behavior. This is the exact hollow-anchor risk called out in `feedback_hollow_test_anchors`. The oracle must observe the FALL-THROUGH branch, not the switch's own return path.

**Required plan edit:** re-write the acceptance criterion in terms of "no `Options changed for ... scheduling reload` log line" AND "no supervisor `Reloading configuration entry` on the integration entry_id within N seconds of the toggle." A test that only patches `async_reload` inside the switch class is a false green.

---

## PLAN-FINDING-4 (MEDIUM) — INV-1 as stated is stronger than the tests prove

INV-1: *"the value returned by every consumer read is identical whether the flag was last set via the Switch entity or via the Camera Census options-flow step, at any time after the write has settled."*

The two `_face_recognition_enabled` consumers are boot-cached and only re-read at `async_init` / `async_setup`. Between "options written" and "reload settles + re-caches", INV-1 at the consumer layer is briefly false — the cached value trails the store. The D4 tests handle this correctly (they assert AFTER `async_init`), but the invariant is not falsifiable in the shape written unless "settled" is defined as "reload complete AND cached consumers re-initialized."

**Required plan edit:** either scope INV-1 to `entry.options[KEY]` ⇔ `switch.is_on` (surface invariant) OR pin the discriminating observation to post-reload-settle. Add an explicit second invariant INV-2 covering cached-consumer re-hydration if you want the consumer layer in the sprint contract.

---

## PLAN-FINDING-5 (MEDIUM) — Marginal-benefit pushback owed on Smart People Counting

Per `CLAUDE.md#Marginal-Benefit Decomposition`, decompose:

- **Benefit of the SIMPLEST version** (ship only egress-identity as a switch — it's already designed live, allowlist-able with no discharge needed, and default-OFF so operator toggling is legitimate observability):
  captures ~100% of the "casual toggle a kill switch from the device page" use case for the ONE flag that was designed for it.
- **Marginal benefit of adding Smart People Counting**: promoting the heaviest of the three (structural setup branch, default TRUE meaning operator rarely toggles, reload cost = documented multi-minute outage risk) to a device tile that looks live-tunable but isn't. Marginal user benefit: near zero (operator toggles this maybe once per release cycle to compare engines).
- **Marginal ingredient risk**: adds a second casual click target for the parent-reload hazard; the switch entity implies live-tunability that the underlying `__init__.py:2253` structural branch cannot honor without refactor.
- **Recommendation**: **do not ship `switch.ura_smart_people_counting`**. Keep it options-only until (or unless) `__init__.py:2253` is refactored to be re-runnable in-place. This is exactly the "park the fancy design, don't delete it" outcome the rule prescribes; record the trigger to revisit as "if operator observation says census-engine toggle is legitimately frequent."

If the operator disagrees and wants all three shipped, that's fine — but the plan should carry the recommendation and the operator's override, not silently deliver all three.

---

## PLAN-FINDING-6 (LOW) — Consumer table imprecision

`transit_validator.py:1094` is an indirect call to `census._is_egress_identity_enabled()`, not a direct merged-dict read. Fix the row for clarity; no behavioral consequence.

---

## Items the plan gets right

- Option (B) source-of-truth choice is correct and well-argued; divergence-by-construction reasoning is airtight for the storage layer.
- Consumer enumeration is complete (verified above).
- Defaults match `config_flow.py:2956-2978` exactly (verified: `face_recognition=False`, `enhanced_census=True`, `egress_identity=DEFAULT_EGRESS_IDENTITY_ENABLED` = False).
- Entity-id pinning + no-migration reasoning is sound (verified: none of the three locked entity_ids exist today).
- Institutional-context section is present and largely accurate — one blind spot: it consulted `AUDIT_integration_options_reload_classification.md` but did NOT consult the freshly-shipped mitigation code (`INTEGRATION_OPTIONS_RELOAD_SUPPRESS_KEYS` and `_dispatch_integration_key_signals`) that the plan should have co-opted.

---

## Verdict

**PLAN-NEEDS-FIXES.** Do not dispatch build. Required updates before build:

1. Resolve PLAN-FINDING-1 with option (A) or (B) explicitly, and update D1/D3 accordingly.
2. Correct the reload cost in D3 per PLAN-FINDING-2.
3. Rewrite the `does_not_reload` acceptance criterion per PLAN-FINDING-3.
4. Sharpen INV-1's "settled" clause per PLAN-FINDING-4.
5. Add the marginal-benefit pushback for Smart People Counting per PLAN-FINDING-5 and record the operator's decision.
6. Fix consumer-table row per PLAN-FINDING-6.

After the plan is amended, the build tier remains 2 (per plan's classification), but the review protocol for the built code should still verify the listener-collision path independently (Reviewer B "lifecycle + reload correctness" framing — expand explicitly to trace the update listener AND the switch's own `async_reload`, in that order).
