# PLANNING — Enable Custom Preset Ranges (D9 / `guest_mode_actuation`, HVAC arc step 5)

**Status:** PLAN **REV 3.3** (2026-10-03 — post W1-C P1 re-check; see "REV 3.3 ERRATA" below, authoritative over everything after it, and "Plan re-check (post W1-C P1)" at the end). Previously REV 3.2 (2026-09-29). Not built. Batch C parent card `HVAC-CUSTOM-PRESET-RANGES-1` (children `HVAC-S10-DPM-VS-S1-1`, `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`, `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`). Build zone_3 first. **Do NOT deploy after building until the operator says so** (operator 2026-09-27 Q5). REV 3.1 addressed plan-review findings F1-F8; REV 3.2 addresses re-check R1-R5 (`docs/reviews/code-review/plan_review_hvac_cpr_rev3.md` §"REV 3.1 re-check"). No further plan review needed.

**Operator ruling (2026-09-27):** "yes", the operator wants the feature. URA wins over app edits. Carrier originals are restored when the feature is turned off. The heat-bug fallback is handled separately (shipped v5.103.22).

**Arc position:** `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` §11 row 5.

**Cards resolved on ship:** `HVAC-S10-DPM-VS-S1-1`, `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` (both folded into D3 by construction, not by a separate deliverable). Disposition of `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` in §9; rebased in REV 3.1 F5 on the by-construction proof (only reader `hvac.py:4108` + only writer `:4153`, both deleted by D3), plus REV 3.2 R1 (D3c also retires the S11 producer + throttle flag).

**Version:** next free `5.103.x` PATCH after Batch B/D land on `develop`.

---

## REV 5 FIX-PLAN (2026-10-05) — authoritative over REV 4 and REV 3.3 wherever they disagree

**Scope:** closes plan-review findings F1–F9 against REV 4. No build; no commit. Where a REV 4 or REV 3.3 bullet contradicts a REV 5 point below, REV 5 wins. Where REV 5 is silent, REV 4 / 3.3 stand. Base: `develop` HEAD on `feature/census-inputs-first`; W1-C P2 (`PLANNING_hvac_w1c_p2_ecobee.md` REV 3) is the authority on the ecobee half of `set_preset_range` (§4.2 :270-278, §4.2a :315-345, §4.9 :491-521).

### F1 (HIGH) — S10 call shape, result handling, Generic verb, and ownership of the ecobee half

**Supersedes:** REV 4 V1 bullets 4 (the `feature_available` discussion and the `no_device_presets` verb); REV 4's "D3 adds" acceptance line for `no_device_presets`; REV 4's "Live" bullet wording that keyed on `no_device_presets`; REV 3.3 §5 D3 test name `test_generic_set_preset_range_zero_calls_feature_unavailable`; the Generic SKIPPED/DEFERRED enumeration in REV 4 V1.

- **S10 calls** `_w1c_strategy(self.hass, zone.climate_entity).set_preset_range(self.hass, zone.climate_entity, P, low, high, gate=_s10_gate, zone_id=zone_id, site=..., reason=..., emit=emit_set_activity_setpoint)` and **branches only on `result.status`**. `_w1c_applied` is forbidden (REV 3.3 U1 :24 already bans it). Truthiness raises.
- **Status table (binding):**
  - `APPLIED` → **success**. Record one throttle entry for `(zone, P, mode)`; no retry; no latch.
  - `SKIPPED_ALREADY_CORRECT` with ANY reason (incl. P2's `stored_for_next_hold`, `range_already_live`, or Carrier's `ha_view_matches`, or any other brand-specific reason) → **success**. Record the throttle entry; no retry; no latch; no NM.
  - `DEFERRED` with ANY reason → **consumes the §6.2 rate clock**, exactly as REV 3.3 §6.2 specifies for Carrier `gate_deferred`. No failure count. No latch. The caller-side ledger (`_log_deferred_write`) is the record.
  - `FAILED` → **counts a failure (§6.2 `call_failed`) only when `reason == "emit_raised"`.** All other FAILED reasons (including `preset_range_unsupported`) are a **quiet skip**: no latch, no failure count, no NM, one INFO log once per entity per process lifetime.
- **Generic has ONE result and ZERO wire calls.** `GenericStrategy.set_preset_range` returns `WriteResult(WriteStatus.FAILED, "preset_range_unsupported")` with zero `climate.*` service calls (per CPR §3.3 :732, §14 :1236 and P2 §4.9 :498). Under the FAILED rule above, `preset_range_unsupported` is a quiet skip.
- **Delete every occurrence of `no_device_presets`** in this plan (REV 4 V1 bullets 2 and 4, REV 4 V1 "writing nothing to `last_sent`" footnote, REV 4 "D3 adds" and REV 4 "Live" bullet). There is no `no_device_presets` verb, no `profile_has_no_activity_setpoint` verb, no SKIPPED/DEFERRED Generic result, and no second Generic result shape anywhere in CPR.
- **Ecobee behaviour is owned by W1-C P2, not CPR.** CPR does NOT define `EcobeeHomeKitStrategy.set_preset_range`, does NOT enumerate its SKIPPED reasons, and does NOT change its DEFERRED semantics. P2 §4.2 / §4.2a / §4.9 is authoritative (store-first APPLIED, two SKIPPED reasons, DEFERRED on mode precondition or caller gate, CPR-OFF Seasonal Baseline restore). CPR consumes it unchanged via the ANY-reason rule above.
- **Pointer required by P2 §4.9 :521.** Add a one-line pointer in §3.3 of this plan (Carrier rules section) reading: *"Ecobee's `set_preset_range` shape, store-first semantics and CPR-OFF restore are specified in `PLANNING_hvac_w1c_p2_ecobee.md` §4.9; CPR consumes it via the ANY-reason APPLIED/SKIPPED/DEFERRED/FAILED rule in REV 5 F1."*
- **Test rename (replaces REV 4 F1 rename and REV 3.3 U1 contract-test name).** The former `test_generic_set_preset_range_zero_calls_feature_unavailable` is renamed **`test_generic_set_preset_range_zero_calls_unsupported`** and asserts: (a) `WriteStatus.FAILED` with `reason == "preset_range_unsupported"`; (b) zero `climate.*` service calls; (c) no `call_failed` latch increment and no `s10_preset_range_call_failed` NM.
- **Live (zone-3-first) wording update:** the "ecobee rooms produce zero S10 rows regardless of switch state" criterion now reads *"any strategy returning `FAILED("preset_range_unsupported")` (Generic today; ecobee pre-P2) produces zero `climate_write` rows and zero latch increments"*. P2's ecobee once shipped will produce zero wire calls under the SKIPPED/DEFERRED paths; both land as quiet skips under F1.

### F2 (HIGH) — New adapter verb `preset_range_original`; §3.4 Step 9 snapshot gated on it

**Supersedes:** REV 3.3 §3.4 and §6.3 wherever they say the snapshot captures "the live HA view" as the universal device original.

- Add one adapter verb on the strategy registry: `preset_range_original(hass, entity, P) -> tuple[int, int] | None`.
  - **CarrierStrategy:** returns `(low, high)` for preset `P` from the device's P1/P2 comfort profile under the HA-view rounding rule (same whole-°F rounding the Carrier write applies). Never raises; unreadable entity → `None`.
  - **EcobeeHomeKitStrategy** (defined in P2, consumed here, no CPR edit to P2): returns the P2 Seasonal Baseline pair for `P`.
  - **GenericStrategy:** returns `None`. There is no device-side preset profile.
- **§3.4 Step 9 snapshot** runs **only when `preset_range_original(hass, zone.climate_entity, P)` is non-`None` AND differs from the composed `desired` range**. If it is `None`, no snapshot is captured and no `S10_preset_range_restore` row is ever produced for that `(zone, P)`. The P1/P4 guard-masked-match caveat (REV 3.1 F7) is unchanged for Carrier (match → no snapshot, harmless).
- **Snapshot shape** stays `(low, high)` + `captured_iso`; the only change is the SOURCE used to seed it (the verb, not the live `obs`).
- **Test (new, replaces the ad-hoc Generic-snapshot assertion in REV 3.3 §3.4):** `test_s10_generic_zone_never_snapshots` — a Generic-resolving zone that enters CPR's apply pass produces zero snapshot entries in `__s10_preset_ranges.snapshots` and zero `S10_preset_range_restore` rows across the apply-then-OFF transition.
- **No behaviour change for Carrier** on the all-Carrier install (byte-identical snapshots for House 1).

### F3 (HIGH) — switch.py restore semantics (anchors re-verified against develop)

**Supersedes:** REV 3.3 R4 switch-reader audit anchors for the map-clear and no-prior-state lines; REV 4 V3's switch-side anchor cells; REV 3.3 §3.5 wording for the `no_last_state_default` resolution path.

- **Verified anchors on current `develop`:**
  - `switch.py:2070` `return True  # default ON` (hvac-is-None branch of `is_on`).
  - `switch.py:2071` `return getattr(hvac, "_guest_mode_actuation_enabled", True)`.
  - `switch.py:2087-2088` `_last_emitted_range.clear()` (OFF path).
  - `switch.py:2111-2113` early return on `last_state is None or last_state.state not in ("on", "off")` ("No prior state — default ON is truth").
  - `switch.py:2131-2152` `_handle_hvac_ready` deferred-restore landing.
- **Patch rules (both must land in D8; neither substitutes for the other):**
  - **:2070** — change `return True  # default ON` to `return None` so an unavailable HVAC coord reports `None` (unknown/pending), not True. REV 3.3 R4 named only :2021-area getattr; it missed this hvac-is-None branch.
  - **:2071** — change `getattr(..., True)` default to `None`. Together with the F1 tri-state readers already specified in REV 3.3 R4 for `hvac.py:3923`, `hvac.py:3940`, `sensor.py:10199/10231`, this makes `None` the only unresolved value anywhere on the read path.
- **Unavailable/unknown saved last_state resolution (new, binding).** When `async_get_last_state()` returns a `State` whose `.state` is `"unavailable"` or `"unknown"` (not only when it is `None`), the resolution is **False** with `source="no_last_state_default"`. The :2111-2113 early-return branch is amended to call `set_custom_ranges_enabled(False, source="no_last_state_default")` instead of silently returning. REV 3.3 R4's "no-last-state → False" ruling now covers all three shapes (`last_state is None`, `last_state.state == "unavailable"`, `last_state.state == "unknown"`). This closes Bug Class #52 for the CPR switch specifically.
- **Deferred-landing emits NM/ledger when it lands, not when the switch loaded (new, binding).** If the resolution would occur while `hvac is None` at `async_added_to_hass` time, it MUST be deferred with `source="deferred_landing_<original_source>"` where `<original_source>` ∈ {`restore_entity`, `no_last_state_default`} is captured at `async_added_to_hass`. `_handle_hvac_ready` (`switch.py:2131-2152`) completes the deferral by calling `set_custom_ranges_enabled(target_bool, source="deferred_landing_<original_source>")`. The NM + §4.3 ledger row (REV 3.1 F1's `s10_restart_default_off_restore_pending` + `s10_default_off_after_restart`, if applicable) emit at the LANDING instant on the HVAC coord, not when the switch entity loaded. If HVAC is still `None` when the ready signal fires, the existing warning at `:2141-2144` stands and the R2 backstop (F8) is the only remaining resolver.
- **Anchor errata to fix in-place in REV 3.3 R4 and the REV 3.3 Anchor table (`:233`):**
  - map clear: was `:2046-2047`, is **`:2087-2088`**.
  - no-prior-state default: was unset in R4 ("None — default ON" prose), is **`:2111-2113`** (early return) + the new resolution call this F3 adds.
- **Tests (both required; both must FAIL on pre-CPR source and PASS post-fix):**
  - `test_switch_restore_unavailable_last_state_resolves_false` — RestoreEntity hands back a `State(..., state="unavailable")`; after `async_added_to_hass`, flag resolves to False with source `no_last_state_default`; S1 reads False on the next tick.
  - `test_switch_no_last_state_deferred_lands_false_via_ready_signal` — RestoreEntity returns `None` while HVAC coord is not yet in `hass.data`; the switch takes the deferred path; dispatching `SIGNAL_HVAC_COORDINATOR_READY` lands the resolution as False with source `deferred_landing_no_last_state_default` and emits the NM + ledger row at the landing instant.

### F4 (MED) — "Blocker 4" is withdrawn; sequencing is additive

**Supersedes:** REV 4 "Known blockers" row 4 ("NEW dependency: W1-C P2 (ecobee adapter) OR a thin-adapter `set_preset_range` shim on the CPR branch"); REV 4 V1 sequencing bullet (a)/(b) that required CPR to merge after P2 or shim the thin-adapter verb on-branch.

- **CPR builds the Carrier AND Generic halves now.** F1 above specifies both; CPR's diff contains ZERO references to `feature_available` / `feature_unavailable_reason`. Reviewer D's lint on CPR's diff (REV 4 Non-goals) is binding; CPR does not depend on P2's deletion of those symbols.
- **W1-C P2 adds the ecobee half** (`EcobeeHomeKitStrategy.set_preset_range`, P2 §4.9) on its branch, independently.
- **Rebase rule.** Whichever of CPR and P2 merges second rebases `hvac_strategy.py` as a mechanical union — Carrier override + Generic base from CPR, ecobee override from P2. No logic conflict is possible because the two overrides land on disjoint subclasses.
- **Interim behaviour.** Until P2 ships, House 2's ecobee zones resolve `GenericStrategy` and therefore return `FAILED("preset_range_unsupported")` → F1 quiet-skip. This is the accepted interim — identical to a zone with no CPR support at all, zero wire calls, no NMs.
- **Row 4 in "Known blockers" is deleted;** the three HVAC-* cards remain the complete blocker set.

### F5 (HIGH) — INV rewrite; drop the composite "≤7 calls / 60 min" bullet; two separate falsifiers

**Supersedes:** REV 4 "Falsifiable invariant (consolidated, REV 4)" bullets 1, 2 and 4 and the combined falsified-by clause.

- **INV-CPR-REV5.** With switch 01 resolved **True** (not None, not False) and the Carrier adapter present:
  - **At most ONE wire call per tick** for any given `(zone, P)` via `set_preset_range`.
  - **Zero wire calls on any tick where the device's HA-view range already equals the composed `desired` range** (SKIPPED_ALREADY_CORRECT and DEFERRED paths produce zero wire calls by construction).
  - **For any strategy whose `set_preset_range` returns FAILED with any reason other than `emit_raised`** (including Generic `preset_range_unsupported`, and any future brand that returns FAILED unsupported), zero wire calls, zero latch increments, zero `s10_preset_range_call_failed` NMs.
  - **Snapshot/restore invariant.** For every `(zone, P)` ever written by APPLIED, an F2-sourced snapshot exists from before the first APPLIED until a confirmed restore; a restore write occurs ONLY while the flag has resolved to False. Zones whose `preset_range_original` is `None` never snapshot and never restore.
- **Two separate falsifiers (replace the single combined falsifier of REV 4):**
  - **F-APPLY.** Any `climate_write` row with `site LIKE 'S10_preset_range%'` AND `site NOT LIKE 'S10_preset_range_restore%'` while the resolved flag is anything other than **True** falsifies INV-CPR-REV5. (Covers both `None` and False.)
  - **F-RESTORE.** Any `climate_write` row with `site LIKE 'S10_preset_range_restore%'` while the resolved flag is anything other than **False** falsifies INV-CPR-REV5. (Covers both `None` and True.)
- **The REV 4 "≤7 wire calls per 60 min / (zone, preset, mode)" bullet is deleted.** It was a rate artifact of the retired compose-away storm regime, not a CPR correctness invariant. **INV-NO-STORM (REV 3.3 U6) is unchanged** — it continues to carry the 7-call/h rate bound on its own axis.

### F6 (MED) — `S10_ROLLOUT_ZONE_IDS` moves to rung 2 (options-flow field, default empty)

**Supersedes:** REV 3.3 U5 placement of `S10_ROLLOUT_ZONE_IDS` as a rung-1 module constant with default `frozenset({"zone_3"})`.

- Per the "Numbers Get Knobs" ladder and the operator's multi-home revision of `project_single_user_no_backcompat` (2nd install going live weekend 2026-10-03/04), **`S10_ROLLOUT_ZONE_IDS` is rung 2 — an options-flow field on the HVAC coordinator entry.**
  - Field key: `hvac_s10_rollout_zone_ids` (frozenset of zone slugs; serialised as a sorted list).
  - **Default: empty set** — no zones. CPR's apply pass is a no-op on every zone of a fresh install until the operator explicitly opts a zone in. The restore pass is NOT gated by this field (REV 3.3 U5 restore-ungated rule unchanged).
  - To widen to every zone, the operator adds each zone slug by name; there is no "all" sentinel. This is deliberate — a second install (ecobee-only) cannot inadvertently enable CPR by inheriting a House-1 default.
- **Pre-second-install contract (binding).** CPR must not ship with any non-empty default anywhere. The House 1 operator opts zone_3 in via the options flow at deploy time, replacing REV 3.3 U5's "widening patch" step. House 2's ecobee zones produce zero S10 rows by configuration AND by the F1 FAILED quiet-skip (double no-op; both intentional).
- **Test additions:**
  - `test_s10_rollout_default_empty_set_no_apply_rows_on_fresh_install`.
  - `test_s10_rollout_scope_apply_zone_3_only_restore_all` is kept but seeds the field via the options flow, not via a module constant.

### F7 (MED) — Mutation drill ownership moves to Reviewer C

**Supersedes:** REV 4 Tier paragraph wherever it assigns the "force CarrierStrategy.set_preset_range to return DEFERRED('no_device_presets')" drill to Reviewer D.

- **Reviewer C** (test-authority / per-site mutation) owns the following drill, run under the pyc-staleness protocol (`PYTHONDONTWRITEBYTECODE=1` + clear `__pycache__`):
  - **Mutation.** In the F1 result-handling block, neuter the quiet-skip branch for `FAILED` with `reason != "emit_raised"` so it falls through into the `call_failed` latch path.
  - **Expected failure.** `test_s10_registry_miss_generic_skips_quietly` fails with a latch-increment assertion at exactly one site; no other test fails.
  - **Restore.** The mutation is reverted and the suite returns to green.
- **Reviewer D** retains the INV-CPR-REV5 enumeration (F-APPLY / F-RESTORE), the compose-away reachable configs (REV 3.3 U6), and the F3 restore corners. D does NOT run the F7 mutation.
- REV 4's "force `CarrierStrategy.set_preset_range` to return `DEFERRED('no_device_presets')`" drill is DELETED (no_device_presets does not exist per F1).

### F8 (MED) — R2 backstop handle lifecycle

**Supersedes:** REV 3.2 R2 wherever it leaves the `async_call_later` handle unmanaged across a reload.

- The R2 backstop handle (the `async_call_later(S10_SWITCH_RESOLUTION_TIMEOUT_S, ...)` scheduled at coordinator boot that resolves `None → False`) is stored on the HVAC coordinator as `self._cpr_resolution_backstop_handle: CALLBACK_TYPE | None`.
- **Cancel-before-re-arm.** `manager.py:1231` (the re-call of `async_setup` on reload) MUST cancel the existing handle BEFORE scheduling a new one. The cancel is unconditional on reload entry; the new schedule is only armed if the flag is still `None` at the moment the new `async_setup` runs its boot block.
- **Teardown.** `async_will_remove_from_hass` / coordinator teardown cancels the handle and clears the attribute. A cancel on a `None` attribute is a no-op.
- **Ledger.** When the backstop fires and resolves False, the §4.3 ledger row's `source` field is `unresolved_backstop` (REV 3.2 R2 unchanged). Add `handle_cancelled_by: "reload" | "teardown" | None` to the row for Reviewer D's enumeration.
- **Test (new).** `test_cpr_r2_backstop_handle_cancelled_on_reload_and_teardown` — arm the backstop; trigger a reload at `manager.py:1231`; assert the first handle's `cancel()` was called before the second was scheduled; trigger teardown; assert the final handle is cancelled and the attribute is `None`.

### F9 (LOW) — V2 app-name templating reads P2's strategy label field

**Supersedes:** REV 4 V2 bullet 3 wherever it says "ecobee's label comes from its strategy, not CPR" without naming the field.

- The U9 "NM strings must be profile-templated" rule reads **`strategy.app_name`** — the P2-defined strategy label field (P2 §4.5 preserves `app_name` in the trimmed `ProfileCapabilities`).
- Any CPR NM string that would read "Bryant app" (REV 3.3 U9: L3, L9 wording) is swapped at build time for `strategy.app_name`. Carrier returns `"Bryant"`; ecobee returns `"ecobee"`; Generic returns `strategy.app_name = None`, in which case the templated phrase falls back to the brand-neutral noun **"the thermostat app"** and the NM runs through unchanged.
- **Test.** `test_s10_nm_templates_use_strategy_app_name` — swap the resolved strategy between Carrier / ecobee / Generic fixtures and assert the three expected renderings; FAIL on any hard-coded "Bryant".
- No change to Carrier NM wording (byte-identical to REV 3.3). Additive templating only.

### REV 5 changelog
- **F1:** single Generic result (`FAILED("preset_range_unsupported")`); S10 branches on `.status`; APPLIED and SKIPPED_ALREADY_CORRECT (any reason) = success; DEFERRED consumes rate clock; FAILED counts only on `emit_raised`; `no_device_presets` deleted everywhere; test renamed to `..._unsupported`; pointer to P2 §4.9 added in §3.3; P2 owns ecobee half.
- **F2:** new `preset_range_original` adapter verb; §3.4 Step 9 snapshot gated on non-None + differs-from-desired; new `test_s10_generic_zone_never_snapshots`.
- **F3:** `switch.py:2070` → `return None`; `:2071` getattr default → `None`; `unavailable`/`unknown` last_state resolves False via `no_last_state_default`; deferred landing emits NM/ledger via `_handle_hvac_ready` at the landing instant; anchors corrected (`:2087-2088`, `:2111-2113`); two new tests.
- **F4:** Blocker 4 withdrawn; CPR builds both halves; rebase rule stated; House 2 ecobee = Generic quiet-skip interim (accepted).
- **F5:** INV rewritten — "≤1 wire call per tick, 0 once HA view matches"; two separate falsifiers (F-APPLY, F-RESTORE); REV 4 bullet 4 and the ≤7/60 min cap deleted.
- **F6:** `S10_ROLLOUT_ZONE_IDS` → rung-2 options field; default empty set; test added.
- **F7:** FAILED-non-emit_raised mutation drill owned by Reviewer C; D keeps INV enumeration.
- **F8:** R2 backstop handle stored, cancelled before re-arm on reload (`manager.py:1231`), cancelled in teardown; new test; row `handle_cancelled_by` field added.
- **F9:** V2 app-name templating reads `strategy.app_name` (P2 §4.5 preserved field); Generic falls back to brand-neutral noun; new test.

---


## Builder notes (2026-10-05, branch `feature/hvac-batch-c-cpr-build`) — what the build did where the plan was silent

Read-first attestation: `HVAC_ARCHITECTURE_STATE_OF_PLAY.md` read completely; nothing in its §10 is re-asserted.
Branch note: `feature/hvac-batch-c-cpr` already existed (a stale plan-only branch at `19aaa76d2`, checked out in another
worktree), so the build is on `feature/hvac-batch-c-cpr-build` off develop `0ef1f1675`.

- **B1 (F9 — `app_name`).** P2 §4.5's trimmed `ProfileCapabilities` field list does NOT contain `app_name`, and no
  `app_name` exists in source. Built as a plain strategy CLASS attribute (`GenericStrategy.app_name = None`,
  `CarrierStrategy.app_name = "Bryant"`), not a capabilities field, so the frozen field-set test is untouched and P2 adds
  `"ecobee"` on its subclass. **Question for the operator/P2:** confirm the attribute (not a capabilities field) is the
  intended home.
- **B2 (await gap, INV-CPR-REV5 snapshot clause).** The write-ahead save is an `await` between step 9 (snapshot check)
  and the adapter call, so the view can change in between. S10 re-checks `preset_range_original` synchronously right
  before the call and stands down if an un-captured differing original now exists. `CarrierStrategy.set_preset_range`
  also DEFERs (`range_unreadable`) when the view has no low/high, so the adapter never edits a profile whose original
  cannot be captured. Test `test_s10_snapshot_await_gap_never_edits_without_original`.
- **B3 (rate-clock semantics for no-wire outcomes).** REV 5 F1 says DEFERRED "consumes the rate clock" while §6.2 said
  roll it back; built: every attempt stamps `last_attempt_iso` (kept on DEFERRED / SKIPPED); a same-value re-attempt
  waits `S10_PRESET_RANGE_MIN_INTERVAL_S` only after a WIRE attempt (writes or failures > 0), otherwise the 600 s
  spacing. A Generic `preset_range_unsupported` quiet skip rolls the stamp back (no record left).
- **B4 (latch read).** "Due retry at the limit and the HA view still differs" reads the view through the adapter's
  `preset_range_original` (Carrier = HA view of P while confirmed on P); `None` = cannot tell = no call, no latch.
- **B5 (restore confirm).** The separate "≥ MIN_INTERVAL since the last restore write" check is enforced by the rate
  gate itself (an equivalent mutant as a second check, removed).
- **B6 (rollout field home).** Rung-2 field `hvac_s10_rollout_zone_ids` lives on the Baseline Presets options step
  (multi-select of discovered HVAC zones, free text allowed, saved as a sorted list; default empty). Read live each
  tick from the coordinator-manager entry.
- **B7 (user OFF NM).** The "Putting original ranges back" NM is sent only when at least one original is pending.
- **B8 (F8 anchor).** `manager.py` is unchanged: the cancel-before-re-arm runs at the top of
  `_arm_cpr_resolution_backstop`, which `async_setup` calls on every (re)setup — the manager's re-enable path re-runs
  `async_setup`. The boot-settle condition of R2 is not separately checked (the backstop only resolves an unresolved
  flag to OFF; the restore pass itself runs on full cycles, which wait for boot-settle anyway).
- **Not done here:** D0 items 1–3 (probe `scripts/probes/hvac_preset_profile_probe.py`) — a dispatch precondition, not
  a build deliverable; README `README_v5.103.x.md` (version not yet assigned; deploy HELD).

## REV 4 re-check (2026-10-05) — authoritative over REV 3.3 wherever they disagree

**Reviewer:** ura-planner, operator-requested re-check in parallel with ecobee W1-C P2 work. **No build yet; no commit.** Base of this re-check: `develop` HEAD on `feature/census-inputs-first` (not a CPR branch; ecobee probe in flight). The REV 3.3 anchor base was `8a4619b32` (post v5.103.36). Deltas since: v5.103.37 (CM outage incident surfaced on 10-03) and v5.103.38 (README records the live CPR-switch re-enable bug and names it as "fix tracked in Batch C"). W1-C P2 (ecobee) is in flight on a separate branch; CPR must slot after or alongside it without creating ordering surprises.

### What is still right

- **The three blockers are still the correct set and still fold cleanly:**
  - `HVAC-S10-DPM-VS-S1-1` → closed by §3.1 named-profile write (D3).
  - `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` → closed by D3 deletion of F2 + the compose-away block.
  - `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` → `measured_2026_10_03_overnight` REFUTED it as a live defect (0 strands / 6.4 days); the by-construction closure via D3c (R1 retires `_last_emitted_range` end-to-end) still holds, and the card's own `revisit_if` is covered by the throttle-removal path CPR takes.
- **The known live bug `switch.ura_hvac_coordinator_guest_mode_actuation` re-enabling on reload/restart is addressed by the plan as written**, in two layers:
  - F1 tri-state (`None` init at `hvac.py:684` — verified still `bool = True` on current develop, line unchanged from REV 3.3) + D8 explicit `None → False` resolution on the no-last-state path.
  - U4 pre-deploy mandatory switch-OFF step on the OLD code before the deploy restart (because today's code default is True and a 10-02 entity re-create / a 10-03 unavailable-restore flip both proved the operator-gate can be bypassed at the switch layer).
  - The 10-04 groom on `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` records the SAME two mechanisms (entity re-create showing code default True; guarded restore of saved-state `unavailable` falling back to default True) and confirms README_v5.103.38 captures it as "fix tracked in Batch C". The companion general card `RESTORE-UNAVAILABLE-OFF-SWEEP-1` (Bug Class #52) stays separate; CPR fixes only its own switch.
- **Falsifiable invariants** (INV-S10 / INV-RATE / INV-RESTORE / INV-NO-STORM) stated in §7.1 and §4 of the compose-away fold still hold; each has a discriminating test and a reviewer-D break repro.
- **Brand-neutral above the strategy line:** §14 and the W1-C hand-off checklist are brand-agnostic; `__s10_preset_ranges`, the skip matrix, the snapshot/restore state machine, the latch/rate model and the tri-state resolution read no Carrier state.

### What has changed since REV 3.3 — must be folded before plan review

**V1 (HIGH) — Thin-adapter ruling supersedes U1's `feature_available("cpr")` skip (operator 2026-10-03, already recorded at the bottom of this plan, lines 1215–1216).** REV 3.3 U1 still describes a `strategy.feature_available("cpr") == False → skip` step 0.3 and a `GenericStrategy.set_preset_range` body that reads `feature_available` / `feature_unavailable_reason`. The operator ruling retires that pattern for the HVAC side: "The thermostat brand layer is a thin command adapter; HVAC features are never gated by brand." For CPR this means:

- S10 does NOT call `feature_available("cpr")` and never branches on brand. Delete U1 step 0.3 and the `feature_available` test cases from U1's contract-test additions.
- `GenericStrategy.set_preset_range` returns `WriteResult(WriteStatus.SKIPPED_ALREADY_CORRECT, "no_device_presets")` (preferred verb) OR `DEFERRED("no_device_presets")` — picked by the adapter author, not CPR — making ZERO calls, writing nothing to `last_sent`. S10 treats this as a quiet skip (same bookkeeping as unreadable: no latch, no failure count, no NM, one INFO log once per entity).
- `CarrierStrategy.set_preset_range` keeps P1–P6 as REV 3.3 wrote them.
- Sequencing: either (a) CPR merges AFTER W1-C P2 REV 2 removes `feature_available` / `feature_unavailable_reason` from `hvac_strategy.py` (ecobee P2 is in flight), OR (b) CPR implements the verb shape directly on its branch without referencing `feature_available` at all. Builder's choice; the operator's constraint is the thin-adapter invariant.
- U1's `test_generic_set_preset_range_zero_calls_feature_unavailable` is renamed `test_generic_set_preset_range_zero_calls_no_device_presets` and asserts the SKIPPED/DEFERRED verb + reason without reading `feature_available`.

**V2 (MED) — Ecobee P2 brand-neutral slotting.** The three ecobee thermostats discovered on 10-04 (plan commit `dd18c1849`) will land as a second brand under the strategy registry. CPR must not assume Carrier is the only strategy with a non-FAILED `set_preset_range`:
- The U5 rollout gate (`S10_ROLLOUT_ZONE_IDS = {"zone_3"}`) is already brand-agnostic; it stays as the single staged-rollout mechanism and only widens by operator go.
- The U6 "INV-NO-STORM" test is parameterised by strategy, not Carrier-only; add a Generic/ecobee case that asserts zero wire calls on a profile-less brand regardless of switch state.
- The U9 "NM strings must be profile-templated" rule tightens: any string that today reads "Bryant app" (L3, L9 wording) is swapped at build time for the strategy's `app_name` label; ecobee's label comes from its strategy, not CPR.

**V3 (MED) — Anchor re-verification against develop HEAD, not `8a4619b32`.** REV 3.3's anchor table was captured against v5.103.36. v5.103.37/.38 shipped since. Re-greped on current develop:
- `hvac.py:684` `_guest_mode_actuation_enabled: bool = True` — **unchanged** (good; U4 pre-deploy step still correct).
- `hvac.py:3928` `_async_apply_preset_overrides` method entry; `:3945` `if not self._guest_mode_actuation_enabled:` gate; `:3962` `master_enabled = …` — **match REV 3.3's U1 anchor cells** (`:3945` / `:3962`). No drift from v5.103.36 → .37 → .38.
- `switch.py:2067` `is_on` reads `getattr(hvac, "_guest_mode_actuation_enabled", True)` and `:2076` / `:2084` turn_on/turn_off — same shape REV 3.3 R4 patches.
- Builder MUST re-grep the full anchor table at build dispatch regardless; this re-check does not relieve that duty.

**V4 (LOW) — Live switch state at write time.** On 10-04 02:40Z the operator turned the switch OFF (per the groom log on `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1`). The §3.3 LIVE-STATE NOTE in the state-of-play (dated 10-03) is thus stale; the switch is OFF now. U4 remains correct wording ("turn it OFF on the OLD code before deploy restart") but the pre-deploy checklist should verify the current state at deploy time rather than assume ON.

### Known blockers — unchanged in count, one dependency added

| # | Blocker | Status in REV 4 |
|---|---|---|
| 1 | `HVAC-S10-DPM-VS-S1-1` | Still a Batch C child; closed by D3. |
| 2 | `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` | Still a Batch C child; closed by D3 deletion. |
| 3 | `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` | Still a Batch C child; closed by construction via D3c (R1 full-map retirement). |
| 4 | **NEW dependency: W1-C P2 (ecobee adapter) OR a thin-adapter `set_preset_range` shim on the CPR branch** | V1 above. Operator's thin-adapter invariant requires one of the two before CPR builder dispatch. |

### Tier (unchanged)

**Tier 2-DB + mandatory Reviewer D** (four framing-disjoint reviews + live validation + README write-back), per REV 3.1 §11 and REV 3.3 U9. V1 widens Reviewer D's enumeration surface: a brand that implements `set_preset_range` as a quiet SKIPPED/DEFERRED (ecobee today, Generic always) must not latch, not count a failure, not emit an NM, and not consume rate-clock. Mutation drill: force `CarrierStrategy.set_preset_range` to return `DEFERRED("no_device_presets")` on one call → S10 writes no `climate_write` row and no latch/NM; restore the method.

### Falsifiable invariant (consolidated, REV 4)

> **INV-CPR-REV4.** With switch 01 resolved ON, DPM overrides active, and the Carrier adapter present:
> - On the FIRST tick a named zone (home / sleep / away / vacation in heat_cool) has a differing cell, S10 issues exactly ONE `set_activity_setpoint` wire call for that (zone, preset); on every subsequent tick while the pair matches HA view, S10 issues zero wire calls.
> - Across any 60 min, wire calls for one (zone, preset, mode) ≤ ⌈3600 / `S10_PRESET_RANGE_MIN_SPACING_S`⌉ + 1 = **7**, independent of DPM flap, S1 reclaim, borrow return, restart, or brand mix.
> - For every (zone, preset) edited, a persisted snapshot exists from before the first edit to a confirmed restore; a restore write occurs ONLY while the flag has resolved to False.
> - For any strategy whose `set_preset_range` is not implemented, S10 writes zero `climate_write` rows for that zone and increments no latch counter — a brand without the capability costs nothing.
>
> Falsified by: ≥ 2 S10 wire calls per 10 min on one (zone, preset, mode); any `climate_write site LIKE 'S10%'` row while the flag reads `None` or `True` is False; any `S10_preset_range_restore` row for a zone with no snapshot; any NM `s10_preset_range_call_failed` from a brand that returned SKIPPED/DEFERRED with reason `no_device_presets`.

### Acceptance criteria delta (adds to REV 3.3 §5 D3 / D3b / D4)

- **D3 adds:** `test_s10_generic_strategy_quiet_skip_zero_rows_zero_latch` — Generic (or ecobee) strategy's `set_preset_range` returns SKIPPED/DEFERRED `no_device_presets`; S10 writes zero `climate_write` rows AND zero latch/failure counter increments across 12 ticks.
- **D3 renames:** `test_generic_set_preset_range_zero_calls_feature_unavailable` → `test_generic_set_preset_range_zero_calls_no_device_presets` (asserts verb + reason, not `feature_available`).
- **Live (zone-3-first):** add a verifier that `climate_write` rows filtered by `site LIKE 'S10%'` carry only Carrier zone entity_ids while rollout = `{"zone_3"}`; ecobee rooms (once their config lands) produce zero S10 rows regardless of switch state.
- **Deploy gate (unchanged):** operator explicit go, zone 3 first, U4 OFF pre-step verified live at deploy time.

### Non-goals (REV 4 additions)

- No change to ecobee W1-C P2 scope. CPR consumes P2's output; it does not drive it.
- No build-time dependency on `feature_available` / `feature_unavailable_reason` anywhere in CPR files. Reviewer D fails the build if a `feature_available` reference appears in CPR's diff.

## REV 3.3 ERRATA (2026-10-03, post W1-C P1 v5.103.36) — authoritative over REV 3.2 / 3.1 / 3 wherever they disagree

Re-check against `develop` @`8a4619b32`. W1-C P1 shipped in v5.103.36 (`df03c904f`): every thermostat write goes through `hvac_strategy.py`, and the byte-identity goldens (`quality/tests/golden/w1c_p1_goldens.json`, 168 records) pin S10 and `_last_emitted_range`. The compose-away blocker plan (`PLANNING_hvac_compose_away_throttle.md` REV 1) is folded here. Behaviour of the plan is unchanged except U5 (rollout scope). Every anchor below was re-grepped on this commit.

### U1 (HIGH) — S10 writes go through the strategy layer, P1 conventions

**Supersedes:** §3.2 step 11, §3.3 "Generic" paragraph, D1 lint text, D2.

- **Call shape.** S10 calls `_w1c_strategy(self.hass, zone.climate_entity).set_preset_range(self.hass, zone.climate_entity, P, target_temp_low=lo, target_temp_high=hi, freeze_active=self._freeze_active, gate=_s10_gate, site=..., zone_id=zone_id, reason=..., emit=emit_set_activity_setpoint)`. `_w1c_strategy` is `hvac.py:117-119`. Pass the funnel as `emit=`, the P1 convention (`hvac_strategy.py:48-51`): `hvac.py` resolves the module-level funnel name at call time, so test seams that patch it keep intercepting.
- **Result handling.** `set_preset_range` returns a `WriteResult`. S10 branches on `result.status == WriteStatus.<X>`; truthiness raises (`hvac_strategy.py:228-232`). Do **NOT** use `_w1c_applied` (`hvac.py:123-126`). It folds SKIPPED_ALREADY_CORRECT and FAILED into False, and §6.2 treats those two very differently from DEFERRED.
- **Where the method lives.** The base method goes on `GenericStrategy`: `if not self.feature_available("cpr"): return WriteResult(WriteStatus.FAILED, self.feature_unavailable_reason("cpr"))`. That makes zero calls, and the reason is `profile_has_no_activity_setpoint` (REUSE: `hvac_strategy.py:340-352`, `supports_activity_setpoint` on `CARRIER_CAPABILITIES` :165 / `GENERIC_CAPABILITIES` :196). This replaces REV 3's new `"preset_range_unsupported"` string. `CarrierStrategy` overrides it with P1–P6.
- **Not a pure delegate.** The method observes and decides. It writes **nothing** to `last_sent`, so it never calls `_record_sent` / `_clear_sent`. Reason: `_record_sent` wipes every verb's record (:304-307), which would change S1's D2.5 `hold_preset` no-op.
- **Wire exception.** Carrier catches it and returns `FAILED("emit_raised", <exc type>)`, the same shape as `hold_preset` (:484-486). The funnel still writes its one `climate_write` row on the raise path (D1).
- **Service literal: REUSE.** Use `CARRIER_PLATFORM` (`hvac_strategy.py:71`). `"set_activity_setpoint"` is the only new literal, and it lives in `hvac_strategy.py`. Leave `hvac_const.py:1473` `CARRIER_INTEGRATION_DOMAIN` alone. F3's lint forbids the literal only inside `hvac_setpoint.py` and inside `async_call("ha_carrier", …)` outside `hvac_strategy.py`; both rules are compatible with :1473.
- **A profile without the feature skips quietly (W1-C §3c, `PLANNING_hvac_w1c_thermostat_profiles.md:213`).** S10 checks `strategy.feature_available("cpr")` as a new skip **step 0.3**, before snapshot, record and rate.
  - When it is false, S10 writes no record, counts no failure, sets no latch and sends no NM. It logs once per entity.
  - Why this matters: a TRANSIENT registry miss on a real Carrier entity resolves Generic and must not count toward the §6.2 `call_failed` latch.
  - §6.2 "FAILED → failures += 1" now applies only to `FAILED` with reason `emit_raised`.
- **Contract tests (extend `test_hvac_w1c_p1_profile_contract.py`):**
  - `test_generic_set_preset_range_zero_calls_feature_unavailable`
  - `test_carrier_set_preset_range_records_nothing_in_last_sent`
  - `test_set_preset_range_wire_raise_maps_failed_emit_raised`
- **Kwargs completeness.** Add `emit_set_activity_setpoint` to the funnel set in `test_hvac_climate_write_funnel_completeness.py` `test_every_production_funnel_call_supplies_required_kwargs` (~:324).
  - **Pre-existing blind spot since P1:** a funnel passed as `emit=` and called inside the strategy is not a direct Call of the funnel name, so this AST check does not see it.
  - CPR therefore adds the behavioural `test_s10_strategy_call_supplies_site_zone_reason`. It drives the real S10 and asserts the funnel received `site` / `zone_id` / `reason`. Required kw-only arguments make an omission a TypeError.

### U2 (HIGH) — The W1-C P1 goldens change by intent; exact procedure

**Supersedes:** compose-away plan §7 D1 "W1-C P1 interaction" bullet (made concrete here).

- **Blast radius is all 168 cases, not just S10.** `_observe` reads `ctx.coord._last_emitted_range` for every case (`test_hvac_w1c_p1_byte_identity.py:361-364`). Once D3c deletes the attribute, every case raises AttributeError. Scenario seeds write the map at :467 (`sc_S10`), :740 (`_bank`), :765 (`sc_S12`) and :795 (`_preheat_tok`).
- **Commit G1 (test-only, on the CPR branch, BEFORE any production edit):**
  - Drop the `last_emitted_range` key from `_observe`.
  - Remove the key from all 168 JSON records with a scripted key-drop. This is NOT a re-record.
  - The seeds stay in G1, because the attribute still exists.
  - All 168 Carrier cases and the registry-miss cases must stay green on pre-CPR production source. That proves the key drop alone changed nothing.
- **Production CPR commit(s):** remove the four seeds.
- **Commit G2 (re-record):** run `URA_W1C_RECORD_GOLDENS=1` for ONLY the keys whose observation changed: the 6 `A13_S10|*` keys, plus any `A11_S11_*` / `A11_S12|*` / `A11_S13_*` key whose calls or rows moved.
  - The builder lists the exact key set in the build notes.
  - Reviewer C checks that G2's JSON diff touches only that set (key-set diff script) and that each changed record matches the intended behaviour.
  - P1's rule that "regeneration is review-blocking" (:7-12) is satisfied by this named, scoped exception.
- **`failed_raise` gap.** The harness raises only for domain `climate` (:263). Extend it to the CPR service domain, otherwise `A13_S10|failed_raise` silently stops exercising the raise path.
- **Registry-miss suite (:986).** `A13_S10` is now an INTENDED Generic divergence: Generic makes zero calls, Carrier makes an activity-setpoint call. Skip `A13_S10` there with a reason that names CPR + U1. Add `test_s10_registry_miss_generic_skips_quietly`: zero calls, no record, no snapshot, no failure count.
- **Coincidental-equality warning (#63).** The harness fallback baseline may equal the seeded 68/76, so `A11_S11_manual` may NOT change in G2. The authority for the S11 change is R3's discriminating `test_s11_write_reflects_baseline_not_map_pair`, not the golden.
- **Converted tests that drive `A13_S10` via `drive_site` / `site_ctx` must be rewritten:**
  - `test_zzz_hvac_conditioning_demand.py` ~:395
  - `test_v478_egress_window.py` ~:822
- **Test-file counts on develop (re-greped):**
  - `_last_emitted_range` appears in **13** files: the 11 in R1, plus `test_hvac_w1c_p1_byte_identity.py` and `test_v478_egress_window.py`.
  - `_async_apply_preset_overrides` is called from **9** files (not 7): adds `test_hvac_fast_occupancy_response.py` and `test_hvac_w1c_p1_byte_identity.py`.

### U3 (MED) — `_resolve_baseline_range` has FIVE consumers; R1's safety note was S11-only

**Supersedes:** R1 "S11 behaviour change" note (extends it).

After D3c, every caller reads the preset-resolved fallback (`hvac_predict.py:964-985`): the house-state target preset's CONFIGURED (heat, cool). The callers are:

| Caller | Site | Effect after retirement |
|---|---|---|
| First-eval orphan detect | `hvac_predict.py:565` | compares live high to the configured target cool |
| Banking-set discharge | `:674` | same |
| S11 release (HUMAN_MANUAL raw branch) | `:1048` | R1 note (unchanged) |
| **Pre-arrival `from_baseline` pre-cool** | `:1336` | banked_high = configured cool + offset |
| **S12 token snapshot override** | `:1358` | `pre_target_low/high` = configured pair; feeds later S11/S13 HUMAN_MANUAL raw restores |

- **Live relevance.** Switch 01 has been ON since 2026-10-02 21:28Z (state-of-play §3.3 LIVE-STATE NOTE). Since then the map has held S10/D9 `cool − 7` pairs, so today the pre-arrival and S12 paths can read a cool−7 low. Retirement removes that. The change is strictly more correct.
- **New tests:**
  - `test_pre_arrival_precool_from_baseline_uses_preset_fallback`
  - `test_s12_token_snapshot_uses_preset_fallback_not_map`
- **LOW, pre-existing, not in scope:** the fallback keys on the HOUSE target preset, not the zone's current preset.

### U4 (HIGH, deploy-time) — Switch 01 is live ON. Turn it OFF before the CPR restart

- **Today's state.** Code default is True: `hvac.py:684`, the `is_on` fallback at `switch.py:2044-2045`, and the "No prior state — default ON is truth" branch at `switch.py:2085-2087`. The 10-02 entity re-create landed ON. CPR's RestoreEntity would restore `on`, so the first full tick after the deploy restart would run the APPLY pass on every zone, before any operator go and before zone-3-first.
- **Mandatory pre-deploy step (§7.2 step 0, new):**
  - The operator turns `switch.ura_hvac_coordinator_guest_mode_actuation` OFF on the OLD code. The old turn-off only clears the map, which is harmless.
  - Verify `off` in the recorder.
  - Then deploy and restart, and enable per §7.2 only on the operator's go.
  - The deploy checklist and README carry this step.
- **Why the window matters.** Until D8 ships, any entity re-create can flip the switch back ON, so this step is not optional.

### U5 (MED) — Zone-3-first needs a mechanism. There was none

- **The gap.** Switch 01 is house-wide. The per-zone DPM opt-in gates only OVERRIDES, not the static baseline half that S10 now always applies. Config-first: no per-zone knob exists.
- **Add a rung-1 constant** `S10_ROLLOUT_ZONE_IDS: frozenset[str] | None = frozenset({"zone_3"})` in `hvac_const.py`. `None` = all zones.
  - Rung 1 because it is a temporary staged-rollout safety bound, and widening it should be a reviewed one-line patch.
- **Apply pass:** new skip **step 0.2** — a zone not in the set is skipped before snapshot / record / rate.
- **The RESTORE pass is NOT gated**, so INV-RESTORE holds for any zone that has a snapshot.
- **Widening patch** (after L1–L3 + L8 PASS on zone_3) sets it to `None`.
- **Test:** `test_s10_rollout_scope_apply_zone_3_only_restore_all`.
- **Operator to confirm** this mechanism at the build-dispatch go.

### U6 (MED) — Fold of `PLANNING_hvac_compose_away_throttle.md` (card HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1)

Add to §7.1 and D3 verbatim:

- **INV-NO-STORM.** With switch 01 resolved ON and DPM overrides active, in ANY reachable state, an established fused-empty zone on the same named preset gets **zero** S10 wire calls on the second and later ticks once its range matches.
  - Over any 60 min, calls per (zone, preset) are ≤ ⌈3600 / `S10_PRESET_RANGE_MIN_SPACING_S`⌉ + 1 = **7**. That is the fencepost-consistent form of INV-RATE.
  - The bound holds regardless of DPM flapping, S1 reclaims, borrow returns or restarts.
  - **Falsified by** any reachable config that gives one empty zone ≥ 2 S10 calls per 10 min, or S10 and S1 alternating on consecutive ticks.
- **Test (new, discriminating):** `test_s10_no_s1_alternation_on_empty_zone`. Drive `_apply_house_state_presets` 6 ticks on an empty zone with a real `PresetManager` + S1. Assert there is no (S10 call → S1 `preset_change`, same zone) tick pair.
  - It must FAIL on pre-CPR code.
  - A compare-only fix would also fail it; that is the discriminator against the card's original fix.
- **Reviewer D must also try:**
  - zone_1 status/hold split (state-of-play §9.7 second entry)
  - a presets-only borrow return landing on `away`
  - a HUMAN_MANUAL S8 raw restore on an empty zone
  - DPM `cool_high` flapping every tick
  - 8 restarts within an hour
- **Reviewer C mutations:**
  - Re-insert an unconditional emit (the old `and not _compose_away` shape) → `test_s10_empty_zone_no_storm_12_ticks` + the alternation test fail.
  - Delete the spacing check → `test_s10_dwell_zero_flap_bounded_by_spacing` fails.
- **Build-time lint (wire into the pre-deploy zero-bugs gate):**
  - `grep -rn '_last_emitted_range' custom_components/universal_room_automation/` → empty.
  - `grep -n '_compose_away\|_dpm_composed_away_zones' custom_components/universal_room_automation/domain_coordinators/hvac.py` → empty.
- **Live card discriminator (after enable, zone 3 first):** `climate_write` rows `site LIKE 'S10%'` per empty zone per hour ≤ 1 in steady state. The old D9 behaviour gave ~12–48.
- **Card disposition (§9):** unchanged — done on ship by D3/D3c deletion.

### U7 (LOW) — Zone-delete prune anchor was wrong

- §3.4 and §6.3 cite `hvac.py:4044` / `:4044-4081`. Those lines are inside S10 and always were.
- The real site is `_handle_zm_zones_updated` `hvac.py:5328`, which persists via `_rewrite_zone_state_store` :5489-5526.
- CPR must prune BOTH:
  - the persisted `__s10_preset_ranges` sub-dicts;
  - the IN-MEMORY S10 state.
- If only the persisted copy is pruned, the next `_build_zone_state_snapshot` save resurrects it.
- **Test:** `test_s10_zone_delete_prunes_memory_and_store`.

### U8 (LOW) — Side-keys: there are five, not three

- `_build_zone_state_snapshot` (`hvac.py:2349-2373`) already carries `__person_zone_map`, `__short_cycles_today`, `__immune_holds`, `__tao_state` and `__interrupt_latch`.
- The D3b non-collision test covers all five plus `__s10_preset_ranges`.
- Update that method's docstring, which lists only four.

### U9 (LOW) — Small confirmations

- **S10 runs only on full ticks.** The call site is gated `not self._observation_mode and zone_filter is None` (`hvac.py:3870-3871`, v5.103.20 INV-4); fast runs skip DPM. Keep it.
- **Unchanged facts:**
  - The F1 race still holds: initial cycle `hvac.py:1572` runs before `SIGNAL_HVAC_COORDINATOR_READY` at :1580-1581; `not_cold_boot` is at :1190.
  - The F2 premise still holds: `latch_level_check` :2246 runs before `_apply_house_state_presets` :2278.
- **NM strings** must be profile-templated (W1-C ruling 4). The D5 strings are already brand-free. "Bryant app" appears only in operator live-check wording (L3/L9).
- **D0 items 1–3 are still unrun.** `scripts/probes/hvac_preset_profile_probe.py` does not exist (verified). This is still a gate before builder dispatch. Item 1 must also exclude samples within 125 min of any `S10_dpm_apply` `climate_write` row, because switch 01 has been live ON since 10-02.

### Anchor table (develop @`8a4619b32`; old REV 3.x cite → current)

| Symbol | Old | Current |
|---|---|---|
| `_guest_mode_actuation_enabled` init (still `bool = True`) | `hvac.py:664` | `hvac.py:684` |
| `_last_emitted_range` init | `:667` | `:687` |
| S10 call site | `:3849` | `:3870-3871` |
| `_async_apply_preset_overrides` | `:3906-4171` | `:3928-4194` |
| switch gate `if not …` | `:3923` | `:3945` |
| `master_enabled = …` | `:3940` | `:3962` |
| `get_preset_for_house_state` | `:3949-3951` | `:3971-3973` |
| D9 block (incl. transient hold `:4053-4072`, `_compose_away` `:4073`) | `:3985-4067` | `:4007-4083` |
| `_dpm_composed_away_zones` | `:4055-4056` | `:4077-4078` |
| cool − 7 | `:4074` | `:4096` |
| F2 bypass | `:4096-4111` | `:4118-4133` (test `:4132`) |
| `suppress(kind="temp")` | `:4114-4115` | `:4135-4137` |
| S10 wire call (now `_w1c_strategy(...).set_setpoints(..., emit=emit_set_temperature)`) | `:4131-4142` | `:4153-4165` |
| deferred `unsuppress` | `:4150-4151` | `:4173-4174` |
| map write | `:4153` | `:4176` |
| exception `unsuppress` | `:4168` | `:4190-4191` |
| stale map comments | — | `hvac.py:453`, `:505`, `:4021`, `:4122` |
| `_climate_unreadable` | `:2382-2411` | `:2402` |
| `latch_level_check()` call | `:2226` | `:2246` |
| `_apply_house_state_presets` call | `:2258` | `:2278` |
| `_zones_written_this_cycle` | `:505 / :2096 / :3672` | `:525 / :2116 / :3694` |
| `_build_zone_state_snapshot` | `:2329` | `:2349` |
| `_rehydrate_arrester_state` | `:1981` | `:2001` |
| `_note_s1_reclaim` | `:1854` | `:1874` |
| zone-delete rewrite | `:4044` (wrong) | `:5328` / `:5489-5526` |
| `update_throttle` caller | `hvac_predict.py:482` | `:497` |
| map preference read (in `_resolve_baseline_range` `:916`) | `:932-948` | `:947-962` |
| preset fallback | `:951-968` | `:964-985` |
| `update_throttle` kwarg | `:974` | `:989` |
| map read in `_release_banked_zones` | `:1003` | `:1018` |
| S11 map write | `:1153-1154` | `:1170-1171` |
| `update_throttle` caller | `:1260` | `:1277` |
| S13 map write | `:1900-1903` | `:1921-1924` |
| `_interrupt_latched` reader | `:1281-1291` | `:1298-1306` |
| stale map comments/docstrings | `:933-941, :995-1000` | `:182`, `:196`, `:919-962`, `:996-1012`, `:1245`, `:1876` |
| switch `is_on` (`return True` default + getattr True) | `switch.py:~2021` | `:2044-2045` |
| switch-OFF map clear | `:2046-2047` | `:2061-2062` |
| no-last-state "default ON" | — | `:2085-2087` |
| restore fast path / deferred landing | — | `:2092` / `:2120` |
| sensor master_enabled readers | `sensor.py:10199`, `:10231` | `:10217`, `:10249` |
| `_corrective_writes_suppressed` | `hvac_override.py:806` | `:830` |
| `interrupt_latched` / `_latch_state_discharges` / `latch_level_check` def | `:1308-1318` | `:1304` / `:1331` / `:1367` |
| `has_active_ac_reset` | `:2484` | `:2509` |
| `comfort_delay_active` | — | `:2813` |
| arrester "preset range adjustment. Ignore." | `:3619-3622` | `:3652-3654` |
| `manual_guard_verdict` / caller | `hvac_preset.py:234` / `:365` | `:234` / `:369` |
| S1 manual check (now `is_manual_hold_for`) | `:357-358` | `:362-363` |
| funnels | — | `hvac_setpoint.py` `recent_ura_setpoints:94`, `apply_setpoint_guards:146`, `emit_set_temperature:429`, `emit_set_preset_mode:542`, `emit_set_hvac_mode:813` |

---

## REV 3.2 ERRATA (2026-09-29) — authoritative over REV 3.1 wherever they disagree

Re-check verdict: REVISE (small). F2, F3, F6, F7, F8 closed. R1-R5 apply below.

### R1 (MED) — D3c completeness: S11 is a SECOND `_last_emitted_range` producer

REV 3.1 F5's D3c said "S13 is the map's only producer after D3." False. S11 writes the map itself at `hvac_predict.py:1153-1154` (`last_emitted[zone_id] = (emit_low, emit_high)` when `update_throttle`). The `update_throttle` kwarg is defined at `hvac_predict.py:974` and passed at `:482` and `:1260`.

**Supersedes:** D3c deliverable spec; §8 supersession row for `_last_emitted_range`.

**D3c amended (must delete ALL of):**
1. `hvac.py:667` — map init.
2. `hvac_predict.py:932-948` — S11 preference read.
3. `hvac_predict.py:1003` — additional map read (re-check §"Other readers").
4. `hvac_predict.py:1153-1154` — **S11 write [R1 addition].**
5. `hvac_predict.py:974` — **`update_throttle` kwarg definition [R1 addition].**
6. `hvac_predict.py:482, :1260` — **both callers passing `update_throttle=...` [R1 addition].**
7. `hvac_predict.py:1900-1903` — S13 write.
8. `switch.py:2061-2062` — switch-OFF clear.
9. Stale comments at `hvac_predict.py:933-941, :995-1000`.

**S11 behaviour change (R1 safety note, state explicitly in D3c):**
- S11's map value matters only on its HUMAN_MANUAL branch (raw `emit_set_temperature(base_low, base_high)`). The named-snapshot branch pins the preset and writes no values.
- **Before:** that branch wrote whatever the map held — either S13's pre-heat pre-borrow snapshot or an older S11/S10 pair, possibly days old.
- **After:** S11 writes `_resolve_baseline_range`'s fallback (`hvac_predict.py:951-968`) — the configured `(heat, cool)` of the house-state target preset. Well-defined, never stale, low side fixed since v5.103.22.
- The change matters on a pre-heat-sourced-value path: S11 used to accidentally write the person's own pre-heat values (from S13's snapshot); it now writes URA's baseline. Small behaviour change on a rare path, arguably more correct (those values belonged to the pre-heat token, not the banking one). **Safe.**
- Outside tests, the only readers are `hvac.py:4108` (deleted by D3), `hvac_predict.py:932` / `:1003`, and `switch.py:2046` — all in the DELETE list. No sensor / diagnostics / frontend reads the map.

**Test files touching `_last_emitted_range` (11 — D3c must list for rewrite or retirement, like D3 does):**
- `test_arrester_comfort_delay.py`
- `test_freeze_floor.py`
- `test_hc_precool_oc_observability.py`
- `test_hvac_excursion_banking_migration.py`
- `test_hvac_excursion_preheat_migration.py`
- `test_hvac_live_room_hold_wire_in.py`
- `test_hvac_w1b_returns_and_strategy.py`
- `test_hvac_w1w2_finish_part_b.py`
- `test_v471_fixup_d2_d3_d4.py`
- `test_v5_7_1_energy_precool.py`
- `test_zzz_hvac_conditioning_demand.py`

Each file's map-related assertions get rewritten to assert the post-retirement behaviour (S11 writes preset-resolved values; S13 does not touch a map) OR the test is retired if the map WAS the subject under test.

### R2 (MED) — Tri-state flag needs a backstop timeout

REV 3.1 F1's flag is resolved only by the switch entity (`async_added_to_hass` / `_handle_hvac_ready`). If the switch entity is disabled in the registry, or the switch platform fails to set up, no entity is added and the flag stays `None` forever. S10 is then inert permanently: no apply (fine) and **no restore**. Edited presets keep URA's ranges indefinitely — INV-RESTORE silently violated.

**Supersedes:** §3.5 (add fourth resolution path); §3.2 method entry (backstop resolution); new constant in §6.1.

**Fix:**
- **New rung-1 constant** in `hvac_const.py`: `S10_SWITCH_RESOLUTION_TIMEOUT_S = 300` (5 min). Rung 1 because it is a boot-lifecycle invariant, not an operator knob; change requires review.
- After boot-settle release AND `S10_SWITCH_RESOLUTION_TIMEOUT_S` elapsed since coordinator setup, if `_guest_mode_actuation_enabled is None`, resolve to `False` via `set_custom_ranges_enabled(False, source="unresolved_backstop")`. Fires the F1 NM (`s10_restart_default_off_restore_pending`) with the reason line adjusted for this path: *"Custom Preset Ranges switch did not resolve after {N} minutes; treating as off. If you had it on, re-enable it now."* — a distinct NM id `s10_switch_unresolved_backstop` (info level; one per boot).
- Implementation: schedule an `async_call_later(S10_SWITCH_RESOLUTION_TIMEOUT_S, ...)` at coordinator boot; the callback checks `_guest_mode_actuation_enabled is None` and calls `set_custom_ranges_enabled(False, source="unresolved_backstop")`. Cancelled if the flag resolves earlier (any other source).
- Backstop is `source="unresolved_backstop"` in §3.5 — a fifth resolution path.
- **New test:** `test_s10_backstop_resolves_false_after_timeout` — simulate switch entity never added; after 5 min, flag resolves False; one info NM `s10_switch_unresolved_backstop`; the restore pass runs on the next tick.
- **New falsifier Q11:** any `climate_write` `site=S10_preset_range*` where the ts is > `S10_SWITCH_RESOLUTION_TIMEOUT_S + HVAC_DECISION_TICK` after boot AND no switch-resolution ledger row precedes it → 0.

### R3 (LOW) — `test_s13_no_map_write_after_retirement` was a grep-as-test

REV 3.1 F5's `test_s13_no_map_write_after_retirement` is grep-as-test (Bug Class #62, hollow anchor). Keep the grep as a **build-time lint**, but the pytest assertion is behavioural.

**Supersedes:** D3c tests.

**D3c tests (final):**
- **Build-time lint** (not a pytest run): `grep -rn '_last_emitted_range' custom_components/universal_room_automation/` returns empty. Wire this into the pre-deploy zero-bugs gate script.
- **Pytest — behavioural:**
  - `test_s11_baseline_uses_preset_resolved_after_map_retirement` — S11 restore reads the preset-baseline fallback, not any map. Drives `_release_banked_zones` on the HUMAN_MANUAL branch and asserts the emitted values equal `_resolve_baseline_range(house_state)` output.
  - `test_s11_write_reflects_baseline_not_map_pair` **[R3 replacement, replaces `test_s13_no_map_write_after_retirement`]** — construct a scenario where (pre-retirement) S13 would have written a stale pair into the map (pre-heat snapshot with values X, Y); run S13 return then S11 release on HUMAN_MANUAL path; assert S11 emits the resolved-baseline pair, NOT (X, Y).
  - `test_s13_return_writes_no_setpoints_after_map_retirement` — S13 return path calls no `set_temperature`; only the presets-only return runs.

### R4 (LOW) — `None`-unsafe readers the tri-state must handle

REV 3.1 F1 changed the flag init to `None` but did not audit every reader. `hvac.py:3923` `if not self._guest_mode_actuation_enabled` treats `None` as OFF, which is exactly the F1 bug that motivated the tri-state.

**Supersedes:** §3.2 method entry ordering; §Q2 sensor row; D8 wording.

**Fix (every reader):**
- **`hvac.py:3923`** — the `is None` return must come BEFORE the `if not ...` gate. Explicit order in §3.2:

  ```
  if self._guest_mode_actuation_enabled is None:
      _LOGGER.debug("S10: switch unresolved; deferring")
      return
  if self._guest_mode_actuation_enabled is False:
      # restore pass (§3.4)
      ...
      return
  # apply pass (True)
  ```

- **`hvac.py:3940`** (`master_enabled = self._guest_mode_actuation_enabled`) — under the tri-state discipline this line is unreachable while `None` (the earlier `is None` return fires first). Leave the assignment as-is but add an inline `assert self._guest_mode_actuation_enabled is not None` for reviewer clarity.
- **`sensor.py:10199`** (getattr(..., True) attribute exposure) — render `None` as `"unknown"` (or HA's `STATE_UNKNOWN`), not `True`. Never claim True while unresolved.
- **`sensor.py:10231`** — same rule.
- **Switch `is_on` (`switch.py:2021-2022` region, grep for `getattr(coordinator, "_guest_mode_actuation_enabled", True)`)** — render `None` as `is_on = None` (HA's "pending" for a switch; the state renders as `unknown`), not `True`. HA switches accept a `None` state during setup.
- **D8 wording updated:** was *"change all four defaults to False"*; now reads: *"init `_guest_mode_actuation_enabled = None` at `hvac.py:664`; every reader (`hvac.py:3923`, `hvac.py:3940`, `sensor.py:10199`, `sensor.py:10231`, and the switch `is_on` reader) renders `None` explicitly as unknown/pending, never as True. The four switch source paths (§3.5) resolve `None` to a Bool; the R2 backstop provides the fifth path."*
- **New tests (add to D8):**
  - `test_sensor_renders_none_as_unknown_not_true`
  - `test_switch_is_on_renders_none_as_none`

### R5 (LOW) — F4 test arithmetic

REV 3.1 F4's `test_s10_dwell_zero_flap_bounded_by_spacing` claimed "≤ 3 wire calls" for a 30-min flap with 600 s spacing. Actual arithmetic: calls allowed at t=0, 10, 20, 30 min → **4 calls**.

**Supersedes:** D4 acceptance verify line; F4 changelog item wording; §6.3 budget-table cell wording (cosmetic).

**Fix:**
- Assertion becomes **≤ 4 wire calls** for a 30-min flap.
- Test name unchanged; docstring updated to explain the fencepost.
- Equivalent alternative (also acceptable): shorten the flap window to 25 min and assert ≤ 3.
- **§6.3 budget-table row "DPM change (any dwell)"** is textually correct at "≤ 1 call per `S10_PRESET_RANGE_MIN_SPACING_S` (10 min) per (zone, preset) — so ≤ 6/h/(zone, preset)" and needs no change.

### Lint clarification (companion to F3)

The F3 lint must **accept** the funnel's non-literal `async_call(service_domain, service_name, ...)` call — the domain and name are `Name`-typed AST nodes, not string literals. The AST test rejects string-literal `"ha_carrier"` outside `hvac_strategy.py`; it does NOT reject a variable-typed domain argument. Add one lint-of-the-lint test that constructs a fake caller passing `service_domain=some_var` and verifies the lint passes it.

---

## REV 3.1 ERRATA (2026-09-29) — authoritative over REV 3 wherever they disagree (unchanged, retained for context)

Plan review verdict: REVISE (no redesign). Fixes F1-F8 from `docs/reviews/code-review/plan_review_hvac_cpr_rev3.md`. Each item names the section(s) it supersedes; the rest of REV 3 stands. **REV 3.2 R1-R5 above further amend F1, F4 and F5.**

### F1 (HIGH) — Tri-state CPR flag + boot/reload race

**Supersedes:** §3.2 method entry; §3.4 "Restore on OFF"; D3, D3b, D8; INV-RESTORE. **REV 3.2 R2 adds the backstop timeout; R4 adds the reader audit.**

The RestoreEntity path can land the switch value *after* the coordinator's first decision cycle (state-of-play §2 boot-settle release; `hvac.py:1169-1170` `not_cold_boot` + initial cycle ~`:1363` before the switch's deferred `SIGNAL_HVAC_COORDINATOR_READY` handler runs). With D8 default OFF, a snapshot-present zone would run one restore call per reload before the switch resolves True, then the apply record blocks re-emit for 130 min — the operator's zone runs Carrier defaults for up to 130 min per reload, plus spurious latch churn.

**Fix (plan text; no redesign):**
1. Make `_guest_mode_actuation_enabled` **tri-state**: `None` = not-yet-resolved, `True`/`False` = resolved. Init to `None` at `hvac.py:664`.
2. `set_custom_ranges_enabled(value, *, source)` is the sole writer (§3.5). ALL FIVE switch paths (`user` turn_on/turn_off, RestoreEntity path, no-last-state default → False, **REV 3.2 R2 backstop timeout → False**) must call it. The no-last-state default from D8 is a *resolution*, not "still None".
3. S10 method entry (`_async_apply_preset_overrides`): if `self._guest_mode_actuation_enabled is None`, return immediately — **neither apply nor restore**. Debug log `"S10: switch unresolved; deferring"`. No wire call, no snapshot capture, no counter, no NM. **[R4] the `is None` check MUST precede `hvac.py:3923`'s `if not ...`.**
4. The restore pass is state-driven ONLY when the flag has resolved to `False`.
5. A restart that boot-restores `True` OR `False` runs normally next tick. A restart into a lost-restore-state landing (`None → False` via the no-last-state default OR the R2 backstop) does the same, but §3.5 adds a **single info NM** on that path: `s10_restart_default_off_restore_pending` — title *"Custom Preset Ranges default is off after restart"*, message *"URA is putting back the original ranges on {n} presets as each zone next uses them."* This is the *documented* silence path: NM + one ledger row `s10_default_off_after_restart`. Not carded as a defect.

**New tests (added to D3 and D3b, plus R2/R4 additions):**
- `test_s10_no_write_before_switch_resolved` — flag `None` for cycles 1..3, snapshot exists, zone on named preset → **zero** wire calls; cycle 4 resolves flag → normal behaviour.
- `test_s10_no_restore_before_switch_resolved` — flag `None`, snapshot exists → zero restore calls.
- `test_s10_reload_race_no_restore_when_actually_on` — restart with restored `on` state landing on cycle 2; cycle 1 sees `None` → 0 calls; cycle 2 sees `True` → apply pass runs.
- `test_s10_default_off_no_last_state_emits_one_nm` — no last state, snapshots present → one `s10_restart_default_off_restore_pending` NM per boot; not repeated on subsequent restarts if snapshots drain.
- **`test_s10_backstop_resolves_false_after_timeout` [R2]** — switch entity never added; after `S10_SWITCH_RESOLUTION_TIMEOUT_S`, flag resolves False; one info NM `s10_switch_unresolved_backstop`; restore pass runs next tick.
- **`test_sensor_renders_none_as_unknown_not_true` [R4]**
- **`test_switch_is_on_renders_none_as_none` [R4]**

**T-mutation:** neuter step "if flag is None: return" → `test_s10_no_write_before_switch_resolved` fails.

**INV-RESTORE clarified:** *"...and while switch 01 has resolved to False (never while `is None`)."*

### F2 (MED) — Drop step 3.5, T10, Q8 and L11 (unreachable); replace with a defence-in-depth note

**Supersedes:** §3.2 skip step 3.5; §3.6 last bullet; D3 tests (drop `test_s10_defers_when_interrupt_latched`); §7.1 Q8; §7.3 L11; §10 T10; INV-S10 (drop the latch clause); §6.3 budget-table row "Zone interrupt-latched". CLOSED per re-check.

The interrupt latch discharges at LEVEL any time the state is readable, named and not `manual` (`hvac_override.py:1308-1318`). `latch_level_check()` runs at `hvac.py:2226`, **before** `_apply_house_state_presets` at `hvac.py:2258`, so before S10. A zone that is BOTH interrupt-latched AND on a named preset is a shape the code prevents from persisting past the pass boundary; step 6 (`P ∈ {home, sleep, away, vacation}`) or step 0.5 (unavailable) already skips every reachable path.

**Fix:** DELETE step 3.5, D3 test, T10, Q8, L11, INV-S10 clause, budget row. Retain as a one-line NOTE at end of §3.2 naming `OverrideArrester.interrupt_latched(entity_id)` as the ONE reader for future refactoring. Reviewer B assumption verified at build time.

### F3 (MED) — One consistent rule for the service literal; one lint

**Supersedes:** D1 (funnel body + acceptance test text); §14 "REV 3 correction to D1"; §2.1 AST lint row. CLOSED per re-check.

**Fix (adopt §14; rewrite D1):**
- D1 signature: `emit_set_activity_setpoint(hass, entity_id, *, service_domain: str, service_name: str, target_temp_low, target_temp_high, freeze_active, blocking, gate, site, zone_id, reason) -> bool`. Funnel body contains `await hass.services.async_call(service_domain, service_name, {...}, blocking=blocking)`. `"ha_carrier"` and `"set_activity_setpoint"` appear ONLY in `CarrierStrategy.set_preset_range` (D2).
- D1 lint: AST test forbids `hass.services.async_call("ha_carrier", ...)` outside `hvac_strategy.py`; also forbids the literal `"ha_carrier"` in `hvac_setpoint.py`. **[REV 3.2 clarification]** The lint MUST accept a non-literal domain argument — the funnel's `async_call(service_domain, ...)` is a `Name` AST node, not a string literal. Add a lint-of-the-lint test that verifies a fake caller with `service_domain=some_var` passes.
- New test `test_emit_set_activity_setpoint_uses_caller_supplied_domain`.

### F4 (MED) — Per-(zone, preset) minimum spacing across values

**Supersedes:** §6.1 constants; §6.2 rate/latch model bullet 1; §6.3 budget table; INV-RATE. CLOSED per re-check **with REV 3.2 R5 arithmetic fix (≤ 4 not ≤ 3).**

New constant `S10_PRESET_RANGE_MIN_SPACING_S = 600` (10 min, rung 1). §6.2 bullet 1 becomes: value-change resets counters but keeps `last_attempt_iso`; new value writes only if `now − last_attempt ≥ 600s`, else DEFERRED (`per_key_min_spacing`). INV-RATE updated. New tests `test_s10_dwell_zero_flap_bounded_by_spacing` (**R5: ≤ 4 wire calls over 30-min flap**), `test_s10_value_change_resets_record_but_respects_spacing`.

### F5 (MED) — Restore-writers card closure + `_last_emitted_range` producer-loss

**Supersedes:** §9 disposition of `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1`; §8 supersession row for `_last_emitted_range`; §2.1 row. **Amended by REV 3.2 R1** (adds S11 write, throttle kwarg, callers, 11-test-file list, S11 behaviour-change note) and **R3** (behavioural tests, grep as build-time lint only).

Close the strand card on the by-construction proof (only reader `hvac.py:4108` + only writer `hvac.py:4153`, both deleted by D3). D0 item 4 is corroboration, not the gate. `_last_emitted_range` map retired by D3c — see R1 for the full deletion list and test-file list.

### F6 (LOW) — Stale anchors outside the S10 block + `:4168` unsuppress

Corrected: `_corrective_writes_suppressed` :672→:806, `has_active_ac_reset` :2183→:2484, arrester "preset range adjustment. Ignore." :3216-3226→:3619-3622, `_build_zone_state_snapshot` :2081-2103→:2329, `_rehydrate_arrester_state` :1059→:1981, `_note_s1_reclaim` :1653-1695→:1854, `_zones_written_this_cycle` :455/:1879/:3194→:505/:2096/:3672, switch clear :2037-2039→:2046-2047. Added `hvac.py:4168` (third `unsuppress`, exception-path roll-back) to the DELETE list. CLOSED per re-check.

### F7 (LOW) — P4's HA-view match caveat

Snapshot capture bullet in §3.4 states the guard-masked-match case: harmless (nothing edited, cloud IS the pre-URA original). CLOSED per re-check.

### F8 (LOW) — Q7 rekeyed

**Q7:** *"S10 rows whose `values_before.state ∈ HVAC_CLIMATE_UNREADABLE_STATES` → 0. Equivalent join form: no `climate_write` row with `site ∈ {S10_preset_range, S10_preset_range_restore}` falls inside a `climate_write_held_unreadable` episode for the same `entity_id`."* CLOSED per re-check.

### Tier decision — Tier 2-DB PLUS a mandatory 4th adversarial-completeness reviewer

Stay at Tier 2-DB (three framing-disjoint reviews); **add one mandatory 4th reviewer, Reviewer D — adversarial completeness — scoped to INV-RESTORE and the switch/boot lifecycle.** REV 3.2 R2 (backstop) extends D's scope to include the still-`None` gap.

---

### REV 3 changelog (2026-09-29) — what changed since REV 2

*(REV 3.1 supersedes items in the errata above; REV 3.2 further amends F1/F4/F5. The rest stands.)*

REV 3 was produced by re-reading `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` in full (589 lines: Batch B v5.103.21-23; Batch D v5.103.24/25; §4.2 W1-A funnel table; §7 arrester ↔ AC-reset interplay; §9e "person interrupts"; §10 C25-C29 corrections ledger; §11 W1-C position at step 5) and re-greping every write site the REV 2 plan cited on current `develop`. **The plan's behaviour is unchanged. What moved is (a) file:line anchors, (b) two new mandatory skips CPR must inherit, (c) tier framing, (d) explicit Carrier-profile scoping for the coming W1-C generic-thermostat cycle, (e) explicit fold of the three blocker cards as deliverables.**

**1. Every `hvac.py` line number in REV 2 is STALE.** Batch B v5.103.23 + Batch D v5.103.24 inserted ~500 lines above S10. Re-verified by grep on `develop` @ 2026-09-29:

| REV 2 cite | Current | Symbol |
|---|---|---|
| `hvac.py:540` | `hvac.py:664` | `_guest_mode_actuation_enabled` (init to `None` per REV 3.1 F1) |
| `hvac.py:543` | `hvac.py:667` | `_last_emitted_range` map init (DELETED by F5/R1 D3c) |
| `hvac.py:3317-3320` | `hvac.py:3849` | `await self._async_apply_preset_overrides()` |
| `hvac.py:3373-3638` | `hvac.py:3906-4171` | `_async_apply_preset_overrides` (S10 method) |
| `hvac.py:3390` | `hvac.py:3923` | switch gate — **[R4] the `is None` return precedes this** |
| `hvac.py:3416` | `hvac.py:3949-3951` | `get_preset_for_house_state(self._house_state)` |
| `hvac.py:3452-3528` | `hvac.py:3985-4067` | D9 compose-away block |
| `hvac.py:3488-3517` | inside `hvac.py:3985-4067` | S10 transient hold |
| `hvac.py:3522-3526` | `hvac.py:4055-4056` | `_dpm_composed_away_zones` counter |
| `hvac.py:3541` | `hvac.py:4074` | `baseline_low = baseline_cool - 7.0` |
| `hvac.py:3563-3578` | `hvac.py:4096-4111` | F2 throttle bypass |
| `hvac.py:3581-3582`, `:3617-3618`, `:3634-3635` | `hvac.py:4114-4115`, `:4150-4151`, **`:4168` (REV 3.1 F6)** | arrester suppress stamps to DELETE |
| `hvac.py:3598-3609` | `hvac.py:4131-4142` | `emit_set_temperature` to REPLACE |
| `hvac.py:3620` | `hvac.py:4153` | throttle-map write to DELETE |
| `hvac_preset.py:333` | `hvac_preset.py:234`, caller `:365` | `manual_guard_verdict` — `borrow_live` factoring valid |
| `hvac_preset.py:293-317` | `hvac_preset.py:234-345` | gate (e) inside `manual_guard_verdict` |
| `hvac_setpoint.py:127-160, :163+, :258` | present, plus `emit_set_hvac_mode` `:813-859` | funnel helpers |
| `ha_carrier/climate.py:91-104, :467-537, :539-596` | unchanged in v2.28.4 (§5, C15) | `set_activity_setpoint` upstream, HACS-safe |

REV 3.1 F6 stale-anchor corrections: `_corrective_writes_suppressed` :672→:806; `has_active_ac_reset` :2183→:2484; arrester ignore :3216-3226→:3619-3622; `_build_zone_state_snapshot` :2081-2103→:2329; `_rehydrate_arrester_state` :1059→:1981; `_note_s1_reclaim` :1653-1695→:1854; `_zones_written_this_cycle` :455/:1879/:3194→:505/:2096/:3672; switch clear :2037-2039→:2046-2047; switch paths shifted 5-10 lines (grep callers of `set_custom_ranges_enabled`).

**Action for the builder:** treat REV 2 site labels (S10, F2, compose-away, cool-7) as the source of truth for **what** changes; use the tables above for **where**. Re-grep before touching.

**2. NEW SKIP — unavailable/unknown climate entity (from Batch D v5.103.24).** Consult `HVACCoordinator._climate_unreadable(zone_id, zone)` at `hvac.py:2382-2411`. Added to §3.2 skip matrix as step 0.5.

**3. ~~NEW SKIP — interrupt latch~~ [REV 3.1 F2: SUPERSEDED — unreachable]**

**4. S6/S7 INFO-1 interaction — NO plan change; interoperates cleanly.**

**5. Blocker fold:** see §9. REV 3.1 F5 + REV 3.2 R1 rebase the restore-writers card closure.

**6. Tier — Tier 2-DB + mandatory Reviewer D** (REV 3.1). See §11.

**7. Carrier-specific vs profile-agnostic scoping (new §14)** — collapsed with REV 3.1 F3.

**8. Read-first attestation refreshed.**

---

## Read-first attestation

- I read `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` completely (589 lines on `develop` @ 2026-09-29), including Batch B v5.103.21-23, Batch D v5.103.24/25, §3.2, §4.1, §4.2, §4.2b, §4.3, §5, §6, §7, §9e, §10 C1-C29, §11 W1-C.
- **[REV 3.1]** I read `docs/reviews/code-review/plan_review_hvac_cpr_rev3.md` (134 lines); F1-F8 addressed.
- **[REV 3.2]** I re-read the same file's §"REV 3.1 re-check" (lines 137-180); R1-R5 addressed here.
- W1-B shipped v5.103.18: S1 manual guard replaced by four gates; borrow returns presets-only.
- Batch B v5.103.23 (built not deployed): within-manual detection, human-interrupt ends borrows, interrupt latch persistence + level discharge.
- Batch D v5.103.24 (built not deployed): Fan Mode, unreadable-thermostat guard on B1/S1, INFO-1 nudge-restore, arrester ↔ AC-reset separation.
- This plan re-asserts nothing in §10 (C1-C29): does not rely on the retired v3.8.0 guard (C25); does not treat `hold_activity` as universal oracle (C20/C22/C23); does not use 42-79 s as Carrier schedule (C16); does not call `set_activity_setpoint` a local patch (C15); does not claim ha_carrier re-sends to the cloud (C21); does not remove the `_auto_return` manual-skip (C26); does not pin `manual` in boot audit / S4 revert (C28/C29).
- Both blocker cards read in full; operator constraint honoured (no `begin_excursion` change).
- CPR parent card requires re-check against v5.103.23 (Batch B); REV 3 is that re-check, REV 3.1 folds plan-review, REV 3.2 folds re-check.

---

### REV 2 delta (retained for the re-reviewer)

| Finding | Where fixed |
|---|---|
| HIGH-1: controlled live test | §4 D0 item 5 (PASSED zone_3 2026-09-28) |
| M1: confirmation rationale | §3.3 P4, §6.1, §7.3 L3 |
| M2: latch rule; FAILED counted separately | §6.2 |
| M3: persistence across restarts | §6.3 |
| M4: drop `suppress(kind="temp")` | §3.2 step 11, §2.1 row; **REV 3.1 F6 adds `:4168`** |
| LOW-1: P1 rationale | §3.3 P1 |
| LOW-2: after-call check | §3.3 P6 |
| LOW-3: clear records on switch paths | §3.5 |
| LOW-4: heat fallback | SHIPPED v5.103.22 (`HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` DONE) |
| LOW-5: preset-range consumers | §2.7 |
| LOW-6: switch default OFF | D8 (operator YES); **REV 3.1 F1: init `None` + resolutions; REV 3.2 R4: readers audit** |
| LOW-7: reword INV-RATE | §7.1; **REV 3.1 F4: per-key spacing; REV 3.2 R5: ≤ 4 not ≤ 3** |
| New-funnel sanction | §12 |
| Operator Q2: restore Carrier originals | §3.4 + D3b |

---

## STEP 0 — what the feature is today, and the real knob

### Q1. What does the feature do today, and why was it dormant?

The only actuator is `HVACCoordinator._async_apply_preset_overrides` (site **S10**, `hvac.py:3906-4171`). It is called at the end of `_apply_house_state_presets` (`hvac.py:3849`), in the same tick and right after S1. It returns immediately when `_guest_mode_actuation_enabled` is False (`hvac.py:3923` — REV 3.1 F1 makes tri-state; REV 3.2 R4 places the `is None` return BEFORE this line).

When the switch is ON, S10 does this for every zone on every tick:
1. Takes the **house-state** preset (`hvac.py:3949-3951`). Exception: D9 compose-away swaps in `away` for established-empty zones (`hvac.py:3985-4067`).
2. Builds a baseline from URA's seasonal table (`get_seasonal_setpoints`, `hvac_preset.py:126-180`).
3. **Sets low side to `cool − 7` and throws away the configured heat value** (`hvac.py:4074`).
4. Layers OverrideEngine records from EC `_dynamic_preset_overrides` (`energy.py:7126-7319`).
5. Writes **raw `climate.set_temperature`** via `emit_set_temperature` (`hvac.py:4131-4142`) when the pair differs from `_last_emitted_range`. On compose-away zones, every tick (F2 bypass, `hvac.py:4096-4111`).

Under W1-B, S1 reclaims the manual hold on the next tick. Occupied zones settle silently. Empty zones storm at ~48 Carrier calls/h/zone via F2. Bug Class #63: `cool − 7` equals configured heat only by coincidence (winter away 80/65 → heat 73 °F to an empty zone).

**Why it was dormant.** v5.103.7 shipped D9/F2 assuming this switch stays off; W1-B added the S1-vs-S10 fight; the switch is off in every recorded state since 09-18.

### Q2. Is `switch.ura_hvac_coordinator_guest_mode_actuation` the right switch?

**Yes.**

| Entity id | Label | Backing field | Live |
|---|---|---|---|
| `switch.ura_hvac_coordinator_guest_mode_actuation` | **"01 · Custom Preset Ranges"** (`switch.py:1998`) | `HVACCoordinator._guest_mode_actuation_enabled` (`hvac.py:664`) | off |
| `switch.ura_energy_coordinator_dynamic_preset_overrides` | **"02 · Dynamic Preset Auto-Adjust"** (`switch.py:1715`) | `EnergyCoordinator._dynamic_preset_enabled` (`energy.py:791`) | off |

Notes: real entity id has no `_enabled` suffix. Switch 01 is the only actuation gate. Per-zone opt-in is `true` on all four zone configs. Stored `dynamic_preset_enabled: true` vs restored `off` mismatch carded (§12). `en.json:1244` and `:1231` wrong while 01 is off; fixed in D5.

---

## 1. Config-first check

| Candidate | Solves it? |
|---|---|
| Flip 01 ON with no code change | **No, harmful**: storm + winter-away 73 |
| Flip 02 only | No: nothing actuates |
| Type ranges into each Bryant preset | **Partly**; loses automation |
| `ha_carrier` `infinite_holds` | No |

**Verdict: BUILD** (operator YES), D0 item 5 PASSED.

---

## 2. Institutional context verified

### 2.1 Prior-art scan (REUSE / BUILD per piece)

| Piece | Verdict | Existing symbol / justification |
|---|---|---|
| Write a preset's range without a hold | **REUSE upstream** `ha_carrier.set_activity_setpoint` | `climate.py:91-104, :539-596` (C15). |
| Funnel for the new verb | **BUILD** `emit_set_activity_setpoint` | W1-A-sanctioned. REV 3.1 F3: takes `service_domain`/`service_name` from caller; funnel never hard-codes `"ha_carrier"`. |
| Per-brand rules | **REUSE + extend** `hvac_strategy.py` | Adds `set_preset_range` on `GenericStrategy` (FAILED unsupported) and `CarrierStrategy` (P1-P6). SOLE site of the `"ha_carrier"` + `"set_activity_setpoint"` literals. |
| Live-borrow read | **REUSE** gate (e) (`hvac_preset.py` `manual_guard_verdict` `:234`, caller `:365`) | Extract into pure `borrow_live(zone_id)`. |
| Person-protected skip | **REUSE** `_corrective_writes_suppressed` (`hvac_override.py:806` — REV 3.1 F6) | |
| Unreadable-climate skip | **REUSE** `_climate_unreadable(zone_id, zone)` (`hvac.py:2382-2411`) | Batch D v5.103.24. |
| ~~Interrupt-latch skip~~ | **[REV 3.1 F2: DROPPED — unreachable]** — sole named predicate is `OverrideArrester.interrupt_latched(entity_id)`; sole reader `hvac_predict.py:1281-1291`. |
| Comfort-delay defer | **REUSE** `_s10_gate` / `comfort_delay_active` (`hvac.py:4118-4130`) |
| Same-tick S1 skip | **REUSE** `_zones_written_this_cycle` (`:505 / :2096 / :3672`) |
| AC-reset / egress skips | **REUSE** `has_active_ac_reset` (`hvac_override.py:2484`), `is_paused` |
| Range values | **REUSE** `get_seasonal_setpoints` + OverrideEngine + EC overrides |
| Arrester must not book S10 | **REUSE, no stamp** (M4) — `hvac_override.py:3619-3622`. DELETE `hvac.py:4114-4115` + `:4150-4151` + `:4168`. |
| Persistence | **REUSE** `_zone_state_store` side-key (`hvac.py:2329`, rehydrate `:1981`) | New side-key `__s10_preset_ranges`. Coexists with `__interrupt_latch`, `__immune_holds`, `__tao_state`. |
| Trip-wire NM | **REUSE pattern** `_note_s1_reclaim` (`hvac.py:1854`) |
| AST lint | **EXTEND** `test_hvac_climate_write_funnel_completeness.py` | REV 3.1 F3: forbid `hass.services.async_call("ha_carrier", ...)` outside `hvac_strategy.py`; forbid `"ha_carrier"` literal in `hvac_setpoint.py`. **REV 3.2 clarification: variable-domain `async_call(service_domain, ...)` is ALLOWED.** |
| D9 compose-away, F2, transient hold, `_dpm_composed_away_zones`, cool-7 | **DELETE** (§8) |
| `_last_emitted_range` map | **[REV 3.1 F5 + REV 3.2 R1: DELETE]** — D3c retires init at `hvac.py:667`; readers `hvac_predict.py:932-948, :1003`; writers `hvac_predict.py:1153-1154` (S11), `:1900-1903` (S13); kwarg `update_throttle` `:974` + callers `:482, :1260`; switch clear `switch.py:2061-2062`. Stale comments `:933-941, :995-1000`. |

**Surfaces grepped:** const files; config/flow; switch/sensor; `hvac*.py`; energy.py, dynamic_preset.py, preset_overrides.py; ha_carrier {climate,const,data_update_coordinator}.py; quality/tests (7 files call `_async_apply_preset_overrides`, 11 reference `_last_emitted_range` per R1). Batch B/D adds re-greped: `HVAC_CLIMATE_UNREADABLE_STATES`, `_climate_unreadable`, `_interrupt_latch`, `_latch_state_discharges`, `pre_arrival_reference_preset`, `emit_set_hvac_mode`.

### 2.2 Prior plans
As REV 3. Adds `PLANNING_hvac_w1_w2_finish.md` REV 2 (Batch B).

### 2.3 READMEs
v5.103.7, v5.103.18, v4.7.1-4.7.3; NEW REV 3: v5.103.23 (Batch B), v5.103.24 (Batch D).

### 2.4 Memory
`feedback_label_style_guide`, `reference_hvac_state_of_play`, marginal-benefit, config-first, `feedback_unrestored_mutation_drill_poisons_evidence`, `feedback_suppression_needs_discharge`, `feedback_orchestrator_stays_in_main_checkout`, `feedback_do_robust_fix_not_bandaid_and_card` (F5).

### 2.5 Design docs
State-of-play (589 lines); `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §2–§3, verb table, open item 6 (closed by D0-5).

### 2.6 Code read
- `hvac.py` — S10 `3906-4171`, S1 `2913-3210`, boot rehydrate `1873-1880` / `2329` / `1780-1871`, `_note_s1_reclaim` `1854`, `_climate_unreadable` `2382-2411`, imports `:53`, episode init `:551`
- `hvac_preset.py` (all), `hvac_strategy.py` (all), `hvac_setpoint.py` incl. `emit_set_hvac_mode` `:813-859`
- `preset_overrides.py`, `dynamic_preset.py`, `energy.py` 7126-7319
- `switch.py` 1685-2104, `sensor.py` 10128-10260
- `hvac_override.py` 806, 2484, 3619-3622; latch `:1308-1318`; `interrupt_latched` reader (`hvac_predict.py:1281-1291`)
- `hvac_excursion.py` — `_auto_return` C26 skip **RETAINED**
- `hvac_predict.py` 150-195, 855-1065, **482, 932-948, 951-968 (`_resolve_baseline_range` fallback), 974, 1003, 1132-1140, 1153-1154, 1260, 1281-1291, 1900-1903 (all D3c sites, REV 3.2 R1)**
- `ha_carrier/climate.py` 60-600, const 40-64, coordinator 145-345/425-435
- **REV 3.1/3.2:** `docs/reviews/code-review/plan_review_hvac_cpr_rev3.md` (all 180 lines)

### 2.7 Every consumer of a preset profile's setpoints (LOW-5)

*(unchanged from REV 3; every consumer reads the live profile, which is intended)*

Zone refresh; nudge trigger / start / restore (incl. Batch D S6/S7 INFO-1); nudge outcome; hard reset; boot ramp; arrester detection delta; within-manual detection (Batch B — CPR writes NOT recorded because `emit_set_activity_setpoint ≠ emit_set_temperature`); comfort-grant; startup audit (named zones skipped); excursion begin snapshot; pre-cool/banking; pre-heat; predictor demand deltas; fans (Batch D Fan Mode-gated); covers; diagnostics; sensor; strategy observe; PWA. See REV 3 §2.7 table for file:line and trust/display classifications.

---

## 3. Design

### 3.1 Core move: write the preset's profile, never a hold

S10 edits the zone's **named preset profile** in place through `ha_carrier.set_activity_setpoint`, and only while the zone is on that preset. Two independent reasons nothing reacts:
- S1 has nothing to reclaim (`hvac_preset.py:357-358`).
- The arrester ignores the change (`hvac_override.py:3619-3622`).

W1-B's presets-only returns, arrester reverts and schedule transitions all land on named presets that carry the range, so no after-borrow corrector is needed.

**Batch B interaction:** the "person interrupts" path fires only on a CHANGED leg where both states are `heat_cool`. A CPR profile edit does not change any leg on any zone on a different preset; on the target zone it edits the profile the zone is on, which the arrester ignores. CPR writes cannot spuriously trigger the interrupt path.

Rejected: EXCURSION_KIND (operator constraint); per-tick flag (loses the range on S1 reclaim); "write a preset" (a preset cannot carry a custom range).

### 3.2 S10 per-zone algorithm

**Method entry [REV 3.1 F1 tri-state + REV 3.2 R4 ordering]:**

```
if self._guest_mode_actuation_enabled is None:
    _LOGGER.debug("S10: switch unresolved; deferring")
    return  # MUST precede hvac.py:3923's `if not ...` gate
if self._guest_mode_actuation_enabled is False:
    # restore pass (§3.4) if snapshots exist
    return
# apply pass (True)
```

The observation-mode gate at the call site (`hvac.py:3849`) is unchanged. An absent EC or empty overrides no longer returns early, because the static half still applies.

**Apply pass, per zone.** First skip wins; each skip is `continue` + debug log.
0.5. `self._climate_unreadable(zone_id, zone)` (`hvac.py:2382`). No wire call, no snapshot, no rate-clock consumption. Existing helper writes one INFO + one `climate_write_held_unreadable` row per outage EPISODE — do NOT open a second episode for S10.
1. `egress_manager.is_paused(zone_id)`.
2. `arrester._corrective_writes_suppressed(zone_id)` (`hvac_override.py:806`), plus `_log_shave_skipped(..., "dpm_preset_override")`.
3. `zone_id in self._zones_written_this_cycle`.
4. `preset_manager.borrow_live(zone_id) is not None` (gate e).
5. `arrester.has_active_ac_reset(zone_id)` (`hvac_override.py:2484`).
6. `P = zone.preset_mode`. Skip unless `P ∈ {home, sleep, away, vacation}`.
7. `(base_cool, base_heat) = get_seasonal_setpoints(P)`. Skip if None.
8. Compute the range:
   - `resolved = engine.resolve_range(base_heat, base_cool, engine.get_active_overrides(zone_id, P, house_state, True, overrides.get(zone_id, [])))`.
   - `desired = apply_setpoint_guards(base_heat, resolved.cool_high, freeze_active=self._freeze_active)`.
   - Only `cool_high` comes from overrides; the low side is always the configured heat.
9. Snapshot capture (§3.4): if no snapshot for (zone, P), capture and save it **first**.
10. Rate/latch check (§6.2), including per-(zone, preset, mode) `S10_PRESET_RANGE_MIN_SPACING_S` bound (REV 3.1 F4).
11. Write:
    - `result = await strategy_for(...).set_preset_range(hass, entity, P, *desired, gate=_s10_gate, zone_id, site="S10_preset_range", reason="preset_range_dpm" | "preset_range_baseline")`.
    - **No `suppress()` stamp.** DELETE `suppress(zone.climate_entity, kind="temp")` at `hvac.py:4114-4115`, `unsuppress` at `:4150-4151`, AND exception-path `unsuppress` at `:4168` (REV 3.1 F6).
12. Update the record per §6.2.

**REV 3.1 F2 NOTE (defence in depth):** a zone that is both interrupt-latched and on a named preset is not reachable — `latch_level_check()` runs at `hvac.py:2226` before this pass and level-discharges on any readable named-non-manual state (`hvac_override.py:1308-1318`). If future refactoring produces that shape, add a skip using `OverrideArrester.interrupt_latched(entity_id)` — grep first, do not invent a coordinator predicate. Sole current reader: `hvac_predict.py:1281-1291`.

### 3.3 `CarrierStrategy.set_preset_range` (brand rules)

*Ecobee's `set_preset_range` shape, store-first semantics and CPR-OFF restore are specified in `PLANNING_hvac_w1c_p2_ecobee.md` §4.9; CPR consumes it via the ANY-reason APPLIED/SKIPPED/DEFERRED/FAILED rule in REV 5 F1.*

**P1. Both feeds name `preset`.** `obs.preset_mode == preset and obs.hold_activity == preset`; else `DEFERRED("activity_not_confirmed")`. Reasoning as REV 3 (edited profile equals `P` regardless; the check exists to avoid writing into an unstable hold state during the 5-min post-write guard).

**P2.** `hvac_mode == "heat_cool"`, else `DEFERRED("not_heat_cool")`.

**P3.** Round to whole °F.

**P4. HA-view comparison.** `|obs.low − low| ≤ 0.5 and |obs.high − high| ≤ 0.5` → `SKIPPED_ALREADY_CORRECT("ha_view_matches")`. HA copy, not cloud truth (5-min post-write guard hides reverts). Retry interval (§6.1) guarantees ≥ 1 full read between a write and its retry.

**P5. Funnel call** `emit_set_activity_setpoint(..., service_domain="ha_carrier", service_name="set_activity_setpoint", blocking=True)` (REV 3.1 F3: service literals passed as kwargs by the strategy). No `await` between `observe` and the wire call.

**P6. After-call check.** Re-observe once, synchronously. If `preset_mode != preset` or `hold_activity` changed → `APPLIED` with `flag="possible_wrong_profile"`; log one `s10_possible_wrong_profile` row.

`GenericStrategy.set_preset_range` returns `FAILED("preset_range_unsupported")` and makes zero calls. S10 logs once per entity.

**Why the low side is the configured heat value:** on heat_cool `target_temp_low` IS the heat setpoint; OverrideEngine's `cool_low` has no physical meaning. So written low = baseline editor's "Heat Low"; winter-away 73 °F defect gone.

### 3.4 Restore Carrier originals when the feature is turned off

**Snapshot capture: when.**
- Apply pass step 9: first time S10 is about to write (zone, P) and no snapshot exists.
- Only after P1 and P2 hold, and only if the HA view differs from `desired`.
- Snapshot is `(round(obs.low), round(obs.high))` + `captured_iso`.
- **[REV 3.1 F7] Guard-masked match caveat.** If the HA view matches because of a guard-masked optimistic copy (C16/C21), no snapshot is taken and no S10 write occurs. Harmless: nothing edited, cloud IS the pre-URA original. Next 130-min full read either confirms or reveals a divergence (then step 9 captures).

**Snapshot capture: order.**
- Record snapshot → `await self.async_save_zone_state()` → write.
- Save raises → skip the write (`DEFERRED("snapshot_not_saved")`).
- No URA edit can exist without a persisted original.

**Snapshot capture: never overwritten.** Cleared only by a confirmed restore.

**Independent record.** HA view can be stale up to one full-read interval; D0 fixture item 1 + operator's app notes are the independent record for L8.

**Persistence.** Side-key `__s10_preset_ranges.snapshots[zone_id][preset]` in `_build_zone_state_snapshot` (§6.3). Rehydrated at boot. Verify no key collision with `__interrupt_latch` / `__immune_holds` / `__tao_state`.

**Restore on OFF [REV 3.1 F1].**
- Runs on every tick while `self._guest_mode_actuation_enabled is False` (**not** while `None`).
- Same skip matrix (step 0.5 + 1-6), same strategy method, same funnel; `desired = snapshot`, `site="S10_preset_range_restore"`, `reason="restore_carrier_original"`.
- Restores only the preset the zone is currently on. Lazy; home/sleep/away visited daily; vacation may wait.
- Pending restores shown on the sensor (D6); NM on OFF lists them.

**Restore confirmation.** Post-write HA-view check at next attempt (≥ `S10_PRESET_RANGE_MIN_INTERVAL_S`). Match → snapshot deleted, `s10_original_restored` row. Differs → retry/latch (§6.2); latch → NM `s10_restore_not_taking`.

**A preset URA never edited has no snapshot and is never touched.**

**Re-enable while restores are pending.** Snapshots stay; records cleared (§3.5); no re-capture.

**Zone deleted from URA** (`hvac.py:4044` store rewrite). Snapshot entries dropped; one `s10_original_dropped_zone_removed` ledger row.

### 3.5 Switch paths [REV 3.1 F1 + REV 3.2 R2]

One coordinator method `set_custom_ranges_enabled(value: bool, *, source: str)` is called by **FIVE** paths:
- `source="user"` (turn_on/turn_off, value actually changes) → clear every S10 **record** (value, writes, failures, latch) and save. **Snapshots kept.** User toggle is the latch discharge.
- `source="restore"` (RestoreEntity paths) → set the flag only. Records not cleared (M3 restart-storm protection).
- `source="no_last_state_default"` (D8 default OFF on fresh install or lost RestoreEntity) → set flag to False. If any snapshot exists, emit ONE info NM `s10_restart_default_off_restore_pending`. One `s10_default_off_after_restart` ledger row. Guard against re-emit by "snapshot count > 0 AND no prior row in 24 h".
- **`source="unresolved_backstop"` [REV 3.2 R2]** — fired by an `async_call_later(S10_SWITCH_RESOLUTION_TIMEOUT_S, ...)` scheduled at coordinator boot; callback checks `_guest_mode_actuation_enabled is None` and resolves to False. Emits one info NM `s10_switch_unresolved_backstop` (title *"Custom Preset Ranges switch did not resolve"*, message *"URA is treating it as off after {N} minutes. If you had it on, re-enable it now."*). The `async_call_later` is cancelled if the flag resolves earlier by any other source.
- **`async_turn_off`** no longer clears `_last_emitted_range` (the map is retired by D3c per F5/R1).
- On a user OFF: one info NM `Custom Preset Ranges is off. Putting back the original ranges on {n} presets as each zone next uses them.`

**All FIVE sources set `_guest_mode_actuation_enabled` from `None` to a resolved value. Nothing else does.**

### 3.6 What S10 no longer does
- No longer composes house-state preset onto a zone (row-1 owns retreat).
- No longer writes raw setpoints; no longer creates `manual`; no longer writes every tick.
- No longer writes `_last_emitted_range` (map retired D3c) and no longer stamps suppress (all three sites `:4114`, `:4150`, `:4168`).
- Does nothing while `_guest_mode_actuation_enabled is None`.
- Does nothing while the climate entity is `unavailable`/`unknown`.

---

## 4. D0 — measure before build (first deliverable; gates the build)

Probe: `scripts/probes/hvac_preset_profile_probe.py` (read-only via `ssh ha`).

1. **Current Bryant profile per (zone, preset)** — last 7 days, `preset_mode == hold_activity == P` in `heat_cool`, ≥ 125 min after any URA/human write.
2. **The fixture** — zone × preset: Bryant vs URA desired, summer + shoulder. Differing cells = expected writes on enable. Committed acceptance fixture.
3. **S10 reach** — share of 5-min samples where both feeds agree on a named preset. Flag any zone < 50 %.
4. **Restore-writers disposition** — episodes since v5.103.18 where an established-empty zone sat on a comfort preset > 15 min. Expected ≈ 0. **[REV 3.1 F5]** Corroboration only; the card is closed on the by-construction proof (§9). Item 4 > 0 → investigate as separate finding, NOT block CPR.
5. **Controlled live test of `set_activity_setpoint` (HIGH-1). BUILD GATE.** Target zone_3. Step A: `set_activity_setpoint` with high + 1. Observe at +0/1/2/5/10 min and after next full read. Operator app screenshot at +2 min + full read. URA side: no `override_detected`, no S1 `preset_change`, no NM. Step B: revert. PASS = neither feed reads `manual`; app shows named preset with new range after full read. FAIL = any manual reading / cloud revert / app showing Manual → no build.

**D0 gates.** Item 5 FAIL → stop; matched cells → tell operator; > 4 °F from Bryant → operator review.

### 4.1 D0 results

**Item 5 PASSED zone_3 2026-09-28 08:26 CDT.** Items 1-3 to be filled before build dispatch. Item 4 corroboration only (REV 3.1 F5).

---

## 5. Deliverables

### D1 — `emit_set_activity_setpoint` funnel (`hvac_setpoint.py`) [REV 3.1 F3]

- Signature: `emit_set_activity_setpoint(hass, entity_id, *, service_domain: str, service_name: str, target_temp_low, target_temp_high, freeze_active, blocking, gate, site, zone_id, reason) -> bool`.
- Steps: gate check; `apply_setpoint_guards`; synchronous snapshot; `await hass.services.async_call(service_domain, service_name, {...}, blocking=blocking)`.
- Exactly one `climate_write` row (`verb=service_name`) per attempted call, on success and raise paths.
- No brand logic. Strings `"ha_carrier"` + `"set_activity_setpoint"` DO NOT appear in this file.

**Acceptance**
- `test_emit_set_activity_setpoint_one_row_per_call`
- `test_emit_set_activity_setpoint_raise_one_row`
- `test_emit_set_activity_setpoint_gate_defers_no_call`
- `test_emit_set_activity_setpoint_freeze_floor`
- `test_emit_set_activity_setpoint_uses_caller_supplied_domain` (REV 3.1 F3)
- **Lint:** extended `test_hvac_climate_write_funnel_completeness.py` forbids `hass.services.async_call("ha_carrier", ...)` outside `hvac_strategy.py` AND literal `"ha_carrier"` in `hvac_setpoint.py`. **REV 3.2:** the lint MUST accept a non-literal domain (Name-typed AST node). Add `test_lint_accepts_variable_service_domain` — fake caller with `service_domain=some_var` passes the lint.
- **Live:** S10 rows appear as `climate_write` with `verb=set_activity_setpoint`.

### D2 — `set_preset_range` strategy method (`hvac_strategy.py`)

Per §3.3 (P1-P6). REV 3.1 F3: SOLE site of `"ha_carrier"` + `"set_activity_setpoint"`. Generic returns FAILED unsupported.

**Acceptance:** as REV 3 (8 tests: both-feeds, manual-defers, heat_cool-only, rounds-and-skips, applies-diff, flags-possible-wrong-profile, generic-unsupported, no-await-between-observe-and-wire).

### D3 — S10 apply pass (`hvac.py`) + `borrow_live` (`hvac_preset.py`)

- Implement §3.2 (tri-state entry per REV 3.1 F1 + REV 3.2 R4 ordering; unavailable skip step 0.5).
- DELETE `hvac.py:3985-4067` (D9 block), `:4055-4056` (`_dpm_composed_away_zones`), `:4074` (cool-7), `:4096-4111` (F2 bypass), `:4114-4115` (`suppress`), `:4150-4151` (`unsuppress`), **`:4168` (exception-path `unsuppress`, REV 3.1 F6)**, `:4153` (throttle-map write).
- Pull gate (e) out into `borrow_live`. `manual_guard_verdict` byte-identical.

**Acceptance** (folds `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` + `HVAC-S10-DPM-VS-S1-1`)
- **Verify (no fight):** DPM cool_high 75 vs Bryant 76 on home/home → one S10 call, next tick zero S1 writes and S10 SKIPPED.
- **Verify (no storm):** established-empty away zone, 12 ticks → zero S10 calls.
- **Verify (skip matrix, 10 cases [REV 3.1 F2: was 11, drop latch]):** egress / **unavailable** / a-b / same-tick / borrow / `_nudge_in_flight` / `_compromise_timers` / AC reset / manual / wake → zero calls each.
- **Verify (low side):** winter away 80/65 → write 65/80.
- **Verify:** zone's own preset edited, never the house-state preset.
- **Verify (M4):** S10 edit replayed as state_changed → no `override_detected`, no comfort grant, no `_suppressed_until`.
- **Verify [REV 3]:** S10 edit does NOT append to Batch B's URA-last-4 `set_temperature` RAM record; a later human-typed setpoint on the same entity's manual profile IS detected.
- **Verify [REV 3.1 F1]:** flag `None` for cycles 1..3 → zero wire calls; cycle 4 resolves → normal.
- **Tests:**
  - `test_s10_edits_profile_not_hold_no_s1_reclaim`
  - `test_s10_empty_zone_no_storm_12_ticks`
  - `test_s10_skip_matrix` (parametrised, 10 cases)
  - `test_s10_defers_when_climate_unreadable`
  - `test_s10_no_write_before_switch_resolved` (F1)
  - `test_s10_no_restore_before_switch_resolved` (F1)
  - `test_s10_reload_race_no_restore_when_actually_on` (F1)
  - `test_s10_default_off_no_last_state_emits_one_nm` (F1)
  - **`test_s10_backstop_resolves_false_after_timeout` (R2)**
  - `test_s10_low_side_uses_configured_heat_winter_away`
  - `test_s10_acts_on_zone_preset_not_house_state`
  - `test_s10_dpm_sleep_override_applies_only_in_sleep`
  - `test_s10_edit_books_no_override_detected`
  - `test_s10_edit_not_recorded_in_within_manual_detector`
  - `test_borrow_live_extraction_verdict_identical`
- **Retired/rewritten tests:** D9 tests in `test_zzz_hvac_conditioning_demand.py`; S10 transient-hold tests in `test_hvac_live_room_hold_wire_in.py`; S10 expectations in `test_freeze_floor.py`, `test_arrester_comfort_delay.py`, `test_v471_fixup_d2_d3_d4.py`, `test_hvac_w1a_site_migration.py`, `test_v478_egress_window.py`. **REV 3.2 R1: the 11 files listed for `_last_emitted_range` retirement are handled in D3c.**

### D3b — Restore originals (`hvac.py`, `switch.py`)

Implements §3.4 and §3.5 (with REV 3.2 R2 backstop + R4 reader audit).

**Acceptance** (as REV 3.1, plus R2 test integration):
- Capture: first write to (z, home) saves values BEFORE the wire call; later DPM change does not overwrite; matching HA view takes no snapshot; failed save blocks the write.
- Restore: user OFF with a home snapshot on zone-on-home → one call `site=S10_preset_range_restore`; next attempt ≥ interval with matching view → snapshot deleted + `s10_original_restored` row; away zone with only home snapshot → no call until home.
- Never-edited: preset without a snapshot gets zero calls.
- Restart: on → snapshots kept, no re-capture; off + snapshots → restore continues after resolution; latched → stays latched.
- **[NEW]** Rehydrate coexists with `__interrupt_latch` / `__immune_holds` / `__tao_state` — no side-key collision.
- **[NEW REV 3.1 F1]** No-last-state boot + snapshots → one info NM.
- **[NEW REV 3.2 R2]** Switch entity never added → backstop fires after `S10_SWITCH_RESOLUTION_TIMEOUT_S`; restore pass begins next tick.
- Toggle: user OFF→ON clears records, keeps snapshots; RestoreEntity path clears nothing.
- Restore latch: view never matches → exactly LIMIT restore calls, then NM `s10_restore_not_taking`.
- **Tests:** as REV 3.1, plus `test_s10_backstop_cancelled_when_switch_resolves_earlier` (R2 cancellation).

### D3c — Retire `_last_emitted_range` map [REV 3.1 F5 + REV 3.2 R1]

**DELETE ALL of:**
1. `hvac.py:667` — map init.
2. `hvac_predict.py:932-948` — S11 preference read.
3. `hvac_predict.py:1003` — additional map read.
4. `hvac_predict.py:1153-1154` — **S11 write (R1)**.
5. `hvac_predict.py:974` — **`update_throttle` kwarg definition (R1)**.
6. `hvac_predict.py:482, :1260` — **both call-site arguments passing `update_throttle=...` (R1)**.
7. `hvac_predict.py:1900-1903` — S13 write.
8. `switch.py:2061-2062` — switch-OFF clear.
9. Stale comments at `hvac_predict.py:933-941, :995-1000`.

**S11 behaviour change (R1 safety note):** S11's map value matters only on the HUMAN_MANUAL branch (raw `emit_set_temperature(base_low, base_high)`). Before: that branch could write the map's pair (S13's pre-heat pre-borrow snapshot or an older pair, possibly days old). After: writes `_resolve_baseline_range`'s fallback (`hvac_predict.py:951-968`) — the configured `(heat, cool)` of the house-state target preset. Well-defined, never stale, low side fixed since v5.103.22. The specific pre-heat-sourced-values case: S11 used to accidentally write the person's pre-heat token's values; it now writes URA's baseline (arguably more correct — those values belonged to the pre-heat token, not the banking one). **Safe.**

**Test files touching `_last_emitted_range` (11 — REV 3.2 R1 list, each rewritten or retired):**
- `test_arrester_comfort_delay.py`
- `test_freeze_floor.py`
- `test_hc_precool_oc_observability.py`
- `test_hvac_excursion_banking_migration.py`
- `test_hvac_excursion_preheat_migration.py`
- `test_hvac_live_room_hold_wire_in.py`
- `test_hvac_w1b_returns_and_strategy.py`
- `test_hvac_w1w2_finish_part_b.py`
- `test_v471_fixup_d2_d3_d4.py`
- `test_v5_7_1_energy_precool.py`
- `test_zzz_hvac_conditioning_demand.py`

Each file's map-related assertions rewrite to post-retirement behaviour (S11 writes preset-resolved values; S13 does not touch a map) OR the test retires if the map WAS the subject.

**Acceptance [REV 3.2 R3 — grep is build-time lint, pytest is behavioural]:**
- **Build-time lint (not pytest):** `grep -rn '_last_emitted_range' custom_components/universal_room_automation/` returns empty. Wire into the pre-deploy zero-bugs gate script.
- **Pytest — behavioural:**
  - `test_s11_baseline_uses_preset_resolved_after_map_retirement` — drives `_release_banked_zones` HUMAN_MANUAL branch; asserts emitted values equal `_resolve_baseline_range(house_state)` output.
  - **`test_s11_write_reflects_baseline_not_map_pair` [R3 replacement]** — construct scenario where pre-retirement S13 would have written stale (X, Y) into the map; run S13 return then S11 release on HUMAN_MANUAL; assert S11 emits resolved-baseline pair, NOT (X, Y).
  - `test_s13_return_writes_no_setpoints_after_map_retirement` — S13 return path calls no `set_temperature`; only presets-only return runs.

### D4 — Rate bound, latch, persistence (`hvac.py`, `hvac_const.py`)

Per §6. Adds `S10_PRESET_RANGE_MIN_SPACING_S = 600` (F4). **[REV 3.2 R2]** Adds `S10_SWITCH_RESOLUTION_TIMEOUT_S = 300` (5 min, rung 1).

**Acceptance**
- Retry interval: device never takes value → exactly 3 calls per (zone, preset, value), ≥ 130 min apart, then latch with NM `s10_preset_range_not_sticking`.
- Failures: service raises every call → exactly 3 attempts, then latch with NM `s10_preset_range_call_failed`. Failures counted separately.
- Value-change resets record but keeps `last_attempt_iso`; new value writes only if `now − last_attempt ≥ S10_PRESET_RANGE_MIN_SPACING_S`, else DEFERRED (`per_key_min_spacing`).
- **[REV 3.2 R5]** DPM dwell 0, hysteresis 0, cool_high flaps 75↔76 every tick for 30 min → **≤ 4 wire calls** total (calls allowed at t=0, 10, 20, 30 min). Include A→B→A case.
- User toggle discharges latch. Restart does not.
- Write-ahead save happens before each call.
- **Tests:**
  - `test_s10_retry_interval_130min`
  - `test_s10_latch_without_call_at_limit`
  - `test_s10_failed_counted_separately_own_nm`
  - `test_s10_value_change_resets_record_but_respects_spacing`
  - **`test_s10_dwell_zero_flap_bounded_by_spacing` (R5: assert ≤ 4)**
  - `test_s10_restart_storm_no_refire` (8 restarts → ≤ 3 calls total)
  - `test_s10_write_ahead_save`

### D5 — User-facing text (label style guide)

Unchanged from REV 3.1 (all NM strings + baseline editor + DPM master + switch docstring + `s10_restart_default_off_restore_pending`). **Adds one row [REV 3.2 R2]:**

| Surface | Key | Text |
|---|---|---|
| NM (info, backstop timeout) | `s10_switch_unresolved_backstop` | Title `Custom Preset Ranges switch did not resolve`; message `URA is treating it as off after {N} minutes. If you had it on, re-enable it now.` |

**Acceptance:** as REV 3 + `test_label_no_jargon_s10_strings` includes the new NM.

### D6 — Diagnostics (`sensor.py` `HVACActivePresetOverridesSensor`)

New attributes:
- `preset_range_by_zone`
- `originals_pending_restore`

Docstring line on `resolved_ranges` (engine's opinion; written low is configured heat).

**Acceptance:** `test_active_preset_overrides_sensor_exposes_s10_record_and_originals`; live within 2 ticks.

### D7 — Docs in the same commit

- State-of-play (bump snapshot; §1, §3.2, §3.3, §4.1, §4.2, §5, §9.7 closed, §11 row 5 SHIPPED).
- `THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` §3 (adopted; close open item 6).
- README `README_v5.103.x.md` with Validated table.

### D8 — Switch default OFF (LOW-6; REV 3.1 F1 + REV 3.2 R4 wording)

**Wording (final, REV 3.2 R4):** *"init `_guest_mode_actuation_enabled = None` at `hvac.py:664`; every reader (`hvac.py:3923`, `hvac.py:3940`, `sensor.py:10199`, `sensor.py:10231`, and the switch `is_on` reader) renders `None` explicitly as unknown/pending, never as True. The five switch source paths (§3.5, including the R2 backstop) resolve `None` to a Bool."*

Specific reader edits:
- `hvac.py:3923` — the `is None` return in §3.2 must precede this line.
- `hvac.py:3940` (`master_enabled = self._guest_mode_actuation_enabled`) — unreachable while `None`; add `assert self._guest_mode_actuation_enabled is not None` for reviewer clarity.
- `sensor.py:10199` — render `None` as `STATE_UNKNOWN`, never `True`.
- `sensor.py:10231` — same rule.
- Switch `is_on` (grep `getattr(coordinator, "_guest_mode_actuation_enabled", True)`) — render `None` as `is_on = None` (HA switch pending state), not `True`.

**Tests:**
- `test_custom_preset_ranges_default_is_none_until_resolved` (F1)
- `test_custom_preset_ranges_no_last_state_resolves_off_and_nm` (F1)
- **`test_sensor_renders_none_as_unknown_not_true` (R4)**
- **`test_switch_is_on_renders_none_as_none` (R4)**

---

## 6. Numbers, rate model, persistence

### 6.1 Constants (knob ladder)

| Name | Value | Rung | Why |
|---|---|---|---|
| `S10_PRESET_RANGE_MIN_INTERVAL_S` | 7800 (130 min) | 1 | Carrier cloud call-rate bound; ≥ `FULL_RECONCILE_INTERVAL_MINUTES` (120) + guard (5) + slack (5). |
| `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` | 3 | 1 | Same. Covers lost write + transient error. Also FAILED limit. |
| `S10_PRESET_RANGE_MIN_SPACING_S` | 600 (10 min) | 1 (F4) | Carrier cloud call-rate bound across value changes for same (zone, preset, mode). Bounds DPM-flap adversary to ≤ 6 writes/h/(zone, preset). |
| **`S10_SWITCH_RESOLUTION_TIMEOUT_S`** | **300 (5 min)** | **1 (R2)** | **Boot-lifecycle invariant: still-`None` flag resolves to False after this window. Change requires review.** |

Switch 01 is the kill switch.

### 6.2 Rate and latch model (M2 + F4)

Record keyed by `(zone_id, preset, mode)`, mode ∈ {apply, restore}:

```
{value:[lo,hi], writes:int, failures:int, latched:bool, latch_reason:str|None, last_attempt_iso:str|None}
```

- **Value differs [F4]** → reset value/writes/failures, keep `last_attempt_iso`. New value writes immediately only if `now − last_attempt ≥ S10_PRESET_RANGE_MIN_SPACING_S`; else DEFERRED (`per_key_min_spacing`), no wire call.
- `latched` → no call.
- Retry of same value → allowed only if `now − last_attempt ≥ S10_PRESET_RANGE_MIN_INTERVAL_S`.
- Due retry with `writes == LIMIT` and HA view still differs → `latched = True`, `latch_reason = "not_sticking"`, one NM, no call.
- Otherwise write ahead: increment attempt, set `last_attempt_iso`, `await` save, call:
  - APPLIED → `writes += 1`.
  - FAILED → `failures += 1`. If `failures == LIMIT`, latch `call_failed`, own NM.
  - DEFERRED → roll back attempt stamp, do not save.
- `SKIPPED_ALREADY_CORRECT` → no call, counters NOT reset (guard-masked match cannot re-arm endless loop). In restore mode with `last_attempt ≥ MIN_INTERVAL` → confirms restore.
- Discharge: value change (subject to F4 spacing); user toggle. **Not** on restart.

### 6.3 Persistence (M3)

`_build_zone_state_snapshot` (`hvac.py:2329`) gains:

```
"__s10_preset_ranges": {
  "snapshots": {zone_id: {preset: {"low": float, "high": float, "captured_iso": str}}},
  "records":   {zone_id: {"<preset>|<mode>": {record fields above}}}
}
```

Rehydrated in `_rehydrate_s10_state(stored)` next to `_rehydrate_arrester_state` (`hvac.py:1981`). Wall-clock ISO timestamps. Coexists with `__interrupt_latch` / `__immune_holds` / `__tao_state`.

Saves: snapshot save before first edit awaited; each attempt saved before call (write-ahead); confirmations/latches scheduled. Zone-delete rewrite (`hvac.py:4044-4081`) prunes.

**Budget:**

| Scenario | Old S10 | New S10 |
|---|---|---|
| Steady state | ~48 calls/h per empty zone | **0** |
| Enable | storm | ≤ D0 differing cells (≤ 4/zone), each as its preset is visited |
| DPM change (any dwell) [F4] | raw write + reclaim | ≤ 1 call per 10 min per (zone, preset) — ≤ 6/h/(zone, preset) |
| Season boundary | — | ≤ 4/zone |
| Device refuses | unbounded | ≤ 3 per (zone, preset, value, mode) across restarts, then latch |
| Turn off | — | ≤ snapshots × 3 |
| Thermostat unavailable | pointless + latch churn | **0** (one INFO/ledger per outage episode) |
| Switch unresolved / boot race [F1] | wrong restore on reload | **0** (tri-state blocks both passes) |
| **Switch never resolves [R2]** | **restores never run** | **backstop resolves False at `S10_SWITCH_RESOLUTION_TIMEOUT_S`; restore pass begins** |

---

## 7. Invariants and live validation

### 7.1 Invariants

> **INV-S10.** With switch 01 resolved to ON (`_guest_mode_actuation_enabled is True`), every S10 wire call is `ha_carrier.set_activity_setpoint`, only while `preset_mode == hold_activity == P ∈ {home, sleep, away, vacation}` in heat_cool, never for a zone with live borrow, person-protected hold, arrester comfort window, AC reset, egress pause, same-tick S1 write, or unavailable/unknown climate entity. Never changes hold state; never creates `manual`; S1 never reclaims because of S10. **[F1]** No S10 wire call while `_guest_mode_actuation_enabled is None`.

> **INV-RATE.** For any (zone, preset, mode, value), wire calls summed across any restarts ≤ `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` successful + ≤ `S10_PRESET_RANGE_UNCONFIRMED_LIMIT` failed. Same value: ≥ `S10_PRESET_RANGE_MIN_INTERVAL_S` apart. Same (zone, preset, mode) regardless of value: ≥ `S10_PRESET_RANGE_MIN_SPACING_S` apart. Re-opens: value change (subject to spacing) or user toggle.

> **INV-RESTORE [F1 clarified].** For every (zone, preset) URA has edited, a persisted original exists from before the first edit until a confirmed restore. Restore writes occur ONLY while `_guest_mode_actuation_enabled is False` (resolved); NEVER while `is None` or `is True`. **[R2]** A still-`None` flag resolves to False by the backstop within `S10_SWITCH_RESOLUTION_TIMEOUT_S` of coordinator boot, so INV-RESTORE never silently stalls on a never-added switch.

**Falsifier queries** (one-shot, `ura_activity_log`):
- Q1: S10 rows with `verb != 'set_activity_setpoint'` → 0.
- Q2: S10 rows with `values_before.preset_mode != values_before.hold_activity` or with `manual` → 0.
- Q3: `preset_change` rows with `manual_class='zero_delta_ura'` on a zone within 15 min after an S10 row, no other URA write between → 0.
- Q4: count per (zone, site, `values_after`) → ≤ 3 (≤ 6 counting failures).
- Q5: `override_detected` within 2 min after an S10 row on the same zone, no preset transition → 0.
- Q6: `s10_possible_wrong_profile` → 0 expected; any row investigated.
- **Q7 [F8]:** S10 rows whose `values_before.state ∈ HVAC_CLIMATE_UNREADABLE_STATES` → 0. Equivalent: no S10 row inside a `climate_write_held_unreadable` episode for the same entity.
- **Q9 [F1]:** S10 restore rows < 60 s after a URA boot AND before the switch's `s10_default_off_after_restart` or user-driven state row → 0.
- **Q10 [F4]:** pairs of S10 wire calls (both sites) for same (zone, preset, mode) with `Δts < 600 s` → 0.
- **Q11 [R2]:** S10 row with ts > `S10_SWITCH_RESOLUTION_TIMEOUT_S + HVAC_DECISION_TICK` after boot AND no switch-resolution ledger row precedes it → 0.

### 7.2 The enable step (operator)

Prerequisites: D0 item 5 PASS (done zone_3 2026-09-28), deploy, HACS install, restart, fixture review; note app's current preset ranges.
1. Turn ON `switch.ura_hvac_coordinator_guest_mode_actuation`. Run L1-L6, L8.
2. Turn ON `switch.ura_energy_coordinator_dynamic_preset_overrides`. Run L7. Optional: open options → HVAC → Dynamic Preset and save.
3. Restore drill (L9), operator's choice.

### 7.3 Live checks

| # | Check | Oracle | PASS if |
|---|---|---|---|
| L1 | Rows only for differing cells | `climate_write site=S10_preset_range` | rows = differing fixture cells |
| L2 | Zone stays named | `preset_mode` + `hold_activity` 10 min after each row | unchanged, never `manual` |
| L3 | **Thermostat holds the range** | **Operator Bryant app** after next full read (≥ 125 min) | app matches `values_after` |
| L4 | No fight | Q3 | 0 |
| L5 | No storm, no false override | Q1, Q4, Q5 | 0 / ≤ 3 / 0 |
| L6 | Borrows unaffected | next soft nudge returns to named preset with custom range | as stated |
| L7 | Weather reaches profile | bucket/range sensors + S10 row `reason=preset_range_dpm` | as stated |
| L8 | Originals captured correctly | sensor `originals_pending_restore` vs D0 fixture + app notes | equal per cell |
| L9 | Restore works | after OFF: `S10_preset_range_restore` rows as each preset visited; app shows originals | as stated |
| L10 | Unavailable skip | outage episode: `climate_write_held_unreadable` rows exist, **zero** `S10_preset_range` | Q7 |
| L12 [F1] | Switch-resolution race | first 60 s post-restart: zero restore rows before switch-state row | Q9 |
| L13 [F4] | Per-key spacing | pairs of S10 rows same (zone, preset, site) with Δts < 600 s | Q10 = 0 |
| **L14 [R2]** | **Backstop timeout** | **any restart where switch entity fails to add: `s10_switch_unresolved_backstop` NM fires within 5 min; restore pass begins next tick** | **Q11 = 0** |

Proven only in-suite: latch/NM, restart-storm bound, winter low side, restore latch, side-key non-collision, tri-state flag, per-key spacing, backstop timeout, S11-baseline-not-stale (R3).

---

## 8. Supersession

| Item | File:line | Bucket | Superseded by |
|---|---|---|---|
| D9 compose-away | `hvac.py:3985-4067` | DELETE | row-1 preset retreat + W1-B presets-only returns |
| F2 bypass | `hvac.py:4096-4111` | DELETE | rate model |
| S10 transient hold | inside `:3985-4067` | DELETE | — |
| `_dpm_composed_away_zones` | `hvac.py:4055-4056` | DELETE | — |
| `cool − 7` at S10 | `hvac.py:4074` | DELETE | configured heat |
| suppress/unsuppress at S10 (three sites) | `hvac.py:4114-4115`, `:4150-4151`, **`:4168`** | DELETE | arrester named-preset ignore (M4) |
| **`_last_emitted_range` map (init + ALL producers/consumers) [F5 + R1]** | `hvac.py:667`; `hvac_predict.py:482, :932-948, :974, :1003, :1153-1154, :1260, :1900-1903`; `switch.py:2061-2062` | **DELETE** | D3c (private channel holds stale values) |
| `hvac_predict` cool-7 fallback | `hvac_predict.py:~929` | **DONE** — shipped v5.103.22 | — |
| OverrideEngine `cool_low` | `preset_overrides.py:60` | KEEP + DOCUMENT | — |
| `hvac_excursion.py` `_auto_return` manual-skip | (unchanged) | **KEEP** (§10 C26) | — |

---

## 9. Card dispositions

- `HVAC-COMPOSE-AWAY-THROTTLE-STORM-BLOCKER-1` → **done on ship** by D3 DELETION. Evidence: `test_s10_empty_zone_no_storm_12_ticks`; live Q1/Q4/Q5 zero rows/h on empty zones.
- `HVAC-S10-DPM-VS-S1-1` → **done on ship** by §3.1 named-profile write. Evidence: `test_s10_edits_profile_not_hold_no_s1_reclaim`, `test_s10_edit_books_no_override_detected`; live Q2/Q3 zero rows.
- `HVAC-RESTORE-WRITERS-STRAND-EMPTY-NIGHT-ZONE-1` → **closed by construction (F5 + R1).** Strand mechanism: restore writers did not update `_last_emitted_range`, so D9's corrective re-emit was suppressed by S10's throttle at `hvac.py:4108`. `hvac.py` has exactly one reader (`:4108`) and one writer (`:4153`), both deleted by D3. D3c also retires the `hvac_predict.py` producers/consumers (R1), closing the residual stale-pair risk. Empty-zone retreat is then S1 row-1 alone; presets-only returns land on a preset S1 flips next tick. D0 item 4 is corroboration only. `FOLD_2026_09_17` (EC coast/shed offset path) stays open as separate concern.
- **New cards (minted or shipped):**
  - `HVAC-PRECOOL-RESTORE-HEAT-MINUS7-1` — SHIPPED v5.103.22, DONE.
  - `HVAC-DPM-OPTION-VS-SWITCH-SPLIT-1` — carded.
  - DPM range sensor display — folded into the first card.
  - `HVAC-WRITES-WHILE-THERMOSTAT-UNAVAILABLE-1` — SHIPPED Batch D v5.103.24 for B1/S1; CPR inherits via §3.2 step 0.5.

---

## 10. Test authority (builder + Reviewer C)

- **T1.** Every skip/precondition/counter branch mutation-anchored: neuter, named test fails, restore, `git status` clean. Bytecode off, `__pycache__` cleared.
- **T2.** Fight and restore tests drive `_apply_house_state_presets`.
- **T3.** Neuter P1 → both-feeds test fails.
- **T3b.** Neuter `hold_activity` half only → `test_carrier_set_preset_range_requires_both_feeds` still fails (status=home / hold=away case).
- **T4.** Neuter rounding → rounding test fails.
- **T5.** Insert `await asyncio.sleep(0)` between observe and wire → no-await test fails.
- **T6.** Re-add `suppress()` → `test_s10_edit_books_no_override_detected` fails.
- **T7.** Delete write-ahead save → `test_s10_restart_storm_no_refire` fails. Delete snapshot-before-write order → `test_s10_snapshot_saved_before_first_edit` fails.
- **T8.** Real `PresetManager`, real CM options shapes, real `Store` round-trip for the side-key. Mock service edits only status-named activity.
- **T9.** Neuter step 0.5 → `test_s10_defers_when_climate_unreadable` fails.
- **T11.** Route S10 through `emit_set_temperature` → `test_s10_edit_not_recorded_in_within_manual_detector` fails.
- **T12 [F1].** Change entry test from `if not enabled` to `if enabled is False` (letting `None` fall through) → `test_s10_no_write_before_switch_resolved` fails; `test_s10_reload_race_no_restore_when_actually_on` fails.
- **T13 [F3].** Remove funnel's `service_domain` kwarg and hard-code `"ha_carrier"` → lint fails AND `test_emit_set_activity_setpoint_uses_caller_supplied_domain` fails.
- **T14 [F4].** Delete the per-key spacing check → `test_s10_dwell_zero_flap_bounded_by_spacing` fails (asserting ≤ 4 per R5).
- **T15 [F5].** Restore the S11 map preference at `hvac_predict.py:932-948` → `test_s11_baseline_uses_preset_resolved_after_map_retirement` fails.
- **T16 [R1].** Restore the S11 map write at `hvac_predict.py:1153-1154` → `test_s11_write_reflects_baseline_not_map_pair` fails.
- **T17 [R2].** Delete the `async_call_later` backstop → `test_s10_backstop_resolves_false_after_timeout` fails.
- **T18 [R3 lint-of-lint].** Change the lint to reject a Name-typed domain → `test_lint_accepts_variable_service_domain` fails.
- **T19 [R4].** Render sensor `None` as `True` → `test_sensor_renders_none_as_unknown_not_true` fails.
- **Suite:** `PYTHONPATH=quality .venv-ha/bin/python -m pytest quality/tests/ -v`, serial. Compare test names against `pre-review` baseline.

---

## 11. Tier and review [REV 3.1: adds Reviewer D]

**Tier 2-DB + mandatory Reviewer D** (four framing-disjoint reviews + live validation + README write-back).

Elevated from Tier 2 under standing regression-prone policy: new writer verb; deleted corrector path; new persisted state (coexists with three W1-B/Batch B side-keys); adjacency to S1/nudge/arrester precedence.

**Not full Tier 3.** One emission site (two modes), one strategy method, one snapshot store; INV-RESTORE is single-surface. **But mandatory Reviewer D** because F1 (HIGH, now with R2 backstop) is exactly the class A/B/C converge on missing — a pre-existing boot-ordering path + a changed default + a new state-driven pass + the never-resolved corner (R2).

**REV 3 standing addition** (kept): orchestrator personally re-greps every wire-call site and every consumer of `__s10_preset_ranges` before deploy.

**Reviews (four parallel, framing-disjoint):**
- **Plan re-review:** none needed per re-check (R1-R5 applied as written; Reviewer D covers the lifecycle).
- **A — correctness + edge cases:** P1-P6, rounding, guards, low side, season/DPM gates, snapshot capture rules (incl. F7 guard-masked caveat), restore current-preset-only, unavailable skip.
- **B — cross-coordinator, lifecycle, no-flap:** S1 same-tick, borrow family, arrester (no stamp), ha_carrier guard vs 130-min retry, five switch source paths (incl. R2 backstop), restart/rehydrate, zone delete, `_last_emitted_range` retirement (D3c full set per R1), side-key coexistence, Batch B RAM record not polluted, Batch D unreadable-episode ledger not double-opened, F2 assertion (no reachable named-latched shape on develop @ build time).
- **C — test authority by real per-site mutation:** T1-T19, lint (incl. lint-of-lint).
- **D — adversarial completeness (MANDATORY):** state INV-RESTORE as falsifiable ("for every (zone, preset) URA has edited, a persisted original exists from before the first edit until a confirmed restore, and NO restore writes happen while switch 01 is `None` or `True`; the still-`None` corner resolves within `S10_SWITCH_RESOLUTION_TIMEOUT_S`"), then BREAK it. Re-enumerate the whole switch/boot/reload/restore lifecycle INCLUDING pre-existing code (`not_cold_boot` fast path, `SIGNAL_HVAC_COORDINATOR_READY`, RestoreEntity handlers, `set_custom_ranges_enabled` callers, the R2 `async_call_later` cancellation). Every leak ships with a concrete repro.
- **Pre-deploy:** `pre-review-v5.103.x` tag + zero-bugs gate + grep-lint for `_last_emitted_range`. Orchestrator re-greps every wire-call site and every consumer of `__s10_preset_ranges` on develop HEAD.
- **Post-deploy:** HACS check → enable step (§7.2) → L1-L10, L12, L13, **L14** → README Validated table + state-of-play in same commit. **DEPLOY HELD** until operator says so.

Any CRITICAL/HIGH from any block deploy; re-run D after fix-up.

---

## 12. Non-goals

- No new EXCURSION_KIND. No change to `hvac_excursion.py` (including `_auto_return` manual-skip, §10 C26).
- New funnel is W1-A-sanctioned; does not conflict with W1-B constraint. Existing funnels untouched.
- No change to S1's four gates or `should_change_preset`.
- Nudges stay on `set_temperature`.
- No heat-side weather adjustment. No guest-override producer. No entity_id rename.
- No non-Carrier support in THIS cycle (strategy hook exists §14; W1-C carries generic).
- No `wake` preset.
- No fix for zone_1's status/hold split (S10 defers; `HVAC-WRITE-CONFIRMATION-ORACLE-1`).
- No change to `hvac_predict` cool-7 fallback (SHIPPED v5.103.22).
- No Bryant schedule changes.
- No forcing a zone onto a preset to restore it (restores are lazy).
- No change to Batch B's within-manual RAM record, interrupt-latch primitive, pre-arrival lifecycle, arrival-reference resolver, Fan Mode, or arrester ↔ AC-reset separation. CPR consumes.

---

## 13. Open questions for the operator

Q1-Q3 answered (rulings below). Q4-Q5 answered 2026-09-27. Still open:
6. Willing to run L3 (physical Bryant-app check) once per zone × preset in the first 24 h post-enable? Recommend yes; then rely on falsifiers.

## Operator rulings 2026-09-27 (verbatim, pre-build)
- **Q1:** "Won't the app just reflect the new preset? Yes Ura wins."
- **Q2:** "If we turn of cpr, it should go back to the default ranges inset right?" + Restore Carrier originals.
- **Q3:** Separately — SHIPPED v5.103.22.

## Operator answers Q4-Q5 (2026-09-27 ~22:25, verbatim)
- **Q4:** "Default OFF (Recommended)".
- **Q5:** "Run it in zone 3. Btw don't deploy after building until I say so".

## D0 item 5 — live test log (zone_3)
- 22:33:0x CDT 2026-09-27: `ha_carrier.set_activity_setpoint` on `climate.back_hallway_zone_3` on named preset **away** (66/80): low 66, high 81.
- +0 (HA): preset_mode away, hold_activity away, hold_until None, 66/81.
- +1 min (operator app 22:34): Zone 3 "66 - 81 · Holding Away" — NOT manual.
- +31 min (22:37): unchanged, 66/81.
- **Bonus:** 23:04:50 URA switched away → sleep (70/77); 23:24:51 switched back sleep → away and zone came back at **66/81**. Neither switch produced `manual`.
- **RESULT (2026-09-28 08:26 CDT, ~10 h): PASS.** Zone 3 never read `manual` (0 rows). Every return to away showed 66/81. Gate MET.
- **Reverted 2026-09-28 08:3x CDT:** 66/80. Test closed.

## Cross-plan note (2026-09-28)
Fast-response review D-L4 found D9 compose-away does not consult `_pending_arm_hold_write`. This plan DELETES compose-away entirely.

---

## 14. Carrier-specific vs profile-agnostic scoping [REV 3, amended by REV 3.1 F3]

Feeds `HVAC-W1C-GENERIC-THERMOSTAT-1`. CPR is a **Carrier-profile capability**, not a hard-wired assumption.

**Above the strategy line (profile-agnostic):**
- S10 apply pass in `hvac.py` (§3.2): skip matrix, `borrow_live`, snapshot/restore state machine, latch/rate model, sensor exposure, switch entity, config-flow field, NM texts, `__s10_preset_ranges` side-key, `_climate_unreadable` skip, tri-state resolution (F1), backstop (R2). None read Carrier state.
- `emit_set_activity_setpoint` funnel (D1): verb-shaped, not brand-shaped. **REV 3.1 F3 (binding):** funnel takes `service_domain`/`service_name` from caller. Strategy supplies them. `hvac_strategy.py` SOLE site naming `"ha_carrier"` + `"set_activity_setpoint"`. Lint enforces (variable-domain permitted per R3 clarification).

**Below the strategy line (Carrier-specific — behind `CarrierStrategy.set_preset_range`):**
- Choice of service (`ha_carrier.set_activity_setpoint`) + schema.
- Two-feed P1 rule.
- 5-min post-write guard reasoning (P4).
- 130-min retry interval.
- "Edit status-named activity" semantics (P6).
- Preset name set `{home, sleep, away, vacation}`.

**Generic strategy:** `GenericStrategy.set_preset_range` returns `FAILED("preset_range_unsupported")`; zero calls. S10 logs once per entity; skips quietly. W1-C brands override with brand behaviour.

**W1-C hand-off checklist:**
1. Brand-scope `S10_PRESET_RANGE_MIN_INTERVAL_S` / `_MIN_SPACING_S` / `_SWITCH_RESOLUTION_TIMEOUT_S` if needed.
2. `borrow_live` / `manual_guard_verdict` / `_climate_unreadable` already brand-agnostic.
3. Templating NM text ("Bryant app") by brand.
4. `__s10_preset_ranges` side-key has no brand-specific keys.
5. `emit_set_activity_setpoint` service parameters come from strategy (F3).

No CPR piece hard-codes Carrier assumptions above the strategy line.

---

## Plan re-check (post W1-C P1) — 2026-10-03

**Reviewer:** ura-reviewer, one adversarial pass (Tier 2-DB plan). **Base:** `develop` @`8a4619b32`, which includes W1-C P1 / v5.103.36 `df03c904f`.

**Read first:**
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`, completely (592 lines). §10 C1–C29 are not re-asserted.
- `PLANNING_hvac_compose_away_throttle.md` REV 1.

**Method:** every anchor and site re-greped and read in source:
- `hvac.py` S10 method, end to end
- `hvac_strategy.py`, all of it
- `hvac_predict.py`: the `_resolve_baseline_range` callers
- `switch.py:2040-2125`, `sensor.py`
- the P1 golden harness and the contract / funnel lints

**Verdict: BUILD-READY (REV 3.3)** — the plan text is fixed in place by the REV 3.3 ERRATA at the top. Dispatch preconditions (operator/probe gates, not plan defects):
1. D0 items 1–3 run (probe not yet written; U9).
2. Operator confirms the U5 rollout constant (`S10_ROLLOUT_ZONE_IDS = {zone_3}`).
3. At deploy: U4 switch-OFF pre-step, then operator go; deploy remains HELD until the operator says so.

| # | Sev | Finding | Fixed in |
|---|---|---|---|
| U1 | HIGH | Plan wired S10 → `set_preset_range` with pre-P1 shapes. It lacked the `emit=` convention and quad-state `.status` branching (not `_w1c_applied`). Generic FAILED was conflated with the §6.2 wire-failure latch: a transient registry miss on a Carrier entity would latch + NM `call_failed`. The plan also ignored the existing `feature_available("cpr")` surface. Kwargs-completeness lint is blind to `emit=` delegation (pre-existing since P1) | U1 |
| U2 | HIGH | D3c deletion breaks ALL 168 P1 goldens (`_observe` reads the map, `test_hvac_w1c_p1_byte_identity.py:361-364`), not just S10. Four scenario seeds write the map. The `failed_raise` variant would not cover the new domain. The registry-miss suite must exclude A13_S10 by intent. Two converted tests drive A13_S10 | U2 (G1 key-drop / G2 scoped re-record procedure) |
| U3 | MED | `_resolve_baseline_range` has 5 consumers (orphan detect, banking discharge, S11, pre-arrival from_baseline, S12 token snapshot). R1 covered S11 only. With switch 01 live ON, the map currently feeds cool−7 lows to pre-arrival/S12 | U3 + 2 tests |
| U4 | HIGH (deploy) | Switch 01 is live ON (code default True; 10-02 re-create). CPR's RestoreEntity would run the apply pass on all zones at the first post-restart tick, before the operator's go | U4 mandatory pre-deploy OFF |
| U5 | MED | "Zone 3 first" had no mechanism; switch 01 is house-wide and the DPM opt-in does not gate the static half | U5 rung-1 rollout constant (restore ungated) |
| U6 | MED | Compose-away blocker additions not yet in this plan | U6 (INV-NO-STORM, alternation test, D-repros, C mutations, lint greps, live discriminator) |
| U7 | LOW | Zone-delete prune anchor `hvac.py:4044` was wrong (inside S10); in-memory prune unstated | U7 |
| U8 | LOW | Five side-keys exist, not three | U8 |
| U9 | LOW | Fast runs skip S10 (keep). F1 and F2 premises re-confirmed. NM templating ok. D0 1–3 unrun | U9 |
| — | LOW | Every REV 3.x line anchor drifted by +20 to +25 lines (hvac.py) / +15 to +21 lines (hvac_predict.py). `switch.py:2046-2047` was updated to `:2061-2062` in the REV 3.2 body (compose-away plan D2 ask) | anchor table |

**Cleared (holds because):**
- **D0-5 PASS still valid:** no ha_carrier change affects it.
- **F1 tri-state race is real:** the initial cycle at `hvac.py:1572` runs before READY at :1580.
- **F2 latch unreachability holds:** :2246 runs before :2278.
- **Strategy is still the sole `"ha_carrier"` naming site besides `hvac_const.py:1473`.** That constant is compatible with the F3 lint as scoped.
- **Arrester ignore branch still present:** `hvac_override.py:3652-3654`.
- **No §10 claim is re-asserted:** C25 (no reliance on the v3.8.0 guard), C26 (`_auto_return` skip kept), C20/C22/C23 (no `hold_activity` oracle), C15/C16/C21.

## Operator ruling 2026-10-03 — thin adapter (supersedes REV 3.3 U1's `feature_available("cpr")` skip)
The thermostat brand layer is a thin command adapter; HVAC features are never gated by brand (memory: thermostat-brand-layer-is-thin-command-adapter). Do NOT branch S10 on `feature_available("cpr")`. Instead S10 calls an adapter verb (e.g. `set_preset_range`) and the adapter decides how to carry it out per brand; a brand with no device presets returns SKIPPED (`no_device_presets`) and URA keeps the range itself. W1-C P2 REV 2 removes `feature_available`/`feature_unavailable_reason` from `hvac_strategy.py`; sequence CPR after P2 or implement the verb shape directly.
