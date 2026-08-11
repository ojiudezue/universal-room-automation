# PLANNING — FAN-MANUAL-1: Manual-ON hold for URA fans

**Card:** FAN-MANUAL-1 (`docs/planning/kanban.data.yaml:838`)
**Origin:** operator 2026-08-10 — "URA fans don't have manual override? … I can't seem to turn on the living room fan manually without it turning off by itself."
**Sibling (linked, not merged):** ARREST-COMFORT-1 (thermostat side of the same "system overrules the human" class).
**Author:** ura-planner (dispatched from orchestrator)
**Status:** planned; awaiting operator ruling on the two policy questions in §7 before build.

---

## 1. Falsifiable invariant (up front)

> **INV-FMH (Fan Manual Hold):** for `fan_manual_on_hold_s` seconds after URA
> detects an external (non-URA) ON transition on a room's fan(s), **no URA
> code path shall emit `SERVICE_TURN_OFF` against those fans** except for
> the four discharge conditions enumerated in §5.3. In particular,
> `handle_temperature_based_fan_control` shall NOT emit the "Fans off (below
> threshold, N°F)" call while the hold is live.

D-framing (§8, Review D) enumerates the entire OFF-emitting surface and
mutates each site to prove it is gated by the hold predicate. A site whose
mutation leaves the invariant test green is an untested site.

---

## 2. Institutional context verified

### 2.1 Greps run + verdicts per proposed addition

| Proposal | Verdict | Evidence |
|---|---|---|
| Manual-ON detection primitive | **REUSED** the exact shape of the manual-OFF cooldown | `automation.py:1657-1722` (`_last_seen_any_fan_on`, `_fan_off_issued_this_tick`, `_fan_manual_off_until`). Mirror it for ON — do NOT invent a second detection mechanism (would fork policy → known bug class). |
| Room-tier `_fan_manual_on_until` field | **NEW** (no equivalent) | Grep of `automation.py`: only `_fan_manual_off_until`. HVAC tier has a partial equivalent via overloaded `manual_off_cooldown_until` (see 2.2 below) — do not extend that overload. |
| `is_fan_in_manual_on_hold()` accessor (room) | **NEW**, symmetric to `is_fan_in_manual_cooldown()` at `automation.py:294` | Consumed by reconciler and by sleep-onset gate mirror. |
| Reconciler defer on manual-ON hold | **REUSED** the exact pattern from `actuator_reconciler.py:784-795` | Add a second `is_fan_in_manual_on_hold()` clause next to the existing manual-off clause. |
| HVAC-tier field `manual_on_hold_until` on `RoomFanState` | **NEW** as a distinct field | `hvac_fans.py:311-368` already adopts externally-lit fans and abuses `manual_off_cooldown_until` as an ON-side marker (see the comment at `hvac_fans.py:788` — "sets manual_off_cooldown_until on an is_on=True fan as a marker"). This overload is confusing and downstream code (`hvac_fans.py:1401`) filters on it as an OFF-side signal. Split into a purpose-named field; keep the OFF field OFF-only. |
| `CONF_FAN_MANUAL_ON_HOLD_S` / `DEFAULT_FAN_MANUAL_ON_HOLD_S` | **NEW** module constant, mirroring `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S = 3600` at `const.py:562` | Same rung (module constant — safety-adjacent, tunable via reviewed code change, kill switch at 0). Argued in §6. |
| Sleep-onset hold check | **REUSED** the `is_fan_in_manual_cooldown()` gate site pattern at `automation.py:2479-2488` | Add a sibling check for manual-ON hold (with the policy question in §7.1). |
| Comfort-fan AWAY veto interaction | **REUSED**, no change required | `fan_veto.py:386-450` only vetoes `turn_on` under AWAY/VACATION. The hold protects an already-on fan from being turned OFF, so the veto is orthogonal — see §4 loop analysis for the safety carve-out. |
| Humidity-fan carve-out | **REUSED**, no code change | v5.6.0 humidity fans are managed by `_humidity_gate.py` / bathroom exhaust unification and are sole-owner exempt from the veto. They are not driven by `handle_temperature_based_fan_control` and therefore are not subject to the "below threshold" revert. **INV-FMH does not apply to them.** Explicit non-goal (§3.2). |
| Duty-cycle `fan_assist` (coast) | **REUSED**, no change | `hvac_fans.py:226-228` — `fan_assist` only elevates fan trust in coast mode; it does not emit OFFs. Non-interacting. |

### 2.2 Prior planning docs consulted

- `docs/planning/PLANNING_fan_manual_off_cooldown.md` (referenced at `automation.py:267`) — the one-directional precedent. Read the FIX C D1/D2/D3 comments in `automation.py:1657-1722` and `hvac_fans.py:270-368` as the on-the-ground record.
- `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md` — humidity-fan sole-owner contract; establishes that humidity fans are OUT of scope for INV-FMH.
- v5.40.0 D3 comfort-fan AWAY veto planning (in-tree via `fan_veto.py` header + `CONF_COMFORT_FAN_AWAY_VETO_ENABLED`) — establishes AWAY veto is turn-on-only; a manual-ON hold on an already-on fan is orthogonal.
- `feature/sleep-fans-and-flash` (referenced at `automation.py:281-292`, `hvac_fans.py:219-254`) — sleep-onset one-shot; the manual-ON hold must interact with `SLEEP_FAN_ON_REARM_S` and the running-fans-untouchable contract at `automation.py:2489-2496`.
- ARREST-COMFORT-1 (`kanban.data.yaml:694-735`) — sibling; graduated concession machinery. See §6.5 for the marginal-benefit argument that fans should NOT reuse it.

### 2.3 Memory bodies pulled

- `feedback_suppression_needs_discharge.md` — every grace/deferral MUST specify the events that re-fire the suppressed action + a backstop + restart behavior. Drives §5.3 discharge table.
- `feedback_no_fabrication.md` — the HVAC-tier "adopt externally-lit fan" branch at `hvac_fans.py:302-368` is easy to describe wrong; the plan cites file:line and treats the current overload as a defect to unwind.
- `feedback_marginal_benefit_pushback.md` — drives the recommendation in §6.5 to ship the plain timed hold and PARK the concession pattern.
- `feedback_hollow_test_anchors.md` — every site listed in §5.5 must be mutation-verified per Tier 2-DB/Tier 3 Reviewer-C protocol; a suite-green mutation is a fail.

### 2.4 Design docs read

No dedicated `docs/Coordinator/HVAC.md` fan section exists; the on-file `hvac_fans.py:1-100` docstring plus the FIX C comment blocks are the authoritative design record. If this cycle ships, add a "Fan manual override contract" subsection to the HVAC coordinator design doc post-deploy (deliverable D6).

### 2.5 Code locations surveyed end-to-end

- `automation.py:260-310` (state fields + accessors), `automation.py:1599-1830` (`handle_temperature_based_fan_control` — the bug site), `automation.py:2440-2510` (sleep-onset gate).
- `hvac_fans.py:180-370` (`update` loop, external-off detect, external-on adopt with the ON-marker overload), `hvac_fans.py:580-600` (evaluate path cooldown read), `hvac_fans.py:780-800` (adopt-fan speed read), `hvac_fans.py:1272` ("does NOT trip manual_off_cooldown_until") and `hvac_fans.py:1395-1405` (cooldown filter for diagnostics).
- `actuator_reconciler.py:780-800` (defer on room-tier manual cooldown — insertion point for manual-ON hold defer).
- `fan_veto.py:1-100, 380-460` (AWAY veto scope — turn_on only, orthogonal to hold).
- `presence_fan_recheck.py:79, 260-290, 580-680, 770+` (pause/restore machinery + `STATE_PAUSED` + `force_restore`).
- `const.py:562, 771, 870-880` (`DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S`, `CONF_FAN_VACANCY_HOLD`, `FAN_TRUST_STATES`).

---

## 3. Scope

### 3.1 In scope

Comfort fans (room-owned via `handle_temperature_based_fan_control` AND HVAC-managed via `hvac_fans.FanController.update`) that are subject to a URA-emitted `SERVICE_TURN_OFF` in response to temperature, vacancy, or sleep policy. The Living Room bug (room-tier temperature revert) is the primary defect; the HVAC-tier ON-marker overload is a latent bug of the same class and is fixed in the same cycle to prevent a re-emergence via a different site.

### 3.2 Explicit non-goals

- **Humidity-driven bathroom exhausts** (v5.6.0 sole-owner) — driven by `_humidity_gate`, not by comfort. INV-FMH does not apply.
- **Safety-driven emissions** (smoke, indoor humidity emergency, freeze protection) — MUST always override the hold. See §5.3 discharge condition (d).
- **Comfort-fan AWAY veto** (`fan_veto.py`) — turn-on-only; not an OFF-emitter. No change.
- **`fan_assist` coast constraint** — not an OFF-emitter.
- **Manual-OFF cooldown** — already shipped in v5.31.0; kept as-is. This cycle only ADDS the symmetric ON side and cleans up the HVAC-tier field overload it introduced.

### 3.3 The two carve-outs to be argued (§7 operator ruling)

- **FAN_SLEEP_OFF policy vs. fresh manual-ON.** The freshest human instruction usually wins; but FAN_SLEEP_OFF is itself an explicit standing instruction. See §7.1.
- **Fan-recheck pause interaction.** A manually-held fan must still be pauseable by `presence_fan_recheck` (otherwise recheck cannot test), and the restore must re-honor the hold if the operator wasn't the one who paused it. See §7.2.

---

## 4. Fan-interference feedback-loop analysis (the important one)

Presence trust reads fan state as a nuisance-signal input (fan-noise interference gate). A manually-held fan changes those inputs. Analysis by loop segment:

1. **Room-local:** occupancy pipeline discounts PIR/mmWave while a fan runs in the same room. Extending fan-on runtime by up to `fan_manual_on_hold_s` extends that discount window. In the occupied case, this is the *point* — the hold exists because a human said they want the fan on. Blast radius: zero.
2. **Vacancy-then-hold:** occupant leaves during hold. Fan-noise discount persists in an empty room. The eventual OFF driver (vacancy sweep or comfort revert) is gated by the hold, so the room can present as "fan on, presence noisy" for the remainder of the window. This is BOUNDED (`fan_manual_on_hold_s`; default 3600 s) and self-heals at expiry. Acceptable given a knob.
3. **Fan-recheck contradiction:** `presence_fan_recheck._enter_paused` (line 582) actively turns fans OFF to test whether occupancy readings are fan-induced. If the hold blocks this OFF, recheck cannot run and the fan-noise gate stays permanently on for the held window — a functional regression in the recheck substrate. **Design decision (§7.2 operator ruling):** recheck's `_enter_paused` OFF is an ALLOWED emission (special-cased via a `trigger_path` allowlist read by the hold predicate, mirroring how `hvac_fans._set_fan_state` already carries `trigger_path="turn_off_all_managed"` at line 196). On `_restore`, if the hold is still live, restore the fan (recheck's normal behavior); if the operator canceled during the pause, honor the cancel.
4. **Cross-room:** presence trust is per-room; no cross-room amplification via fan-noise. Confirmed by re-reading `fan_veto._get_house_state` and the veto invocation sites — they read fan STATE, not "how long fan has been on."
5. **Sleep-onset re-arm interaction:** if the hold is active when the house crosses into sleep, the sleep-onset one-shot latch at `automation.py:2489-2496` already skips when a fan is on (running-fans-untouchable contract). No new interaction — the hold is compatible with the existing sleep-onset skip.

**Loop verdict:** the hold DOES prolong an already-benign coupling (fan-on → PIR discount). It creates ONE genuine contradiction (fan-recheck), which is resolved by making recheck's OFF an allowlisted emission with hold-aware restore.

---

## 5. Design

### 5.1 Manual-ON detection (mirror of the OFF detector)

At each entry to `handle_temperature_based_fan_control` (and its HVAC-tier sibling in `FanController.update`), BEFORE any actuation:

```
prev_any_on = self._last_seen_any_fan_on
curr_any_on = any(state==on for f in fans)
we_issued_on_this_tick = self._fan_on_issued_this_tick   # NEW mirror flag
if (not prev_any_on) and curr_any_on and (not we_issued_on_this_tick):
    if self._fan_manual_on_until is None:
        open manual-ON hold: self._fan_manual_on_until = now + fan_manual_on_hold_s
        clear _fan_vacancy_start (symmetric to the OFF-open path at line 1684)
        log INFO "Room X: fan turned on externally — manual-ON hold until Y"
```

The detection consumes the EXACT existing baseline (`_last_seen_any_fan_on`) and adds ONE new mirror flag (`_fan_on_issued_this_tick`). No second manual-detection path.

Ownership boundary: `_fan_on_issued_this_tick` is set True by every path in `automation.py` that calls `SERVICE_TURN_ON` on `fans` (grep target list in §5.5), and cleared at the top of `handle_temperature_based_fan_control` (mirror of line 1665).

### 5.2 Consumer sites (the OFF-emitters that must gate on the hold)

Enumerated from grep of `SERVICE_TURN_OFF` + `turn_off_all_managed` + `_set_fan_state(...False...)` across the fan surface:

| # | Site | File:line | Emission | Gate |
|---|---|---|---|---|
| 1 | Temperature-below-threshold revert | `automation.py:1801-1809` | `SERVICE_TURN_OFF` | **Gate on hold** — the bug site |
| 2 | Vacancy revert (same branch, `not occupied`) | `automation.py:1801-1809` | `SERVICE_TURN_OFF` | **Gate on hold** — with the understanding that hold survives vacancy for its window; sweep resumes at expiry (backstop) |
| 3 | Sleep policy FAN_SLEEP_OFF | `automation.py:1729-1736` | `SERVICE_TURN_OFF` | **Policy question §7.1** |
| 4 | HVAC-tier vacancy/temp OFF via `_set_fan_state` | `hvac_fans.py` (via `_evaluate_temp_fan`) | `_set_fan_state(..., False)` | **Gate on hold** at the `_set_fan_state` boundary (single chokepoint — verify by grep it is the sole HVAC-tier OFF path aside from `turn_off_all_managed`) |
| 5 | `turn_off_all_managed` (fan_control_enabled toggled off) | `hvac_fans.py:186-203` | mass OFF | **Not gated** — this is an operator kill switch; hold cleared as part of reset (already zeros `manual_off_cooldown_until` at line 203; add `manual_on_hold_until` to the reset) |
| 6 | Fan-recheck `_enter_paused` OFF | `presence_fan_recheck.py:582` | OFF via injected fan-writer | **Allowlisted** via `trigger_path` — see §4.3 |
| 7 | AI-rules executor R2 residual (`fan.turn_on` unvetoed) | referenced in card scope note | turn-ON path, NOT OFF | Out of scope for INV-FMH (that residual is an ON-emitter without veto — a DIFFERENT defect, tracked separately) |
| 8 | Comfort-fan AWAY veto | `fan_veto.py` | turn-ON gate | Not an OFF-emitter |

**Discharge/backstop wiring: see §5.3.**

### 5.3 Discharge table (per feedback_suppression_needs_discharge.md)

| Condition | Effect | Rationale |
|---|---|---|
| (a) Hold timer expires (`now >= _fan_manual_on_until`) | Clear hold; next tick evaluates normally | Bounded runtime; backstop against forgotten holds |
| (b) External OFF detected (operator turns fan off) | Clear hold immediately; open manual-OFF cooldown per existing v5.31.0 path | Freshest human instruction wins; mirrors line 1691-1706 cancel-reversal shape |
| (c) URA-owned OFF via allowlisted `trigger_path` (fan-recheck, `turn_off_all_managed`) | Do NOT clear hold; recheck restore re-honors hold if still live | §4.3 loop analysis |
| (d) Safety event (smoke, freeze protection, indoor humidity emergency) | Override hold; log "safety override of manual-ON hold" | Safety > policy > preference. Emit an activity_log entry so the operator sees why their fan went off |
| (e) `fan_control_enabled` toggled OFF (operator kill switch) | Clear hold as part of `turn_off_all_managed` reset | Global disable is a superset instruction |

**Restart behavior:** hold is RAM-only. Argument: (i) HA restarts are not a common comfort event; (ii) persisting via RestoreEntity introduces the boot-transient-poisoning class we hit in the v5.31.0 vacancy-hold fix-up (see `automation.py:1740-1766` comment block); (iii) if the operator turned the fan on 30 minutes before an unrelated restart, the fan will re-adopt as externally-lit on the first post-boot tick (HVAC tier already does this at `hvac_fans.py:302-368` after this cycle's fix, and the room tier gets the symmetric adopt path in D2) — which re-opens the hold fresh from that boot. Deliberate simplicity; log the boot-adopt as INFO so the reset is visible.

### 5.4 HVAC-tier field-overload cleanup

`hvac_fans.py` currently sets `manual_off_cooldown_until` on an `is_on=True` fan as a manual-ON marker (line 361-363; comment at line 788). Split:

- `manual_off_cooldown_until` — OFF-only marker (existing semantics preserved).
- `manual_on_hold_until` — NEW field on `RoomFanState`. Written by the external-adopt branch (currently at lines 349-363) and by the mirror of §5.1 detection in `FanController.update`.

Migration: NONE required (RAM-only field on an in-memory dataclass; no persistence).

Callers to update: `hvac_fans.py:295-299` (reverse-clear branch — was clearing the overloaded field on turn-ON; that clear becomes a no-op and the new field is set instead), `hvac_fans.py:1395-1405` (diagnostic filter — verify it should now read from `manual_on_hold_until` for the ON-marker case).

### 5.5 Sites requiring per-site mutation verification (Reviewer C authority)

For Tier 3 (if elevated) or Tier 2-DB Reviewer C: mutate each site to bypass its hold gate individually and confirm a NAMED test fails.

1. `automation.py:1801-1809` — temperature/vacancy OFF: remove the hold check → `test_manual_on_hold_blocks_temp_revert` MUST fail.
2. `automation.py:1729-1736` — FAN_SLEEP_OFF OFF: per §7.1 outcome, either gate + test or leave + test-that-documents.
3. `hvac_fans.py` `_set_fan_state(..., False)` boundary — the HVAC chokepoint gate: mutate away → `test_hvac_tier_manual_on_hold_blocks_temp_off` MUST fail.
4. `actuator_reconciler.py:790-795` — remove the `is_fan_in_manual_on_hold()` clause → `test_reconciler_defers_on_manual_on_hold` MUST fail.
5. Field-split: mutate `manual_on_hold_until` writer back to overload `manual_off_cooldown_until` → `test_hvac_manual_on_hold_uses_dedicated_field` MUST fail.
6. External-detect predicate: force `_fan_on_issued_this_tick` always-True → `test_manual_on_hold_opens_on_external_on` MUST fail (URA-issued ON must NOT open a hold).

Aggregate monkeypatch of a shared helper is NOT sufficient (per `feedback_hollow_test_anchors.md`).

---

## 6. Numbers-Get-Knobs ladder

Per the operator-coined placement ladder (2026-07-16):

| Number | Value | Rung | Home | Why |
|---|---|---|---|---|
| `DEFAULT_FAN_MANUAL_ON_HOLD_S` | 3600 (1 h) | 1 — module constant | `const.py` next to `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S` | Safety-adjacent (governs whether a comfort revert can fire); should require reviewed code change to tune. Kill switch at 0 (identical semantics to the OFF-side kill switch). |
| Per-room override `CONF_FAN_MANUAL_ON_HOLD_S` | unset → default | 2 — config/options flow | `config_flow.py` room step alongside `CONF_FAN_VACANCY_HOLD` | Advanced-user knob; per-room because the Living Room's tolerance differs from a bedroom's. Ships in D4. |
| Live-tunable number entity | DEFERRED | 3 — Number entity | not this cycle | Marginal-benefit: the operator's mental model of "how long should my manual override last" is set-and-forget, not dashboard-tunable. Revisit only if operators report they retune it monthly. |

**Kill switch semantics:** `DEFAULT_FAN_MANUAL_ON_HOLD_S = 0` disables the entire feature at the module constant. Documented on the const, mirrored on the per-room CONF (empty/0 = fall through to default; explicit 0 in per-room = feature disabled for that room).

### 6.5 Marginal-benefit decomposition (fans vs. concession machinery)

The ARREST-COMFORT-1 sibling design carries a graduated-concession pattern (grant 76°F for 15 min → step to 78°F for 15 min, monitoring approach). Should FAN-MANUAL-1 share it?

**Decompose the benefit:**
- Plain timed hold captures: "I turned my fan on and it stayed on." That is the entire operator complaint. ~100% of the observed value.
- Concession machinery would add: after N minutes, negotiate the fan back off. Marginal benefit ≈ 0 — a fan is binary comfort. There is no setpoint to negotiate toward; you cannot "step" between ON and OFF meaningfully. The fan is either providing the comfort the operator asked for, or it is not.

**Price the marginal risk:** concession machinery would introduce approach-speed monitoring + step timing + graduated state on a room-tier struct, tripling the state-machine surface. Rare-fire paths + config combinatorics for essentially zero comfort win.

**Recommend:** plain timed hold. **Park** the concession pattern here; revisit only if operator reports (evidence trigger) that a 60-min hold expires too abruptly and they'd prefer a graduated wind-down.

---

## 7. Operator rulings needed BEFORE build

### 7.1 FAN_SLEEP_OFF vs. fresh manual-ON

`CONF_FAN_SLEEP_POLICY=off` is an explicit standing instruction ("no comfort fans in this bedroom during sleep window"). A manual-ON at 02:30 is a fresh, contradictory instruction. Options:

- **A. Freshest wins.** Manual-ON hold overrides FAN_SLEEP_OFF for its window. Matches "system overrules the human" avoidance; matches the manual-OFF cooldown at `automation.py:2479-2488` which respects a fresh manual-OFF over the sleep-onset activation.
- **B. Policy wins.** FAN_SLEEP_OFF holds; the manual-ON is reverted. Preserves the explicit-policy contract; consistent with "operator set this deliberately weeks ago."
- **C. Freshest wins but reduced-speed.** Honor the manual-ON but at `FAN_SLEEP_REDUCE` speed cap (33%) — a middle path.

**Planner recommendation: A.** The manual-OFF cooldown precedent already treats a fresh manual act as authoritative over standing policy (sleep-onset skip). Symmetry argues A. But this is a comfort/policy call, not a technical one — flagging for explicit operator ruling.

### 7.2 Fan-recheck pause: allowlist vs. block

Recheck cannot function without pausing fans (it exists to disambiguate fan-noise-induced PIR from real occupancy). Options:

- **A. Allowlist recheck's OFF via `trigger_path`.** Hold is not cleared; recheck's `_restore` re-arms the fan and the hold continues from where it paused (or the remaining window; specify which).
- **B. Cancel the hold on recheck pause.** Simpler; but recheck can pause at any time, so the hold becomes unreliable ("why did my fan stop after 8 minutes?").

**Planner recommendation: A**, with the hold's remaining time preserved across the pause (subtract paused duration from the deadline). Recheck's whole purpose is a brief test; the operator's intent shouldn't be canceled by a diagnostic.

---

## 8. Tier classification (argued)

**Tier: 2-DB (three framing-disjoint reviews). Argued elevation to Tier 3 if operator flags delicate.**

Justification:
- Cross-coordinator ripple: room automation ↔ HVAC fan controller ↔ actuator reconciler ↔ presence fan-recheck ↔ sleep-onset. Five surfaces.
- The v5.31.0 manual-OFF sibling cycle needed multiple fix-ups (see the `A-M1 fix-up` and `hotfix/fan-sweep-trio` comments in `automation.py:1679-1706` and `hvac_fans.py:353-368`). Same shape of change, same ripple → assume the same review depth is warranted.
- Field-split on `RoomFanState.manual_off_cooldown_until` is a rename/semantic-split of a value consumed by ≥3 sites in `hvac_fans.py` (evaluate, adopt, diagnostic filter). Bug-class #22 (enum mismatch) territory if a reader is missed.
- Regression-prone per the operator's 2026-06-08 standing policy: this is a trust-hierarchy change (human intent vs. automation).

**Reviewer framings (framing-disjoint):**

- **Review A — Correctness + edge cases.** Per-site: does the hold predicate fire when it should and only when it should? Cold-boot behavior. External-off during hold. External-on-off-on flap. Speed-change (dimmer to 50%) during hold — is that an "external ON" event or a no-op? Cite site by file:line.
- **Review B — Cross-coordinator + no-flap + lifecycle.** Recheck pause/restore across a hold. HVAC-tier field split: are all readers of `manual_off_cooldown_until` still correct after the split? Reconciler defer ordering vs. HVAC-managed defer. Sleep-onset re-arm window interaction. Restart adopt path.
- **Review C — Test authority via per-site source mutation.** Each of the six sites in §5.5 mutated individually; confirm a NAMED test fails on each; restore. Aggregate monkeypatch is NOT accepted per `feedback_hollow_test_anchors.md`.

If operator elevates to Tier 3:
- **Review D — Adversarial completeness / diff-blind.** Enumerate every URA path that emits `SERVICE_TURN_OFF` against a fan entity, including pre-existing code paths outside the diff (mirror of v5.5.3 D-HIGH-1 discovery). State INV-FMH in falsifiable form. Provide a concrete legal-config reachable repro for any leak.

---

## 9. Deliverables + acceptance criteria

### D1 — Room-tier manual-ON detection + hold state

**Files:** `automation.py` (add `_fan_manual_on_until`, `_fan_on_issued_this_tick`, `is_fan_in_manual_on_hold()` accessor; wire the detection block into `handle_temperature_based_fan_control` symmetric to lines 1657-1722).
**Constants:** `const.py` — add `DEFAULT_FAN_MANUAL_ON_HOLD_S = 3600`, `CONF_FAN_MANUAL_ON_HOLD_S = "fan_manual_on_hold_s"`.

Acceptance criteria:
- **Verify:** flipping the Living Room fan ON via HA UI while `room_temp < effective_threshold` does NOT produce a "Fans off (below threshold)" activity log entry within `fan_manual_on_hold_s`.
- **Verify:** URA-issued ON (sleep-onset or reconciler) does NOT open a hold — `_fan_on_issued_this_tick` guard.
- **Test:** `test_manual_on_hold_opens_on_external_on`, `test_manual_on_hold_blocks_temp_revert`, `test_manual_on_hold_not_opened_by_ura_on`, `test_manual_on_hold_expires_after_window`, `test_external_off_during_hold_cancels_and_opens_off_cooldown`.
- **Live:** post-restart, manually turn on the Living Room fan when the room is 75°F. Confirm the fan stays on for 60 min and the activity log carries no `[room/fan_off] "Fans off (below threshold, 75°F)"` entry until the hold window closes.

### D2 — HVAC-tier mirror + field-overload cleanup

**Files:** `hvac_fans.py` — add `RoomFanState.manual_on_hold_until` (dataclass field, default `""`); write it from the external-adopt branch at lines 349-363 (replacing the overloaded `manual_off_cooldown_until = ...` write on an `is_on=True` fan); gate `_set_fan_state(..., False)` on the hold at its single chokepoint; update the reverse-clear branch at lines 295-299 to write the new field; audit the diagnostic filter at lines 1395-1405.

Acceptance criteria:
- **Verify:** `grep 'manual_off_cooldown_until' hvac_fans.py` — every remaining write is on an `is_on=False` fan (OFF-only semantic restored).
- **Verify:** `manual_on_hold_until` is written by exactly two paths (external-adopt + FanController's own mirror of §5.1 detection).
- **Test:** `test_hvac_manual_on_hold_uses_dedicated_field`, `test_hvac_tier_manual_on_hold_blocks_temp_off`, `test_hvac_manual_off_field_off_only_after_split`.
- **Live:** HVAC-managed bedroom fan turned on externally at 74°F — no HVAC-tier OFF for the hold window; the log line reads "manual_on_hold_until=..." not "cooldown=..." for the ON case.

### D3 — Reconciler defer + fan-recheck allowlist

**Files:** `actuator_reconciler.py:790` — add second defer clause `is_fan_in_manual_on_hold()`. `presence_fan_recheck.py` — extend the pause OFF-write path with a `trigger_path="fan_recheck_pause"` marker; the hold-open detector treats this trigger_path as a URA-owned OFF (does not clear hold; deadline pauses for the recheck window and resumes on restore).

Acceptance criteria:
- **Verify:** reconciler emits no ON write against a fan under manual-ON hold (mirrors the existing manual-OFF defer).
- **Verify:** fan-recheck can still pause a held fan and restore it; hold deadline is extended by paused duration.
- **Test:** `test_reconciler_defers_on_manual_on_hold`, `test_fan_recheck_pause_preserves_manual_on_hold`, `test_fan_recheck_restore_rearms_held_fan`.
- **Live:** trigger a fan-recheck on the Living Room fan while a hold is live. Confirm the fan pauses briefly, then restores; the hold continues to block the comfort revert past the recheck window.

### D4 — Config-flow per-room override

**Files:** `config_flow.py`, `options_flow.py`, `strings.json`, `translations/en.json`.

Acceptance criteria:
- **Verify:** room options flow shows a "Fan manual-ON hold (seconds)" field alongside "Fan vacancy hold".
- **Test:** `test_config_flow_manual_on_hold_field_round_trips`.
- **Live:** set Living Room's per-room override to 1800 s; confirm subsequent manual-ON honors the shorter window.

### D5 — Sleep-onset gate mirror (pending §7.1 ruling)

**Files:** `automation.py:2479-2488` — add sibling `is_fan_in_manual_on_hold()` check per operator ruling on §7.1.
Acceptance criteria depend on the ruling; not spec'd here to avoid pre-committing.

### D6 — Design-doc write-back (post-deploy)

**Files:** `docs/Coordinator/HVAC.md` — add "Fan manual override contract" subsection documenting the OFF cooldown (v5.31.0) + ON hold (this cycle) + the field split + the recheck allowlist. Also add the discharge table verbatim.

### D7 — README write-back (post-live-validation, mandatory per CLAUDE.md)

**Files:** `docs/readmes/README_v<version>.md` — replace prospective Live acceptance with observed results table. Cite `activity_log` entries (or absence thereof) as the authoritative signal for INV-FMH.

---

## 10. Test additions summary

- `test_manual_on_hold_opens_on_external_on`
- `test_manual_on_hold_not_opened_by_ura_on`
- `test_manual_on_hold_blocks_temp_revert` (INV-FMH primary)
- `test_manual_on_hold_expires_after_window`
- `test_external_off_during_hold_cancels_and_opens_off_cooldown`
- `test_hvac_manual_on_hold_uses_dedicated_field`
- `test_hvac_tier_manual_on_hold_blocks_temp_off`
- `test_hvac_manual_off_field_off_only_after_split`
- `test_reconciler_defers_on_manual_on_hold`
- `test_fan_recheck_pause_preserves_manual_on_hold`
- `test_fan_recheck_restore_rearms_held_fan`
- `test_config_flow_manual_on_hold_field_round_trips`
- `test_humidity_fan_not_subject_to_manual_on_hold` (explicit non-goal guard — humidity fans exempted)
- `test_safety_event_overrides_manual_on_hold` (discharge (d))
- `test_fan_control_disabled_clears_manual_on_hold` (discharge (e))

Each of these anchors ONE mutation in §5.5 or one discharge condition in §5.3. Reviewer C runs the mutation drill.

---

## 11. Sharpest risk

The **field-overload cleanup on `RoomFanState`** is the sharpest risk, not the new hold itself. The current `manual_off_cooldown_until` field is written on both `is_on=True` (ON marker; lines 361-363) and `is_on=False` (OFF cooldown; line 285) fans, and is read in at least three sites (`hvac_fans.py:295, 586, 1395`). Splitting semantics is a semantic-migration change of exactly the class that produced 6 CRITICAL findings on the first pass in v4.6.3 (why Tier 2-DB exists). If any reader is missed — for example the diagnostic filter at line 1395 that today counts a mixed population — we ship a diagnostic regression that masks the very bug this cycle is trying to prevent. Review B MUST enumerate every reader of `manual_off_cooldown_until` and confirm each is either correct under the new OFF-only semantic or migrated to `manual_on_hold_until`.

Secondary risk: the sleep-onset FAN_SLEEP_OFF interaction (§7.1). Whichever policy wins, an occupant will occasionally be surprised. The plan defers that call to the operator rather than smuggling it into a technical decision.

---

## 12. Plan completion tracking

Items deliberately NOT in this cycle:

- **AI-rules executor R2 residual** (`fan.turn_on` unvetoed). This is an ON-emitter defect, not an OFF-emitter defect. Different failure class from INV-FMH. Tracked in the card scope note; a separate cycle should apply the comfort-fan AWAY veto to the AI-rules ON path.
- **Live-tunable Number entity for `fan_manual_on_hold_s`** (Numbers-Get-Knobs rung 3). Parked per §6.5 marginal-benefit argument. Revisit if operator retunes ≥ monthly.
- **Persistence of the hold across HA restarts.** Parked per §5.3 restart-behavior argument. Revisit if restart-adopt proves unreliable in practice.
- **Graduated-concession machinery.** Parked per §6.5. Revisit if the plain timed hold proves too abrupt.
- **Design doc write-back to a dedicated `docs/Coordinator/HVAC.md` fan section** (D6). Written post-live-validation; if deferred, tracked as a follow-up ticket referencing this planning doc.
