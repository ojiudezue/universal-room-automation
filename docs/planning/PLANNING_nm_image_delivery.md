# PLANNING — NM-IMAGE-1: NM Image Attachment Delivery

**Date opened:** 2026-08-11
**Revised:** 2026-08-11 (rev-2 — plan-review findings applied; see §12
Plan-review record)
**Rev marker:** rev-2
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
At `notification_manager.py:1495` the per-person "always immediate" override
fires only for CRITICAL and HIGH. When the exterior-person severity resolves
to MEDIUM or LOW (e.g. `NM_HAZARD_EXTERIOR_PERSON_GUEST_SEVERITY="MEDIUM"` at
`const.py:1410`, or the pass-by DEMOTE path from the Tier-3 severity-map
coercion at `perimeter_alert.py:1040-1049`), the recipient's pref stays
`digest`. The notification is queued via `database.log_notification` — and
the digest queue **does not persist `snapshot_path` / `snapshot_url` at all**
(see `database.log_notification` signature — no snapshot columns). At flush
time `_deliver_digest` (`notification_manager.py:4168-4241`) calls
`_send_whatsapp` / `_send_imessage` / `_send_pushover` / `_send_companion` with
**no snapshot kwargs**. The image is lost the instant the recipient is
digest-preferred and the severity is not HIGH/CRITICAL.

**Second drop (rev-2, HIGH-1):** the global quiet-hours early-return at
`notification_manager.py:1229-1268` short-circuits `async_notify` BEFORE the
per-person loop when ALL of these hold: `_is_quiet_hours()`, no global bypass,
no per-recipient bypass, no digest-pref recipient. A household whose recipients
are all IMMEDIATE-pref (no digest at all) with a security-image alert at
MEDIUM in quiet hours **would still be dropped even after the :1495 fix**,
because control never reaches :1495. The fix at :1495 alone is insufficient;
the early-return must also learn about the security-image force-immediate
condition. See §4.1 for the composite fix.

**Adjacent observations (in scope, see §6):**
- A bare `Perimeter Alert — [audit]` message reached the operator at 10:01 on
  2026-08-11. Per rev-2 MED-2: the emit site is `_emit_audit_row`
  (`notification_manager.py:4004`), which is **working as designed** —
  `"[audit]"` is the intentional message sentinel used by every routing-audit
  row. The bug is in the READER path: `_deliver_digest` / `_fire_digest` /
  `get_pending_digest` lack a sentinel filter, so audit rows with severity in
  LOW/MEDIUM (e.g. `dnd_suppressed` audit rows for MEDIUM alerts) get pulled
  into the next digest body. No investigation phase; the fix is reader-side
  filtering (§6-D3).
- A 04:24 exterior-person event was delivered at 09:26 (~5h latency). This is
  the *same drop* as the primary bug: MEDIUM severity + digest pref → held
  until morning flush → also stripped of image. Design B closes this by making
  image-bearing security-class alerts force-immediate, independent of
  digest pref AND independent of the global DND early-return.

**iMessage attachments are separately structural** (BlueBubbles integration
drops them on `send_message`). Out of scope for NM-IMAGE-1, tracked as
`SNAP-1-followup`. See §5.

---

## 1. Falsifiable Invariant (rev-2)

**INV-1 (primary):** *For every exterior security-class alert (`hazard_type in
NM_SECURITY_HAZARDS`) with a truthy snapshot (`snapshot_path or snapshot_url`
is truthy) that survives NM's pre-existing suppressions — namely global kill
switch (`_messaging_suppressed`), `enabled=False`, silence-until
(`_silence_until`), event-type dedup (`_last_notification_at` per
`{event_type}:{location}`), boot-settle guard, and memory-conditioning /
allowlist skips — the alert is delivered on the IMMEDIATE branch on every
channel the router selects for `(recipient, hazard_type, severity)`, with the
attachment threaded to any channel whose transport renders attachments
(Pushover, Companion, WhatsApp). It is never queued to digest, never rendered
image-less, and never dropped by the global quiet-hours early-return.*

**Suppressions INV-1 does NOT override (deliberate, per rev-2 HIGH-3):**
- `_messaging_suppressed` / kill switch (life-safety operator control).
- `enabled=False` (NM off).
- `_silence_until` window (operator active silence).
- Dedup window on `{event_type}:{location}` (NM_DEDUP_* — prevents camera
  hammering).
- **Boot-settle guard** (NM Cycle B B4 boot-burst guard — critical: protects
  against camera-boot avalanches where a whole exterior camera bank re-arms
  and fires simultaneous person events).
- Memory-conditioning / recipient mute / channel mute (Cycle-C router
  decisions the operator legitimately owns).
- Recipient DND without a matching bypass entry (see L9 in §3).

Rationale: these are the operator's active, contract-shaped suppressions;
security-image force-immediate is a routing-priority fix, not a suppression
bypass.

**INV-2 (audit hygiene):** *No `notification_log` row whose `message` field
equals the `"[audit]"` sentinel is ever rendered into a transport body
delivered to a recipient. The sentinel remains the canonical audit-row marker;
readers filter it.*

Both invariants are falsifiable by direct DB query + transport-log inspection.

**"Channel the router selects" (MED-1 clarification):** the media-capable
receiver of the attachment is the intersection of (a) the Cycle-C router's
`_route_for_recipient(person_id, hazard_type, severity)` decision, (b) the
per-channel token-bucket gate, and (c) the recipient's configured targets.
INV-1 does not force delivery on channels the router omitted; it forces
delivery on the ones it selected.

---

## 2. Institutional context verified

### Files read end-to-end during scoping
- `custom_components/universal_room_automation/domain_coordinators/notification_manager.py` — targeted spans:
  1180-1220 (async_notify signature), 1229-1268 (global quiet-hours
  early-return — REV-2 HIGH-1 site), 1460-1650 (channel routing +
  CRITICAL/HIGH override at 1495), 3960-4018 (`_emit_audit_row`), 4053-4316
  (digest timers, `_fire_digest`, `_deliver_digest`, `_format_digest`).
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
| Image-bearing force-immediate override | **NEW (surgical, two sites)** | Extends CRITICAL/HIGH branch at `notification_manager.py:1495` AND the global quiet-hours early-return condition at :1261-1265; no equivalent guard exists in Cycle A/B/C. |
| Snapshot kwargs on `_deliver_digest` path | **NOT PROPOSED** (design alt A parked) | See §4.2. |
| `NM_HAZARD_EXTERIOR_PERSON` / `NM_HAZARD_EXTERIOR_VEHICLE` constants | **REUSED** | `const.py:1394 / 1406`. |
| `NM_SECURITY_HAZARDS` set (media-force-immediate whitelist) | **NEW** — module constant in `const.py` | Rung-1. See §4.4. |
| `NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE`, `NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE` | **NEW** — module constants (per rev-2 LOW-3) | Named next to the pre-existing free-string `"dnd_suppressed"` at :1529; that legacy string stays as-is to avoid churn — the two NEW values are constants from day one. |
| `"[audit]"` message sentinel | **REUSED — working as designed** | `notification_manager.py:4004`, `coordinator.py:218`, `_stuck_signal_nm.py:200-202`. Per MED-2: emit is intentional; readers must filter. |
| `get_pending_digest` filter (excluding `message="[audit]"`) | **EXTEND** existing method | `database.py:3876`; single-line WHERE-clause addition. |
| `_format_digest` defensive filter | **EXTEND** existing method | `notification_manager.py:4290-4316`; belt-and-suspenders. |
| Perimeter Alert titles (exact strings) | **REUSED** | `perimeter_alert.py:1201, 2235, 3136-3139`. |

### Prior planning docs consulted
- `docs/planning/PLANNING_nm_overhaul_2026_07.md` — full read.
- `docs/planning/PLANNING_nm_cycle_c_routing_matrix.md` — skimmed for router
  branch labels used in audit rows.
- `docs/planning/PLANNING_nm_cycle_c2_routing_ui.md` — skimmed.
- `docs/planning/AUDIT_nm_rename_impact.md` — skimmed.

### Memory bodies pulled
- Memory "NM BlueBubbles + WhatsApp Audit 2026-05-30" — confirms iMessage
  attachment path is structural.
- Memory "resume 2026-08-05" — v5.51.1 shipped; NM Cycle A/B/C live.
- No prior NM-IMAGE cycle.

### Design doc read
- `docs/Coordinator/NOTIFICATION_MANAGER.md` — pre-implementation doc, does
  not cover attachment routing.

### QUALITY_CONTEXT bug classes considered
- **#53 (computed-but-not-consumed):** `snapshot_path` is computed at the
  perimeter edge and threaded into `async_notify`, but the digest queue does
  not persist it — a textbook consume-drop. INV-1 exists to prevent it.
- **#22 (enum mismatch):** predicate uses `Severity` enum, not string; hazard
  membership uses the constant set.
- Digest force-immediate survives HA restart: fix lives inside `async_notify`,
  not in restored state.

---

## 3. NM delivery-leg enumeration (S-style, for INV-1 completeness)

Every reachable delivery leg for an image-bearing exterior alert, today vs. post-fix:

| # | Leg | Trigger | Today (image?) | Post-fix (image?) |
|---|---|---|---|---|
| L1 | IMMEDIATE, severity CRITICAL/HIGH, non-DND | line 1495 override | YES (all media-capable channels) | UNCHANGED |
| L2 | IMMEDIATE-pref, severity MEDIUM/LOW, non-DND | pref=IMMEDIATE | YES (media kwargs threaded) | UNCHANGED |
| L3 | DIGEST-pref, severity CRITICAL/HIGH | line 1495 override forces immediate | YES | UNCHANGED |
| **L4** | **DIGEST-pref, severity MEDIUM/LOW, `hazard∈SECURITY` + snapshot present, NOT quiet hours** | line 1495 does NOT fire → queued row (no snapshot cols) | **NO — image lost** | **YES — force-immediate; delivered on router-selected media-capable channels** |
| **L4′** | **REV-2 HIGH-1: severity MEDIUM/LOW, `hazard∈SECURITY` + snapshot present, IN quiet hours, ALL recipients IMMEDIATE-pref, no global/per-recipient bypass matching MEDIUM** | today: global early-return at :1261-1265 fires → `return` → per-person loop never runs → :1495 fix never fires | **NO — image lost (global early-return)** | **YES — early-return condition ANDed with `not _force_immediate_for_security_image`; control flows to per-person loop; :1495 fix + `_recipient_bypasses_dnd` decide per person (see L9)** |
| L5 | DIGEST-pref, severity MEDIUM/LOW, `hazard∈SECURITY`, NO snapshot | line 1495 does NOT fire | body-only in next digest | UNCHANGED (no image to lose) |
| L6 | DIGEST-pref, severity MEDIUM/LOW, `hazard∉SECURITY` | line 1495 does NOT fire | body-only in next digest | UNCHANGED |
| L7 | DIGEST flush | `_fire_digest` → `_deliver_digest` | body-only, ever | UNCHANGED for media; **rev-2 fix: filter `message="[audit]"` rows out at `get_pending_digest` AND at `_format_digest`.** |
| L8 | Quiet-hours / global DND + IMMEDIATE-pref, non-security | line 1515-1536: audit row only, no send | audit row (no send) | UNCHANGED |
| L9 | Quiet-hours + security-image, per-recipient decision | today: L4′ short-circuit removes this case entirely; where reached (recipient DND, no bypass) → audit row | image lost / suppressed | **Reached post-fix.** Recipient with `_recipient_bypasses_dnd(...)`=True: image delivered IMMEDIATE. Recipient without bypass: audit row `NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE`, image NOT deferred to digest (would be stale). No auto-bypass. |
| L10 | `CONF_NM_DRY_RUN` active | `_dry_run_active=True` | audit row only | UNCHANGED — dry-run stays honest. |
| L11 | Weekly regime digest | `_send_regime_weekly_digest` | body-only | UNCHANGED — regime events are not security-class. |
| L12 | Global kill switch `_messaging_suppressed` | `async_notify` early-return line 1211 | nothing sent | UNCHANGED (deliberate — see INV-1 non-override list). |
| L13 | `enabled=False` (NM disabled) | early-return line 1206 | nothing sent | UNCHANGED (deliberate). |
| L14 | Legacy `notify_service` fallback | `perimeter_alert.py:1188` | legacy path | UNCHANGED — outside NM. |
| L15 | Silence-until active (`_silence_until` > now) | line ~693-699 | dropped | UNCHANGED (deliberate — operator active silence). |
| L16 | Dedup window closed for `{event_type}:{location}` | `_last_notification_at` gate | dropped | UNCHANGED (deliberate — camera-hammer protection). |
| L17 | Boot-settle guard active (NM Cycle B B4) | boot-burst guard | dropped | UNCHANGED (deliberate — camera-boot avalanche protection; rev-2 HIGH-3 explicit). |

**Post-fix invariant on L4, L4′, L9:** an image-bearing security alert that
survives L12/L13/L15/L16/L17 never enters the digest queue and is never
dropped by the global quiet-hours early-return. It either lands IMMEDIATE on
router-selected media-capable channels or is suppressed by an existing
pre-existing per-recipient gate (mute / DND without bypass) — with an audit
row explaining which via a named `route_reason`.

---

## 4. Design decision — B (image-bearing security-class force-immediate)

### 4.1 What the fix is — TWO sites, one predicate (rev-2)

Introduce a helper predicate computed ONCE per `async_notify` call, before the
global quiet-hours early-return, and reused at both suppression sites:

```python
_force_immediate_for_security_image = (
    hazard_type in NM_SECURITY_HAZARDS
    and bool(snapshot_path or snapshot_url)   # rev-2 MED-4: truthy, not is-not-None
)
```

**Site A — global quiet-hours early-return (`notification_manager.py:1229-1268`,
per rev-2 HIGH-1):** OR the new predicate into the "any escape" condition so
the early-return does NOT fire on a security-image emit:

```python
if (
    not global_bypass
    and not any_recipient_bypass
    and not any_digest_recipient
    and not _force_immediate_for_security_image   # NEW
):
    _LOGGER.debug("Notification suppressed during quiet hours: %s", title)
    self._quiet_suppressions += 1
    return
```

This preserves every existing escape (global bypass, per-recipient bypass,
digest-queue path) and adds one more. Byte-identical when the predicate is
False (i.e. non-security emit, or no snapshot).

**Site B — per-person force-immediate at `notification_manager.py:1490-1498`:**
extend the existing gate to also OR the new predicate:

```python
if (
    severity in (Severity.CRITICAL, Severity.HIGH)
    or _force_immediate_for_security_image     # NEW
):
    effective_pref = NM_DELIVERY_IMMEDIATE
else:
    effective_pref = delivery_pref
```

The predicate is computed once outside the loop; both sites use the same
Python-level value — reviewers can trace one source, not two.

Rest of the pipeline (matrix router, mute, token bucket, per-recipient DND
bypass, `_send_*` attachment threading) is unchanged. Because `_send_pushover`,
`_send_companion`, `_send_whatsapp` already carry `snapshot_path`/`snapshot_url`
on the IMMEDIATE branch, the image ships with the alert on every routed
media-capable channel.

Audit-row `route_reason` values (per rev-2 LOW-3, named constants):
- `NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE` for the override branch.
- `NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE` for L9 recipient-DND
  without bypass.

Both added to `const.py` next to the Cycle-C router constants.

### 4.2 Why not design A (persist snapshot into digest rows)

- **Value dies with staleness** — 4-5h old image in the morning digest.
- **Schema touch** (`notification_log` migration + `log_notification`
  signature bump + write-volume audit) for a stale delivery.
- **Marginal benefit fails decomposition:** simple version B captures the
  entire operator-visible benefit; A adds churn AND latency.
- **Parked, not deleted:** revisit only if a non-security image-bearing
  MEDIUM emitter is added AND digest-time delivery of that image is
  demonstrably useful.

### 4.3 Hybrid (B for security, A never) — accepted

Non-security image-bearing alerts are theoretical today. If one appears,
`NM_SECURITY_HAZARDS` is the extension point, not schema.

### 4.4 The knob and its rung

`NM_SECURITY_HAZARDS: Final[frozenset[str]] = frozenset({
    NM_HAZARD_EXTERIOR_PERSON, NM_HAZARD_EXTERIOR_VEHICLE
})`

- **Rung 1 (module constant in `const.py`).** Safety-class routing whitelist;
  expansion requires code review. Kill-switch semantics: `frozenset()` disables
  the override → byte-identical to pre-cycle behavior. Documented on constant.
- **NOT rung 2 / rung 3.**

No other new numbers introduced. Existing severity map at `const.py:1415` and
hazard type constants at 1394/1406 are unchanged.

### 4.5 What remains lagged after B ships — state honestly (rev-2)

- **L5, L6, L11 (non-security or no-snapshot MEDIUM/LOW):** digest-lagged.
  Correct.
- **iMessage attachments:** structurally dropped by BlueBubbles regardless of
  B (SNAP-1-followup). Text-only on iMessage; image on WhatsApp / Pushover /
  Companion.
- **L15/L16/L17 (silence-until / dedup / boot-settle):** honestly dropped.
  INV-1 does not override these (see §1 non-override list).
- **L9 without bypass:** honestly not delivered. Audit row records
  `NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE`. No auto-bypass.
- **Digest-body echo of force-immediate rows (rev-2 HIGH-2, explicit trade):**
  a security-image alert delivered via the force-immediate override writes
  its `notification_log` row with `delivered=1`. `get_pending_digest`
  already filters on `delivered=0` (`database.py:3883`), so this row will
  NOT reappear in the morning digest body. **Deliberate:** the immediate
  delivery IS the authoritative surfacing; echoing it in the digest hours
  later would produce a "did I already handle this?" recipient experience
  and dilute the digest with events already actioned. **Parked
  alternative:** a `_format_digest` branch that pulls `delivered=1`
  security rows from the last N hours into an "already sent (for context)"
  section — deferred pending operator observation that omission is missed.
  This is the design's chosen trade, not an oversight.
- **Predicate empty-string case (rev-2 MED-4):** `snapshot_path=""` and
  `snapshot_url=""` are treated as "no snapshot" (truthy check). Documented
  in `const.py` alongside `NM_SECURITY_HAZARDS`. Upstream emitters
  (`perimeter_alert.py`) pass `None` when no snapshot; empty string would
  represent a bug upstream (e.g. snapshot-capture returned an empty path),
  and the truthy check correctly refuses to force-immediate a broken
  emitter — we do not want to page the operator with a garbage attachment
  reference. Test coverage in D2.

---

## 5. Non-goals (explicit)

- **BlueBubbles iMessage attachment upload** (`SNAP-1-followup`).
- **CONSOL-1 llmvision consolidation.**
- **Digest-row schema expansion (Design A).**
- **Changing severity resolution / DEMOTE map.**
- **Non-exterior hazard types** (`NM_SECURITY_HAZARDS` restricted to two).
- **Changes to Cycle-C router matrix behavior** (mute, DND-bypass, matrix
  branch labels).
- **Auto-bypass of DND for security-image alerts** (see §10.2).
- **Migration of legacy free-string `route_reason` values to constants
  wholesale** — only the two NEW values are constants (rev-2 LOW-3);
  migrating `"dnd_suppressed"` etc. is a separate hygiene cycle.
- **`_format_digest` "already sent security events" section** (rev-2
  HIGH-2 parked alt).

---

## 6. Deliverables

### D0 (build precondition, rev-2 LOW-1): live-DB baseline count

Before applying D3's `mark_digest_delivered` semantics change, capture:

```sql
SELECT COUNT(*) FROM notification_log
 WHERE message = '[audit]' AND delivered = 0 AND severity IN ('LOW','MEDIUM');
```

Recorded in the PR body as `baseline_audit_undelivered_count = <N>` so post-
deploy the growth rate can be measured and D3's mark-`delivered=2` behavior
verified as bounded.

**Acceptance Criteria**
- **Verify:** count captured via `ura-sqlite` MCP against the LIVE Samba-
  mounted DB path, recorded in PR body before the D3 fix commit lands.
- **Live:** 24h post-deploy, re-run the same query; count should not grow
  unboundedly (marking `delivered=2` OR filtering at emit should bound it).

### D1: `NM_SECURITY_HAZARDS` + `NM_ROUTE_REASON_*` constants

Add to `const.py` alongside the existing NM hazard constants (~line 1408):

- `NM_SECURITY_HAZARDS: Final[frozenset[str]] = frozenset({NM_HAZARD_EXTERIOR_PERSON, NM_HAZARD_EXTERIOR_VEHICLE})`
- `NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE: Final[str] = "force_immediate_security_image"`
- `NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE: Final[str] = "dnd_suppressed_security_image"`

Docstrings:
- `NM_SECURITY_HAZARDS`: purpose (attachment-preserving force-immediate
  whitelist), kill-switch (`frozenset()`), how to extend, and rev-2 MED-4
  note that the predicate is truthy on `snapshot_path or snapshot_url`
  (empty string treated as "no snapshot" by design).
- Route-reason constants: cross-reference to the Cycle-C audit ledger
  convention.

**Acceptance Criteria**
- **Verify:** `NM_SECURITY_HAZARDS == frozenset({"exterior_person",
  "exterior_vehicle"})` post-import; both route-reason constants importable.
- **Test:** `test_nm_security_hazards_constant_shape` — asserts type,
  contents, and that empty override on the `notification_manager` module
  binding (per rev-2 MED-3) cleanly disables the force-immediate paths.
  Monkeypatch target: `custom_components.universal_room_automation.
  domain_coordinators.notification_manager.NM_SECURITY_HAZARDS` (the module
  binding used at call sites), NOT `const.NM_SECURITY_HAZARDS`. Python
  imports rebind at import time; patching const alone leaves stale
  references in `notification_manager`.
- **Test:** `test_nm_route_reason_constants_are_strings`.
- **Live:** module import in HA log shows no error; NM boot completes.

### D2: `async_notify` force-immediate at both suppression sites

Modify:

1. `notification_manager.py:1229-1268` — global quiet-hours early-return.
   Compute `_force_immediate_for_security_image` at the top of the
   `async_notify` body (after `_refresh_config`), pass it into the
   condition OR (see §4.1 Site A). Predicate uses the module binding of
   `NM_SECURITY_HAZARDS` (per rev-2 MED-3).
2. `notification_manager.py:1490-1498` — per-person `effective_pref`
   selection. OR the same predicate into the CRITICAL/HIGH branch
   (see §4.1 Site B).
3. Audit rows on both override paths use the named constants:
   - Force-immediate override in the per-person loop:
     `route_reason=NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE`.
   - Recipient-DND suppression on a would-be-force-immediate security image
     (L9 without bypass): `route_reason=NM_ROUTE_REASON_DND_SUPPRESSED_
     SECURITY_IMAGE`.

Predicate MUST be computed ONCE per `async_notify` call, above the DND
early-return, and reused at both sites — avoids inconsistent decisions if
config re-reads between sites.

**Acceptance Criteria**
- **Verify:** `async_notify(hazard=exterior_person, severity=MEDIUM,
  snapshot_path="/media/ura/snapshots/foo.jpg", ...)` with a digest-pref
  recipient invokes `_send_pushover` / `_send_whatsapp` / `_send_companion`
  on the IMMEDIATE branch with the snapshot threaded.
- **Verify:** same call with `snapshot_path=None AND snapshot_url=None`
  falls through to the recipient's `delivery_pref` unchanged.
- **Verify:** same call with `hazard="indoor_humidity"` + snapshot does NOT
  force immediate.
- **Verify (rev-2 MED-4):** same call with `snapshot_path=""` and
  `snapshot_url=""` does NOT force immediate (truthy check).
- **Verify (rev-2 HIGH-1, L4′):** during `_is_quiet_hours()==True` with ALL
  recipients IMMEDIATE-pref (no digest, no bypass matching MEDIUM), an
  exterior-person MEDIUM+snapshot emit does NOT hit the early-return —
  control reaches the per-person loop and each recipient's DND-bypass
  matrix decides.
- **Test:** `test_security_image_forces_immediate_over_digest`,
  `test_no_snapshot_no_forced_immediate`,
  `test_non_security_snapshot_no_force`,
  `test_empty_string_snapshot_no_force`,
  `test_security_image_survives_global_dnd_early_return_with_all_immediate_pref_recipients`
  (rev-2 HIGH-1 acceptance test — exact name required),
  `test_force_immediate_respects_recipient_dnd_bypass`,
  `test_force_immediate_respects_global_kill_switch`,
  `test_force_immediate_respects_silence_until`,
  `test_force_immediate_respects_dedup_window`,
  `test_force_immediate_respects_boot_settle_guard`
  (last three cover the INV-1 non-override list).
- **Test (audit-row):**
  `test_audit_row_route_reason_force_immediate_security_image`,
  `test_audit_row_route_reason_dnd_suppressed_security_image` — assert the
  constants (not string literals) appear in DB rows and in the
  `_routing_audit_log` ring feeding
  `sensor.ura_notification_manager_notification_diagnostics.
  nm_routing_audit_recent`.
- **Live:** trigger a live exterior-person event during guest state
  (MEDIUM), observe WhatsApp / Pushover / Companion delivery with
  attachment within `<10s` of edge capture; `notification_log` row shows
  `delivered=1`, `channel in {pushover,companion,whatsapp}`,
  `route_reason='force_immediate_security_image'`.
- **Live:** `sensor.ura_notification_manager_notification_diagnostics`
  attribute `nm_routing_audit_recent` contains an entry with
  `route_reason='force_immediate_security_image'`.
- **Live (rev-2 LOW-2 fallback path when guest state isn't reproducible):**
  temporarily set the operator recipient's `delivery_pref=digest`, fire a
  normal-severity exterior-person test event (real capture, not synthetic),
  observe immediate delivery + attachment, then restore
  `delivery_pref` to prior value. Documented in the README validation
  table as the fallback path used and why.

### D3: `[audit]` sentinel reader-side filter (rev-2 MED-2 — no investigation)

Root cause is settled: `_emit_audit_row` (`notification_manager.py:4004`)
writes `message="[audit]"` intentionally as the audit-row marker; this is the
canonical audit sentinel. The leak is that `get_pending_digest` /
`_deliver_digest` / `_format_digest` do NOT filter it. No investigation
phase — go straight to the reader fixes:

1. `database.get_pending_digest` (`database.py:3876`) — add
   `AND message != '[audit]'` to the WHERE clause.
2. `notification_manager._format_digest` (`notification_manager.py:4290`)
   — defensive skip of items where `item.get("message") == "[audit]"`.
3. `database.mark_digest_delivered` (`database.py:3893`) — decision
   post-D0 baseline: mark audit rows `delivered=2` alongside real ones
   (bounded queue growth). D0 baseline count justifies the semantics change.

**Acceptance Criteria**
- **Verify:** test constructs a `notification_log` row with
  `message="[audit]"` for a digest-pref person at MEDIUM severity, fires
  `_fire_digest`, asserts delivered digest body contains no `"[audit]"`
  substring.
- **Verify:** `get_pending_digest` returns 0 rows for a person whose only
  pending rows have `message='[audit]'`.
- **Verify:** `_format_digest` given a mixed list of real + audit rows
  emits lines only for the real rows (belt-and-suspenders).
- **Sensor:** `sensor.ura_notification_manager_notification_diagnostics`
  attribute `last_notification.message` is never `"[audit]"` for a
  delivered channel (channel ∈ transport set, not `None`).
- **Test:** `test_digest_body_excludes_audit_sentinel_rows`,
  `test_pending_digest_query_filters_audit_sentinel`,
  `test_format_digest_skips_audit_sentinel_items`,
  `test_mark_digest_delivered_also_marks_audit_rows_bounded`.
- **Live:** 7 days post-deploy, DB query `SELECT COUNT(*) FROM
  notification_log WHERE delivered > 0 AND message = '[audit]'` returns 0.
- **Live (bounded queue):** D0 baseline count post-deploy has NOT grown
  monotonically at MEDIUM+LOW volume (mark-`delivered=2` semantics
  working).

### D4: Delivery-latency semantics — regression baseline + README paragraph

State clearly what remains lagged post-fix. Add to `README_v<version>.md`
under a "Delivery latency" heading:

- Security-class exterior alerts (person / vehicle) with image: immediate on
  router-selected media-capable channels. **No lag.** Applies even during
  quiet hours to households with all-IMMEDIATE-pref recipients (per L4′ fix).
- Security-class exterior alerts without image: existing behavior — immediate
  if CRITICAL/HIGH, digest if MEDIUM/LOW (no image to lose).
- Non-security digest-pref alerts (all other MEDIUM/LOW): morning/evening
  digest, as designed.
- Suppressions that STILL drop the alert (deliberate): kill switch, NM
  disabled, silence-until, dedup window, boot-settle guard, recipient DND
  without matching bypass.

**Acceptance Criteria**
- **Verify:** README paragraph exists and states all four cases.
- **Live (post-deploy validation):** first observed real exterior-person
  MEDIUM event, `delivered_time − event_time < 30s` on any media-capable
  channel. Fallback per rev-2 LOW-2 documented above.

---

## 7. Reviewer framing (Tier 2 — 2 reviews)

Per PLAN-TIER protocol: ONE adversarial plan review before build (COMPLETE —
rev-2 findings applied, see §12); TWO adversarial code reviews before deploy;
live validation after restart; README write-back.

**Code Review A — correctness + edge cases:**
- INV-1 holds across §3 legs L1-L17; predicate is truthy (`bool(a or b)`),
  hazard whitelist restricts as intended; audit-row constants used (not
  string literals); `frozenset` immutable.
- Bug class #22 (enum mismatch): predicate uses `Severity` enum + string
  constants correctly.
- Bug class #53 (computed-not-consumed): assert `snapshot_path` reaches
  every media-capable `_send_*` on the new IMMEDIATE branch AND on the L4′
  post-early-return path.
- Empty-string snapshot case (§4.5): predicate refuses to force.

**Code Review B — async + lifecycle + cross-coordinator:**
- Global early-return interaction with the new predicate (rev-2 HIGH-1):
  verify the predicate is computed ONCE at the top of `async_notify` and
  the value is the SAME object referenced at both sites (no config
  re-read between sites can flip it).
- `_channel_gate` / token-bucket interaction: force-immediate does NOT
  bypass the token bucket (fires at MEDIUM/LOW volume; verify capacity).
- `_recipient_bypasses_dnd` interaction: DND matrix authoritative — no
  back-door bypass (per §10.2).
- Restart resilience: decision is per-call, not persisted.
- `mark_digest_delivered` UPDATE now touches audit rows too — verify no
  downstream consumer of `delivered=2` treats audit rows as delivered
  notifications (grep confirms `delivered=2` is a queue-management marker,
  not a "was sent" attribute).
- Cycle-C router-audit ring (maxlen=10) accepts new `route_reason` values
  (they're free-string in the ring; constants used for authorship).

**Live Validation (Review 3, post-restart):** run per §6 Live criteria per
deliverable, write results back to `README_v<version>.md` under
`Validated <date>`.

---

## 8. Pre-Review Baseline

Before applying any code-review fixes: `git tag pre-review-nm-image-1 -m
"Pre-review baseline for NM-IMAGE-1"`.

---

## 9. Plan-completion tracking placeholders

Post-build, this doc gets a "What did not ship" section. Explicit non-goals
listed in §5.

---

## 10. Open design points — dispositions (rev-2)

1. **Rung of `NM_SECURITY_HAZARDS`:** rung 1 (module constant). Ratified.
2. **DND auto-bypass for security-image:** NO auto-bypass. Ratified — DND
   matrix is a signed contract.
3. **D3 investigation depth:** RESOLVED (rev-2 MED-2) — no investigation;
   the emit site is intentional (audit sentinel), the leak is reader-side.
4. **`mark_digest_delivered` for filtered audit rows:** mark `delivered=2`
   to bound the queue. Baselined at D0 (rev-2 LOW-1).
5. **Digest-body echo of force-immediate rows:** NOT echoed
   (`delivered=1` excluded by existing `get_pending_digest` filter);
   deliberate (rev-2 HIGH-2). Parked alt documented in §4.5.

---

## 11. Verification steps for the reviewer

1. `git grep -n '"exterior_person"\\|"exterior_vehicle"' custom_components/`
   — confirm the two constants are the sole security-hazard producers.
2. `git grep -n 'snapshot_path=\\|snapshot_url=' custom_components/` —
   confirm no NEW emit sites shipped since 2026-08-11 audit; enumerate all
   consumers.
3. `git grep -n 'NM_DELIVERY_IMMEDIATE\\|NM_DELIVERY_DIGEST' custom_components/`
   — confirm the fix modifies the ONE gate at :1495 AND the early-return at
   :1261-1265, and no sibling gate elsewhere silently re-selects digest for
   a security-image emit.
4. `git grep -n '"\\[audit\\]"' custom_components/` — enumerate all
   producers/consumers of the sentinel; confirm the ONLY producer is
   `_emit_audit_row:4004` (MED-2 assertion).
5. `git grep -n 'NM_SECURITY_HAZARDS' custom_components/` — confirm both
   suppression sites and the `const` definition, and that
   `notification_manager` imports the name (module binding for MED-3
   monkeypatch target).
6. Re-run the §3 delivery-leg table against source and verify no missed
   leg. Particular attention to boot-settle guard (L17) and dedup (L16) —
   INV-1 explicitly does NOT override them.

---

## 12. Plan-review record (rev-1 → rev-2)

Plan review returned **NEEDS-REVISION** with the following findings; all
addressed in rev-2:

| ID | Severity | Finding | Rev-2 disposition |
|---|---|---|---|
| HIGH-1 | HIGH | Global-DND early-return at :1229-1268 short-circuits BEFORE per-person loop; :1495 fix insufficient for all-IMMEDIATE-pref households in quiet hours. | Added L4′ to §3 table; §4.1 Site A specifies OR of `_force_immediate_for_security_image` into early-return condition; predicate pre-computed once; new acceptance test `test_security_image_survives_global_dnd_early_return_with_all_immediate_pref_recipients` in D2. |
| HIGH-2 | HIGH | Digest-summary behavioral trade unstated: force-immediate rows land `delivered=1` and won't reappear in morning digest. | §4.5 states the trade explicitly (deliberate; immediate delivery authoritative). Parked alt: `_format_digest` "already-sent security" section, deferred pending operator evidence. Disposition also in §10.5. |
| HIGH-3 | HIGH | INV-1 must name silence/dedup/boot-settle/memory-conditioning as pre-existing suppressions it does NOT override. | INV-1 rewritten in §1 with explicit non-override list; boot-settle called out as critical (camera-boot avalanche protection). §3 table extended with L15/L16/L17. §11 verification step 6 checks this. |
| MED-1 | MEDIUM | "Media-capable channel" too broad — should be scoped to "channels the router selects for (recipient, hazard_type, severity)". | INV-1 phrasing corrected in §1; §1 tail paragraph "Channel the router selects" clarifies intersection with router + token bucket + configured targets. §3 L4/L4′ text updated. |
| MED-2 | MEDIUM | D3 should commit that the emit site is `_emit_audit_row:4004` (working as designed) and the leak is the READER — no investigation phase. | §0 adjacent observations, §2 grep table, D3 body, and §10.3 all state the resolution. D3 restructured to skip investigation and specify reader-side fixes (`get_pending_digest`, `_format_digest`, `mark_digest_delivered`). |
| MED-3 | MEDIUM | Monkeypatch target for the disable-override test must be the `notification_manager` module binding, not `const`. | D1 acceptance criteria explicitly names `custom_components.universal_room_automation.domain_coordinators.notification_manager.NM_SECURITY_HAZARDS` as the patch target and explains why. §11 step 5 adds the grep verification. |
| MED-4 | MEDIUM | Predicate is truthy (`snapshot_path or snapshot_url`), not `is not None`; document empty-string case. | §4.1 code sample uses `bool(snapshot_path or snapshot_url)`; §4.5 documents empty-string treatment; D1 docstring requirement; D2 test `test_empty_string_snapshot_no_force`. |
| LOW-1 | LOW | Build precondition: live-DB count of `message='[audit]' AND delivered=0` rows before changing `mark_digest_delivered` semantics. | Added D0 as build precondition (SQL query, PR body capture, growth-bound live check). §10.4 references. |
| LOW-2 | LOW | Live-criteria fallback for guest-state MEDIUM case. | D2 Live section adds fallback: temporarily set operator recipient `delivery_pref=digest` and fire real-capture normal-severity emit; document in README validation table. |
| LOW-3 | LOW | New `route_reason` strings become named constants next to Cycle-C siblings. | `NM_ROUTE_REASON_FORCE_IMMEDIATE_SECURITY_IMAGE` and `NM_ROUTE_REASON_DND_SUPPRESSED_SECURITY_IMAGE` defined in D1; used in D2. §5 clarifies scope: only NEW values become constants; legacy free-strings left as-is to avoid scope creep. |

Rev marker bumped to **rev-2**. Ready for build dispatch subject to a
one-line orchestrator re-read confirming the L4′ code-shape recommendation
is acceptable OR the operator's preferred alternative shape is subbed in
before build.
