# AUDIT: STEP chatter-quarantine 2-day forcing gate — 2026-08-21

**Run type:** Scheduled read-only evidence-gathering routine, per operator-mandated 2-day gate
(README_v5.85.0.md: flip `select.ura_chatter_mode` to `act` within 2 days of the 2026-08-19
deploy, or declare the program moot).

**Bottom line up front: recommend EXTEND, not flip / not moot — and this routine could not
independently verify current live state (no Home Assistant access from this session; see
Blocker below). The recommendation below is built entirely from git-tracked prior-session
evidence (`docs/planning/kanban.data.yaml`, card `STEP-SHADOW-EVIDENCE-WATCH-1`), not from a
fresh live read.**

---

## Blocker: this session has no path to the live HA instance

This routine fired in a remote/cloud Claude Code session. It has:
- No `home-assistant` MCP connector attached (`ListConnectors` returns only Fathom / Gmail /
  Google Calendar / Google Drive / Slack — no HA entry).
- No `ssh` binary and no SSH config for reaching the HA host.
- No HA URL/token in environment variables.

This matches the documented caveat that interactively-authenticated MCP servers (like the
operator's local `home-assistant` MCP) are absent in headless/cron runs. **Step 2 of the gate
task (ha_get_state / ha_get_history / ha_get_logs reads) could not be performed.** Everything
below is reconstructed from the git-tracked kanban board, which a prior *interactive* session
(with live HA access) wrote during the shadow window.

**Action needed:** an interactive session with HA access must run the live checks below before
the gate decision is finalized — see "What still needs a live read," last section.

---

## README acceptance criteria (from `docs/readmes/README_v5.85.0.md`)

- **L1** boot clean, zero URA ERROR; `select.ura_chatter_mode = shadow` — **PASS at deploy**
  (validated 2026-08-19 ~11:26 CDT).
- **L2** `K` / `T_floor` Numbers present on the Coordinator Manager, at defaults 10 / 1.0 —
  **PASS at deploy**, but **T_floor was subsequently changed live** (see below) — no longer at
  the shipped default as of gate day.
- **L3** detector registers listeners on allowlisted blind-time-gated entities, no errors —
  **PASS at deploy**.
- **L4 (discriminator)** on a real chatter episode, `chatter_telemetry` shows
  `would_quarantine: true` **and** the sensor's vote is still counted (shadow = detect-only) —
  **PENDING, unresolved as of the last git-tracked evidence** (see below).
- **L5** zero chatter exclusions promoted while `mode=shadow` — mutation-anchored in-suite;
  no live violation reported.

**Falsifiable invariant:** *in shadow mode, no reachable path promotes a chatter exclusion into
the fusion set.* Not in question here — the open question is whether the detector actually
**fires** (L4), not whether shadow correctly withholds action.

---

## What actually happened during the shadow window (from kanban card `STEP-SHADOW-EVIDENCE-WATCH-1`)

### 2026-08-20, hand-check ("did it find chatterers accurately?")

A prior session read `chatter_telemetry` live across every room exposing it (game_room,
garage_a, kitchen, living_room, master_bedroom, upstairs_guestroom, study_a):

- `chatter_would_quarantine_count = 0` in every room; `would_quarantine = false` for every
  individual sensor. `sub_floor_burst_count` was 0 or 1 everywhere against `K = 10`.
- Cross-checked against sensors **independently known** to misbehave (the discriminating test):
  `binary_sensor.mmwave_zigbee_studya_presence` (3,043 duty-cycle-stuck warnings in 5h from a
  *different* detector) scored `transition_count: 2`, not flagged. `binary_sensor.jaya_3_presence`
  (522 duty-cycle-stuck warnings) not flagged. Four corridor sensors with 45-62 transitions/24h,
  not flagged. The single highest `transition_count` found anywhere was 82
  (`binary_sensor.garageopener_gdoblaq_wifi_garagea_motion`) — still `sub_floor_burst_count: 0`.
- Initial interpretation ("it found nothing, real house pathologies are stuck-ON not chatter")
  was **wrong and later retracted** — see next section.

### 2026-08-20, root cause found (operator pushback: "check the garage motion sensor")

- `binary_sensor.garageopener_gdoblaq_wifi_garagea_motion`, 12h history: **311 transitions**,
  13 dense bursts across the day (09:19, 11:32, 11:45, 11:50, 12:27, 14:41, 14:59, 15:37, 16:07,
  16:11, 17:13, 17:17, 17:45). The 17:45:45→17:50:58 burst alone was **~44 transitions**
  (ON ~3s / OFF ~2s repeating for 5 minutes) — a textbook chatterer, exactly what the mechanism
  was built to catch.
- **Root cause: a units defect, not "no chatter."** `chatter_detector.py:518-520` scores
  `interval < t_floor` in seconds; the live `number.ura_chatter_t_floor` override was **1.0s**
  (`DEFAULT_CHATTER_T_FLOOR_S = const.py:3847`, and the per-family defaults are also all 1.0,
  `const.py:3848-3853`). The garage sensor cycles at 2-3s. 2.0 > 1.0, so every one of the 311
  transitions scored as "legitimate" — the floor was set **below the physical noise floor of the
  hardware**, so the detector was structurally incapable of firing for the ~36h it ran at this
  setting. `_effective_t_floor_default()` (chatter_detector.py:378-382) flattens all four
  provenance families (pir/mmwave/opener/reed) to this single override.
- **Consequence stated explicitly in the card:** *"the shadow period proved nothing either way —
  it was run with detection effectively disabled. Turning on `act` today would still act on an
  empty set; declaring it moot would discard a mechanism that has a real, live, well-matched
  target."*

### 2026-08-20, 19:33 CDT — fix applied live (operator: "Raise T_floor, re-observe briefly. Do it.")

- `number.ura_chatter_t_floor` written **1.0 → 5.0** via `number.set_value`; confirmed live —
  `chatter_telemetry` on every checked room (garage_a, living_room) now reports `t_floor: 5`.
  `K` left at 10, `CHATTER_OBSERVATION_WINDOW_S` left at 300.
- Mode **deliberately left at `shadow`** per standing operator instruction: *"Chatter mode is not
  on unless we find evidence of its success."*
- Write-safety was checked before applying: `CONF_CHATTER_T_FLOOR_S` is in `_NM_A2_KEYS`
  (`__init__.py:5686`), spread into `OPTIONS_RELOAD_SUPPRESS_KEYS` (`:5960`); the CM options
  listener unconditionally flushes the knob cache on every CM options update (`:6632-6647`) —
  in-place write, no CM reload, no parent-entry cascade. Confirmed live by the attribute
  changing with no restart.
- `sub_floor_burst_count` reading 0 immediately after the change was expected (scoring is
  forward-only; pre-existing deque entries were recorded under the old 1.0s floor; the 300s
  window self-clears quickly) — **not** evidence the fix failed.
- **The card's own "NEXT CHECK" was never closed out.** Verbatim: *"read `chatter_telemetry` on
  `sensor.garage_a_unavailable_entities` after the next garage-door activity. If
  `would_quarantine` goes true, the mechanism is vindicated... If it stays 0 through an observed
  burst, the defect is deeper than units and the card escalates."* No later kanban entry records
  this check having been run. The most recent kanban reconcile (commit `dd8ea03`, 2026-08-21
  07:26 CDT) touched unrelated cards (EVSE-DRAIN-PRECEDENCE, SENSCAP-ORPHAN-1) and did not add a
  new entry to `STEP-SHADOW-EVIDENCE-WATCH-1`.

### Current knob state (as of the last git-tracked write, 2026-08-20 19:33 CDT)

| Knob | Shipped default | Live value (last known) |
|---|---|---|
| `select.ura_chatter_mode` | shadow | shadow (unchanged, per operator standing instruction) |
| `number.ura_chatter_burst_k` (K) | 10 | 10 (unchanged) |
| `number.ura_chatter_t_floor` (T_floor) | 1.0s | **5.0s** (raised 2026-08-20 19:33 CDT) |

No live re-read confirms these values still hold at gate time — this table is the last
git-tracked state, not a fresh observation.

---

## Decision: EXTEND

None of the three clean outcomes fit:

- **FLIP TO ACT** is not supportable: the discriminator (L4 — a real chatter episode correctly
  flagged `would_quarantine: true` with no false positive on a healthy sensor) has **not been
  observed and confirmed** at the corrected T_floor. Flipping to `act` on an unconfirmed
  detector risks quarantining votes based on a mechanism whose post-fix behavior is unverified.
- **DECLARE MOOT** is not supportable: unlike a genuine "no chatter in 2 days despite bazillion
  devices" negative, this negative is **explained by a producer defect** (T_floor units bug)
  that made the detector structurally blind to a known, real, actively-misbehaving sensor
  (`binary_sensor.garageopener_gdoblaq_wifi_garagea_motion`, 311 transitions/12h, 13 bursts).
  Declaring moot now would discard a mechanism proven to have a live, well-matched target,
  based on evidence gathered while it was effectively disabled for most of the window.
- **EXTEND fits**: the fix landed **~14-16h before the gate**, inside the 300s observation
  window's self-clearing behavior and without a confirmed subsequent burst-and-flag cycle. This
  is exactly the "genuinely ambiguous, part of the window was compromised" case the gate task
  anticipates.

**Proposed extension:** short — the garage sensor bursts multiple times per day (13 bursts
observed in the single 12h reference day), so a fresh confirming burst should arrive within
hours, not days. Recommend **24h from whenever a live re-check is actually run**, not from now,
since no live re-check has happened yet against the corrected T_floor.

---

## What still needs a live read (requires an interactive session with HA access)

1. Confirm `select.ura_chatter_mode` is still `shadow` and `number.ura_chatter_t_floor` is still
   `5.0` (nothing should have silently reverted).
2. Read `chatter_telemetry` on `sensor.garage_a_unavailable_entities` (and ideally the full room
   sweep this routine was asked to do) for `binary_sensor.garageopener_gdoblaq_wifi_garagea_motion`
   specifically: has `sub_floor_burst_count` crossed `K=10` and `would_quarantine` flipped `true`
   on any burst since 19:33 CDT 2026-08-20? Cross-check the entity's own history
   (`ha_get_history`) for a burst timestamp to correlate against.
3. **Discriminator check (false-positive side):** sweep every other room's `chatter_telemetry`
   for any `would_quarantine: true` on a sensor NOT independently known to be chattering — a
   false positive here is disqualifying regardless of #2's result.
4. Scan URA logs for chatter-path DEBUG/NM lines and errors since the T_floor change, per the
   original task's step 2.
5. Log the result back into kanban card `STEP-SHADOW-EVIDENCE-WATCH-1` (the "NEXT CHECK" this
   audit found still open) so the next gate re-check isn't rebuilding this same context.

**If #2 confirms a clean true-positive AND #3 finds zero false positives:** flip to `act` is
supportable on the corrected evidence.
**If #2 still shows zero after a confirmed burst post-fix, or #3 finds a false positive:** the
defect is deeper than units (per the card's own escalation criterion) and the program should be
re-scoped, not simply re-extended again.

---

## Note on scope

This audit did not re-verify the code-level claims in the kanban card (units math, key
placement in `_NM_A2_KEYS`/`OPTIONS_RELOAD_SUPPRESS_KEYS`, etc.) against current source — those
were read from the prior session's write-up, not independently re-derived here, because this
run's purpose was live-evidence gathering (which failed) rather than a code review. A quick
grep-confirmation of `DEFAULT_CHATTER_T_FLOOR_S` and `_effective_t_floor_default()` would be
cheap follow-up if the operator wants the units claim itself double-checked before acting on it.
