# PLANNING: SAFEWORD-WINDOW-1 — "duke Nh" ack-plus-perimeter-silence

Card: SAFEWORD-WINDOW-1 (kanban.data.yaml). Plan-review status: BUILD-READY
with the addenda below. This doc adjudicates the semantics that the card
left open after live-code grep, and is the spec the builder consumes.

## Institutional context verified

Greps run against `custom_components/universal_room_automation/` on the
main worktree (read-only):

- **Safeword parse / gate** — `notification_manager.py:3080-3260`
  (`_process_inbound_reply`). Existing safeword match at
  `_match_safe_word` (:2639) requires **exact** stripped-lowered equality
  vs the personal (per-CONF_NM_PERSON_SAFE_WORD) or global
  (CONF_NM_SAFE_WORD) word — so "duke 2h" **cannot match today** without a
  pre-parse. REUSED entry point; NEW pre-parse ahead of `_match_safe_word`.
- **Existing `_silence_until`** — `notification_manager.py:346` (RAM
  field), set at :3251 by the `silence`/`stop`/`mute`/`quiet` command;
  minute-precision, sourced from CONF_NM_SILENCE_DURATION
  (const.py:2441). Gate at :1348-1355 is `severity != CRITICAL AND
  _silence_until in future` — **blanket over ALL non-CRITICAL hazards**.
  Inbound-side gate at :3127 blocks non-status/help/safeword replies
  during silence. **_silence_until is NOT in `get_persistence_state()`
  (:820-870) — RAM-only, cleared on restart.** The :630 comment refers to
  the `async_suppress_messaging` kill-switch preserving it across a
  messaging-disable/enable, not across restart. Verified.
- **NM_SECURITY_HAZARDS** — `const.py:1509-1512` is
  `frozenset({NM_HAZARD_EXTERIOR_PERSON, NM_HAZARD_EXTERIOR_VEHICLE})`
  ONLY. Confirmed EXCLUDES `intrusion` (interior alarm) and every
  life-safety hazard (smoke/CO/leak/freeze/high-humidity/etc). This is
  the correct enumeration for "perimeter-class" per the card's safety
  note. REUSED.
- **Life-safety helper** — `is_life_safety_hazard(hass, hazard_type)` at
  `domain_coordinators/_nm_cycle_a.py:200` unions the rung-1
  `NM_LIFE_SAFETY_HAZARDS` (const.py:2354) with the operator's
  `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS`. REUSED as the "never window" gate.
- **Re-page path** — `_repeat_alert` at :2506+. Rebuilt in v-Cycle-C
  fix-up so re-pages honor per-recipient mute/DND (with life-safety
  bypass). **`_repeat_alert` does NOT consult `_silence_until`.**
  Confirmed: the existing silence gate lives only in `async_notify`
  first-fire. The card's ":2530 bypass" concern therefore does not
  block the ack-plus-window semantics chosen below.
- **Echo guard** — `_is_self_echo` at :3092 runs BEFORE parse; drops
  reflected outbound text on `imessage`/`whatsapp`. Rung-1 constants at
  const.py:246-255 (`NM_ECHO_GUARD_TTL_S`, etc). The v5.51.1 echo-guard
  ship (post-BlueBubbles incident, MEMORY:v5.51.1) is what allows the
  new parse to trust that our own "Alerts silenced. Will resume at HH:MM"
  reflection cannot re-enter the safeword path.
- **CONF_NM_SILENCE_DURATION** — `const.py:2441`. Existing default (minutes)
  reused as the parse-fallback when the operator sends bare "duke" with
  no duration and asks for a window separately; NOT used for the "duke Nh"
  form (that carries its own N).

Prior docs skimmed: `docs/planning/PLANNING_bathroom_exhaust_intelligence_and_humidity_fan_unification.md`
(NM re-page fix history), MEMORY entries for
`shipwatch_confirmed_v5.31.0_H7.json` (silence surviving 48h with no
manual-hold regression) and v5.51.1 echo-guard.

Design docs read: none for NM — no `docs/Coordinator/NOTIFICATION_MANAGER.md`
present; notification_manager.py's inline docstrings are authoritative.

Files surveyed end-to-end for the change surface: `_process_inbound_reply`
(:3080-3260), `_match_safe_word` (:2639-2659), `async_notify` gate section
(:1330-1400), `_repeat_alert` (:2506-2620), `get_persistence_state` /
`restore_persistence_state` (:820-960).

## Falsifiable invariants (state up front — reviewers falsify these)

The build ships iff **all five** hold across the whole reachable code
surface (D-framing reviewer re-enumerates from scratch):

1. **I1 (never-blanket)** Under any silence window created by "duke Nh",
   `is_life_safety_hazard(hass, H)==True` ⇒ the alert reaches its
   normal dispatch path (never suppressed by this new gate). No reachable
   config makes I1 false.
2. **I2 (perimeter-only scope)** The new window suppresses first-fire
   dispatch iff `H ∈ NM_SECURITY_HAZARDS` AND the window is active AND the
   hazard is not life-safety. For any `H ∉ NM_SECURITY_HAZARDS` the new
   gate is a no-op.
3. **I3 (current-alert ack, not repeat-suppress)** "duke Nh" acks the
   currently-repeating alert (kills its re-pages via the existing
   `async_acknowledge` path) AND opens the window for NEW arrivals; the
   window does NOT retroactively suppress re-pages of a pre-existing
   unacked non-perimeter CRITICAL. (Composition avoids the :2530 bypass
   issue entirely — we never try to silence a live re-page loop.)
4. **I4 (bounded)** Every window duration is clamped to `[1 min, 180 min]`
   (hard cap 3 h). Bad input ("duke 999h", "duke abc", "duke 0m",
   negative) rejects with a reply and does NOT ack, does NOT open a
   window.
5. **I5 (auto-expiry + surfaced)** Window auto-expires at `expiry`; the
   remaining time is readable on `sensor.<nm>_status` (or existing NM
   status attribute surface) as `perimeter_silence_expires_at` (ISO) and
   `perimeter_silence_active` (bool). No polling required — first
   post-expiry perimeter alert flows normally on next tick.

Non-invariants (deliberate — for D reviewer to not flag as gaps):
- **Restart clears the window.** RAM-only, matching existing
  `_silence_until`. Rationale: a restart is a discontinuity; if the
  operator's real intent persists (e.g. contractor still on-site), a
  30-second re-send of "duke Nh" restores it. Persisting adds
  cross-episode bleed risk (a stale window silencing a legitimate
  perimeter alert after unrelated restart) with no measured value.
  Documented on the sensor attribute so the operator sees an empty value
  after restart.
- **Re-pages of the acked alert stop via the ordinary ack path**, not
  via this gate. Confirmed by reading `async_acknowledge` — it cancels
  `_repeat_unsub` and moves state out of REPEATING.

## Deliverables

### D1 — Parse "duke Nh" / "duke Nm"

**Location:** `notification_manager.py:_process_inbound_reply`, immediately
before `is_safe_word, _sw_source = self._match_safe_word(text, person_id)`
at :3124.

**Behaviour.** Strip a trailing duration token from `text` (lowercased,
already stripped at :3107) BEFORE calling `_match_safe_word`. If the
stripped remainder matches, treat as safeword + carry a `window_minutes`
value into the safe_word branch.

Parse regex: `r"^(?P<word>.+?)\s+(?P<n>\d+)\s*(?P<unit>[hm])$"`.

- `unit == "h"` → `window_minutes = n * 60`.
- `unit == "m"` → `window_minutes = n`.
- Clamp `[1, 180]`. If the raw value is > 180, **reject** (do not silently
  clamp): reply `"Window capped at 3h — try 'duke 3h' or less."` and
  return without acking. Rationale: silent clamp hides operator intent.
- Bad shape (`"duke 0m"`, `"duke abc"`, negative — regex won't match a
  negative but keep the guard): fall through to normal safeword match.
  If the raw text also fails `_match_safe_word`, the reply is the usual
  "unknown command" path — no change.
- `word` is then handed to `_match_safe_word(word, person_id)` unchanged
  (personal + global fallback preserved).

**Echo safety.** Runs after `_is_self_echo` (:3092) drops our own
reflections. Additionally, the two reply strings we ever emit for this
feature — `"Perimeter alerts silenced for {N} min. Will resume at HH:MM."`
and the ack-announce — do not contain "duke" and cannot re-parse as
"duke Nh". Verified by construction; test in D5.

**Kill switch.** New rung-1 constant
`NM_SAFEWORD_WINDOW_ENABLED: Final[bool] = True` in `const.py` (adjacent
to `NM_ECHO_GUARD_TTL_S` at :246). When False, the pre-parse is skipped;
bare "duke" continues to ack normally.

### D2 — New perimeter-scoped silence gate

**Field.** `self._perimeter_silence_until: datetime | None = None`
initialized alongside `_silence_until` at :346. RAM-only (per I-non-invariant).

**Gate site.** ONE new site, immediately AFTER the existing silence
check at :1348-1355 in `async_notify`. Explicit branch (no combining
with the existing gate — different scope + different severity semantics):

```python
# NEW: perimeter-class window (I2). Life-safety NEVER windowed (I1).
if (
    self._perimeter_silence_until
    and dt_util.utcnow() < self._perimeter_silence_until
    and hazard_type in NM_SECURITY_HAZARDS
    and not is_life_safety_hazard(self.hass, hazard_type)
):
    _LOGGER.debug(
        "NM: perimeter alert suppressed by safeword window (%s until %s)",
        hazard_type, self._perimeter_silence_until.isoformat(),
    )
    self._perimeter_silence_suppressions += 1  # new counter, attr-surfaced
    return
```

**Do NOT add a gate in `_repeat_alert`.** Per I3, the window never
silences an in-flight re-page loop; the "duke Nh" call acks the current
alert first (D3), which is what actually stops the loop.

### D3 — Wire ack + window in the safeword branch

Inside the `if is_safe_word:` block at :3148-3212, when the pre-parse
extracted `window_minutes`:

1. Run the existing ack authority + `async_acknowledge` path unchanged.
   (For non-perimeter unacked CRITICALs — e.g. an active water_leak —
   this still ACKs the current alert; the window is separately about
   FUTURE perimeter alerts. That's the operator's stated semantics.)
2. After a successful ack, set:
   `self._perimeter_silence_until = dt_util.utcnow() + timedelta(minutes=window_minutes)`
3. Compose reply: `"<usual ack sentence> Perimeter alerts silenced for
   {N}m; resume at HH:MM."`.
4. Log at INFO with structured fields:
   `person=<person_id> window_min=<N> expiry=<iso>`.

If the ack is **denied** (unauthorized security ack path at :3172-3187),
**do not open the window** and do not reply about a window — that state
already returns early with the deny text.

**NM note requirement (card).** After setting the window, dispatch a NM
`INFO` note (via the existing `async_notify` low-severity path, hazard
`None`) with title `"Perimeter alerts silenced"` and body carrying start,
expiry, requester. On expiry (first `async_notify` call after
`_perimeter_silence_until` passes) emit a matching `"Perimeter alerts
resumed"` note. Rationale: makes start/end visible in the NM log the
operator already scans; requires no scheduler (piggy-backed on next
event).

### D4 — Attribute surface + diagnostics

Add to the NM status attribute dict (grep `perimeter_silence` after
build to verify these are the only two new keys):
- `perimeter_silence_active: bool`
- `perimeter_silence_expires_at: str | None` (ISO)
- `perimeter_silence_suppressions_today: int` (mirrors existing
  `_quiet_suppressions` / `_dedup_suppressions` pattern)

### D5 — Tests (mutation-anchored)

Location: `quality/tests/nm/test_safeword_window.py` (new).

Each test names the exact source line it anchors so the C-framing
reviewer's per-site mutation drill can pick it up.

- `test_duke_2h_parses_and_windows` — sends "duke 2h", asserts ack fired
  AND `_perimeter_silence_until ≈ now + 120min` (± 2s).
- `test_duke_45m_parses` — minute unit.
- `test_duke_over_cap_rejected` — "duke 5h" → no ack, no window, reply
  contains "capped at 3h".
- `test_duke_abc_falls_through` — "duke abc" → normal safeword ack (no
  window).
- `test_window_suppresses_exterior_person_first_fire` — sets window,
  fires an `exterior_person` CRITICAL, asserts the notify path returns
  early (suppression counter +1, no channel sends). **Mutation anchor:**
  removing the `hazard_type in NM_SECURITY_HAZARDS` check MUST fail this
  test AND `test_window_never_blankets_water_leak`.
- `test_window_never_blankets_water_leak` — sets window, fires a
  `water_leak` (non-perimeter, non-life-safety), asserts it dispatches
  normally.
- `test_window_never_blankets_life_safety` — sets window, fires a
  hazard in `NM_LIFE_SAFETY_HAZARDS` that is ALSO in NM_SECURITY_HAZARDS
  if such union grows later (today: fire smoke separately) — asserts
  dispatch normal. **Mutation anchor:** removing the
  `is_life_safety_hazard(...)` check MUST fail this test.
- `test_active_perimeter_repage_not_suppressed_by_window` — start a
  perimeter CRITICAL, let it enter REPEATING, THEN set window (via
  "duke Nh" from an authorized ack) — assert the ack cancels the repeat
  (I3, tested via `_repeat_unsub is None`), and a NEW perimeter alert
  during the window is suppressed.
- `test_window_expires` — freeze clock, set 5-min window, advance
  clock, first post-expiry perimeter dispatch fires normally AND emits
  the "Perimeter alerts resumed" NM note.
- `test_kill_switch` — set `NM_SAFEWORD_WINDOW_ENABLED = False`, "duke
  2h" → pre-parse skipped; raw text ("dukeword 2h") fails
  `_match_safe_word` (exact equality with the trailing " 2h"), so
  behaviour is: NO ack, NO window, NO reply beyond the ordinary
  no-context/unknown path. To keep "bare duke" acking normally when
  the kill switch is off, send it WITHOUT the duration suffix — that
  path is entirely unaffected by NM_SAFEWORD_WINDOW_ENABLED.
  (Fix-up A3 2026-08-14: prior wording implied "duke 2h" would ack
  without the window when disabled; that is not what happens and not
  what should happen — the kill switch must not silently rewrite
  operator intent.)
- `test_restart_clears_window` — set window, run
  `get_persistence_state` → assert key absent; restore into a fresh
  instance → assert `_perimeter_silence_until is None`.

### D6 — Config-flow / knob ladder

- `NM_SAFEWORD_WINDOW_ENABLED` — rung-1 module constant (kill switch;
  changing requires review — bounds a rare-fire security path).
- Hard cap `180` — rung-1 inline in the parse. NOT operator-tunable:
  a 24-hour perimeter blackout is a category of risk (physical-security
  loss); if the operator ever needs longer, escalate to a config-flow
  cycle with an explicit warning banner.
- No new Number/Switch entity. The window is per-invocation via SMS;
  persisting a "default duration" would invite the exact 24h-blackout
  the cap exists to prevent.

## Acceptance criteria (per CLAUDE.md sprint-contract rule)

- **Verify:** "duke 2h" from an authorized person acks a repeating
  perimeter CRITICAL AND sets a 120-min window.
- **Verify:** during window, a synthetic `exterior_person` first-fire
  returns early (log line matches "perimeter alert suppressed by
  safeword window").
- **Verify:** during window, a synthetic `water_leak` or smoke test
  dispatches normally.
- **Verify:** "duke 5h" → reply "capped at 3h", no ack, no window.
- **Verify:** at expiry, next perimeter alert fires AND a NM "resumed"
  note is emitted.
- **Sensor:** NM status attributes carry `perimeter_silence_active`
  and `perimeter_silence_expires_at`; both nulled after restart.
- **Test:** the D5 tests all pass. Per-site mutation drill: removing
  the perimeter-scope check MUST fail the pair (suppress + never-blanket)
  it anchors; removing the life-safety check MUST fail its test.
- **Live:** post-deploy, send "duke 1m" from the operator's number
  (window kept trivially short for validation). Confirm receipt of the
  ack reply + the two NM notes (silenced / resumed 60s later). Record
  in the README's post-restart validation table (per CLAUDE.md
  README-write-back rule).

## Tier classification

**Tier 2-DB (3 framing-disjoint reviews).** Justification per
CLAUDE.md's standing policy (Tier 2-DB for ALL regression-prone work):
the change adds a NEW gate on the NM dispatch path (a shared primitive
consumed by every coordinator), the failure mode is one-missed-site
class (either the life-safety exclusion or the perimeter-scope check
being wrong = silent security-alert loss), and the parse touches a code
path where a prior echo-loop bug shipped (v5.51.1). The change is not
Tier-3 (single gate, single parse, single field — no state machine
threading), but two-review convergence risk is real: A and B both looking
at "did we suppress correctly" could both miss "did we forget to
exclude smoke".

**Recommended framings:**
- **A — parse correctness + echo safety + kill-switch semantics.**
  Regex boundary cases, unit handling, cap-reject vs clamp, echo of
  our own reply strings, `NM_SAFEWORD_WINDOW_ENABLED=False` behaviour,
  authority-deny path does NOT open a window.
- **B — gate scoping + interactions.** Life-safety exclusion holds under
  operator promotion via `CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS`; new gate
  does not interfere with existing `_silence_until`, boot-settle,
  quiet-hours, dedup, or DND ordering; `_repeat_alert` remains
  unaffected; NM notes emit exactly once at start and exactly once at
  expiry.
- **C — persistence choice + test authority (mutation-anchored per
  site).** Every load-bearing check in D2 fails a specific named test
  when mutated in-source (not aggregate monkeypatch); restart-clears
  choice documented and covered; attribute-surface diff limited to the
  two new keys + one counter.

## Non-goals

- No change to bare "duke" behaviour (ack-only, no window).
- No change to the existing `3=silence` blanket-non-CRITICAL command.
- No change to `_repeat_alert` (I3 forbids it).
- No new Number/Switch entity, no options-flow field, no schema change.
- No persistence across restart (documented non-invariant).
- No expansion of NM_SECURITY_HAZARDS (out-of-scope; separate cycle if
  ever needed).

## Verdict

**BUILD-READY.** All five card open questions resolved against live
code:
1. Existing `_silence_until` gate is **blanket non-CRITICAL** — perimeter
   scoping is NEW logic; `NM_SECURITY_HAZARDS` at const.py:1509 is the
   correct enumeration (excludes `intrusion`, life-safety); life-safety
   exclusion uses `is_life_safety_hazard()` at `_nm_cycle_a.py:200`.
2. Parse fits ahead of `_match_safe_word` at :3124 with the regex
   above; echo guard at :3092 protects the regression class the :3089
   comment warns about.
3. Re-page interaction adjudicated as ack-current-plus-window-future
   (I3) — sidesteps the :2530 bypass entirely; no change to
   `_repeat_alert`.
4. Persistence: RAM-only, matching existing `_silence_until`;
   documented non-invariant with a two-attribute operator-visible
   surface after restart.
5. Tier: Tier 2-DB, three framings A/B/C above.
