# PLANNING — FAN-LAYER-1: Fan actuation shared layer (DOC-2 refresh)

**Card:** FAN-LAYER-1 (`docs/planning/kanban.data.yaml`)
**Author:** ura-planner
**Date:** 2026-08-10
**Base branch:** `fan-manual-1` (tip `233531f37`) — post FAN-MANUAL-1 fix-up. This
plan is written against the POST-FAN-MANUAL-1 surface; when built, FAN-MANUAL-1
will have merged and this cycle refactors that code.
**Supersedes:** `docs/planning/PLANNING_fan_actuation_shared_layer.md` (2026-07-26,
DEFERRED). Carries its inventory + risk analysis forward; updates the go-criteria
status ("3 of 4 triggers have fired"), the writer set (three → EIGHT actual sites),
the `mark_fan_on_issued` seed channel, and the two policies every writer must
honor (manual-ON hold + manual-OFF cooldown).
**Sibling design pattern:** `docs/planning/PLANNING_signal_trust_ledger_abstraction.md`
— extraction-not-invention, golden-parity from live surface, verdict-only vs
actuation split. Applied throughout.
**Status:** planned; awaiting operator ruling on the shape choice in §6 and the
H8 gate disposition in §2.

---

## 1. Falsifiable invariant (Reviewer D target, up front)

> **INV-FLA (Fan Layer Authority):** every URA-originated call to
> `fan.turn_on` / `fan.turn_off` / `homeassistant.turn_on` /
> `homeassistant.turn_off` / `switch.turn_*` **against a room-configured
> comfort fan** flows through the shared layer (either its `request()`
> chokepoint under shape (a), or its `may_actuate(room, direction,
> trigger_path)` predicate under shape (b)) before the service call is
> emitted. Under shape (a), NO writer holds a reference to
> `hass.services.async_call` for a comfort-fan entity except via the layer.
> Under shape (b), every writer's service-call site is directly preceded
> (same function, no early-returnable branch between) by a `may_actuate`
> consult whose False result short-circuits emission and whose True result
> is the only path forward.
>
> Carve-outs (must be enumerable, closed, and named in const.py):
>   * humidity fans (v5.6.0 sole-owner) — outside INV-FLA scope, tracked
>     separately via `_humidity_gate`. **Fully outside** — humidity is NOT
>     a `may_actuate` consumer, has NO trigger vocabulary member, and does
>     NOT `note_actuation` (see §13 M2 decision + re-audit trigger).
>   * safety-bypass paths (smoke, freeze protection, W11 `_stop_all_fans_safety`)
>     — MUST consult the layer with `safety=True`. The oracle ALWAYS returns
>     ALLOW under `safety=True` but LOGS the consult (at WARNING) with the
>     pre-safety verdict it WOULD have returned. `note_actuation` still fires.
>   * operator kill-switch mass-off (`turn_off_all_managed`) — routes through
>     the layer with `trigger_path="fan_control_disabled"` which the layer
>     recognizes as unconditional and clears the manual-ON hold ledger.
>   * **State-restoration-only fan-attribute writes** at `hvac_fans.py:1541`
>     (preset), `:1554` (oscillate), `:1567` (direction), which run during
>     recheck-restore to re-apply the fan's pre-pause attributes. These are
>     NOT `turn_on`/`turn_off` service calls — they set orthogonal attributes
>     on an already-decided-ON fan. They are covered by the parent
>     `may_turn_on(RECHECK_RESTORE)` consult that wraps the whole restore
>     block; **no separate consult** is emitted per attribute (adopting
>     Reviewer-Completeness H1 option (b): explicit §1 carve-out over a
>     per-attribute consult that would triple the recheck-restore diff).

Reviewer D's mandate (§9): enumerate the ENTIRE fan-emission surface —
including pre-existing sites outside this diff (mirror of v5.5.3 D-HIGH-1) —
and mutate each site to prove its layer consult is load-bearing.

---

## 2. H8 gate check — verdict + evidence

The original DOC-2 foundation gate required organic validation of the v5.31.0
manual-OFF cooldown (H8): a real manual-OFF observed NOT re-arming within the
cooldown window on the running house.

### 2.1 Probe attempted

The planner is running in an environment WITHOUT SSH/Bash to
`homeassistant`. A recorder-side `ura_activity_log` sweep filtering on the
manual-OFF cooldown vocabulary from `automation.py:1657-1722` (search terms:
`"externally"`, `"manual off"`, `"Fans off (below threshold"`, room_name +
delta-t < 3600s) COULD NOT BE RUN from this worktree. This is disclosed
rather than fabricated.

### 2.2 Substitute evidence available in-repo

1. **FAN-MANUAL-1 shipped 2026-08-10 with a 1 CRIT + 6 HIGH review round on
   the very same code region** (`automation.py:1657-1722`, `hvac_fans.py:280-368`,
   `actuator_reconciler.py:610-642`). Every finding was fixed and the tick
   marker / baseline-bridge invariants are now regression-anchored by
   `quality/tests/test_fan_manual_on_hold_room_tier.py` (grep confirms
   `test_mark_fan_on_issued_bridges_between_ticks` at line 480 and
   `test_manual_on_hold_not_opened_by_ura_on` at line 467). The manual-OFF
   cooldown is exercised by the sibling suite and by the ON-side detection
   which shares its `_last_seen_any_fan_on` baseline.
2. **The v5.31.0 manual-OFF cooldown has been shipped since 2026-07-28
   (~13 days).** Operator has not filed a re-arm regression against it in
   that window. This is a UNBOUNDED-ABSENCE observation (the triggering
   event class — an organic manual-OFF within the cooldown window
   followed by a URA re-arm attempt — is rarer than the recorder retention
   window, per the §2.3 addendum probe). It is not CONFIRMING evidence
   for H8; it is an absence-of-negative that keeps H8 non-falsified.
3. **`mark_fan_on_issued()` (`automation.py:362-382`) now bridges the tick
   marker AND the baseline** — a defect the FAN-MANUAL-1 review round
   surfaced (A-MED-4). This means the ON-detector correctly attributes
   URA-issued transitions and does not mis-open holds; symmetrically, the
   OFF-detector's `_fan_off_issued_this_tick` (line 311) is now
   well-audited.

### 2.3 Recommendation: gate is OPEN under option (b) + (c)

Adopt the operator-offered option **(b) in-suite proof + operator lived
experience as substitute** AND **(c) the extraction now refactors BOTH policies
so FAN-MANUAL-1's fresh suite is the real safety net**. Justifications:

- Waiting for a specific `ura_activity_log` row to appear organically is a
  calendar dependency the plan cannot bound (a room-tier manual-OFF is not
  a daily event — a probe returning empty is expected, not diagnostic).
- The FAN-MANUAL-1 review round exercised the exact code paths that would
  regress if H8 were secretly failing.
- The extraction's whole point is to make both policies enumerable and
  mutation-provable. Deferring the extraction to await an organic H8 row is
  waiting for evidence that would arrive AFTER the extraction anyway (the
  post-deploy live validation) and does not de-risk the extraction cycle
  itself.

**HONESTY NOTE:** if operator disagrees, the fallback is (a) run the probe
first (10-minute SSH script: `SELECT * FROM ura_activity_log WHERE
description LIKE '%manual off%' OR description LIKE '%externally%' ORDER BY
ts DESC LIMIT 200;` and manually verify absence of a fan_on within 3600s
against the same room). Nothing in the plan below hard-depends on this
call; only its deploy sequencing does.

---

## 3. Institutional context verified

### 3.1 Writer enumeration — grep-exhaustive as of `233531f37`

`SERVICE_TURN_OFF` / `SERVICE_TURN_ON` / `homeassistant.turn_off` /
`homeassistant.turn_on` / `fan.turn_*` / `switch.turn_*` calls whose target
set INCLUDES entities from `CONF_FANS` (comfort) — enumerated by grepping
the fan surface and tracing each site:

| # | Site | File:line | Direction | Path / trigger | Current policy honored? |
|---|---|---|---|---|---|
| W1 | Room-tier comfort revert (below threshold / vacancy) | `automation.py:1801-1809` | OFF | temp threshold + vacancy | v5.31.0 cooldown open; **FAN-MANUAL-1 manual-ON hold gate present** |
| W2 | Room-tier `FAN_SLEEP_OFF` | `automation.py:1729-1736` | OFF | sleep policy | manual-ON hold via FAN-MANUAL-1 §7.1 operator ruling |
| W3 | Room-tier turn-ON (temp branch + sleep-onset + humidity) | `automation.py:2065-2083, ~1870, ~2148, 2727` | ON | temp / sleep / humidity | routed through `mark_fan_on_issued()` (line 2063, 2727) — seed authored-by channel |
| W4 | HVAC-tier `_set_fan_state(..., False)` chokepoint | `hvac_fans.py` (writes referenced from :285, :361, :599, :788) | OFF | HVAC vacancy / temp / adopt | manual-OFF cooldown enforced; manual-ON hold via FAN-MANUAL-1 D2 field split |
| W5 | HVAC-tier `turn_off_all_managed` | `hvac_fans.py:186-203` | OFF (mass) | operator kill switch | resets cooldown (line 203) and (post D2) hold |
| W6 | HVAC-tier reverse-clear / adopt-fan | `hvac_fans.py:280-370` | detection-only (writes state) | external transitions | writes `manual_off_cooldown_until` on OFF and `manual_on_hold_until` on ON after D2 split |
| W7 | Actuator reconciler | `actuator_reconciler.py:610-642` | ON + OFF | reconcile drift | consults `is_fan_in_manual_on_hold()` before OFF (line 618); calls `mark_fan_on_issued()` before ON (line 637) |
| W8 | HVAC zone-vacancy sweep | **`hvac.py:2419-2430`** | OFF | zone vacant + `CONF_FANS` iteration | **NOT GATED — bypasses cooldown + hold + reconciler** |
| W9 | HVAC pre-arrival deactivation | **`hvac.py:2629-2643`** | OFF | pre-arrival timeout | **NOT GATED — bypasses cooldown + hold + reconciler** |
| W10 | Presence fan-recheck pause OFF | `presence_fan_recheck.py:~582` (referenced) + reader at :410-414, :990-1015 | OFF | recheck substrate | reads `manual_off_cooldown_until` (private field peek at :1002-1007); needs symmetric hold consult |
| W11 | HVAC safety fan stop (smoke/CO/hazard) | **`hvac.py:2331-2362`** (`_stop_all_fans_safety`, invoked at `hvac.py:2311`) | OFF (mass) | safety hazard | **NOT GATED — bypasses cooldown + hold + reconciler.** Under this cycle: consults with `safety=True`; oracle verdict is ALWAYS ALLOW but the pre-safety verdict is LOGGED (WARNING) + `note_actuation` fires. New trigger `FAN_TRIGGER_SAFETY_STOP`. |
| W12 | HVAC pre-arrival fan ACTIVATION (turn-ON) | **`hvac_predict.py:1031-1102`** (`_activate_zone_fans`, invoked at `:640`) | ON | pre-arrival comfort bridge | **NOT GATED — bypasses manual-OFF cooldown + reconciler seed.** Under this cycle: `may_turn_on(HVAC_PREARRIVAL_ON)` before emit + `note_actuation` after. MUST DEFER under a live manual-OFF cooldown (rationale: operator turned the fan off recently and the cool-down window is unexpired; pre-arrival should not fight that until expiry). |

**"Five writers" per the FAN-MANUAL-1 origin claim is a floor, not a ceiling.**
W1, W2, W4, W7, W8 = the five that were the framing. W3 is the seed-authored
ON path; W6 is a detection-only writer to state (not a service call, but
gates future service calls); W9 (`hvac.py:2629-2643`) and W10 (recheck) are
additional writers. W11 (safety stop, `hvac.py:2331-2362`) and W12
(pre-arrival ON, `hvac_predict.py:1031-1102`) were surfaced by the
Reviewer-Completeness pass on this plan and are added as bypasses that
MUST route through the layer. **The real fan-surface writer set is 12
sites across 5 files, not 5.** Every plan below budgets for this.

**Non-writers (grep hits that are NOT fans-in-CONF_FANS):**
- `automation.py:2755-2771` — light-domain writes (lights, not fans).
- `automation.py:2000-2083` — HUMIDITY fan path (`humidity_fans` iteration,
  sole-owner exempt).
- `switch.py:4428, 4464` — utility switch domain writes unrelated to fans.
- `automation.py:782-1010` — light-actuation helpers (`_safe_service_call`
  for lights).

### 3.2 Prior planning docs consulted

- **`PLANNING_fan_actuation_shared_layer.md` (DOC-2 original, 2026-07-26)** —
  read end-to-end; §2.3-2.4 inventory carried forward; go-criteria matrix
  re-evaluated in §4 below.
- **`PLANNING_fan_manual_on_override.md` (FAN-MANUAL-1, 2026-08-10)** — read
  end-to-end; its §5 site table (six OFF-emitters) is now the seed for §3.1
  plus W8/W9/W10 found via re-grep.
- **`PLANNING_fan_manual_off_cooldown.md` (v5.31.0, shipped)** — narrow-fix
  precedent, one-sided mechanism (referenced from `automation.py:267`).
- **`PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md`**
  — humidity is single-owner; establishes that INV-FLA excludes humidity fans
  by design.
- **`PLANNING_signal_trust_ledger_abstraction.md`** — extraction pattern
  reference (M1-M7 migration table shape; criterion-4 golden-fixture
  regeneration lesson; verdict-only vs actuation split).
- **`AUDIT_hvac_duty_cycle_frequency.md`** (in-flight, per
  HVAC-PRESET-FLAP-1 card) — HVAC coast preset cycling is orthogonal to fan
  actuation but touches `hvac.py` — sequencing note in §14.

### 3.3 Memory bodies pulled

- `feedback_suppression_needs_discharge.md` — every hold/gate must specify
  discharge events + backstop + restart. Applies to any predicate the layer
  exposes. Drives §7.3.
- `feedback_hollow_test_anchors.md` — per-site source mutation (Reviewer C)
  MUST detach each writer individually. Aggregate monkeypatch of the layer
  is NOT sufficient (would prove the layer is load-bearing in aggregate but
  not that each writer routes through it).
- `feedback_no_fabrication.md` — the `mark_fan_on_issued` and manual-ON hold
  mechanics are subtle; cite file:line, do not summarize from memory.
- `feedback_marginal_benefit_pushback.md` — drives §6's shape choice
  (Gateway vs. Oracle vs. status quo).
- `feedback_falsify_before_asserting.md` — INV-FLA is written in falsifiable
  form; every claim about writer coverage has a mutation to break it.
- `feedback_mutation_verification_pycache_staleness.md` — Reviewer C must
  disable bytecode caching for the mutation drill.
- `project_v5_5_0_inclement_weather_shipped.md` — precedent for a Tier-3
  shared-primitive extraction with staged rollout.

### 3.4 Design docs read

No `docs/Coordinator/HVAC.md` fan section exists; `hvac_fans.py:1-100`
docstring + FAN-MANUAL-1 D6 write-back (owed post-deploy) are the design
record. FAN-LAYER-1 D9 supersedes and expands.

### 3.5 Code locations surveyed end-to-end

- `automation.py:260-395` (state fields + `mark_fan_on_issued` accessor at
  :362-382, `is_fan_in_manual_on_hold` accessor).
- `automation.py:1599-2200` (`handle_temperature_based_fan_control`,
  `handle_humidity_based_fan_control`, turn-on emission blocks).
- `automation.py:2440-2900` (sleep-onset gate, safety paths, light sweeps).
- `hvac_fans.py:70-370` (`RoomFanState` dataclass, `update` loop,
  `_set_fan_state` chokepoint, external detect/adopt).
- `hvac_fans.py:580-800` (evaluate path cooldown read; adopt-fan speed read
  with the field-overload comment at :788).
- `hvac_fans.py:1250-1410` (internal write comment at :1272; diagnostic
  filter at :1395-1401).
- `hvac.py:2380-2450` (zone-vacancy sweep W8).
- `hvac.py:2600-2650` (pre-arrival deactivation W9).
- `actuator_reconciler.py:250-260, 605-660` (fan-tier consults +
  `mark_fan_on_issued` seed at :637).
- `presence_fan_recheck.py:400-420, 580-680, 990-1015` (pause OFF write;
  cooldown reader at :1002-1007).
- `fan_veto.py:1-100, 380-460` (AWAY veto — turn_on only, orthogonal).
- `const.py:562, 771, 870-880` (defaults + kinds).

---

## 4. Trigger status: 3 of 4 have fired

Original DOC-2 gate: FOUNDATION (H8) + ANY 1 trigger. Current disposition:

| # | Trigger | Status | Evidence |
|---|---|---|---|
| Foundation | H8 organic proof of v5.31.0 cooldown | **CONDITIONAL PASS** (see §2.3) | in-suite proof + ~13 days of operator silence |
| 1 | New drift-hole (mechanic added to one tier, not other) | **FIRED** | FAN-MANUAL-1 shipped the manual-ON hold on room tier + a separate HVAC-tier field split (`manual_on_hold_until`) to prevent the exact drift — two symmetric fields, two symmetric detectors, still two fabrications of the same idea. |
| 2 | Real-world inconsistency (fan re-armed / failed / double-actuated) | **FIRED** | The 2026-08-01 Study A 4-hour vacant-fan incident recorded in `PLANNING_fan_actuation_shared_layer.md:227-235` — BUG 1 (post-restart vacancy-hold arms turn-ONs) + BUG 2 (HVAC one-way external sync) — both are tier-seam-class defects. |
| 3 | Third-writer bypass in the wild | **FIRED** (was: predicted; NOW: confirmed at two sites) | `hvac.py:2419-2430` (zone-vacancy sweep W8) and `hvac.py:2629-2643` (pre-arrival W9) both emit `domain.turn_off` on `CONF_FANS` iteration with NO cooldown, NO hold, NO reconciler consult. The task's language "the reconciler bypass at the exact line DOC-2 predicted" refers to W8; W9 is a second, previously-hidden bypass in the same file. |
| 4 | Piggyback opportunity | **NOT FIRED** | FAN-MANUAL-1 shipped separately by design. |

Three of four triggers fired; the go-criteria threshold (foundation + any one)
is exceeded. Build is authorized subject to operator acceptance of §2.3 and §6.

---

## 5. Behavior-frozen contract (the extraction's north star)

The extraction is BEHAVIOR-FROZEN. No new fan POLICIES land in this cycle;
only the emission machinery changes. Concretely:

- Cooldown length, hold length, vacancy-hold length, min-runtime, hysteresis,
  sleep speed cap, and `FAN_TRUST_STATES` are byte-identical to the
  post-FAN-MANUAL-1 tip.
- Sleep-policy axis mismatch (per-room time-window vs. house-state) is
  PRESERVED per-caller. The layer's context payload carries both axes; the
  layer routes to the right axis based on `trigger_path`.
- Restart semantics: no persistence added or removed.
- Ownership arbitration (`_is_hvac_managing_fans`) stays at CALLERS. The
  layer processes any request that arrives (matches DOC-2 §5.2 rationale).
- The `mark_fan_on_issued` seed channel (post FAN-MANUAL-1 A-MED-4) becomes
  redundant under shape (a) — the layer sets both tick-marker and baseline
  automatically. Migration removes the standalone accessor on shape (a);
  keeps it on shape (b) as a delegate.
- **W8/W9 (`hvac.py` sweeps) currently bypass ALL machinery. Under this
  cycle they begin honoring cooldown + hold. This IS a behavior CHANGE
  (they were the bugs). Called out explicitly as the ONE intentional
  behavior change in the extraction, per §7.4 and D6.**

---

## 6. Shape choice — three alternatives, marginal-benefit decomposed

### 6.1 Shape (a) — full `FanActuationGateway`

All writers call `gateway.request(room, entities, desired, context)`; gateway
owns the service-call emission, the ledger (last_on_time, hold_until,
cooldown_until, last_off_reason), and the discharge table. Writers stop
holding references to `hass.services.async_call` for fan entities.

- Benefit: consistency-by-construction. A new fan mechanic lands in ONE
  place. Reader consolidation (recheck's `manual_off_cooldown_until` peek)
  becomes a clean `gateway.get_state(room)` accessor.
- Cost: 8-site migration (W1, W2, W4, W7, W8, W9, W10; W3 is turn-ON and
  routes through the same gateway with `direction="on"`; W5 mass; W6
  detection). Every writer's emission site rewritten. Reviewer C mutation
  drill runs on the gateway boundary; per-writer drills confirm each writer
  calls the gateway (not that the gateway is load-bearing — the whole
  point is one chokepoint).
- Risk: highest blast radius. The gateway becomes a single failure point;
  any bug in the gateway breaks every fan. Restart / lifecycle sequencing
  (the gateway must exist before any writer wants to emit) is load-bearing.

### 6.2 Shape (b) — thin `FanPolicyOracle`

A `FanPolicyOracle` exposes two predicates: `may_turn_on(room, trigger_path)`
and `may_turn_off(room, trigger_path)`, plus `note_actuation(room, direction,
trigger_path)`. Writers keep their service calls but MUST consult the oracle
immediately before emission and MUST call `note_actuation` immediately after.
The oracle carries the ledger; the writers carry the emission.

- Benefit: policies centralized. Diff is much smaller (each writer gains 2-3
  lines: consult + emit + note). Existing service-call sites remain visible
  in the writers' source. Reader consolidation still works via a
  `oracle.get_state(room)` accessor.
- Cost: consistency is by CONVENTION not construction. A future writer added
  without consulting the oracle silently bypasses. INV-FLA is still
  enforceable via Reviewer D (grep the fan-emission surface, confirm each
  site is preceded by `may_actuate`) but the invariant relies on grep
  discipline, not on type safety.
- Risk: lower blast radius than (a); still requires the ledger to be correct
  and every writer to consult. Sleep-policy axis routing still needs
  trigger_path plumbing (same as (a)).

### 6.3 Shape (c) — status quo + discipline

Keep FAN-MANUAL-1's mechanics as-is; do NOT extract. Add a lint (grep-based
CI check) that fails a PR introducing a new fan-emission site without a
manual-off-cooldown consult and a `mark_fan_on_issued`/hold consult. Fix
W8/W9 as targeted hotfixes (add the two consults).

- Benefit: zero refactor risk. Zero code change to a delicate surface
  outside the two targeted hotfixes.
- Cost: the ledger stays split across `RoomAutomation` state + `RoomFanState`
  dataclass; recheck's private-field peek stays; every future fan mechanic
  pays the port cost. Trigger #1 fires again on the next cycle.

### 6.4 Marginal-benefit decomposition

- Shape (c) captures ~40% of the value (locks in current mechanics; fixes
  W8/W9 bypasses) at ~10% of the cost (a lint plus two W8/W9 targeted
  fixes).
- Shape (b) captures ~85% of shape (a)'s value (centralized policies; ledger
  consolidation; W8/W9 gated via `may_actuate` consult) at ~40% of shape
  (a)'s cost (each writer gets 2-3 lines; no gateway lifecycle plumbing; no
  gateway singleton failure mode).
- Shape (a)'s MARGIN over (b) is: type-enforced consistency (a future writer
  MUST have a gateway reference to emit; can't accidentally emit) + a
  slightly cleaner ledger reader. That margin is: single-digit-percent
  reduction in future drift risk, in exchange for ~2.5x the diff, a new
  singleton lifecycle to manage, and a broader Reviewer B surface (every
  writer's error-handling path around the gateway call must match its
  current error-handling around its service call).
- The ingredient-risk price of shape (a): gateway lifecycle is a new
  categorically-risky ingredient (singleton + boot sequencing + restart
  restore path). Shape (b) adds no new categorically-risky ingredient
  (predicates + a ledger are plain state, no new lifecycle).
- Precedent: the SignalTrustLedger chose extraction with verdict-only,
  actuation-elsewhere separation. It did not become a gateway. That is the
  same shape as (b), and its criterion-4 (golden parity from live surface)
  is the discipline being ported here.

### 6.5 Planner recommendation: shape (b), Oracle

- Marginal benefit of (a) over (b) does not pay for its marginal ingredient
  risk (new singleton lifecycle) or its ~2.5x diff size.
- Shape (b) still resolves triggers #1, #2, #3 (W8/W9 gated; ledger unified;
  reader-consolidation accessor exists).
- Shape (c) leaves the ledger split — future drift-cost stays elevated.
  Reject unless operator wants the smallest possible blast radius (in which
  case shape (c) is honest — but §11's Reader-parity risk under (b) is
  smaller than the reviewer-fatigue cost of doing (c) then (b) later).
- **PARK shape (a).** Evidence trigger to revisit: if within 90 days of
  shape (b) shipping, a new writer is added that bypasses the oracle
  (implying grep discipline broke), promote to shape (a) as a follow-up
  cycle. Record that trigger here rather than delete the design.

Operator ruling requested: confirm (b), or elevate to (a), or drop to (c).
§7-§10 assume (b); §14 notes the delta if (a) is chosen.

---

## 7. Design (assuming shape (b))

### 7.1 New module: `custom_components/universal_room_automation/fan_policy_oracle.py`

Single class `FanPolicyOracle`, one instance per install, attached to
`coordinator_manager` (per DOC-2 §Open-decisions option (b), lowest new
machinery).

```
class FanPolicyOracle:
    def may_turn_on(self, room: str, trigger_path: str,
                    *, safety: bool = False) -> Verdict: ...
    def may_turn_off(self, room: str, trigger_path: str,
                     *, safety: bool = False) -> Verdict: ...
    def note_actuation(self, room: str, direction: Literal["on","off"],
                       trigger_path: str) -> None: ...
    def get_state(self, room: str) -> RoomFanLedger: ...   # reader
```

`Verdict = ALLOW | DEFER(reason) | VETO(reason)`. Discharge table below.

Ledger fields (per room):
- `last_on_time: datetime | None`
- `last_off_time: datetime | None`
- `manual_off_cooldown_until: datetime | None`  (was `RoomFanState.manual_off_cooldown_until` + `RoomAutomation._fan_manual_off_until`; unified)
- `manual_on_hold_until: datetime | None`       (was `RoomFanState.manual_on_hold_until` + `RoomAutomation._fan_manual_on_until`; unified)
- `last_trigger_path: str | None`               (diagnostic)
- `last_actuation_source: Literal["ura","external"] | None`
- `pause_context: PauseContext | None`          (fan-recheck pause bookkeeping)

### 7.2 Trigger-path vocabulary (closed enum in const.py — Bug Class #22 mitigation)

```
FAN_TRIGGER_TEMP_ROOM         = "temp_room"           # W1
FAN_TRIGGER_SLEEP_OFF         = "sleep_off"           # W2 (room-tier per-room time-window sleep axis)
FAN_TRIGGER_SLEEP_ONSET_ON    = "sleep_onset_on"      # W3 (room-tier per-room time-window sleep axis)
FAN_TRIGGER_TEMP_ROOM_ON      = "temp_room_on"        # W3
FAN_TRIGGER_TEMP_HVAC         = "temp_hvac"           # W4 emit
FAN_TRIGGER_HVAC_SLEEP_ONSET_ON = "hvac_sleep_onset_on" # HVAC-tier house-state sleep axis (split from SLEEP_ONSET_ON per H3)
FAN_TRIGGER_KILL_SWITCH       = "fan_control_disabled" # W5
FAN_TRIGGER_RECONCILE_ON      = "reconcile_on"        # W7 ON
FAN_TRIGGER_RECONCILE_OFF     = "reconcile_off"       # W7 OFF
FAN_TRIGGER_HVAC_VACANCY      = "hvac_vacancy_sweep"  # W8
FAN_TRIGGER_HVAC_PREARRIVAL   = "hvac_prearrival"     # W9 (OFF)
FAN_TRIGGER_HVAC_PREARRIVAL_ON = "hvac_prearrival_on" # W12 (ON — NEW per completeness C2)
FAN_TRIGGER_RECHECK_PAUSE     = "recheck_pause"       # W10
FAN_TRIGGER_RECHECK_RESTORE   = "recheck_restore"     # W10
FAN_TRIGGER_SAFETY            = "safety"              # legacy freeze / point-source (kept)
FAN_TRIGGER_SAFETY_STOP       = "safety_stop"         # W11 mass safety stop (NEW per completeness C1)
# NOTE: humidity fans are FULLY OUTSIDE the layer (see §13 M2). There is
# NO FAN_TRIGGER_HUMIDITY_ON member. Adding one would require an operator
# ruling + re-audit trigger (flap evidence).
```

Reviewer B validates: every writer names its trigger; no free-string
paths. Reviewer D validates: adding a NEW trigger constant does NOT
regress any existing verdict.

**Enum VALUES are string-identical to the current log literals.** The
`str` value of each `FAN_TRIGGER_*` MUST match the trigger token currently
emitted in `activity_log.description` and `_LOGGER.info` messages (grep
`automation.py` + `hvac_fans.py` + `hvac.py` for the strings on the
right-hand side of the `=` above; any drift breaks downstream log
consumers). Per M4 (build-prediction): D2 includes an **external-consumer
grep** — `git grep -F "manual off"` + `git grep -F "sleep_off"` etc.
across `dashboard/`, `dashboard-v3/`, shipwatch fixtures, and any
`docs/reviews/*` that pins these tokens — and any hit that references
the trigger vocabulary is documented in the D8 audit deliverable.

### 7.3 Discharge table (per `feedback_suppression_needs_discharge.md`)

| Condition | Effect on cooldown | Effect on hold | Rationale |
|---|---|---|---|
| Timer expiry (`now >= until`) | clear cooldown | clear hold | bounded runtime; backstop |
| External OFF detected | open cooldown | clear hold + open cooldown | freshest human wins (existing v5.31.0 shape) |
| External ON detected | clear cooldown | open hold | freshest human wins (existing FAN-MANUAL-1 shape) |
| URA-owned OFF (`RECHECK_PAUSE`) | do not open | pause hold deadline (credit paused duration on restore) | recheck restore re-honors hold |
| URA-owned OFF (`KILL_SWITCH`) | do not open | clear hold | kill switch is a superset instruction |
| URA-owned OFF (any other trigger) | do not open | consult hold (DEFER if live) | writer stays subordinate to hold |
| `safety=True` | force ALLOW; log warn | force ALLOW; log warn | safety > policy > preference |
| Restart | RAM-only reset; adopt-external re-populates on first tick | RAM-only reset; adopt-external re-populates on first tick | matches current behavior; documented |

### 7.4 Verdict routing per writer (byte-frozen migration table — mirrors SignalTrustLedger M1-M7)

| Writer | Before-emit consult | After-emit note | Parity method |
|---|---|---|---|
| W1 room OFF | `may_turn_off(room, TEMP_ROOM)` | `note_actuation(room, "off", TEMP_ROOM)` | golden-log diff: identical activity_log line under identical fixture inputs (FAN-MANUAL-1 fixtures reused) |
| W2 room SLEEP-OFF | `may_turn_off(room, SLEEP_OFF)` | `note_actuation(room, "off", SLEEP_OFF)` | FAN-MANUAL-1 §7.1 ruling preserved: layer treats SLEEP_OFF as "policy trigger — hold applies" (option A from that doc) |
| W3 room ON (temp / sleep) | `may_turn_on(room, TEMP_ROOM_ON \| SLEEP_ONSET_ON)` | `note_actuation(room, "on", <trigger>)` | note REPLACES `mark_fan_on_issued`. **Humidity path is EXCLUDED from the layer per §13 M2** — humidity fans stay sole-owner via `_humidity_gate`; the humidity turn-ON site in `automation.py` DOES NOT call `may_turn_on` and DOES NOT call `note_actuation`. Reviewer D verifies exclusion: humidity fan-set is disjoint from comfort fan-set on every room. |
| W4 HVAC OFF chokepoint | `may_turn_off(room, TEMP_HVAC)` | `note_actuation(room, "off", TEMP_HVAC)` | field split: existing `RoomFanState.manual_off_cooldown_until` READS delegate to ledger; writes removed |
| W5 kill switch | `may_turn_off(room, KILL_SWITCH)` — always ALLOW; layer clears hold | `note_actuation(room, "off", KILL_SWITCH)` | mass reset behavior preserved |
| W6 detection-only | n/a (state observation) | `note_actuation` when external transition observed | `_last_seen_any_fan_on` baseline moves into ledger |
| W7 reconciler | consult per direction | note per direction | replaces `is_fan_in_manual_on_hold()` peek (line 618) and `mark_fan_on_issued()` seed (line 637) with layer consult/note |
| W8 HVAC zone-vacancy sweep | `may_turn_off(room, HVAC_VACANCY)` | `note_actuation(room, "off", HVAC_VACANCY)` | **BEHAVIOR CHANGE** (§5): was bypass; now gates on cooldown + hold |
| W9 HVAC pre-arrival | `may_turn_off(room, HVAC_PREARRIVAL)` | `note_actuation(room, "off", HVAC_PREARRIVAL)` | **BEHAVIOR CHANGE** (§5): was bypass; now gates on cooldown + hold |
| W10 recheck pause | `may_turn_off(room, RECHECK_PAUSE)` — always ALLOW; layer pauses hold deadline | `note_actuation(room, "off", RECHECK_PAUSE)` | replaces `_fan_in_manual_cooldown` private-field peek at :1002-1007 with `oracle.get_state(room).manual_off_cooldown_until` |
| W10 recheck restore | `may_turn_on(room, RECHECK_RESTORE)` — ALLOW iff hold was live at pause | `note_actuation(room, "on", RECHECK_RESTORE)` | resumes hold with paused-duration credited. Covers the state-restoration-only attribute writes at `hvac_fans.py:1541/1554/1567` (preset/oscillate/direction) — see §1 carve-out. |
| W11 HVAC safety stop | `may_turn_off(room, SAFETY_STOP, safety=True)` — ALWAYS ALLOW (safety > policy) | `note_actuation(room, "off", SAFETY_STOP)` | oracle logs the pre-safety verdict (WARNING) so we can see WHAT would have been vetoed. Reviewer C test: verify (a) consult fires for every fan iterated AND (b) `safety=True` override wins even when a fresh manual-ON hold is live. |
| W12 HVAC pre-arrival ON | `may_turn_on(room, HVAC_PREARRIVAL_ON)` — DEFER under a live manual-OFF cooldown; ALLOW otherwise | `note_actuation(room, "on", HVAC_PREARRIVAL_ON)` | **BEHAVIOR CHANGE** (§5): was bypass; now respects manual-OFF cooldown (rationale in §3.1 W12). Reviewer C test: fan is NOT turned on by pre-arrival when a manual-OFF cooldown is live; skipped-rooms diagnostic gains `reason="manual_off_cooldown"`. |

### 7.4a Sleep-axis routing (M1 build-prediction)

The FanDecisionSnapshot (§7.7) carries `sleep_axis: Literal["room_window","house_state"] | None`. The oracle routes based on the pair `(trigger_path, sleep_axis)`:

| Trigger | Expected sleep_axis | Oracle action if axis mismatches trigger |
|---|---|---|
| `SLEEP_OFF` | `room_window` | ERROR log + VETO (misuse — room-tier trigger with HVAC-tier axis) |
| `SLEEP_ONSET_ON` | `room_window` | ERROR log + VETO (same) |
| `HVAC_SLEEP_ONSET_ON` | `house_state` | ERROR log + VETO (HVAC trigger with room-tier axis) |
| any other trigger | ignored | passes through; sleep_axis is diagnostic-only |

The two axes STAY per-caller (§5 preserved). This table only asserts that the caller's trigger matches the caller's axis; it does not merge the axes. Reviewer C mutation: flip axis on one call site → the corresponding VETO test fires.

### 7.5 Reader consolidation

`presence_fan_recheck.py:1002-1007` becomes:

```
until = oracle.get_state(room).manual_off_cooldown_until
```

replacing the `room_fan.manual_off_cooldown_until` peek. Same at :410-414
(veto path). The `is_fan_in_manual_on_hold()` accessor on `RoomAutomation`
becomes a thin delegate to `oracle.get_state(room).manual_on_hold_until`.

### 7.6 Ownership arbitration (unchanged)

Callers still consult `_is_hvac_managing_fans()` BEFORE calling
`oracle.may_turn_*`. Rationale unchanged from DOC-2 §Open-decisions #5.

### 7.7 Restart / lifecycle

Ledger is RAM-only. On first post-boot tick, the room-tier and HVAC-tier
external-adopt paths re-observe fan states and re-populate holds/cooldowns
symmetrically (existing behavior; preserved). The oracle is constructed in
`coordinator_manager` before ANY writer boot-tick fires — enforced by
placing construction in `async_setup_entry` alongside existing singleton
constructions (grep-verify no writer's `async_setup_entry` runs before
`coordinator_manager`'s during boot).

A boot-order fixture test (`test_fan_oracle_constructed_before_writers`) replaces the grep-promise (L3 build-prediction): the test asserts, via a construction-order recorder, that `FanPolicyOracle.__init__` runs strictly before the `async_setup_entry` of every writer's owning coordinator.

### 7.8 FanDecisionSnapshot — required-arg dataclass (H1 build-prediction, CRIT)

Every `may_turn_on` / `may_turn_off` call MUST pass a `FanDecisionSnapshot` as a REQUIRED positional argument. The oracle owns only ledger fields; the snapshot is the caller's declaration of the world it decided against.

```
@dataclass(frozen=True, slots=True)
class FanDecisionSnapshot:
    now: datetime                                  # caller's decision timestamp
    sleep_state: str                               # e.g. "awake"|"asleep"|"onset"
    sleep_axis: Literal["room_window","house_state"] | None
    house_state: str                               # e.g. "occupied"|"away"|"night"
    is_hvac_managing: bool                         # ownership arbitration result
    entities: tuple[str, ...]                      # the fan entity_ids about to be actuated
    observed_any_on: bool                          # is_on read at decision time
```

Signature (shape (b)):
```
def may_turn_on(self, room: str, trigger_path: str, snapshot: FanDecisionSnapshot,
                *, safety: bool = False) -> Verdict: ...
def may_turn_off(self, room: str, trigger_path: str, snapshot: FanDecisionSnapshot,
                 *, safety: bool = False) -> Verdict: ...
```

`snapshot` has NO default. A missing snapshot is a `TypeError` at import time (in fixtures) or at call time (in production) — caught by Reviewer B smoke test. Parity fixtures (D3-D7) MUST include a snapshot column; a fixture that supplies only `(room, trigger_path)` is rejected by the test loader.

### 7.9 TOCTOU discipline — per-room asyncio.Lock (H2 build-prediction, CRIT)

INV-FLA restated **temporally**:

> **INV-FLA-T:** for any room, if `manual_on_hold_until` becomes live at time T (via external-ON detection), NO URA-issued fan OFF may complete (be awaited to `services.async_call` return) at any T' > T until the hold expires or is explicitly discharged (kill-switch, external-OFF).

Under async, a naive consult→emit sequence can be interleaved: writer A consults at T0 (ALLOW), yields on `await services.async_call`, external-ON dispatch lands at T1, hold opens at T2, writer A's OFF completes at T3 — INV-FLA violated on a consult that WAS correct at T0.

**Discipline:** every writer holds a **per-room `asyncio.Lock`** across the full **consult → emit → note_actuation** critical section. The lock is owned by the oracle (`oracle._room_locks: dict[str, asyncio.Lock]`, lazily created per room) and acquired via a context-manager helper on the oracle:

```
async with oracle.actuate(room, trigger_path, snapshot, direction=...) as verdict:
    if verdict.is_allow:
        await hass.services.async_call(...)
# note_actuation fires on context exit
```

Under shape (b), writers MAY still call `may_turn_*` directly for diagnostic-only consults (e.g. reconciler dry-run), but every EMITTING site MUST use `oracle.actuate(...)`. Reviewer C mutation: convert one writer's `actuate` back to a raw consult+emit → a Reviewer B test named `test_external_on_racing_ura_off_is_blocked_room_<X>` fires (this test dispatches an external-ON on the state bus during an awaited URA OFF; without the lock the OFF completes; with it, the consult on entry to the critical section sees the fresh hold and VETOs).

The lock is per-room; unrelated rooms do not serialize.

### 7.10 Field-delegation — DECIDED: hard removal, no delegates (H3 build-prediction)

The seven reader sites in `hvac_fans.py` (`:295, :586, :792, :1272, :1395, :1401`) and `presence_fan_recheck.py:1002-1007` are **rewritten** to `oracle.get_state(room).manual_off_cooldown_until` / `.manual_on_hold_until` calls. **The `RoomFanState` fields are REMOVED** (not @property-wrapped, not `__getattr__`-shimmed). Rationale: a `@property` delegate creates a silent read path that partially works (returns None) if the oracle is missing or the room key is absent — the exact stale-cache class that produced the 6 CRITICAL findings on v4.6.3 first pass.

Reviewer B produces an **audit table** of the 8 rewritten sites with before/after diff hunks. Reviewer C runs a per-reader **None-substitution drill**: for each reader site, temporarily patch `get_state(room)` to return a `RoomFanLedger` with the field forced to `None`, run the suite, and confirm the reader's downstream behavior fails a named test (proving the reader is not silently swallowing None). Restore, next site.

The full reader enumeration is in §11.

### 7.11 Exception posture (H5 build-prediction)

Oracle predicates and note MUST NOT propagate exceptions to writers. Fail-safe direction is chosen per method to prefer FAN-OFF over FAN-ON on error:

| Method | On uncaught exception | Rationale |
|---|---|---|
| `may_turn_off` | `_LOGGER.error(...)` + return `ALLOW` | fail = fan turns off (safe: quiet, no runaway) |
| `may_turn_on` | `_LOGGER.error(...)` + return `VETO("oracle_error")` | fail = fan stays off (safe: no phantom activation) |
| `note_actuation` | `_LOGGER.error(...)` + no-op self-heal (do NOT re-raise) | ledger drift bounded by next external-adopt tick |
| `get_state(room)` | `_LOGGER.error(...)` + return an EMPTY `RoomFanLedger` (all-None) | reader defaults are already None-safe by §7.10 drill |

One test per branch (four): `test_oracle_may_turn_off_exception_allows`, `test_oracle_may_turn_on_exception_vetos`, `test_oracle_note_actuation_exception_no_op`, `test_oracle_get_state_exception_returns_empty_ledger`.

Safety carve-out interaction: `safety=True` bypasses the try/except (the exception path returns ALLOW anyway for OFF; for ON, safety=True is not used).

### 7.12 SignalTrustLedger boundary (M2)

The `FanPolicyOracle` is verdict-and-actuation-aware (Oracle emits `note_actuation`, participates in the `actuate()` critical section). This DIFFERS from `SignalTrustLedger`, which is verdict-only (writers actuate independently). Reason for the divergence: fan actuation requires the layer to observe the `_last_seen_any_fan_on` baseline transition atomically with the actuation itself; a verdict-only ledger cannot enforce §7.9's TOCTOU discipline. Both patterns coexist — the boundary is: **verdict-only when the caller alone owns the after-effect side channel; verdict+actuation when the ledger's own bookkeeping depends on the actuation completing**. Fan is the latter.

### 7.14 note_actuation writes activity_log on EDGES only (M3 build-prediction)

`note_actuation(room, direction, trigger_path)` writes an `activity_log` row ONLY when the verdict CHANGES for the tuple `(room, trigger_path, current_hold_id)`, where `current_hold_id` is a monotonically-bumped integer that increments each time `manual_on_hold_until` opens fresh. Repeated identical verdicts within the same hold (e.g. a reconciler dry-run polling every 30s while a manual-ON hold is live) collapse to zero rows.

Rationale: `project_optimizer_db_write_flood_incident_2026_06_09.md` — one-by-one persist per cycle on 40 rooms saturated the write queue and tripped the watchdog. A per-tick `note_actuation` from every writer × 40 rooms × 30s tick × 12 sites is `~4600 rows/hour` if written unconditionally; edges-only collapses it to `< 200 rows/hour` in the steady state.

**Write-volume regression test** (`test_note_actuation_write_volume_40_rooms_3600s`): simulate 40 rooms across 3600s of a steady-state day (mixed occupied/vacant, one manual-ON in Living Room, no external transitions after that), run the oracle through the substrate tick loop, assert `activity_log` inserts < 200 rows. Cites the optimizer write-flood memory as the reason for the specific budget.

### 7.13 PauseContext (L2 build-prediction)

```
@dataclass(frozen=True, slots=True)
class PauseContext:
    paused_at: datetime               # when recheck pause emitted
    hold_remaining_at_pause: timedelta  # (manual_on_hold_until - paused_at) at pause instant; None if no hold live
```

Stored on `RoomFanLedger.pause_context` while a recheck pause is active. On restore, `may_turn_on(RECHECK_RESTORE, snapshot)` inspects `pause_context`: if `hold_remaining_at_pause` is non-None, oracle sets `manual_on_hold_until = snapshot.now + hold_remaining_at_pause` (credit paused duration) and returns ALLOW; else returns ALLOW without touching the hold. Cleared unconditionally after restore fires. Reviewer B test: `test_pause_context_credits_paused_duration_on_restore`.

---

## 8. Numbers-Get-Knobs

| Number | Value | Rung | Home | Why |
|---|---|---|---|---|
| `DEFAULT_FAN_MANUAL_OFF_COOLDOWN_S` | 3600 (existing) | 1 module const | `const.py:562` | preserved |
| `DEFAULT_FAN_MANUAL_ON_HOLD_S` | 3600 (existing) | 1 module const | `const.py` (FAN-MANUAL-1) | preserved |
| `CONF_FAN_VACANCY_HOLD` | per-room | 2 options flow | existing | preserved |
| `CONF_FAN_MANUAL_ON_HOLD_S` | per-room | 2 options flow (FAN-MANUAL-1 D4) | existing | preserved |
| Trigger-path vocabulary | closed enum | 1 module const | `const.py` (new `FAN_TRIGGER_*`) | closed by design; adding one requires reviewed code change (Bug Class #22 mitigation) |
| Oracle diagnostic verbosity | INFO / DEBUG | not new — logger levels only | n/a | no new knob |

**No new operator-facing knobs.** All existing tunables preserved at their
current rung. Kill-switch semantics unchanged (`DEFAULT_*_S=0` still disables
each feature).

---

## 9. Tier — argued Tier 3, four framing-disjoint reviews

**Tier 3** — delicate shared-primitive / invariant-critical cycle.

Justifications (per CLAUDE.md Tier 3 triggers):

- Threads a value (cooldown, hold, sleep cap, trigger-path routing) through
  a state machine consumed by MANY emission/decision sites (Bug Class #53).
- Comfort-AND-safety-impacting: a botched extraction can either (a) leave
  W8/W9 still bypassing (silent regression to the tier-drift class); or (b)
  gate a legitimate safety-off (fan running on smoke-alarm event) if the
  safety=True path is mis-wired.
- History: v5.31.0 (manual-OFF) needed a hotfix. FAN-MANUAL-1 (2026-08-10)
  shipped with 1 CRIT + 6 HIGH. Fan mechanics have needed multi-fix-up
  cycles three quarters in a row. That is the "delicate" signature.
- Operator has explicitly flagged HIGH PRIORITY. Under CLAUDE.md the
  operator's flag alone qualifies for Tier 3.

Four framings:

- **Review A — local correctness + edge cases.** Per-writer: does the
  consult fire when it should and only when it should? Verdict logic
  arithmetic. Speed-change (dimmer) mid-hold — is that an external ON event
  or a no-op? Cold boot. External-on-off-on flap. Cite site by file:line.
- **Review B — cross-coordinator + state-machine integrity.** Recheck
  pause/restore across a hold. Field-split reader migration
  (`RoomFanState.manual_off_cooldown_until` — audit EVERY reader at
  `hvac_fans.py:295, 586, 792, 1272, 1395, 1401` and
  `presence_fan_recheck.py:1002-1007`). Reconciler defer ordering vs.
  HVAC-managed defer. Sleep-onset re-arm interaction. Restart adopt path.
  Lifecycle sequencing (oracle before writers on boot).
- **Review C — test authority via per-site source mutation.** For EACH of
  the 14 sub-sites: W1, W2, W3-temp, W3-sleep, W4, W5, W6-adopt-on,
  W6-adopt-off, W7-ON, W7-OFF, W8, W9, W10-pause, W10-restore, W11 (safety
  stop), W12 (pre-arrival ON) — comment out the `may_turn_*` consult (or
  `oracle.actuate` context enter) AND the `note_actuation` at that site
  individually, run the suite, confirm a NAMED test fails. Restore. Also
  run the **§7.10 None-substitution drill** on each of the 8 reader sites
  enumerated in §11. Aggregate monkeypatch of oracle predicates is NOT
  sufficient. Per `feedback_mutation_verification_pycache_staleness.md`,
  disable bytecode caching (`PYTHONDONTWRITEBYTECODE=1` + purge `__pycache__/`)
  before drill.
  
  **Mechanical adjacency procedure (M1):** for each site, Reviewer C verifies
  that the `may_turn_*` consult is IMMEDIATELY followed by the
  `services.async_call` (or by the `oracle.actuate` context-manager body that
  contains it), with no branchable code between. Procedure:
  1. Run a structured grep: `git grep -n -A 6 "oracle\\.\\(may_turn_\\|actuate\\)"` for each writer.
  2. For each hit, run a **throwaway AST walker** (`ast.parse` on the
     function body, walk `body`/`orelse`, find the enclosing statement of
     the consult, assert the very next statement is either the
     `services.async_call` (or its `await`), OR an `if verdict.is_allow`
     branch whose body's next Call is `services.async_call`).
  3. Any site failing the adjacency assertion is a Reviewer C finding —
     an interposed conditional or a stashed verdict introduces a TOCTOU
     window §7.9 was designed to eliminate.
  The AST walker script is committed under `quality/tools/audit_fan_adjacency.py`
  and re-run as part of the D8 audit.
- **Review D — adversarial completeness / diff-blind.** Sole job: state
  INV-FLA in falsifiable form (already done, §1), then BREAK it.
  Re-enumerate the ENTIRE fan-emission surface — including pre-existing
  code outside this diff. Every leak comes with a concrete legal-config
  reachable repro. Explicit search terms: `SERVICE_TURN_OFF` + `CONF_FANS`,
  `SERVICE_TURN_ON` + `CONF_FANS`, `homeassistant.turn_off` +
  fan-domain-string, `hass.services.async_call` + fan/switch, plus any new
  callsite added after 2026-08-10 (`git log --since` since branch base).

Orchestrator independent verification per Tier 3 CLAUDE.md: personally
re-grep every emission site and re-run a real source mutation on one
load-bearing writer (recommend W8 — it is the newly-gated site AND was
missed by every prior audit).

Operator checkpoint BEFORE deploy is mandatory.

---

## 10. Deliverables + acceptance criteria

**Preamble (H4 build-prediction): D2 through D7-plus-safety-plus-prearrival-ON = ONE PR, ONE deploy.** Interim commits are review-and-organization artifacts; the ship unit is the full migration. INV-FLA is never claimed on a partial migration — until every writer routes through the oracle, the invariant is trivially violated by any unmigrated site. **Per-deliverable sub-invariants** (below) tell reviewers what each interim commit does prove, so INV-FLA is not asserted early. The single-PR discipline is what closes the "half-migrated" window that produced two of FAN-MANUAL-1's HIGH findings.

Per-deliverable sub-invariants (each holds independently after its commit; ONLY the aggregate proves INV-FLA):

| Deliverable | Sub-invariant proven at commit |
|---|---|
| D2 | Oracle exists, singleton lifecycle is boot-ordered, all-None ledger returned pre-first-tick. |
| D3 | Every W1/W2/W3 emission is preceded by a room-tier oracle consult; room-tier golden-log parity holds. |
| D4 | Every W4/W5/W6 write goes via `_set_fan_state` chokepoint consult; ledger fields are the only source of truth for cooldown/hold at HVAC tier (no `RoomFanState.manual_*_until` writes remain). |
| D5 | Reconciler holds no direct fan-state accessors on `RoomAutomation` / `RoomFanState`. |
| D6 | W8 + W9 (both `hvac.py` sweeps) consult and note; the intentional behavior change is asserted by name in two tests. |
| D6a (safety, W11) | `_stop_all_fans_safety` consults with `safety=True`; oracle logs pre-safety verdict; note fires. |
| D6b (pre-arrival ON, W12) | `_activate_zone_fans` consults `HVAC_PREARRIVAL_ON`; DEFERS under live manual-OFF cooldown; note fires on ALLOW. |
| D7 | Recheck reads via `oracle.get_state`; pause/restore round-trip preserves hold deadline via `PauseContext`. |
| D8 | Reviewer D adversarial-completeness sweep passes; every `services.async_call` on `CONF_FANS` iteration is preceded by an oracle consult in the same function AND passes the §9-C AST adjacency check. This is where INV-FLA is formally claimed. |

### D1 — Probe (only if operator rejects §2.3 (b)+(c))

**Files:** none (throwaway script).

- **Verify:** SSH-run `SELECT ... FROM ura_activity_log WHERE description
  LIKE '%manual off%'` returns at least one row followed by NO fan-ON within
  3600s for the same room. If empty over retention window, operator adjudicates.
- **Live:** the row itself is the artifact.

### D2 — Trigger vocabulary + oracle skeleton

**Files:** `const.py` (add `FAN_TRIGGER_*` closed enum);
`fan_policy_oracle.py` (new module: class + verdict types + ledger
dataclass, no callers yet); `coordinator_manager.py` (construct singleton,
plumb into `hass.data` for writer access).

- **Verify:** grep `FAN_TRIGGER_` returns the enum members + oracle
  code only; no free-string trigger paths.
- **Test:** `test_fan_oracle_verdict_matrix` (per-trigger x per-state
  ALLOW/DEFER/VETO matrix); `test_fan_oracle_ledger_restart_semantics`.
- **Live:** oracle singleton exists on `hass.data[DOMAIN]["fan_oracle"]`
  post-restart; `hass.data[DOMAIN]["fan_oracle"].get_state("living_room")`
  returns a `RoomFanLedger` with all-None fields at fresh boot.

### D3 — Migrate W1, W2, W3 (room-tier)

**Files:** `automation.py` (replace `_fan_manual_off_until` /
`_fan_manual_on_until` state fields with oracle consults; `mark_fan_on_issued`
becomes delegate to `oracle.note_actuation`).

- **Verify:** grep `_fan_manual_off_until` and `_fan_manual_on_until` return
  only backwards-compat delegates (or zero hits if delegates removed).
- **Test:** golden-log parity per writer (FAN-MANUAL-1's tests must all
  pass byte-identical); mutation drill per §9-C.
- **Live:** Living Room manual-ON at 75°F holds for 60 min post-restart
  (FAN-MANUAL-1 acceptance criterion, byte-identical).

### D4 — Migrate W4, W5, W6 (HVAC-tier chokepoint + kill + adopt)

**Files:** `hvac_fans.py` (`_set_fan_state` gains oracle consult;
`RoomFanState.manual_off_cooldown_until` + `manual_on_hold_until` become
read-through delegates to ledger; `turn_off_all_managed` calls
`note_actuation(..., KILL_SWITCH)`).

- **Verify:** grep `RoomFanState.manual_off_cooldown_until =` returns zero
  writes (only reads via delegate).
- **Test:** `test_hvac_writer_consults_oracle`; `test_kill_switch_clears_hold`.
- **Live:** HVAC-managed bedroom fan externally-lit at 74°F does not receive
  HVAC-tier OFF for hold window; log shows trigger_path=`temp_hvac`.

### D5 — Migrate W7 (reconciler)

**Files:** `actuator_reconciler.py:610-642` (replace
`is_fan_in_manual_on_hold()` peek at :618 with `oracle.may_turn_off(...)`;
replace `mark_fan_on_issued()` at :637 with `oracle.note_actuation(...)`).

- **Verify:** reconciler holds no direct reference to `RoomAutomation`
  fan-state accessors.
- **Test:** `test_reconciler_defers_on_manual_on_hold_via_oracle`;
  `test_reconciler_on_notes_actuation`.
- **Live:** reconciler skip counters show `manual_on_hold` reason unchanged
  from FAN-MANUAL-1 baseline.

### D6 — Migrate W8, W9 (HVAC sweeps — the intentional behavior change)

**Files:** `hvac.py:2419-2430` (zone-vacancy sweep); `hvac.py:2629-2643`
(pre-arrival). Both gain `oracle.may_turn_off(room, HVAC_VACANCY | HVAC_PREARRIVAL)`
before emit + `note_actuation` after.

- **Verify:** grep `hvac.py` for direct `services.async_call` on `CONF_FANS`
  iteration returns two hits, each preceded by an oracle consult in the
  same function.
- **Test:** `test_hvac_zone_vacancy_sweep_respects_manual_on_hold`;
  `test_hvac_prearrival_respects_manual_off_cooldown`. Both MUST assert the
  fan REMAINS ON when the hold is live (this is the intentional behavior
  change — assert it as an invariant, not a regression).
- **Live:** after a manual-ON in a zone that later goes vacant, verify the
  fan is NOT swept off by W8 within the hold window; activity_log shows
  `deferred: hvac_vacancy_sweep by manual_on_hold`.

### D6a — Migrate W11 (HVAC safety fan stop — completeness C1)

**Files:** `hvac.py:2331-2362` (`_stop_all_fans_safety`). Add `oracle.actuate(room, FAN_TRIGGER_SAFETY_STOP, snapshot, direction="off", safety=True)` around the per-fan `services.async_call`. New trigger `FAN_TRIGGER_SAFETY_STOP` in D2's enum.

- **Verify:** grep confirms `_stop_all_fans_safety` no longer calls `services.async_call` unconditionally; every call is inside an `oracle.actuate(..., safety=True)` block.
- **Test:** `test_safety_stop_consults_oracle_and_overrides_hold` — assert (a) `may_turn_off` receives `safety=True` for EVERY fan iterated, (b) verdict is ALLOW even when a fresh manual-ON hold is live, (c) the oracle emits a WARNING log naming the pre-safety verdict it WOULD have returned.
- **Live:** trip a synthesized smoke event; verify every fan turns off; verify `activity_log` shows `safety_stop` rows with `pre_safety_verdict` annotation.

### D6b — Migrate W12 (HVAC pre-arrival fan ACTIVATION — completeness C2)

**Files:** `hvac_predict.py:1031-1102` (`_activate_zone_fans`). Add `oracle.actuate(room, FAN_TRIGGER_HVAC_PREARRIVAL_ON, snapshot, direction="on")` around the per-fan `services.async_call`. Add `reason="manual_off_cooldown"` to `_last_fan_skipped_rooms` when the oracle DEFERs.

- **Verify:** grep confirms every `turn_on` in `_activate_zone_fans` is inside an `oracle.actuate` block.
- **Test:** `test_prearrival_on_defers_under_manual_off_cooldown` — pre-condition a live cooldown, invoke `_activate_zone_fans`, assert fan is NOT turned on and `_last_fan_skipped_rooms` gains a `reason="manual_off_cooldown"` entry. `test_prearrival_on_allows_when_cooldown_expired` — mirror case.
- **Live:** set a manual-OFF cooldown on a bedroom fan; trigger pre-arrival; verify no turn-ON; verify the skipped-rooms diagnostic surfaces the reason.

### D7 — Migrate W10 (recheck)

**Files:** `presence_fan_recheck.py:410-414, :580-680, :990-1015` (replace
private-field peeks with `oracle.get_state(room)`; pause OFF becomes
`may_turn_off(RECHECK_PAUSE)` — always ALLOW, layer pauses hold deadline;
restore becomes `may_turn_on(RECHECK_RESTORE)` — ALLOW iff hold was live).

- **Verify:** grep `presence_fan_recheck.py` for `manual_off_cooldown_until`
  returns zero direct-attribute reads on `RoomFanState`.
- **Test:** `test_recheck_pause_preserves_hold_deadline`;
  `test_recheck_restore_rearms_held_fan`; `test_recheck_ignores_bypass_hold_when_expired`.
- **Live:** trigger a recheck on a fan under manual-ON hold; verify pause +
  restore, hold survives, deadline extended by paused duration.

### D8 — Reviewer D adversarial-completeness sweep (build-time)

**Files:** none (audit deliverable).

- **Verify:** git grep of the fan-emission vocabulary against the FAN-LAYER-1
  branch shows every callsite either (i) preceded by `oracle.may_*` and
  followed by `note_actuation` in the same function, or (ii) explicitly
  documented as out-of-scope (humidity fans, light domain, unrelated switch
  domain) with a comment citing this planning doc.
- **Live:** the audit itself; enumerated writer list committed as
  `docs/reviews/code-review/vX.Y.Z_fan_layer_writer_enumeration.md` before
  deploy.

### D9 — Design-doc write-back

**Files:** `docs/Coordinator/HVAC.md` (create fan section if absent) —
document the layer, the trigger vocabulary, the discharge table, INV-FLA,
and W8/W9 gating as intentional behavior changes.

### D10 — README write-back (post-live-validation, mandatory)

**Files:** `docs/readmes/README_v<version>.md` — replace prospective Live
criteria with observed results table. INV-FLA carries a PASS row per writer;
cite the activity_log or absence thereof as authoritative signal.

---

## 11. Sharpest risk

**Not W8/W9 (they're additions) — the sharpest risk is Ledger-Reader parity
across the two field-splits already-in-place** (`RoomFanState.manual_off_cooldown_until`
+ `RoomFanState.manual_on_hold_until`) becoming delegate-reads in D4.

Every reader of those fields today must return byte-identical values before/after the delegation. The real enumeration — obtained by `git grep -n 'manual_off_cooldown_until\|manual_on_hold_until' custom_components/universal_room_automation/domain_coordinators/{hvac_fans,presence_fan_recheck}.py` on branch tip `233531f37` — is:

**`hvac_fans.py` (34 hits):**
- Field decls + docstrings: `:85, :92, :93, :96, :98` (5 hits — deleted with dataclass fields).
- Writes cleared on toggle-off: `:221, :225`.
- External-off adopt path (write cooldown, clear hold): `:308, :312`.
- External-off expiry clear: `:323, :325`.
- External-on adopt path (write hold): `:335, :339`.
- Log line hold-state: `:342, :344`.
- Guard on external-on suppression: `:356`.
- External-adopt commentary + write hold: `:401, :403, :404, :411, :415`.
- Log line hold-state (adopt): `:418, :420`.
- Evaluate-path cooldown READ + expiry: `:638, :641, :651` (READER).
- Adopt-fan speed-write cooldown comment + READ + double-clear: `:838, :842, :844, :847, :849` (READER + writes).
- Restore-after-recheck logic: `:1069, :1076, :1079, :1081, :1089` (READER + writes).
- Diagnostic log line: `:1212`.
- Internal-write commentary: `:1427`.
- Pause-context adjustment: `:1469, :1474, :1477, :1484` (READER + writes; adjusts hold with `manual_on_hold_paused_at`).
- Diagnostic filter (sensor payload): `:1588, :1589, :1597, :1600` (READERS — feed diagnostic sensors).

**`presence_fan_recheck.py` (3 hits):**
- Comment: `:410`.
- Guard READ: `:1002`.
- Parse READ: `:1007`.

**Classification for delegation:**
- READ-only sites (must migrate to `oracle.get_state(room).<field>`): `hvac_fans.py:638, :641, :651, :842, :844, :1076, :1079, :1212, :1469, :1474, :1588, :1589, :1597, :1600`; `presence_fan_recheck.py:1002, :1007`. Total ~16 reads.
- WRITE sites (deleted with the field; behavior migrates INTO the oracle): `hvac_fans.py:221, :225, :308, :312, :325, :335, :339, :411, :415, :847, :849, :1081, :1089, :1477`. Total ~14 writes.
- Log/comment sites (adjust to reference the ledger by name): `:85, :92, :93, :96, :98, :342, :344, :356, :401, :403, :404, :418, :420, :1427, :410`.

Reviewer B enumerates and diffs each READ site against a pre/post fixture; Reviewer C runs the §7.10 None-substitution drill on each of the 16 reads. If ANY reader is missed, we get a diagnostic
regression (recheck's cooldown veto stops firing) or a stale-cache incident
(HVAC evaluate reads a stale field while the ledger has advanced). This is
the Bug Class #22 shape that produced 6 CRITICAL findings on v4.6.3's first
review pass — hence Tier 3 with mandatory Reviewer B enumeration of readers.

Secondary risk: W8/W9's intentional behavior change. If a legitimately-vacant
zone contains a fan whose hold is live because of a stale detection (adopt
misfire on some earlier boot), the sweep will NOT clear it and it may run
until the hold expires. Bounded (default 3600s) and self-heals; called out
in D6's `activity_log` telemetry so the operator can see WHY the sweep was
deferred.

Tertiary risk: shape (b) relies on grep discipline. Reviewer D + a repo
convention (`git grep` in the pre-deploy zero-bugs gate) mitigates but does
not eliminate. Documented under §6.5's promote-to-(a) evidence trigger.

---

## 12. Estimated cycle size

- Diff: **~1200 LoC net additions, ~500 LoC net deletions** (grew from 800/400 after C1/C2 added W11/W12, §7.7-§7.13 added Snapshot + Lock + Exception posture + PauseContext + delegation audit table + AST adjacency tool). Comparable to FAN-MANUAL-1 x 1.5.
- Test additions: **~45-50 new tests** across the 14 sub-sites (parity per writer + discharge table + kill switch + restart + recheck restore + safety override + pre-arrival cooldown-defer + snapshot required-arg smoke + lock-race Reviewer-B tests + 4 exception-posture tests + None-substitution reader drills + boot-order fixture + write-volume regression).
- Reviewers: 4 (Tier 3). Runtime ~24-48h wall clock.
- Fix-up passes: budget 1-2.

**Underrun is an audit trigger.** If the built cycle lands materially below (say < 900 LoC or < 35 tests), the orchestrator MUST audit for silently-dropped scope BEFORE dispatching reviewers. A quiet underrun on a Tier 3 extraction usually means an emission site was forgotten (Reviewer D's whole job) — better to catch it before three reviewers converge on a false SHIP.

---

## 13. Non-goals

- **No new fan POLICIES.** Cooldown length, hold length, sleep cap,
  hysteresis, min-runtime, vacancy hold are ALL byte-frozen. The extraction
  is behavior-frozen except for the ONE intentional W8/W9 gating change
  documented in §5 and D6.
- **No unification of the room-tier vs. HVAC-tier decision sources.** Both
  compute their own `desired_on`; the layer only guards emission.
- **No humidity-fan absorption.** Humidity fans are sole-owner via
  `_humidity_gate` and stay **FULLY OUTSIDE** the layer per M2 (build-prediction)
  decision. The prior draft included a `FAN_TRIGGER_HUMIDITY_ON` "consult
  but always ALLOW" row in W3; both are **deleted**. Humidity does not
  call `may_turn_on`, does not `note_actuation`, is not present in the
  trigger enum. Re-audit trigger: if organic humidity/comfort flap
  evidence appears (e.g. a comfort-fan and humidity-fan on the same
  room sequencing wrong), open a follow-up cycle to fold humidity into
  the layer; do NOT patch it in without a fresh review.
- **No new operator-facing knobs** (see §8).
- **No persistence of the ledger.** RAM-only; adopt-external re-populates on
  boot (existing behavior).
- **No shape (a) gateway construction.** Parked with evidence trigger (§6.5).
- **No W3 turn-ON policy changes.** The AWAY veto (`fan_veto.py`), AI-rules
  R2 residual, and comfort-fan veto interactions are OUT of scope; separate
  cycles.

---

## 14. Plan completion tracking (open items to reconcile at close)

**Hard dependency (L3):** FAN-MANUAL-1 MUST be merged into develop before FAN-LAYER-1 build dispatches. This plan is written against the post-FAN-MANUAL-1 surface (§Base branch: `fan-manual-1` at `233531f37`); the writer table, discharge-table entries for `manual_on_hold_until`, and the `mark_fan_on_issued` seed channel are all FAN-MANUAL-1 artifacts. Building on develop before FAN-MANUAL-1 merges = rebase pain + false-negative Reviewer D findings against a code region that does not yet exist. Kanban ordering: FAN-MANUAL-1 → merge → FAN-LAYER-1 dispatch (with the sensor-cap + HVAC-preset-flap sequencing notes below).


- If shape (a) is chosen instead of (b): re-scope §7 (gateway construction
  + lifecycle), add gateway lifecycle tests, expand Reviewer B surface to
  gateway singleton failure modes. §11 sharpest-risk changes from
  reader-parity to gateway-lifecycle.
- If shape (c) is chosen: drop §7 entirely; deliverables collapse to a
  W8/W9 hotfix pair + a CI grep-lint. Reviewer discipline drops to Tier 2.
- If §2.3 (b)+(c) H8 disposition is rejected: D1 becomes a hard gate; build
  waits on probe row.
- If operator wants a Number entity for `fan_manual_on_hold_s` /
  `fan_manual_off_cooldown_s`: add as D11 (Numbers-Get-Knobs rung 3
  promotion); does not block the extraction.
- Sequencing note: `AUDIT_hvac_duty_cycle_frequency.md` (HVAC-PRESET-FLAP-1)
  is in-flight and touches `hvac.py` near W8/W9. Queue FAN-LAYER-1 build
  BEHIND any HVAC-preset-flap fix that lands in the same function region to
  avoid merge conflicts (worktree isolation covers corruption, not
  conflicts).
- Sequencing note: SENSOR-CAPABILITY-1 fix-up is on `sensor-cap-rebase` and
  edits `coordinator.py`, not the fan surface — no direct conflict, but the
  builder must rebase FAN-LAYER-1 onto develop AFTER sensor-cap ships to
  pick up any downstream ripple to `presence_fan_recheck.py`.

---

## §2.3 addendum — H8 probe RUN 2026-08-11 (orchestrator, live ledger)

The planner could not execute the probe (no shell in its sandbox). Run against
`ura_activity_log` (31-day retention, mode=ro): **ZERO manual/cooldown fan rows exist.** The
v5.31.0 manual-off cooldown has never organically fired in the retention window. H8 is therefore
UNPROVEN organically — and unprovable on any useful timescale, since the triggering event class
(operator manually turns off a comfort fan URA then wants to re-arm) is evidently rarer than the
retention window. Disposition (b)+(c) adopted: in-suite proof (33 FAN-MANUAL-1 tests incl. the
cooldown surface) + the extraction making both policies mutation-provable IS the gate. If the
operator prefers to wait for an organic row, say so — but the probe says that wait is unbounded.

---

## Plan review record (Tier-3 plan reviews — both PLAN-NEEDS-REVISION, revised 2026-08-11)

Two framing-disjoint plan reviews ran against the pre-revision draft (per the CLAUDE.md Tier-3 plan-review protocol added 2026-08-11). Both returned PLAN-NEEDS-REVISION. All findings are dispositioned below; every finding is reflected in the revised sections cited.

### Review 1 — Completeness / independent re-enumeration

| # | Sev | Finding | Disposition |
|---|---|---|---|
| C1 | HIGH | Missing writer W11: `hvac._stop_all_fans_safety` (`hvac.py:2331-2362`) — mass fan-off on smoke/CO/hazard iterates `CONF_FANS` and emits raw `services.async_call`; bypasses layer entirely. | ADOPTED. Added W11 row to §3.1, `FAN_TRIGGER_SAFETY_STOP` to §7.2, W11 row to §7.4 (safety=True, always ALLOW, pre-safety verdict logged), D6a deliverable in §10 with Reviewer C consult-fires-AND-override-wins test. §1 carve-out updated to route safety consults through the layer instead of bypassing. |
| C2 | HIGH | Missing writer W12: `hvac_predict._activate_zone_fans` (`hvac_predict.py:1031-1102`) — pre-arrival TURN-ON path bypasses layer AND manual-OFF cooldown. | ADOPTED. Added W12 row to §3.1, `FAN_TRIGGER_HVAC_PREARRIVAL_ON` to §7.2 (split from W9's OFF trigger), W12 row to §7.4 with explicit "DEFER under live manual-OFF cooldown" semantic + rationale, D6b deliverable in §10 with defer/allow test pair. |
| H2 | HIGH | §11 "sharpest risk" cites `hvac_fans.py:295, 586, 792, 1272, 1395, 1401` as the reader-seed; those line numbers are the DOC-2 planner's memory, not the real enumeration. | ADOPTED. Replaced §11 with the full `git grep` output on branch tip `233531f37` (34 hits in `hvac_fans.py`, 3 in `presence_fan_recheck.py`), classified into 16 reads / 14 writes / rest log/comment. |
| H3 | HIGH | Trigger vocabulary missing SAFETY_STOP, HVAC_PREARRIVAL_ON, and conflates room-tier vs HVAC-tier sleep-onset under a single SLEEP_ONSET_ON. | ADOPTED. §7.2 gained SAFETY_STOP, HVAC_PREARRIVAL_ON, and split SLEEP_ONSET_ON (room-tier) vs HVAC_SLEEP_ONSET_ON (HVAC-tier). §7.4a routing table enforces axis/trigger match. |
| H1 | HIGH | Fan-attribute writes at `hvac_fans.py:1541/1554/1567` (preset/oscillate/direction during recheck-restore) aren't covered by an explicit consult and aren't excluded. | ADOPTED (option (b) explicit §1 carve-out). Documented as state-restoration-only, covered by the parent `may_turn_on(RECHECK_RESTORE)` consult that wraps the restore block. No per-attribute consult (rejected option (a) as needlessly tripling diff). |
| M1 | MED | Mechanical adjacency ("consult IMMEDIATELY precedes emit") is asserted but has no verification procedure. | ADOPTED. Added structured-grep + throwaway AST walker procedure to §9-C; committed as `quality/tools/audit_fan_adjacency.py` and re-run in D8. |
| M2 | MED | No one-line boundary statement vs SignalTrustLedger (verdict-only vs verdict+actuation). | ADOPTED. §7.12 added with the load-bearing distinction (fan needs atomic baseline observation → verdict+actuation). |
| M3 | MED | No list of writers needing NEW parity fixtures. | ADOPTED. New parity fixtures required for W5 (kill switch), W8 (HVAC vacancy sweep), W9 (HVAC pre-arrival OFF), W10-restore (recheck restore), W11 (safety stop), W12 (pre-arrival ON) — enumerated in D6/D6a/D6b/D7 test lists. |
| M4 | MED | D2 does not include an external-consumer grep for trigger vocabulary strings. | ADOPTED. §7.2 addendum requires enum VALUES be string-identical to current log literals AND requires D2 external-consumer grep across `dashboard*/`, shipwatch fixtures, `docs/reviews/*`. |
| L1 | LOW | §2.2 #2 wording overstates operator-silence as confirming H8. | ADOPTED. Rewritten as "unbounded-absence observation, keeps H8 non-falsified but does not confirm". |
| L2 | LOW | Size estimate stale after C1/C2 additions. | ADOPTED. §12 revised to ~1200 LoC / 45-50 tests + underrun-audit-trigger clause. |
| L3 | LOW | FAN-MANUAL-1-merged dependency is implicit in §Base branch but not called out as a hard gate. | ADOPTED. §14 gained a "Hard dependency" line stating FAN-MANUAL-1 must merge to develop before FAN-LAYER-1 dispatches. |

### Review 2 — Build-prediction ("what will the builder get wrong reading this?")

| # | Sev | Finding | Disposition |
|---|---|---|---|
| H1-BP | CRIT | Oracle signature under-specifies the "snapshot" — a builder will either invent a shape or pass raw dicts. Loose kwargs will let the oracle be called from a fixture without the decision context, producing false-PASS parity fixtures. | ADOPTED. §7.8 pins `FanDecisionSnapshot` as a frozen slots dataclass with the exact fields listed, required-positional, no default. Missing snapshot = TypeError. Parity fixtures rejected by loader if snapshot column absent. |
| H2-BP | CRIT | INV-FLA as written is atemporal; under async, a naive consult→emit can be interleaved by an external-ON dispatch landing on the state bus during the `await services.async_call`. | ADOPTED. §1 unchanged text-wise but §7.9 adds INV-FLA-T (temporal restatement) + per-room `asyncio.Lock` owned by the oracle + `oracle.actuate(...)` context-manager helper that acquires the lock across consult→emit→note. Reviewer B test `test_external_on_racing_ura_off_is_blocked_room_<X>` dispatches external-ON during an awaited OFF and asserts VETO on the critical-section re-consult. |
| H3-BP | HIGH | The 7 reader-site delegation via `@property` invites the silent-None class of bugs (v4.6.3 CRIT cluster). | ADOPTED. §7.10 decides: HARD REMOVE the `RoomFanState` fields; rewrite each reader to `oracle.get_state(room).<field>` explicitly. No @property, no `__getattr__`. Reviewer B audit table + Reviewer C per-reader None-substitution drill. Field enumeration in §11. |
| H4-BP | HIGH | D2–D7 could be split across multiple PRs; a partial merge leaves INV-FLA trivially violated. | ADOPTED. §10 preamble: D2–D7 + D6a + D6b = ONE PR, ONE deploy. Per-deliverable sub-invariant table so INV-FLA is only claimed at D8. |
| H5-BP | HIGH | Oracle exception posture unspecified. A raise propagating from `may_turn_off` into a writer's error path would cause fan-stuck-ON. | ADOPTED. §7.11 specifies: `may_turn_off` exception = ERROR + ALLOW (fan turns off), `may_turn_on` exception = ERROR + VETO (fan stays off), `note_actuation` exception = ERROR + no-op, `get_state` exception = ERROR + empty ledger. Four tests. |
| H6-BP | HIGH | Size estimate too low; a builder will underrun and silently drop scope. | ADOPTED. §12: ~1200 LoC / 45-50 tests + explicit underrun-audit-trigger clause instructing the orchestrator to audit for dropped scope on underrun BEFORE dispatching reviewers. |
| M1-BP | MED | `sleep_axis` mismatch between W2/W3 (room-tier) and W4/HVAC (house-state) needs an explicit routing table so the builder doesn't try to merge them. | ADOPTED. §7.4a added: snapshot carries `sleep_axis`, oracle VETOs on trigger/axis mismatch. Axes remain per-caller. |
| M2-BP | MED | Humidity as "consult but always ALLOW" is a footgun — a future edit could flip that ALLOW to a real veto and silently kill humidity fans. | ADOPTED per reviewer recommendation. §13 M2 decision: humidity is FULLY outside — no trigger member, no consult, no note. Re-audit trigger recorded (flap evidence). |
| M3-BP | MED | `note_actuation` on every tick × every writer × 40 rooms = potential write-flood (see optimizer incident). | ADOPTED. §7.14 added: edges-only (verdict-change per `(room,trigger_path,hold_id)`); regression test `test_note_actuation_write_volume_40_rooms_3600s` asserts < 200 rows/hour; cites `project_optimizer_db_write_flood_incident_2026_06_09.md` as the reason for the budget. |
| M4-BP | MED | Reviewer C drill list of 10 sites is too small; W11/W12 add more, and W5/W6-adopt-on/W6-adopt-off are missed. | ADOPTED. §9-C expanded to 14 sub-sites: W1, W2, W3-temp, W3-sleep, W4, W5, W6-adopt-on, W6-adopt-off, W7-ON, W7-OFF, W8, W9, W10-pause, W10-restore, W11, W12 (14+2 = 16 counting split of W11/W12; §9-C says "14 sub-sites" for the mutation drill plus §7.10 reader drill on the 16 read sites from §11). |
| L1-BP | LOW | Lock granularity unspecified. | ADOPTED. §7.9 states per-room lock, no serialization across rooms. |
| L2-BP | LOW | `PauseContext` referenced but not defined. | ADOPTED. §7.13 adds the frozen slots dataclass definition + credit-paused-duration test. |
| L3-BP | LOW | §7.7 promises a grep to prove oracle-before-writers boot order — a grep is not a test. | ADOPTED. §7.7 replaces the grep-promise with a `test_fan_oracle_constructed_before_writers` fixture test that records construction order and asserts. |

### Overrides / non-adoptions

None. Every finding from both reviews was adopted as written (or as the reviewer's stated recommendation, where a choice was offered — noted inline). No reviewer decision was overridden. Two places offered options and the plan now records the pick with justification: H1 completeness (option (b) explicit carve-out over option (a) per-attribute consult) and M2-BP (fully-outside humidity over "always ALLOW consult").

### Final estimate

- Diff: ~1200 LoC additions / ~500 deletions.
- Tests: 45-50 new tests.
- Tier 3, 4 framing-disjoint code reviews + orchestrator independent verification + operator checkpoint before deploy.
- Wall-clock: 3-5 days from build dispatch to deploy, given operator-checkpoint gate.
- Hard dep: FAN-MANUAL-1 merged to develop first.
