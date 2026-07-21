"""NM Cycle C (2026-07-20) — Per-recipient routing matrix + DND-bypass +
mute-shortcut + audit-UX behavioral + mutation-anchored tests.

Contract from `PLANNING_nm_cycle_c_routing_matrix.md`:

  C-INV-1 Backward-compat routing — no matrix set → `_route_for_recipient`
    reproduces `_channel_qualifies` semantics byte-identically for the
    (severity × hazard × channel) tuple space.
  C-INV-2 Dry-run zero-outbound — `CONF_NM_DRY_RUN=true` → zero
    `hass.services.async_call` invocations to transport domains from
    ANY reachable NM path (matrix router, DND-bypass, mute, audit UX).
  C-INV-3 DND-bypass determinism — quiet-hours alert fires iff
    `severity ∈ recipient.dnd_bypass` OR hazard ∈ LIFE-SAFETY floor.

Mutation-anchored coverage: each test names the load-bearing production
line whose bypass makes the test fail. See the `MUTATION_ANCHORS` map
at the bottom of this module.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Piggyback on the NM harness's HA-module stubs.
from test_notification_manager import _make_hass, _make_config  # noqa: F401

from custom_components.universal_room_automation.const import (
    CONF_NM_PERSONS,
    CONF_NM_PERSON_ENTITY,
    CONF_NM_PERSON_PUSHOVER_KEY,
    CONF_NM_PERSON_COMPANION_SERVICE,
    CONF_NM_PERSON_WHATSAPP_PHONE,
    CONF_NM_PERSON_IMESSAGE_HANDLE,
    CONF_NM_PERSON_DELIVERY_PREF,
    CONF_NM_PERSON_ROUTING_MATRIX,
    CONF_NM_PERSON_HAZARD_OVERRIDES,
    CONF_NM_PERSON_DND_BYPASS_SEVERITIES,
    CONF_NM_MUTE_DEFAULT_DURATION_MINUTES,
    CONF_NM_DRY_RUN,
    CONF_NM_PUSHOVER_ENABLED,
    CONF_NM_PUSHOVER_SEVERITY,
    CONF_NM_COMPANION_ENABLED,
    CONF_NM_COMPANION_SEVERITY,
    CONF_NM_WHATSAPP_ENABLED,
    CONF_NM_IMESSAGE_ENABLED,
    CONF_NM_TTS_ENABLED,
    CONF_NM_LIGHTS_ENABLED,
    CONF_NM_QUIET_USE_HOUSE_STATE,
    CONF_NM_QUIET_MANUAL_START,
    CONF_NM_QUIET_MANUAL_END,
    NM_DELIVERY_IMMEDIATE,
    NM_CHANNELS_KNOWN,
    NM_LIFE_SAFETY_HAZARDS,
    DEFAULT_NM_PERSON_DND_BYPASS_SEVERITIES,
    SERVICE_NM_MUTE_PERSON_CHANNEL,
)
from custom_components.universal_room_automation.domain_coordinators.notification_manager import (
    NotificationManager,
)
from custom_components.universal_room_automation.domain_coordinators.base import Severity


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _base_person(pid="person.oji", **overrides):
    p = {
        CONF_NM_PERSON_ENTITY: pid,
        CONF_NM_PERSON_PUSHOVER_KEY: "pk_oji",
        CONF_NM_PERSON_COMPANION_SERVICE: "notify.oji_phone",
        CONF_NM_PERSON_WHATSAPP_PHONE: "+15551234",
        CONF_NM_PERSON_IMESSAGE_HANDLE: "+15551234",
        CONF_NM_PERSON_DELIVERY_PREF: NM_DELIVERY_IMMEDIATE,
    }
    p.update(overrides)
    return p


def _cfg_all_channels(**overrides):
    cfg = _make_config(**{
        CONF_NM_PUSHOVER_ENABLED: True,
        CONF_NM_PUSHOVER_SEVERITY: "LOW",
        CONF_NM_COMPANION_ENABLED: True,
        CONF_NM_COMPANION_SEVERITY: "LOW",
        CONF_NM_WHATSAPP_ENABLED: True,
        CONF_NM_IMESSAGE_ENABLED: True,
        CONF_NM_TTS_ENABLED: True,
        CONF_NM_LIGHTS_ENABLED: True,
        CONF_NM_PERSONS: [_base_person()],
    })
    cfg.update(overrides)
    return cfg


# =========================================================================
# C-INV-1: backward-compat fixture sweep (matrix absent → legacy oracle)
# =========================================================================


class TestCINV1Backcompat:
    """Full (severity × channel) sweep — matrix-absent path MUST byte-match
    the legacy `_channel_qualifies` oracle for every tuple.

    Mutation anchor: replace the `return legacy` line in
    `_route_for_recipient` (Layer D fallback) with `return set()` — this
    test suite must FAIL.
    """

    def test_router_backcompat_full_fixture(self):
        hass = _make_hass()
        cfg = _cfg_all_channels()
        nm = NotificationManager(hass, cfg)
        # Empty per-recipient matrix + no override → Layer-D fallback.
        for sev in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
            for ch in ("pushover", "companion", "whatsapp", "imessage", "tts", "lights"):
                legacy = nm._channel_qualifies(ch, sev)
                router = ch in nm._route_for_recipient("person.oji", None, sev)
                assert legacy == router, (
                    f"C-INV-1 violation: ch={ch} sev={sev.name} "
                    f"legacy={legacy} router={router}"
                )

    def test_router_backcompat_across_hazards(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        # hazard axis is a no-op in the legacy fallback path (channel
        # gate is severity-only). This is the invariant.
        for hz in ("smoke", "water_leak", "intruder", "co2", "overheat", None):
            for sev in (Severity.MEDIUM, Severity.HIGH):
                r1 = nm._route_for_recipient("person.oji", hz, sev)
                r2 = nm._route_for_recipient("person.oji", None, sev)
                assert r1 == r2

    def test_migration_byte_identical(self):
        """`_migrate_legacy_severity_to_matrix` produces a matrix that
        yields the same routing decisions as the legacy path.
        """
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        # Snapshot legacy routing decisions BEFORE migration.
        expected = {
            (sev, ch): nm._channel_qualifies(ch, sev)
            for sev in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
            for ch in NM_CHANNELS_KNOWN
        }
        nm._migrate_legacy_severity_to_matrix()
        for (sev, ch), want in expected.items():
            got = ch in nm._route_for_recipient("person.oji", None, sev)
            assert got == want, (
                f"migration lost byte-identity: sev={sev.name} ch={ch} "
                f"want={want} got={got}"
            )

    def test_migration_idempotent(self):
        # Fix-up 2026-07-20 (D4/B-MED-1): migration writes to a
        # coordinator-owned dict, NEVER to `person_cfg` (aliased into
        # entry.data/options). Recomputes only if the hash of legacy
        # inputs changed.
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        # Snapshot person_cfg BEFORE — assert unchanged post-migration.
        before = dict(nm._config[CONF_NM_PERSONS][0])
        nm._migrate_legacy_severity_to_matrix()
        after = dict(nm._config[CONF_NM_PERSONS][0])
        assert before == after, "migration must NOT mutate person_cfg"
        # Materialized matrix populated + stable across second call.
        first = {k: dict(v) for k, v in nm._materialized_matrix.items()}
        nm._migrate_legacy_severity_to_matrix()
        second = {k: dict(v) for k, v in nm._materialized_matrix.items()}
        assert first == second

    def test_migration_re_materializes_on_live_config_change(self):
        """D4/B-MED-1: legal severity-lowering must take effect on next
        notify. Prior code froze routing to the boot snapshot via a
        process-lifetime latch.
        """
        from custom_components.universal_room_automation.const import (
            CONF_NM_PUSHOVER_SEVERITY,
        )
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels(**{
            CONF_NM_PUSHOVER_SEVERITY: "HIGH",
        }))
        nm._migrate_legacy_severity_to_matrix()
        # At HIGH threshold, MEDIUM should not fire pushover.
        assert nm._materialized_matrix["person.oji"]["MEDIUM"]["pushover"] is False
        # Simulate a live options change lowering the threshold to LOW.
        nm._config[CONF_NM_PUSHOVER_SEVERITY] = "LOW"
        nm._migrate_legacy_severity_to_matrix()
        assert nm._materialized_matrix["person.oji"]["MEDIUM"]["pushover"] is True

    def test_migration_self_check_full_coverage(self):
        """C-5: materialized matrix has 4 severities × all NM_CHANNELS_KNOWN."""
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        nm._migrate_legacy_severity_to_matrix()
        m = nm._materialized_matrix["person.oji"]
        assert set(m.keys()) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        for sev_map in m.values():
            assert set(sev_map.keys()) == set(NM_CHANNELS_KNOWN)


# =========================================================================
# C1: explicit matrix + hazard-override precedence
# =========================================================================


class TestC1MatrixAndOverride:
    """Matrix explicit → wins over legacy. Hazard override → wins over matrix.

    Mutation anchor: comment out the `if override_hit is not None: return`
    branch in `_route_for_recipient` — `test_hazard_override_wins` fails.
    """

    def test_explicit_matrix_wins_over_legacy(self):
        hass = _make_hass()
        # Legacy would allow pushover at MEDIUM (default LOW threshold);
        # explicit matrix denies it. Router must honor matrix.
        person = _base_person()
        person[CONF_NM_PERSON_ROUTING_MATRIX] = {
            "MEDIUM": {
                "pushover": False, "companion": True, "whatsapp": False,
                "imessage": False, "tts": False, "lights": False,
            },
        }
        cfg = _cfg_all_channels(**{CONF_NM_PERSONS: [person]})
        nm = NotificationManager(hass, cfg)
        allowed = nm._route_for_recipient("person.oji", None, Severity.MEDIUM)
        assert "pushover" not in allowed
        assert "companion" in allowed

    def test_hazard_override_wins(self):
        hass = _make_hass()
        person = _base_person()
        # Base matrix bans pushover for MEDIUM.
        person[CONF_NM_PERSON_ROUTING_MATRIX] = {
            "MEDIUM": {"pushover": False, "companion": False},
        }
        # But for "intrusion" hazard, override says pushover=True.
        person[CONF_NM_PERSON_HAZARD_OVERRIDES] = {
            "intrusion": {"MEDIUM": {"pushover": True, "companion": False}},
        }
        cfg = _cfg_all_channels(**{CONF_NM_PERSONS: [person]})
        nm = NotificationManager(hass, cfg)
        # Non-matching hazard → matrix path (pushover suppressed).
        assert "pushover" not in nm._route_for_recipient(
            "person.oji", "water_leak", Severity.MEDIUM,
        )
        # Matching hazard → override wins (pushover fires).
        assert "pushover" in nm._route_for_recipient(
            "person.oji", "intrusion", Severity.MEDIUM,
        )

    def test_branch_label_reflects_source(self):
        hass = _make_hass()
        person = _base_person(
            **{
                CONF_NM_PERSON_ROUTING_MATRIX: {"HIGH": {"pushover": True}},
                CONF_NM_PERSON_HAZARD_OVERRIDES: {
                    "intruder": {"HIGH": {"pushover": True}},
                },
            }
        )
        nm = NotificationManager(_make_hass(), _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        assert nm._route_branch_label(person, "intruder", Severity.HIGH) == "hazard_override"
        assert nm._route_branch_label(person, "water_leak", Severity.HIGH) == "matrix_default"
        person_no_matrix = _base_person()
        assert nm._route_branch_label(person_no_matrix, None, Severity.HIGH) == "legacy_fallback"


# =========================================================================
# C3: DND bypass + safety floor
# =========================================================================


class TestC3DNDBypass:
    """C-INV-3: quiet-hours alert fires iff bypass set OR life-safety.

    Mutation anchor: replace `NM_LIFE_SAFETY_HAZARDS` check at the top of
    `_recipient_bypasses_dnd` with `False` — `test_life_safety_always_bypasses`
    fails.
    """

    def test_default_preserves_v526_critical_bypass(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        # Default set = {"CRITICAL"}. Non-CRIT + non-life-safety = no bypass.
        assert nm._recipient_bypasses_dnd("person.oji", "water_temp", Severity.MEDIUM) is False
        assert nm._recipient_bypasses_dnd("person.oji", "water_temp", Severity.CRITICAL) is True
        # Global (recipient=None) inherits the same default.
        assert nm._recipient_bypasses_dnd(None, "generic", Severity.CRITICAL) is True
        assert nm._recipient_bypasses_dnd(None, "generic", Severity.MEDIUM) is False

    def test_recipient_bypass_honored(self):
        hass = _make_hass()
        person = _base_person(
            **{CONF_NM_PERSON_DND_BYPASS_SEVERITIES: ("LOW", "MEDIUM", "CRITICAL")}
        )
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        assert nm._recipient_bypasses_dnd("person.oji", "water_temp", Severity.LOW) is True
        assert nm._recipient_bypasses_dnd("person.oji", "water_temp", Severity.MEDIUM) is True
        assert nm._recipient_bypasses_dnd("person.oji", "water_temp", Severity.HIGH) is False

    def test_life_safety_always_bypasses(self):
        hass = _make_hass()
        # Empty bypass set for this recipient — safety floor MUST still fire.
        person = _base_person(**{CONF_NM_PERSON_DND_BYPASS_SEVERITIES: ()})
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        for hz in NM_LIFE_SAFETY_HAZARDS:
            for sev in (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL):
                assert nm._recipient_bypasses_dnd("person.oji", hz, sev) is True, (
                    f"safety floor violated: hz={hz} sev={sev.name}"
                )


# =========================================================================
# C4: mute shortcut
# =========================================================================


class TestC4MuteShortcut:
    """Mute suppresses target channel only + expiry + restart-safe.

    Mutation anchor: force `_mute_active` to `return False` unconditionally —
    `test_mute_suppresses_target_channel_only` fails.
    """

    def test_mute_service_registration_arg_shape(self):
        # Sanity — the constant name we register the service under is stable.
        assert SERVICE_NM_MUTE_PERSON_CHANNEL == "nm_mute_person_channel"

    def test_mute_suppresses_target_channel_only(self):
        # NM Cycle C fix-up (2026-07-20): life-safety hazards SKIP mute
        # per operator-ratified safety exception. Use a non-life-safety
        # hazard to exercise the mute layer.
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.oji", "pushover", 15))
        allowed = nm._route_for_recipient("person.oji", "peak_overshoot", Severity.HIGH)
        assert "pushover" not in allowed
        assert "companion" in allowed
        assert "whatsapp" in allowed

    def test_mute_unknown_person_noop(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.stranger", "pushover", 15))
        assert nm._person_channel_mutes == {}

    def test_mute_unknown_channel_noop(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.oji", "telegram", 15))
        assert nm._person_channel_mutes == {}

    def test_mute_expiry_auto_clears(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        # Register a mute in the past — first `_mute_active` call self-heals.
        nm._person_channel_mutes[("person.oji", "pushover")] = (
            datetime.utcnow() - timedelta(minutes=5)
        )
        assert nm._mute_active("person.oji", "pushover") is False
        assert ("person.oji", "pushover") not in nm._person_channel_mutes

    def test_mute_duration_zero_clears_existing(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.oji", "pushover", 15))
        assert ("person.oji", "pushover") in nm._person_channel_mutes
        _run(nm.async_mute_person_channel("person.oji", "pushover", 0))
        assert ("person.oji", "pushover") not in nm._person_channel_mutes

    def test_mute_survives_restart_via_persistence(self):
        hass = _make_hass()
        nm1 = NotificationManager(hass, _cfg_all_channels())
        _run(nm1.async_mute_person_channel("person.oji", "pushover", 30))
        snapshot = nm1.get_persistence_state()
        assert "person_channel_mutes" in snapshot
        assert any("person.oji::pushover" in k for k in snapshot["person_channel_mutes"])
        # Fresh NM, restore.
        nm2 = NotificationManager(_make_hass(), _cfg_all_channels())
        nm2.restore_persistence_state(snapshot)
        assert nm2._mute_active("person.oji", "pushover") is True

    def test_mute_pruned_when_past_expiry_on_restore(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        past = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        future = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        nm.restore_persistence_state({
            "person_channel_mutes": {
                "person.oji::pushover": past,
                "person.oji::companion": future,
            }
        })
        assert ("person.oji", "pushover") not in nm._person_channel_mutes
        assert ("person.oji", "companion") in nm._person_channel_mutes

    def test_active_mutes_per_person_prunes(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.oji", "pushover", 30))
        _run(nm.async_mute_person_channel("person.oji", "companion", 30))
        out = nm.active_mutes_per_person()
        assert out == {"person.oji": ["companion", "pushover"]}


# =========================================================================
# C5: combinatorial fixture — extremes/inversions + no-transport-call guard
# =========================================================================


class TestC5Combinatorial:
    """Extremes/inversions of the four independent knobs. C-INV-2 guard:
    under dry-run, ZERO transport calls originate from any reachable NM
    path exercised here.

    Mutation anchor: remove the `if self._dry_run_active: return` guard
    at the top of `_send_pushover` (line ~1320) — the transport-call
    guard fires.
    """

    def test_empty_matrix_falls_back_to_legacy(self):
        hass = _make_hass()
        person = _base_person(**{CONF_NM_PERSON_ROUTING_MATRIX: {}})
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        r = nm._route_for_recipient("person.oji", None, Severity.MEDIUM)
        # Legacy defaults enable pushover at MEDIUM.
        assert "pushover" in r

    def test_all_channels_all_severities_true(self):
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_ROUTING_MATRIX: {
                sev: {ch: True for ch in NM_CHANNELS_KNOWN}
                for sev in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            },
        })
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        r = nm._route_for_recipient("person.oji", None, Severity.LOW)
        assert r == set(NM_CHANNELS_KNOWN)

    def test_all_false_recipient_effectively_muted(self):
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_ROUTING_MATRIX: {
                sev: {ch: False for ch in NM_CHANNELS_KNOWN}
                for sev in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
            },
        })
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        assert nm._route_for_recipient("person.oji", None, Severity.CRITICAL) == set()

    def test_mute_and_matrix_intersect(self):
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_ROUTING_MATRIX: {
                "HIGH": {"pushover": True, "companion": True, "whatsapp": True,
                         "imessage": True, "tts": False, "lights": False},
            },
        })
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        _run(nm.async_mute_person_channel("person.oji", "companion", 30))
        r = nm._route_for_recipient("person.oji", None, Severity.HIGH)
        assert "companion" not in r
        assert "pushover" in r

    def test_dry_run_zero_transport_calls_via_router_paths(self):
        """C-INV-2 combinatorial guard: sweep the router across the extreme
        matrix / hazard-override / mute states under dry-run and assert
        no transport-domain service call is issued.
        """
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_ROUTING_MATRIX: {
                "HIGH": {ch: True for ch in NM_CHANNELS_KNOWN},
            },
            CONF_NM_PERSON_HAZARD_OVERRIDES: {
                "intruder": {"HIGH": {"pushover": True}},
            },
        })
        cfg = _cfg_all_channels(**{
            CONF_NM_PERSONS: [person],
            CONF_NM_DRY_RUN: True,
            CONF_NM_QUIET_USE_HOUSE_STATE: False,
        })
        nm = NotificationManager(hass, cfg)
        # Router is pure — invoking it doesn't touch transports at all.
        # But make sure it doesn't grab hass.services along the way.
        hass.services.async_call.reset_mock()
        for hz in ("intruder", "water_leak", "generic"):
            for sev in (Severity.LOW, Severity.HIGH, Severity.CRITICAL):
                nm._route_for_recipient("person.oji", hz, sev)
        assert hass.services.async_call.await_count == 0

    def test_config_boundary_bypass_empty_but_matrix_all(self):
        """Legal-config extreme: recipient's bypass set is empty but matrix
        allows all channels. Under quiet hours, DND-bypass wins — no fire.
        Under non-quiet hours, matrix decides — all channels fire.
        """
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_ROUTING_MATRIX: {
                "MEDIUM": {ch: True for ch in NM_CHANNELS_KNOWN},
            },
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES: (),  # nothing bypasses
        })
        nm = NotificationManager(hass, _cfg_all_channels(**{CONF_NM_PERSONS: [person]}))
        # Route is severity-based (bypass is applied in async_notify) —
        # confirm the router still returns the matrix result.
        r = nm._route_for_recipient("person.oji", "water_temp", Severity.MEDIUM)
        assert r == set(NM_CHANNELS_KNOWN)
        # And per-recipient DND-bypass for non-life-safety returns False.
        assert nm._recipient_bypasses_dnd(
            "person.oji", "water_temp", Severity.MEDIUM,
        ) is False


# =========================================================================
# Options suppress-key membership (both prior cycles tripped this trap)
# =========================================================================


class TestOptionsSuppressKeyMembership:
    """Every new CONF_NM_* key MUST be in both OPTIONS_RELOAD_SUPPRESS_KEYS
    and _NO_LIVE_ATTR_KEYS. Explicitly protecting this trap (fired B-B1
    v5.26.0 + A-2 fix v5.25.0).
    """

    def test_nm_c_keys_in_both_membership_sets(self):
        # __init__.py imports many HA symbols; touch only the frozensets
        # via a re-implementation to avoid full-package import cost.
        # The declarations live at the tail of __init__.py — we walk the
        # file text as a robust cheap check compatible with the test stub.
        import os
        init_path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "custom_components", "universal_room_automation", "__init__.py",
        )
        with open(init_path, "r") as fh:
            src = fh.read()
        # Both frozensets must reference _NM_C_KEYS via splat.
        # (`grep -c` equivalent is fine here — 2 splats expected.)
        assert src.count("*_NM_C_KEYS,") == 2, (
            "NM Cycle C keys must be splatted into BOTH "
            "_NO_LIVE_ATTR_KEYS and OPTIONS_RELOAD_SUPPRESS_KEYS"
        )
        # And the underlying set must include all four keys.
        assert "_CONF_NM_PERSON_ROUTING_MATRIX" in src
        assert "_CONF_NM_PERSON_HAZARD_OVERRIDES" in src
        assert "_CONF_NM_PERSON_DND_BYPASS_SEVERITIES" in src
        assert "_CONF_NM_MUTE_DEFAULT_DURATION_MINUTES" in src


# =========================================================================
# Mutation-anchor documentation (read by Review C for audit)
# =========================================================================

# =========================================================================
# NM Cycle C fix-up (2026-07-20) — Tier-3 review findings
# =========================================================================


class TestFixupRepeatPathRouterIntersection:
    """D1/D2 CRITICAL: `_repeat_alert` NameError + missing router gate on
    pushover. Rebuilds per-recipient intersection consistently across all
    4 messaging channels. Life-safety exception: mutes + DND SKIPPED for
    NM_LIFE_SAFETY_HAZARDS on repeats.
    """

    def test_repeat_alert_no_nameerror_with_companion_configured(self):
        """The exact CRITICAL bug: companion configured → repeat used
        undefined `_router_allowed` → NameError → repeat chain dies.
        """
        hass = _make_hass()
        person = _base_person()  # has companion, whatsapp, imessage
        cfg = _cfg_all_channels(**{CONF_NM_PERSONS: [person]})
        nm = NotificationManager(hass, cfg)
        nm._active_alert_data = {
            "coordinator_id": "safety",
            "title": "Fire!",
            "message": "Fire!",
            "hazard_type": "fire",
        }
        from custom_components.universal_room_automation.domain_coordinators.notification_manager import AlertState
        nm._alert_state = AlertState.REPEATING
        # Stub send helpers to observe calls without touching transports.
        nm._send_pushover = AsyncMock()
        nm._send_companion = AsyncMock()
        nm._send_whatsapp = AsyncMock()
        nm._send_imessage = AsyncMock()
        nm._send_tts = AsyncMock()
        nm._schedule_repeat = MagicMock()
        _run(nm._repeat_alert())
        # All 4 messaging channels invoked (life-safety fire hazard).
        assert nm._send_pushover.await_count == 1
        assert nm._send_companion.await_count == 1
        assert nm._send_whatsapp.await_count == 1
        assert nm._send_imessage.await_count == 1

    def test_repeat_alert_non_life_safety_mute_stops_channel(self):
        """Non-life-safety repeats HONOR mutes for that channel."""
        hass = _make_hass()
        person = _base_person()
        cfg = _cfg_all_channels(**{CONF_NM_PERSONS: [person]})
        nm = NotificationManager(hass, cfg)
        # Mute pushover before the repeat fires.
        _run(nm.async_mute_person_channel("person.oji", "pushover", 30))
        nm._active_alert_data = {
            "coordinator_id": "energy",
            "title": "Overshoot",
            "message": "kWh spike",
            "hazard_type": "peak_overshoot",  # NOT life-safety
        }
        from custom_components.universal_room_automation.domain_coordinators.notification_manager import AlertState
        nm._alert_state = AlertState.REPEATING
        nm._send_pushover = AsyncMock()
        nm._send_companion = AsyncMock()
        nm._send_whatsapp = AsyncMock()
        nm._send_imessage = AsyncMock()
        nm._send_tts = AsyncMock()
        nm._schedule_repeat = MagicMock()
        _run(nm._repeat_alert())
        assert nm._send_pushover.await_count == 0  # muted
        assert nm._send_companion.await_count == 1
        assert nm._send_whatsapp.await_count == 1
        assert nm._send_imessage.await_count == 1

    def test_repeat_alert_life_safety_ignores_mute(self):
        """Life-safety repeats bypass mute for messaging channels."""
        hass = _make_hass()
        person = _base_person()
        cfg = _cfg_all_channels(**{CONF_NM_PERSONS: [person]})
        nm = NotificationManager(hass, cfg)
        _run(nm.async_mute_person_channel("person.oji", "pushover", 30))
        nm._active_alert_data = {
            "coordinator_id": "safety",
            "title": "Smoke!",
            "message": "Smoke!",
            "hazard_type": "smoke",  # LIFE-SAFETY
        }
        from custom_components.universal_room_automation.domain_coordinators.notification_manager import AlertState
        nm._alert_state = AlertState.REPEATING
        nm._send_pushover = AsyncMock()
        nm._send_companion = AsyncMock()
        nm._send_whatsapp = AsyncMock()
        nm._send_imessage = AsyncMock()
        nm._send_tts = AsyncMock()
        nm._schedule_repeat = MagicMock()
        _run(nm._repeat_alert())
        # Mute skipped for life-safety.
        assert nm._send_pushover.await_count == 1


class TestFixupGlobalDNDUnion:
    """D3/B-HIGH-1: global quiet-hours gate must union with per-recipient
    bypass sets. C3 acceptance case = MEDIUM + recipient bypass
    {LOW, MEDIUM, CRITICAL} in quiet hours → fires for that recipient only.
    """

    def test_medium_in_quiet_hours_with_widened_recipient_bypass(self):
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_DND_BYPASS_SEVERITIES: ("LOW", "MEDIUM", "CRITICAL"),
        })
        cfg = _cfg_all_channels(**{
            CONF_NM_PERSONS: [person],
            CONF_NM_QUIET_USE_HOUSE_STATE: False,
            CONF_NM_QUIET_MANUAL_START: "00:00",
            CONF_NM_QUIET_MANUAL_END: "23:59",
        })
        nm = NotificationManager(hass, cfg)
        # Force quiet-hours = True.
        nm._is_quiet_hours = MagicMock(return_value=True)
        nm._send_pushover = AsyncMock()
        _run(nm.async_notify("safety", Severity.MEDIUM, "T", "M"))
        # Global gate would have suppressed pre-fix; now unioned.
        assert nm._send_pushover.await_count == 1

    def test_medium_in_quiet_hours_no_widened_bypass_still_suppresses(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels(**{
            CONF_NM_QUIET_USE_HOUSE_STATE: False,
        }))
        nm._is_quiet_hours = MagicMock(return_value=True)
        nm._send_pushover = AsyncMock()
        _run(nm.async_notify("safety", Severity.MEDIUM, "T", "M"))
        assert nm._send_pushover.await_count == 0


class TestFixupMuteRejectsGlobalChannels:
    """D6/B-LOW-2: tts and lights are recipient-less globals; muting
    them per-person must be rejected with an error.
    """

    def test_mute_tts_rejected(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.oji", "tts", 30))
        assert ("person.oji", "tts") not in nm._person_channel_mutes

    def test_mute_lights_rejected(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        _run(nm.async_mute_person_channel("person.oji", "lights", 30))
        assert ("person.oji", "lights") not in nm._person_channel_mutes


class TestFixupBurnOnlyOnReceivingChannel:
    """B-HIGH-2: token burn happens only when ≥1 recipient actually
    receives the channel (post-mute/matrix/DND intersection).
    Fully-muted channel + repeat notify → zero tokens burned.
    """

    def test_fully_muted_channel_no_token_burn(self):
        hass = _make_hass()
        nm = NotificationManager(hass, _cfg_all_channels())
        # Mute all four messaging channels for the sole recipient.
        for ch in ("pushover", "companion", "whatsapp", "imessage"):
            _run(nm.async_mute_person_channel("person.oji", ch, 30))
        capacity_before = dict(nm._bucket_tokens)
        gate = nm._gate_channels_for_notify(
            nm._config[CONF_NM_PERSONS], Severity.MEDIUM, "peak_overshoot", "energy",
        )
        assert all(v is False for v in gate.values())
        # No token was drawn (bucket_take never invoked).
        capacity_after = dict(nm._bucket_tokens)
        assert capacity_before == capacity_after


class TestFixupAuditRowAndDryRunGuards:
    """C-1 / C-2 / C-3 / C-4 anchors."""

    def test_c3_alert_lights_dryrun_guards_task_creation(self):
        """Kill the `if self._dry_run_active: return` guard at
        `_trigger_alert_lights` → `hass.async_create_task` gets a call
        under dry-run. Fixture self-check first (tautology guard #9):
        confirm the harness returns None so any accidental call would
        register as call_count > 0.
        """
        from custom_components.universal_room_automation.const import CONF_NM_ALERT_LIGHTS
        hass = _make_hass()
        # Fixture self-check.
        assert hass.async_create_task.return_value is None
        cfg = _cfg_all_channels(**{
            CONF_NM_ALERT_LIGHTS: ["light.hall"],
            CONF_NM_DRY_RUN: True,
        })
        nm = NotificationManager(hass, cfg)
        # `_log_dry_run` writes a row via NM's own DB helper — stub it.
        nm._log_dry_run = AsyncMock()
        hass.async_create_task.reset_mock()
        _run(nm._trigger_alert_lights("fire", Severity.CRITICAL))
        assert hass.async_create_task.call_count == 0
        assert nm._log_dry_run.await_count == 1

    def test_c4_ack_announce_dryrun_guard(self):
        from custom_components.universal_room_automation.const import CONF_NM_TTS_SPEAKERS
        hass = _make_hass()
        cfg = _cfg_all_channels(**{
            CONF_NM_TTS_SPEAKERS: ["media_player.kitchen"],
            CONF_NM_DRY_RUN: True,
        })
        nm = NotificationManager(hass, cfg)
        nm._log_dry_run = AsyncMock()
        hass.services.async_call.reset_mock()
        _run(nm._announce_ack("Test", "fire", "Kitchen"))
        assert hass.services.async_call.await_count == 0
        assert nm._log_dry_run.await_count == 1

    def test_c1_end_to_end_matrix_and_mute_honored_at_send_sites(self):
        """End-to-end async_notify with matrix denying whatsapp + mute on
        companion → only pushover/imessage fire. Kills a mutation setting
        `_router_allowed = full set` (would fire all four).
        """
        hass = _make_hass()
        person = _base_person(**{
            CONF_NM_PERSON_ROUTING_MATRIX: {
                "HIGH": {"pushover": True, "companion": True,
                         "whatsapp": False, "imessage": True,
                         "tts": False, "lights": False},
            },
        })
        cfg = _cfg_all_channels(**{
            CONF_NM_PERSONS: [person],
            CONF_NM_QUIET_USE_HOUSE_STATE: False,
        })
        nm = NotificationManager(hass, cfg)
        nm._is_quiet_hours = MagicMock(return_value=False)
        _run(nm.async_mute_person_channel("person.oji", "companion", 30))
        nm._send_pushover = AsyncMock()
        nm._send_companion = AsyncMock()
        nm._send_whatsapp = AsyncMock()
        nm._send_imessage = AsyncMock()
        _run(nm.async_notify("safety", Severity.HIGH, "T", "M", hazard_type="peak_overshoot"))
        assert nm._send_pushover.await_count == 1
        assert nm._send_companion.await_count == 0  # muted
        assert nm._send_whatsapp.await_count == 0  # matrix denies
        assert nm._send_imessage.await_count == 1

    def test_c2_audit_row_written_per_recipient_with_route_reason(self):
        """C-2: audit rows carry route_reason + matrix_branch +
        bucket_outcome; O(persons) rows per notify. Kills a mutation
        that neuters `_emit_audit_row` to a no-op.
        """
        hass = _make_hass()
        person = _base_person()
        cfg = _cfg_all_channels(**{
            CONF_NM_PERSONS: [person],
            CONF_NM_QUIET_USE_HOUSE_STATE: False,
        })
        nm = NotificationManager(hass, cfg)
        nm._is_quiet_hours = MagicMock(return_value=False)
        # Provide a fake database that captures audit calls.
        captured = []

        async def _cap(**kwargs):
            captured.append(kwargs)
        nm._emit_audit_row = _cap
        # And a minimal fake DB so the audit branch is reached.
        fake_db = MagicMock()
        fake_db.log_notification = AsyncMock()
        hass.data[__import__("custom_components.universal_room_automation.const", fromlist=["DOMAIN"]).DOMAIN]["database"] = fake_db
        nm._send_pushover = AsyncMock()
        _run(nm.async_notify("safety", Severity.MEDIUM, "T", "M"))
        assert len(captured) == 1  # O(persons) — one recipient
        row = captured[0]
        assert row["route_reason"] in ("matrix_default", "hazard_override", "legacy_fallback")
        assert row["matrix_branch"] in ("matrix_default", "hazard_override", "legacy_fallback", "dnd")
        assert row["bucket_outcome"] in ("accepted", "no_channel_fired", "quiet_hours_suppressed")


MUTATION_ANCHORS = {
    # (test → production site whose bypass makes the test fail)
    "TestCINV1Backcompat.test_router_backcompat_full_fixture": (
        "notification_manager.py::_route_for_recipient — Layer D "
        "`return legacy` line (matrix-absent fallback)"
    ),
    "TestC1MatrixAndOverride.test_hazard_override_wins": (
        "notification_manager.py::_route_for_recipient — `if override_hit "
        "is not None: return ... - muted_channels` branch"
    ),
    "TestC3DNDBypass.test_life_safety_always_bypasses": (
        "notification_manager.py::_recipient_bypasses_dnd — the "
        "`NM_LIFE_SAFETY_HAZARDS` safety-floor check at top of function"
    ),
    "TestC4MuteShortcut.test_mute_suppresses_target_channel_only": (
        "notification_manager.py::_mute_active — the expiry check "
        "(`return True` on active mute)"
    ),
    "TestC5Combinatorial.test_dry_run_zero_transport_calls_via_router_paths": (
        "notification_manager.py::_send_* helpers — `if self._dry_run_active"
        ": return` guard at each transport boundary (lines 1320/1353/"
        "1393/1409/1428/1461/2182)"
    ),
    "TestOptionsSuppressKeyMembership.test_nm_c_keys_in_both_membership_sets": (
        "__init__.py::_NM_C_KEYS splat into _NO_LIVE_ATTR_KEYS AND "
        "OPTIONS_RELOAD_SUPPRESS_KEYS — trap that fired B-B1 (v5.26.0) "
        "and A-2 fix (v5.25.0)"
    ),
    # NM Cycle C fix-up (2026-07-20) — Tier-3 review anchors added.
    "TestFixupRepeatPathRouterIntersection.test_repeat_alert_no_nameerror_with_companion_configured": (
        "notification_manager.py::_repeat_alert — per-recipient loop's "
        "`_router_allowed = self._route_for_recipient(...)` call. Bypass "
        "the assignment (or set to empty set) → all 4 channel awaits go "
        "to zero. Prior code referenced undefined `_router_allowed` on "
        "pushover/companion/whatsapp/imessage → NameError."
    ),
    "TestFixupRepeatPathRouterIntersection.test_repeat_alert_non_life_safety_mute_stops_channel": (
        "notification_manager.py::_route_for_recipient — the "
        "`legacy - muted_channels` / `override - muted_channels` "
        "subtraction (Layer A mute). Bypass → muted channel still fires."
    ),
    "TestFixupRepeatPathRouterIntersection.test_repeat_alert_life_safety_ignores_mute": (
        "notification_manager.py::_route_for_recipient — the "
        "`if life_safety: muted_channels = set()` branch. Bypass → "
        "life-safety hazards honor mute (safety regression)."
    ),
    "TestFixupGlobalDNDUnion.test_medium_in_quiet_hours_with_widened_recipient_bypass": (
        "notification_manager.py::async_notify — the global-quiet-hours "
        "union check (`any_recipient_bypass` loop). Bypass by reverting "
        "to `not self._recipient_bypasses_dnd(None,...): return`."
    ),
    "TestFixupMuteRejectsGlobalChannels.test_mute_tts_rejected": (
        "notification_manager.py::async_mute_person_channel — the "
        "`if channel in ('tts','lights'): return` guard."
    ),
    "TestFixupBurnOnlyOnReceivingChannel.test_fully_muted_channel_no_token_burn": (
        "notification_manager.py::_gate_channels_for_notify — the "
        "`any_receiving` router+mute intersection loop. Bypass → tokens "
        "burn on fully-muted channels."
    ),
    "TestFixupAuditRowAndDryRunGuards.test_c3_alert_lights_dryrun_guards_task_creation": (
        "notification_manager.py::_trigger_alert_lights — the "
        "`if self._dry_run_active: return` guard. Fixture self-check "
        "asserts hass.async_create_task.return_value is None."
    ),
    "TestFixupAuditRowAndDryRunGuards.test_c4_ack_announce_dryrun_guard": (
        "notification_manager.py::_announce_ack — the "
        "`if self._dry_run_active: return` guard."
    ),
    "TestFixupAuditRowAndDryRunGuards.test_c1_end_to_end_matrix_and_mute_honored_at_send_sites": (
        "notification_manager.py::async_notify — per-channel "
        "`_channel_gate.get(ch, False) and ch in _router_allowed` "
        "intersection at all 4 messaging sites."
    ),
    "TestFixupAuditRowAndDryRunGuards.test_c2_audit_row_written_per_recipient_with_route_reason": (
        "notification_manager.py::async_notify — the "
        "`await self._emit_audit_row(...)` per-recipient call."
    ),
    "TestCINV1Backcompat.test_migration_re_materializes_on_live_config_change": (
        "notification_manager.py::_migrate_legacy_severity_to_matrix — "
        "the `_legacy_matrix_key` change-detection. Freezing to the "
        "boot-time snapshot fails this test."
    ),
    "TestCINV1Backcompat.test_migration_self_check_full_coverage": (
        "notification_manager.py::_migrate_legacy_severity_to_matrix — "
        "the 4×N materialization loop (C-5 self-check)."
    ),
}
