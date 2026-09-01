# AUDIT — Room Light Automation (READ-ONLY)

Date: 2026-08-31
Scope: URA room LIGHT entry/exit control, night-light handling, canonical↔reconciler
D2.10 parity. Read-only investigation; no code edited. Findings feed operator
carding — this doc does not build.

Founding case: **NIGHT-LIGHT-NO-OFF-PATH-1** — a `night_lights`-only entity
(Master Bath under-cabinet Sonoff, `switch.sonoff_1002197ef7_1`) is turned ON by
URA (dark occupied entry / sleep) but has **no off-path**: all off-paths are
`CONF_LIGHTS`-scoped and the reconciler vacant branch deliberately mirrors that
(actuator_reconciler.py:794-804, A-HIGH-1 comment). The light stays on 20-29h
until a human/device clears it.

Files read end-to-end: `automation.py` (`_control_lights_entry` :966,
`_control_lights_exit` :1034, `_turn_on_night_lights` :1133,
`_turn_on_regular_lights` :1092, `_turn_off_non_night_lights` :1201,
`_shared_space_turn_off_all` :3314); `actuator_reconciler.py`
(`resolve_desired_state` :704, `_resolve_light` :735, `_tracked_entities` :262,
`_light_entities` :232, edge handler :430-548, `_reconcile_one` :587);
`const.py` :848-906. Live config via `ssh ha` (`.storage/core.config_entries`,
`.storage/core.entity_registry`).

---

## D1 — The night_lights-only off-path gap: full fix scope

### Confirmation of the gap (both surfaces)

**Canonical ON-path (turns night lights on):**
- `_control_lights_entry` (automation.py:966). Two ON routes for night lights:
  - Sleep entry (:991-996): `is_sleep_hours and night_lights` → `_turn_on_night_lights(mode="sleep")` + `_turn_off_non_night_lights()` → returns. Turns ALL `night_lights` ON.
  - Normal entry (:1019-1023): after `should_turn_on`, `_turn_on_regular_lights()` then `if night_lights: _turn_on_night_lights(mode="day")`. Turns ALL `night_lights` ON at day brightness.

**Canonical OFF-path (the gap):**
- `_control_lights_exit` (automation.py:1034-1088): iterates `CONF_LIGHTS` ONLY (:1040 `lights = self.config.get(CONF_LIGHTS, [])`). A `night_lights` entity that is NOT also in `CONF_LIGHTS` is never in the turn-off set. **This is the primary gap.**
- `_turn_off_non_night_lights` (automation.py:1201): by name/design turns off `CONF_LIGHTS − night_lights`; it EXCLUDES night lights. Called only on sleep entry (:995) — it is not an off-path for night lights, ever.
- `_shared_space_turn_off_all` (automation.py:3314): iterates `CONF_LIGHTS` only (:3317). Same gap; shared-space vacancy also never clears a night-only entity.
- **No sleep-end / dark→bright off-handler exists.** When sleep ends, the room either re-fires entry (→ night lights go to day-mode ON) or does nothing. Nothing turns night lights OFF at wake. Grep confirms no other turn_off site references `CONF_NIGHT_LIGHTS`.

**Reconciler parity (actuator_reconciler.py):**
- `_tracked_entities` (:262) DOES include night-only entities — `_light_entities` (:232) unions `_LIGHT_KEYS = (CONF_LIGHTS, CONF_NIGHT_LIGHTS)` (:107). So the reconciler *watches* the night-only entity.
- `_resolve_light` vacant branch (:794-804): asserts OFF only when `exit_action == TURN_OFF and entity_id in regular_lights` (regular_lights = `CONF_LIGHTS`, :798). The A-HIGH-1 comment (:794-797) explicitly mirrors the buggy canonical: "a night_lights-only entity is NEVER turned off on exit by canonical." So the reconciler **correctly maintains parity with the bug** — it will NOT fix it on its own, and must be changed in lockstep with the canonical.
- `_resolve_light` sleep branch (:746-767): sleep + in night_lights → ON; sleep + not night_light → OFF. Regardless of occupancy or entry_action.

### Exact touch-points for the fix (keeping D2.10 parity)

The intended off vehicle is **vacancy exit** (see D4 for the intent choice). The
reconciler only fires on unavailable→available edges (reconcile-on-return, see
"reconciler behavior" note below), so it is NOT a policy driver — the canonical
exit path is the primary fix and the reconciler MUST be updated to mirror it or
parity breaks.

| # | File:line | Change | Why |
|---|---|---|---|
| T1 | automation.py:1040 (`_control_lights_exit`) | Build the turn-off set from `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` (not `CONF_LIGHTS` alone) when `exit_action == TURN_OFF`. Keep the existing light.*/switch.* domain split. | Primary off-path. Union is safe: dual-listed night lights already turn off here, so only night-ONLY entities are newly added. |
| T2 | actuator_reconciler.py:798-804 (`_resolve_light` vacant branch) | Widen the membership gate from `entity_id in regular_lights` to `entity_id in (regular_lights + night_lights)`. Update the A-HIGH-1 comment to state the NEW canonical behavior. | D2.10 parity — the reconciler vacant assertion must match whatever set the canonical exit now clears. |
| T3 | automation.py:3317 (`_shared_space_turn_off_all`) | Same union as T1 for shared-space vacancy. | Shared-space rooms otherwise keep the gap. Verify a shared-space bug room exists before scoping (none of the 5 bug rooms below are shared-space today — low priority but needed for correctness/consistency). |

**Do NOT touch:** the sleep branch (:746-767) or `_turn_on_night_lights` — the
ON behavior is correct; only the OFF set is missing. If the operator picks the
"stay-on-till-wake" intent (D4), T1/T2/T3 change instead of vacancy, and a
sleep-end off-handler must be ADDED (larger scope — see D4).

**Parity invariant to state in the plan (falsifiable):** "For every tracked
light entity E and every reachable (occupancy, sleep, entry_action, exit_action)
tuple, `_resolve_light(E)` yields OFF **iff** the canonical entry/exit path would
leave E off." Today this holds only because both sides skip night-only on exit;
after the fix both sides must clear night-only on vacancy exit.

### Review tier

**Tier 2-DB (three framing-disjoint reviews) — elevate.** No DB schema change,
but this modifies a **shared primitive** (`actuator_reconciler._resolve_light`,
consumed by the reconcile-on-return path) under a hard **canonical↔reconciler
parity invariant**, and it changes turn-OFF behavior across 5 live rooms →
regression-prone per the standing policy. Framings suggested: A = local
correctness (union set, domain split, transition params); B = parity +
sleep/entry interaction (no suppression of a legitimate ON; byte-identical on the
no-op path; leave_on rooms untouched); C = per-site mutation test authority
(detach T1 and T2 independently, confirm a specific test fails).

### Reconciler behavior note (important for the plan)

The reconciler is **reconcile-on-return only**: its edge handler (:441-447)
returns unless `old in UNAVAILABLE_STATES and new not in UNAVAILABLE_STATES`. It
does not actuate on occupancy or sleep transitions. Consequence: fixing only the
reconciler would NOT create an off-path (it never fires on vacancy). The
canonical exit is the required vehicle; the reconciler change is parity-only.

---

## D2 — Dual-listing survey (live config, 40 room entries)

Source: `.storage/core.config_entries`, domain `universal_room_automation`,
2026-08-31. "night-only" = a `night_lights` entity NOT also in `lights`
(→ has the bug). "dual-listed" = night light also in `lights` (→ turns off via
the existing `CONF_LIGHTS` exit path, which is why "other night lights turn off").

### BLAST RADIUS — night-only bug rooms (5)

| Room | entry / exit | Night-only entity | Notes |
|---|---|---|---|
| **Master Bathroom** | turn_on_if_dark / turn_off | `switch.sonoff_1002197ef7_1` | Founding case. On-path = entry (sleep + day-dark). |
| **Study B** | turn_on_if_dark / turn_off | `light.dimmer_shellyplus_wifi_studyb1` | Distinct entity from the regular `..._studyb` (both registered — NOT a typo). Genuine night-only. |
| **Kitchen** | turn_on_if_dark / turn_off | `switch.switch_tapo_wifi_kitchenrange` | Night light is the **range/vent light** — odd choice; on-path fires it at every dark entry. Flag for operator sanity-check (see D3-F4). |
| **Garage Hallway** | turn_on_if_dark / turn_off | `light.dimmer_tapo_wifi_matter_hallwaycabinet` | Cabinet light night-only; regular light is a different fixture. |
| **Master Bedroom** | none / turn_off | `light.shellydimmer2_24d7ebe93470` | Special: `lights` EMPTY + entry=none → canonical entry DOUBLE short-circuits (:973 action==none, :980 empty lights). Canonical NEVER turns this on. Only the reconciler can (on device recovery during sleep) → and never off. See D3-F2. |

All 5 use `exit_action = turn_off` → the D1 vacancy off-path (T1/T2) fixes all 5.
None are shared-space, so T3 is not needed to close these specific 5.

### Dual-listed (night light also in lights → already turns off correctly) — 15

Study A, Stair Closet, Living Room*, Kitchen Hallway, Patio, Receiving Room,
Breakfast Nook*, Game Room, Kitchen Hallway Garage, Exercise Room, Jaya Bathroom*,
Ziri Bathroom, Laundry, Kitchen Pantry, Master Bath Toilet, Butler Pantry.

\* Living Room / Breakfast Nook / Jaya Bathroom / Master Hallway use
`exit=leave_on` — their lights (incl. night) never turn off on exit by design;
not a bug. Note that in **sleep** the reconciler/canonical still force
non-night lights OFF for these rooms (sleep branch overrides leave_on) — verify
that is intended, minor (D3-F5).

### No night_lights configured (unaffected) — 20

Dining Room, Guest Bedroom 1 Bathroom, Upstairs Guestroom, Guest Bedroom 2
Bathroom, Laundry Closet, Guest Bedroom 1, Study A Closet, AV Closet, Media Room
Closet, Garage A, Ziri Bedroom, Jaya Bedroom, Garage B, Media, Exercise Room
Closet, Guest Bedroom 1 Closet, Oji Vanity, Master Bath Toilet(has), Upstairs
Hallway, Master Hallway. (Media / Dining / Upstairs Hallway / Master Hallway have
no lights at all.)

**Conclusion:** blast radius = **5 rooms**. The reason "other night lights turn
off" is confirmed: 15 rooms dual-list their night lights, so they ride the
existing `CONF_LIGHTS` exit path.

---

## D3 — Improvement opportunities (ranked by impact)

**F1 (HIGH) — the night-only off-path gap.** = D1. 5 rooms, lights stuck 20-29h.
Primary finding.

**F2 (MEDIUM) — canonical↔reconciler divergence on `entry=none` + sleep.**
Canonical `_control_lights_entry` early-returns at :973 (`action == NONE`) and at
:980 (empty `lights`) BEFORE the sleep block (:991). But `_resolve_light` checks
the sleep branch (:746) BEFORE `entry_action` (:769). So during sleep, for a room
with `entry=none` and/or empty `lights` but populated `night_lights`, the
reconciler wants night lights ON while the canonical would never turn them on.
Manifests when such a night-light device recovers unavailable→available during
sleep. Affected: **Master Bedroom** (entry=none + empty lights), **Patio**
(entry=none), **Game Room** (entry=none). This is a real D2.10 parity break
predating this cycle. Recommend the plan either (a) gate the reconciler sleep
branch on the same entry_action/lights preconditions as canonical, or (b) fix
canonical so night lights are honored independent of `entry_action`
(arguably the better behavior — night lights are a sleep-safety feature, not an
entry action). Decide deliberately; don't paper over.

**F3 (MEDIUM) — empty-`lights` short-circuit blocks night lights entirely
(canonical).** `_control_lights_entry` returns at :980 when `CONF_LIGHTS` is
empty, before the sleep/night-light block. Any room that wants night-lights-only
behavior (Master Bedroom is exactly this) gets ZERO canonical night-light
actuation. If night lights are meant to work without a regular-lights list, the
:980 guard must move below the sleep block. Ties to F2.

**F4 (LOW-MED) — Kitchen "night light" is the range/vent light.**
`switch.switch_tapo_wifi_kitchenrange` as `night_lights` means every dark
occupied Kitchen entry turns on the range light at day brightness (normal entry
path :1023). Likely a config mistake (range light ≠ courtesy night light).
Operator sanity-check; not a code bug.

**F5 (LOW) — sleep overrides `leave_on`.** For Living Room / Breakfast Nook /
Jaya Bathroom (exit=leave_on) the sleep branch (canonical :995
`_turn_off_non_night_lights`; reconciler :764 OFF) forces non-night lights off
during sleep, contradicting the operator's leave_on intent. Confirm intended.

**F6 (LOW) — `_shared_space_turn_off_all` has the same night-only gap** (:3317,
CONF_LIGHTS only). No shared-space room is currently a bug room, but fix in the
same cycle (T3) for consistency so a future shared-space night light doesn't
reintroduce the bug.

**F7 (LOW) — day-mode night lights ignore color temp unless FULL capability.**
`_turn_on_night_lights` applies `color_temp_kelvin` only for
`LIGHT_CAPABILITY_FULL` (:1182), brightness only for BRIGHTNESS/FULL (:1178).
Switch-domain night lights (Master Bath Sonoff, Kitchen range) get neither —
expected (switches can't dim), just documenting that "night brightness/color"
silently no-ops for the switch-backed night lights, which are 2 of the 5 bug
rooms. No action; informs D4 (a switch night light is purely on/off).

**F8 (INFO) — unknown-prefix entities assumed light.** `_control_lights_exit`
:1054 treats non-`light.`/non-`switch.` ids as light.*. No such entities in live
config today; benign.

---

## D4 — Intent options for the night-light fix (operator decision)

The night light is turned ON by URA; the question is WHEN it should go OFF.

### Option A — OFF on vacancy (recommended default)
Night light turns off when the room goes vacant, same as a regular light.
- **Behavior:** courtesy light while you're in the room (day or night), off when
  you leave. During sleep, re-entry re-lights it at sleep brightness.
- **Code shape:** T1 + T2 + T3 (union `CONF_LIGHTS ∪ CONF_NIGHT_LIGHTS` in the
  exit turn-off set + mirror in reconciler vacant branch). Smallest diff,
  strongest parity, no new state machine, no new sleep-end handler.
- **Downside:** if you get up at 3am, walk out and back, it re-lights each time
  (but at 15% warm — acceptable; that's the point of a night light).
- Covers all 5 bug rooms (all exit=turn_off).

### Option B — Stay on till wake (sleep-end off)
Night light stays on for the whole sleep window, turns off at sleep-end / house
wakes / dark→bright.
- **Behavior:** persistent low glow all night regardless of vacancy; clears in
  the morning.
- **Code shape:** LARGER. Needs a NEW sleep-end / dark→bright OFF handler (none
  exists today — grep-confirmed) that turns off `night_lights` when
  `is_sleep_mode_active()` goes True→False, plus a reconciler edge/branch to
  mirror it. Introduces a state-transition seam (the exact ingredient class
  behind prior bug families per CLAUDE.md Marginal-Benefit rule). Higher review
  cost.
- **Downside:** a night-only device that recovers or gets manually toggled during
  the day has no vacancy off-path — still needs Option A's exit union as a
  backstop.

### Option C — Hybrid (off on vacancy AND at sleep-end)
Option A's vacancy off PLUS Option B's sleep-end sweep.
- **Code shape:** T1+T2+T3 (Option A) + the sleep-end handler (Option B).
  Most robust, most surface. Only worth it if the operator wants BOTH "off when I
  leave" and "guaranteed clear at wake even if the room stayed occupied all
  night."

**Marginal-benefit read (per CLAUDE.md pushback duty):** Option A captures the
entire founding complaint (light stuck 20-29h) with the smallest, parity-safe
diff and no new time-seam. Option B/C's marginal benefit (glow persists while you
sleep in the room) is a *feature preference*, not a bug fix, and adds a
sleep-transition writer — recommend **Option A now**, park B/C behind an explicit
operator "I want the glow to persist while occupied overnight" trigger. For the 2
switch-backed bug rooms (Master Bath Sonoff, Kitchen range) the light is pure
on/off, so Option A is strictly correct behavior.

---

## Appendix — items to card

1. NIGHT-LIGHT-NO-OFF-PATH-1 fix — Option A (T1+T2+T3), Tier 2-DB. (F1/D1)
2. Reconciler↔canonical sleep-branch divergence for entry=none/empty-lights
   rooms (Master Bedroom, Patio, Game Room). (F2)
3. Empty-`lights` short-circuit blocks night-only rooms in canonical. (F3) —
   likely folded into #2's decision.
4. Operator sanity-check: Kitchen range light as night_light. (F4) — config, not code.
5. Confirm sleep-overrides-leave_on is intended. (F5) — investigation.
</content>
