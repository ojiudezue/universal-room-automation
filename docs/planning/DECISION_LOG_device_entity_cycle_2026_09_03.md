# Decision Log — Device/Entity De-fragmentation Cycle (2026-09-03)

**TIER UPGRADE (operator 2026-09-03):** this reorg cycle is **Tier 3**, not Tier 2 — the earlier "Tier 2, don't over-Tier" calibration was for the 6.0.0 identity-consumer cards, not the reorg. Tier 3 = 4 framing-disjoint reviews (A local-correctness ✓, B state-machine ✓, C test-authority-via-per-site-mutation [pending], D adversarial-completeness [pending]) + stated falsifiable invariant + orchestrator independent mutation-verify + **operator checkpoint before deploy**. More operator adjudications inbound ("starting with tier 3") — C/D reviews held until the full set is in.

Operator mandate: drive to completion; **final "mondo" orchestrator + live review** across all deliverables before the ship gate; **operator holds only the ship decision**; I make reasonable adjudications and log them here for audit at the ship gate.

Every autonomous call I make in this cycle is recorded below (newest last). At the ship gate I present this log + the mondo review + live validation.

## Adjudications

| # | Decision | Rationale | Reversible? |
|---|---|---|---|
| 1 | **Tier 2** for the cycle, NOT Tier 3 | Operator calibration; nesting/consolidation/naming/has_entity_name are low-risk (identifiers stable → no re-registration). | — |
| 2 | **De-fragmentation deliverable gets a hard acceptance gate** (entity_id + unique_id preserved, 0 new `_2`, entity count stays 4626, no orphans, live-registry verified) despite Tier 2 | The ownership migration is the one real `_2`/orphan hazard on a live 4626-entity system; the gate is the minimal safeguard, not Tier-3 ceremony. | — |
| 3 | **D4 naming = Option 3** (distinction from nesting; rooms untouched, no renames) | Operator-decided. Zero room-device churn; resolves the defect without cosmetic churn. | via config later |
| 4 | **`SECURITY-CENSUS-UNKNOWN-WIRE-1` → parked** (defer + measure) | Operator call: auto-lock is only as safe as the unknown-count FP/FN rate; measure first. Revive: measure FP/FN then wire. | yes (revive) |
| 5 | **`LAST-RESIDENT-EGRESS-ARM-1` → parked** (parsimony) | Operator call: existing all-away arm covers it; marginal gain (arm a few min earlier) doesn't pay for the ingredient risk + is gated on the ~0%-attach producer. Revive: producer lands + measured arm-lag gap. | yes (revive) |

| 6 | **De-frag confirmed a plain relocation (no migration hook)** | D0 registry probe: 17-entity migration set, **17 SAFE / 0 BLOCKED** — all unique_ids entry-independent, so re-homing the config_entry_id re-registers in place with no `_2` mint. Split counts matched the screenshots exactly. Downgrades D1 risk from MEDIUM to LOW-MEDIUM. | — |
| 7 | **Do NOT "clean up" the space in `..._person_oji udezue_next_room_accuracy`** | Literal space is SAFE as-is; any string change would mint a `_2`. Hands off during D2/D3. | — |
| 8 | **Delete both dead `coordinator_music_following` device records** (CM + PARENT, 0 entities each) | Retired identity, zero entities, safe. Via registry, not a code no-op. | irreversible — verified 0 entities first |

| 9 | **SCOPE-DOWN D2** — consolidate only the genuine duplicate-authoring (music_following 3 sites, notification_manager 3 sites) + the base.py model race; DEFER the full one-DeviceInfo-per-identity consolidation (100+ inline sites: hvac 38, CM 23, energy 22, presence 21) to a separate parked hygiene item | Plan-review found INV-2 was a 10× larger diff than estimated and it is NOT what causes the split (the split is the branch-forwarding, fixed by D1). Marginal-benefit + keeps the cycle Tier-2-sized. **This is a scope call I made — flagging for your audit.** | park (revive as hygiene cycle) |
| 10 | **`ReconcileHealthSensor` + `IntegrationHouseStateSensor` STAY on the INTEGRATION entry** | Both resolve to `(DOMAIN, "integration")` = Whole House (verified AST). The plan wrongly listed ReconcileHealthSensor as a migration target — moving it would MANUFACTURE the split defect on the one clean device. | — |
| 11 | **The 10 `aggregation.py`-hosted coordinator entities need a CM-side setup split, not a branch-move** | `async_setup_aggregation_sensors/_binary_sensors` hard-return on non-INTEGRATION entry_type, so the branch-move idiom can't reach them. Build must split a `async_setup_cm_hosted_aggregation_*` called from the CM entry. Higher-surface than the D0 estimate, still LOW-MED risk (unique_ids SAFE). | — |

| 12 | **Build fix-up dispatched** after 2 framing-disjoint build-reviews (A correctness+mutation, B lifecycle+setup-order) both FIX-REQUIRED | B1 (CRITICAL) binary-sensor class-name collision — CM grabbed the Whole-House SafetyAlert/SecurityAlert pair, orphaning the coordinator pair + making a NEW split; B2 (CRITICAL) HA sets up entries concurrently so the 8 per-person CM sensors skip every boot → `async_at_started`; B3 (HIGH) D-NEST cold-boot sweep for room/zone; A-HIGH-1 5 v460 tests unupdated; A-HIGH-2 the exactly-once (_2-prevention) guard was deleted not replaced + wire-in unanchored. All in the D1b aggregation-split — the delicate part. | — |
| 13 | **Validator full-suite name-diff is the test authority, NOT the builder's -k report** | The builder's `-k "device or defrag…"` filter MISSED test_v460_d4_d5_registration.py → it reported 3 (wrong) failures and missed 5 real cycle-introduced ones. Not dishonesty — a scoping miss. Every build report's test claims get validator-confirmed via full name-diff before ship. | — |
| 14 | **`CoordinatorEnabledSwitch` (switch.py:236) latent second-authoring of coordinator device identity — ACCEPT this cycle, card latent** | Both reviewers: the identifier/name/model are parameterized; all 7 call sites match canon exactly, so no model race is reachable today. But it's a genuine second author — a future divergent literal wouldn't be caught. Card it (folds into the parked DEVICE-INFO-HELPER-CONSOLIDATION-1). | card |
| 15 | **Pre-existing shadowing noted (not this cycle):** `OccupantCountSensor` defined twice in sensor.py (:1807 house, :2917 room) — the later wins, so aggregation.py:218 builds the room class with (hass,entry) args | Present on develop unchanged (A verified). Out of scope; card separately as a latent bug. | card (separate) |

| 16 | **Validator CLEAN (orchestrator-verify)** — full-suite name-diff identical 62/62 (0 new), all 5 de-frag mutation gates RED-on-neuter load-bearing | Independent confirm (full suite, not -k). B1 import / exactly-once _2-gate / B2 async_at_started / oji-space / dead-device all proven. Build+fix-up solid on correctness+test-authority. Tier-3 C/D still owed. | — |
| 17 | **Adjudication #2 (room-nesting) — already satisfied** | Build's D-NEST catch-all nests room devices under Whole House; per-room reload preserved (own entry). No plan change needed. | — |
| 18 | **Adjudication #3 (per-zone/per-coordinator individual reload) — SURFACED as a scope decision, NOT folded** | Reload is per-config-entry; zones share one ZM entry, coordinators share one CM entry → per-item reload needs each as its own entry = a config-TOPOLOGY migration (split 2 entries → ~15 + entity re-home at scale). Big + high-risk (largest _2/orphan hazard) for a convenience gain. Recommended: ship this reorg (visual tree + de-frag + per-room reload already delivered), card the topology cycle separately. AWAITING operator fold-in-vs-card decision. | — |

| 19 | **Menu-consistency (operator "finally audit the menus") — SPLIT: fold icon-normalization into the reorg, card the zone-picker→menu conversion as a Tier-2 fast-follow** | Read-only menu audit (agent ae6ad690f4) found URA is ALREADY `async_show_menu` everywhere except two instance-pickers. The operator's "zones use a dropdown, CM uses a menu" = `manage_zones` (config_flow.py:7900) routes to a `SelectSelector` LIST **form** to pick a zone, while CM lists domains directly in its menu; `ai_rule_list` (:11246) is a second form-picker (DROPDOWN). **Icon fix** = ~8-12 label edits in `strings.json`+`translations/en.json` (un-iconned `signal_responses`/`add_zone`/`setup_zone`/config-flow `init_chain_*`/`init_ai_*`; ✓ vs ✅ drift) — pure translation strings, no code path, no test impact → **fold in**. **Zone-picker→menu** threads the v4.7.5 raw-vs-canonical-zone contract + shared-thermostat banner + a guarding AST test (`test_v475_d2_picker_does_not_call_iter_canonical`) → its own Tier-2 fast-follow, NOT folded into a Tier-3 device-tree cycle (blast-radius separation). Closes the adjudication set. | icons: via cycle; zone-picker: card |

| 20 | **CORRECTION to adjudication #16 (Review C, C-MEDIUM-3): test authority was OVERSTATED.** #16 claimed "all 5 de-frag mutation gates RED-on-neuter load-bearing." Review C's per-site drills show only the *literal-revert* form goes RED; of the five, only M7 (D-NEST stamper) is genuinely BEHAVIOURAL, M6 (oji-space unique_id) is an acceptable string oracle, and M3a/M4a are string-mirrors their behavioural equivalents (M3b/M4b) defeat while staying green. The real coverage picture: both D1b coroutines, the `_2` runtime guard, the D1a double-registration, the B1/B2/D-NEST wire-ins, and the dead-device deletion are all **neuter-deletable with a green suite** (C-CRITICAL-1/2/3, C-HIGH-1/2/3, C-MEDIUM-1). Fix-up FIX-6..FIX-10 add behavioural anchors. | — |
| 21 | **D3 reframed (Review C, C-MEDIUM-2): D3 is INERT, not a race fix.** `BaseCoordinator(ABC)` is not an HA `Entity`, so its `device_info` property is never read by HA; `_coordinator_device_info`'s only consumer is that dead property. The "model first-writer-wins race" D3 claimed to fix was never reachable through base.py (same on develop). Decision: KEEP the base.py routing as harmless future-proofing (correct IF BaseCoordinator ever becomes an Entity) but STOP presenting it as a race fix; delete the dangling docstring ref (test_device_entity_architecture.py:168 cites a nonexistent test). The genuine device identity authors are the six inline sensor.py helpers (scoped out in adjudication #9). | — |
| 22 | **Tier-3 C + D both FIX-REQUIRED → one consolidated fix-up dispatched (FIX-1..FIX-11).** Review D: 5 leaks (D-LEAK-1 HIGH per-person no-discharge one-shot; D-LEAK-2 MED-HIGH sweep no re-arm; D-LEAK-3 MED runtime-room unparented; D-LEAK-4 MED dead-device deletion targets nonexistent identifier — CONFIRMED via live registry; D-LEAK-5 MED unsubs not on unload). Review C: hollow test anchors across the delicate D1b split + inert D3. Clean bills: INV-DEFRAG#1/#2 (identity byte-stable, 0 unique_id changes, oji-space intact), INV-DEFRAG#4 (211/211 coordinator entities under CM, 0 under INTEGRATION — independent AST re-enumeration), INV-NEST zero declarative via_device. After fix-up: re-verify (re-run C's mutations on fixed sites + D's enumeration) BEFORE the ship checkpoint. | — |

| 23 | **Orchestrator independent mutation-verify CAUGHT the fix-up's FIX-6/7/10 anchors as STILL HOLLOW → sent back.** The fix-up (commit 6465e5841) claimed the new FIX-6/7/10 anchors "go RED if the coroutine body is neutered." I falsified this directly: inserted an early `return` after the docstring of `async_setup_cm_hosted_aggregation_sensors` (whole body dead), cleared .pyc, ran the 7 fix6/fix7/fix10/cm_hosted tests → **7 passed, 0 failed** (green on full neuter). They are `re.search`-on-source-text asserts — Bug Class #62 reproduced more elaborately (4th consecutive hollow-wire-in offense per `feedback_wire_in_anchor_mandatory`). Do NOT trust reviewer/builder summaries — the Tier-3 mandatory orchestrator re-run is exactly what caught this. Send-back reuses the EXISTING execution harness (test_v460_d4_d5_registration.py runs async_setup_aggregation_sensors; test_v462_single_registration_invariant.py is the behavioural exactly-once pattern) — the builder's "needs substantial new scaffolding" was wrong. Builder must self-verify RED-on-neuter and paste output before reporting. Tree restored clean after my drill. | — |

| 24 | **Round-2 fix-up independently VERIFIED (orchestrator re-run, not builder summary).** Builder commit 5b908a560 added quality/tests/test_device_entity_cm_hosted_behavioural.py (6 tests that actually `await` the CM-hosted coroutines, reusing the test_v460/test_v462 harness). I re-ran the mutations MYSELF: (a) early `return` in `async_setup_cm_hosted_aggregation_sensors` → **4 RED**; (b) early `return` in `_binary_sensors` → **1 RED**; (c) delete the CM-branch `async_schedule_device_tree_sweep(hass)` call while leaving the import (the exact M9 mutation) → FIX-9 **RED** (positional call-string anchor, not bare-name). Restored clean after each. INV-NEST re-checked on the final tree: zero declarative `via_device=` (only the _devices.py docstring). Residual regex-only anchors (FIX-2 integration-also-schedules, FIX-5 unsub tracking) are lower-risk sites additionally covered by the behavioural D-NEST stamper test + live validation; FIX-4 deletion is scoped-grep + directly live-gated (post-restart: zero `coordinator_music_following` devices). Test authority now adequate for ship. | — |

_(appended as the cycle proceeds — plan/review/build adjudications, fix-up calls, any scope trims)_

## Falsifiable invariant (Tier-3 — D's sole job is to break this)

**INV-DEFRAG (identity + ownership preservation):** For every URA entity, after this cycle:
1. `entity_id` AND `unique_id` are **byte-identical** to pre-cycle (verified via live registry name-diff), and
2. **zero** new `_2`-suffixed entities are minted, and
3. total entity count is **preserved** (baseline 4626), and
4. **no coordinator entity is split-owned** across two config entries — every coordinator entity is owned by exactly the CM entry (none still forwarded from the INTEGRATION entry), and
5. **no entity is orphaned** (owned by a deleted/dead device).

**Falsified by** any of: a unique_id that changes; any new `_2`; any entity-count delta not explained by the 2 deliberately-deleted dead `coordinator_music_following` device records (which had 0 entities → count unaffected); any coordinator entity still reachable from the INTEGRATION entry's platform forward; any orphaned entity.

**INV-NEST (device tree, 2026.9-safe):** every coordinator device resolves `via_device_id → CM device → Whole House`; zones and rooms resolve `via_device_id → Whole House`; and there is **zero declarative `DeviceInfo(via_device=…)`** anywhere in the component (the HA 2026.9 hard `RuntimeError` source). **Falsified by** any `via_device=` in a DeviceInfo constructor, or any coordinator/zone/room device with no via_device_id after a cold boot.

D re-enumerates the ENTIRE surface (pre-existing code included, not just the diff — per the v5.5.3 D-HIGH-1 lesson) and must supply a concrete legal-config reachable repro for any leak.

## Live-registry ground truth (2026-09-03, v5.93.1 pre-reorg — via ha_get_device, mount was down)

Pulled the live device registry to resolve Review-D D-LEAK-4. The fragmentation is present as **same-identifier duplicate device records across two config entries** (entry `01KJEC3FYPYAGBQKZWC94CR8GR` and entry `01KAYV8P69B381KCK3516YVM76`):

| Identifier | device_id (entry) | entities | note |
|---|---|---|---|
| `coordinator_manager` | `0a83…` (…C94CR8GR) | 50 | core CM (house_state, bayesian, chatter, db) |
| `coordinator_manager` | `df3b…` (…KAYV8) | 10 | the per-person next_room_accuracy + routine_status sensors (the D-LEAK-1 set) |
| `security_coordinator` | `29af…` (…C94CR8GR) | (main) | |
| `security_coordinator` | `29c9…` (…KAYV8) | 6 | Outside/Perimeter track sensors |
| `music_following_coordinator` | `3e9b…`/`8609…` | 1 | LIVE (music_following_health) — do NOT touch |
| **`coordinator_music_following`** | `236d…` (…C94CR8GR) | **0** | DEAD, disabled_by=user, sw 3.6.29 |
| **`coordinator_music_following`** | `1cdb…` (…KAYV8) | **0** | DEAD, disabled_by=user, sw 3.6.29 |

**D-LEAK-4 CONFIRMED as a real defect (upgrade from "unverified"):** the build's dead-device deletion (`__init__.py:4217`) targets `identifiers={(DOMAIN, "music_following")}` — an identifier **no device has**. The two actual dead records are `(DOMAIN, "coordinator_music_following")`. So the deletion is a **silent no-op** and both dead records persist. Fix: target `coordinator_music_following`, and iterate ALL matching 0-entity records (there are TWO, one per config entry — `async_get_device` returns only one).

**Consequence for the acceptance gate (INV-DEFRAG#5 / "no orphans"):** after the reorg forwards all coordinator platforms from one entry, the per-person sensors (now on `df3b`) and the `29c9` security set re-home to the canonical single device per identifier; the losing duplicate device records go to 0 entities. Whether HA's reload merges the same-identifier duplicates or leaves orphaned empty devices **cannot be proven statically** — it is the #1 live-validation check: post-restart there must be exactly ONE `coordinator_manager` device, ONE `security_coordinator` device, and ZERO `coordinator_music_following` devices.

## Deliverables (from the plan, de-frag-led)
- **D0** — live registry probe: which entities are owned by the parent entry vs the CM entry (measure-before-build).
- **D1 (elevated)** — de-fragment coordinator devices: forward all coordinator platforms from the CM entry only; parent entry hosts only Whole House; delete the dead `URA: Music Following` device. **Hard acceptance gate (see #2).**
- **D2** — consolidate `_*_device_info()` helpers into `_devices.py`; kill inline dups (music-following 3×, NM 3×).
- **D3** — fix the model first-writer-wins race (`base.py` vs sensor helpers).
- **D-NEST** — restore device nesting via `dr.async_update_device(via_device_id=…)` (coordinators → CM → Whole House; zones → Whole House).
- **D5** — `has_entity_name` per-entity audit.
- **D6** — reload-safety (device-registry writes only; census-toggles precedent).

## Ship gate (what the operator sees)
1. This decision log (all adjudications).
2. The mondo cross-cutting review outcome.
3. Live post-deploy validation — EXPANDED (operator 2026-09-03: "More post start validation? You need to exercise the menus etc"). A device-registry row check alone is too thin for a cycle whose visible surface is the device tree + the config/options-flow menus. Full post-restart battery (browser-driven where it's a UI surface), results written back into README_v5.94.0.md:

   **A. Device tree (registry + Devices UI):** via `ha_get_device` AND the Settings→Devices UI — exactly ONE `coordinator_manager` device, ONE `security_coordinator` device, ZERO `coordinator_music_following` devices; every coordinator nested `→ CM → Whole House`; zones + rooms nested `→ Whole House`. (Pre-deploy live baseline captured: 2 CM, 2 security, 2 dead-music, CM via_device_id=null — so the diff is provable.)

   **B. Entity integrity:** entity count preserved (~4626 baseline), 0 new `_2`, the 8 per-person sensors present (the D-LEAK-1 set: `ura_person_<p>_next_room_accuracy` + `_routine_status` × 4), no coordinator entity `unavailable`/orphaned.

   **C. Menus EXERCISED (Claude-in-Chrome, read-only — navigate + observe, do NOT submit/save any step):**
   - **Options flow** (house/integration entry): the `init` menu renders with consistent icons incl. the newly-iconned `📶 Signal Responses`; open a coordinator submenu (e.g. `🌡️ HVAC` → settings/dynamic_preset/baseline menu) and back out.
   - **Config flow add-entry:** start "Add entry" → `entry_type_select` shows `🚪 Add a Room / 🗂️ Add a Zone / ⚙️ Add a Coordinator` (add_zone now iconned); reach `post_integration_setup` (`🗂️ Set Up a Zone First`, `✅ Finish Setup`) — then **CANCEL** (no entry created).
   - Confirm no config-flow exception in the log during navigation.
   - **Caveat noted:** the zone instance-picker is still a `SelectSelector` form (fast-follow `MENU-ZONE-PICKER-1`) — confirm it still opens; it's the known odd-one-out, not a regression.

   **D. Per-entry reload:** reload ONE room entry and ONE coordinator-manager entry individually (`homeassistant.reload_config_entry`) → scoped reload succeeds, no cascade to siblings (sibling `last_changed` invariant), device tree re-nests correctly after reload.

   **E. Logs:** clean boot, no new "Error adding entity None", no via_device RuntimeError, no config-flow tracebacks.

   **F. README write-back:** replace the prospective Live section with a `Validated <date>` table, one row per A–E with observed evidence (entity_id/attr, device_id, screenshot/log line).
