"""v4.5.20 — Periodic-closure swallow escalations.

The C audit (run after v4.5.17 NameError fix) identified 11 sites
across 6 files where `_LOGGER.debug(...)` in `except` blocks could
silently hide bugs in periodic closures. Mirroring v4.5.17 + v4.5.16,
this cycle escalates each to `_LOGGER.warning(..., exc_info=True)`
so the next hidden NameError-class bug surfaces immediately.

Sites escalated (per the audit findings):

HIGH (4 — exact v4.5.17 shape):
1. energy.py:_account_arbitrage_cycle/_refresh_arbitrage_status_cache
   inside _async_decision_cycle (same function as v4.5.17 fix)
2. energy.py:_refresh_arbitrage_status_cache outer try
3. manager.py:_execute_action NM routing dispatch
4. hvac_covers.py:update() cover intent check

MEDIUM (3 — observability gaps but recoverable):
5. manager.py:_log_decision DB write
6. energy.py:_update_power_profiles
7. energy.py:_get_house_avg_climate (was bare except: pass)

LOW (4 — cosmetic exc_info adds):
8. energy.py:_refresh_arbitrage_status_cache cycle_start parse
9. energy.py NM alert helper
10. hvac_override.py NM alert
11. security.py compliance scheduling
12. music_following.py anomaly baseline save

Tests are AST + source-grep regression guards. The behavior changes
are log-level only — no functional change to assert.
"""

import pytest


# ===========================================================================
# Source fixtures
# ===========================================================================


@pytest.fixture(scope="module")
def energy_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/energy.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def manager_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/manager.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_covers_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_covers.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_override_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_override.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def security_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/security.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def music_following_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/music_following.py"
    ) as f:
        return f.read()


# ===========================================================================
# HIGH escalations — pin specific sites
# ===========================================================================


def test_arbitrage_accounting_no_longer_debug_swallow(energy_src: str):
    """v4.5.17-shape site #1: arbitrage accounting in _async_decision_cycle.
    The pre-v4.5.20 line was `_LOGGER.debug("Arbitrage cycle accounting skipped: %s", exc)`.
    """
    assert (
        '_LOGGER.debug("Arbitrage cycle accounting skipped'
        not in energy_src
    ), (
        "v4.5.20 regression: arbitrage accounting debug-swallow returned. "
        "This site is in the SAME function the v4.5.17 NameError lived in."
    )
    # And the new shape must be present
    assert "Arbitrage cycle accounting skipped" in energy_src
    assert "savings sensors" in energy_src or "exc_info=True" in energy_src


def test_arbitrage_cache_refresh_no_longer_debug_swallow(energy_src: str):
    """Site #2: cache refresh outer try."""
    assert (
        '_LOGGER.debug("Arbitrage status cache refresh failed'
        not in energy_src
    )
    assert "Arbitrage status cache refresh failed" in energy_src


def test_nm_routing_no_longer_debug_swallow(manager_src: str):
    """Site #3: HIGH — central NM dispatch."""
    assert (
        '_LOGGER.debug("NM routing failed (non-fatal)")' not in manager_src
    ), "v4.5.20 regression: NM routing dispatch debug-swallow returned"
    # New shape includes coordinator + description context
    assert "NM routing failed for %s" in manager_src
    # And captures exc_info (was completely dropping the exception before)
    assert (
        "NM routing failed" in manager_src
        and "exc_info=True" in manager_src
    )


def test_hvac_covers_intent_check_no_longer_debug_swallow(
    hvac_covers_src: str,
):
    """Site #4: HVAC cover intent check — silent failure → all covers
    permanently skipped.
    """
    # Old line had "intent check failed for %s (%s) — "
    assert (
        '_LOGGER.debug(\n                            "HVAC Covers: intent check failed'
        not in hvac_covers_src
    )
    assert "intent check failed for %s" in hvac_covers_src


# ===========================================================================
# MEDIUM escalations
# ===========================================================================


def test_log_decision_no_longer_debug_swallow(manager_src: str):
    """Decision audit trail — silent failure dropped audit rows."""
    assert (
        '_LOGGER.debug(\n                "Failed to log decision for'
        not in manager_src
    )
    assert "Failed to log decision for %s" in manager_src
    assert "audit-trail row dropped" in manager_src


def test_power_profile_update_no_longer_debug_swallow(energy_src: str):
    """B4 L2 power profile learning silent failure."""
    assert '_LOGGER.debug("Power profile update error' not in energy_src
    assert "Power profile update error" in energy_src
    assert "B4 L2 learning skipped" in energy_src


def test_get_house_avg_climate_no_longer_bare_pass(energy_src: str):
    """The original bare `except: pass` — most invisible shape — now logs."""
    # Find the function and ensure no bare `except Exception: pass` directly
    func_start = energy_src.find("def _get_house_avg_climate(")
    assert func_start >= 0
    # Take a generous window
    func_end = energy_src.find("\n    def ", func_start + 100)
    body = energy_src[func_start:func_end if func_end > 0 else func_start + 3000]
    # Pre-v4.5.20 had `except Exception:\n            pass` — must be gone
    assert "except Exception:\n            pass" not in body, (
        "v4.5.20 regression: bare except-pass restored in _get_house_avg_climate"
    )
    # Should now log
    assert "_get_house_avg_climate iteration failed" in body or \
        "history snapshots will use None" in body


# ===========================================================================
# LOW escalations (cosmetic exc_info adds)
# ===========================================================================


def test_arbitrage_cycle_start_parse_no_longer_debug(energy_src: str):
    """Inner sub-step inside cache refresh."""
    assert (
        '_LOGGER.debug("cycle_start parse fell through' not in energy_src
    )
    assert "cycle_start parse fell through" in energy_src


def test_energy_nm_alert_no_longer_debug(energy_src: str):
    assert (
        '_LOGGER.debug("Energy: NM alert failed' not in energy_src
    )
    assert "Energy: NM alert failed (non-fatal)" in energy_src


def test_hvac_override_nm_alert_no_longer_debug(hvac_override_src: str):
    assert (
        '_LOGGER.debug("HVAC Override: NM alert failed'
        not in hvac_override_src
    )
    assert "HVAC Override: NM alert failed (non-fatal)" in hvac_override_src


def test_security_compliance_no_longer_debug(security_src: str):
    assert (
        '_LOGGER.debug(\n                        "Compliance check scheduling failed'
        not in security_src
    )
    assert "Compliance check scheduling failed for %s" in security_src


def test_music_following_baseline_save_no_longer_debug(
    music_following_src: str,
):
    assert (
        '_LOGGER.debug(\n                    "MusicFollowingCoordinator: failed to save anomaly baselines'
        not in music_following_src
    )
    assert "failed to save anomaly baselines" in music_following_src


# ===========================================================================
# All sites use exc_info=True (or equivalent traceback mechanism)
# ===========================================================================


def test_all_escalated_sites_capture_traceback(
    energy_src: str,
    manager_src: str,
    hvac_covers_src: str,
    hvac_override_src: str,
    security_src: str,
    music_following_src: str,
):
    """Every v4.5.20-escalated site must include `exc_info=True` so the
    next NameError-class bug surfaces with a traceback. Counts the
    occurrences as a smoke check.
    """
    # The 11 escalated sites each add a `exc_info=True` keyword. Sum
    # across all files — exact count depends on whether other unrelated
    # exc_info=True calls exist, so verify minimum thresholds per file
    # rather than exact totals.
    assert energy_src.count("exc_info=True") >= 6, (
        "energy.py should have ≥6 exc_info=True after v4.5.20 "
        "(arbitrage accounting, cache refresh outer + cycle_start "
        "inner, NM alert, power profiles, _get_house_avg_climate)"
    )
    assert manager_src.count("exc_info=True") >= 2, (
        "manager.py should have ≥2 exc_info=True after v4.5.20 "
        "(NM routing, decision log)"
    )
    assert hvac_covers_src.count("exc_info=True") >= 1
    assert hvac_override_src.count("exc_info=True") >= 1
    assert security_src.count("exc_info=True") >= 1
    assert music_following_src.count("exc_info=True") >= 1
