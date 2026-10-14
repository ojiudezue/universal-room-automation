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
    """Exec real source into ``mod.__dict__`` (additive). Idempotent.

    FIX-1 (A1): use ``mod.__dict__.get`` NOT ``getattr`` — a stub with a
    module-level ``__getattr__`` catch-all (e.g. test_arrester_comfort_delay
    for signals) would return the marker NAME (truthy) and silently
    short-circuit completion.
    """
    if mod.__dict__.get(marker, False):
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


# ---------------------------------------------------------------------------
# TEST-SUITE-ORDER-INDEP-PRODSTUBS-1: complete-module helper for ANY first-party
# production submodule (signals, hvac_fans, hvac, hvac_egress, hvac_setpoint,
# actuator_reconciler, occupancy_substrate, fan_veto, automation, ...).
#
# Shape: same as ensure_ura_const/ensure_ura_signals, but PRESERVES whatever the
# test file already installed in the partial stub (setdefault semantics). Many
# tests install a stub carrying *intentional* mock values; blindly exec'ing the
# real source over mod.__dict__ clobbers those (that was the 2026-09-12 revert
# fingerprint — ~87 runtime failures unmasked). This variant exec's real source
# into a THROWAWAY namespace and copies in only the symbols the stub lacks.
# ---------------------------------------------------------------------------

_PROD_MARKER = "__ura_prod_complete__"

# Dotted name -> relative-to-pkg path. Only first-party modules; must map to a
# real .py file in the package. Keep this list narrow — adding a dotted name
# here means every poisoned stub for that name will be upgraded at the next
# pytest_collectstart hook (see conftest).
_PROD_SUBMODULES: dict[str, str] = {
    "domain_coordinators.signals": "domain_coordinators/signals.py",
    "domain_coordinators.hvac": "domain_coordinators/hvac.py",
    "domain_coordinators.hvac_fans": "domain_coordinators/hvac_fans.py",
    "domain_coordinators.hvac_egress": "domain_coordinators/hvac_egress.py",
    "domain_coordinators.hvac_setpoint": "domain_coordinators/hvac_setpoint.py",
    "domain_coordinators.occupancy_substrate": "domain_coordinators/occupancy_substrate.py",
    "domain_coordinators._stuck_signal_nm": "domain_coordinators/_stuck_signal_nm.py",
    "domain_coordinators._loop_stall_watchdog": "domain_coordinators/_loop_stall_watchdog.py",
    "actuator_reconciler": "actuator_reconciler.py",
    "fan_veto": "fan_veto.py",
    "automation": "automation.py",
    "config_flow": "config_flow.py",
    "camera_census": "camera_census.py",
}


def _dotted_keys(sub_dotted: str) -> tuple[str, ...]:
    """Both the full-prefix and bare-package keys suite tests might use."""
    return tuple(f"{p}.{sub_dotted}" for p in _PKG_KEYS)


def _complete_additive(mod: types.ModuleType, source_path: str) -> None:
    """setdefault-semantics upgrade: fill in missing symbols, never clobber.

    1. exec real source into a THROWAWAY namespace.
    2. For every (k, v) real symbol: if ``k`` is already present on ``mod``,
       keep the stub's value; otherwise set it.
    3. Marker is idempotent — only re-run if someone cleared it.
    """
    if mod.__dict__.get(_PROD_MARKER, False):
        return
    tmp: dict = {
        "__name__": getattr(mod, "__name__", None) or source_path,
        "__file__": source_path,
    }
    try:
        source = _read_source(source_path)
        code = compile(source, source_path, "exec")
        exec(code, tmp)  # noqa: S102
    except Exception:
        # If real source cannot be loaded for any reason (missing optional
        # import, environment-dependent symbol), DO NOT raise during
        # collection — the whole point is to be a safety net, not a new
        # failure source. Mark as attempted so we do not retry per file.
        mod.__dict__[_PROD_MARKER] = True
        return
    for k, v in tmp.items():
        if k.startswith("__") and k.endswith("__"):
            # Preserve dunders the stub set deliberately (__name__, __path__, …).
            # Only backfill dunders the stub is missing.
            mod.__dict__.setdefault(k, v)
        else:
            mod.__dict__.setdefault(k, v)
    mod.__dict__[_PROD_MARKER] = True


def ensure_ura_prod_module(sub_dotted: str) -> types.ModuleType | None:
    """Upgrade a resident partial stub of a first-party production submodule
    in-place via setdefault semantics. No-op if nothing is resident.

    ``sub_dotted`` is the path after the package root, e.g.
    ``domain_coordinators.hvac_fans`` or ``fan_veto``.
    """
    rel = _PROD_SUBMODULES.get(sub_dotted)
    if rel is None:
        return None
    source_path = os.path.join(_URA_ROOT, rel)
    if not os.path.exists(source_path):
        return None
    mod = None
    for key in _dotted_keys(sub_dotted):
        if key in sys.modules:
            mod = sys.modules[key]
            break
    if mod is None:
        return None  # nothing resident — not our job to install one
    _complete_additive(mod, source_path)
    # Mirror under both keys if the sibling key is already resident (do not
    # create a new one — same policy as ensure_ura_const).
    for key in _dotted_keys(sub_dotted):
        parent_bare = key.rsplit(".", 1)[0]
        if parent_bare in sys.modules and key not in sys.modules:
            sys.modules[key] = mod
    return mod


def ensure_ura_pkg_paths() -> None:
    """Repair resident package stubs so Python's import machinery can find real
    submodules by filesystem path.

    Many test files install a bare ``types.ModuleType`` under
    ``custom_components`` / ``custom_components.universal_room_automation`` /
    ``.domain_coordinators`` with no ``__path__`` or an empty one. Later
    ``from custom_components.universal_room_automation.X import Y`` fails with
    ``IndexError: list index out of range`` (empty ``__path__[0]``) or
    ``ModuleNotFoundError`` (missing attr + no path). Pointing ``__path__`` at
    the real on-disk directory lets the standard FileFinder resolve ``X``.

    Idempotent, additive — never clears or shortens an existing path.
    """
    cc = os.path.normpath(os.path.join(_URA_ROOT, ".."))  # custom_components/
    pkg_paths = {
        "custom_components": cc,
        "custom_components.universal_room_automation": _URA_ROOT,
        "universal_room_automation": _URA_ROOT,
        "custom_components.universal_room_automation.domain_coordinators":
            os.path.join(_URA_ROOT, "domain_coordinators"),
        "universal_room_automation.domain_coordinators":
            os.path.join(_URA_ROOT, "domain_coordinators"),
    }
    for key, real_dir in pkg_paths.items():
        mod = sys.modules.get(key)
        if mod is None:
            continue
        if not os.path.isdir(real_dir):
            continue
        try:
            cur = list(getattr(mod, "__path__", []) or [])
        except TypeError:
            cur = []
        if real_dir not in cur:
            cur.append(real_dir)
            try:
                mod.__path__ = cur  # type: ignore[attr-defined]
            except Exception:
                pass
        # __file__ for an __init__.py helps importers that inspect it.
        init_py = os.path.join(real_dir, "__init__.py")
        if os.path.exists(init_py) and not getattr(mod, "__file__", None):
            try:
                mod.__file__ = init_py  # type: ignore[attr-defined]
            except Exception:
                pass


def ensure_ura_all_prod_modules() -> list[str]:
    """Walk every known production submodule and upgrade each resident stub.

    Returns the dotted-name list of modules it actually upgraded (for logging).
    Safe to call repeatedly; cheap when nothing is resident.
    """
    touched: list[str] = []
    for sub_dotted in _PROD_SUBMODULES:
        if ensure_ura_prod_module(sub_dotted) is not None:
            touched.append(sub_dotted)
    return touched


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
