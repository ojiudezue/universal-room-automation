# PLANNING — HVAC W1-B: Per-brand thermostat definition (Carrier/Bryant first) — REV 5

> **PROBLEM 1 — ALTERNATIVE A APPROVED (2026-09-27, operator).** Operator: *"yes. Its outdated design. We know a lot more. We didn't even know borrows would come back as manual then. Note that a and b are basically the same thing. I'm the only immune person currently that can be detected afaik. But I guess we should generalize."*
>
> Problem 1 is solved by **replacing the v3.8.0 S1 manual guard at `hvac_preset.py:202-217`**. Provenance chain / kill-switch / drift sensor / D0 merge blocker — **DROPPED**. Rulings 15/16 SUPERSEDED where they only existed to serve provenance.
>
> **REV-5 collapse (orchestrator mid-turn 2026-09-27, code-verified):** the earlier REV-5 draft carried TWO borrow-protection mechanisms — gate (e) reading `_row_present_and_fresh(zone_id)` at S1, AND a `BORROW_LOCK` funnel-side gate reading `_nudge_excursion_tokens` / `_nudge_restore_timers` / `_compromise_timers`. That is duplication. Every timer/token dict is populated STRICTLY AFTER `begin_excursion(...)` populates `_rows[zone_id]`, and the row's `stale_ts = started_ts + duration_s + EXCURSION_LEASE_SLACK_S` (`hvac_excursion.py:562/576`) covers the full timer window (per-kind `duration_s` already flows in — S3 at `hvac_override.py:3390` `self._compromise_minutes * 60`; S5 at `:4449` `duration_s`). Verified sequences:
>
> - COMPROMISE: `begin_excursion` `hvac_override.py:3383` → `emit_set_temperature` `:3414` → `self._compromise_timers[zone_id] = async_call_later(...)` `:3449`. Row present before timer.
> - NUDGE: `begin_excursion` `:4442` → `emit_set_temperature` `:4469` → `self._nudge_excursion_tokens[zone_id] = _ex_token` `:4491` → later restore scheduled at `:4613`. Row present before either dict.
>
> **No reachable window** exists where any of the three dicts is live but `_rows[zone_id]` is absent or stale. Therefore:
> - **Gate (e) is the ONE borrow predicate.** S1 consumes it; the arrester's `nudge_win` booking consumes it. `BORROW_LOCK` (its four sources, `BORROW_LOCK_CAP_FOR`, `_lock_capped` memo, `[BORROW LOCK CAP HIT]` NM) is **DELETED**.
> - **Per-kind bound is the row's `stale_ts`** — no new cap constant, no new memo, no new NM. The existing `stale_excursion_row` (low-severity NM at `hvac_excursion.py:293-334`, emitted by `_reap_stale` `:582`) IS the overrun notice.
> - **No "funnel-side gate" anywhere.** The rule lives ONLY at the S1 decision site (`should_change_preset` / `hvac.py:2626`). No changes to `emit_*` funnels in `hvac_setpoint.py`. No changes to `begin_excursion` / `return_excursion` / borrow code.
>
> Everything else in REV 5 retained: §5 D2.4 presets-only five-site setpoint-return migration, §5 D2.5 no-op suppression, §5 D2.6 anchors + AST lint, §5 D2.8 28-site table, §5 D2a `_last_emitted_range` split, D1 quad-state `WriteResult` + `allow_resume` kwarg, ruling 13 (nudge wins), **ruling 14 UI-max clamp for `hvac_compromise_minutes` (§5 D4a)** — retained as-is.

**Card:** `HVAC-W1-THERMOSTAT-DEFINITION` (Stage B).
**Tier:** **Tier 3** (delicate; S1 manual guard consumed by every preset-write path; S1 also reads the borrow registry).
**Depends on:**
- W1-A (`emit_set_hvac_mode` funnel + `climate_write`) — **SHIPPED v5.103.16**.
- Echo-fix — **SHIPPED v5.103.17 2026-09-27 ~10:45 CDT**.

**MANDATORY reads:**
`docs/Coordinator/HVAC_ARCHITECTURE_STATE_OF_PLAY.md` (all sections); `docs/Coordinator/THERMOSTAT_DEFINITION_CARRIER_BRYANT.md` rev 2; `README_v5.103.16.md` + `README_v5.103.17.md` + `README_v3.9.0.md:45-50` (arrester passive-mode); `hvac_excursion.py:6-16` (2026-08-21 lease-strip note); `hvac_excursion.py:293-334` (stale_excursion_row) + `:562-579` (`_row_present_and_fresh` bound); REV-4 plan review findings; card `operator_rulings_2026_09_27`.

---

## REV 5 change log

| Ruling / amendment | One-line delta | Where folded |
|---|---|---|
| 13 — nudge wins over human; remove human-ends-borrow | INV C3 rewritten. `_restore_after_nudge` untouched. Revival: nudge effective share < 80 % over 7 d → `HVAC-NUDGE-EFFECTIVENESS-REVISIT-1`. | §0 C3; §7 C3. |
| 14 — UI clamp for `hvac_compromise_minutes` (max 120 → 15) | `config_flow.py:6106` selector max trimmed to 15; stored > 15 clamped on read via `_read_hvac_compromise_minutes(options)` helper in `hvac_const.py`; sole decision consumer `__init__.py:3804/3862`. | §5 D4a. |
| 14 — per-kind borrow cap | **REPLACED by row's `stale_ts` bound** — no new constant. `stale_ts` already carries `duration_s + EXCURSION_LEASE_SLACK_S`; per-kind duration flows into `begin_excursion` today. | §5 gate (e). |
| 15 / 16 (SUPERSEDED where provenance-only) | Provenance classifier / learner / URA-owned reclaim writer / kill switch / drift sensor DROPPED under Alt A. | INV C4/C6 DROPPED; §5 D2.3 chain DELETED. |
| Mid-turn — Alt A approved | §5.P1 five-gate helper: (a/b) person-protected, (c) arrester grace/compromise, (d) arrester disabled (README v3.9.0), (e) active borrow row via `_row_present_and_fresh(zone_id)`. Rule lives at S1 only. | §5.P1; INV C-P1A/C-P1B; §7. |
| Mid-turn REV-5 collapse | BORROW_LOCK DELETED — gate (e) is the ONE borrow predicate consumed by S1 and by the arrester `nudge_win` booking. No funnel-side gate. | Front matter; §5.P1 gate (e); §0 C2 rewritten; §7 C2 rewritten; §5 D2.8 columns updated. |

---

## 0. Falsifiable invariant

> **INV-W1B (REV 5, Alt A + collapsed).** On a Carrier/Bryant zone, over the ship-gate floor (§7):
>
> **C1 (presets-only return).** Every URA borrow return emits ZERO `climate.set_temperature`, EXCEPT for HUMAN_MANUAL snapshots. Exhaustive list = five sites (§5 D2.4).
>
> **C2 (borrow protection via the row registry).** While `_row_present_and_fresh(zone_id)` is True (i.e. `_rows[zone_id]` exists and `now < started_ts + duration_s + EXCURSION_LEASE_SLACK_S`), S1 emits ZERO preset writes to that zone's entity AND the arrester books any `override_detected` on that entity with `gated_reason='borrow_active'` (or `'nudge_win'` when kind == NUDGE — see C3), NOT acting on it. The borrow's own return writes are exempt via `excursion_id` match. On stale (row exceeds `stale_ts`): `_reap_stale` emits `stale_excursion_row` (`hvac_excursion.py:293-334`; existing NM) and gate (e) disarms — normal writers resume on the next tick.
>
> **C3 (nudge wins).** For an active NUDGE (row present AND `_nudge_excursion_tokens[zone_id]` set), the arrester books `override_detected` with `gated_reason='nudge_win'` and does NOT revert. Restore runs unchanged.
>
> **C5 (no-op suppression at the funnel).** Zero service calls on a proven no-op.
>
> **C-P1A (S1 rewrites URA-caused zero-delta manual).** While the arrester is enabled AND no person-protected hold AND no arrester grace/compromise window AND `_row_present_and_fresh(zone_id) is False` AND S1's `effective_preset != "manual"`: S1 leaves the zone in `manual` for AT MOST one S1 decision tick.
>
> **C-P1B (S1 never races a legitimate hold).** S1 emits ZERO preset writes while ANY of the four Alt-A gates ((a/b), (c), (d), (e)) is armed for that zone.

### Falsification queries

| # | Query |
|---|---|
| C1 | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.verb')='set_temperature' AND json_extract(data,'$.site') IN (<D2.4 return sites>) AND json_extract(data,'$.reason') NOT LIKE 'human_manual_%';` MUST be 0. |
| C2 | Join `ura_activity_log`(`climate_write`) × `hvac_excursion_events` per `entity_id` × row `[started_ts, stale_ts]`; exclude `excursion_id` matches; count MUST be 0. `SELECT COUNT(*) FROM ura_activity_log WHERE action='override_detected' AND ...` during row window without `gated_reason IN ('borrow_active','nudge_win')` MUST be 0. |
| C3 | Any `override_detected` on an entity during active `_nudge_excursion_tokens[zone_id]` window WITHOUT `gated_reason='nudge_win'` MUST be 0. |
| C5 | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.wire_ok')=1 AND json_extract(data,'$.values_before')=json_extract(data,'$.values_after');` MUST be 0. |
| C-P1A | For every `preset_mode='manual'` window with arrester enabled, no person-protected hold, no arrester grace, no fresh borrow row, S1 target differs: interval until next `climate_write.site='S1_manual_write_through'` MUST be ≤ `HVAC_DECISION_TICK + 30 s`. |
| C-P1B | `SELECT COUNT(*) FROM ura_activity_log WHERE action='climate_write' AND json_extract(data,'$.site')='S1_manual_write_through' AND <gate-state snapshot at ts_issued showed any of (a/b)/(c)/(d)/(e) armed>;` MUST be 0. |

---

## 1. Institutional context verified

### 1.1 Prior-art scan — REUSE

- `_temp_arrester_override_active` — `hvac_override.py:463/858`.
- `_immune_holds` / `_is_hold_immune(zone_id)` — `hvac_override.py:448/656/705/727`. Generalised over `_immune_persons` (`:431/508-521`, populated from `CONF_HVAC_ARRESTER_IMMUNE_PERSONS` `hvac_const.py:189-198`).
- `_override_active[zone_id]` — `hvac_override.py:224/2102/3246/3303/2888`.
- `_compromise_timers[zone_id]` — `hvac_override.py:220/2153/2885/3449/3476`. **NOTE:** the timer dict is populated AFTER `begin_excursion` (§0). Kept as a read source for gate (c) — grace/compromise legitimacy, not borrow existence.
- `arrester.enabled` — property `hvac_override.py:2816`; log `:2897`; passive-mode `override_detected` `:3172-3186`. README `README_v3.9.0.md:45-50`.
- **`_row_present_and_fresh(zone_id)`** — `hvac_excursion.py:562` (module-level, public read-only). Reads `_rows` (populated by five `begin_excursion` sites); auto-reaps stale via `_reap_stale` `:582` → `stale_excursion_row` NM `:293-334`. Boot audit rehydrates. **THIS IS THE ONE BORROW PREDICATE for both S1 and the arrester `nudge_win` path.**
- Five `begin_excursion` sites (verified `develop` 2026-09-27): `hvac_override.py:3383` COMPROMISE (`duration_s = self._compromise_minutes*60`, `:3390`), `hvac_override.py:4442` NUDGE (`duration_s = duration_s`, `:4449`), `hvac_egress.py:655` EGRESS_PAUSE, `hvac_predict.py:1128` BANKING, `hvac_predict.py:1419` PREHEAT. Each populates `_rows` before its `emit_set_temperature` fires; no reachable window where the timer/token dicts are live but the row is absent/stale (see front matter).
- `_is_genuine_manual` — `hvac_override.py:~2434` (echo-safe).
- `should_change_preset` consumer: one site — `hvac.py:2626`.

### 1.2–1.5 (Unchanged.)

### 1.6 REV-4 review findings folded

Reviewer #1/#2 CRIT-2 → MOOT under Alt A. Reviewer #2 CRIT-3 → exhaustive 5-site setpoint-return inventory (§5 D2.4). Reviewer #2 CRIT-4 (LIVE-state derivation) → subsumed by gate (e) which reads the LIVE row registry. Reviewer #1 CRIT-3 → quad-state `WriteResult`. Reviewer #1 HIGH → regenerated 28-site table (§5 D2.8). Reviewer #2 HIGH → D1 truly behaviour-neutral. Reviewer #1 MED → `preset_mode` trust reads (§5 D2.6). Reviewer C → per-site mutation .pyc-safe.

---

## 2. Non-goals

- No provenance classifier / learner / URA-owned reclaim writer / kill switch / drift sensor.
- **No `BORROW_LOCK` funnel-side gate; no `BORROW_LOCK_CAP_FOR`; no `_lock_capped` memo; no `[BORROW LOCK CAP HIT]` NM.** Superseded by gate (e) + existing `stale_excursion_row`.
- No confirmation oracle / bounded retry.
- No knob-expiry reclaim (closed-by-A per §5.P4).
- No human-ends-borrow on NUDGE (ruling 13).
- No new state listeners.
- No `set_temperature` migration beyond removing setpoint from the 5 return sites.
- **No changes inside `begin_excursion` / `return_excursion` / any borrow code.**
- **No changes inside `emit_*` funnels in `hvac_setpoint.py`.**
- No Nest strategy code.

---

## 3. D0 — Read-only measurement (Alt-A form; not a merge blocker)

CONFIG-FIRST refresh; nudge-effectiveness sanity read; optional replay of the four §9.1 historical strands.

---

## 4. Deliverable order

1. **D0** (Alt-A form).
2. **D1** — Strategy interface, quad-state `WriteResult`, `allow_resume` kwarg, thin-forwarding.
3. **D4** — module constants (none new; `NUDGE_LOCK_CAP_SLACK_S` / `COMPROMISE_LOCK_CAP_SLACK_S` NOT ADDED — cap collapsed to row bound).
4. **D4a** — UI-max clamp for `hvac_compromise_minutes`.
5. **D5** — generic default.
6. **D2** — Carrier strategy: §5.P1 (S1 manual-guard replacement, four gates incl. gate (e)); §5 D2.4 five-site setpoint-return migration; §5 D2.5 no-op; §5 D2.6 anchors + AST lint; §5 D2.8 table enforcement; §5 D2a split.
7. **Live-validation write-back** into `README_v<version>.md`.

---

## 5. Deliverables

### D1 — Strategy interface

Unchanged. Quad-state `WriteResult = (status: {APPLIED, SKIPPED_ALREADY_CORRECT, DEFERRED, FAILED}, reason, exc)`. `FAILED` retains raise-semantics; `DEFERRED` covers gate skips (never latches NM). Truthiness banned. `hold_preset(..., allow_resume=True)`. No call-site migration. Registry-miss → GenericStrategy uncached. `_snapshot_climate_state` exempt.

### D2 — Carrier strategy

#### §5.P1 — S1 manual-guard replacement (Alt A, APPROVED)

Change site: `hvac_preset.py:202-217`. New signature carries `zone_id`. New helper `_arrester_is_legitimately_holding(zone_id) -> (refused: bool, reason: Optional[str])` — pure read; injected via constructor.

If `current_preset != "manual"` → return True. If `current_preset == "manual"` → return `not refused`. Store last reason for the caller's `preset_change_deferred` telemetry.

**The FOUR gates (all read-only, all pre-existing signals; rule lives ONLY here):**

| Gate | Condition | Signals (verified `develop` 2026-09-27) | Reason string |
|---|---|---|---|
| **(a/b) person-protected hold** | TAO on OR any immune-person hold active (generalised across `_immune_persons`). | `arrester._temp_arrester_override_active` OR `arrester._is_hold_immune(zone_id)` | `"person_protected_hold"` |
| **(c) arrester grace / compromise window** | Arrester inside its own override-handling window (grace or compromise; NOT a borrow). | `arrester._override_active.get(zone_id, False)` OR `zone_id in arrester._compromise_timers` | `"arrester_grace_or_compromise"` |
| **(d) arrester disabled (passive)** | Arrester off; still books passive-mode `override_detected` but never reverts. Safety rail. | `not arrester.enabled` (`hvac_override.py:2816`) | `"arrester_disabled_passive"` |
| **(e) active borrow row (ONE borrow predicate)** | A borrow of any kind is live on this zone. Reads the row registry — the same source of truth `begin_excursion` writes to, and the ONLY thing S1 or the arrester needs to know a borrow is in flight. Bounded by `stale_ts = started_ts + duration_s + EXCURSION_LEASE_SLACK_S`; auto-reaps to `stale_excursion_row` NM. | `hvac_excursion._row_present_and_fresh(zone_id)` (`hvac_excursion.py:562`) — reads `_rows` populated by the five `begin_excursion` sites (`hvac_override.py:3383` compromise, `:4442` nudge, `hvac_egress.py:655` egress, `hvac_predict.py:1128` banking, `hvac_predict.py:1419` preheat). Public read-only accessor already used by `begin_excursion`'s REJECT-on-existing-row path and by the boot audit. | `"active_borrow_row"` |

**Gap analysis — verified.** Every timer/token dict (`_compromise_timers`, `_nudge_excursion_tokens`, `_nudge_restore_timers`) is populated STRICTLY AFTER `begin_excursion` populates `_rows[zone_id]` (front matter cites the exact call ordering). Per-kind duration already flows into `begin_excursion.duration_s` (S3 `hvac_override.py:3390`; S5 `:4449`). The row's `stale_ts` therefore covers the full timer window plus `EXCURSION_LEASE_SLACK_S`. There is NO reachable window where the arrester's own timers are live but `_row_present_and_fresh` returns False → **no arrester-side timer read is needed** for gate (e) coverage. Gate (c) continues to read `_compromise_timers` for its OWN semantic — arrester grace/compromise legitimacy, distinct from "is a borrow live" — and that is correct: a compromise is BOTH an arrester window (gate c) AND a borrow row (gate e) simultaneously; both refuse; no conflict.

**Discharge for gate (e) (suppression-needs-a-discharge — enumerated):**
- **Row return** — every `return_excursion` clears the row (`_clear_row` `hvac_excursion.py:544-559`); next S1 tick unblocks.
- **Stale reap** — `_row_present_and_fresh` calls `_reap_stale` (`:582`) when `now >= stale_ts`; emits existing `stale_excursion_row` NM (`:293-334`). No new NM introduced.
- **Auto-release sweep** — `auto_release_on_incomplete` (`hvac_excursion.py:1322`).
- **Boot audit** — `async_startup_excursion_audit` clears stranded rows; the timer/token dicts do NOT survive restart either (in-memory), so no split-brain across boot.

**Arrester `nudge_win` booking (C3):** the arrester's `override_detected` path (`hvac_override.py:2304-2340`) reads `_row_present_and_fresh(zone_id)` AND checks `zone_id in _nudge_excursion_tokens` to distinguish NUDGE (→ `gated_reason='nudge_win'`) from other kinds (→ `gated_reason='borrow_active'`). Both suppress revert; only `nudge_win` also suppresses lockout counting per ruling 13. This is a READ inside the arrester's existing detection code — not a new listener, not a funnel gate.

**Every S1 write path touched.** `should_change_preset` consumer at `hvac.py:2626`; `zone_id` kwarg added at that site. `preset_change_locked_out` (edge-triggered telemetry `hvac.py:2630+`) rewritten as `preset_change_deferred` carrying `reason` — fires ONLY when a gate refuses.

**Step-by-step: genuine human manual (grace → compromise → S4 revert) intact.**

1. T+0: human writes manual. 2. T+0..15 s: temp suppression filters echoes. 3. T+~15 s: `_is_genuine_manual` True; `_override_active[zone_id] = True`; grace begins. 4. **T+~15 s .. grace_end (20 min):** gate (c) armed → S1 refuses (`reason='arrester_grace_or_compromise'`). 5. **T+grace_end (compromise armed):** S3 places compromise via `begin_excursion` (`:3383`) → `_rows[zone_id]` populated → gate (e) ALSO armed; `_compromise_timers[zone_id]` armed → gate (c) still armed. S1 refuses. Both gates enforce; no conflict. 6. **T+compromise_end (S4 revert):** row cleared by `return_excursion` in S4; `_compromise_timers` cleared; `_override_active` cleared. All four gates disarmed → next tick, if zone still reads `manual` (Carrier lag), S1 writes over.

**TAO / immune / arrester-disabled variants** — as prior draft, each honoured via the respective gate.

**URA-caused zero-delta manual (problem 1).** URA's return preset-only (D2.4) shouldn't create a manual. If one appears: no gate fires (arrester deliberately ignores; no borrow row; arrester enabled; no person-protected hold). S1 next tick sees `manual` + no gate → writes `home`. **Problem 1 closed.**

**Acceptance:** as prior draft, plus:
- `test_gate_e_covers_all_kinds` — parametric over the 5 begin sites; each `begin_excursion` populates `_rows`; S1 refuses with `reason='active_borrow_row'`; return clears; S1 unblocks.
- `test_gate_e_no_arrester_timer_gap` — arm each of `_compromise_timers`, `_nudge_excursion_tokens`, `_nudge_restore_timers` in isolation via a defer-in-source mutation (deferring `begin_excursion` by one line at each of the 5 sites) and confirm the matching `test_gate_e_active_during_<kind>` goes RED with a specific named failure. This proves the row is armed BEFORE any timer/token could be observed by S1 or the arrester.
- `test_gate_e_stale_reap_emits_stale_excursion_row_and_disarms` — advance time past `stale_ts`; `_row_present_and_fresh` returns False; existing `stale_excursion_row` NM fires (assert against NM channel); gate disarms.
- `test_arrester_nudge_win_booking_uses_row_registry` — active NUDGE; arrester's `override_detected` path books `gated_reason='nudge_win'`; discriminating: end nudge (clear row + token) → next detection books normally.
- `test_arrester_borrow_active_booking_for_non_nudge_kinds` — active COMPROMISE / BANKING / PREHEAT / EGRESS_PAUSE; arrester books `gated_reason='borrow_active'`; no revert.
- Per-site mutation of each of the 4 gates (.pyc-safe) → specific named test failure.
- **Live:** replay §9.1 four historical strands → each written over within one S1 tick when all gates disarmed.

#### §5.P2 — Supersession triage (deletions gated on §7 PASS)

| Item | File:line | Bucket | Justification |
|---|---|---|---|
| HIGH-1 skip rule + "D3 recovery parked" | `hvac_excursion.py:629-650` | DELETE | S1 recovers directly under Alt A. |
| D2b return re-pin | `hvac_predict.py:1540-1580` | KEEP + DOCUMENT | Faster path than one S1 tick. |
| Lockout ledger row | `hvac.py:2616-2675` | KEEP + WIRE | Repurpose to `preset_change_deferred` with gate reason. |
| Card `HVAC-PRESET-LOCKOUT-ESCAPE-1` | — | CLOSE | Alt A IS the escape. |
| Card `HVAC-ZONE1-MANUAL-OSCILLATION-1` | — | CLOSE | Strand class written over within one tick. |

#### §5.P3 — Write volume and preset-kind suppression

~80 nudges/day × 2 wire calls (resume + pin, via existing `emit_set_preset_mode` `_needs_resume_first` `hvac_setpoint.py:171-222`) = ~160 extra Carrier writes/day. Well within cloud call-rate bounds. `SUPPRESS_TTL_SECONDS_PRESET = 120 s` (`hvac_override.py:173/2798`) prevents the S1 reclaim being booked as a false override (Carrier echo lands inside the 120 s window). Verify: `test_s1_manual_write_through_sets_preset_suppression`.

#### §5.P4 — Problem 4 closed-by-A free of charge

Person-protected sunset → gate (a/b) disarms → next S1 tick reclaims. One test — `test_person_protected_hold_sunset_s1_reclaims_next_tick`. No new code beyond §5.P1. Ruling 3 (reclaim delay + kill switch) SUPERSEDED.

#### D2.4 Presets-only returns — 5-site setpoint-return inventory

| # | Site | File:line | Kind | Migration |
|---|---|---|---|---|
| 1 | S6 nudge restore setpoint | `hvac_override.py:4650` | NUDGE | DROPPED; `Strategy.return_borrow(allow_resume=False)`. |
| 2 | S8 cancel-nudge setpoint | `hvac_override.py:5877` | NUDGE (button) | DROPPED. |
| 3 | S9 boot audit setpoint | `hvac_override.py:6289` | NUDGE (boot) | DROPPED. |
| 4 | S11 banking release setpoint | `hvac_predict.py:984` | BANKING | DROPPED. |
| 5 | S13 pre-heat release setpoint | `hvac_predict.py:1520` | PRE-HEAT | DROPPED. |

Preset-return sites (kept, routed via `Strategy.return_borrow` + `allow_resume=False`): `hvac_excursion.py:667`, `:1131`; `hvac_override.py:3578`, `:4159`, `:4698`, `:5906`, `:6313`; `hvac_predict.py:1046`, `:1570`; `hvac_egress.py:815`.

`_auto_return` snapshot rules per value: named → pin only; `manual/None/""` → restore pre-borrow setpoints, no resume.

`S11._release_ok(zone)`: True iff banking token present AND banking release gate met AND (`zone.preset_mode != "manual"` OR no Alt-A gate armed).

Return order: mode → preset → setpoints only if snapshot classifies HUMAN_MANUAL.

#### D2.5 No-op suppression at the funnel

Unchanged. `SKIPPED_ALREADY_CORRECT` iff (verb, values) match last-sent AND observation matches. Distinct from `DEFERRED`.

#### D2.6 S1 + arrester + consumer wiring — behavioural anchors + AST lint

Trust-reader table + AST lint as prior draft. S1 also reads the borrow registry (`_row_present_and_fresh`) — import-only, no `preset_mode` read; AST `preset_mode` lint unaffected. The arrester's `nudge_win`/`borrow_active` booking also reads `_row_present_and_fresh` — covered by `test_arrester_*_booking_uses_row_registry` (§5.P1 acceptance) and a Reviewer-C mutation drill.

AST lint keyed by `(file, qualname)`; in-source marker `# preset_mode: display-only — <reason>`; alias normalisation; self-tests; precedent `quality/tests/domain_coordinators/test_hvac_climate_write_funnel_completeness.py`.

#### D2.8 28-site write table (regenerated against `develop` 2026-09-27)

| # | Site | Verb | Strategy method (or direct funnel + reason) | Gates consulted |
|---|---|---|---|---|
| 1 | `hvac.py:1941` | set_hvac_mode | direct — "heat_cool enforcer" | funnel-only |
| 2 | `hvac.py:2816` | set_preset_mode | `Strategy.hold_preset` (S1) | Alt-A four gates ((a/b), (c), (d), (e)); no-op |
| 3 | `hvac.py:3217` | set_temperature | direct — "S10 DPM baseline; F8-exempt" | freeze |
| 4 | `hvac_excursion.py:667` | set_preset_mode | `Strategy.return_borrow` (_auto_return) | no-op |
| 5 | `hvac_excursion.py:1131` | set_preset_mode | `Strategy.return_borrow` (boot NUDGE) | no-op |
| 6 | `hvac_override.py:3414` | set_temperature | `Strategy.borrow(kind=COMPROMISE)` (S3) | freeze |
| 7 | `hvac_override.py:3548` | set_hvac_mode | direct — "S4 revert mode" | funnel-only |
| 8 | `hvac_override.py:3578` | set_preset_mode | `Strategy.return_borrow` (S4) | gate (e) exempt via excursion_id |
| 9-11 | `hvac_override.py:3923/4045/4084` | set_hvac_mode | direct — "hard reset off/on" | funnel-only |
| 12 | `hvac_override.py:4159` | set_preset_mode | `Strategy.return_borrow` (hard reset restore preset) | — |
| 13 | `hvac_override.py:4469` | set_temperature | `Strategy.borrow(kind=NUDGE)` (S5) | freeze; ARMS gate (e) via `begin_excursion` |
| 14 | `hvac_override.py:4650` | set_temperature | **REMOVED in D2.4** (S6) | — |
| 15 | `hvac_override.py:4698` | set_preset_mode | `Strategy.return_borrow` (S6/S7 nudge restore) | gate (e) exempt via excursion_id, no-op |
| 16 | `hvac_override.py:5877` | set_temperature | **REMOVED in D2.4** (S8 cancel setpoint) | — |
| 17 | `hvac_override.py:5906` | set_preset_mode | `Strategy.return_borrow` (S8 cancel preset) | — |
| 18 | `hvac_override.py:6289` | set_temperature | **REMOVED in D2.4** (S9 boot setpoint) | — |
| 19 | `hvac_override.py:6313` | set_preset_mode | `Strategy.return_borrow` (S9 boot preset) | — |
| 20 | `hvac_predict.py:984` | set_temperature | **REMOVED in D2.4** (S11 setpoint) | — |
| 21 | `hvac_predict.py:1046` | set_preset_mode | `Strategy.return_borrow` (S11 preset) | `S11._release_ok` |
| 22 | `hvac_predict.py:1167` | set_temperature | `Strategy.borrow(kind=BANKING)` (S12 pre-cool — CORRECTED) | freeze |
| 23 | `hvac_predict.py:1456` | set_temperature | `Strategy.borrow(kind=PREHEAT)` (S13 start) | freeze |
| 24 | `hvac_predict.py:1520` | set_temperature | **REMOVED in D2.4** (S13 setpoint) | — |
| 25 | `hvac_predict.py:1570` | set_preset_mode | `Strategy.return_borrow` (S13 preset) | — |
| 26 | `hvac_egress.py:688` | set_hvac_mode | direct — "egress pause mode" | funnel-only |
| 27 | `hvac_egress.py:794` | set_hvac_mode | direct — "egress resume mode" | funnel-only |
| 28 | `hvac_egress.py:815` | set_preset_mode | `Strategy.return_borrow` (egress resume preset) | — |

**No funnel-side BORROW_LOCK column** — deleted with the mechanism. S1's site 2 writes with `reason="s1_manual_write_through"` when moving a zone out of `manual`.

Verify at build-start: `git grep` returns exactly these 28 rows. Any drift → refresh in the SAME commit.

#### D2a — Split `_last_emitted_range`

Unchanged. Funnel's `last_sent` (per-verb, no-op suppression) vs `HvacZoneBaseline` (S10/DPM). Byte-identical.

### D4 — Module constants

**No new constants.** `NUDGE_LOCK_CAP_SLACK_S` / `COMPROMISE_LOCK_CAP_SLACK_S` / `BORROW_LOCK_HARD_CAP_S` NOT ADDED — cap collapsed to the row's `stale_ts = duration_s + EXCURSION_LEASE_SLACK_S` (existing). `URA_OWNED_*` NOT ADDED (Alt-B chain dropped).

No Rung-3 kill switch entity. No drift telemetry sensor.

### D4a — UI-max clamp for `hvac_compromise_minutes` (ruling 14, RETAINED)

`config_flow.py:6106` selector `max=120` → **`max=15`**. Inspect `:5906` same edit. Strings/translations unchanged. Code-side constants unchanged.

Stored-value handling: **CLAMP ON READ** via `_read_hvac_compromise_minutes(options)` in `hvac_const.py` — `min(15, options.get(CONF_HVAC_COMPROMISE_MINUTES, DEFAULT))`. Single install (`project_single_user_no_backcompat`); not a migration; not "warn-and-leave"; reversible; idempotent.

Read sites: `config_flow.py:5906/6103` (display), `__init__.py:3804/3862` (decision consumer — sole clamp site).

Acceptance: `test_config_flow_hvac_compromise_minutes_max_is_15`; `test_read_hvac_compromise_minutes_clamps_stored_20_to_15`; live: slider max 15; stored 20 clamps to 15 at first read.

### D5 — Generic default (unchanged from REV 4)

---

## 6. Operator questions — none

---

## 7. Ship gate

Pre-deploy: replay §9.1 four historical strands + the four-gate parametric matrix + gate-(e) discharge matrix (row return / stale reap → `stale_excursion_row` / sweep / boot audit). Any strand-not-cleared or gate-violation → BLOCK.

Post-deploy disposition at N ≥ 10 non-nudge return episodes per zone (7-day cap). §0 queries.

PASS → dispose + execute §5.P2 DELETE-bucket.

---

## 8. Review protocol — Tier 3

**Reviewer A — local correctness.** Four gate reads at correct signals; `_last_manual_refusal_reason` discipline; `_row_present_and_fresh` semantics (bounds, reap); D2.8 cell-by-cell; verify NO funnel-side gate anywhere.

**Reviewer B — integration / state-machine integrity.** Gap analysis: verify NO reachable window where `_compromise_timers` / `_nudge_excursion_tokens` / `_nudge_restore_timers` is live but `_rows[zone_id]` is absent/stale (re-run the code trace from the front matter independently). Gate (c) cleared at S4 revert. Gate (d) under passive `override_detected`. Arrester `nudge_win` / `borrow_active` booking reads the row registry, not the timer dicts. `stale_excursion_row` NM path unchanged; not double-emitted. Operator constraint honoured (no changes to borrow code, no changes to funnels).

**Reviewer C — test authority via REAL per-site source mutation.** `PYTHONDONTWRITEBYTECODE=1` + cache clear. Each of the 4 gates mutated. Each of the 5 `begin_excursion` sites deferred by one line → corresponding `test_gate_e_active_during_<kind>` RED. Every migrated D2.4 site; every D2.8 site; D2a; D4a. Arrester `nudge_win` / `borrow_active` booking mutations. Each mutation → specific named test failure.

**Reviewer D — adversarial completeness.** Re-enumerate every path that could set `hold_activity == manual` from URA. Confirm gate (e) covers ALL five borrow kinds and the arrester's `nudge_win` reads the same source. Confirm NO funnel-side gate (grep `emit_*` bodies for any borrow-registry read — MUST be zero). Confirm `S11._release_ok` cannot fire under an Alt-A gate. Falsify INV C-P1A / C-P1B / C2. Confirm the gate-(e) restart-gap analysis holds (in-memory timer dicts don't survive restart; boot audit rehydrates rows). Confirm no config toggle can silently disable a gate without breaking a specific named test.

**Two plan reviews before build dispatch:**
1. **Completeness.** Re-run the code-trace gap analysis (front matter) — verify per-kind `duration_s` flow-through at S3 `hvac_override.py:3390` and S5 `:4449`; verify `stale_ts = duration_s + EXCURSION_LEASE_SLACK_S`; verify `stale_excursion_row` NM is the discharge for cap overrun; verify no funnel-side gate.
2. **Adversarial build-prediction.** Predict what a builder will get wrong. Specifically challenge: does the plan say gate (e) is the ONE borrow predicate (no funnel-side gate, no BORROW_LOCK)? Does it say the arrester's `nudge_win` booking reads `_row_present_and_fresh` + `_nudge_excursion_tokens`, not any `BORROW_LOCK`? Does it say the row's `stale_ts` bounds the borrow window and `stale_excursion_row` is the overrun NM?

**Orchestrator hand-check before deploy:** re-grep 28 sites + 5 begin sites; real source mutation of each of the 4 gates + each migrated site + each begin-site defer drill; AST lint; §9.1-historical replay; gate-(e) stale-reap drill; verify slider max = 15 post-deploy AND stored 20 clamps; verify `preset_change_deferred` telemetry fires with correct reasons and never on a URA-caused zero-delta manual; **grep `emit_*` bodies for any borrow-registry read (MUST be zero)**.

**Operator checkpoint before deploy:** invariant proof; 5-site setpoint-return coverage; 28-site table; four-gate parametric demo incl. all four gate-(e) discharge paths; config-flow slider max.

---

## 9. Sequencing / dependencies

1. W1-A **SHIPPED v5.103.16**.
2. Echo-fix **SHIPPED v5.103.17**.
3. **Alt A APPROVED 2026-09-27** + **REV-5 collapse (BORROW_LOCK → gate (e))**.
4. Two plan reviews on this REV 5.
5. Build in worktree `.claude/worktrees/hvac-w1b-thermostat-definition`.
6. Build order: D1 + D4 + D4a + D5 → D2 (§5.P1 four-gate helper + `should_change_preset` replacement + `preset_change_deferred` telemetry rewrite; D2.4 five-site migration + preset-return `allow_resume=False`; D2.5; D2.6; D2.8; D2a). **Arrester `nudge_win` / `borrow_active` booking** updated in the arrester's existing detection code (`hvac_override.py:2304-2340`) as part of D2 — a READ addition, not a new listener; still not a "funnel-side gate" (the funnel is not touched).
7. Four framing-disjoint reviews in parallel. Fix CRIT/HIGH.
8. Operator checkpoint. Deploy.
9. Live-validation write-back.
10. Post-deploy disposition at N ≥ 10.
11. On §7 PASS: execute §5.P2 DELETE-bucket.

Not this cycle: `HVAC-WRITE-CONFIRMATION-ORACLE-1`.

**No soak.**

---

## Operator decisions — BINDING (verbatim; annotate, never edit earlier text)

**REV 3 (2026-09-26 "Accept recs"):**
1. `set_activity_setpoint` NOT adopted this cycle.
2. No in-code schedule-boundary guard.
3. Reclaim DELAY + kill switch. [REV 5: SUPERSEDED by Alt A — reclaim path doesn't exist; no delay, no kill switch.]
4. Ship-gate N ≥ 10, replay pre-deploy.
5. No Nest stub.
6. Timing values Rung 1. [REV 5: no new timing values; `stale_ts` bound is the row's existing property.]
7. Reclaim on TAO / immune-person expiry against HUMAN hold. [REV 4: REMOVED per decision 8.] [REV 5: closed-by-A per §5.P4.]

**REV 4 (2026-09-26 evening):**
8. Scope = problems 1, 2, 3, 5.
9. Borrow lock nudges + compromises only, hard cap 10 min, LIVE-state, `excursion_id` exempt, one NM at cap. [REV 5 (2026-09-27, orchestrator finding + operator SIMPLIFY direction): SUPERSEDED. Code-verified: every timer/token dict is populated strictly after `_rows[zone_id]`; per-kind `duration_s` already flows into `begin_excursion`; row's `stale_ts = duration_s + EXCURSION_LEASE_SLACK_S` covers the full timer window. Therefore the ONE borrow predicate is gate (e) (`_row_present_and_fresh`), consumed by S1 AND by the arrester's `nudge_win` booking. `BORROW_LOCK_CAP_FOR`, `_lock_capped` memo, `[BORROW LOCK CAP HIT]` NM DELETED — bound = row's `stale_ts`; overrun NM = existing `stale_excursion_row` (`hvac_excursion.py:293-334`). No new borrow code; no funnel-side gate; operator constraint honoured.]
10. Genuine human change during a locked borrow ENDS the borrow. [REV 5: REVERSED by decision 13 — nudge WINS.]
11. Problem 1 = presets-only returns + in-memory W1-A last-write record; URA-owned reclaim. [REV 5: SUPERSEDED by Alt A — presets-only returns retained (§5 D2.4); URA-owned reclaim NOT built; S1 writes over residual manual directly, gated by four legitimacy conditions (§5.P1).]
12. CONFIG-FIRST.

**REV 5 (2026-09-27):**
13. **Decision 10 REVERSED: nudge WINS.** Evidence 564/579 (97 %). Revival: nudge effective share < 80 % over 7 rolling days → `HVAC-NUDGE-EFFECTIVENESS-REVISIT-1`.
14. **UI max for `hvac_compromise_minutes` trimmed 120 → 15 min**; stored > 15 clamped on read. [REV-5 collapse: the per-kind borrow-cap portion of ruling 14 is honoured via the row's existing `stale_ts` bound — no new cap constants; only the UI clamp lands as new code.]
15. [SUPERSEDED where provenance-only.]
16. [SUPERSEDED where provenance-only.]

**Mid-turn (2026-09-27, operator):** *"yes. Its outdated design. We know a lot more. We didn't even know borrows would come back as manual then. Note that a and b are basically the same thing. I'm the only immune person currently that can be detected afaik. But I guess we should generalize."* → **Alt A APPROVED.**

**Mid-turn amendment (2026-09-27, orchestrator + operator constraint):**
- Add gate (e) via `_row_present_and_fresh(zone_id)` — the v3.8.0 lease strip relied on the manual-lockout as protection; removing the lockout under Alt A requires S1 to check the registry directly.
- Rule lives ONLY at S1; borrow code and funnels untouched.

**Mid-turn REV-5 collapse (2026-09-27, orchestrator SIMPLIFY direction):**
- `BORROW_LOCK` (four LIVE-state sources, `BORROW_LOCK_CAP_FOR`, `_lock_capped`, `[BORROW LOCK CAP HIT]` NM) DELETED. Gate (e) is the ONE borrow predicate. Bound = row's `stale_ts`. Overrun NM = existing `stale_excursion_row`.
- No funnel-side gate anywhere. No changes to `emit_*` funnels. No changes to `begin_excursion` / `return_excursion` / borrow code.
- Gap analysis proved no reachable window where an arrester timer/token is live without a fresh row.

---

## REV 5 delta summary (for reviewers)

- **Collapsed:** BORROW_LOCK DELETED. Gate (e) = the ONE borrow predicate for S1 AND arrester `nudge_win`/`borrow_active` booking. Bound = row's `stale_ts`. Overrun = existing `stale_excursion_row` NM.
- **No funnel-side gate anywhere** — grep the plan; no gate lives in `hvac_setpoint.py`; no changes to borrow code.
- **Retained:** ruling 13 (nudge wins); ruling 14 UI clamp (§5 D4a); five-site setpoint-return migration (§5 D2.4); no-op suppression; anchors + AST lint; 28-site table with actual verbs; D1 quad-state `WriteResult`; same-tick ordering DROPPED (was tied to BORROW_LOCK arming; under gate (e) it is not needed — a nudge start that populates `_rows` immediately arms gate (e), so any subsequent same-tick S1 write for that zone is already refused).
- **Deleted (REV-5 collapse):** `BORROW_LOCK_CAP_FOR`, `NUDGE_LOCK_CAP_SLACK_S`, `COMPROMISE_LOCK_CAP_SLACK_S`, `_lock_capped` memo, `[BORROW LOCK CAP HIT]` NM, `_zones_written_this_tick` set.
- **Corrected:** 28-site table has actual verbs; 7 `set_hvac_mode` stay direct-funnel; only 5 setpoint-return writes exist to migrate; S12 = BANKING; `S11._release_ok` redefined; gate (c) STAYS separate (grace/compromise, not a borrow).
- **Gap analysis (verified in code):** every `_compromise_timers` / `_nudge_excursion_tokens` / `_nudge_restore_timers` setter is dominated by a preceding `begin_excursion(...)` that populates `_rows`; per-kind `duration_s` already threads through (S3 `hvac_override.py:3390`, S5 `:4449`); row `stale_ts` covers the full timer window plus slack. No reachable gap.

**Falsifiable invariant (one sentence, REV 5 collapsed):** on a Carrier/Bryant zone, no URA borrow return writes a raw setpoint (except HUMAN_MANUAL); while `_row_present_and_fresh(zone_id)` is True, S1 emits zero preset writes to that zone and the arrester books `override_detected` as `nudge_win` (NUDGE) or `borrow_active` (other kinds) without reverting (borrow's own return exempt via `excursion_id`); the nudge wins over any human change for its duration; the funnel emits zero service calls on a proven no-op; AND while the arrester is enabled, no person-protected hold or arrester grace/compromise window is armed, AND no fresh borrow row exists, S1 leaves the zone in `manual` for at most one decision tick; conversely S1 emits zero preset writes while ANY of the four Alt-A gates ((a/b), (c), (d), (e)) is armed.

**Open questions: none.**
