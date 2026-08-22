"""Anchor test for the hvac_excursion import guard's WARNING.

Fix-up r4 (2026-08-21): the import guard in hvac_egress.py's
_try_load_excursion_module MUST fire a WARNING on the ImportError path,
naming the consequence ("hvac_excursion unavailable; egress excursions
will NOT be governed"). Silent fallback is a production hazard: if a
future edit (circular import, partial deploy, hotfix syntax error)
breaks the import, every egress excursion silently stops being
governed while the wire writes still happen.

Neuter anchor: remove the _LOGGER.warning call in the except branch of
_try_load_excursion_module -> this test fails.

This test reuses test_v478_egress_window's _load_egress_module() helper
which builds a synthetic package namespace WITHOUT a hvac_excursion
sibling, so the import guard's except-ImportError branch fires
deterministically.
"""
import sys
import test_v478_egress_window as _v478


def test_hvac_excursion_import_guard_logs_warning_on_import_error(caplog):
    import logging
    # Load the egress module under the synthetic package (this
    # triggers the ImportError path for hvac_excursion).
    caplog.set_level(logging.WARNING)
    egress_mod = _v478._load_egress_module()
    # Reset memoization + call again with capture active.
    egress_mod._EX_MOD_CACHE = ...
    caplog.clear()
    result = egress_mod._try_load_excursion_module()
    assert result is None, (
        f"expected None fallback; got {result!r}"
    )
    text = caplog.text
    assert "hvac_excursion unavailable" in text, (
        f"Item-1 WARNING absent. caplog={text!r}"
    )
    assert "egress excursions will NOT be governed" in text, (
        f"Item-1 consequence text absent. caplog={text!r}"
    )
