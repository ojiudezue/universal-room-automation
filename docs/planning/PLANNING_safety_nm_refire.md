# PLANNING — SAFETY-NM-REFIRE-UNWIRED-1 (Rev 2): wire hazard_type/location on the Safety NotificationAction, make `is_hazard_active` hold-aware, and stop the unacked repeat loop when Safety reports the hazard cleared

- Card: `SAFETY-NM-REFIRE-UNWIRED-1`
- Blocker: `SAFETY-HAZARD-NEVER-CLEARS-1` — shipped v5.103.61 (2026-10-15, live).
- Tier: **Tier 2-DB** (standing policy for regression-prone life-safety work; cross-coordinator safety ↔ NM; touches a shared primitive — the NM re-fire / repeat path — consumed by every coordinator).
- Branch / worktree: `plan/safety-refire` under `.claude/worktrees/plan-safety-refire`.
- Scope: **plan only**. Do not build; do not run the full suite.
- Rev 2 motivation: plan review (`docs/reviews/code-review/plan_safety_nm_refire_review.md`,
  2026-10-15, FIX-REQUIRED) returned findings F1-F7. This revision resolves each in the
  "Review-resolution" table (§0) and expands the deliverables with D5 (unacked
  repeat-loop stop-on-clear) and D6 (flooding location sort) + corresponding tests. The
  code shape of the original D1/D2 is unchanged; the plan text, invariant, blast
  radius, test list, and live-validation query are corrected.

## 0. Review-resolution table (plan review FIX-REQUIRED → Rev 2)

| # | Severity | Finding (summary) | Resolution in Rev 2 | Verified against |
|---|---|---|---|---|
| F1 | HIGH | Plan omitted D1's real NM blast radius; wrongly said non-life-safety comfort hazards would get a 300 s re-fire (non-CRITICAL never enters ALERTING / cooldown). | §5 D1 "Blast radius" rewritten as the explicit list of NM behaviours flipped for life-safety tokens (repeat cadence, boot-settle exemption, DND/mute/token-bucket bypass, security-image guard, per-hazard boot-settle dedup bucket, cooldown length). Each tagged intended / unintended. The wrong 300 s claim removed; §10 Q2 superseded. | `notification_manager.py:2578-2579, 2634, 1508-1509, 4184, 4235, 3889-3892, 3925, 4028, 1480, 658`; `const.py` COOLDOWN_CONFIG + `is_life_safety_hazard`. |
| F2 | HIGH | INV-REFIRE clause 2/3 false on the UNACKED repeat path: `_repeat_alert` never consults `is_hazard_active`, and with D1 making life-safety repeats 30 s flat, a smoke CRITICAL whose detector recovered pages every 30 s until an ACK. Operator travelling → not acceptable. | **D5 added.** `_repeat_alert` gets a Safety-scoped stop-on-clear gate: when `coordinator_id == "safety"` AND the live Safety coordinator reports `is_hazard_active(hazard_type, location) is False` (same hold-aware predicate from D2), transition to IDLE and skip the re-page. Non-Safety coordinators preserve current repeat behaviour (no change). Fail-open on EVERY error path — unresolvable coordinator / predicate exception / missing coordinator-manager → keep paging CRITICAL (life-safety contract: never silence a live hazard on a bug). INV-REFIRE §1 reworded to cover BOTH paths (post-ACK cooldown AND unacked REPEATING). | `notification_manager.py:2645-2710` (`_repeat_alert`), `:3034-3039` (precedent for the coordinator lookup it mirrors), `safety.py:3398-3410` (predicate used). |
| F3 | MEDIUM | Invariant hazard set wrong: FIRE never emitted by Safety; OVERHEAT absent from `NM_LIFE_SAFETY_HAZARDS` and never CRITICAL; WATER_LEAK/FREEZE_RISK never enter ALERTING. | §1 restated: invariant domain = **CRITICAL Safety hazards actually emitted**, i.e. `{smoke, carbon_monoxide (≥100 ppm), flooding}` — the intersection of the Safety-emitted CRITICAL set and `NM_LIFE_SAFETY_HAZARDS`. Flooding's 5 min cooldown ≥ the 300 s clear hold is noted (clause 3 bites only on smoke/CO). | `safety.py:1864` (smoke CRITICAL), CO numeric thresholds CRITICAL ≥100 ppm, `safety.py:1917-1919, 1938` (flooding CRITICAL); `const.py:3391-3399` (`NM_LIFE_SAFETY_HAZARDS`). |
| F4 | LOW | `security.py:825-828` pre-existing `is_hazard_active` checks `"intrusion"` but security emits `"intruder"` → security re-fire path also dead. | **Explicit non-goal.** Separately carded as `SECURITY-REFIRE-INTRUSION-KEY-1` (sibling to this card). §6 updated. | `security.py:825-828`; `const.py:3393-3396` comment. |
| F5 | MEDIUM | Test miscount (6 listed vs "five"); 3 tests pass on develop (regression guards) misdescribed as RED; round-trip omits ACK; "re-fired exactly once" ambiguous; relapse test should drive through `_respond_to_hazard`, not call `_record_sensor_relapse` directly. | §5 D3 rewritten: **8 tests total** split into (a) regression guards (pass on develop today), (b) fix-proving tests (must FAIL on develop, PASS after build), (c) negative twins. Round-trip test explicitly performs the `async_acknowledge` step. "Exactly one re-fire" scoped to `async_notify` calls originating from `_re_evaluate_hazard` only; the subsequent REPEATING-state ticks are counted separately. Relapse test drives via the smoke binary-sensor path (`_respond_to_hazard` → `_LIFE_SAFETY_REARM_TYPES` re-arm, `safety.py:2487-2492`). Unacked-recovery test added for D5 (RED on develop even after D1 alone — proves D5 is load-bearing). | `notification_manager.py:2953` (`_start_cooldown` only inside `async_acknowledge`); `safety.py:2487-2492`. |
| F6 | LOW | Live-validation query used `ts` / columns not verified against `notification_log` DDL; D2 live keyed on a log string instead of a DB row. | §8 live queries rewritten against the real schema: columns `id, timestamp, coordinator_id, severity, title, message, hazard_type, location, person_id, channel, delivered, acknowledged, ack_time, cooldown_expires, dry_run, recipient_id, route_reason, dnd_bypass_applied, bucket_outcome, matrix_branch`. D2 live-check now reads a `notification_log` re-fire row (ground truth) in addition to the log scan. | `database.py:4440-4490` (`log_notification` DDL / INSERT column order). |
| F7 | LOW | Flooding `location = ", ".join(set(...))` → non-deterministic order; a later re-key can mismatch and `is_hazard_active` returns False on a still-active multi-sensor flood. | **D6 added.** One-line fix: `", ".join(sorted(set(locations)))` at `safety.py:1919` and `safety.py:1926` (message string, same set). Covered by a new deterministic-order test. Fix LOWs In-Cycle. | `safety.py:1910-1928`. |

**Carried from Rev 1 unchanged:** D1 (populate `hazard_type` + `location` on the Safety
`NotificationAction`), D2 (`is_hazard_active` hold-aware), the knob-ladder table, the
single-emission-site institutional-context verdict.

## 1. Falsifiable invariant (revised per F2, F3)

> **INV-REFIRE (Rev 2)**: Let `H_safety_crit = {smoke, carbon_monoxide, flooding}` be the
> subset of `HazardType` the Safety Coordinator actually emits at CRITICAL severity
> (intersected with `const.NM_LIFE_SAFETY_HAZARDS`). For every hazard emitted by
> Safety with `hazard_type ∈ H_safety_crit`:
>
> 1. **Still-active ⇒ re-page, on BOTH paths.**
>    - *Post-ACK path:* when NM's cooldown expires in state `COOLDOWN`,
>      `_re_evaluate_hazard` (`notification_manager.py:3020-3060`) MUST see
>      `coordinator.is_hazard_active(hazard_type, location) == True` and MUST re-fire
>      exactly once (one `async_notify(severity=CRITICAL)` call from `_re_evaluate_hazard`).
>    - *Unacked REPEATING path:* while `_alert_state == REPEATING` and the hazard is
>      unacked, each `_repeat_alert` tick MUST re-page as long as
>      `is_hazard_active(hazard_type, location) == True`.
> 2. **Cleared ⇒ never re-page, on BOTH paths.**
>    - *Post-ACK path:* when every raising sensor has recovered AND the
>      `HAZARD_MIN_HOLD_S = 300 s` clear hold has elapsed (key popped from
>      `_active_hazards`), `is_hazard_active(...) == False` and NM returns to IDLE
>      at cooldown expiry.
>    - *Unacked REPEATING path:* on the first `_repeat_alert` tick where
>      `is_hazard_active(...) == False`, NM transitions to IDLE and no further re-page
>      fires. (D5.)
> 3. **Pending-clear ⇒ never re-page, on BOTH paths.** If every raising sensor has
>    recovered but the 300 s clear hold is still running (key in
>    `_hazard_clear_pending`), `is_hazard_active(...) == False` even though the key is
>    still in `_active_hazards`. This is the `constraint_2026_10_14` requirement: the
>    smoke/CO cooldown (120 s, `DEFAULT_NM_COOLDOWN_SMOKE/_CO = 2 min`) and the 30 s
>    life-safety repeat cadence are both shorter than the 300 s clear hold, so without
>    this clause we would re-page CRITICAL (post-ACK) or keep paging every 30 s
>    (unacked) for a detector that has already recovered. Flooding's 5 min cooldown is
>    ≥ the 300 s hold, so clause 3 only bites for smoke/CO on the post-ACK path; it
>    still bites for all three on the unacked REPEATING path (30 s < 300 s < 5 min).
> 4. **Re-raise during pending clear ⇒ re-page.** If the hold is pending and a
>    contributor relapses through the smoke/CO/leak sensor path
>    (`_respond_to_hazard` → `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` at
>    `safety.py:2487-2492`), `is_hazard_active(...) == True` and both paths re-page.
> 5. **Fail-open on D5 errors.** On the unacked REPEATING path, if the coordinator
>    lookup or `is_hazard_active` call raises OR the coordinator-manager / coordinator
>    is unresolvable, `_repeat_alert` MUST re-page (never silence a live life-safety
>    hazard due to a bug). Clause 2 (unacked path) is CONDITIONAL on
>    `is_hazard_active` returning a well-formed `False`.
>
> **Falsification observations (any one disproves the plan):**
> - Live `notification_log` row where NM cooldown expired on an active smoke/CO
>   hazard and no re-page row followed within one tick → clause 1 (post-ACK) false.
> - A re-page row whose `hazard_type` matches a key currently in
>   `_hazard_clear_pending` → clause 3 false.
> - A `_re_evaluate_hazard` call with `hazard_type == ""` or `location == ""`
>   (grep `notification_log` and the structured log line at
>   `notification_manager.py:3042-3044`) → the D1 wiring did not land.
> - On the unacked path: a smoke sensor goes off, recovers, 300 s hold elapses, and
>   `_repeat_alert` continues to insert `notification_log` rows for the same
>   (coordinator_id, hazard_type, location) key after the hold expiry → D5 false.
> - An induced predicate exception during the unacked path produces NO re-page row
>   within one repeat interval → clause 5 (fail-open) false.

## 2. Institutional-context verified

Grep surfaces consulted: `const.py`, `config_flow.py`, `options_flow.py`,
`sensor.py`, `binary_sensor.py`, `number.py`, `switch.py`, `select.py`,
`button.py`, `services.yaml`, `domain_coordinators/*.py`, `database.py`,
`docs/Coordinator/*`, `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md`.

Prior-art verdicts (REUSED / NEW with file:line) — unchanged from Rev 1 except where noted:

- **`NotificationAction.hazard_type` field** — REUSED (`base.py:136`).
- **`NM.async_notify(hazard_type, location)`** — REUSED
  (`notification_manager.py:530-558`).
- **`BaseCoordinator.is_hazard_active`** — REUSED (`base.py:237`); override at
  `safety.py:3398-3410`.
- **`_hazard_clear_pending`** — REUSED
  (`safety.py:1043, 2870, 2878, 2885, 2890, 2927, 2944, 2952, 3051, 3441`).
  Read-only in this cycle.
- **`HazardType` emitted at CRITICAL by Safety** — ENUMERATED via grep of
  `Severity.CRITICAL` inside `Hazard(` constructors in `safety.py`:
  `smoke` (`safety.py:1864`), `carbon_monoxide` ≥100 ppm (via `NUMERIC_THRESHOLDS`),
  `flooding` (`safety.py:1917-1919`, `:1938`). WATER_LEAK tops out at HIGH; FREEZE_RISK
  / OVERHEAT / HIGH_CO2 / HIGH_TVOC / HUMIDITY top out at HIGH or MEDIUM — none ever
  enter NM's ALERTING state. **FIRE** is defined in the enum but never produced in
  `safety.py` (verified: no `type=HazardType.FIRE` construction site). This grounds
  the Rev 2 invariant domain.
- **NM cooldown constants** — REUSED (`const.py` COOLDOWN_CONFIG):
  `DEFAULT_NM_COOLDOWN_SMOKE=2`, `_CO=2`, `_FLOODING=5`, `_WATER_LEAK=10`,
  `_FREEZE=15`. Not touched.
- **Life-safety repeat cadence** — REUSED (`NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s`,
  `const.py`). Not touched. Rev 2 note: D1 is the first time Safety reaches it
  because today Safety emits with `hazard_type=None` → `is_life_safety_hazard() == False`.
- **`is_life_safety_hazard`** — READ-ONLY. Branches used:
  `notification_manager.py:2578-2579` (`_repeat_interval_for_active_alert`),
  `:2634` (`_repeat_phase`), `:1508-1509` (boot-settle), `:4184` (DND floor),
  `:4235` (router mute), `:3889-3892, 3925, 4028` (token bucket bypass),
  `:1480` (security-image guard), `:658` (boot-settle dedup bucket key).
  **F1 enumeration** — these are the NM policies that flip when D1 lands.
- **Precedent for `hazard_type`-wired NotificationAction** — REUSED. Sites that already
  pass `hazard_type`+`location`: `perimeter_alert.py:1529, 2968`,
  `zone_monitoring_tripwire.py:125`, `button.py:2373` (test),
  `energy_battery.py:1313, 1507, 1599, 1769, 1855`. Safety is the single outlier.
- **Existing NotificationAction site in safety** — ENUMERATED, one and only one:
  `safety.py:2579-2587` inside `_respond_to_hazard`.
  (`rg -n 'NotificationAction\(' safety.py` → single match.)
- **`_repeat_alert` (D5 target)** — REUSED (`notification_manager.py:2645+`). The
  coordinator-manager lookup at `:3034-3039` (used by `_re_evaluate_hazard`) is the
  pattern D5 mirrors. No new helper is introduced; the predicate is the hold-aware
  `is_hazard_active` from D2.

Prior planning docs consulted:
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` rev 4 — read §4-G
  (`is_hazard_active` suffix-aware), §10 (SAFETY-NM-REFIRE-UNWIRED fold-out).
- `docs/reviews/code-review/plan_safety_nm_refire_review.md` (Rev 1 plan review, this
  file's F1-F7 trigger).

Memory bodies pulled: none required beyond CLAUDE.md's standing rules (No
Fabrication, Config-First, Numbers-Get-Knobs, Tier-2-DB default, Fix LOWs In-Cycle,
Suppression needs a discharge).

Design docs read: `docs/Coordinator/SAFETY_COORDINATOR.md` §5 clear-on-recovery
(line 293: `HAZARD_MIN_HOLD_S = 300` and the per-minute sweep).

Code locations surveyed end-to-end:
- `safety.py:1864-1940` (CRITICAL emission sites: smoke, flooding)
- `safety.py:2465-2600` (`_respond_to_hazard` + `NotificationAction` emit; re-arm at
  `:2487-2492`)
- `safety.py:2860-2954` (clear-hold machinery, `_record_sensor_recovery`,
  `_try_clear_if_quiet`, `_sweep_hazard_clears`)
- `safety.py:3398-3410` (`is_hazard_active`)
- `manager.py:1070-1095` (NOTIFICATION dispatch — forwards `action.hazard_type or None`
  and `action.location or None`)
- `notification_manager.py:520-560` (`async_notify` + cooldown entry)
- `notification_manager.py:2515-2600` (`_enter_alerting` — only CRITICAL enters)
- `notification_manager.py:2562-2644` (`_repeat_interval_for_active_alert`,
  `_repeat_phase`)
- `notification_manager.py:2645-2800` (`_repeat_alert` — D5 target)
- `notification_manager.py:2953-3060` (`async_acknowledge` → `_start_cooldown` →
  `_cooldown_expired` → `_re_evaluate_hazard`)
- `base.py:120-240` (`NotificationAction` schema + base `is_hazard_active`)
- `const.py` COOLDOWN_CONFIG + `NM_LIFE_SAFETY_HAZARDS` + `NM_REPEAT_*`
- `database.py:4440-4490` (`log_notification` INSERT column order — F6 source).

## 3. Config-first check

- No configuration (knob, options-flow field, HA setting, operator action) resolves this:
  the data to be propagated (hazard type + location) are **computed inside the
  emitter** and are not operator-settable. Live NM cooldown values are tunable but
  irrelevant to the symptom (`is_hazard_active('','')` always-False and the unacked
  repeat loop never consults it at all).
- Verdict: **Code change required.** Config-first checked; no knob turn substitutes.

## 4. Producer and Consumer map

**Producer** (`safety.py:2465-2587`):
- Arithmetic: `hazard.type.value` (StrEnum → canonical token) and `hazard.location`
  (room/zone string populated at every `Hazard(...)` construction site:
  `safety.py:1864, 1891, 1917, 1938, 1805, 2073, 2175, 2200, 2229, 2404, 2446`).
- Dependency health: both are already set at every `Hazard` construction site; the
  `@dataclass` requires both as keyword args. Flooding's `location` composition
  (D6 target) is the only non-deterministic string in the set.

**Consumers:**
- `manager.py:1070-1081` (trust, forwards both into NM).
- `notification_manager.py:551` (trust, log row): writes `hazard_type` + `location`
  into `notification_log`.
- `notification_manager.py:3029-3039` (trust, post-ACK re-fire gate): calls
  `coordinator.is_hazard_active(hazard_type, location)` — D2 consumer.
- `notification_manager.py:2645-2710` (trust, unacked REPEATING loop): **new consumer
  via D5** — calls the same predicate.
- `notification_manager.py:2578-2579, 2634, 1508-1509, 4184, 4235, 3889-3892, 3925,
  4028, 1480, 658` (policy): read `hazard_type` for life-safety classification.
  **F1 blast radius** — see §5 D1.
- `sensor.py:8341, 8436, 8548, 14169` (display): dashboard readouts.
- `database.py:4440-4490` (storage, `log_notification`): persists both.

## 5. Deliverables

### D1 — Populate `hazard_type` + `location` on the Safety `NotificationAction`

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:2579-2587`

**Change (surgical):** inside the one `NotificationAction(...)` constructor, add two
keyword arguments:

```python
hazard_type=hazard.type.value,
location=hazard.location,
```

That is it. No new import; `hazard.type.value` is already the exact token written to
`notification_log` by the activity-logger block one scope up (`safety.py:2537`), so
the two sites now agree on their key.

**Blast radius in NM (F1 — rewritten).** Today every Safety alert reaches NM with
`hazard_type=None`, so `is_life_safety_hazard()` returns False for smoke / CO /
flooding at every call site in NM. D1 flips the following NM policies at once for
Safety life-safety tokens (`smoke`, `carbon_monoxide`, `flooding`). Each is tagged
**intended** or needs explicit acceptance:

| # | Site | Behaviour today (hazard_type=None) | Behaviour post-D1 | Verdict |
|---|---|---|---|---|
| B1 | `_repeat_interval_for_active_alert` (`notification_manager.py:2578-2579`) + `_repeat_phase` (`:2634`) | 300 s decay ladder (`phase1=300 s` → `phase2` after `PHASE1_WINDOW_S` → `daily` after `DAILY_AFTER_S`). | Fixed **30 s** (`NM_REPEAT_INTERVAL_LIFE_SAFETY`), **never decays**. | **INTENDED.** Life-safety contract (`const.py:3387`). D5 bounds the exposure (unacked repeats stop as soon as Safety reports cleared). |
| B2 | Boot-settle collapse exemption (`notification_manager.py:1508-1509`) | Smoke/CO/flooding CRITICALs raised during the boot-settle window could be collapsed into the dedup bucket (silent). | Boot-settle collapse is bypassed for life-safety hazards — the CRITICAL raises immediately. | **INTENDED.** A smoke hazard during boot must not be silenced. |
| B3 | DND safety floor (`notification_manager.py:4184`) | DND veto applies, suppressing CRITICAL smoke/CO/flooding during quiet hours. | DND bypass applied — life-safety CRITICALs page through DND. | **INTENDED.** DND safety floor is the stated design. |
| B4 | Router per-recipient mute bypass (`notification_manager.py:4235`) | Per-recipient mute suppresses even CRITICAL smoke/CO. | Per-recipient mute bypassed for life-safety. | **INTENDED.** |
| B5 | Token-bucket bypass (`notification_manager.py:3889-3892, 3925, 4028`) | Rate limiter can drop smoke CRITICALs in a burst. | Token bucket bypassed for life-safety; CRITICALs always admitted. | **INTENDED.** |
| B6 | Security-image override guard (`notification_manager.py:1480`) | A smoke alert during a security image path could be deprioritised. | Life-safety path takes precedence. | **INTENDED.** |
| B7 | Boot-settle dedup bucket key (`notification_manager.py:658`) | Key `(coord, hazard_type)` was `("safety", "")` — a single shared bucket for all Safety hazards during boot. | Per-hazard buckets: `("safety","smoke")`, `("safety","carbon_monoxide")`, `("safety","flooding")`. | **INTENDED.** Dedup becomes correct per-hazard. |
| B8 | COOLDOWN_CONFIG lookup (post-ACK path, `notification_manager.py:196-205`) | Cooldown falls back to `DEFAULT_NM_COOLDOWN_DEFAULT` (keyed on `""`). | Smoke/CO → 120 s; flooding → 5 min. | **INTENDED.** Operator-tunable per-hazard cadence. |

**NON-regression (F1 correction):** non-life-safety Safety hazards (HIGH / MEDIUM —
HIGH_CO2, HIGH_TVOC, HUMIDITY, OVERHEAT, FREEZE_RISK, WATER_LEAK) **do not enter the
ALERTING state at all** (only `Severity.CRITICAL` enters, `notification_manager.py:2515`).
They therefore never reach `_cooldown_expired` / `_re_evaluate_hazard` / `_repeat_alert`,
and the Rev 1 claim that they would get "a 300 s non-life-safety re-fire" was wrong and
is removed. Their non-life-safety classification does route them through B2-B6 differently
(e.g. subject to DND, token bucket, mute), which is the intended non-life-safety
treatment.

**Build test anchor for F1 (new):** `test_safety_smoke_repeat_phase_is_life_safety` —
construct a smoke CRITICAL through `_respond_to_hazard`, drive it to `REPEATING`, assert
`nm._repeat_phase() == "life_safety"` and `nm._repeat_interval_for_active_alert() ==
NM_REPEAT_INTERVAL_LIFE_SAFETY`. **RED on develop today** (hazard_type is None →
returns `"phase1"` / 300 s).

### D2 — Make `is_hazard_active` hold-aware

Unchanged from Rev 1. **File / line:**
`custom_components/universal_room_automation/domain_coordinators/safety.py:3398-3410`.

Reference implementation:

```python
def is_hazard_active(self, hazard_type: str, location: str) -> bool:
    """SAFETY-NM-REFIRE-UNWIRED-1: hold-aware — a key whose clear hold
    is pending (all contributors recovered, 300 s HAZARD_MIN_HOLD_S not
    yet elapsed) is reported INACTIVE so NM does not re-page a
    detector that has already recovered. A relapse cancels the hold
    (`_record_sensor_relapse`), which re-exposes the key here.
    """
    exact = f"{hazard_type}:{location}"
    for active_key in self._active_hazards:
        base = active_key[:-4] if active_key.endswith(":roc") else active_key
        if base != exact:
            continue
        # Hold-aware: a pending clear with no raising contributors == inactive.
        if (
            active_key in self._hazard_clear_pending
            and not self._hazard_raising_sensors.get(active_key)
        ):
            continue
        return True
    return False
```

Preserves the ROC-suffix behaviour shipped in SAFETY-HAZARD-NEVER-CLEARS-1 §4-G.
Covered by existing test `test_safety_hazard_clear_on_recovery.py:515-525` (regression
guard).

### D3 — Tests (quality/tests/safety/ and quality/tests/notification_manager/)

**8 tests total.** Each is explicitly classified as (R) regression guard (passes on
develop today) or (F) fix-proving (fails on develop today, passes on build).

| # | Name | File | Class | Mutation anchor |
|---|---|---|---|---|
| T1 | `test_safety_notification_action_carries_hazard_type_location` | `quality/tests/safety/` | **F** | Remove either `hazard_type=` or `location=` kwarg from D1 → assertion flips. |
| T2 | `test_safety_is_hazard_active_true_when_active` | `quality/tests/safety/` | **R** | Covers D2 non-regression on the already-shipped path. |
| T3 | `test_safety_is_hazard_active_false_when_cleared` | `quality/tests/safety/` | **R** | Covers D2 non-regression on the cleared path. |
| T4 | `test_safety_is_hazard_active_false_during_clear_hold` | `quality/tests/safety/` | **F** | Revert D2 → test fails (pending-clear key returns True). |
| T5 | `test_safety_is_hazard_active_true_on_relapse_during_hold` | `quality/tests/safety/` | **R** | Drives relapse through `_respond_to_hazard` (smoke binary-sensor flips back on) exercising `had_pending_clear` + `_LIFE_SAFETY_REARM_TYPES` at `safety.py:2487-2492` — NOT by calling `_record_sensor_relapse` directly. |
| T6 | `test_safety_smoke_repeat_phase_is_life_safety` | `quality/tests/notification_manager/` | **F** | New F1 anchor. Remove either D1 kwarg → `_repeat_phase()` returns `"phase1"` and the assertion fails. |
| T7 | `test_nm_re_evaluates_safety_hazard_round_trip` | `quality/tests/notification_manager/` | **F** | Full post-ACK round-trip. Steps: (1) raise smoke via `_respond_to_hazard`; (2) assert ALERTING; (3) call `nm.async_acknowledge(...)` (ACK step — fixes Rev 1 omission); (4) advance 120 s cooldown; (5) assert exactly ONE `async_notify(severity=CRITICAL)` call originating from `_re_evaluate_hazard` (counted by patching the sole call site at `notification_manager.py:3046-3054`); (6) assert the call used `hazard_type="smoke"` and `location="<room>"` (not `("", "")`). Separately counts REPEATING-state ticks — not included in the "exactly one" count. |
| T7-neg | `test_nm_re_evaluate_no_refire_during_pending_clear` | `quality/tests/notification_manager/` | **F** | Negative twin of T7. Steps (1)-(3) as T7; then (4) smoke sensor recovers at t=60 s (hold armed, `_hazard_clear_pending` has the key); (5) advance to t=130 s (cooldown expired, hold still running); (6) assert ZERO re-fire `async_notify` calls from `_re_evaluate_hazard` and `_alert_state == IDLE`. Fails on develop even with D1 but without D2 (would re-fire). |
| T8 | `test_nm_repeat_alert_stops_when_safety_reports_cleared` | `quality/tests/notification_manager/` | **F** | **D5 anchor (F2 fix).** Steps: (1) raise smoke CRITICAL, do NOT ack → enter REPEATING; (2) advance 30 s → assert one re-page row; (3) smoke sensor recovers at t=45 s (hold armed); (4) advance past 300 s hold expiry (t=360 s); (5) assert `_repeat_alert` ticks observed `is_hazard_active == False`, transitioned to IDLE, and NO further `notification_log` row was written. **RED on develop even after D1 alone** (D1 makes the repeat 30 s flat; without D5 the loop never consults `is_hazard_active` and keeps paging). Mutation anchor: revert D5 only → test fails. |
| T8-fail-open | `test_nm_repeat_alert_fails_open_on_predicate_error` | `quality/tests/notification_manager/` | **F** | Monkeypatch `safety.is_hazard_active` to raise; drive one `_repeat_alert` tick on an active smoke CRITICAL; assert re-page emitted (clause 5). Revert D5's try/except → test fails or raises. |
| T9 | `test_safety_flooding_location_is_deterministic` | `quality/tests/safety/` | **F** | **D6 anchor (F7 fix).** Construct two `_active_leak_sensors` with locations `["Kitchen", "Garage"]` in two different insertion orders; assert the emitted `Hazard.location` is `"Garage, Kitchen"` (sorted) in both runs. RED on develop (`set()` iteration order non-deterministic). |

### D4 — Doc updates (same commit as build, per CLAUDE.md §10 rule)

- `docs/Coordinator/SAFETY_COORDINATOR.md` §5: add a paragraph that (a)
  `is_hazard_active` is hold-aware (post-ACK path), (b) NM's unacked REPEATING
  loop also consults it (D5), (c) the clear hold (300 s) and smoke/CO cooldown
  (120 s) + 30 s repeat cadence interact by design.
- `docs/planning/PLANNING_safety_hazard_clear_on_recovery.md` §10: mark the
  SAFETY-NM-REFIRE-UNWIRED fold-out as "shipped v<next>" with back-link.

### D5 — Stop the unacked repeat loop when Safety reports cleared (F2)

**File / line:** `custom_components/universal_room_automation/domain_coordinators/notification_manager.py:2645-2710` (inside `_repeat_alert`, before the per-person fan-out and after the state / messaging-suppressed guards at `:2647-2650`).

**Change (surgical, Safety-scoped, fail-open):**

```python
# SAFETY-NM-REFIRE-UNWIRED-1 D5: stop re-paging an unacked life-safety
# CRITICAL once the owning coordinator reports the hazard is no longer
# active. Mirrors the predicate used by _re_evaluate_hazard (:3034-3039).
#
# Scope: ONLY coordinator_id == "safety" (preserves current behaviour for
# every other coordinator — out of scope here; a sibling card will apply
# the same pattern to security after SECURITY-REFIRE-INTRUSION-KEY-1).
#
# Fail-open: ANY error path (missing coordinator-manager, unresolvable
# coordinator, predicate raises) MUST keep paging. Never silence a live
# life-safety hazard due to a bug.
data = self._active_alert_data
coord_id = data.get("coordinator_id", "")
if coord_id == "safety":
    try:
        hazard_type = data.get("hazard_type", "") or ""
        location = data.get("location", "") or ""
        cm = self.hass.data.get(DOMAIN, {}).get("coordinator_manager")
        coord = cm.coordinators.get(coord_id) if cm else None
        if coord is not None:
            still_active = coord.is_hazard_active(hazard_type, location)
        else:
            still_active = True  # fail-open
    except Exception:
        _LOGGER.warning(
            "D5 is_hazard_active predicate raised — failing open (keep paging)",
            exc_info=True,
        )
        still_active = True
    if not still_active:
        _LOGGER.info(
            "Safety hazard %s at %s cleared — stopping repeat loop",
            hazard_type, location,
        )
        self._alert_state = AlertState.IDLE
        self._active_alert_data = None
        async_dispatcher_send(self.hass, SIGNAL_NM_ALERT_STATE_CHANGED)
        async_dispatcher_send(self.hass, SIGNAL_NM_ENTITIES_UPDATE)
        return
```

**Discharge (per "Suppression needs a discharge"):** this is not a suppression — it is
a terminal transition to IDLE. The REPEATING-state tick listener is implicitly cancelled
on the next scheduling pass because `_alert_state != REPEATING` falls through the guard
at `:2649`. No lingering timer; no residual state.

**Non-Safety coordinators:** `coord_id != "safety"` branch is skipped entirely →
byte-identical behaviour for every non-Safety repeat path. (Security will adopt the
same pattern once `SECURITY-REFIRE-INTRUSION-KEY-1` lands.)

**Fail-open proof obligation:** T8-fail-open test above. Reviewer C mutation-anchors it
by removing the `try/except` and asserting the test fails.

### D6 — Deterministic flooding location (F7)

**File / line:** `custom_components/universal_room_automation/domain_coordinators/safety.py:1919, 1926`.

**Change:**

```python
# before:
location=", ".join(set(locations)),
...
f"{', '.join(set(locations))}!"

# after:
location=", ".join(sorted(set(locations))),
...
f"{', '.join(sorted(set(locations)))}!"
```

**Rationale:** `set()` iteration order is non-deterministic across process restarts
(hash randomisation) so a flooding hazard raised, cleared partway, then re-keyed may
not match itself in `_active_hazards` → `is_hazard_active` returns False on a still-
active multi-sensor flood. One-line, in-cycle per Fix LOWs In-Cycle. T9 is the anchor.

## 6. Non-goals (expanded)

- No change to NM cooldown defaults (`DEFAULT_NM_COOLDOWN_SMOKE=2` etc.) — knob on the
  entity ladder, not a code decision here.
- No change to the life-safety hazard set (`NM_LIFE_SAFETY_HAZARDS`).
- No new `NotificationAction` emission sites, no new DAO, no schema change.
- No behaviour change for non-life-safety Safety hazards (HIGH / MEDIUM — HIGH_CO2,
  HIGH_TVOC, HUMIDITY, OVERHEAT, FREEZE_RISK, WATER_LEAK) at the ALERTING / cooldown /
  repeat machinery (they never enter ALERTING). D1 only affects their boot-settle,
  DND, mute, and token-bucket classification (B2-B5), which is the pre-existing
  non-life-safety treatment.
- Not re-opening SAFETY-HAZARD-NEVER-CLEARS-1 — treat its machinery
  (`_hazard_clear_pending`, `_sweep_hazard_clears`, `HAZARD_MIN_HOLD_S`,
  `_record_sensor_recovery/_relapse`) as a stable primitive to be read.
- **Not fixing** `security.py:825-828` (`"intrusion"` vs `"intruder"` token mismatch —
  F4). Separately carded as **`SECURITY-REFIRE-INTRUSION-KEY-1`**.
- **Not** applying D5 to coordinators other than Safety. The pattern is adoptable
  (same predicate, same fail-open), but the token-mismatch gap means security would
  no-op in the "still active" branch today. Deferred to the sibling card.

## 7. Knobs on the ladder

Rule: "Numbers get knobs". New numbers introduced here: **none**. Reused numbers and
their rung:

| Number | Rung | Home | Why |
|---|---|---|---|
| `HAZARD_MIN_HOLD_S = 300` | 1 (module const in `safety.py`) | shipped v5.103.61 | Safety-semantics bound; recovery minimum. |
| `DEFAULT_NM_COOLDOWN_SMOKE/_CO = 2 min` | 2 (options flow) | `const.py` COOLDOWN_CONFIG | Operator-tunable paging cadence. |
| `DEFAULT_NM_COOLDOWN_FLOODING = 5 min` | 2 (options flow) | `const.py` COOLDOWN_CONFIG | Operator-tunable. |
| `NM_REPEAT_INTERVAL_LIFE_SAFETY = 30 s` | 1 (module const) | `const.py:3387` | Safety contract. Not operator-tunable by design. |

No new knob to defend.

## 8. Acceptance criteria (rewritten per F6 against real schema)

Real `notification_log` columns (`database.py:4440-4490`):
`id, timestamp, coordinator_id, severity, title, message, hazard_type, location,
person_id, channel, delivered, acknowledged, ack_time, cooldown_expires, dry_run,
recipient_id, route_reason, dnd_bypass_applied, bucket_outcome, matrix_branch`.

### D1 — hazard_type+location on NotificationAction
- **Verify (unit):** `NotificationAction` emitted by `_respond_to_hazard` has
  `hazard_type == hazard.type.value` and `location == hazard.location`.
- **Verify (DB row):** after a test fire, the latest `notification_log` row for
  `coordinator_id='safety'` has `hazard_type` and `location` non-NULL and equal to
  the raising sensor's location (not `""`).
- **Test:** T1, T6.
- **Live (DB, post-deploy):**
  ```sql
  SELECT id, timestamp, coordinator_id, hazard_type, location, severity
    FROM notification_log
   WHERE coordinator_id='safety'
     AND timestamp > datetime('now','-1 day')
   ORDER BY id DESC
   LIMIT 20;
  ```
  Zero rows with `hazard_type IS NULL OR hazard_type=''` after the next real or
  button-driven test hazard.

### D2 — is_hazard_active hold-aware
- **Verify (still-active):** mid-hazard, `safety.is_hazard_active("smoke", "<room>") is True`.
- **Verify (post-clear, hold elapsed):** 301 s after recovery, key popped,
  `is_hazard_active(...) is False`.
- **Verify (pending-clear discriminator):** 60 s after recovery while key still in
  `_hazard_clear_pending`, `is_hazard_active(...) is False`. Discriminated from the
  "cleared" case by inspecting `_active_hazards` membership (present during pending,
  absent after). Reviewers B/C validate both branches hit via mutation anchors in D3.
- **Verify (relapse via sensor path):** relapse through `_respond_to_hazard` →
  `is_hazard_active(...) is True`.
- **Test:** T2, T3, T4, T5.
- **Live (DB, ground truth per F6):** after the next real alert that recovers
  (post-ACK path):
  ```sql
  SELECT id, timestamp, hazard_type, location, acknowledged, ack_time,
         cooldown_expires
    FROM notification_log
   WHERE coordinator_id='safety' AND severity='critical'
     AND timestamp > datetime('now','-1 day')
   ORDER BY id DESC;
  ```
  Expect: exactly one row per real still-active life-safety event (the re-fire row
  carries the same `hazard_type` + `location` as the original and a later
  `timestamp`), and zero re-fire rows whose `hazard_type` was in
  `_hazard_clear_pending` at the time of cooldown expiry.
  Also scan the log for `nm:3042 "Hazard %s at %s still active after cooldown —
  re-firing"` as a secondary signal; the DB row is authoritative.

### D5 — unacked repeat loop stops on cleared (F2)
- **Verify (unit):** T8 — raise smoke, do not ACK, enter REPEATING, recover sensor,
  advance past hold expiry, assert `_alert_state == IDLE` and no further
  `notification_log` row.
- **Verify (fail-open):** T8-fail-open — predicate raises → re-page still fires.
- **Live (DB, ground truth):** after a smoke / CO test fire where no human acks:
  ```sql
  SELECT id, timestamp, hazard_type, location, acknowledged
    FROM notification_log
   WHERE coordinator_id='safety' AND severity='critical'
     AND hazard_type IN ('smoke','carbon_monoxide')
     AND timestamp > datetime('now','-1 hour')
   ORDER BY id ASC;
  ```
  Expect: a cluster of repeats at ~30 s cadence while the sensor is on, then **a
  final row within ~30 s of sensor recovery + 300 s hold expiry, and NO rows
  thereafter**. If rows continue past (recovery_ts + 330 s) → D5 regressed.

### D6 — deterministic flooding location (F7)
- **Verify (unit):** T9 — two set-insertion orders produce the same `location`.
- **Live:** on any multi-sensor flood, the `location` column alphabetises the room
  names (operator-visible via dashboard + DB).

### D3 — tests
- **Test:** all 10 functions (T1-T9 + T8-fail-open) PASS on build. Per-test
  mutation anchors in §5 D3; each bypass causes a specific test to fail.
- Fix-proving (RED on develop) subset: T1, T4, T6, T7, T7-neg, T8, T8-fail-open, T9.
- Regression guards (GREEN on develop): T2, T3, T5.

## 9. Review framings (Tier 2-DB, three framing-disjoint reviews)

- **A — data integrity + payload shape.** Every `NotificationAction` emission site in
  `safety.py` still well-formed? `notification_log` row shape unchanged (D1 adds no
  columns)? Any `Hazard` construction site missing `location` (would crash)? D6's
  `sorted(...)` round-trips through the DB cleanly?
- **B — migration correctness + signal chain integrity (both paths).** Full trace from
  `_respond_to_hazard` → `manager.py:1070` → `NM.async_notify` →
  (post-ACK path) `_cooldown_expired` → `_re_evaluate_hazard` → `is_hazard_active` →
  re-fire, AND (unacked path) `_enter_alerting` → `_schedule_repeat` → `_repeat_alert`
  → D5 predicate → either re-page or IDLE. Does the smoke/CO 2 min cooldown + 30 s
  repeat interact correctly with the 300 s clear hold at every reachable state
  (active, recovering mid-cooldown, relapsing mid-cooldown, cleared before cooldown
  fires, cleared during REPEATING, relapsing during REPEATING)? Enumerate every
  `is_hazard_active` reader (grep: `coordinator.is_hazard_active`, `self.is_hazard_active`)
  and confirm no caller depends on the pre-D2 behaviour. Confirm D5 preserves byte-
  identical behaviour for every non-Safety coordinator (`coord_id != "safety"` → skip
  path exercised by test).
- **C — new surfaces + test fixture authority.** Mutation-anchor every test in D3:
  delete the `hazard_type=` kwarg → T1 and T6 fail; revert D2 → T4 fails; revert D5
  → T8 fails; revert D5's try/except → T8-fail-open fails; revert D6 sorted → T9
  fails. Verify tests drive the real `_respond_to_hazard` / `_repeat_alert` /
  `async_acknowledge` paths, not stubs. Confirm T7 performs the ACK step.

**Life-safety discriminator (post-deploy):** per F6, the `notification_log` DB row is
the authoritative signal, not the log string. A sentinels-only log = payload-shape
failure.

## 10. Open questions

1. **Pending-clear discriminator ambiguity.** D2 reports both "already cleared" and
   "pending-clear hold running" as `is_hazard_active == False`. Operator-facing
   consequence: during the 300 s pending-clear window the NM re-fire gate sees
   "cleared" while the dashboard safety-alert entity still reads ON (deliberate,
   from v5.103.61 and reaffirmed by orchestrator ruling 2026-10-15 Q1). **Resolved
   as intended.**
2. ~~Non-life-safety re-fire.~~ **Withdrawn** — F1 established that non-CRITICAL
   hazards never enter the ALERTING / cooldown / repeat machinery at all, so D1
   cannot produce a non-life-safety re-fire. No per-type scoping needed in Safety.
3. **`fire` and `intruder` not emitted by Safety.** Reference only — these live in
   `NM_LIFE_SAFETY_HAZARDS` but are emitted by security, not safety. Verified by
   grep: no `HazardType.FIRE` production emission in `safety.py` (only the enum
   definition). No action. Security's `is_hazard_active` token-mismatch tracked
   under `SECURITY-REFIRE-INTRUSION-KEY-1` (F4 non-goal).

## 11. Orchestrator rulings on open questions (2026-10-15)

- **Q1:** YES. While a hazard's clear hold is pending with no raising sensor, the
  dashboard may read ON for up to 300 s while the NM re-fire gate reads cleared.
  This is the card's `constraint_2026_10_14`, and it avoids touching the shipped
  hold or the smoke/CO cooldown.
- **Q2 (Rev 2 revision):** Rev 2 § F1 established that non-CRITICAL hazards never
  reach ALERTING, so there is no "re-fire of comfort hazards" to scope. The Rev 1
  ruling ("verify NM policy doesn't re-page MEDIUM comfort") is moot. The only
  policy flips D1 causes are the eight B1-B8 behaviours tabled in §5 D1, all tagged
  intended. No change to NM's re-fire policy.
- **Q3:** noted; no action in this cycle; carded as `SECURITY-REFIRE-INTRUSION-KEY-1`.

---

### Rev 2 changelog
- Added §0 Review-resolution table (F1-F7).
- §1 invariant rewritten: domain narrowed to `{smoke, carbon_monoxide, flooding}`
  (F3); both post-ACK and unacked REPEATING paths covered (F2); fail-open clause 5
  added.
- §2 institutional context expanded with the F1 blast-radius sites and the D5
  precedent at `notification_manager.py:3034-3039`.
- §5 D1 blast radius rewritten as a per-site table (F1); the wrong "300 s comfort
  re-fire" claim removed.
- §5 D3 rewritten as 10 named tests classified R / F; T7 adds the ACK step (F5).
- §5 D5 added (F2 fix: Safety-scoped stop-on-clear in `_repeat_alert`, fail-open).
- §5 D6 added (F7 fix: deterministic flooding location).
- §6 non-goals expanded with F4 carding.
- §8 live queries rewritten against the real `notification_log` DDL (F6).
- §9 review framings updated to cover both paths and D5/D6 anchors.
- §10 Q2 withdrawn; §11 Q2 updated accordingly.
