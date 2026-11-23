# Interior vision ship 2: review B (integration, lifecycle, DB)

Branch `feature/interior-vision-ship2` @ 0bc751d8, worktree `.claude/worktrees/builder-interior-ship2`, diff `git diff develop...HEAD` (develop has not moved since the merge-base for any file this review touches). Tier 2-DB, framing B. Read first, completely: `docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` (incl. §10 ledger), plan §9.D3 / §6.3 / §8, the contract. Nothing in the §10 ledger is re-asserted here.

**Verdict: FIX-REQUIRED** (one MEDIUM: an existing security-ack test is RED on this branch). Everything else is LOW.

Note: during this review another agent's mutation drill was live in the same worktree (`interior_vision.py:337`, `required.append("affect")` replaced by `pass`). I did not touch it. The one failure below is independent of that file (mechanism shown, and the test passes on a develop-based tree).

## Findings

| ID | Sev | Site | Finding / repro | Bug class |
|---|---|---|---|---|
| B-M1 | MEDIUM | `domain_coordinators/notification_manager.py:3468` (`_is_authorized_to_ack` now calls `self._operator_person_entities()`) | `quality/tests/test_notification_hygiene.py::test_fix5_authority_gate_behavior` FAILS on the branch: it execs `_is_authorized_to_ack` alone against a `_Fake` that has only `_config`, so `AttributeError: '_Fake' object has no attribute '_operator_person_entities'`. Passes on a develop-based tree (`builder-step8-d2`, 1 passed). Production behaviour is equivalent (same list, same order, same tuple returns), but the C-HIGH-1 security-ack authority anchor is RED, so the suite gate fails and the security-ack contract has no live test until fixed. Fix: bind the helper in the test's namespace (exec both functions, or give `_Fake` the method), keep the four assertions. | Test fixture drift after a refactor (hollow anchor risk, #62 adjacent) |
| B-L1 | LOW | `interior_vision.py` `_run`: `files = await self._stage_dewarped(...)` then `finally: if files: await self._unstage(files)` | Cancel (teardown, reload, HA stop) while `_write_stage` runs in the executor: the thread finishes writing `iv_<stamp>_<i>.jpg`, the coroutine gets `CancelledError` before `files` is assigned, the `finally` sees `files == []`, nothing is deleted and `interior_frames_left` never fires. Cleared only by the next `_setup_interior` sweep; on a presence-only reload the new producer's sweep can list the folder before the old thread's write lands, so the still stays until the next restart. Repro: Foyer (lens `360`) describe, teardown during the dewarp executor job. Fix: choose the paths before the await (deterministic `iv_<stamp>_*` prefix) and on `CancelledError` remove by that prefix in the executor. | Untracked side effect on cancel (INV-IV-NO-STORE discharge gap) |
| B-L2 | LOW | `interior_vision.py` `InteriorVisionSampler.calls_today` / `cost_today` (RAM, `_roll_day`) | Counters reset on every restart / producer rebuild, so the daily cap and cost cap are per-process-lifetime, not per day. Crossing vision rehydrates its counter from DB rows (P3-D5). Cost exposure is tiny (on-demand, 60 s cooldown, est. $0.0003/call), so LOW; state it in the README or rehydrate from `interior_description` rows (note: error outcomes write no row, so a row count would under-count). | Restart resilience |
| B-L3 | LOW | `person_sighting.py` `_log_description_row` (`attrs["affect"]`) | The affect field is written to the durable `memory_episodes` row whenever `INTERIOR_DESCRIBE_AFFECT_ENABLED`. R16 polices Python attribute reads only; any SQL / memory-query reader of the row gets affect with no guard. The plan (§9.D3, closure N7) talks about reply and attribute readers, not the DB copy. Decide: drop affect from the row, or record the DB copy as a stated R16 limit. | Concept leak past a guard |
| B-L4 | LOW | `notification_manager.py:4769` `_describe_counts` | Written (`describe_unresolved_requester`, `_denied`, `_cooldown`, `_refused`, `_scheduled`), read nowhere (no sensor attribute, no diagnostics). Denied requests are therefore invisible. Surface them on the NM diagnostics / inbound attributes or drop the dict. | #53 computed-not-consumed |
| B-L5 | LOW | `interior_vision.py` `_describe`: `if self.torn_down: return ""` | `""` means "scheduled" to NM, so during a teardown window NM stamps the cooldown, logs `(describing)` and the requester never gets a reply. Return a refusal string ("Interior vision is not running.") instead. | Silent no-op on lifecycle edge |

## Focus items cleared (with evidence)

**1. Shared-file collisions.**
- `perimeter_enrichment.analyze_crossing_images`: the branch's hunk is byte-identical to 921c9c47's (`diff` of the two `+/-` hunks from the common merge-base: identical). `git merge-tree` of this branch with 921c9c47 gives ONE `def analyze_crossing_images` and no conflict in `perimeter_enrichment.py`.
- `crossing_vision.vision_provider_id`: `git merge-tree develop 921c9c47` and `git merge-tree feature/interior-vision-ship2 921c9c47` both conflict in the same 6 `crossing_vision.py` hunks (P2-D8 is already stale against develop); the refactor adds no new hunk, and the method body region auto-merges. `CrossingVisionShadow._vision_provider_id` keeps its name and returns `vision_provider_id(self.hass)`, the same code with `self.hass` -> `hass`; the inner import from `perimeter_enrichment` is unchanged, so monkeypatches of `_get_integration_config` still apply.
- Crossing vision tests: `test_crossing_vision_shadow.py`, `_p3_first.py`, `_setup_wirein.py` all pass on the branch (in the 616-test run below).

**2. NM inbound.**
- The describe branch sits after the self-echo rail (`:4087`) and the messaging kill, before the command table, and is gated `channel in {"imessage", "whatsapp"}` (`notification_manager.py:4118`). Companion (`:3813-3828`), pushover (`:3961`) and `test_inbound` (`__init__.py:6797`, default channel `companion`) cannot reach it unless a caller passes a text channel name. The cooldown check and the stamp have no `await` between them (`request_room_description` is sync), and the sampler reserves the call before task creation, so two quick requests cannot both pass.
- Security-ack: the factored `_operator_person_entities` returns exactly the old `allowed` list (ack persons, else the first NM person's entity), and `_is_authorized_to_ack` returns the same tuples. Behaviour unchanged; only its test broke (B-M1).

**3. Lifecycle.**
- Sampler call tasks: `hass.async_create_background_task`, held in `sampler.tasks`, discarded on done, cancelled in `sampler.teardown()`, which `_teardown_interior` calls (`person_sighting.py` end of `_teardown_interior`); `async_teardown` calls `_teardown_interior` first. The sampler holds only `hass` and callbacks into its own producer; `tasks` is cleared, so nothing survives a reload except the gap in B-L1.
- Stage folder: swept by a tracked task at `_setup_interior` (before the `INTERIOR_ROOM_RECORDS_ENABLED` early return, so it runs even with records off), cancelled at teardown. Deleted in `finally` on success, error, timeout and cancel during the model call; not on cancel during staging (B-L1).
- RAM store `_room_descriptions`: written only by `_emit_unnamed("description")`; guard owner tables updated (`STORE_ATTRS_OWNER`, `R2_STORE_OWNERS`, `R2_PRIVATE_STORES`, `RECORD_OWNERS`).
- CM no-reload: `interior_vision_daily_calls`, `interior_vision_daily_cost_usd`, `interior_describe_access` are in both `_NO_LIVE_ATTR_KEYS` and `OPTIONS_RELOAD_SUPPRESS_KEYS` (`__init__.py` +7470, +7818), same pattern as `crossing_vision_daily_calls`. The Numbers and the Select are built in the CM branch and write CM entry options.
- Persistence: Numbers and Select read `{**entry.data, **entry.options}` at construction, clamp / validate (an unknown stored option falls back to `operator`), and publish to `hass.data` in `__init__`, so the value exists before the first request; writes go to options. No RestoreEntity needed (options are the source of truth).

**4. DB.**
- `interior_description` rows go through `Database.log_memory_episode`, whose write uses `self._db()`, the single-worker write queue (`database.py:581`). One row per successful description, tracked task in `_interior_tasks`, skipped after teardown. `window_dedup=False`, `dedup_source_ref=False` with a per-record ms `source_ref`.
- Registered in `MEMORY_EPISODE_TYPES` (DAO registry gate `database.py:10723`) and NOT in `MEMORY_WRITER_BACKED_EPISODE_TYPES`; the writer-health check counts only writer-backed types (`database.py:11598-11602`), so a quiet week pages nothing.
- `interior_vision_zero_calls`: fires only with >= 5 requests that REACHED the sampler (resolved target with a group; NM-denied and cooldown requests never count) in 24 h, zero model calls, switch on and both caps > 0; latched until a call happens. Nobody asking = empty trigger deque = never fires. It does fire after 5 requests that all hit `still_source_not_live` / `no_still_source` (Frigate member down), which is the condition its remedy text names. The cost-cap-below-one-call config cannot be reached from the UI (step 0.05 > 0.0003).

**5. Guard R16 and the pin path change.**
- `PINNED_READERS["request_room_description"]` changed from `"notification_manager.py"` to `"domain_coordinators/notification_manager.py"`. `pinned_ok` matches `rel` exactly (`_layer_guard_engine.py:294-301`), so the old pin could never match the real file; the change makes the pin real and does not widen it (still one function). No other pin changed. `test_iv_pinned_readers_clean_on_real_tree_and_pins_are_real` now also checks this pin.
- R16 is additive and never allowlisted (no change to the allowlist total). Owners `person_sighting.py`, `interior_vision.py`. Limits: computed `getattr` names (stated) and the DB copy (B-L3).

## Tests run (serial, `PYTHONDONTWRITEBYTECODE=1`)
17 files (interior vision ship 1 + 2, dewarp, crossing vision x3, NM inbound companion / whatsapp, notification hygiene, safe-word window, layer guard, census trust golden): 615 passed, 1 skipped, 1 failed (B-M1).

## Summary

| Sev | Found | Must fix before ship |
|---|---|---|
| CRITICAL | 0 | - |
| HIGH | 0 | - |
| MEDIUM | 1 | B-M1 |
| LOW | 5 | recommended in the fix-up pass (B-L1, B-L5 are a few lines each) |

Bug classes: test fixture drift after a refactor (1), cancel-path side effect (1), restart resilience (1), concept leak past a guard (1), #53 computed-not-consumed (1), lifecycle silent no-op (1).
