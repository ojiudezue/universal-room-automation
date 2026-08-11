# PLANNING — NM-IMAGE-1: NM Image Attachment Delivery

**Date opened:** 2026-08-11
**Author:** ura-planner
**Cycle ID:** NM-IMAGE-1
**Tier classification:** **Tier 2** (routing behavior change on a shared primitive;
one adversarial plan review before build per PLAN-TIER protocol; two adversarial
code reviews before deploy + live validation).
**Branch:** `plan/nm-image-1`

---

## 0. Background — verified today, do NOT re-litigate

Empirically established live on 2026-08-11:

1. **Capture works.** Fresh JPEGs land in `/media/ura/snapshots` at edge time.
2. **Transports work for images.** A live `notify.send_message` WhatsApp send
   with `media_path` DID deliver the attached image to the operator; iMessage
   / Pushover attachment paths were previously validated in NM Cycle C.
3. **Perimeter dispatch is correct.** `perimeter_alert.py:1258-1267` threads
   `snapshot_path` and `snapshot_url` into `nm.async_notify` on every person /
   vehicle emit.
4. **`nm.async_notify` accepts the args.** `notification_manager.py:1182-1192`
   declares both kwargs and passes them through to `_send_pushover`,
   `_send_companion`, `_send_whatsapp`, `_send_imessage` on the
   IMMEDIATE branch (`notification_manager.py:1570 / 1595 / 1619 / 1641`).

**The drop:** The operator's `nm_persons` recipient has `delivery_pref=digest`.
At `notification_manager.py:1495` the "always immediate" override fires only for
CRITICAL and HIGH. When the exterior-person severity resolves to MEDIUM or LOW
(e.g. `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY="MEDIUM"` at `const.py:1410`,
or the pass-by DEMOTE path from the Tier-3 severity-map coercion at
`perimeter_alert.py:1040-1049`), the recipient's pref stays `digest`. The
notification is queued via `database.log_notification` — and the digest queue
**does not persist `snapshot_path` / `snapshot_url` at all** (see
`database.log_notification` signature — no snapshot columns). At flush time
`_deliver_digest` (`notification_manager.py:4168-4241`) calls
`_send_whatsapp` / `_send_imessage` / `_send_pushover` / `_send_companion` with
**no snapshot kwargs**. The image is lost the instant the recipient is
digest-preferred and the severity is not HIGH/CRITICAL.

**Adjacent observations (in scope, see §6):**
- A bare `Perimeter Alert — [audit]` message reached the operator at 10:01 on
  2026-08-11. `"[audit]"` is the message sentinel written to `notification_log`
  by `_emit_audit_row` (`notification_manager.py:4004`) — a routing-audit row,
  never intended as a body. Some path is rendering audit rows out. Investigate
  and fix (P24-style context-preservation, see §6-D3).
- A 04:24 exterior-person event was delivered at 09:26 (~5h latency). This is
  the *same drop* as the primary bug: MEDIUM severity + digest pref → held
  until morning flush → also stripped of image. Design B closes this by making
  image-bearing security-class alerts force-immediate, independent of
  digest pref.

**iMessage attachments are separately structural** (BlueBubbles integration
drops them on `send_message`). Out of scope for NM-IMAGE-1, tracked as
`SNAP-1-followup`. See §5.

---

## 1. Falsifiable Invariant

**INV-1 (primary):** *An exterior security-class alert (`hazard_type` in
`{NM_HAZARD_EXTERIOR_PERSON, NM_HAZARD_EXTERIOR_VEHICLE}`) with a captured
snapshot (`snapshot_path` is not None OR `snapshot_url` is not None) is
delivered on every media-capable channel routed to a recipient with an
attachment, and is delivered on the immediate path — never later than the
IMMEDIATE branch would allow, and never as an image-less body.*

**INV-2 (audit hygiene):** *No `notification_log` row whose `message` field
equals the `"[audit]"` sentinel is ever rendered into a transport body
delivered to a recipient.*

Both invariants are falsifiable by direct DB query + transport log inspection.
Reviewer D (adversarial completeness pass, if elevated) breaks them by
enumerating every reachable path from `async_notify(hazard=exterior_person,
snapshot_path=<real>)` and every consumer of `notification_log.message`.

**Media-capable channel** = channel whose send path accepts and forwards
`snapshot_path` / `snapshot_url` to a transport that renders attachments:
Pushover, Companion (`data.image`), WhatsApp (`media_path`). NOT media-capable
today: TTS, lights, iMessage/BlueBubbles (structural, see SNAP-1-followup).

---

## 2. Institutional context verified

### Files read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` — targeted spans:
  1180-1220 (async_notify signature), 1460-1650 (channel routing + CRITICAL/HIGH
  override at 1495), 3960-4018 (`_emit_audit_row`), 4053-4316 (digest timers,
  `_fire_digest`, `_deliver_digest`, `_format_digest`).
- `custom_components/universal_room_automation/perimeter_alert.py` — 1160-1290
  (person emit + dispatch), 2220-2300 (vehicle emit), 1030-1080
  (severity resolver + DEMOTE map).
- `custom_components/universal_room_automation/database.py` — 3791 (`log_notification`
  signature — NO snapshot columns), 3820-3905 (`get_pending_digest`,
  `mark_digest_delivered`), 1737-1764 (notification_log audit columns).
- `custom_components/universal_room_automation/const.py` — 1391-1550 (hazard type
  constants + severity maps), 1644-1680 (SNAP-1 kill-switch comments).

### Grep survey for reuse
| Proposed knob / component | Result | Evidence |
|---|---|---|
| Image-bearing force-immediate override | **NEW (surgical)** | Extends the existing CRITICAL/HIGH branch at `notification_manager.py:1495`; no equivalent guard exists in Cycle A/B/C constants. |
| Snapshot kwargs on `_deliver_digest` path | **NOT PROPOSED** (design alt A parked) | Would require adding `snapshot_path`/`snapshot_url` columns to `notification_log` + threading through `_send_*` at flush. Rejected §4. |
| `NM_HAZARD_EXTERIOR_PERSON` / `NM_HAZARD_EXTERIOR_VEHICLE` constants | **REUSED** | `const.py:1394 / 1406`. |
| `NM_SECURITY_HAZARDS` set (media-force-immediate whitelist) | **NEW** — module constant in `const.py` | Rung-1 (behavioral bound; enable/disable through code review, not operator UX). Kill-switch = empty set (feature off, byte-identical to today). |
| `"[audit]"` message sentinel | **REUSED** | `notification_manager.py:4004`, `coordinator.py:218`, `_stuck_signal_nm.py:200-202`. |
| `get_pending_digest` filter (excluding `message="[audit]"`) | **EXTEND** existing method | `database.py:3876`; single-line WHERE clause addition. |
| Perimeter Alert titles (exact strings for §6-D3 grep) | **REUSED** | `perimeter_alert.py:1201 ("Person Detected"), 2235 ("Vehicle deep-night"), 3136-3139 (fallback branch)`. |
| Digest `_format_digest` row renderer | **REUSED** — hardening | `notification_manager.py:4290-4316` — must NEVER emit "[audit]" body content (defensive skip in `get_pending_digest` PLUS defensive skip in `_format_digest`). |

### Prior planning docs consulted
- `docs/planning/PLANNING_nm_overhaul_2026_07.md` — full read, especially §Institutional
  context and Cycle C routing matrix definitions.
- `docs/planning/PLANNING_nm_cycle_c_routing_matrix.md` — skimmed for router
  branch labels (`matrix_branch`) used in audit rows.
- `docs/planning/PLANNING_nm_cycle_c2_routing_ui.md` — skimmed (dry-run UX, no
  overlap with image delivery).
- `docs/planning/AUDIT_nm_rename_impact.md` — skimmed (rename impact, no
  overlap).

### Memory bodies pulled
- Memory "NM BlueBubbles + WhatsApp Audit 2026-05-30" — confirms iMessage
  attachment path is structural (BlueBubbles), tracked separately.
- Memory "resume 2026-08-05" — v5.51.1 shipped; NM Cycle A/B/C live; recipients
  filled per Cycle C plan.
- No prior NM-IMAGE cycle. This is the first.

### Design doc read
- `docs/Coordinator/NOTIFICATION_MANAGER.md` — pre-implementation doc, does not
  cover attachment routing. This cycle predates the doc's next revision.

### QUALITY_CONTEXT bug classes considered
- **#53 (computed-but-not-consumed):** `snapshot_path` is computed at the
  perimeter edge and threaded into `async_notify`, but the digest queue does
  not persist it — a textbook consume-drop. INV-1 exists to prevent it.
- **#22 (enum mismatch):** guard string severity ('MEDIUM'/'LOW' as text) vs
  `Severity` enum values in the new predicate. Use `hazard_type in
  NM_SECURITY_HAZARDS AND (snapshot_path or snapshot_url)`, NOT severity
  string comparison.
- **#7 (stale data source):** none — routing decisions read live config.
- Digest force-immediate must survive HA restart mid-cycle (RestoreEntity /
  boot-transient): the fix lives inside `async_notify`, not in restored state.

---

## 3. NM delivery-leg enumeration (S-style, for INV-1 completeness)

Every reachable delivery leg for an image-bearing exterior alert, today vs. post-fix:

| # | Leg | Trigger | Today (image?) | Post-fix (image?) |
|---|---|---|---|---|
| L1 | IMMEDIATE, severity CRITICAL/HIGH, non-DND | line 1495 override | YES (all media-capable channels) | UNCHANGED |
| L2 | IMMEDIATE-pref, severity MEDIUM/LOW, non-DND | pref=IMMEDIATE | YES (media kwargs threaded) | UNCHANGED |
| L3 | DIGEST-pref, severity CRITICAL/HIGH | line 1495 override forces immediate | YES | UNCHANGED |
| **L4** | **DIGEST-pref, severity MEDIUM/LOW, `hazard∈SECURITY` + snapshot present** | today: line 1495 does NOT fire → queued row (no snapshot cols) | **NO — image lost** | **YES — force-immediate; delivered on media-capable channels** |
| L5 | DIGEST-pref, severity MEDIUM/LOW, `hazard∈SECURITY`, NO snapshot | line 1495 does NOT fire | body-only in next digest | UNCHANGED (parked A never justified — no image to lose) |
| L6 | DIGEST-pref, severity MEDIUM/LOW, `hazard∉SECURITY` (e.g. env sensor) | line 1495 does NOT fire | body-only in next digest | UNCHANGED |
| L7 | DIGEST flush | `_fire_digest` → `_deliver_digest` | body-only, ever | UNCHANGED — no snapshot cols. Defensive: filter `message="[audit]"` rows out at `get_pending_digest`. |
| L8 | Quiet-hours / global DND + IMMEDIATE-pref | line 1515-1536: audit row only, no send | audit row (no send) | UNCHANGED for non-security; **security-class + snapshot = still routes to IMMEDIATE and honors existing DND-bypass matrix (`_recipient_bypasses_dnd`)**. Design point: **image-bearing security alerts do NOT auto-bypass DND**; they take the recipient's existing `dnd_bypass` decision. Rationale: DND is an operator-configured contract; a MEDIUM person-at-door at 03:00 is exactly what the recipient's DND-bypass matrix is for — do not create a hidden second override. |
| L9 | Quiet-hours + DIGEST-pref | today: queued, delivered at flush | image lost | **FIX:** the new force-immediate at L4 fires BEFORE the DND branch, but respects `_recipient_bypasses_dnd`. If DND blocks the recipient, audit row `route_reason=dnd_suppressed_security_image` (new value), image is NOT deferred to digest (would be stale). |
| L10 | `CONF_NM_DRY_RUN` active | `_dry_run_active=True` path | audit row only | UNCHANGED — dry-run stays honest. |
| L11 | Weekly regime digest | `_send_regime_weekly_digest` | body-only | UNCHANGED — regime events are not security-class. |
| L12 | Global kill switch `_messaging_suppressed` | `async_notify` early-return line 1211 | nothing sent | UNCHANGED — kill switch remains authoritative. |
| L13 | `enabled=False` (NM disabled) | early-return line 1206 | nothing sent | UNCHANGED. |
| L14 | Legacy `notify_service` fallback | perimeter_alert.py 1188 | legacy path (uses `snapshot_url` in kwargs downstream) | UNCHANGED — outside NM. |

**Post-fix invariant on L4 + L9:** an image-bearing security alert never enters
the digest queue. It either lands as IMMEDIATE (on every routed media-capable
channel per the Cycle-C router) or is suppressed by an existing pre-existing
gate (kill switch / disabled NM / recipient DND without bypass) — with an
audit row explaining which.

---

## 4. Design decision — B (image-bearing security-class force-immediate)

### 4.1 What the fix is

Extend the existing "always immediate" gate at `notification_manager.py:1495`
so it also fires when:

```
hazard_type in NM_SECURITY_HAZARDS
AND (snapshot_path is not None OR snapshot_url is not None)
```

where `NM_SECURITY_HAZARDS = {NM_HAZARD_EXTERIOR_PERSON,
NM_HAZARD_EXTERIOR_VEHICLE}` (new module constant, rung 1).

Behavior: the per-recipient `effective_pref` becomes `NM_DELIVERY_IMMEDIATE`
for these emissions regardless of the recipient's `delivery_pref=digest`. The
rest of the pipeline (matrix router, mute, token bucket, DND bypass,
_send_* attachment threading) is unchanged. Because `_send_pushover`,
`_send_companion`, `_send_whatsapp` already carry `snapshot_path`/`snapshot_url`
on the IMMEDIATE branch, the image ships with the alert on every routed
media-capable channel.

Audit row on this path gets a new `route_reason` value
`"force_immediate_security_image"` so the audit ledger records the override.

### 4.2 Why not design A (persist snapshot into digest rows)

- **Value dies with staleness.** Person on the perimeter at 04:24, digest at
  09:00: the image is 4-5 hours old when it arrives. A stale security image is
  noise (was that person still there? did the family enter/leave in the
  interim?). Design B eliminates the latency entirely for the class where
  staleness matters most.
- **Schema touch cost.** Adding `snapshot_path` / `snapshot_url` columns to
  `notification_log` is a DB migration + `log_notification` signature bump +
  RestoreEntity impact + write-volume audit. All spent to deliver a stale
  image to inbox #3.
- **Ingredient risk (marginal-benefit decomposition):** the simple version (B)
  captures the entire operator-visible benefit; A adds schema churn AND
  latency without adding value. Parked, not deleted: reconsider if a
  household emerges where non-security image-bearing MEDIUM alerts (e.g.
  humidity fan graph attachments) would benefit from digest inclusion — that
  is not this cycle.

### 4.3 Hybrid (B for security, A never) — accepted

The plan is exactly B: security-class + image → force-immediate. Non-security
image-bearing alerts are theoretical today (no non-security emitter passes
`snapshot_path`) — if one appears, the security whitelist is the extension
point, not schema.

### 4.4 The knob and its rung

`NM_SECURITY_HAZARDS: Final[frozenset[str]] = frozenset({
    NM_HAZARD_EXTERIOR_PERSON, NM_HAZARD_EXTERIOR_VEHICLE
})`

- **Rung 1 (module constant in `const.py`).** Rationale: this is a bounded
  safety-class whitelist. Expanding it changes routing precedence globally and
  should require a code review, not operator UX. Kill-switch semantics:
  setting the set to `frozenset()` disables the override → byte-identical to
  pre-cycle behavior. Documented on the constant.
- **NOT rung 2 (options flow).** Not per-deployment structure.
- **NOT rung 3 (Number/Select entity).** Not observationally tuned.

Every other value in this cycle already has a knob (severity map at
`const.py:1415`, hazard type constants at 1394/1406, dedup windows at
1314-1317). No new numbers introduced.

### 4.5 What remains lagged after B ships (state honestly)

- **L5, L6, L11 (non-security or no-snapshot MEDIUM/LOW):** still digest-lagged.
  Correct — that is what digest is for.
- **iMessage attachments:** structurally dropped by BlueBubbles integration
  regardless of B (SNAP-1-followup). Operator receives the alert as
  text-only on iMessage; WhatsApp / Pushover / Companion get the image.
- **DND'd security image (L9, recipient without bypass):** honestly not
  delivered — no back-door override. Audit row records
  `dnd_suppressed_security_image`.

---

## 5. Non-goals (explicit)

- **BlueBubbles iMessage attachment upload.** Structural upstream issue.
  Tracked as `SNAP-1-followup`.
- **CONSOL-1 llmvision consolidation.** Independent cycle.
- **Digest-row schema expansion (Design A).** Parked in §4.2.
- **Changing severity resolution / DEMOTE map** (`const.py:1415-1550`,
  `perimeter_alert.py:1040-1049`). Out of scope — this cycle routes around
  the resulting `MEDIUM` correctly; it does not re-litigate why guest state
  is MEDIUM.
- **Non-exterior hazard types.** `NM_SECURITY_HAZARDS` is intentionally
  restricted to the two exterior perimeter classes. Adding e.g.
  `interior_glass_break` is a future cycle.
- **Any change to Cycle-C router matrix behavior** (mute, DND-bypass,
  matrix branch labels) — the fix hooks BEFORE the router without altering
  it.

---

## 6. Deliverables

### D1: `NM_SECURITY_HAZARDS` constant + `SNAPSHOT_FORCE_IMMEDIATE` predicate

Add `NM_SECURITY_HAZARDS: Final[frozenset[str]] = frozenset({...})` to
`const.py` alongside the existing NM hazard constants (~line 1408). Docstring
must state:
- Purpose (attachment-preserving force-immediate whitelist).
- Kill-switch (`frozenset()` → feature off, byte-identical).
- How to extend (add a hazard string; requires code review because it changes
  global routing precedence).

**Acceptance Criteria**
- **Verify:** `NM_SECURITY_HAZARDS == frozenset({"exterior_person", "exterior_vehicle"})`
  post-import.
- **Test:** `test_nm_security_hazards_constant_shape` asserts type is
  `frozenset[str]`, contents match, and empty override in monkeypatch
  cleanly disables the fix (test does NOT edit `const.py` — uses
  `monkeypatch.setattr` on the notification_manager reference).
- **Live:** module import in HA log shows no error; `hass.data[DOMAIN]`
  boot completes.

### D2: `async_notify` force-immediate extension

Modify the block at `notification_manager.py:1490-1498` (inside the
`for person_cfg in persons` loop). Current:

```python
if severity in (Severity.CRITICAL, Severity.HIGH):
    effective_pref = NM_DELIVERY_IMMEDIATE
else:
    effective_pref = delivery_pref
```

Post-fix:

```python
_security_image = (
    hazard_type in NM_SECURITY_HAZARDS
    and (snapshot_path is not None or snapshot_url is not None)
)
if severity in (Severity.CRITICAL, Severity.HIGH) or _security_image:
    effective_pref = NM_DELIVERY_IMMEDIATE
else:
    effective_pref = delivery_pref
```

The predicate MUST be computed ONCE outside the loop (per notification, not
per person) and passed in — avoids per-recipient recomputation and guarantees
uniform decision across all recipients for the same emit.

When `_security_image and severity not in (CRITICAL, HIGH)` and the recipient
would have been digest, the audit row must set
`route_reason="force_immediate_security_image"`. DND branch's audit uses
`route_reason="dnd_suppressed_security_image"` for the same recipient class,
so post-mortem queries can distinguish "delivered because of override" from
"held because of DND on override".

**Acceptance Criteria**
- **Verify:** an `async_notify(hazard=exterior_person, severity=MEDIUM,
  snapshot_path="/media/ura/snapshots/foo.jpg", ...)` call with a digest-pref
  recipient invokes `_send_pushover` / `_send_whatsapp` / `_send_companion`
  on the IMMEDIATE branch and passes `snapshot_path` through.
- **Verify:** the same call with `snapshot_path=None AND snapshot_url=None`
  falls through to the recipient's `delivery_pref` (digest queue), unchanged
  from today.
- **Verify:** the same call with `hazard=indoor_humidity` and a snapshot
  (theoretical) DOES NOT force immediate — the whitelist gates.
- **Test:** `test_security_image_forces_immediate_over_digest`,
  `test_no_snapshot_no_forced_immediate`, `test_non_security_snapshot_no_force`,
  `test_force_immediate_respects_recipient_dnd_bypass`,
  `test_force_immediate_respects_global_kill_switch`.
- **Test (audit-row):** `test_audit_row_route_reason_force_immediate_security_image`
  asserts the new `route_reason` string appears in the DB row for the override
  branch AND in the `_routing_audit_log` ring feeding the D4 diagnostics
  attribute.
- **Live:** trigger a live exterior-person event during guest state (MEDIUM),
  observe operator's WhatsApp / Pushover / Companion receive the alert with
  attachment within `<10s` of edge capture; observe `notification_log` row
  with `delivered=1`, `channel in (pushover,companion,whatsapp)`, `person_id`
  populated, `route_reason='force_immediate_security_image'`.
- **Live:** `sensor.ura_notification_manager_notification_diagnostics`
  attribute `nm_routing_audit_recent` contains an entry with
  `route_reason='force_immediate_security_image'`.

### D3: Bare-title `[audit]` delivery investigation and fix

At 10:01 on 2026-08-11 the operator received a message with title
`"Perimeter Alert — [audit]"` (or similar). `"[audit]"` is the message
sentinel from `_emit_audit_row` (`notification_manager.py:4004`). No
production code path should surface this sentinel as a delivered body.

Investigation the builder MUST perform (do NOT skip — the mechanism is
hypothesized, not confirmed):

1. `git grep -n '"\\[audit\\]"'` — enumerate all producers.
2. Trace how a `notification_log` row with `message="[audit]"` can be
   read back and forwarded to a transport. Candidate paths, verify each:
   - `_format_digest` iterating rows from `get_pending_digest` — currently
     no filter on `message`; if a MEDIUM audit row for a perimeter emit ever
     lands (e.g. `dnd_suppressed` for a MEDIUM alert), it will appear in
     the next digest body.
   - `_recover_state_from_db` populating `self._last_notification`
     (`notification_manager.py:4322-4343`) from `get_last_notification`,
     any downstream consumer surfacing `last.message` verbatim.
   - The stuck-signal NM emit (`_stuck_signal_nm.py:200-202`) referencing
     the sentinel.
3. **Fix (definitive, not just hypothesized):**
   - `database.get_pending_digest` (`database.py:3876`) — add
     `AND message != '[audit]'` to the WHERE clause. Defense-in-depth
     even if root cause is elsewhere.
   - `notification_manager._format_digest` — skip items whose `message ==
     '[audit]'` when building lines. Belt-and-suspenders.
   - The actual emit-site the investigation identifies: give the title
     real context per the P24 fix pattern (P24 threaded room / kind into
     stuck-signal titles). The builder MUST document the concrete offending
     site in the fix-up PR body, cite file:line, and reproduce the bad
     delivery in a test BEFORE fixing.

**Acceptance Criteria**
- **Verify (test-anchored):** a test constructs a `notification_log` row
  with `message="[audit]"` for a digest-pref person at MEDIUM severity,
  fires `_fire_digest`, asserts the delivered digest body contains
  no `"[audit]"` substring.
- **Verify:** the identified offending emitter is documented in the PR body
  by file:line, with a repro test that FAILS pre-fix and PASSES post-fix.
- **Sensor:** `sensor.ura_notification_manager_notification_diagnostics`
  attribute `last_notification.message` is never `"[audit]"` for a
  delivered channel (channel ∈ transport set, not `None`).
- **Test:** `test_digest_body_excludes_audit_sentinel_rows`,
  `test_pending_digest_query_filters_audit_sentinel`,
  `test_<offending_emitter>_uses_real_title_and_body` (name filled after D3
  investigation).
- **Live:** during 7 days post-deploy (monitored via DB query, NOT calendar
  soak) no `notification_log` row exists with `delivered > 0 AND message =
  '[audit]'`.

### D4: 04:24-delivered-at-09:26 semantics — regression baseline + explanation

State clearly what remains lagged post-fix and what does not. Add a short
paragraph to the `README_v<version>.md` under a "Delivery latency" heading:

- Security-class exterior alerts (person / vehicle) with image: immediate on
  media-capable channels. **No lag.**
- Security-class exterior alerts without image: immediate on media-capable
  channels (severity CRITICAL/HIGH pre-existing) or digest (severity MEDIUM/LOW,
  no image to lose — L5).
- Non-security digest-pref alerts (all other MEDIUM/LOW): morning/evening
  digest, as designed.

**Acceptance Criteria**
- **Verify:** README paragraph exists and states the three cases.
- **Live (post-deploy validation):** in the first observed real
  exterior-person MEDIUM event, delivered-time − event-time < 30s on any
  media-capable channel.

---

## 7. Reviewer framing (Tier 2 — 2 reviews)

Per PLAN-TIER protocol: ONE adversarial plan review before build; TWO
adversarial code reviews before deploy; live validation after restart; README
write-back.

**Plan review (before build):** verify §2 institutional context is complete
by re-running the greps independently; re-enumerate the delivery legs in §3
(is L4 the only leg?); verify INV-1's falsifiability; verify no number
introduced lacks a knob-ladder line; verify §5 non-goals cover what the
builder might scope-creep into.

**Code Review A — correctness + edge cases:**
- INV-1 holds across all §3 legs; predicate uses `is not None` not truthy
  checks (path could be `""`); hazard whitelist restricts as intended;
  audit row `route_reason` matches ledger convention; `frozenset` immutable
  so no mutation-at-runtime hazard.
- Bug class #22 (enum mismatch): predicate uses `Severity` enum, not string.
- Bug class #53 (computed-not-consumed): assert `snapshot_path` reaches every
  media-capable `_send_*` on the new IMMEDIATE branch.

**Code Review B — async + lifecycle + cross-coordinator:**
- `_channel_gate` / token-bucket interaction: force-immediate does NOT bypass
  the token bucket (fires at MEDIUM/LOW volume; verify per-channel capacity
  can absorb the redirected traffic).
- `_recipient_bypasses_dnd` interaction with new force-immediate: DND matrix
  is still authoritative — no back-door bypass.
- Migration correctness for the audit row schema: `route_reason` values are
  free-string; no schema bump needed. Verify Cycle-C's routing-audit ring
  (maxlen=10) still accepts new label.
- Restart resilience: force-immediate decision is per-call, not persisted —
  restart-safe by design.
- The D3 fix must not affect the ordering of rows in `_format_digest` or the
  `mark_digest_delivered` UPDATE (verify the UPDATE still marks the filtered
  audit rows as `delivered=2` OR intentionally leaves them at `delivered=0`
  and documents which — silent orphans would recur next digest).

**Live Validation (Review 3, post-restart):** run per §6 Live criteria per
deliverable, write results back to `README_v<version>.md` under
`Validated <date>`.

---

## 8. Pre-Review Baseline

Before applying any review fixes: `git tag pre-review-nm-image-1 -m
"Pre-review baseline for NM-IMAGE-1"`.

---

## 9. Plan-completion tracking placeholders

After build, this doc gets a "What did not ship" section enumerating any
deferred item. Currently expected non-deferrals: all D1-D4. Expected
explicit non-goals: §5 (BlueBubbles upload, Design A schema, non-security
whitelist expansion).

---

## 10. Open design points for plan review to ratify or falsify

1. **Rung placement of `NM_SECURITY_HAZARDS`.** Plan says rung 1 (module
   constant). Alternative: rung 2 (options flow) if the operator wants
   per-household extensibility from the UI. Recommendation: rung 1 —
   safety-class routing whitelists don't belong on operator UX; the two
   values covered are structural NM hazard constants.
2. **DND behavior for image-bearing security alerts.** Plan says: honor
   existing `_recipient_bypasses_dnd` matrix — no auto-bypass. Alternative:
   auto-bypass DND for image-bearing security alerts (a person at the door
   at 03:00 is arguably the archetype for bypass). Recommendation: no
   auto-bypass — DND matrix is a signed contract; add auto-bypass only if
   the recipient's real behavior in quiet hours proves the current matrix
   wrong.
3. **D3 investigation depth.** Plan requires the builder to identify the
   concrete emit site by grep + test, not just add defensive filters.
   Alternative: ship defensive filters only, file investigation as
   follow-up. Recommendation: identify AND fix — a sentinel leaking to
   transport is a bug-class we should extinguish at source.
4. **`mark_digest_delivered` semantics for filtered audit rows.** The D3
   fix filters `message='[audit]'` out of `get_pending_digest` — but
   `mark_digest_delivered` still updates all `delivered=0` LOW/MEDIUM rows
   including audit rows. Should audit rows be excluded from the UPDATE
   (staying at `delivered=0` forever, an ever-growing set) or included
   (marked `delivered=2` alongside real ones)? Recommendation: include
   (mark as `delivered=2`) so the queue stays bounded; the audit rows are
   analytical, not deliverable, and marking them `delivered=2` records
   "considered but never rendered".

---

## 11. Verification steps for the reviewer

1. `git grep -n '"exterior_person"\\|"exterior_vehicle"' custom_components/`
   — confirm the two constants are the sole security-hazard producers.
2. `git grep -n 'snapshot_path=\\|snapshot_url=' custom_components/` —
   confirm no NEW emit sites shipped since 2026-08-11 audit; enumerate all
   consumers.
3. `git grep -n 'NM_DELIVERY_IMMEDIATE\\|NM_DELIVERY_DIGEST' custom_components/`
   — confirm the fix modifies the ONE gate at line 1495 and no sibling gate
   elsewhere silently re-selects digest for a security-image emit.
4. `git grep -n '"\\[audit\\]"' custom_components/` — enumerate all
   producers/consumers of the sentinel for D3.
5. Re-run the delivery-leg table in §3 against source and verify no missed
   leg.
