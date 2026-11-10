# v5.107.5 — Door alert "that was <name>" follow-up

Tier 1 (operator-approved 2026-11-08). Revives the v5.107.0 D10.5 parked ask. NM cannot edit a sent
notification, and the operator ruled that a separate follow-up message is fine.

## What it does

A door camera that is also a perimeter camera ("dual-role") may page for an unknown person. If the house
identifies that person within 90 s, it now sends one short follow-up:

> **Perimeter Alert — Identified**: Front door: that was Jaya

The camera name is the camera entity's friendly name, falling back to the camera key in title case.
The person name is the `person.<slug>` friendly name, falling back to the slug in title case.

### When it arms
All of these must hold for the alert that just dispatched successfully:
- its D10.5 decision (same edge timestamp) has reason `egress_unknown_corroborated` or `xcorr_waived_single_nvr`
  and `demoted = False`;
- the dispatched severity is above LOW and still equals D10.5's output, so a later VLM demote counts as demoted;
- the alert text carried no `Identified: <name>` annotation;
- `switch.ura_perimeter_identity_followup` is ON and the window is above 0.

A demoted or LOW alert never arms, because nothing reached the operator. Alerts with the D10.5 gate off, or
shielded by the classification-transition exemption, don't arm either: no unknown verdict was made.

### What counts as "known"
The same `_known_identity_for` rule D10.5 uses: an egress-bus identity or a scored face leg at ≥ 0.9, or an
unscored Frigate face plus a real arrival of the same person (person tracker or Bermuda). This complies with
manual §5.5(a), since the follow-up only annotates. It never changes the original alert's severity.

**Which sources can actually fire it (review fix, item 7).** The original plan assumed Protect back-fills face
names onto the door cameras in 40-80 s. On develop (v5.107.1, `camera_census.py:3343`) the Protect face entity
legs are a parked bridge with no live source. So today only two sources can fire the follow-up:
- the egress identity bus event (`ura_person_egress_event` with `identity_confidence` ≥ 0.9). Its detection
  timestamp must be within ±15 s of the edge (`PERIMETER_EGRESS_IDENTITY_MATCH_S`), so it usually lands
  near the alert rather than late;
- a Frigate face match on the door camera plus a real arrival of the same person: a live `person.*`
  not_home → home edge, or a Bermuda move into the door's area, within 120 s.

If a scored Protect face leg goes live again, it qualifies automatically at ≥ 0.9.

**Different-person limitation (review item 5).** During the window, any known identity that lands on the same
camera key is attributed to this alert. That includes a second known person who crosses at, say, t+80 s. A
name latched more than 15 s before the edge is rejected, and one within ±15 s would already have demoted the
alert at D10.5, so this only affects a genuinely new identity during the window. The follow-up text says
"that was <name>". In this case it is wrong about who the unknown person was, but still correct that a
known person is at the door. This is accepted for an annotation-only message. Correlating each identity to
its crossing would need person-in-frame data that URA does not have.

### Bounded listener and discharge
- A chained `async_call_later` re-checks identity every `PERIMETER_IDENTITY_FOLLOWUP_POLL_S` (5 s) up to
  `PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S` (90 s). Elapsed time is the sum of the scheduled delays.
- At most one follow-up per alert. The pending entry is popped before the send, and a stale tick whose state is
  no longer pending does nothing.
- Discharge happens on window expiry, on `async_teardown`, and on any later successfully dispatched alert on the
  same camera key, whether or not that alert arms its own follow-up.
- Restart: pending follow-ups are in-memory only and lost on restart. A restart within 90 s of a page drops the
  follow-up, which is acceptable for an annotation.
- Restart recovery (review HIGH fix): a quiet follow-up's `notification_log` rows keep their TRUE severity
  (e.g. CRITICAL), which keeps the audit trail honest, but they are written already acknowledged
  (`acknowledged=1`). This is the same idiom as the `[ACK]` audit row. As a result, `get_active_critical` /
  `get_active_criticals` never return one, and NM restart recovery can't resume siren paging for "that was
  Jaya". I chose this over logging below CRITICAL because a lower-severity row would misstate what the
  operator received.

### Delivery — `async_notify(..., quiet=True)` (new keyword, default False = byte-identical)
The follow-up goes at the original severity, so it clears the same per-channel severity floors and reaches the
same recipients and channels. Each channel uses its quiet form:

| Channel | Original (CRITICAL / HIGH) | Follow-up (`quiet=True`) |
|---|---|---|
| Pushover | `priority 1` + `sound: siren` / `priority 1` | `priority` = `NM_QUIET_PUSHOVER_PRIORITY` (0, normal, no siren) |
| Companion | critical sound + safe-word actions (CRITICAL) | standard push, no critical sound, **no action buttons** (the one-tap "Acknowledge" would bulk-ack every open CRITICAL without the safe word) |
| WhatsApp / iMessage | message + response menu | plain message, no response menu |
| Wall panel, TTS, alert lights | fire per gates | skipped (`not quiet` is checked before the TTS/lights rate-limit checks, so no slot is consumed) |
| CRITICAL ack/re-page engine | started | not started |

Thread or tag: NM has no thread, tag or reply primitive on any channel (no `tag` in `_send_companion`, no
Pushover receipt handling), so none is used. The follow-up is linked to the original by the camera name in the
text and the same `location` (sensor entity).

Things that still apply to the follow-up: the perimeter safeword silence window (hazard `exterior_person`),
quiet hours/DND exactly as for the original severity, and NM dedup. The dedup key differs from the original's
because the title differs.

## Knobs
| Knob | Rung | Default | Why |
|---|---|---|---|
| `switch.ura_perimeter_identity_followup` (`CONF_PERIMETER_IDENTITY_FOLLOWUP`) | 3 (options-backed switch, reload-suppressed, fresh-read per alert) | ON | operator kill switch |
| `PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S` | 1 | 90 | operator-chosen bound; covers the 120 s face+arrival rule's typical lag, and a revived Protect back-fill (40-80 s); 0 disables |
| `PERIMETER_IDENTITY_FOLLOWUP_POLL_S` | 1 | 5 | re-check cadence |
| `NM_QUIET_PUSHOVER_PRIORITY` (notification_manager.py) | 1 | 0 | Pushover normal priority; -1 would be fully quiet |

## Files
- `perimeter_alert.py`: `_arm_identity_followup`, `_schedule_followup_tick`, `_followup_check`,
  `_async_send_identity_followup`, `_cancel_identity_followup`. Wired from `_do_dispatch` after a successful
  dispatch. Teardown discharge added. The annotation flag is captured as `_annotated_identity`.
- `domain_coordinators/notification_manager.py`: `async_notify(quiet=)`, `_send_pushover(quiet=)`.
- `const.py`, `switch.py`, `strings.json`, `translations/en.json`, and the `__init__.py` reload-suppress allowlist.
- Docs: `IDENTITY_FUSION_CAMERAS_MANUAL.md` §4.5 bullet, and the parked item in `README_v5.107.0.md` marked revived.

## Tests
`quality/tests/test_perimeter_identity_followup.py` (26 tests) drives the real trigger handler, the scheduled
ticks, teardown and the real NM. Two reload-allowlist mirror tests gained the new key. In targeted sibling runs
(perimeter, exterior, NM and reload files), 826 tests passed. The new file also passes when it runs before
`test_exterior_cycle2` (shared `_scheduled` is drained).

Mutation drills: 23 sites, all RED on neuter. They cover the wire-in call in `_do_dispatch`; each arm conjunct
(switch, window 0, LOW, annotated, decision `at` / `demoted` / `reason` / `severity_after`); the supersede
cancel; the stale-tick guard; pop-before-send; window expiry; the teardown discharge; `quiet=True` passed;
NM's Pushover quiet branch and its threading; companion non-critical; and the TTS, panel, re-page and
response-menu skips.

Review fix-up: 5 more tests (31 total). They cover a real-DB restart-recovery test with a quiet=False
control, the Companion no-actions check, `quiet` threaded through to Companion, and TTS/lights slots not
consumed. 9 more drills, all RED: `_row_ack`, each of the four per-channel `acknowledged=_row_ack` rows, the
Companion quiet branch, `quiet` threading to Companion, and the TTS and lights short-circuits. The audit-row
`acknowledged=_row_ack` is a belt with no drill of its own: `[audit]` rows are already excluded by
`get_active_critical`.

## Live validation

### Validated 2026-11-10

Read 2026-11-10 ~02:10-02:20 CST, HA running v5.108.1 (manifest), restart 01:04 CST. Read-only. This release (v5.107.1 through v5.107.6) first ran at that restart. Logging caveat: the integration logger is `log_level: WARNING`, so every INFO marker in these criteria is never written to the HA log, and `ha_get_logs` cannot show it. Log absence is therefore NOT evidence for or against these criteria.

| Criterion | Result | Evidence |
|---|---|---|
| Identified follow-up after an unknown door page | NOT-YET-OBSERVABLE | `notification_log` has 0 rows with `Identified` in the title, all time. No dual-role door unknown page since restart. Per the README, a zero count after a week is a coverage finding, not a pass. |
| No follow-up after a LOW or demoted alert | NOT-YET-OBSERVABLE (vacuous) | Zero follow-ups exist, so the negative cannot be tested. Not a PASS. |
| Every `Perimeter Alert — Identified` row has `acknowledged = 1` | NOT-YET-OBSERVABLE (vacuous) | Zero rows exist. |

**Verdict 2026-11-10:** 0 PASS, 0 FAIL, 3 NYO. The feature is deployed but has no evidence yet.

## Not done
- No per-channel thread or edit: NM has no such primitive. Revival trigger: NM gains a companion `tag` or a
  Pushover receipt-replace path.
- No event-driven re-check on the egress bus. A 5 s poll is enough for a 90 s window, and adding a second call
  site isn't worth it.
- Measure-before-build (manual §5.5(c)): the value depends on the egress identity event or a Frigate face plus
  an arrival at the door cameras, both sparse. Protect face legs are parked on develop. The operator approved it as low-cost. The live rate shows up in `notification_log`.
