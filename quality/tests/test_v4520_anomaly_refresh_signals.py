"""v4.5.20 — Anomaly sensor refresh signals (Presence + MF).

Closes the v4.5.14 visibility gap. Before this cycle:
- `PresenceAnomalySensor` and `MusicFollowingAnomalySensor` had
  `extra_state_attributes` (per v4.5.14) but no `async_added_to_hass`
  subscription to any refresh signal
- Sensors refreshed only when HA naturally re-queried (not on every
  coordinator decision cycle)
- HVAC + Safety + Security already had this pattern; Presence + MF
  lagged because no `SIGNAL_PRESENCE_*` / `SIGNAL_MUSIC_FOLLOWING_*`
  constants existed

v4.5.20:
1. Adds two new signal constants in `signals.py`
2. `PresenceCoordinator._run_inference` dispatches at end of cycle
3. `MusicFollowingCoordinator._on_transfer_outcome` dispatches per
   transfer outcome (MF is event-driven — no periodic tick)
4. `PresenceAnomalySensor` + `MusicFollowingAnomalySensor` subscribe
   via `async_added_to_hass`

Tests are AST + source-grep regression guards. Behavior is tested
implicitly by HA's dispatcher framework — no custom harness needed.
"""

import pytest


@pytest.fixture(scope="module")
def signals_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/signals.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def presence_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/presence.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def mf_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/music_following.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def sensor_src() -> str:
    with open(
        "custom_components/universal_room_automation/sensor.py"
    ) as f:
        return f.read()


# ===========================================================================
# Signal constants exist
# ===========================================================================


def test_signals_defines_presence_entities_update(signals_src: str):
    assert (
        'SIGNAL_PRESENCE_ENTITIES_UPDATE: Final = "ura_presence_entities_update"'
        in signals_src
    )


def test_signals_defines_mf_entities_update(signals_src: str):
    assert (
        'SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE: Final = "ura_music_following_entities_update"'
        in signals_src
    )


def test_new_signal_names_do_not_collide_with_existing(signals_src: str):
    """Bug Class #32 prevention: the new signal string values must not
    overlap with any existing signal name. A collision would cause
    cross-coordinator listener cross-talk.
    """
    new_names = {
        "ura_presence_entities_update",
        "ura_music_following_entities_update",
    }
    # Count occurrences as strings — each new name should appear
    # exactly twice (constant definition + comment context isn't a
    # string literal). Tighten check: each appears in exactly one
    # constant-definition line.
    for name in new_names:
        occurrences = signals_src.count(f'"{name}"')
        assert occurrences == 1, (
            f"Signal name {name!r} appears {occurrences}x in signals.py — "
            "expected exactly 1 (the constant definition). A duplicate "
            "would suggest a collision with another signal."
        )


# ===========================================================================
# Presence coordinator dispatches the signal
# ===========================================================================


def test_presence_run_inference_dispatches_signal(presence_src: str):
    """_run_inference must end with an async_dispatcher_send call for
    the new SIGNAL_PRESENCE_ENTITIES_UPDATE signal.
    """
    # The dispatch must be present
    assert "SIGNAL_PRESENCE_ENTITIES_UPDATE" in presence_src
    # And invoked via async_dispatcher_send
    assert "async_dispatcher_send(self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE)" in presence_src


def test_presence_dispatch_after_check_zone_anomalies(presence_src: str):
    """The dispatch must come AFTER `await self._check_zone_anomalies()`
    in `_run_inference`. Pre-anomaly observation is too early.
    """
    cza_idx = presence_src.find("await self._check_zone_anomalies()")
    dispatch_idx = presence_src.find(
        "async_dispatcher_send(self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE)"
    )
    assert cza_idx >= 0 and dispatch_idx >= 0
    assert dispatch_idx > cza_idx, (
        "v4.5.20: dispatch must run AFTER _check_zone_anomalies so the "
        "sensor sees the post-cycle state of anomaly metrics."
    )


def test_presence_dispatch_has_exception_handling(presence_src: str):
    """The dispatch is non-critical to the inference cycle's primary
    work, so it should be wrapped in try/except + WARNING log to keep
    inference robust if dispatcher fires fail somehow.
    """
    # Find the dispatch
    idx = presence_src.find(
        "async_dispatcher_send(self.hass, SIGNAL_PRESENCE_ENTITIES_UPDATE)"
    )
    assert idx >= 0
    # Look backward for try:
    try_idx = presence_src.rfind("try:", 0, idx)
    # And forward for except:
    except_idx = presence_src.find("except", idx)
    assert try_idx > 0 and except_idx > idx
    # Window between try and except should contain the dispatch
    block = presence_src[try_idx:except_idx]
    assert "SIGNAL_PRESENCE_ENTITIES_UPDATE" in block


# ===========================================================================
# Music Following coordinator dispatches the signal
# ===========================================================================


def test_mf_on_transfer_outcome_dispatches_signal(mf_src: str):
    assert "SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE" in mf_src
    assert "async_dispatcher_send(" in mf_src
    # Specific call form
    assert (
        "async_dispatcher_send(\n                    self.hass, SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE"
        in mf_src
        or "async_dispatcher_send(self.hass, SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE)"
        in mf_src
    )


def test_mf_dispatch_inside_on_transfer_outcome(mf_src: str):
    """Dispatch must be inside `_on_transfer_outcome` — MF's natural
    decision point. Other entry points wouldn't be event-driven.
    """
    method_idx = mf_src.find("def _on_transfer_outcome(self)")
    dispatch_idx = mf_src.find("SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE")
    assert method_idx >= 0 and dispatch_idx >= 0
    # Find next method def after _on_transfer_outcome
    next_def = mf_src.find("\n    def ", method_idx + 100)
    next_async = mf_src.find("\n    async def ", method_idx + 100)
    candidates = [c for c in (next_def, next_async) if c > 0]
    method_end = min(candidates) if candidates else method_idx + 3000
    assert method_idx < dispatch_idx < method_end, (
        "v4.5.20: SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE dispatch must "
        "be inside _on_transfer_outcome (line ~168). Dispatching from "
        "another site would fire on the wrong cadence."
    )


# ===========================================================================
# Sensors subscribe to the new signals
# ===========================================================================


def test_presence_anomaly_sensor_subscribes(sensor_src: str):
    """PresenceAnomalySensor must define async_added_to_hass subscribing
    to SIGNAL_PRESENCE_ENTITIES_UPDATE.
    """
    class_start = sensor_src.find("class PresenceAnomalySensor(")
    assert class_start >= 0
    next_class = sensor_src.find("\nclass ", class_start + 1)
    body = sensor_src[class_start:next_class if next_class > 0 else class_start + 5000]
    assert "async def async_added_to_hass(self)" in body, (
        "PresenceAnomalySensor must define async_added_to_hass (v4.5.20 fix)."
    )
    assert "SIGNAL_PRESENCE_ENTITIES_UPDATE" in body
    assert "async_dispatcher_connect" in body
    assert "self.async_on_remove" in body, (
        "Subscription must be wrapped in async_on_remove for cleanup on "
        "entity removal — Bug Class #38 prevention pattern."
    )


def test_music_following_anomaly_sensor_subscribes(sensor_src: str):
    class_start = sensor_src.find("class MusicFollowingAnomalySensor(")
    assert class_start >= 0
    next_class = sensor_src.find("\nclass ", class_start + 1)
    body = sensor_src[class_start:next_class if next_class > 0 else class_start + 5000]
    assert "async def async_added_to_hass(self)" in body
    assert "SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE" in body
    assert "async_dispatcher_connect" in body
    assert "self.async_on_remove" in body


def test_stale_mf_anomaly_comment_removed(sensor_src: str):
    """The old comment that explicitly said no SIGNAL_MUSIC_FOLLOWING_*
    existed is now misleading. v4.5.20 must remove or rewrite it.
    """
    # The pre-v4.5.20 comment text
    stale_phrase = "no SIGNAL_MUSIC_FOLLOWING_ENTITIES_UPDATE exists"
    assert stale_phrase not in sensor_src, (
        "v4.5.20: stale comment about missing signal must be removed "
        "or rewritten (the signal now exists)."
    )


# ===========================================================================
# Import-resolves smoke check (Bug Class #34 + #32 prevention)
# ===========================================================================


# ===========================================================================
# DOMAIN NameError regression (Phase 2 of swallow-escalation discovery)
# ===========================================================================
# v4.5.19's swallow escalations surfaced a long-latent NameError in
# energy.py's arbitrage code path: two sites used bare `DOMAIN` but the
# file imports it as `_DOMAIN` at module level (line 30, for lambda
# closures). Every arbitrage decision cycle threw NameError silently.
# v4.5.20 bundles the fix: replace `DOMAIN` with `_DOMAIN` at both sites.


@pytest.fixture(scope="module")
def energy_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/energy.py"
    ) as f:
        return f.read()


def test_energy_module_imports_DOMAIN_as_underscore(energy_src: str):
    """Pin the existing convention: DOMAIN is imported as `_DOMAIN` at
    module scope. Catches a future refactor that drops the alias.
    """
    assert "from ..const import DOMAIN as _DOMAIN" in energy_src, (
        "energy.py must import DOMAIN as `_DOMAIN` at module level. "
        "If renamed, update all `_DOMAIN` references in arbitrage code."
    )


def test_account_arbitrage_cycle_uses_underscore_DOMAIN(energy_src: str):
    """Site 1: _account_arbitrage_cycle DB write. Must use `_DOMAIN`."""
    func_idx = energy_src.find("def _account_arbitrage_cycle(")
    assert func_idx >= 0
    next_def = energy_src.find("\n    def ", func_idx + 100)
    next_async = energy_src.find("\n    async def ", func_idx + 100)
    candidates = [c for c in (next_def, next_async) if c > 0]
    end = min(candidates) if candidates else func_idx + 3000
    body = energy_src[func_idx:end]
    # Must use _DOMAIN now
    assert "self.hass.data.get(_DOMAIN, {})" in body, (
        "v4.5.20 fix: _account_arbitrage_cycle must use _DOMAIN, not DOMAIN."
    )
    # Must NOT use bare DOMAIN (would NameError)
    assert "self.hass.data.get(DOMAIN, {})" not in body, (
        "v4.5.20 regression: _account_arbitrage_cycle still has bare DOMAIN. "
        "NameError will fire every arbitrage cycle."
    )


def test_refresh_arbitrage_status_cache_uses_underscore_DOMAIN(energy_src: str):
    """Site 2: _refresh_arbitrage_status_cache cache refresh. Must use `_DOMAIN`."""
    func_idx = energy_src.find("def _refresh_arbitrage_status_cache(")
    assert func_idx >= 0
    next_def = energy_src.find("\n    def ", func_idx + 100)
    next_async = energy_src.find("\n    async def ", func_idx + 100)
    candidates = [c for c in (next_def, next_async) if c > 0]
    end = min(candidates) if candidates else func_idx + 3000
    body = energy_src[func_idx:end]
    assert "self.hass.data.get(_DOMAIN, {})" in body
    assert "self.hass.data.get(DOMAIN, {})" not in body


def test_sensor_imports_match_signals_definitions(
    sensor_src: str, signals_src: str,
):
    """Catch the v4.5.10.1 ImportError shape: every
    `from .domain_coordinators.signals import SIGNAL_*` in sensor.py
    must reference a SIGNAL_* constant that actually exists in signals.py.
    """
    import re
    # Match `from .domain_coordinators.signals import (...)` (parenthesized
    # multi-line) OR `from .domain_coordinators.signals import NAME[, NAME...]`
    # (single line). Stop at closing paren or end of line.
    multi = re.findall(
        r"from \.domain_coordinators\.signals import\s*\(([^)]+)\)",
        sensor_src,
    )
    single = re.findall(
        r"from \.domain_coordinators\.signals import\s+([^\n(]+)",
        sensor_src,
    )
    all_names = set()
    for imp in multi + single:
        for n in imp.replace("\n", " ").split(","):
            n = n.strip()
            # Strip trailing whitespace and any comments
            if "#" in n:
                n = n.split("#", 1)[0].strip()
            if n.startswith("SIGNAL_") and " " not in n:
                all_names.add(n)
    for name in all_names:
        assert name in signals_src, (
            f"sensor.py imports {name} from signals.py but it isn't "
            "defined there. Bug Class #32 / #34 prevention."
        )
