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


@contextmanager
def import_scope(prefixes=DEFAULT_PREFIXES):
    before = {k: v for k, v in list(sys.modules.items()) if _matches(k, prefixes)}
    installed: dict = {}
    try:
        yield installed
    finally:
        after = {k: v for k, v in list(sys.modules.items()) if _matches(k, prefixes)}
        for k, v in after.items():
            if before.get(k) is not v:
                installed[k] = v
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
    under a placeholder package at test time)."""
    with import_scope(prefixes):
        for k, v in installed.items():
            sys.modules[k] = v
        yield
