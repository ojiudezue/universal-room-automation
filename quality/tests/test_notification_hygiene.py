"""Notification Hygiene cycle (2026-08-03) — source-anchored tests.

Covers FIX 1..5 from the repeat-storm + long-suppression incident:

  FIX 1 — Suppression age gate on restart (B-3(c))
  FIX 2 — CRITICAL repeat decay ladder + age-across-restart
  FIX 3 — Write-verify severity split (attempts=HIGH, final+standdown=CRITICAL)
  FIX 4 — Ack audit row via _emit_audit_row
  FIX 5 — Per-person safe words + security ack authority

These tests are source-anchored (read the .py files as text) so they run
without spinning up HA — matching the pattern of
test_nm_suppression_visibility.py in the same suite.
"""
from __future__ import annotations

import ast
import os


HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
        return fh.read()


CONST_SRC = _read("custom_components/universal_room_automation/const.py")
NM_SRC = _read(
    "custom_components/universal_room_automation/domain_coordinators/"
    "notification_manager.py"
)
SWITCH_SRC = _read("custom_components/universal_room_automation/switch.py")
BUTTON_SRC = _read("custom_components/universal_room_automation/button.py")
INIT_SRC = _read("custom_components/universal_room_automation/__init__.py")
CFG_SRC = _read("custom_components/universal_room_automation/config_flow.py")
WV_SRC = _read(
    "custom_components/universal_room_automation/domain_coordinators/"
    "energy_write_verify.py"
)


# ---------------------------------------------------------------------------
# FIX 1 — Suppression age gate on restore
# ---------------------------------------------------------------------------
def test_fix1_max_age_const_default_and_kill_semantics():
    assert "NM_SUPPRESSION_RESTORE_MAX_AGE_S: Final = 86400" in CONST_SRC
    # Kill-switch semantics documented (0 → legacy).
    assert "Kill: 0 disables the gate" in CONST_SRC


def test_fix1_switch_marks_restore_pending_only_on_restore_path():
    # Restore-triggered sync sets _restore_pending; operator toggles do not.
    assert "self._restore_pending = True  # FIX 1" in SWITCH_SRC
    # __init__ initializes to False.
    assert "self._restore_pending = False" in SWITCH_SRC


def test_fix1_gate_reads_const_and_uses_since_or_last_changed_fallback():
    # The gate must consult the const AND accept a switch-last-changed
    # fallback when nm._suppressed_since is None (mirrors the daily-warning
    # helper approximation policy).
    assert "NM_SUPPRESSION_RESTORE_MAX_AGE_S" in SWITCH_SRC
    assert 'getattr(nm, "_suppressed_since", None)' in SWITCH_SRC
    assert "last_changed" in SWITCH_SRC


def test_fix1_gate_emits_one_shot_high_and_flips_off():
    # On stale restore: flip _is_on to False, WARNING log, send HIGH notify
    # (MED-A4: promoted from MEDIUM so it bypasses digest preferences).
    assert "self._is_on = False" in SWITCH_SRC
    assert "NM messaging suppression NOT restored on startup" in SWITCH_SRC
    assert "Severity.HIGH" in SWITCH_SRC


def test_fix1_kill_switch_zero_skips_gate():
    # Guard: max_age <= 0 → gate is inert (legacy always-restore).
    assert "if max_age > 0:" in SWITCH_SRC


# ---------------------------------------------------------------------------
# FIX 2 — CRITICAL repeat decay ladder
# ---------------------------------------------------------------------------
def test_fix2_ladder_consts_present_with_defaults():
    assert "NM_REPEAT_PHASE1_S: Final = 300" in CONST_SRC
    assert "NM_REPEAT_PHASE1_WINDOW_S: Final = 3600" in CONST_SRC
    assert "NM_REPEAT_PHASE2_S: Final = 1800" in CONST_SRC
    assert "NM_REPEAT_DAILY_AFTER_S: Final = 86400" in CONST_SRC


def test_fix2_ladder_kill_switch_documented():
    assert "PHASE1_WINDOW_S == 0" in CONST_SRC


def test_fix2_interval_helper_gates_life_safety_first():
    """Life-safety cadence is unchanged — the ladder must NOT apply to
    life-safety hazards (safety contract preserved)."""
    tree = ast.parse(NM_SRC)
    body = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_repeat_interval_for_active_alert"
        ):
            body = ast.get_source_segment(NM_SRC, node)
            break
    assert body is not None
    # Life-safety branch appears BEFORE the ladder in the CODE body
    # (strip the docstring first — it names identifiers in prose order).
    code_only = body.split('"""', 2)[-1]
    ls_idx = code_only.find("return NM_REPEAT_INTERVAL_LIFE_SAFETY")
    ladder_idx = code_only.find("NM_REPEAT_PHASE1_WINDOW_S")
    assert 0 < ls_idx < ladder_idx, "life-safety must gate before ladder"
    # Kill-switch → legacy flat cadence.
    assert "NM_REPEAT_INTERVAL_NON_LIFE_SAFETY" in body
    # Ladder returns phase intervals.
    assert "NM_REPEAT_PHASE1_S" in body
    assert "NM_REPEAT_PHASE2_S" in body
    # Daily bucket = 86400.
    assert "86400" in body


def test_fix2_phase_boundaries_are_correct():
    """Verify the ladder boundaries — this is the functional intent."""
    # Simulate the pure decision by loading the helper into a namespace.
    src = NM_SRC
    tree = ast.parse(src)
    fn_src = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_repeat_interval_for_active_alert"
        ):
            fn_src = ast.get_source_segment(src, node)
            break
    assert fn_src is not None

    # Load consts.
    ns: dict = {}
    exec(
        "NM_REPEAT_INTERVAL_LIFE_SAFETY=30\n"
        "NM_REPEAT_INTERVAL_NON_LIFE_SAFETY=300\n"
        "NM_REPEAT_PHASE1_S=300\n"
        "NM_REPEAT_PHASE1_WINDOW_S=3600\n"
        "NM_REPEAT_PHASE2_S=1800\n"
        "NM_REPEAT_DAILY_AFTER_S=86400\n",
        ns,
    )

    class _Fake:
        def __init__(self, hazard, age):
            self.hass = None
            self._active_alert_data = {"hazard_type": hazard}
            self._age = age

        def _unacked_critical_age_s(self):
            return self._age

    # Inject a `is_life_safety_hazard` stub matching the union helper.
    ns["is_life_safety_hazard"] = lambda hass, hz: hz in {
        "smoke", "fire", "carbon_monoxide",
        "water_leak", "flooding", "intruder", "freeze_risk",
    }
    exec(fn_src.replace("def _repeat_interval_for_active_alert(self)",
                        "def _repeat_interval_for_active_alert(self)"), ns)
    fn = ns["_repeat_interval_for_active_alert"]

    # Phase boundaries at non-life-safety.
    assert fn(_Fake("reserve_soc", 0)) == 300         # phase1
    assert fn(_Fake("reserve_soc", 3599)) == 300       # phase1 upper
    assert fn(_Fake("reserve_soc", 3600)) == 1800      # phase2 lower
    assert fn(_Fake("reserve_soc", 86399)) == 1800     # phase2 upper
    assert fn(_Fake("reserve_soc", 86400)) == 86400    # daily
    assert fn(_Fake("reserve_soc", 90 * 86400)) == 86400  # deep-daily
    # Life-safety cadence untouched.
    assert fn(_Fake("smoke", 100000)) == 30


def test_fix2_created_at_stamped_and_recovered_from_db():
    # _enter_alerting stamps created_at on active_alert_data.
    assert '"created_at": dt_util.utcnow().isoformat()' in NM_SRC
    # _recover_state_from_db pulls the DB row's timestamp as created_at.
    assert '"created_at": active.get("timestamp")' in NM_SRC


def test_fix2_diagnostics_expose_phase_and_age():
    assert '"unacked_critical_age_s"' in NM_SRC
    assert '"repeat_phase"' in NM_SRC


# ---------------------------------------------------------------------------
# FIX 3 — Write-verify severity split
# ---------------------------------------------------------------------------
def test_fix3_maybe_fire_nm_accepts_severity_default_critical():
    # Signature backward-compatible.
    assert 'severity: str = "critical",\n' in WV_SRC


def test_fix3_stuck_ladder_demotes_intermediate_to_high():
    # In the stuck-retry site, attempts < MAX pass severity="high"; final
    # falls through to "critical".
    idx = WV_SRC.find("pending_write_stuck_final")
    assert idx > 0
    snippet = WV_SRC[idx: idx + 800]
    assert 'severity=(' in snippet
    assert '"high"' in snippet
    assert 'attempt_no < CONF_PENDING_MAX_ATTEMPTS' in snippet
    assert '"critical"' in snippet


def test_fix3_standdown_stays_critical():
    # The standdown call uses default severity (critical).
    idx = WV_SRC.find('alert_type="pending_write_standdown"')
    assert idx > 0
    # Walk backwards to the enclosing _maybe_fire_nm call; the call should
    # NOT pass severity= (defaulting to critical).
    call_start = WV_SRC.rfind("self._maybe_fire_nm(", 0, idx)
    call_end = idx + len('alert_type="pending_write_standdown"')
    call_src = WV_SRC[call_start:call_end]
    assert "severity=" not in call_src


# ---------------------------------------------------------------------------
# FIX 4 — Ack audit row
# ---------------------------------------------------------------------------
def test_fix4_async_acknowledge_accepts_person_and_channel():
    assert "acked_by_person: str | None = None" in NM_SRC
    assert "acked_by_channel: str | None = None" in NM_SRC


def test_fix4_ack_audit_row_uses_emit_audit_row_with_ack_reason():
    # Snapshot pre-teardown so title/created_at survive.
    assert "_snap = dict(self._active_alert_data)" in NM_SRC
    # Reuses _emit_audit_row — NOT a new table.
    idx = NM_SRC.find("write an audit row for")
    assert idx > 0
    body = NM_SRC[idx: idx + 2500]
    assert "await self._emit_audit_row(" in body
    assert "route_reason=" in body
    assert '"ack_safe_word"' in body
    assert '"ack"' in body


def test_fix4_callers_thread_channel_label():
    # Service handler labels as "service".
    assert 'nm.async_acknowledge(acked_by_channel="service")' in INIT_SRC
    # Button labels as "button".
    assert 'nm.async_acknowledge(acked_by_channel="button")' in BUTTON_SRC
    # Companion action labels as "companion".
    assert 'acked_by_channel="companion"' in NM_SRC


# ---------------------------------------------------------------------------
# FIX 5 — Per-person safe words + security ack authority
# ---------------------------------------------------------------------------
def test_fix5_consts_and_hazard_family():
    assert 'CONF_NM_PERSON_SAFE_WORD: Final = "nm_person_safe_word"' in CONST_SRC
    assert (
        'CONF_NM_SECURITY_ACK_PERSONS: Final = "nm_security_ack_persons"'
        in CONST_SRC
    )
    # Family covers all four security-family hazard tokens.
    assert "NM_SECURITY_ACK_HAZARDS: Final = frozenset({" in CONST_SRC
    for tok in ("intruder", "security_state_change",
                "exterior_person", "envoy_write_verification"):
        assert f'"{tok}"' in CONST_SRC


def test_fix5_options_flow_surface_per_person_and_authority_list():
    # Per-person safe word appears in the per-person step schema + payload.
    assert "CONF_NM_PERSON_SAFE_WORD" in CFG_SRC
    # Ack authority list appears in the quiet-hours (CM-level) step.
    assert "CONF_NM_SECURITY_ACK_PERSONS" in CFG_SRC


def test_fix5_match_safe_word_prefers_personal_then_global():
    # Personal matches → source "personal".
    assert 'return (True, "personal")' in NM_SRC
    # Global fallback → source "global".
    assert 'return (True, "global")' in NM_SRC
    # Legacy 4-char minimum enforced.
    assert "len(text_l) < 4" in NM_SRC


def test_fix5_authority_gate_defaults_to_first_tracked_person_when_list_empty():
    """Empty CONF_NM_SECURITY_ACK_PERSONS → default = first CONF_NM_PERSONS entry."""
    tree = ast.parse(NM_SRC)
    body = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_is_authorized_to_ack"
        ):
            body = ast.get_source_segment(NM_SRC, node)
            break
    assert body is not None
    assert "NM_SECURITY_ACK_HAZARDS" in body
    assert "CONF_NM_SECURITY_ACK_PERSONS" in body
    assert "CONF_NM_PERSONS" in body
    assert '"unauthorized_security"' in body
    assert '"authorized_security"' in body
    assert '"any"' in body


def test_fix5_inbound_unauthorized_ack_polite_reply_does_not_ack():
    """The polite-reply branch must NOT call async_acknowledge — the
    repeat keeps running."""
    tree = ast.parse(NM_SRC)
    body = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "_process_inbound_reply"
        ):
            body = ast.get_source_segment(NM_SRC, node)
            break
    assert body is not None
    # The unauthorized branch: polite text + no async_acknowledge call
    # BEFORE the early-return.
    unauth_idx = body.find("needs an authorized person to ack")
    assert unauth_idx > 0
    # Between the "if not allowed:" gate and the return, no ack call.
    gate_idx = body.rfind("if not allowed:", 0, unauth_idx)
    ret_idx = body.find("return response", unauth_idx)
    between = body[gate_idx:ret_idx]
    assert "async_acknowledge" not in between
    # Structured warning log for the denied ack.
    assert "NM ack DENIED" in between


# ---------------------------------------------------------------------------
# Mutation-anchored assertion (post-#62 standard): each fix has one
# named source anchor that, if deleted, MUST cause a test in this file
# to go RED. The dispositions in the cycle report cite these anchors.
# ---------------------------------------------------------------------------
_MUTATION_ANCHORS = {
    "FIX1_KILL_GUARD": ("switch.py", "if max_age > 0:"),
    "FIX1_ONE_SHOT_NOTIFY": (
        "switch.py",
        "NM messaging suppression NOT restored on startup",
    ),
    "FIX2_LADDER_PHASE1": (
        "domain_coordinators/notification_manager.py",
        "return int(NM_REPEAT_PHASE1_S)",
    ),
    "FIX2_LADDER_DAILY": (
        "domain_coordinators/notification_manager.py",
        "return 86400",
    ),
    "FIX2_CREATED_AT_STAMP": (
        "domain_coordinators/notification_manager.py",
        '"created_at": dt_util.utcnow().isoformat()',
    ),
    "FIX3_STUCK_SEVERITY_HIGH": (
        "domain_coordinators/energy_write_verify.py",
        '"high"',
    ),
    "FIX4_AUDIT_EMIT": (
        "domain_coordinators/notification_manager.py",
        "await self._emit_audit_row(",
    ),
    "FIX5_AUTHORITY_DENIAL": (
        "domain_coordinators/notification_manager.py",
        '"unauthorized_security"',
    ),
    "FIX5_PERSONAL_MATCH": (
        "domain_coordinators/notification_manager.py",
        'return (True, "personal")',
    ),
}


def test_mutation_anchor_strings_present():
    """Smoke check (C-MED-1 rename): assert every documented mutation
    anchor string exists in its source file. This is NOT proof of
    load-bearing behavior — string presence alone cannot show that a
    site is actually exercised. The behavioral tests above
    (``test_fix2_phase_boundaries_are_correct``,
    ``test_fix5_authority_gate_behavior``,
    ``test_fix5_match_safe_word_behavior``) are the proof; this test
    only guards against silent renames that would break the cycle's
    documented mutation exercise."""
    for name, (rel, needle) in _MUTATION_ANCHORS.items():
        src = _read(f"custom_components/universal_room_automation/{rel}")
        assert needle in src, (
            f"Mutation anchor {name} missing needle {needle!r} in {rel}"
        )


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): C-HIGH-1 — behavioral authority gate
# ---------------------------------------------------------------------------
def _load_fn(src: str, name: str, *, is_async: bool = False):
    """Extract a top-level def/async-def source segment by name."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            (is_async and isinstance(node, ast.AsyncFunctionDef))
            or (not is_async and isinstance(node, ast.FunctionDef))
        ) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


def test_fix5_authority_gate_behavior():
    """C-HIGH-1: exec _is_authorized_to_ack into a namespace and assert
    the four functional contracts. MUST go red under mutation
    ``return (True, "any")`` — verified out-of-band per fix-up protocol."""
    fn_src = _load_fn(NM_SRC, "_is_authorized_to_ack")
    assert fn_src is not None

    ns: dict = {
        "NM_SECURITY_ACK_HAZARDS": frozenset({
            "intruder", "security_state_change",
            "exterior_person", "envoy_write_verification",
        }),
        "CONF_NM_SECURITY_ACK_PERSONS": "nm_security_ack_persons",
        "CONF_NM_PERSONS": "nm_persons",
        "CONF_NM_PERSON_ENTITY": "entity_id",
    }
    # De-indent so the def parses as a top-level function.
    import textwrap
    exec(textwrap.dedent(fn_src), ns)
    fn = ns["_is_authorized_to_ack"]

    class _Fake:
        def __init__(self, config):
            self._config = config

    # (a) unauthorized security hazard
    f_a = _Fake({
        "nm_security_ack_persons": ["alice"],
        "nm_persons": [{"entity_id": "alice"}],
    })
    assert fn(f_a, "bob", "intruder") == (False, "unauthorized_security")

    # (b) authorized security hazard
    assert fn(f_a, "alice", "intruder") == (True, "authorized_security")

    # (c) non-security hazard: any person allowed
    assert fn(f_a, "bob", "reserve_soc") == (True, "any")

    # (d) empty allow-list falls back to persons[0]
    f_d = _Fake({
        "nm_security_ack_persons": [],
        "nm_persons": [{"entity_id": "carol"}, {"entity_id": "dave"}],
    })
    assert fn(f_d, "carol", "intruder") == (True, "authorized_security")
    assert fn(f_d, "dave", "intruder") == (False, "unauthorized_security")


def test_fix5_match_safe_word_behavior():
    """C-HIGH-2: exec _match_safe_word into a namespace with a stubbed
    personal-word lookup. MUST go red under mutation
    ``return (True, "personal")`` at the top — verified out-of-band."""
    fn_src = _load_fn(NM_SRC, "_match_safe_word")
    assert fn_src is not None

    ns: dict = {"CONF_NM_SAFE_WORD": "nm_safe_word"}
    import textwrap
    exec(textwrap.dedent(fn_src), ns)
    fn = ns["_match_safe_word"]

    class _Fake:
        def __init__(self, personal_by_person, global_word):
            self._personal = personal_by_person
            self._config = {"nm_safe_word": global_word}

        def _get_person_safe_word(self, person_id):
            return self._personal.get(person_id, "")

    # No global, no personal — no match.
    f = _Fake({"alice": ""}, "")
    assert fn(f, "gargle", "alice") == (False, "")

    # Personal match beats global.
    f = _Fake({"alice": "peachtree"}, "orangeblossom")
    assert fn(f, "peachtree", "alice") == (True, "personal")

    # Global fallback when no personal is set.
    f = _Fake({"alice": ""}, "orangeblossom")
    assert fn(f, "orangeblossom", "alice") == (True, "global")

    # < 4 char guard.
    f = _Fake({"alice": "abc"}, "abc")
    assert fn(f, "abc", "alice") == (False, "")

    # Person A cannot auth with person B's personal word
    # (unless it also happens to be the global — here it does not).
    f = _Fake({"alice": "peachtree", "bob": "figleaf"}, "")
    assert fn(f, "figleaf", "alice") == (False, "")
    assert fn(f, "figleaf", "bob") == (True, "personal")


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): C-MED-2 — companion trusted path in inbound reply
# ---------------------------------------------------------------------------
def test_companion_ack_bypasses_security_authority_gate():
    """Companion-channel ack overrides the security-authority gate.
    Denied-branch text ("needs an authorized person to ack") must NOT
    be reachable when channel == 'companion'."""
    fn_src = _load_fn(NM_SRC, "_process_inbound_reply", is_async=True)
    assert fn_src is not None
    # The override must apply BEFORE the denial branch.
    override_idx = fn_src.find('if channel == "companion":')
    deny_idx = fn_src.find("needs an authorized person to ack")
    assert 0 < override_idx < deny_idx, (
        "companion trusted override must precede the denial branch"
    )
    # And it sets the authority reason.
    between = fn_src[override_idx:deny_idx]
    assert 'auth_reason = "companion_trusted"' in between
    assert "allowed = True" in between
    # Unresolvable inbound sender is still denied — the override only
    # triggers on the companion channel; other channels with person_id=None
    # fall through to _is_authorized_to_ack which returns unauthorized.
    assert 'return (False, "unauthorized_security")' in NM_SRC


def test_companion_ack_records_companion_user_person():
    # The direct ACKNOWLEDGE_URA companion action stamps person + authority.
    assert 'acked_by_person="companion_user"' in NM_SRC
    assert 'authority_reason="companion_trusted"' in NM_SRC


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): MED-A3 — switch attribute round-trip
# ---------------------------------------------------------------------------
def test_med_a3_switch_persists_and_restores_suppressed_since():
    # Attribute exposed via extra_state_attributes.
    assert '"suppressed_since": self._suppressed_since_attr' in SWITCH_SRC
    # Set on turn_on, cleared on turn_off.
    assert "self._suppressed_since_attr = _dtu.utcnow().isoformat()" in SWITCH_SRC
    assert "self._suppressed_since_attr = None" in SWITCH_SRC
    # Restored from last_state.attributes.
    assert 'attrs.get("suppressed_since")' in SWITCH_SRC
    # Wired into the stale gate (earliest-wins parse branch).
    assert "getattr(self, \"_suppressed_since_attr\", None)" in SWITCH_SRC


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): HIGH-A1 — toggle clears restore-pending + cancels sync
# ---------------------------------------------------------------------------
def test_high_a1_toggle_clears_restore_pending_and_cancels_pending_sync():
    # Both async_turn_on and async_turn_off must set _restore_pending=False
    # BEFORE mutating _is_on / calling NM, and cancel any pending
    # _sync_unsub timer so a deferred restore-sync can't fire the age
    # gate against a fresh toggle.
    tree = ast.parse(SWITCH_SRC)
    for name in ("async_turn_on", "async_turn_off"):
        body = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name == name
            ):
                seg = ast.get_source_segment(SWITCH_SRC, node)
                if "async_suppress_messaging" in seg or "async_resume_messaging" in seg:
                    body = seg
                    break
        assert body is not None, f"{name} not found in NMMessagingSuppressSwitch"
        rp_idx = body.find("self._restore_pending = False")
        cancel_idx = body.find("self._sync_unsub = None")
        is_on_idx = body.find("self._is_on")
        # Restore-clear must appear before is_on flip.
        assert 0 < rp_idx < is_on_idx, (
            f"{name}: _restore_pending clear must precede _is_on flip"
        )
        # Cancel must appear (in the same body).
        assert cancel_idx > 0, f"{name}: pending sync cancel missing"


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): HIGH-A2(b) — init WARNING when ack list empty
# ---------------------------------------------------------------------------
def test_high_a2b_init_warning_names_fallback_person():
    # Text lives in async_setup NM path.
    assert (
        "NM security-alert ack authority defaulting" in NM_SRC
    )
    assert "configure nm_security_ack_persons" in NM_SRC


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): LOW-A7 — safe-word source stamped in ack audit row
# ---------------------------------------------------------------------------
def test_low_a7_ack_audit_row_encodes_safe_word_source_and_authority():
    # async_acknowledge signature accepts the two new fields.
    assert "safe_word_source: str | None = None" in NM_SRC
    assert "authority_reason: str | None = None" in NM_SRC
    # And they compose into route_reason.
    assert 'f":{safe_word_source}"' in NM_SRC
    assert 'f":{authority_reason}"' in NM_SRC


# ---------------------------------------------------------------------------
# Fix-up (2026-08-03): LOW-A5 — tz-aware coercion in age helper
# ---------------------------------------------------------------------------
def test_low_a5_unacked_age_helper_uses_parse_datetime_and_tz_coerce():
    fn_src = _load_fn(NM_SRC, "_unacked_critical_age_s")
    assert fn_src is not None
    assert "parse_datetime" in fn_src
    assert "tzinfo is None" in fn_src
    assert "dt_util.UTC" in fn_src or "timezone.utc" in fn_src
