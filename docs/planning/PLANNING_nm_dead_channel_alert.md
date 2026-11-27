# PLANNING: NM dead-channel alert

Card: NM-IMESSAGE-OUTBOUND-DEAD-1 (dead-channel alert half; the outage half closed 2026-11-27 02:47).
Approval: operator 2026-11-27, "Approved but how will i receive the alert? WhatsApp ?"
Tier: **Tier 2** (one adversarial plan review before build; two framing-disjoint code reviews + live validation). See section 8.

## 0. Why

iMessage (BlueBubbles) failed 100% of sends from 2026-11-22 17:12 to 2026-11-27 02:43 (445 failures, Cloudflare
HTTPS redirect). Nobody was told for 4.5 days: other channels delivered, `notification_log` marks multi-channel rows
`delivered=1`, and the only surface was a diagnostic sensor reading `degraded`. Operator-approved behavior: when one
channel has failed every send for N hours, NM tells the operator on a channel that still works.

## 1. Institutional context verified

### 1a. Greps run (2026-11-27) and REUSE-or-BUILD per piece

| Piece | Verdict | Evidence |
|---|---|---|
| Per-channel health state | REUSED | `_channel_health` seed `notification_manager.py:513-523`; updated only by `_update_channel_health` `:7163-7187` (degraded at 3 consecutive failures, reset on success). In memory only. |
| Health producer call sites (the hook point) | REUSED | Every transport send goes through four helpers, and only they call `_update_channel_health` for message channels: pushover `:2666/:2669`, companion `:2746/:2749`, whatsapp `:2812` (wa_bridge not ready) `:2822/:2826`, imessage `:2922/:2925`. Callers of those helpers: main fan-out `:2170/:2195/:2227/:2254`, CRITICAL repeat `:3691-3716`, inbound replies `:5217-5232`, digest flush `:6234-6283`, `:6613-6628`. tts `:2950/:2953`, lights `:2991`, panels `_set_panel_health :7149` are out of scope (section 7). |
| Channel set in scope | REUSED | `NM_DIGEST_CHANNELS` `const.py:4749` = ("pushover","companion","whatsapp","imessage"). |
| "degraded" display | REUSED, unchanged | `NMChannelStatusSensor` `sensor.py:9407-9456` (producer of `sensor.ura_notification_manager_notification_channel_status`; reads `nm.channel_status` `notification_manager.py:983`). `NMDiagnosticsSensor.native_value` `sensor.py:9706` also reads it. Display only; no trust decision. |
| Restart-surviving latch | REUSED pattern: HA `Store` latch, `room_entities.py:118-143` (`PAGE_LATCH_STORE_KEY`, `_store`, load/save) | Considered and REJECTED: NM's RestoreEntity blob (`get_persistence_state :1133`, restored at `sensor.py:9665-9690`). Two reasons: its main restore is behind an IDLE gate (`sensor.py:9678`; only `restore_repeat_home_budget :1186` escapes it), and RestoreEntity saves the last *written* entity state, so a `failing_since` set inside `_update_channel_health` would not be persisted unless the diagnostics sensor happens to be rewritten. The Store is written explicitly on each transition. |
| Operator alert emit + anomaly trip-wire + retry-on-drop | REUSED | `fire_stuck_signal` `domain_coordinators/_stuck_signal_nm.py:173` (writes the anomaly row `:127-170`, honors kill switch `:70-87`, sets no latch when NM drops the emit so it retries, accepts `severity="HIGH"` `:182-190`). Same helper `room_entities.py:146` uses. |
| Sibling trip-wire precedent | REUSED as template | `_maybe_fire_no_route_tripwire` `notification_manager.py:2449-2510` (NM-NO-CHANNEL-FIRED-1): anomaly + `async_notify(Severity.HIGH, ...)`. |
| HA persistent notification fallback | REUSED pattern | `persistent_notification.create` call shape `button.py:1279`, `hvac_override.py:7305`. |
| `NM_CHANNEL_DEAD_ALERT_H` | NEW | Grepped `const.py`, `notification_manager.py` constants block (`:290-300`), config/options flow for `dead`, `channel_dead`, `DEAD_ALERT`: no hit. Card proposes it. |
| `NM_CHANNEL_DEAD_MIN_FAILURES` | NEW (names an existing inline literal) | The `3` at `notification_manager.py:7186` and `:7160` is unnamed. |
| Dead-channel detector half-built? | NO | grep `dead.channel|channel_dead|DEAD_ALERT` over `custom_components/` and `docs/planning/`: hits only in unrelated camera/lock/perimeter docs and the card itself. No anomaly type for channel death exists (`nm.no_route_tripwire` is the only NM trip-wire). |

### 1b. Prior plans, cards, memory
- `PLANNING_nm_overhaul_2026_07.md`, `PLANNING_nm_cycle_c_routing_matrix.md`, `PLANNING_nm_cycle_a2_knob_surface.md`: routing layers and knob surface; none adds delivery-health alerting.
- `AUDIT_nm_no_channel_fired_2026_11_13.md`: the sibling "alert reached nobody" trip-wire; same emit shape.
- Card NM-BB-CHATGUID-SELFSEND-1: a 10-18 transient (11 failures in 2 h, then recovered). This is the case the threshold must NOT fire on.
- Memory `project_nm_bb_wa_audit_2026_05_30.md`: no channel-health or degraded content (grep empty). `BACKLOG.md` does not exist at repo root.

### 1c. Code read end to end during scoping
`_update_channel_health`, `_send_whatsapp`, `_send_imessage`, `_route_for_recipient :5683`, `_channel_qualifies :6017`,
quiet-hours early return `:1720-1770`, per-recipient DND `:2063-2110`, `restore_repeat_home_budget`, `room_entities.py:95-160`,
`sensor.py:9400-9725`.

## 2. Config-first

No existing knob alerts on channel death. Live config (read 2026-11-27 via `ssh ha`, `core.config_entries`,
Coordinator Manager entry): severity floors pushover CRITICAL, imessage CRITICAL, whatsapp CRITICAL, companion HIGH;
operator `nm_person_delivery_pref = digest`, digest channels whatsapp + imessage; quiet hours 22:00-07:00 plus house state.

**Hard finding on the approved delivery answer.** "Every healthy channel through normal routing at a non-critical
severity" does not reach WhatsApp under this config:
- MEDIUM: operator is digest-pref, so it queues for the 08:00/18:00 digest, and the router allows no channel at MEDIUM
  (all floors HIGH or CRITICAL), the v5.36.1 "reached nobody" shape.
- HIGH: forced immediate (`:2076`), reaches the phone app only (companion floor HIGH). During quiet hours an
  immediate-pref HIGH without a DND bypass is dropped (`:2098-2102`), which is "respect quiet hours" as approved.
- WhatsApp/Pushover/iMessage need CRITICAL, which breaks through DND. Rejected.

Plan keeps the default (normal routing, HIGH, quiet hours respected) and adds an always-on persistent notification so
the message is never lost. The operator can widen delivery with a knob turn, no code: set the WhatsApp severity floor to
HIGH. See open question Q1.

## 3. Falsifiable invariant

**INV-1.** For each channel C in `NM_DIGEST_CHANNELS`: if C records at least `NM_CHANNEL_DEAD_MIN_FAILURES`
consecutive send failures and no success over a span of at least `NM_CHANNEL_DEAD_ALERT_H` hours, measured from C's
first failure after its last success **including across HA restarts**, then exactly one dead-channel episode is opened
for C: one persistent notification (`notification_id = ura_nm_channel_dead_<C>`) created immediately, and one HIGH NM
alert delivered through normal routing (retried on later failures until NM accepts it, then never again in that
episode). The episode closes, and the latch re-arms, only on C's next successful send.

**INV-2.** Idle is not dead: a channel with no send attempts never opens an episode, however long it stays idle.

**INV-3.** No storm: N restarts during one outage produce no more than one HIGH alert and one persistent notification
for that channel.

Break it with: restart between the first failure and hour N; success then failure inside the window; a channel whose
only sends are the alert itself; all four channels dead; quiet hours at the crossing moment.

## 4. Producer and consumer checks

**Producer.** `failing_since[C]` and `consecutive_failures[C]` are produced in one place, `_update_channel_health`,
which every message-channel send outcome already passes through (section 1a). Dependency health: the producer is honest
for imessage and whatsapp (exceptions and wa_bridge-not-ready both record False). Two blind spots, recorded not fixed:
pushover/companion calls are `blocking=True` and record success on service return, so a silent provider-side drop counts
as success; dry-run returns before recording (`:2900-2902`), so dry-run sends are neither success nor failure (correct).

**Fire check.** Over 11-22 to 11-27 the existing `degraded` producer DID fire (imessage degraded since the 11-25 boot),
but it reached no action: it only feeds two display sensors. Forward trace: degraded → `NMChannelStatusSensor` state →
nothing. That is the gap. Send rates measured on the card: imessage 22-150 attempts/day (11-18..11-26); 11-25 successes
pushover 42, companion 80, whatsapp 46.

**Consumers of the new state.** (1) The new evaluator (trust decision: open episode). (2) `channel_status` attribute
gains `failing_since` (display). No other reader.

**New producer's zero-fire trip-wire.** The episode open writes an anomaly row via `fire_stuck_signal` (`kind =
nm_channel_dead`). A detector that is quiet while a channel is degraded for more than N hours is the regression; the
Live check in D3 tests exactly that.

## 5. Emission / decision sites

- Detection: one site, `_update_channel_health` (after the existing failure/success arithmetic). Grep confirmed no other
  writer to `_channel_health[ch]["failures"]` for the four channels.
- Emission: one new helper `_maybe_open_dead_channel_episode(C)`, scheduled as a tracked task from the sync producer
  (NM already schedules from sync code via `hass.async_create_task`, `:1802`). It calls `persistent_notification.create`
  then `fire_stuck_signal(..., severity="HIGH")`.
- Close: success branch of `_update_channel_health` clears state and schedules `persistent_notification.dismiss`.
- Not touched: `async_notify`, `_route_for_recipient`, `_channel_qualifies`, `_send_*` bodies, perimeter's legacy direct
  notify `perimeter_alert.py:4446` (outside NM, records no health; section 7).

**Re-entrancy.** The HIGH alert may route to the dead channel (when C is companion). That send fails and re-enters
`_update_channel_health(C, False)`. The episode latch (`alerted_at` set before any await) makes the re-entry a no-op.
No `exclude_channels` parameter is added to `async_notify`: excluding is unnecessary because a send to a dead channel
fails harmlessly, and adding a parameter to the main routing entry is risk with no benefit (marginal-benefit check).

## 6. Deliverables

### D1. Persisted per-channel failure clock
`_update_channel_health` keeps, for the four channels, `failing_since` (ISO, first failure after last success),
`consecutive_failures`, `alerted_at`. Persisted in a Store `f"{DOMAIN}.nm_channel_dead"` (pattern `room_entities.py:124-130`),
written only on transitions (first failure, episode open, success-after-failure), never per send. Loaded in NM
`async_setup` before the first send; on load, carries `failing_since`, `consecutive_failures`, `alerted_at` forward.
Store failure falls back to RAM (logged debug), as in `room_entities.py:142`.

Acceptance:
- **Verify:** 5 failures, simulated restart (new NM instance, same Store), 1 failure: `failing_since` equals the first pre-restart failure time and count is 6.
- **Verify:** a success clears all three fields and writes the Store once; 100 consecutive successes write it zero more times.
- **Test:** `test_dead_channel_clock_survives_restart`, `test_dead_channel_success_clears_and_rearms`, `test_dead_channel_store_writes_only_on_transition`.
- **Live:** `.storage/universal_room_automation.nm_channel_dead` absent or all channels empty after deploy (all four channels healthy); `channel_status` attributes show `failing_since: null` per channel.

### D2. Episode open: persistent notification + HIGH alert
When `consecutive_failures >= NM_CHANNEL_DEAD_MIN_FAILURES` and `now - failing_since >= NM_CHANNEL_DEAD_ALERT_H` and
`alerted_at is None`: create the persistent notification (always), then `fire_stuck_signal(kind="nm_channel_dead",
key=(C,), severity="HIGH", diagnosis="<C> has failed every send since <time> (<n> tries)...", remedy="...")`.
Set `alerted_at` and save only when `fire_stuck_signal` returns True. If it returns False (quiet hours, silence,
boot-settle, kill switch), leave `alerted_at` unset so the next failure retries; the persistent notification is
idempotent by `notification_id`, so retries do not duplicate it. Evaluation is event-driven on each failure; no timer.

Acceptance:
- **Verify (discriminating):** failures spanning N h minus 1 min: no alert, no persistent notification. One more failure at N h plus 1 min: exactly one of each. A plausible wrong build (counting failures without the persisted clock) passes the first half but fails the restart variant below.
- **Verify:** restart at hour N/2 mid-outage, failures continue: alert fires at hour N measured from the pre-restart first failure, not N h after the restart.
- **Verify:** 5 restarts after the alert, failures continuing: zero further alerts (INV-3).
- **Verify:** crossing during quiet hours: `async_notify` drops it (return False), persistent notification exists, `alerted_at` unset; first failure after 07:00 delivers the alert once.
- **Verify:** C = companion: the alert's own companion send fails and does not open a second episode or recurse.
- **Verify:** all four channels dead: four persistent notifications, and HIGH emits that deliver nowhere leave `alerted_at` unset (retried, never storms because each retry is gated by NM dedup `NM_DEDUP_HIGH` 300 s and only fires on a real send failure).
- **Verify (INV-2):** channel enabled, zero sends for 48 h: no episode.
- **Test:** `test_dead_channel_alert_at_threshold`, `test_dead_channel_alert_across_restart`, `test_dead_channel_no_storm_across_restarts`, `test_dead_channel_quiet_hours_retry`, `test_dead_channel_self_route_no_recursion`, `test_dead_channel_all_dead_persistent_only`, `test_idle_channel_never_dead`, `test_transient_2h_outage_no_alert` (fixture: the 10-18 shape, 11 failures in 2 h then success).
- **Live:** an anomaly row `type` from `fire_stuck_signal` for `nm_channel_dead` exists only if a channel was degraded for more than N h; the D3 drill proves the path.

### D3. Close + live drill
On the first success after an episode: dismiss `ura_nm_channel_dead_<C>`, clear state. No recovery message (non-goal).

Acceptance:
- **Verify:** success after an alerted episode dismisses the persistent notification and a new outage later opens a new episode (one alert per outage, re-armed).
- **Test:** `test_dead_channel_recovery_dismisses_and_rearms`.
- **Live:** after restart the validator reads `channel_status` and the Store and confirms all four channels show `failing_since: null` and no `ura_nm_channel_dead_*` persistent notification exists. The alert path itself is proven in-suite only (D2 tests drive the real `_update_channel_health` and the real `fire_stuck_signal` against a stubbed `async_notify`), because inducing a multi-hour channel failure on the live house is not acceptable. The README records this as in-suite-only with that reason.

## 7. Knobs

| Knob | Default | Rung | Why |
|---|---|---|---|
| `NM_CHANNEL_DEAD_ALERT_H` | **6** | Module constant (NM constants block, beside `NM_NO_ROUTE_TRIPWIRE_*` `:293`) | Lowest measured iMessage rate 22 sends/day ≈ 0.9/h, so 6 h holds about 5 attempts even on a quiet day; long enough to skip the 10-18 2 h transient; short enough that the 11-22 17:12 outage would have opened at 23:12 (persistent notification then, phone-app alert at the first failure after 07:00 on 11-23, about 1.5 days earlier than nothing at all). Operator would rarely tune it; a change should be reviewed. **0 = feature off** (no episode, no Store writes). |
| `NM_CHANNEL_DEAD_MIN_FAILURES` | **3** | Module constant | Names the existing degraded threshold; guards a channel that sent once 6 h ago and failed once now. Applies to the episode only; the inline `3` at `:7186/:7160` is left as is (non-goal). |
| Alert kill switch | existing | `fire_stuck_signal` kill switch `_stuck_signal_nm.py:70-87` | Reused; turning it off suppresses the HIGH alert but not the persistent notification. |

## 8. Non-goals
- No change to routing, severity floors, `async_notify` signature, or `_send_*` bodies.
- No recovery ("channel is back") message. Park: revisit if the operator asks.
- tts, lights, panels: not message channels, out of scope. Perimeter's legacy direct notify (`perimeter_alert.py:4446`) records no health; out of scope.
- No fix for `notification_log delivered=1` semantics on multi-channel rows.
- Not detecting silent provider-side drops on pushover/companion (no failure signal exists).
- Not renaming the inline `3` in `_update_channel_health` / `_set_panel_health`.

## 9. Tier classification
**Tier 2.** Touches `_update_channel_health`, which every NM transport send passes through (regression-prone NM send
path), adds a persisted Store and an async emit from sync code. Not Tier 2-DB: no DB schema, DAO or payload change
(the anomaly row uses the existing `fire_stuck_signal` writer). Not Tier 3: no cost/safety value threaded through many
sites; detection and emission are single sites. One adversarial plan review before build; review framings A
(correctness + restart/latch arithmetic + edge cases) and B (async/re-entrancy, task tracking, Store lifecycle, quiet
hours/boot-settle interaction). Ship at an attended deploy, not while the house sleeps.

## 10. Open questions for the operator
- **Q1.** Under your live gates a HIGH alert reaches only the phone app (WhatsApp, Pushover and iMessage are gated at
  CRITICAL), and at night it waits until the first failed send after quiet hours end. The persistent notification in HA
  appears immediately. If you want WhatsApp too, lower the WhatsApp severity floor to HIGH (a setting, no code; it also
  lets other HIGH alerts reach WhatsApp). Keep as is, or lower the floor?
- **Q2.** If the phone app itself is the dead channel, only the HA persistent notification fires (nothing else is gated
  at HIGH). Acceptable?
