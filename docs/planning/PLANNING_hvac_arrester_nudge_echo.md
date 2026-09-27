# PLANNING — HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1

**Card:** `HVAC-ARRESTER-NUDGE-ECHO-FALSE-OVERRIDE-1` (HVAC arc, W1-A consumer gap
identified 2026-09-26 — see `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
§10 C23).
**Tier:** **Tier 2-DB** — operator-elevated. Arrester detection is a
trust-hierarchy hinge: a wrong call either strands the zone in URA's own
lockout (present state) or blinds URA to a real human at the dial. Three
framing-disjoint reviews + live validation + README write-back.
**Read-first:** `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md`
(complete; §6 nudge/borrow, §7 arrester + dual suppression windows, §10
C17/C20/C21/C22/**C23**) and `docs/readmes/README_v5.103.16.md` (W1-A
`climate_write` schema).

---

## Falsifiable invariant (state up front — D exists to break this)

**INV-ECHO:** *For any URA-originated `climate.set_temperature` write on
entity E at wall-clock T with service data S, the FIRST recorder state event
on E in `[T, T + ECHO_WINDOW_S]` whose observed setpoints are equal, under
the Bryant display quantization Q, to `S.target_temp_high` / `S.target_temp_low`
that URA actually asserted, is NEVER booked as `override_detected`. Any
state event on E that is not equal to URA's last-asserted values under Q,
or that occurs after `T + ECHO_WINDOW_S`, is subject to the pre-existing
arrester logic unchanged (in particular, a genuine human dial to a
DIFFERENT value inside the window remains genuine).*

Reviewer D's job: find a legal-config reachable path where either half of
INV-ECHO is violated — a URA nudge echo booked as override, OR a genuine
human touch swallowed.

---

## 1. Problem — measured (§10 C23)

- Since 2026-09-19, **24 of 52 `override_detected` rows** on the three
  Carrier zones are the thermostat's echo of URA's own nudge, arriving
  **5.3–7.5 s** after `nudge_started`. The URA suppression TTL is 5 s
  for temp writes (`hvac_override.py:133` `SUPPRESS_TTL_SECONDS`,
  deliberately short, `:141-146`) so `_is_genuine_manual`
  (`hvac_override.py:2419-2468`) returns True on TTL expiry and the row
  falls through to normal delta logic.
- URA wrote e.g. 77.5°F; the entity re-emits a whole-degree 78°F (Bryant
  quantizes cool setpoints to integer °F — see §4 rounding).
- **22 of 24** are followed by `preset_change_locked_out` within 30 min
  because S1 refuses to write a preset over `manual` (`hvac_preset.py:212-217`,
  `hvac.py:2484-2539`), and the arrester declines to revert a zero-delta
  hold (§7 of state-of-play). Net harm: self-lockouts caused by URA's own
  nudges.

**Root cause:** the arrester has no per-entity record of what URA JUST
wrote. Suppression is a coarse time window; provenance is inferred from
"is it manual now?", not from "does the new value equal what we wrote?".

---

## 2. Institutional context verified

**Design docs / precedence:**
- `docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` — read completely.
  §7 confirms the two-window suppression (C17), §10 C20/C21 rule out
  simple "trust `hold_activity`" answers, §10 C22 explicitly says neither
  feed is oracle, §10 C23 is this card. §11 W1-A already ships the
  fact-of-write ledger this plan reuses for out-of-band audit (but NOT
  for the inline arrester decision — see §7 provenance ownership note).
- `docs/readmes/README_v5.103.16.md` — `climate_write` row has
  `values_after` = exact service data + `issued_wallclock`. Persisted but
  fire-and-forget → **not usable for a synchronous arrester decision**.
  Reused only for the post-ship disposition query.

**Code locations surveyed end-to-end:**
- `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py`
  (funnels, `_snapshot_climate_state`, `_schedule_climate_write_row`,
  `emit_set_temperature`, `emit_set_preset_mode`, `emit_set_hvac_mode`).
- `.../hvac_override.py` lines 100–170 (constants + `_suppressed_until` /
  `_suppress_kind` / `_nudge_pre_preset` dicts — the existing per-entity
  in-memory pattern to extend); `:2419-2468` (`_is_genuine_manual` — the
  single load-bearing site the fix modifies); `:2764-2799` (`suppress`,
  `unsuppress`); `:3130-3210` (delta computation from event `old_high` /
  `old_low`); `:4400-4480` (S5 nudge start — the primary producer).
- `/Users/okosisi/ha-config/custom_components/ha_carrier/climate.py:467-537`
  (`async_set_temperature` — sends `str(heat_set_point)` / `str(cool_set_point)`
  to the Bryant cloud with NO HA-side rounding, optimistically writes
  local `manual_activity.*` at the exact requested value; whole-degree
  display therefore originates from the Bryant cloud reply / thermostat
  quantization, not from ha_carrier). Confirms the probe's rounding hunt
  is a real physical question, not a HA integration artifact.
- `custom_components/universal_room_automation/database.py:1502-1531`
  (`ac_ramp_events` schema: `target_high` yes, `target_low` no — probe
  compensates by joining with `climate_write` rows post-2026-09-26 20:23Z).

**Prior planning docs consulted:**
- `docs/planning/PLANNING_hvac_w1a_thermostat_write_governance.md` —
  established the `climate_write` row + `values_after` shape reused here
  for audit. Confirms the funnel-level snapshot is *fire-and-forget* /
  DB-only; provenance for a synchronous consumer (this cycle) has to be
  in-memory.

**Memory bodies pulled:**
- `reference_hvac_state_of_play.md`, `feedback_do_robust_fix_not_bandaid_and_card.md`
  (do the robust fix here — a per-value provenance record is the small
  right primitive, not a widened blind TTL).

**Prior-art scan (Tier 2+ REUSE-or-BUILD ledger):**

| Piece proposed | REUSE / BUILD | Cite |
|---|---|---|
| Per-entity in-memory dict keyed by entity_id, keyed inside `OverrideArrester` | **REUSE** the pattern of `self._suppressed_until` / `self._suppress_kind` / `self._nudge_pre_preset` | `hvac_override.py:239-266` |
| Wall-clock capture at ISSUE time (not return) for the record's timestamp | **REUSE** the `issued_wallclock` idea already stamped by the W1-A funnel | `hvac_setpoint.py:227, 439, 568, 634, 668, 780` |
| Snapshot helper that reads live state pre-await | **REUSE** `_snapshot_climate_state` (moved / promoted to a shared read; the W1-A snapshot is already this shape) | `hvac_setpoint.py:127-160` |
| Suppression `suppress()`/`unsuppress()` and TTL constants | **REUSE unchanged**. The fix ADDS a per-value record; the 5 s temp / 120 s preset TTLs stay as-is | `hvac_override.py:129, 158, 2764-2799` |
| `_is_genuine_manual` predicate | **EXTEND** (not rewrite): one added early branch consulting the last-write record — mid-window passthrough logic preserved | `hvac_override.py:2419-2468` |
| A shared "what did URA just write to E" read API (W1-B problem 1 will reuse) | **BUILD** — the record itself, exposed as a small read-only helper on `OverrideArrester` (`get_last_write(entity_id) -> LastWrite | None`) or promoted to a `hvac_writeprov.py` module. Design decision left in §4; the record is not arrester-private state | new (small, ≤ ~80 LoC) |
| Echo window constant | **NEW** module const in `hvac_override.py` — sized from measured p95 (§4). Rung 1 (safety-adjacent) per Numbers-Get-Knobs |
| Rounding function `bryant_display_round` | **NEW** small pure helper in `hvac_setpoint.py` (co-located with the funnels since it names Bryant behaviour). Determined empirically by the probe (Q1); NOT a knob (would invite drift) |
| Any new sensor / entity / config field | **NONE** — arrester internals only |

Grep evidence for "does anything already record URA's last write in memory?":
`git grep -n "last.*write\|_last_emit" hvac_override.py hvac_setpoint.py` →
`hvac.py:521 _last_emitted_range` is a compose-away throttle (`hvac.py`,
NOT the arrester's entity, per-zone not per-entity, dormant with D9).
`_nudge_pre_preset` records the PRE-nudge PRESET only (not the written
values). No per-entity written-values record exists. **BUILD** is justified.

---

## 3. Producer + Consumer check

### Producer of the new record
- **Written by:** every URA temperature funnel exit that actually issued a
  wire call — i.e. inside `emit_set_temperature` on the SUCCESS path,
  AFTER the service call returns and BEFORE `_schedule_climate_write_row`.
  Preset writes DO NOT write the record (they don't change setpoints).
  `emit_set_hvac_mode` doesn't either.
- **Values recorded (per entity_id):**
  `{ verb: "set_temperature",
     issued_wall: iso,
     issued_monotonic: float,
     target_low: float | None,   # exactly what went to service_data
     target_high: float | None,
     freeze_active: bool,         # transform provenance
     applied_low: float | None,   # post-freeze/deadband (what actually shipped)
     applied_high: float | None,
     site: str, zone_id: str, reason: str, excursion_id: str | None }`
  Both raw and applied are captured so the echo comparator can prefer the
  APPLIED values (what the cloud actually saw). No hold on unbounded
  memory: dict is keyed by entity_id (≤ 3 climate entities in this house),
  entries overwritten on next write.
- **Producer health depends on:** `hass.services.async_call` returning
  without raising; the current write path already does. Failure paths do
  NOT populate the record → next `_is_genuine_manual` falls back to
  today's behaviour (fail-open into the existing TTL passthrough — no
  regression).

### Consumers
- **Inline (this cycle):** `_is_genuine_manual` at `hvac_override.py:2419-2468`.
  Only consumer that alters behaviour.
- **Future (W1-B problem 1, presets-only returns):** the same read API is
  called by the borrow-restore path to check "did the manual hold appear
  at values URA just wrote → provenance is URA → reclaim without
  fighting". Reason to expose as a small primitive, not arrester-private:
  the W1-B builder should not reach into `OverrideArrester._last_write`.

Consumer + call-site check today: the ONE inline consumer is the exact
site named above; grep `_is_genuine_manual` = one caller
(`hvac_override.py` `_handle_climate_change`). No indirect consumers.

---

## 4. Design (validates & refines the operator's direction)

The operator's proposed direction is **correct** in shape. Two refinements:

1. **Compare APPLIED values, not the raw request.** `emit_set_temperature`
   already runs `apply_setpoint_guards` (freeze floor + deadband invariant)
   before the wire call. If URA requests 76 low / 74 high and the freeze
   floor bumps low to 40, the ECHO comes back at the applied values, not
   the requested ones. Record BOTH; the comparator uses applied. (Pure
   correctness — costs one extra float in the dict.)
2. **Round both sides consistently.** The probe (Q1) determines the Bryant
   display quantization. Whatever it is, the comparator applies the same
   function to URA's written value and the observed value, and compares
   INTEGERS. Do NOT compare floats. If Q1 reports mixed modes, freeze on
   the winning mode and card the residual (do not soften).

**Echo-window semantics** — the window is a WALL-CLOCK gate on the state
event's `last_updated`, measured from URA's `issued_wall`, not from
`suppress()`'s TTL. This is deliberately independent of `SUPPRESS_TTL_SECONDS`
(5 s stays — it protects legitimate mid-window passthrough for a genuine
human flip to `manual`). Design:

- `ECHO_WINDOW_S = ceil(p95_lag) + 3 s headroom`, from Q1 of the probe;
  clamped to `[10, 30]` as a safety envelope. Rung 1 module constant in
  `hvac_override.py`.
- Only asserted sides count. If URA wrote only `target_temp_high`
  (cool-mode nudge), the comparator ignores the LOW side of the observed
  event.
- Record consumed exactly once. On a match, `_is_genuine_manual` clears
  the record for that entity (mirroring the existing suppression cleanup
  in `_is_genuine_manual:2449` / `:2465`). A second echo would then
  passthrough — the intended fail-open.
- Non-matching change inside the window → today's behaviour (the record
  is NOT cleared; the write's own 5 s TTL still governs `manual`
  passthrough). Genuine human dial to a DIFFERENT value is still genuine.

### Modified `_is_genuine_manual` (behavioural sketch — not the diff)

Insert ONE branch immediately after the `new_state`/`old_state` extraction
and BEFORE the existing `until = self._suppressed_until.get(entity_id)`
block:

```
last = self._last_write.get(entity_id)
if last is not None:
    now_wall = dt_util.now()
    if (now_wall - last.issued_wall).total_seconds() <= ECHO_WINDOW_S:
        # only assessed sides count
        if last.matches_observed(new_state.attributes,
                                 rounder=bryant_display_round):
            # URA echo — clear record and return NOT-genuine.
            self._last_write.pop(entity_id, None)
            return False
```

Everything below is unchanged. The mid-window `preset_mode -> manual`
passthrough for a genuine human continues to fire whenever the observed
values DO NOT equal URA's last write.

### Where the record lives

Store on `OverrideArrester` as `self._last_write: dict[str, _LastWrite]`
(dataclass or plain dict — dataclass preferred for immutability + a
`matches_observed` method). Populate from `emit_set_temperature` by a
CALLBACK the funnel accepts, **NOT** by importing the arrester into the
funnel (avoid the circular import that the existing `_capture_preset_reason`
navigates via `hass.data[DOMAIN]`). Follow the exact `_capture_preset_reason`
shape: fetch `manager.coordinators.get("hvac")`, then the arrester off
the coordinator, then set the record. Best-effort, never raises. This
keeps `hvac_setpoint.py` free of arrester imports.

Small read API on the arrester:

```
def get_last_write(self, entity_id: str) -> LastWrite | None: ...
```

W1-B problem 1 (presets-only returns) will call this to detect
URA-provenance manual holds.

---

## 5. Knobs (Numbers-Get-Knobs)

| Knob | Rung | Value | Why |
|---|---|---|---|
| `ECHO_WINDOW_S` | 1 (module const, `hvac_override.py`) | measured `ceil(p95_lag) + 3`, clamped `[10, 30]` | Safety-adjacent — a wrong value blinds arrester to human. Changing requires code review + a repeat probe |
| Bryant display rounding | 1 (module helper `bryant_display_round`) | winner from probe Q1 | Physical vendor behaviour; not an operator preference |
| `SUPPRESS_TTL_SECONDS`, `SUPPRESS_TTL_SECONDS_PRESET` | UNCHANGED | 5 / 120 | Deliberately preserved (state-of-play §7 C17) |
| Any dashboard entity | none | — | Kill switch is unnecessary — fail-open on record miss = today's behaviour |

Kill-switch semantics: absence of a record for an entity → today's code
path runs verbatim. Deploying the fix and then observing no records
populate (e.g. the coordinator wiring is broken) is behaviour-equivalent
to reverting.

---

## 6. Non-goals (explicit)

- **Not** feed-confirmation / "which Bryant feed confirms a write"
  (W1-B problem 6; §9.7 / C22 / C23 open question).
- **Not** presets-only returns / URA-provenance manual-hold reclaim
  (W1-B problem 1). The read API this cycle exposes is the substrate
  W1-B consumes; W1-B is a separate build.
- **Not** widening `SUPPRESS_TTL_SECONDS`. Widening is the seductive
  band-aid — it blinds a human at the dial (state-of-play §7 explicitly
  keeps it at 5 s for that reason).
- **Not** touching preset or hvac_mode writes. Preset writes don't
  produce a setpoint echo; hvac_mode changes don't either.
- **Not** using the `climate_write` DB row as the inline provenance
  source. It is DB-only fire-and-forget, cannot be read synchronously by
  the arrester. Post-ship it remains the AUDIT source (§8 disposition).

---

## 7. Acceptance criteria — DISCRIMINATING

Every criterion states a fix-path observation AND a break-path
observation that would distinguish it from a plausible different failure.

### D0. Probe run — must produce numbers BEFORE build dispatch
- **Verify (fix-path):** `scripts/probes/nudge_echo_probe.py` reports:
  Q1 lag `n ≥ 100`, `p50` and `p95` in `[3.0 s, 15.0 s]`; ONE winning
  rounding mode with `≥ 90%` of matched rows.
- **Verify (break-path):** if Q1 shows `p95 > 25 s` or the rounding mode
  is not a clean winner (`< 80%` for any single mode), the design
  direction is falsified — STOP and card a different fix (e.g. wait for
  a Bryant-side probe with actual thermostat display quantization).
- **Q2 sanity:** with `ECHO_WINDOW_S` set to the probe-derived value,
  Q2b must report **0** FALSE POSITIVES against the known-genuine
  fixture (rows > 60 s from any URA write on that entity), including
  the 2026-09-25 19:17 CDT zone_2 76→77 row.

### D1. Fix implementation
- **Verify:** `_is_genuine_manual` returns False for a synthetic event
  whose observed setpoints equal `_last_write[entity].applied_{low,high}`
  under `bryant_display_round`, when the event's `time_fired` is inside
  `ECHO_WINDOW_S` of `_last_write[entity].issued_wall`.
- **Verify:** it returns True (genuine) for an event with the SAME
  timestamps but DIFFERENT observed values (a human dial to a value URA
  did not write).
- **Verify:** it returns True (genuine) for an event OUTSIDE the window
  even if values match (fail-open: after the window we don't claim
  provenance).
- **Test:** `test_is_genuine_manual_recognizes_ura_echo`,
  `test_is_genuine_manual_still_catches_human_within_window`,
  `test_is_genuine_manual_falls_through_after_window`.

### D2. Fixture — the 24 measured echo rows must classify as URA-echo
- **Verify (test authority):** commit a fixture file
  `quality/tests/fixtures/nudge_echo_rows_2026_09_19_to_26.jsonl` derived
  from the probe output (one row per measured echo: entity_id,
  URA-write-ts, URA-values, observed-ts, observed-values). A test
  replays each row through `_is_genuine_manual` and asserts NOT-genuine
  for all 24.
- **Verify (must-stay-genuine):** the same test replays known-genuine
  rows (Q2b output) and asserts genuine for all of them.

### D3. Per-site mutation drill (Tier 2-DB Review C authority)
- Neuter the population site inside `emit_set_temperature` (comment out
  the callback that writes the record). Run the D1 + D2 suite → D2 MUST
  turn RED on the 24-row fixture. Restore.
- Neuter the read branch in `_is_genuine_manual` (comment the new
  `if last is not None` block). Run → same RED. Restore.

### D4. Live post-restart
- **Live:** after HA restart, dump `ura_activity_log WHERE action = 'override_detected' AND timestamp > <restart_ts>` alongside
  `... WHERE action = 'climate_write' AND verb = 'set_temperature'`; for
  every URA temp write there must be **zero** `override_detected` rows on
  the same entity within `ECHO_WINDOW_S` (post-ship the query in §8).
- **Live:** `preset_change_locked_out` count on zone_1 in the 24 h after
  restart is materially lower than the 22-in-a-week baseline.

---

## 8. Post-ship disposition query (soak-exit forcing function)

Card enters `shipped_organic` at deploy. Discriminator, queried once at
disposition time (soak-exit protocol):

```sql
-- URA temp writes in a 24-h window post-deploy
WITH w AS (
  SELECT entity_id, timestamp AS w_ts,
         json_extract(details_json,'$.values_after.target_temp_high') AS w_hi
    FROM ura_activity_log
   WHERE action='climate_write'
     AND json_extract(details_json,'$.verb')='set_temperature'
     AND timestamp >= :deploy_ts
),
o AS (
  SELECT entity_id, timestamp AS o_ts,
         json_extract(details_json,'$.new_high') AS o_hi
    FROM ura_activity_log
   WHERE action='override_detected'
     AND timestamp >= :deploy_ts
)
SELECT COUNT(*) AS suspected_echoes
  FROM w
  JOIN o USING (entity_id)
 WHERE (julianday(o_ts)-julianday(w_ts))*86400 BETWEEN 0 AND :ECHO_WINDOW_S
   AND CAST(o_hi AS INT) = CAST(ROUND(w_hi) AS INT);  -- replace with winning rounder
```

**Pass:** `suspected_echoes = 0`. **Met-with-residual:** `> 0` but
`preset_change_locked_out` on zone_1 has dropped ≥ 70 % → close primary,
card the residual. **Reopen:** neither.

---

## 9. Tests (behavioural, not source-grep)

- `test_is_genuine_manual_recognizes_ura_echo` (D1)
- `test_is_genuine_manual_still_catches_human_within_window` (D1) —
  discriminator: same timestamps, values DIFFER from URA's last write.
- `test_is_genuine_manual_falls_through_after_window` (D1) — fail-open.
- `test_emit_set_temperature_populates_last_write_record` — verifies
  producer wiring; runs the funnel with a fake `hass.services.async_call`
  and asserts the record is populated with APPLIED (post-freeze/deadband)
  values on the SUCCESS path, and NOT populated on a raising path.
- `test_emit_set_temperature_no_arrester_import_cycle` — imports
  `hvac_setpoint` in isolation (Bug Class awareness: the funnel must
  not create a cycle with `hvac_override`).
- `test_bryant_display_round_matches_probe_winner` — unit test the
  chosen rounding.
- `test_nudge_echo_fixture_replay` (D2) — 24 known-echo rows classify
  as NOT-genuine; N known-genuine rows classify as genuine.
- Per-site mutation drills (D3), documented in the review record.

---

## 10. Rollback

Additive only. No schema change, no config-flow change, no new entity.
Revert the merge → the record dict is unused and `_is_genuine_manual`
returns to today's semantics.

---

## 11. Risks / where design direction might be wrong

Places worth pushing back on the operator's direction (surfaced BEFORE
build per CLAUDE.md "Marginal-benefit / verify claim types"):

1. **"Just past the 5 s TTL" hides a subtler mechanism.** The probe MUST
   show the lag is genuinely a Carrier echo, not a rebound of a URA
   internal repeat (e.g. a second write inside the tick). If Q1 shows
   bimodal lag with a cluster < 3 s, that's a URA-side double-emit and
   the fix is in the producer, not the arrester.
2. **`applied` vs `requested` matters.** If we ONLY record `requested`,
   a freeze-floor bump makes the echo comparator miss the match. The
   plan captures both; do not simplify to one field.
3. **Preset side effects.** A `set_temperature` write flips `preset_mode`
   from e.g. `sleep`→`manual` as a side effect (this is exactly what
   `_nudge_pre_preset` is for, `hvac_override.py:255-266`). The added
   branch fires on the SETPOINT match; the pre-existing "temp"-kind
   passthrough (`_is_genuine_manual:2461-2462`) still handles the
   induced `manual` preset event. Verify no double-classification.
4. **Do not use `climate_write` DB rows for the inline decision.** They
   are async-scheduled; a slow DB stalls the state event's arrival
   ordering vs the row write. Kept for audit only.
5. **Card the W1-B seam explicitly.** The new `get_last_write` read API
   is the primitive W1-B problem 1 will consume; do NOT let W1-B
   duplicate it. Add a `TODO(W1-B)` comment at the read site.

If the probe (D0) invalidates the numeric assumptions, this plan is
withdrawn and re-planned with the measured data before any build.

---

## 12. Review framings (Tier 2-DB — three parallel, framing-disjoint)

- **Review A — data integrity + fail-open correctness.** Record fields,
  types, applied-vs-requested, dict cleanup on match, dict cleanup on
  TTL expiry (does it leak?), race between funnel populate and state
  event arrival (populate happens AFTER `async_call` returns and AFTER
  ha_carrier's optimistic local write — verify ordering does not
  invert). Include the 2-write-in-flight case.
- **Review B — cross-coordinator + lifecycle.** No import cycle
  `hvac_setpoint` ↔ `hvac_override` (funnel calls via
  `hass.data[DOMAIN]["coordinator_manager"]` per `_capture_preset_reason`
  precedent); restart resilience (record is RAM-only, and that's
  correct — a restart drops the record and the pre-existing startup
  audit takes over); interaction with the `_nudge_pre_preset` snapshot.
- **Review C — test authority via per-site mutation.** D3 drills must
  turn D2 RED under EACH neuter; a green-under-neuter site is
  unacceptable.
- **(D optional if elevated.)** Adversarial completeness pass: re-state
  INV-ECHO, look for a legal path where an echo is booked or a human is
  swallowed under a knob combination not covered by A/B/C (e.g. energy
  coast tolerance bonus, comfort-delay grants, egress-paused zones).

Plan-review (Tier 2 pre-build): one adversarial reviewer confirms the
prior-art table with fresh greps and confirms the probe's D0
pass-criteria are the right bar.

---

## 13. Deliverables & files touched

- **NEW:** `scripts/probes/nudge_echo_probe.py` (already written, ready
  to run).
- **NEW:** `quality/tests/fixtures/nudge_echo_rows_*.jsonl` (from probe
  output).
- **MODIFIED:** `custom_components/universal_room_automation/domain_coordinators/hvac_override.py`
  — add `_last_write` dict, `LastWrite` dataclass, `get_last_write`
  read API, `ECHO_WINDOW_S` constant, new branch in `_is_genuine_manual`.
- **MODIFIED:** `custom_components/universal_room_automation/domain_coordinators/hvac_setpoint.py`
  — add `bryant_display_round`; `emit_set_temperature` populates the
  record via `hass.data[DOMAIN]` lookup on the SUCCESS path (mirroring
  `_capture_preset_reason`).
- **NEW tests:** listed §9.
- **README:** `docs/readmes/README_v<next>.md` with Live Validation
  table (§7 D4) — post-ship written back after live run.
- **State-of-play update:** on ship, edit §7 to name the new echo-window
  mechanism and §10 C23 to reference the ship version.

---

## 14. Probe results

**Not yet run.** The probe (`scripts/probes/nudge_echo_probe.py`) is
written and read-only. The planning agent in this session does not have
a shell tool to `ssh ha`; the orchestrator must run:

```
ssh ha "python3 -" < scripts/probes/nudge_echo_probe.py
```

before build dispatch. Its output MUST be pasted into a
`## 14a. Probe results — <run-ts>` section of this doc and satisfy the
D0 gate. If D0 fails, this plan is on hold pending a re-scope.

## 14a. Probe results (orchestrator, 2026-09-26 evening) — supersede the D0 probe's Q1/Q2 numbers

`scripts/probes/nudge_echo_probe.py` ran (read-only) but MEASURED THE WRONG EVENT: its Q1 lag (n=113, p50 1.6 s) is to the
FIRST recorder change after a URA write, which is ha_carrier's optimistic LOCAL copy of URA's own write (C23), not the
cloud echo that the arrester books. Its rounding tally (110/113 "_no_match") and Q2 (2/52 matched) are therefore invalid.
Authoritative numbers, from the orchestrator's direct join (override_detected vs ac_ramp_events nudge_started, same zone,
0–30 s, since 2026-09-19):
- **Echo rows:** 24 of 52 `override_detected` rows (zone_1 17, zone_2 5, zone_3 2); 22 followed by `preset_change_locked_out`
  within 30 min.
- **Echo lag (nudge_started -> override_detected):** min 5.3 s, max 7.5 s (all 24). => `ECHO_WINDOW_S` = **15 s** (2x max),
  rung 1.
- **Rounding:** ha_carrier does not round setpoints (`climate.py` rounds humidity only, `:332`); the whole degree comes from
  Carrier/Bryant. Observed pairs fit ONLY round-half-to-even: 77.5->78, 76.5->76 (half-up would give 77), 79.5->80, 81.5->82.
  Four distinct values is thin evidence for a specific mode, so the comparator is **tolerance-based: |observed - applied| <= 0.5 F
  on each written bound**, not a named rounding mode (robust to whichever mode the device uses; human false-match requires a
  human dial to within 0.5 F of URA's applied value inside 15 s of URA's write).
- **Genuine-human safety:** 23 override_detected rows are > 60 s from ANY URA write (probe Q2b) — none can fall inside a 15 s
  window, so the rule misclassifies zero known humans by construction; the known human 2026-09-25 19:17 CDT zone_2 76->77
  is among them.
- **Double-emit check (§ design note 6):** no sub-3 s override cluster exists among the 24 (min 5.3 s) — the fix is arrester-side,
  not producer-side.
The probe script is kept for its Q2b count; its Q1/rounding logic must NOT be reused without re-targeting the lag to the
`preset_mode -> manual` transition.
