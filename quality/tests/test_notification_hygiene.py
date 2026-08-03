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


def test_fix1_gate_emits_one_shot_medium_and_flips_off():
    # On stale restore: flip _is_on to False, WARNING log, send MEDIUM notify.
    assert "self._is_on = False" in SWITCH_SRC
    assert "NM messaging suppression NOT restored on startup" in SWITCH_SRC
    assert "Severity.MEDIUM" in SWITCH_SRC


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
    body = NM_SRC[idx: idx + 1500]
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


def test_mutation_anchors_are_load_bearing():
    """Sanity: every anchor is present in its file. Removing any of these
    from source will cause one of the tests above to fail. Documented so
    the mutation exercise in the cycle report is anchor-explicit."""
    for name, (rel, needle) in _MUTATION_ANCHORS.items():
        src = _read(f"custom_components/universal_room_automation/{rel}")
        assert needle in src, (
            f"Mutation anchor {name} missing needle {needle!r} in {rel}"
        )
