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


@contextmanager
def import_scope(prefixes=DEFAULT_PREFIXES, attrs=False):
    """Restore sys.modules keys under ``prefixes`` on exit.

    attrs=True additionally restores ATTRIBUTE writes the block made onto
    modules that already existed (e.g. ``setattr(real_ha_core, "callback",
    stub)``) — the shape a plain sys.modules restore cannot see.
    """
    before = {k: v for k, v in list(sys.modules.items()) if _matches(k, prefixes)}
    before_vars = {k: _vars(m) for k, m in before.items()} if attrs else {}
    installed = Installed()
    try:
        yield installed
    finally:
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
