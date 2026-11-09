# v5.107.5 — Door alert "that was <name>" follow-up

Tier 1 (operator-approved 2026-11-08). Revives the v5.107.0 D10.5 parked ask. NM cannot edit a sent
notification, and the operator ruled that a separate follow-up message is fine.

## What it does

A door camera that is also a perimeter camera ("dual-role") may page for an unknown person. Protect
back-fills the face name 40-80 s later. When that happens, the house now sends one short follow-up:

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

### Bounded listener and discharge
- A chained `async_call_later` re-checks identity every `PERIMETER_IDENTITY_FOLLOWUP_POLL_S` (5 s) up to
  `PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S` (90 s). Elapsed time is the sum of the scheduled delays.
- At most one follow-up per alert. The pending entry is popped before the send, and a stale tick whose state is
  no longer pending does nothing.
- Discharge happens on window expiry, on `async_teardown`, and on any later successfully dispatched alert on the
  same camera key, whether or not that alert arms its own follow-up.
- Restart: pending follow-ups are in-memory only and lost on restart. A restart within 90 s of a page drops the
  follow-up, which is acceptable for an annotation.

### Delivery — `async_notify(..., quiet=True)` (new keyword, default False = byte-identical)
The follow-up goes at the original severity, so it clears the same per-channel severity floors and reaches the
same recipients and channels. Each channel uses its quiet form:

| Channel | Original (CRITICAL / HIGH) | Follow-up (`quiet=True`) |
|---|---|---|
| Pushover | `priority 1` + `sound: siren` / `priority 1` | `priority` = `NM_QUIET_PUSHOVER_PRIORITY` (0, normal, no siren) |
| Companion | critical sound + safe-word actions (CRITICAL) | standard push, no critical sound |
| WhatsApp / iMessage | message + response menu | plain message, no response menu |
| Wall panel, TTS, alert lights | fire per gates | skipped |
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
| `PERIMETER_IDENTITY_FOLLOWUP_WINDOW_S` | 1 | 90 | covers the Protect 40-80 s name back-fill; 0 disables |
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

## Acceptance (live)
- **Live:** after an unknown-person page from a dual-role door camera, when Protect names a resident within 90 s,
  one `Perimeter Alert — Identified` message arrives on the same channels, and Pushover shows no siren.
  Evidence: `notification_log` rows with title `Perimeter Alert — Identified`, and the `identity_followup`
  entry in `sensor` gate-decision diagnostics (`gate_decisions_by_camera.<key>.identity_followup`).
- **Live:** no follow-up row ever follows a LOW/demoted perimeter alert. Check by joining `notification_log` on
  title and location.

## Not done
- No per-channel thread or edit: NM has no such primitive. Revival trigger: NM gains a companion `tag` or a
  Pushover receipt-replace path.
- No event-driven re-check on the egress bus. A 5 s poll is enough for a 90 s window, and adding a second call
  site isn't worth it.
- Measure-before-build (manual §5.5(c)): the value depends on Protect naming people at the door cameras, which
  is sparse. The operator approved it as low-cost. The live rate shows up in `notification_log`.
