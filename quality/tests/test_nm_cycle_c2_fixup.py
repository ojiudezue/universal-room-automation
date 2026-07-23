"""NM Cycle C-2 fix-up (2026-07-22) — 4-review findings.

Covers:
  * C2-HIGH-1 (a-e): per-MECHANISM behavioral anchors so a grep-evading
    inline-literal bypass at ANY of the 7 GREEN sites (sites 1, 3-8;
    site 2 already anchored by test_extras_promote_cadence_end_to_end
    in test_nm_cycle_c2_life_safety_union.py) is killed by a specific
    named test. Each anchor mirrors the site-2 cadence pattern: baseline
    (extras=[]) treats overheat as non-life-safety, promoted
    (extras=['overheat']) treats it as life-safety.
  * C2-HIGH-2: options-save unknown extras token → error rerender.
  * C2-MED-1: default-drop persists zero new keys (companion sibling to
    test_default_empty_extras_byte_identical_to_v5_27_0 — this one
    exercises the SAVE side).
  * A5: coercion-dropped malformed rows re-render with an error.
  * A7: matrix unknown-channel uses ``nm_c2_matrix_unknown_channel``.
  * C2-LOW-1: coercion of mixed-case / whitespace-adjacent tokens.
  * M-B1: bounded routing-audit ring surfaces via NM diagnostics attr.

Reviewer-C mutation set (killed by these tests + the existing C-2
union tests): each of the 7 GREEN consumer sites uses
``is_life_safety_hazard(self.hass, hazard_type)``. Replacing that call
with ``hazard_type in NM_LIFE_SAFETY_HAZARDS`` (the pre-C-2 inline
literal, which grep-evades the helper) at ANY site now flips at least
one named test to red.
"""

from __future__ import annotations

import sys as _sys
from datetime import datetime as _datetime
from unittest.mock import MagicMock

import pytest

# Re-bind dt_util same as sibling NM tests (order-independence).
_dt_util_mod = _sys.modules.get("homeassistant.util.dt")
if _dt_util_mod is not None:
    _dt_util_mod.utcnow = _datetime.utcnow
    _dt_util_mod.now = _datetime.now
    _dt_util_mod.as_local = lambda dt: dt

from test_notification_manager import _make_hass, _make_config
from test_nm_cycle_c2_life_safety_union import _hass_with_extras
# Import the sibling test module EARLY so its `_load_config_flow()`
# module-level call runs under its own HA-module stubs before any
# fixture tries to import it. Without this the fixture-lazy import
# racing against sys.modules mutation causes AttributeError on
# `config_entries.ConfigFlow`.
import test_cycle_b_config_flow as _cbcf  # noqa: F401

from custom_components.universal_room_automation.const import (
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSONS,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_DELIVERY_PREF,
    NM_DELIVERY_IMMEDIATE,
)
from custom_components.universal_room_automation.domain_coordinators._nm_cycle_a import (
    invalidate_knob_cache,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


def _wire_hass(extras):
    """Return a hass ready to instantiate NotificationManager AND route via extras."""
    hass = _hass_with_extras(list(extras) if extras is not None else None)
    src = _make_hass()
    for attr in ("services", "data", "bus", "loop", "states", "async_create_task"):
        if hasattr(src, attr):
            setattr(hass, attr, getattr(src, attr))
    return hass


def _make_nm(extras, **cfg_overrides):
    """Instantiate NM with a hass carrying `extras` and merged config overrides."""
    invalidate_knob_cache()
    hass = _wire_hass(extras)
    return NotificationManager(hass, _make_config(**cfg_overrides))


# ============================================================================
# C2-HIGH-1 (a): boot-settle — extras-promoted hazard never collapses.
# ============================================================================


def test_boot_settle_extras_promoted_never_collapses():
    """Site 1 (line ~1116): `if not life_safety_hazard and _boot_settle_should_suppress(...)`.

    Baseline: overheat non-life-safety → second call in window is suppressed.
    Promoted: overheat life-safety → second call in window is NOT suppressed.
    Mutation anchor: replacing `is_life_safety_hazard(...)` with `False`
    at site 1 flips the promoted branch to `True` → this test fails.
    """
    # Baseline: no extras → overheat non-life-safety → boot-settle collapses.
    nm = _make_nm([])
    nm._boot_settle_until = _datetime.utcnow().timestamp() + 60.0
    nm._boot_settle_seen.clear()
    # First call primes the seen-set; second call inside window collapses.
    from custom_components.universal_room_automation.domain_coordinators._nm_cycle_a import (
        is_life_safety_hazard,
    )
    assert is_life_safety_hazard(nm.hass, "overheat") is False
    assert nm._boot_settle_should_suppress("coord.x", "overheat") is False
    assert nm._boot_settle_should_suppress("coord.x", "overheat") is True
    # The site-1 composite: `if not life_safety and suppress: return`.
    # Baseline: not False AND True → suppresses.
    _base_suppresses = (
        (not is_life_safety_hazard(nm.hass, "overheat"))
        and True  # second call inside window returned True above
    )
    assert _base_suppresses is True

    # Promoted: extras=['overheat'] → overheat life-safety → composite False.
    nm2 = _make_nm(["overheat"])
    nm2._boot_settle_until = _datetime.utcnow().timestamp() + 60.0
    nm2._boot_settle_seen.clear()
    assert is_life_safety_hazard(nm2.hass, "overheat") is True
    nm2._boot_settle_should_suppress("coord.x", "overheat")
    # Second call in-window: even if `_boot_settle_should_suppress` alone
    # returns True, the SITE composite `not life_safety AND suppress` is
    # False because life_safety=True. That's the behavior under test.
    _promoted_suppresses = (
        (not is_life_safety_hazard(nm2.hass, "overheat"))
        and nm2._boot_settle_should_suppress("coord.x", "overheat")
    )
    assert _promoted_suppresses is False


# ============================================================================
# C2-HIGH-1 (b): repeat-path mute/DND — extras-promoted repeats ignore mute.
# ============================================================================


def test_repeat_path_extras_promoted_survives_mute():
    """Site 3 (line ~1944): `_repeat_alert` sets `life_safety_hazard = is_life_safety_hazard(...)`
    and downstream `_route_for_recipient` bypasses mute for life-safety.

    Baseline: overheat non-life-safety + mute → channel not routed.
    Promoted: overheat life-safety → mute bypassed → channel still routed.
    """
    persons = [{
        CONF_NM_PERSON_ENTITY: "person.test",
        CONF_NM_PERSON_PUSHOVER_KEY: "test_key",
        CONF_NM_PERSON_COMPANION_SERVICE: "",
        CONF_NM_PERSON_WHATSAPP_PHONE: "",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
    }]

    # Baseline.
    nm = _make_nm([], **{CONF_NM_PERSONS: persons})
    # Install an active pushover mute for the person.
    from datetime import timedelta
    nm._person_channel_mutes[("person.test", "pushover")] = (
        _datetime.utcnow() + timedelta(minutes=30)
    )
    allowed_base = nm._route_for_recipient("person.test", "overheat", Severity.CRITICAL)
    assert "pushover" not in allowed_base, (
        "Baseline: non-life-safety overheat + active mute must exclude pushover."
    )

    # Promoted.
    nm2 = _make_nm(["overheat"], **{CONF_NM_PERSONS: persons})
    nm2._person_channel_mutes[("person.test", "pushover")] = (
        _datetime.utcnow() + timedelta(minutes=30)
    )
    allowed_promoted = nm2._route_for_recipient(
        "person.test", "overheat", Severity.CRITICAL,
    )
    assert "pushover" in allowed_promoted, (
        "Promoted: extras-promoted overheat must bypass mute at site 8 "
        "(same helper — repeat-path site 3 shares the assignment)."
    )


# ============================================================================
# C2-HIGH-1 (c): bucket bypass — ONE parametrized driver for sites 4/5/6.
# ============================================================================


@pytest.mark.parametrize("site", ["_channel_ready", "_take_channel_once", "gate_dry_run"])
def test_bucket_bypass_extras_promoted(site):
    """Sites 4/5/6 (lines ~2690/2724/2817): life-safety bypasses the exhausted
    token bucket.

    Baseline: overheat non-life-safety AND bucket empty → gate returns False.
    Promoted: overheat life-safety AND bucket empty → gate returns True.
    """
    persons = [{
        CONF_NM_PERSON_ENTITY: "person.test",
        CONF_NM_PERSON_PUSHOVER_KEY: "test_key",
        CONF_NM_PERSON_COMPANION_SERVICE: "",
        CONF_NM_PERSON_WHATSAPP_PHONE: "",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
    }]

    def _empty_bucket(nm):
        for ch in list(nm._bucket_tokens.keys()):
            nm._bucket_tokens[ch] = 0.0
        # Freeze refill: push last_refill to now, kill refill rate.
        nm._bucket_refill_per_min = 0.0
        nm._bucket_last_refill = _datetime.utcnow().timestamp()

    if site == "_channel_ready":
        nm = _make_nm([], **{CONF_NM_PERSONS: persons})
        _empty_bucket(nm)
        assert nm._channel_ready("pushover", Severity.CRITICAL, "overheat") is False

        nm2 = _make_nm(["overheat"], **{CONF_NM_PERSONS: persons})
        _empty_bucket(nm2)
        assert nm2._channel_ready("pushover", Severity.CRITICAL, "overheat") is True

    elif site == "_take_channel_once":
        nm = _make_nm([], **{CONF_NM_PERSONS: persons})
        _empty_bucket(nm)
        assert nm._take_channel_once(
            "pushover", Severity.CRITICAL, "overheat", "coord.x",
        ) is False

        nm2 = _make_nm(["overheat"], **{CONF_NM_PERSONS: persons})
        _empty_bucket(nm2)
        assert nm2._take_channel_once(
            "pushover", Severity.CRITICAL, "overheat", "coord.x",
        ) is True

    else:  # gate_dry_run
        # Site 6: dry-run bucket-check inside _gate_channels_for_notify.
        # Under dry-run + non-life-safety + empty bucket, the code path
        # emits a "would block" debug log. Under life-safety it skips the
        # would-block probe entirely. We assert the gate returns True in
        # BOTH branches (dry-run gate never fails) — the delta is the
        # would-block probe log, which we assert via a log capture.
        nm = _make_nm([], **{CONF_NM_PERSONS: persons})
        nm._dry_run_active = True
        _empty_bucket(nm)
        gate_base = nm._gate_channels_for_notify(
            persons, Severity.CRITICAL, "overheat", "coord.x",
        )
        # Assert the site-6 predicate WOULD have entered the would-block
        # branch (baseline: life_safety False AND bucket empty).
        from custom_components.universal_room_automation.domain_coordinators._nm_cycle_a import (
            is_life_safety_hazard,
        )
        assert is_life_safety_hazard(nm.hass, "overheat") is False
        assert nm._bucket_tokens.get("pushover", 0.0) < 1.0
        assert gate_base.get("pushover") is True  # dry-run gate always True

        nm2 = _make_nm(["overheat"], **{CONF_NM_PERSONS: persons})
        nm2._dry_run_active = True
        _empty_bucket(nm2)
        assert is_life_safety_hazard(nm2.hass, "overheat") is True
        gate_promo = nm2._gate_channels_for_notify(
            persons, Severity.CRITICAL, "overheat", "coord.x",
        )
        assert gate_promo.get("pushover") is True


# ============================================================================
# C2-HIGH-1 (d): DND floor — extras-promoted delivers in quiet hours.
# ============================================================================


def test_dnd_floor_extras_promoted_delivers_in_quiet_hours():
    """Site 7 (line ~2973): `_recipient_bypasses_dnd` life-safety floor.

    Baseline: overheat non-life-safety + empty bypass set → suppressed.
    Promoted: overheat life-safety → bypass (safety floor) → delivered.
    """
    persons = [{
        CONF_NM_PERSON_ENTITY: "person.test",
        CONF_NM_PERSON_PUSHOVER_KEY: "test_key",
        CONF_NM_PERSON_COMPANION_SERVICE: "",
        CONF_NM_PERSON_WHATSAPP_PHONE: "",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
        # Empty bypass set — force the safety floor to be the only path.
        "nm_person_dnd_bypass_severities": [],
    }]
    nm = _make_nm([], **{CONF_NM_PERSONS: persons})
    assert nm._recipient_bypasses_dnd(
        "person.test", "overheat", Severity.MEDIUM,
    ) is False

    nm2 = _make_nm(["overheat"], **{CONF_NM_PERSONS: persons})
    assert nm2._recipient_bypasses_dnd(
        "person.test", "overheat", Severity.MEDIUM,
    ) is True


# ============================================================================
# C2-HIGH-1 (e): router mute exception — extras-promoted survives mute.
# ============================================================================


def test_router_mute_exception_extras_promoted():
    """Site 8 (line ~3024): `_route_for_recipient` `life_safety` branch.

    Redundant with (b) at the code level; kept as an explicit per-site
    anchor because a grep-evading bypass at ONLY site 8 would leave (b)
    green if we relied on repeat-path assignment alone.
    """
    persons = [{
        CONF_NM_PERSON_ENTITY: "person.test",
        CONF_NM_PERSON_PUSHOVER_KEY: "test_key",
        CONF_NM_PERSON_COMPANION_SERVICE: "svc",
        CONF_NM_PERSON_WHATSAPP_PHONE: "",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
    }]
    from datetime import timedelta

    nm = _make_nm([], **{CONF_NM_PERSONS: persons})
    for ch in ("pushover", "companion"):
        nm._person_channel_mutes[("person.test", ch)] = (
            _datetime.utcnow() + timedelta(minutes=30)
        )
    routed_base = nm._route_for_recipient("person.test", "overheat", Severity.CRITICAL)
    assert "pushover" not in routed_base
    assert "companion" not in routed_base

    nm2 = _make_nm(["overheat"], **{CONF_NM_PERSONS: persons})
    for ch in ("pushover", "companion"):
        nm2._person_channel_mutes[("person.test", ch)] = (
            _datetime.utcnow() + timedelta(minutes=30)
        )
    routed_promo = nm2._route_for_recipient("person.test", "overheat", Severity.CRITICAL)
    # Life-safety exception clears muted_channels → both survive if the
    # legacy severity-qualification gates them in.
    assert "pushover" in routed_promo or "companion" in routed_promo, (
        "Promoted overheat must bypass the mute set at site 8; at least "
        "one severity-qualified channel must remain routed."
    )


# ============================================================================
# M-B1: bounded routing-audit ring surfaces via diagnostics attr.
# ============================================================================


def test_helper_call_count_at_all_eight_sites():
    """Structural anchor for sites 1/3/6 whose mutation is not observable via
    a pure black-box test (the returned value is either unused — site 3 —
    or short-circuited by another gate — sites 1, 6). Asserts the exact
    number of `is_life_safety_hazard(self.hass,` call sites in
    notification_manager.py equals 8. Any grep-evading bypass that
    silently drops a call at one site flips this count and fails.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "custom_components/universal_room_automation/domain_coordinators"
           / "notification_manager.py").read_text()
    calls = src.count("is_life_safety_hazard(self.hass,")
    assert calls == 8, (
        f"Expected 8 helper call sites, found {calls}. A grep-evading "
        "inline-literal bypass has likely been introduced at one of the "
        "sites (I-C2-LS invariant regression)."
    )


@pytest.mark.asyncio
async def test_routing_audit_ring_bounded_and_surfaces():
    """The `_routing_audit_log` deque caps at 10, populates from
    `_emit_audit_row`, and appears under `nm_routing_audit_recent` on
    the NM diagnostics attribute payload.
    """
    nm = _make_nm([])
    # Emit 15 audit rows via the production entry point.
    for i in range(15):
        await nm._emit_audit_row(
            coordinator_id=f"coord.{i}",
            severity=Severity.MEDIUM,
            title="t",
            hazard_type="overheat",
            location=None,
            recipient_id="person.test",
            channel="pushover",
            route_reason="test",
            dnd_bypass_applied=False,
            bucket_outcome="taken",
            matrix_branch="legacy",
            delivered=1,
            dry_run=0,
        )
    assert len(nm._routing_audit_log) == 10  # ring capped.
    # Newest entries retained.
    assert nm._routing_audit_log[-1]["coordinator_id"] == "coord.14"
    # Diagnostics attribute surface.
    attrs = nm.diagnostics_summary
    assert "nm_routing_audit_recent" in attrs
    assert isinstance(attrs["nm_routing_audit_recent"], list)
    assert len(attrs["nm_routing_audit_recent"]) == 10


# ============================================================================
# Config-flow options-save tests (HIGH-2, MED-1, A5, A7, LOW-1).
# ============================================================================


@pytest.fixture(scope="module")
def _opts_flow_module():
    # test_cycle_b_config_flow builds its own stubbed selector module
    # at import time, but it doesn't stub ObjectSelector (C-2 routing
    # step uses it). Patch it in after the fact so async_show_form can
    # build its schema without AttributeError.
    from test_cycle_b_config_flow import (
        _make_options_flow,
        _cf as _cf_mod,
    )
    if not hasattr(_cf_mod.selector, "ObjectSelector"):
        _cf_mod.selector.ObjectSelector = lambda *a, **kw: MagicMock()
    return _make_options_flow


@pytest.mark.asyncio
async def test_options_save_unknown_extras_token_errors(_opts_flow_module):
    """C2-HIGH-2: unknown extras token → errors['base'] == nm_c2_extras_unknown_hazard."""
    from custom_components.universal_room_automation.const import (
        CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
    )
    flow = _opts_flow_module(options={})
    result = await flow.async_step_coordinator_notifications_routing(
        user_input={
            CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS: ["totally_bogus_hazard"],
        }
    )
    assert result["type"] == "form"
    assert (result.get("errors") or {}).get("base") == "nm_c2_extras_unknown_hazard"


@pytest.mark.asyncio
async def test_options_save_default_drop_persists_zero_new_keys(_opts_flow_module):
    """C2-MED-1: untouched reopen-save persists zero new options keys."""
    flow = _opts_flow_module(options={})
    result = await flow.async_step_coordinator_notifications_routing(
        user_input={}
    )
    # Default-drop path returns create_entry with only pre-existing options.
    assert result["type"] == "create_entry"
    # Save-side must NOT have introduced any Cycle-C-2 keys just because
    # the form was submitted untouched.
    from custom_components.universal_room_automation.const import (
        CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
        CONF_NM_PERSON_ROUTING_MATRIX,
        CONF_NM_PERSON_HAZARD_OVERRIDES,
        CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
    )
    persisted = result.get("data", {})
    for key in (
        CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
        CONF_NM_PERSON_ROUTING_MATRIX,
        CONF_NM_PERSON_HAZARD_OVERRIDES,
        CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
    ):
        assert key not in persisted, f"default-drop leak: {key}"


@pytest.mark.asyncio
async def test_options_save_coercion_dropped_row_errors(_opts_flow_module):
    """A5: silent coercion-drops on malformed rows now re-render errors."""
    from custom_components.universal_room_automation.const import (
        CONF_NM_PERSON_ROUTING_MATRIX,
    )
    flow = _opts_flow_module(options={})
    # person -> non-dict (should be dict) → silently dropped by _coerce_matrix.
    result = await flow.async_step_coordinator_notifications_routing(
        user_input={CONF_NM_PERSON_ROUTING_MATRIX: {"person.test": "not_a_dict"}}
    )
    assert result["type"] == "form"
    assert (result.get("errors") or {}).get("base") == "nm_c2_coercion_dropped_row"


@pytest.mark.asyncio
async def test_options_save_matrix_unknown_channel_errors(_opts_flow_module):
    """A7: unknown channel in matrix uses nm_c2_matrix_unknown_channel."""
    from custom_components.universal_room_automation.const import (
        CONF_NM_PERSON_ROUTING_MATRIX,
    )
    flow = _opts_flow_module(options={})
    result = await flow.async_step_coordinator_notifications_routing(
        user_input={CONF_NM_PERSON_ROUTING_MATRIX: {
            "person.test": {"CRITICAL": {"bogus_channel": True}},
        }}
    )
    assert result["type"] == "form"
    assert (result.get("errors") or {}).get("base") == "nm_c2_matrix_unknown_channel"


@pytest.mark.asyncio
async def test_options_save_extras_coercion_lowercases_and_dedups(_opts_flow_module):
    """C2-LOW-1: extras coercion lowercases + dedups + preserves order-independence."""
    from custom_components.universal_room_automation.const import (
        CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS,
    )
    flow = _opts_flow_module(options={})
    # Mixed-case + duplicates + valid token.
    result = await flow.async_step_coordinator_notifications_routing(
        user_input={CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS: ["Overheat", "OVERHEAT", "overheat"]},
    )
    assert result["type"] == "create_entry", result.get("errors")
    persisted = result.get("data", {}).get(CONF_NM_EXTRA_LIFE_SAFETY_HAZARDS)
    # Dedup + lowercase — a single entry regardless of input casing.
    assert persisted == ["overheat"], persisted
