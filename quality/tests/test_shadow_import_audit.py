"""SHADOW-IMPORT-AUDIT-1 — permanent regression guard for Bug Class #34
(function-local `from .const import X` shadowing a name USED earlier in the
same function -> UnboundLocalError at runtime; the v5.84.0 CONF_ENTRY_TYPE
incident, plus the presence async_setup sensitivity-swallow and the energy
_save_evse_state dt_util shadow fixed 2026-09-12).

Two assertions:
  1. the detector actually detects the pattern (positive control), and
  2. the whole component is currently CLEAN (no use-before-local-import).
"""
from __future__ import annotations

import importlib.util
import os

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_AUDIT = os.path.join(_REPO, "quality", "tools", "audit_shadow_imports.py")


def _load_audit():
    spec = importlib.util.spec_from_file_location("_audit_shadow", _AUDIT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_detector_flags_a_known_shadow():
    """Positive control: a name used before its function-local import IS flagged."""
    audit = _load_audit()
    bad = (
        "def f(entry):\n"
        "    if entry.get(CONF_X) == 1:\n"        # use BEFORE the local import
        "        return True\n"
        "    from .const import CONF_X\n"           # function-local import
        "    return entry.get(CONF_X)\n"
    )
    findings = audit.find_shadows_in_source(bad, "bad.py")
    names = {fnd[2] for fnd in findings}
    assert "CONF_X" in names, f"detector missed the shadow: {findings}"


def test_detector_ignores_import_before_use():
    """Negative control: import BEFORE use is safe and must NOT be flagged."""
    audit = _load_audit()
    good = (
        "def f(entry):\n"
        "    from .const import CONF_X\n"
        "    return entry.get(CONF_X)\n"
    )
    assert audit.find_shadows_in_source(good, "good.py") == []


def test_component_is_clean_of_shadow_imports():
    """Repo-wide: no Bug Class #34 use-before-local-import remains."""
    audit = _load_audit()
    findings = audit.find_shadows()
    assert findings == [], (
        "Bug Class #34 shadow(s) found (name used before its function-local "
        f"import -> UnboundLocalError): {findings}"
    )
