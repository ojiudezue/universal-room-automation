# PLANNING — NM Cycle C: Per-Recipient Routing Matrix + Full Dry-Run UX + DND-Bypass + NM-1 Mute Shortcut

**Date opened:** 2026-07-20
**Author:** ura-planner
**Parent plan:** `docs/planning/PLANNING_nm_overhaul_2026_07.md` (Cycle C section, ~lines 235-273; revisions 3, 6, 7, 10)
**Base:** develop @ 74e396a8 (v5.26.0 = Cycle B safety rails LIVE; v5.25.0 = Cycle A-2 knob surface LIVE)
**Tier:** **Tier 3** (adopted in parent plan revision 10 — 4 framing-disjoint reviews + adversarial completeness pass + mandatory operator checkpoint before deploy)
**Live-exercise posture:** per-person channel targets (`CONF_NM_PERSON_PUSHOVER_KEY`, `CONF_NM_PERSON_IMESSAGE_HANDLE`, `CONF_NM_PERSON_WHATSAPP_PHONE`) REMAIN BLANK during C build + review + initial live validation — pipeline precondition #1 (parent plan header) is only released *after* Cycle C validates. C's own live validation runs with `CONF_NM_DRY_RUN=true` + blank targets: two independent safety layers.

---

## 1. Falsifiable invariant (Review D's job to break)

Cycle C ships iff **all three** of the following hold under any legal operator configuration and any reachable NM code path (including code paths not modified by this cycle):

> **C-INV-1 (Backward-compat routing).** With no per-recipient matrix configured (legacy `CONF_NM_*_ENABLED` / `CONF_NM_*_SEVERITY` values present, `CONF_NM_PERSONS[i]` matrix key absent or empty), every `(sender_coordinator, hazard_type, severity, recipient)` tuple routes to the IDENTICAL channel set it routed to on v5.26.0 for that tuple. Migration function `_migrate_legacy_severity_to_matrix()` produces the byte-identical channel set for the tuple space enumerated by the fixture in `quality/tests/test_nm_cycle_c_routing_backcompat.py`.
>
> **C-INV-2 (Dry-run zero-outbound, total).** With `CONF_NM_DRY_RUN=true`, **zero** `hass.services.async_call` invocations targeting a notification transport (`notify.*`, `pushover.*`, `tts.*`, `bluebubbles.*`, WhatsApp service domain, `light.turn_on` invoked from an alert-lights emit path) originate from ANY NM code path — including the matrix router, DND-bypass path, hazard-type override branch, NM-1 mute-shortcut confirmation, structured audit-log emit, safe-word ack path, repeat scheduler, boot-settle drain, quiet-hours bypass. The alert-lights *teardown* / `_restore_alert_lights` is exempted and must still run (Cycle B B0 ruling; state must remain honest).
>
> **C-INV-3 (DND-bypass determinism).** During quiet hours, an alert of severity S to recipient R fires iff `S in R.dnd_bypass_severities`; otherwise it does not fire (even if the routing matrix would otherwise permit it). No third condition. Default preserves v5.26.0 behavior: `dnd_bypass_severities = {CRITICAL}` for every migrated recipient.

Bug Class #53 (computed-but-not-consumed / one missed path) is the failure shape C-INV-2 exists to catch. Review D's mandate is to state C-INV-2 in falsifiable form and BREAK it via a concrete, legal-config reachable repro — including sites pre-existing this cycle (v5.5.3 D-HIGH-1 precedent).

---

## 2. Institutional context verified

### 2.1 Files read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` (v5.26.0 tip; emit path + repeat scheduler + webhook handlers + `_channel_qualifies` router)
- `custom_components/universal_room_automation/const.py` — `CONF_NM_*` block lines 1245-1367 (per-person keys, dry-run, buckets, safe-word already exist)
- `docs/planning/PLANNING_nm_overhaul_2026_07.md` — full plan; Cycle C section lines 235-273; deferred register lines 290-296; Numbers-Get-Knobs ladder lines 101-125
- `docs/Coordinator/NOTIFICATION_MANAGER.md` v1.0 (predates implementation — updated as C4 deliverable)

### 2.2 Grep survey for reuse — REUSED vs NEW

| Proposed Cycle C addition | Result | Evidence |
|---|---|---|
| Per-person container `CONF_NM_PERSONS` (list-of-dicts) | **REUSED** | `const.py:1265`; existing per-person keys at `const.py:1266-1275` (`CONF_NM_PERSON_ENTITY`, `_PUSHOVER_KEY`, `_PUSHOVER_DEVICE`, `_COMPANION_SERVICE`, `_WHATSAPP_PHONE`, `_IMESSAGE_HANDLE`, `_DELIVERY_PREF`, `_DIGEST_*`) — matrix + DND + mutes get added as new nested keys under this container |
| `CONF_TRACKED_PERSONS` (house-wide tracked persons) | **REUSED (source of person_id enumeration)** | `const.py:158`; recipient dropdowns in C1 options-flow populate from this list |
| Legacy severity gate `_channel_qualifies(channel, severity)` | **REUSED and REPLACED** | `notification_manager.py:2508`; call sites at 2380, 2413, 2482 — all migrate to `_route_for_recipient(recipient_id, hazard_type, severity)` |
| Dry-run gate `_dry_run_active` + `set_dry_run_active()` | **REUSED (extended)** | `notification_manager.py:279,294,342,344,620`; existing short-circuits at 1320, 1353, 1393, 1409, 1428, 1461, 2182, 2349 — C2 extends to matrix-router / audit-log paths and adds Review-C mutation coverage per NEW site |
| `CONF_NM_DRY_RUN` options key + Switch | **REUSED** | `const.py:1330`; Cycle B B0 shipped the minimal gate — C promotes it to first-class audit UX (no new key, new UI surface only) |
| `NM_LIFE_SAFETY_HAZARDS` frozenset | **REUSED** | `notification_manager.py:111` import; Cycle B B1 shipped it; C3 DND-bypass defaults reference it (life-safety hazards always bypass) |
| `_channel_ready(channel, severity, hazard_type)` runtime enable check | **REUSED** | `notification_manager.py:2358`; C1 keeps the outer `_channel_ready` (enable-flag + hazard-type) but the *routing decision* moves into `_route_for_recipient` — layering: enable → route → gate |
| `nm_cycle_a_knob(...)` options-lookup helper (A-2) | **REUSED** | Referenced in parent plan §2.2 as A-2 primitive; C1/C3 options reads route through the same helper for consistency (no cache — parent B-LOW-1 ruling) |
| `_is_quiet_hours()` + `_silence_until` | **REUSED** | `notification_manager.py:2281` and `279`; C3 wraps `_is_quiet_hours` with a per-recipient DND-bypass check; C4 shortcut adds per-`(person, channel)` silence dict alongside global `_silence_until` |
| `async_suppress_messaging` (global kill switch) | **REUSED** | `notification_manager.py:299`; unchanged — sits above the matrix |
| Persistence `get_persistence_state` / `restore_persistence_state` | **REUSED (extended)** | Cycle B B2 shipped ack-registry persistence; C4 mute-shortcut persists per-`(person, channel)` silence-until in the same shape (episode-boundary agnostic — expiries are absolute times) |
| `notification_log` DAO + additive-migration pattern | **REUSED** | B0 `ADD COLUMN dry_run` precedent (parent plan B0 line 198); C2 either extends via more nullable columns (`recipient_id`, `route_reason`, `dnd_bypass_applied`, `bucket_outcome`, `matrix_hit`) OR introduces `notification_audit_log` sibling table — decision item C-DEC-1 below |
| Repeat scheduler `_schedule_repeat` | **REUSED** | Cycle B B1 shipped per-subtype cadence; C router change flows through unchanged — repeats re-invoke `_route_for_recipient` per fire (C-INV-2 acceptance covers) |
| Per-person delivery preference `CONF_NM_PERSON_DELIVERY_PREF` | **REUSED (semantics preserved)** | `const.py:1272`; if set, becomes a legacy override the matrix migration honors; documented in NOTIFICATION_MANAGER.md v1.1 |

### 2.3 Cycle B primitives Cycle C composes on
- `_dry_run_active` (§2.2) — the load-bearing kill switch. Every NEW emit path in C MUST route through an existing `_send_*` or add a short-circuit at its own boundary. Review C mutation coverage per NEW site.
- `NM_LIFE_SAFETY_HAZARDS` (§2.2) — DND-bypass default seeds from this set.
- Token buckets (`CONF_NM_BUCKET_CAPACITY`, `CONF_NM_BUCKET_REFILL_PER_MIN` — `const.py:1362-1363`) — the router runs BEFORE the bucket; audit log records bucket outcome (`accepted` / `overflow_dropped` / `overflow_queued`).
- Safe-word ack registry (`CONF_NM_SAFE_WORD` `const.py:1366`; Cycle B B2 registry) — the mute shortcut C4 is orthogonal to ack (ack cancels the *episode*; mute suppresses a *channel* for the mute window).
- Overflow drop counter (Cycle B ships DROP COUNTER; real drain deferred to this cycle per parent plan line 292 — decision item C-DEC-2 below).

### 2.4 Prior routing/severity call sites in `notification_manager.py`
- `_channel_qualifies` (line 2508) — sole legacy router. Callers: line 2380, 2413, 2482.
- Emit fan-outs iterating over `nm_persons`: pushover (1073), companion (1092), whatsapp (1114), imessage (1133).
- Repeat-cycle fan-outs at 1690, 1696, 1703, 1707 (Cycle B B1).
- All emit boundaries with a `_dry_run_active` guard already present: 1320, 1353, 1393, 1409, 1428, 1461, 2182, 2349 (context injection). Full `hass.services.async_call` set (17 sites): 1338, 1385, 1397, 1413, 1433, 1501, 1512, 1536, 1548, 1552, 1560, 1566, 1569, 1578, 2191 + two `_restore_alert_lights` (teardown; exempt per B0 ruling).

### 2.5 Prior planning docs consulted
- `PLANNING_nm_overhaul_2026_07.md` — parent (full read).
- `PLANNING_nm_cycle_b_safety_rails.md` (if present) / v5.26.0 README — for the ack-registry schema shape.
- No sibling cycle-C planning doc exists; this is the first.

### 2.6 Memory bodies pulled
- **"NM BlueBubbles + WhatsApp Audit 2026-05-30"** — NM-1 shortcut framing (per-person per-channel mute; safe-word ack doesn't cover repeat cadence); NM-5 (DND-bypass lists); NM-6 (hazard-type as 3rd axis, adopted per parent revision 3). All six gap items map into Cycles B+C; C4 realizes NM-1 as first-class shortcut.

### 2.7 Design doc read
- `docs/Coordinator/NOTIFICATION_MANAGER.md` v1.0 — bumped to v1.1 as part of C2 (documents matrix router, DND-bypass semantics, mute-shortcut, replaces §7 `NotificationRateLimiter` sketch with Cycle B primitives).

### 2.8 Discrepancies / gotchas surfaced
1. `_channel_qualifies` is called from THREE sites (2380, 2413, 2482). Any migration must replace ALL THREE and Review C mutates each independently — a stub returning `True` at one site with the other two migrated leaves a routing leak.
2. `_dry_run_active` is checked at 8 emit boundaries + 1 context site. Review C mutates each site; missing a NEW C-added emit site is the exact D-HIGH-1 failure mode. D re-enumerates ALL emit sites, not just diff.
3. The alert-lights teardown at `_restore_alert_lights` deliberately runs under dry-run (B0 ruling: state honesty). C2 audit log must NOT log the teardown as a "sent notification" — separate log level.

---

## 3. Deliverables

### C1. Per-recipient criticality × channel (× optional hazard_type) matrix

**What.** Replace the global severity-per-channel router with a per-recipient matrix. Default view is 2D (`severity → {channel → bool}`); optional 3D override (`hazard_type → severity → {channel → bool}`) collapses to 2D when the axis is unset. Legacy `CONF_NM_*_ENABLED` / `CONF_NM_*_SEVERITY` migrate via `_migrate_legacy_severity_to_matrix()` producing byte-identical routing for the pre-C fixture tuple space.

**Where.**
- `const.py`: new nested keys under `CONF_NM_PERSONS[i]` — `CONF_NM_PERSON_ROUTING_MATRIX` (dict), `CONF_NM_PERSON_HAZARD_OVERRIDES` (dict|None).
- `config_flow.py` + `options_flow.py`: new step `nm_person_routing_step` per person entry; grid selector for 2D; per-hazard override sub-step.
- `notification_manager.py`: new `_route_for_recipient(recipient_id: str, hazard_type: str | None, severity: Severity) -> set[str]`; callers at 2380, 2413, 2482 migrate; `_channel_qualifies` kept as thin deprecation shim (calls the new router with `recipient_id=None` → falls back to legacy fixture) UNTIL C1 lives one deploy, then deleted in a follow-up.
- Migration function persists once at first setup after upgrade; idempotent.

**Acceptance criteria**
- **Verify:** For every recipient in `CONF_NM_PERSONS`, `_route_for_recipient(rid, None, sev)` returns the same channel set as v5.26.0's `_channel_qualifies` under the legacy config (fixture: 6 severities × 8 hazards × N recipients × 5 channels).
- **Verify:** Hazard-type override, when set, wins over the 2D matrix for that `(hazard_type, severity)` pair; when unset, the 2D matrix decides.
- **Sensor:** `sensor.ura_notification_manager` gains attribute `routing_matrix_configured_recipients: int`.
- **Test:** `quality/tests/test_nm_cycle_c_routing_matrix.py::test_migration_byte_identical` and `::test_hazard_override_wins` and `::test_matrix_backcompat_full_fixture`.
- **Live (dry-run):** MCP-drive one synthetic HIGH-water_leak; audit log records `route_reason=matrix_default` OR `hazard_override` per recipient, matches expected fixture.

### C2. Full dry-run / audit UX (builds on B0)

**What.** Promote B0's minimal `notification_log` dry-run rows into a first-class structured audit surface: per-recipient channel-set decisions, quiet-hours applied, DND-bypass applied, dedup outcome, rate-bucket outcome, mute-shortcut outcome, matrix vs hazard-override branch. Add sensor attribute + service to fetch last N routing decisions.

**Where.**
- `database.py`: **C-DEC-1** — extend `notification_log` via additive `ADD COLUMN` migration (`recipient_id`, `route_reason`, `dnd_bypass_applied`, `bucket_outcome`, `matrix_branch`, all nullable). Rationale: same-table keeps analytics queries stable; nullable columns invisible to existing readers (§2.2 additive-migration precedent). Sibling table rejected as duplicative given the shape overlap.
- `notification_manager.py`: audit-emit helper `_emit_audit_row(...)` called from the router + gate stack; guarded by `_dry_run_active` for the "would-have-fired" branch AND emitted for real fires too (audit is unconditional; dry-run just distinguishes real vs would).
- New service `nm.get_recent_routing_decisions(limit: int = 50) -> list[dict]`; sensor attribute `recent_routing_decisions_count` (rolling 1h).

**Acceptance criteria**
- **Verify (write-volume regression, parent plan revision 6):** Pre-deploy 7-day `notification_log` row rate captured under tag `pre-review-v<C-version>`; post-deploy 7-day rate is within ±25%. Audit rows are per-routing-decision — this is where the check earns its keep.
- **Test:** `test_nm_cycle_c_audit.py::test_dry_run_row_shape`, `::test_real_fire_also_audits`, `::test_audit_survives_migration_from_b0_schema`.
- **Live (dry-run):** MCP-drive 5 tuples across the (severity, hazard) grid; `service: nm.get_recent_routing_decisions` returns 5 rows with populated `route_reason` and `bucket_outcome`.
- **Live:** README write-back records observed 24h `notification_log` row rate vs pre-deploy snapshot.

### C3. Per-recipient DND-bypass lists

**What.** Formalize the "which severities may bypass quiet hours" decision as per-recipient config. Default: `dnd_bypass_severities = {CRITICAL}` (preserves v5.26.0 behavior). Life-safety hazards (`NM_LIFE_SAFETY_HAZARDS`) always bypass regardless of the recipient's set — hard-coded, not a knob (safety invariant).

**Where.**
- `const.py`: `CONF_NM_PERSON_DND_BYPASS_SEVERITIES` (frozenset[str], default `{"critical"}`).
- `options_flow.py`: multi-select in per-person step.
- `notification_manager.py`: `_is_quiet_hours()` unchanged; new `_recipient_bypasses_dnd(recipient_id, hazard_type, severity) -> bool`; router consults it. Existing global CRITICAL-bypass at line 974 remains as safety floor — never removed even if a recipient's set is empty (belt-and-suspenders).

**Acceptance criteria**
- **Verify:** MEDIUM alert to recipient R with `dnd_bypass_severities={LOW, MEDIUM, CRITICAL}` during quiet hours fires (dry-run row); same alert to recipient S with default set does NOT fire.
- **Verify:** Life-safety hazard (`smoke`) at any severity to any recipient during quiet hours fires (safety floor).
- **Test:** `test_nm_cycle_c_dnd_bypass.py::test_recipient_bypass_honored`, `::test_life_safety_always_bypasses`, `::test_default_preserves_v526_behavior`.
- **Live (dry-run):** During in-house quiet-hours window, MCP-inject synthetic MEDIUM `overheat` for recipient with default set — audit shows `dnd_bypass_applied=false, bucket_outcome=quiet_hours_suppressed`.

### C4. NM-1 "mute one person's one channel fast" shortcut

**What.** First-class UX for the frequent 2 AM operation. Per `(person_id, channel)` mute with expiry. Realized as:
- Service: `nm.mute_person_channel(person_id: str, channel: str, duration_minutes: int = 60)` — validates `person_id` in `CONF_NM_PERSONS`, `channel` in known transports.
- Button entities per `(person, channel)` combination that call the service with the operator-set duration (Number entity `nm_mute_default_duration_minutes`, rung 3, default 60).
- Companion "mute-all-channels-for-person" and "mute-all-persons-on-channel" buttons.
- State stored in `_person_channel_mutes: dict[tuple[str, str], datetime]`; router consults BEFORE matrix lookup.
- Restart-safe: persisted via `get_persistence_state` / `restore_persistence_state` (extends Cycle B B2 shape; absolute-time expiries survive restart cleanly, past-expiry entries pruned on restore).

**Where.**
- `const.py`: `CONF_NM_MUTE_DEFAULT_DURATION_MINUTES` (default 60), `SERVICE_NM_MUTE_PERSON_CHANNEL` service name constant.
- `notification_manager.py`: `_person_channel_mutes`, `async_mute_person_channel(...)`, `_mute_active(person_id, channel) -> bool`, integration into `_route_for_recipient`.
- `button.py`: per-`(person, channel)` `NMMutePersonChannelButton` (limit N = enabled channels per person to bound entity count — cap at 5 channels × N persons).
- `services.yaml`: schema for `nm.mute_person_channel`.

**Acceptance criteria**
- **Verify:** After `nm.mute_person_channel(person_id="oji", channel="pushover", duration_minutes=15)`, a subsequent HIGH-water_leak alert routes to `{companion, whatsapp}` for oji but not `pushover`; other persons unaffected.
- **Verify:** After the 15 min expires, next matching alert routes to `pushover` again (dry-run audit rows demonstrate).
- **Verify:** Mute survives HA restart if `duration_minutes` covers the restart window; past-expiry entries pruned on `restore_persistence_state`.
- **Sensor:** `sensor.ura_notification_manager` attribute `active_mutes_per_person: dict[str, list[str]]` (person → muted-channels).
- **Test:** `test_nm_cycle_c_mute_shortcut.py::test_mute_suppresses_target_channel_only`, `::test_expiry_auto_clears`, `::test_mute_survives_restart`, `::test_mute_pruned_when_past_expiry_on_restore`.
- **Live (dry-run):** MCP-drive the service, then MCP-inject a matching alert, then inspect audit log for `bucket_outcome=muted_person_channel`.

### C5. Config-boundary / combinatorial testing (Tier-3 mandate)

**What.** Explicit test matrix at knob extremes and inversions — this is where the leak hides per Tier-3 doctrine.

**Coverage axes and extremes**
- `dnd_bypass_severities`: `∅`, `{CRITICAL}` (default), `{LOW..CRITICAL}` (all-bypass).
- `routing_matrix`: empty (legacy fallback), all-channels-all-severities-true, all-false (recipient effectively muted).
- `hazard_overrides`: unset, override that contradicts base matrix (e.g., base says "no pushover for MEDIUM"; override for `intrusion` says "yes pushover for MEDIUM").
- `mute` state: none, all channels muted for a person, one channel muted across all persons.
- `CONF_NM_DRY_RUN`: false (live), true (dry-run) — every above combination tested under BOTH.
- Life-safety hazards vs non-life-safety at MEDIUM/HIGH/CRITICAL (safety-floor interaction with DND-bypass).

Test file: `quality/tests/test_nm_cycle_c_combinatorial.py`. Every combination asserts `_route_for_recipient` output AND (under dry-run) zero `hass.services.async_call` calls to notification transports via a `patch("...notification_manager.HomeAssistant.services.async_call")` guard that FAILS the test on any transport-domain call.

---

## 4. Numbers-Get-Knobs table

| Knob | Rung | Home | Default | Kill-switch semantics | Why here |
|---|---|---|---|---|---|
| `CONF_NM_PERSON_ROUTING_MATRIX` | **2 — options flow** | per-person options step | (migrated from legacy severity keys) | Empty dict → recipient receives no channels (silent) | Per-deployment structure; edited rarely at setup + when a household grows |
| `CONF_NM_PERSON_HAZARD_OVERRIDES` | **2 — options flow** | per-person options step (sub-step) | `None` | Absent → 2D matrix decides | Optional 3rd axis; rare edit |
| `CONF_NM_PERSON_DND_BYPASS_SEVERITIES` | **2 — options flow** | per-person options step | `{CRITICAL}` | `∅` → still bypassed for life-safety (safety floor) | Per-deployment quiet-hours policy |
| `CONF_NM_MUTE_DEFAULT_DURATION_MINUTES` | **3 — Number entity** | `number.py` | 60 | 0 → mute button no-ops (button disabled UI) | Operator legitimately tunes by observation; per-house paging fatigue |
| `nm.mute_person_channel` (service) | **3 — Service** | `services.yaml` + `notification_manager.py` | n/a | `duration_minutes=0` → clears existing mute (documented) | Frequent operator action |
| Per-`(person, channel)` mute Button | **3 — Button entity** | `button.py` | n/a | n/a (invokes service) | Companion-surfaced |
| `CONF_NM_DRY_RUN` (existing, promoted to UX first-class) | **2 + Switch** | `const.py:1330` + Switch | `false` | `true` → C-INV-2 (zero outbound) | Kill switch; audit surface |

Rung rationale: matrix + DND + hazard-override are structural per-household policy → rung 2. Mute duration + service + button are live-tunable operator paging-fatigue controls → rung 3. Nothing rung 1 (no fitted-model coefficients or protocol windows introduced).

---

## 5. Tier-3 review protocol

Four framing-disjoint reviews run in PARALLEL (D's framing cannot overlap A/B/C).

### Review A — Routing-matrix correctness (per-tuple)
Focus: `_route_for_recipient` for every `(sender, hazard_type, severity, recipient)` tuple against the fixture; legacy migration byte-identical; hazard-override precedence; empty-matrix → legacy fallback; enum-vs-str coercion (parent plan L4). Deliverable: pass/fail per tuple in the fixture, list of missed cases.

### Review B — Async / lifecycle / RestoreEntity round-trip + backward compat + write-volume regression
Focus: options-flow → CoordinatorManager reload → `_route_for_recipient` observes new matrix without HA restart (parent-reload watchdog memo — do NOT propose parent-entry reload for testing); mute state RestoreEntity round-trip across restart; `notification_log` schema migration additive; pre/post ±25% row-rate check per parent revision 6; ack-registry interaction with mutes (ack cancels episode; mute suppresses channel — orthogonal, verified).

### Review C — Test authority via REAL per-site source mutation
Focus: For EVERY `hass.services.async_call` in `notification_manager.py` (17 sites listed §2.4) AND the router `_route_for_recipient` AND `_recipient_bypasses_dnd` AND `_mute_active` — reviewer edits production source to bypass ONE load-bearing site at a time (e.g., replace `if self._dry_run_active: return` at line 1320 with `pass`; replace `if self._mute_active(...)` with `if False`), runs the suite, and confirms a SPECIFIC test fails. A site whose bypass leaves the suite green is untested = SHIP-BLOCK. Aggregate monkeypatch (parent plan critique) is NOT acceptable Tier-3 evidence.

### Review D — Adversarial completeness / diff-blind (MANDATORY, framing distinct from A/B/C)
Sole job: state C-INV-2 in falsifiable form and BREAK it. D re-enumerates the ENTIRE NM emit surface *including pre-existing sites the diff didn't touch* (v5.5.3 D-HIGH-1 precedent — a v5.5.0 gap was found in a v5.5.3 cycle because D looked at all sites, not just changed ones). Any flagged leak comes with a concrete legal-config reachable repro (values + state that trigger it, e.g., "dry_run=true, recipient has hazard-override `intrusion→CRITICAL→whatsapp=true`, mute set on pushover only, quiet-hours active → path X emits WhatsApp call at line Y"). D also enumerates C-INV-1 (backcompat) and C-INV-3 (DND-bypass) once C-INV-2 clears.

### Orchestrator independent verification (before ship, MANDATORY)
Orchestrator personally:
1. Re-greps every `hass.services.async_call` in `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` and confirms each is either (a) inside a `_send_*` with `_dry_run_active` guard OR (b) an exempt teardown (`_restore_alert_lights`).
2. Runs Review C's mutation on the load-bearing router site (`_route_for_recipient` returning `{"pushover", "companion", "whatsapp", "imessage", "tts", "lights"}` unconditionally) and confirms multiple combinatorial tests FAIL (proof the router is load-bearing in the emit chain).
3. Re-runs the fixture in Review A's file against v5.26.0 tag AND HEAD; diff must be empty for legacy-config tuples.

### Operator checkpoint BEFORE deploy (MANDATORY per Tier 3)
Surface to operator:
- The final invariant proof (Review D's completeness enumeration + C's mutation matrix).
- The pre-deploy write-volume snapshot for `notification_log`.
- The dry-run audit sample from the pre-deploy sweep.
- Explicit go/no-go on releasing pipeline-precondition #1 (populating per-person channel targets AFTER first successful live validation with dry-run OFF for one recipient).

---

## 6. Live-exercise posture (targets still blank)

C's live validation runs in TWO phases, both compatible with the blank-targets precondition:

**Phase 1 (targets blank, `CONF_NM_DRY_RUN=true`) — full dry-run sweep** (parent plan lines 266-272):
- MCP-inject synthetic hazards spanning `(severity ∈ {LOW..CRITICAL}) × (hazard_type ∈ life_safety ∪ non_life_safety) × (recipient ∈ configured persons) × (mute state ∈ {none, this_channel_muted, all_channels_muted}) × (DND state ∈ {inside_quiet_hours, outside})`.
- Assert via HA log capture: zero `hass.services.async_call` invocations to any notification-transport domain (`notify`, `pushover`, `tts`, `bluebubbles`, WhatsApp domain, and `light.turn_on` from alert-lights emit — teardown allowed).
- Query `nm.get_recent_routing_decisions` and diff against the fixture-expected decisions.
- Alert-lights teardown observed once per alert cycle (state honesty).

**Phase 2 (operator-checkpoint-gated) — one recipient, one channel, dry-run OFF**:
- After operator approves at the Tier-3 checkpoint, populate ONE per-person channel target (operator's own iMessage handle — already pipe-validated per parent precondition 1b).
- MCP-inject one synthetic MEDIUM `overheat`; confirm one iMessage arrives (operator echo, parent precondition 1b pattern).
- Confirm audit log records `route_reason=matrix_default, bucket_outcome=accepted, dnd_bypass_applied=false`.
- Only after Phase 2 clean → pipeline precondition #1 fully released → operator may populate remaining per-person targets outside a code cycle.

**README write-back (parent-plan rule):** post-restart validation table replaces the prospective bullets in `docs/readmes/README_v<C-version>.md`, one row per acceptance criterion above, with observed evidence (entity attribute values, audit-log rows cited, log-capture proofs).

---

## 7. Deferred-work register + carry-forward

### Carried forward from parent-plan deferred register (parent lines 290-296)

| Item | Origin | Cycle C ruling |
|---|---|---|
| Real overflow drain (per parent line 292 / B-C-HIGH-1) | Cycle B fix-up | **RE-DEFERRED.** Cycle C DOES change queued payload shape (adds `recipient_id`, `route_reason`, `matrix_branch`) — implementing drain here would ship the exact footgun the deferral was made to avoid (stale replays). Land drain in a Cycle D micro-cycle AFTER C's payload shape stabilizes for ≥ 1 deploy cycle. Home: new memory entry "NM overflow drain — Cycle D" opened at pipeline close. |
| `_bucket_refill()` wall-clock → monotonic (parent line 293, B-B6 / C-LOW-1) | Cycle B fix-up | **RE-DEFERRED to Cycle D.** Not on C's causal path; touching it here bloats Tier-3 scope. |
| `_boot_settle_seen` unbounded growth in 60 s window (parent line 294, C-LOW-2) | Cycle B fix-up | **RE-DEFERRED to Cycle D.** Trivial follow-up; not routing-adjacent. |
| **`overheat` / `high_co2` CRITICAL cadence — life-safety or not?** (parent line 295, A-MED-2 open policy question) | Cycle A open question | **CARRIED FORWARD, NOT RESOLVED in C.** Per instructions, this is a policy call for operator, not planner. Operator checkpoint (§5) is the natural place to surface it since it affects DND-bypass safety-floor behavior. If operator ratifies as life-safety, both tokens get added to `NM_LIFE_SAFETY_HAZARDS` in a Cycle A-3 follow-up (const-only change) and C3's safety-floor picks them up automatically (no additional code). If operator amends non-life-safety, document the framing in dashboard copy — no code change. **Cycle C ships with current behavior (300 s cadence, non-life-safety framing) preserved.** |

### Plan-completion accounting stub (fill at cycle close)

Enumerate each Cycle C deliverable at close:
- [ ] C1 shipped? (matrix + migration + backcompat)
- [ ] C2 shipped? (audit UX + service + sensor + schema migration)
- [ ] C3 shipped? (DND-bypass + safety floor preserved)
- [ ] C4 shipped? (mute shortcut + service + button + RestoreEntity)
- [ ] C5 shipped? (combinatorial test file present + green + mutation-verified)
- [ ] Tier-3 4 reviews complete with outcomes recorded in `docs/reviews/code-review/v<C-version>_nm_cycle_c.md` with bug-class tagging
- [ ] Operator checkpoint held; outcome recorded
- [ ] Live Phase 1 (dry-run sweep) results in README write-back
- [ ] Live Phase 2 (one recipient, dry-run off) results in README write-back
- [ ] Pipeline precondition #1 release recorded in parent plan
- [ ] Deferred items above re-homed in NM Cycle D memory entry

Any unchecked item at close requires a written justification in this section — silent drops prohibited (parent plan minimal-deferral rule).

### Decision items for operator at checkpoint

- **C-DEC-1** — audit schema strategy: extend `notification_log` (recommended, §3-C2) vs sibling `notification_audit_log` table. Recommendation: extend. Operator ratify.
- **C-DEC-2** — overflow-drain deferral to Cycle D (recommended above). Operator ratify.
- **C-DEC-3** — Phase 2 first-target channel: iMessage (operator's primary per parent 1b) vs Pushover (operator's other pre-validated pipe). Recommend iMessage.
- **A-MED-2 carry-forward** — `overheat`/`high_co2` life-safety classification (see deferred register).

---

## 8. Open questions for operator (surface at checkpoint, not before)

1. **A-MED-2 policy carry-forward.** Ratify `overheat` + `high_co2` as life-safety (30s cadence + always-bypass DND) or non-life-safety (current 300s + subject to per-recipient DND-bypass set)? Parent plan explicitly leaves this to operator.
2. **C-DEC-1.** Audit column extension vs sibling table — operator preference or defer to recommendation?
3. **C-DEC-3.** Phase-2 pilot channel and recipient.
4. **Mute-button entity fan-out cap.** Cap `NMMutePersonChannelButton` at N persons × 5 channels = up to ~25 buttons for a household. Acceptable, or should Companion actions substitute above a lower cap (say 3 persons)?
5. **Legacy severity keys deprecation timeline.** After C ships and migration runs, do we delete `CONF_NM_PUSHOVER_SEVERITY` etc. in Cycle D, or keep them as read-only fallback indefinitely?
