"""Shared helper: install a COMPLETE ``custom_components.universal_room_automation.const``
into ``sys.modules`` so test-time imports never see a partial stub.

BLE-HOLD-CAP-SUITE-POLLUTION-1 root cause: many test files installed a bare
``types.ModuleType`` under the const key at module scope, carrying only a handful
of attributes (DOMAIN, VERSION, a few enums). Any test file collected LATER whose
top-level ``from ...const import X`` names a symbol the partial stub omits raises
ImportError at collection time and aborts the whole suite (default ordering).

This helper makes ANY resident const module COMPLETE by exec'ing the real
``const.py`` source into the module's __dict__. It is:

  * idempotent   -- safe to call any number of times from any file
  * additive     -- preserves module identity so refs already bound elsewhere
                    see the newly-added attributes
  * override-aware -- pass ``overrides={...}`` to set/replace attributes AFTER
                      the real source is loaded (for the handful of files that
                      set a deliberately-different test value)

Registers the const module under both dotted keys currently in use across the
test suite:

  * ``custom_components.universal_room_automation.const``
  * ``universal_room_automation.const``  (only if the sibling parent already
    exists in sys.modules -- we never *create* the bare namespace)

Also attaches ``parent.const = mod`` where the parent package is already
resident, matching what existing robust stubs do (test_energy_battery.py:101).
"""
from __future__ import annotations

import os
import sys
import types

_URA_ROOT = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "custom_components",
        "universal_room_automation",
    )
)
_REAL_CONST_PATH = os.path.join(_URA_ROOT, "const.py")
_REAL_SIGNALS_PATH = os.path.join(_URA_ROOT, "domain_coordinators", "signals.py")

_PKG_KEYS = (
    "custom_components.universal_room_automation",
    "universal_room_automation",
)
_CONST_KEYS = tuple(k + ".const" for k in _PKG_KEYS)
_SIGNALS_KEYS = tuple(k + ".domain_coordinators.signals" for k in _PKG_KEYS)

# Sentinel: attribute set on the module dict after we exec the real source.
# Its presence proves the module is COMPLETE (came from real const.py).
_COMPLETE_MARKER = "__ura_const_complete__"
_SIGNALS_MARKER = "__ura_signals_complete__"


def _read_source(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _make_complete(mod: types.ModuleType, source_path: str = _REAL_CONST_PATH,
                   marker: str = _COMPLETE_MARKER,
                   default_name: str = "custom_components.universal_room_automation.const") -> None:
    """Exec real source into ``mod.__dict__`` (additive). Idempotent."""
    if getattr(mod, marker, False):
        return
    source = _read_source(source_path)
    path = source_path
    # Ensure the module has __file__/__name__ so exec'd code that references
    # them (or that Python's importer machinery inspects) is happy.
    mod.__file__ = path
    if not getattr(mod, "__name__", None):
        mod.__name__ = default_name
    code = compile(source, path, "exec")
    exec(code, mod.__dict__)  # noqa: S102 - controlled, first-party source
    mod.__dict__[marker] = True


def ensure_ura_const(overrides: dict | None = None) -> types.ModuleType:
    """Guarantee a COMPLETE const module is registered under sys.modules.

    * If a partial stub is resident, upgrade it in place (preserves identity).
    * If nothing is resident, install a fresh complete module.
    * Applies ``overrides`` LAST via setattr so callers can pin test values.

    Returns the (canonical) resident const module.
    """
    # Pick or create the canonical module under the primary key.
    primary = _CONST_KEYS[0]
    mod = sys.modules.get(primary)
    if mod is None:
        # Also check the bare-namespace key in case an older file installed
        # only under that name.
        for k in _CONST_KEYS[1:]:
            if k in sys.modules:
                mod = sys.modules[k]
                break
    if mod is None:
        mod = types.ModuleType(primary)

    _make_complete(mod)

    # Register under every key the suite reads from.
    sys.modules[primary] = mod
    for k in _CONST_KEYS[1:]:
        # Only register the bare-namespace key if the bare parent already
        # exists (some legacy tests set that up); do not create it ourselves.
        parent_bare = k.rsplit(".", 1)[0]
        if parent_bare in sys.modules:
            sys.modules[k] = mod

    # Attach as attribute on any resident parent package.
    for pk in _PKG_KEYS:
        parent = sys.modules.get(pk)
        if parent is not None:
            try:
                parent.const = mod  # type: ignore[attr-defined]
            except Exception:
                pass

    # Apply overrides last so they win over real values.
    if overrides:
        for k, v in overrides.items():
            setattr(mod, k, v)

    return mod


def ensure_ura_signals(overrides: dict | None = None) -> types.ModuleType:
    """Guarantee a COMPLETE ``.domain_coordinators.signals`` is resident.

    Same shape as ``ensure_ura_const`` but for the signals module — many test
    files install a partial ``types.ModuleType`` there and later imports of
    other SIGNAL_* names collapse collection. Upgrades in-place.
    """
    primary = _SIGNALS_KEYS[0]
    mod = sys.modules.get(primary)
    if mod is None:
        for k in _SIGNALS_KEYS[1:]:
            if k in sys.modules:
                mod = sys.modules[k]
                break
    if mod is None:
        mod = types.ModuleType(primary)

    _make_complete(
        mod,
        source_path=_REAL_SIGNALS_PATH,
        marker=_SIGNALS_MARKER,
        default_name=primary,
    )

    sys.modules[primary] = mod
    for k in _SIGNALS_KEYS[1:]:
        parent_bare = k.rsplit(".", 1)[0]
        if parent_bare in sys.modules:
            sys.modules[k] = mod

    if overrides:
        for k, v in overrides.items():
            setattr(mod, k, v)

    return mod
