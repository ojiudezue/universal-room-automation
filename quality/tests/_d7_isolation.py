"""TEST-HARNESS Wave 2 D7: scope a test file's import-time sys.modules stubs.

Many legacy test files install stub packages into ``sys.modules`` at import
(collection) time so the production module under test can be imported
without Home Assistant, and never take them back out. Every file collected
or run afterwards then inherits a partial ``const`` / placeholder package /
MagicMock submodule ("donor" -> "victim").

``import_scope`` is the per-file fix: wrap the stub-install + import block,
and on exit every ``sys.modules`` key under the given prefixes is put back
exactly as it was (replaced keys restored, added keys removed). The objects
the file imported stay bound in the file's own namespace, so its tests are
unaffected. Not a conftest fixture on purpose: the broad conftest-level
restore was tried and reverted (exposed 87 failures); D7 fixes one donor
file at a time.

Known limit (review s1 A-LOW-2): the snapshot is by IDENTITY. An in-place
mutation of an object that already existed (``const.SOME_DICT["k"] = v``,
``some_list.append(x)``) keeps the same object id, so neither the sys.modules
restore nor ``attrs=True`` sees it and it is NOT undone. A donor that
mutates in place needs its own monkeypatch (``monkeypatch.setitem``) or a
copy. ``import_scope(..., guard=True)`` turns the common case (a dict / list
/ set attribute of a pre-existing module under the prefixes changed in
place) into a loud ``RuntimeError`` at scope exit instead of a silent leak.

``installed`` (returned by the context manager) holds what the block put in,
so a module-scoped fixture can re-install it while the file's tests run when
production code does lazy imports at call time (``reinstall``).
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

DEFAULT_PREFIXES = ("custom_components", "homeassistant", "aiosqlite")


def _matches(name: str, prefixes) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


_MISSING = object()


class Installed(dict):
    """sys.modules entries the block installed; ``.attrs`` holds attribute
    writes it made onto modules that already existed (``attrs=True``):
    {module name: {attr: new value or _MISSING-for-deleted}}."""

    def __init__(self):
        super().__init__()
        self.attrs: dict = {}


def _vars(mod):
    try:
        return dict(vars(mod))
    except TypeError:
        return None


_CONTAINERS = (dict, list, set)


def _container_snapshot(mods: dict) -> dict:
    snap = {}
    for k, m in mods.items():
        d = _vars(m)
        if not d:
            continue
        for a, v in d.items():
            if type(v) in _CONTAINERS:
                try:
                    snap[(k, a)] = (v, type(v)(v))
                except Exception:  # noqa: BLE001 - unhashable/odd: skip
                    continue
    return snap


def _container_changes(snap: dict) -> list[str]:
    changed = []
    for (k, a), (obj, copy) in snap.items():
        try:
            if obj != copy:
                changed.append(f"{k}.{a}")
        except Exception:  # noqa: BLE001
            continue
    return changed


@contextmanager
def import_scope(prefixes=DEFAULT_PREFIXES, attrs=False, guard=False):
    """Restore sys.modules keys under ``prefixes`` on exit.

    attrs=True additionally restores ATTRIBUTE writes the block made onto
    modules that already existed (e.g. ``setattr(real_ha_core, "callback",
    stub)``) — the shape a plain sys.modules restore cannot see.
    """
    before = {k: v for k, v in list(sys.modules.items()) if _matches(k, prefixes)}
    before_vars = {k: _vars(m) for k, m in before.items()} if attrs else {}
    containers = _container_snapshot(before) if guard else {}
    installed = Installed()
    try:
        yield installed
    finally:
        mutated = _container_changes(containers) if guard else []
        after = {k: v for k, v in list(sys.modules.items()) if _matches(k, prefixes)}
        for k, v in after.items():
            if before.get(k) is not v:
                installed[k] = v
        for k, old in before_vars.items():
            mod = before[k]
            if old is None:
                continue
            now = _vars(mod) or {}
            changed = {a: v for a, v in now.items() if old.get(a, _MISSING) is not v}
            removed = {a: _MISSING for a in old if a not in now}
            if changed or removed:
                installed.attrs[k] = {**changed, **removed}
                for a in changed:
                    if a in old:
                        setattr(mod, a, old[a])
                    else:
                        delattr(mod, a)
                for a in removed:
                    setattr(mod, a, old[a])
        for k in after:
            if k not in before:
                sys.modules.pop(k, None)
        for k, v in before.items():
            if sys.modules.get(k) is not v:
                sys.modules[k] = v
        _restore_parent_attrs(before, after)
        if mutated:
            raise RuntimeError(
                "import_scope(guard=True): in-place mutation of a pre-existing "
                "module container is not restorable by import_scope: "
                + ", ".join(sorted(mutated))
            )


def _restore_parent_attrs(before: dict, after: dict) -> None:
    """Undo the submodule attribute the import system binds on a parent.

    ``import a.b`` sets ``a.b`` as an attribute of package ``a``. Restoring
    sys.modules alone leaves that attribute on a parent that outlives the
    scope, so ``from a import b`` would bind a different object than
    ``sys.modules['a.b']`` (review s1 B-LOW / A-LOW-1). Applies with
    attrs=False too. Only an attribute that still points at the object the
    scope left behind is touched.
    """
    for k, v in after.items():
        if before.get(k) is v:
            continue
        parent_name, _, child = k.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is None or not child:
            continue
        try:
            current = vars(parent).get(child, _MISSING)
        except TypeError:
            continue
        if current is not v:
            continue
        old = before.get(k, _MISSING)
        try:
            if old is _MISSING:
                delattr(parent, child)
            else:
                setattr(parent, child, old)
        except (AttributeError, TypeError):
            pass


def file_scope(prefixes=DEFAULT_PREFIXES):
    """Generator body for a module-scoped autouse fixture that puts back
    everything a test FILE did to ``sys.modules`` and to pre-existing
    modules under ``prefixes`` while its tests ran -- stubs installed at
    test time, production modules lazily imported against those stubs,
    attribute writes onto real modules (``ha_er.async_get = fake``), and
    parent-package attributes (``homeassistant.util.dt = stub``).

    Usage::

        @pytest.fixture(autouse=True, scope="module")
        def _restore_module_state():
            yield from file_scope()

    TEST-SUITE-ORDER-INDEP-PRODSTUBS-1 runtime slice. Only covers what the
    tests do at RUN time; import-time stubs belong in ``import_scope``.
    """
    with import_scope(prefixes, attrs=True):
        yield


@contextmanager
def real_package_scope(set_aside, prefixes=DEFAULT_PREFIXES):
    """Set aside ``sys.modules`` entries for which ``set_aside(name, mod)``
    is true (typically every URA module and every non-real HA stub), so the
    block can import the REAL package; on exit restore sys.modules,
    attributes of pre-existing modules, and parent-package attributes
    exactly as they were.

    Importing the real package rebinds attributes on parents that outlive
    the swap (e.g. ``homeassistant.util.dt``); without the attribute restore
    a later ``patch("homeassistant.util.dt.now")`` patches a different
    object than the code under test reads (19 polluted clock tests,
    2026-10-20, test_ec_bill_cycle_day_wired.py).
    """
    import importlib

    with import_scope(prefixes, attrs=True):
        for name, mod in list(sys.modules.items()):
            if _matches(name, prefixes) and set_aside(name, mod):
                del sys.modules[name]
        importlib.invalidate_caches()
        yield


def reinstall(installed: dict, prefixes=DEFAULT_PREFIXES):
    """Generator body for a module-scoped fixture: re-install what the import
    block put in, run the module's tests, then put every key under
    ``prefixes`` back as it was before -- including modules the tests
    imported lazily against the stubs (e.g. a production module loaded
    under a placeholder package at test time) and, when the block was
    scoped with ``attrs=True``, its attribute writes on pre-existing
    modules."""
    attr_writes = getattr(installed, "attrs", {})
    with import_scope(prefixes, attrs=bool(attr_writes)):
        for k, v in installed.items():
            sys.modules[k] = v
        for k, writes in attr_writes.items():
            mod = sys.modules.get(k)
            if mod is None:
                continue
            for a, v in writes.items():
                if v is _MISSING:
                    if hasattr(mod, a):
                        delattr(mod, a)
                else:
                    setattr(mod, a, v)
        yield


def restore_clocks_after_test(monkeypatch, module_globals: dict) -> None:
    """Register the CURRENT now/utcnow of every clock module a test file
    drives with ``_set_now`` so monkeypatch puts them back after the test.

    Those files bind a production module's ``dt_util`` (names ending in
    ``dt_util``, or ``<x>_mod.dt_util``) and their own ``_dt_mock``. That object can be the REAL
    homeassistant.util.dt -- or an orphaned real copy no longer in
    sys.modules, which no sys.modules-based restore can see -- so a frozen
    ``_set_now`` clock used to outlive the file (victims:
    ec_billing_emporia_counters, energy_savings_unification, ...)."""
    targets = []
    for name, val in list(module_globals.items()):
        cand = None
        if (name.endswith("dt_util") or name == "_dt_mock") and hasattr(val, "utcnow"):
            cand = val
        elif name.endswith("_mod") and hasattr(getattr(val, "dt_util", None), "utcnow"):
            cand = val.dt_util
        if cand is not None and all(cand is not t for t in targets):
            targets.append(cand)
    for t in targets:
        for attr in ("now", "utcnow"):
            if hasattr(t, attr):
                monkeypatch.setattr(t, attr, getattr(t, attr))


def other_dt_modules():
    """Distinct ``homeassistant.util.dt`` objects other than
    ``sys.modules['homeassistant.util.dt']`` -- today: the parent package
    attribute ``homeassistant.util.dt``, which is what production's call-time
    ``from homeassistant.util import dt`` binds. A sibling stub install can
    leave the two disagreeing; a test that pins a clock must pin both."""
    primary = sys.modules.get("homeassistant.util.dt")
    parent = getattr(sys.modules.get("homeassistant.util"), "dt", None)
    return [parent] if parent is not None and parent is not primary else []
