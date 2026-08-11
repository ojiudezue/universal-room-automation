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
>     separately via `_humidity_gate`.
>   * safety-bypass paths (smoke, freeze protection) — MUST consult the layer
>     but MAY override its verdict with a `safety=True` argument that the
>     layer logs and honors.
>   * operator kill-switch mass-off (`turn_off_all_managed`) — routes through
>     the layer with `trigger_path="fan_control_disabled"` which the layer
>     recognizes as unconditional and clears the manual-ON hold ledger.

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
   that window (evidence trigger #2 in the original gate). Absence is not
   proof but is consistent with H8 holding.
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

**"Five writers" per the FAN-MANUAL-1 origin claim is a floor, not a ceiling.**
W1, W2, W4, W7, W8 = the five that were the framing. W3 is the seed-authored
ON path; W6 is a detection-only writer to state (not a service call, but
gates future service calls); W9 (`hvac.py:2629-2643`) and W10 (recheck) are
additional writers. **The real fan-surface writer set is 8-10 sites across
5 files, not 5.** Every plan below budgets for this.

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
FAN_TRIGGER_TEMP_ROOM        = "temp_room"          # W1
FAN_TRIGGER_SLEEP_OFF        = "sleep_off"          # W2
FAN_TRIGGER_SLEEP_ONSET_ON   = "sleep_onset_on"     # W3 (subset)
FAN_TRIGGER_TEMP_ROOM_ON     = "temp_room_on"       # W3 (subset)
FAN_TRIGGER_HUMIDITY_ON      = "humidity_on"        # W3 (subset — humidity carve-out; consult but oracle always ALLOWs sole-owner path)
FAN_TRIGGER_TEMP_HVAC        = "temp_hvac"          # W4 emit
FAN_TRIGGER_KILL_SWITCH      = "fan_control_disabled" # W5
FAN_TRIGGER_RECONCILE_ON     = "reconcile_on"       # W7 ON
FAN_TRIGGER_RECONCILE_OFF    = "reconcile_off"      # W7 OFF
FAN_TRIGGER_HVAC_VACANCY     = "hvac_vacancy_sweep" # W8
FAN_TRIGGER_HVAC_PREARRIVAL  = "hvac_prearrival"    # W9
FAN_TRIGGER_RECHECK_PAUSE    = "recheck_pause"      # W10
FAN_TRIGGER_RECHECK_RESTORE  = "recheck_restore"    # W10
FAN_TRIGGER_SAFETY           = "safety"             # smoke / freeze
```

Reviewer B validates: every writer names its trigger; no free-string
paths. Reviewer D validates: adding a NEW trigger constant does NOT
regress any existing verdict.

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
| W3 room ON (temp / sleep / humidity) | `may_turn_on(room, TEMP_ROOM_ON \| SLEEP_ONSET_ON \| HUMIDITY_ON)` | `note_actuation(room, "on", <trigger>)` | note REPLACES `mark_fan_on_issued`; humidity path stays sole-owner (oracle always ALLOWs) but consults for cross-writer no-flap |
| W4 HVAC OFF chokepoint | `may_turn_off(room, TEMP_HVAC)` | `note_actuation(room, "off", TEMP_HVAC)` | field split: existing `RoomFanState.manual_off_cooldown_until` READS delegate to ledger; writes removed |
| W5 kill switch | `may_turn_off(room, KILL_SWITCH)` — always ALLOW; layer clears hold | `note_actuation(room, "off", KILL_SWITCH)` | mass reset behavior preserved |
| W6 detection-only | n/a (state observation) | `note_actuation` when external transition observed | `_last_seen_any_fan_on` baseline moves into ledger |
| W7 reconciler | consult per direction | note per direction | replaces `is_fan_in_manual_on_hold()` peek (line 618) and `mark_fan_on_issued()` seed (line 637) with layer consult/note |
| W8 HVAC zone-vacancy sweep | `may_turn_off(room, HVAC_VACANCY)` | `note_actuation(room, "off", HVAC_VACANCY)` | **BEHAVIOR CHANGE** (§5): was bypass; now gates on cooldown + hold |
| W9 HVAC pre-arrival | `may_turn_off(room, HVAC_PREARRIVAL)` | `note_actuation(room, "off", HVAC_PREARRIVAL)` | **BEHAVIOR CHANGE** (§5): was bypass; now gates on cooldown + hold |
| W10 recheck pause | `may_turn_off(room, RECHECK_PAUSE)` — always ALLOW; layer pauses hold deadline | `note_actuation(room, "off", RECHECK_PAUSE)` | replaces `_fan_in_manual_cooldown` private-field peek at :1002-1007 with `oracle.get_state(room).manual_off_cooldown_until` |
| W10 recheck restore | `may_turn_on(room, RECHECK_RESTORE)` — ALLOW iff hold was live at pause | `note_actuation(room, "on", RECHECK_RESTORE)` | resumes hold with paused-duration credited |

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
  W1, W2, W3, W4, W7-ON, W7-OFF, W8, W9, W10-pause, W10-restore: comment
  out the `may_turn_*` consult AND the `note_actuation` call at that site
  individually, run the suite, confirm a NAMED test fails. Restore.
  Aggregate monkeypatch of oracle predicates is NOT sufficient. Per
  `feedback_mutation_verification_pycache_staleness.md`, disable bytecode
  caching before drill.
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

Every reader of those fields today (`hvac_fans.py:295, 586, 792, 1272, 1395,
1401`; `presence_fan_recheck.py:1002-1007`) must return byte-identical values
before/after the delegation. If ANY reader is missed, we get a diagnostic
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

- Diff: ~800 LoC net additions, ~400 LoC net deletions (removes duplicated
  state-field bookkeeping, adds oracle + delegates). Similar in size to
  FAN-MANUAL-1's cycle.
- Test additions: ~25 new tests across the 10 writer-sites (parity per
  writer + discharge table + kill switch + restart + recheck restore).
- Reviewers: 4 (Tier 3). Runtime ~24-48h wall clock.
- Fix-up passes: budget 1-2 (FAN-MANUAL-1 needed 1 CRIT-fix pass; this
  cycle is bigger but the writer surface is well-audited by then).
- Total: comparable to a v5.x minor bump. Not a major.

---

## 13. Non-goals

- **No new fan POLICIES.** Cooldown length, hold length, sleep cap,
  hysteresis, min-runtime, vacancy hold are ALL byte-frozen. The extraction
  is behavior-frozen except for the ONE intentional W8/W9 gating change
  documented in §5 and D6.
- **No unification of the room-tier vs. HVAC-tier decision sources.** Both
  compute their own `desired_on`; the layer only guards emission.
- **No humidity-fan absorption.** Humidity fans are sole-owner via
  `_humidity_gate` and stay outside INV-FLA. A future cycle may fold them
  in; not this one.
- **No new operator-facing knobs** (see §8).
- **No persistence of the ledger.** RAM-only; adopt-external re-populates on
  boot (existing behavior).
- **No shape (a) gateway construction.** Parked with evidence trigger (§6.5).
- **No W3 turn-ON policy changes.** The AWAY veto (`fan_veto.py`), AI-rules
  R2 residual, and comfort-fan veto interactions are OUT of scope; separate
  cycles.

---

## 14. Plan completion tracking (open items to reconcile at close)

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
