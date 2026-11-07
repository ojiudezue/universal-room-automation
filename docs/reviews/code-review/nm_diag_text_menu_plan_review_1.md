# Plan review 1: PLANNING_nm_diag_text_menu.md (NM-INBOUND-HOUSE-QUERIES-1)

Reviewer: ura-reviewer (adversarial plan review, Tier 2 plan-review protocol), 2026-11-07.
Plan rev reviewed: rev 1 (commit 8ff5bfe1). Read-only; no code or plan edits.
Mandatory reads: HVAC / PRESENCE state-of-play docs not re-read for this pass; the plan only displays their values, and no finding below depends on them. Every claim here was checked against `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` (NM) on develop.

**Verdict: FIX-PLAN.** The design is sound and the two-rail idea is right. Three ordering and producer gaps need fixing in the plan before build, plus a correction to how the plan describes its own safety case.

---

## Re-enumeration (done independently with greps)

**Inbound entry points into `_process_inbound_reply` (NM:3547):** companion `:3389`, `:3393`, `:3400` (person None); WhatsApp event `:3415` (via `async_create_task`, bus listener `:1248`); Pushover webhook `:3437` (registered `:1255`); BlueBubbles webhook `:3475` (registered `:1266`, `isFromMe` skip `:3456`). Six calls in total, which matches the plan. There is no other inbound text listener in NM (`async_listen` at `:1204` is companion actions and `:1248` is WhatsApp).

**Outbound text senders.** All four have the dry-run return as their first statement: `_send_pushover` `:2226`, `_send_companion` `:2266`, `_send_whatsapp` `:2329`, `_send_imessage` `:2372`. Callers:

| Caller group | Lines | Covered by a rail at the top of the sender? |
|---|---|---|
| `async_notify` per-person fan-out | 1909 / 1931 / 1958 / 1980 | yes |
| repeat cycle | 2944 / 2951 / 2959 / 2966 | yes (state is REPEATING, so the state rail also covers it) |
| `_send_reply` (all legacy and diag replies) | 4052 / 4056 / 4061 / 4065 | exempt by `menu_safe` (intended) |
| daily digest | 5002-5049 | yes |
| `async_test_notification` (`:5340`; the caller the plan left unnamed) | 5359 / 5364 / 5369 / 5374 | yes |
| `_send_tts` `:2398`, alert lights `:2485`, halo panel `:5708`, ack TTS `:3923` | n/a | not text; correctly excluded |
| **Repo-wide bypass:** `aggregation.py:1602` zone safety alert through legacy `notify.<CONF_NOTIFY_SERVICE>`; `button.py:482` export notify | n/a | **NOT covered.** No `Reply: 1=Ack` body is attached, so these do not invite digits (LOW, F9) |

Where the plan says "first statement, before the dry-run return", that covers every NM text send. It does not cover the non-NM notify paths.

---

## Findings (ranked)

### HIGH-1: Window-open epoch capture is not ordered, so I1 can be broken (class: capture-before-await / under-specified ordering)
D2 says "each window stores the epoch at open", and §2.2 calls `_resolve_diag` "pure (no I/O)". But a `diag` token has to open the window, which is a mutation, and the plan never says whether that happens in `_resolve_diag` (synchronously, before any await) or in the dispatch branch, which runs after `await self._log_and_reply(...)` (DB write plus the `_send_reply` service call, NM:4012-4033).
**Repro:** operator texts `diag`. The builder opens the window after the reply is sent. During the blocking `whatsapp.send_message` await, a CRITICAL `async_notify` reaches `_send_whatsapp`, bumps the epoch to E+1, and sends. The reply returns and the window is stored with epoch E+1. The operator sees the CRITICAL and texts `1`. The state is still IDLE, because `_enter_alerting` runs only after every per-person send and DB log (NM:2099). The epoch matches, so the `1` returns the doors answer and not the legacy "CRITICAL alert requires safe word". I1 is violated.
**Fix in plan:** read `self._diag_send_epoch` into a local at the top of `_process_inbound_reply`, or synchronously in step 4 before any await on the path, and store that captured value. Add a test that bumps the epoch from inside a patched `_send_reply` and asserts that a later digit is legacy.

### HIGH-2: Diag replies still stamp rail 2, so later safe-word, silence and ack confirmations get swallowed (class: cross-path interaction / suppression without discharge)
`_log_and_reply` stamps `self._last_reply_at[key] = now` on every non-rate-limited send (NM:4032). The plan exempts diag commands from the floor but does not say whether diag replies still stamp it. If the builder only adds `diag_*` to `NM_REPLY_RATE_LIMIT_EXEMPT_COMMANDS`, the stamp still happens.
**Repro:** operator texts `doors` at t0 (reply stamps the (operator, imessage) key). A CRITICAL lands, and at t0+20 s he sends his safe word. `async_acknowledge` runs (NM:3711), but the reply "CRITICAL alert acknowledged by …" falls inside 30 s of a stamped reply. `safe_word` is not exempt (NM:280-287), so the confirmation is dropped. The operator gets no feedback on a CRITICAL ack and re-sends. `silence` and `ack` confirmations are dropped the same way. "Check doors, then ack" is the main use case this feature creates.
**Fix in plan:** exempt diag replies from the floor AND do not stamp `_last_reply_at` for them (the per-sender diag budget is their own loop bound). Pin this with a test: `doors`, then safe word within 30 s, and the confirmation is sent.

### MEDIUM-3: The safety case misdescribes which rail carries the load (class #63, coincidental equality masking a concept split)
§2.3 calls the state rail "primary". But `_enter_alerting` is called only for `Severity.CRITICAL` (NM:2098-2099, its only call site). Every HIGH, MEDIUM or LOW alert, each of which carries `Reply: 1=Ack 2=Status 3=Silence` (NM:1740-1742), leaves `_alert_state` IDLE. For all non-CRITICAL alerts the state rail is inert and the send rail is the only guard. The claim "neither rail alone… together they are independent" is false for non-CRITICAL: a future emitter that bypasses the four senders and sends a HIGH alert leaks. Because `has_active_alert` implies a CRITICAL `_active_alert_data`, legacy `1` never acks anything by text (NM:3810-3819). The effectful collision digit is `3` (silence, NM:3830-3836), not `1`.
**Fix in plan:** restate I1's stakes around `3`/silence and around reply-text fidelity for `1`/`2`. Make the send rail's coverage the invariant that is enforced by test: an NM-wide AST check that no `hass.services.async_call` to `whatsapp` / `bluebubbles` / `notify` / the pushover service appears outside the four senders. That is stronger than the proposed `test_every_text_sender_bumps_epoch_ast`, whose rule for "text payload" a builder cannot pin down (F10).

### MEDIUM-4: Grid reading uses the raw, unit-unsafe getter while a normalized sibling exists (class #7 stale/wrong source)
The plan reads `net_power` (energy_battery.py:2411) and marks the existence of a gated sibling UNVERIFIED. `net_power_w` exists at energy_battery.py:2591 ("normalized to W… safe across kW/W firmware variants", `_read_power_w`). It is a W-normalized sibling; it is not staleness-gated like `solar_production_w`. **Fix:** use `net_power_w`, and keep the plan's age render for staleness.

### MEDIUM-5: The I4 golden test has no specified oracle source (class #62 hollow anchor risk)
"Identical before vs after" only means something if the expected strings and calls were captured from the pre-cycle code, either as fixtures recorded at `pre-review` or by running both code paths. A builder will most likely write expectations by reading the new code, which makes the test circular. **Fix:** specify that golden fixtures are captured once from the merge-base and committed, or that the test runs with `NM_DIAG_ENABLED=False` vs True and compares the two (the plan already offers both values in §8; make that the oracle).

### MEDIUM-6: A digit sent after a send-rail close can silently silence alerts (UX, the conservative-for-ack direction is the risky one for silence)
Repro: operator texts `diag`, a HIGH perimeter alert goes out (closing the window), then the operator replies `3` meaning `who`. Legacy silence runs and non-CRITICAL alerts are suppressed for 30 min (NM:1540). That is the I1-intended outcome, but the user meant "who", and nothing tells him the menu was closed. **Fix in plan:** either append "(menu closed by an alert; words still work)" to legacy replies when a digit hits a send-closed window, or accept this residual explicitly in §2.3 next to the pre-emptive-silence residual. Also specify the menu text shown while state ≠ IDLE ("numbers off during an alert, use words").

### LOW-7: The AST read-only lint is shallow
It inspects `house_status.py` syntax only. Getters it calls have side effects. `solar_production_w` writes LKG RAM stamps (energy_battery.py:2577-2580), and `battery_soc`'s resolver may do the same. These are benign (true values), but the I2 claim should say "no actuation or persistent write", and the behavioural I2 test (D3 service-call recorder) is the real guard. Name it as such.

### LOW-8: Producer details a builder will trip on
`get_person_location` takes `person_name`, not an entity id (`person_coordinator.py:1981`; the file is at the package root, not under `domain_coordinators/`). `CoordinatorManager.house_state` returns a `HouseState` enum (manager.py:325-327), so render `.value`. `get_active_criticals` has `limit=50` and no age bound (database.py:4939). The age cap must be applied in `house_status`, reusing `NM_RECOVERY_MAX_AGE_H` (NM recovery `:5228-5236`) with 0 meaning "no bound".

### LOW-9: Non-NM notify bypasses are not enumerated
`aggregation.py:1602` and `button.py:482` call `notify.*` directly. They carry no response dictionary, so they do not invite digits, but §4's claim "every NM text send" should list them as out of scope by name.

### LOW-10: Ambiguities a builder will get wrong
- Where the window dict is written (see HIGH-1), and whether a `diag` resent inside an open window refreshes `opened_at` and the epoch.
- How the AST test recognises "text sender" (name list vs payload shape). Use an explicit allowlist of the four functions.
- Positional call sites: `menu_safe` must be keyword-only, so the 20+ positional callers (e.g. `:1909`, `:5016`) stay unchanged.
- Companion: `(None, "companion")` can open a window from the CRITICAL textInput field (NM:3396-3401). It is harmless (no reply), but say so, or skip diag when `person_id is None`.
- Dry-run: diag replies are also dry-run short-circuited, so the Live criteria assume dry-run is off. State this.
- `NM_DIAG_REPLY_BUDGET = 0` has odd semantics ("one over-budget reply per window"). Document `NM_DIAG_ENABLED` as the only kill switch.

### Cleared (holds because…)
- **Safe-word precedence:** `is_safe_word` is computed (NM:3650) before the proposed step 4, and the window pre-parse rebinds `text` first (NM:3586-3649). Diag gated on `not is_safe_word` keeps the safe word winning.
- **Restart with a window open:** windows are RAM-only, so a restart closes them all. `_recover_state_from_db` (NM:5196) restores the alert state independently. I1 holds.
- **Echo (I3):** every WhatsApp/iMessage outbound is `"*{title}*\n"` / `"{title}\n"` plus the body (NM:2333, 2376) and is recorded after dispatch (2349, 2392). Exact whole-text matching after `strip().lower()` cannot equal a single token while a `\n` sits inside. Pushover and Companion cannot self-echo (NM:281-284). This holds as long as no first-token parse is ever added, so keep §2.1's rule as a pinned test.
- **Two channels or two persons:** the send rail is house-wide (any send closes all windows), so a send to Jaya closes the operator's window too. This is conservative and correct.
- **Institutional context:** NOTIFICATION_MANAGER.md, the c4b plan, the BB plan and the memory body all exist. NM-BB-CHATGUID-SELFSEND-1 (kanban:8566) is correctly treated as a D0 gate. Note: per that card, the self-thread *receive* copy may arrive with `isFromMe=False` (the 08-05 echo mechanism), so operator iMessage inbound may work. D0 measures this, which is correct.
- **Knob ladder:** all numbers are named at rung 1 with reasons. `NM_DIAG_ENABLED` and `NM_DIAG_MENU_WINDOW_S=0` are real kill switches. Non-goals are explicit.
- **Tier:** I agree with the suggested elevation to three framing-disjoint reviews.

## Must-fix before build
1. HIGH-1: capture the epoch synchronously at inbound start and specify where the window is written.
2. HIGH-2: diag replies must not stamp `_last_reply_at`, plus a test (diag then safe word within 30 s, confirmation sent).
3. MEDIUM-3: correct the rail narrative (send rail is the only guard for non-CRITICAL; `3` is the effectful digit) and add the NM-wide "no text `async_call` outside the four senders" AST test.
4. MEDIUM-4: `net_power` → `net_power_w`.
5. MEDIUM-5: specify the I4 golden oracle (`NM_DIAG_ENABLED` False vs True, or fixtures from the merge-base).
6. MEDIUM-6: either a notice on digits after a send-closed window or an explicit residual, plus the menu text while not IDLE.

| Severity | Found |
|---|---|
| HIGH | 2 |
| MEDIUM | 4 |
| LOW | 4 |
