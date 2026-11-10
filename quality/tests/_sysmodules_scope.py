"""Scope a test file's import-time ``sys.modules`` stubs to that file.

Some legacy test files build hand-made package stubs at IMPORT time
(``custom_components``, the URA package, ``domain_coordinators``) and load
real URA modules under those stubs, under the REAL dotted names. Import
time is pytest COLLECTION time, which runs for every file before any test
runs, so the stubs leaked into every other file's tests: a real module's
lazy ``from . import hvac_const`` then resolved to the stub-loaded copy,
not the one the other test file had imported and monkeypatched
(test_hvac_evidence_shadow.py, 25 failures in the full suite, 2026-11-10).

Usage (in the stubbing file)::

    import _sysmodules_scope
    _SCOPE = _sysmodules_scope.ModuleScope(prefixes=("custom_components",))
    ... import-time stubbing + loading, ``from ... import`` bindings ...
    _SCOPE.seal()
    _scoped_modules = _SCOPE.fixture()   # module-scoped, autouse

``seal()`` records every tracked ``sys.modules`` entry the file added or
replaced, then puts back what was there before. The fixture re-installs the
file's entries for the duration of the file's own tests and restores the
entries it found when it exits.
"""
from __future__ import annotations

import sys

import pytest

_MISSING = object()


class ModuleScope:
    def __init__(self, prefixes: tuple[str, ...] = ("custom_components",)):
        self._prefixes = prefixes
        self._before = {k: v for k, v in sys.modules.items() if self._tracked(k)}
        self.installed: dict = {}
        self.previous: dict = {}

    def _tracked(self, name: str) -> bool:
        return any(name == p or name.startswith(p + ".") for p in self._prefixes)

    @staticmethod
    def _apply(mapping: dict) -> None:
        for name, mod in mapping.items():
            if mod is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def seal(self) -> None:
        """Record the file's entries, then restore the pre-import ones."""
        after = {k: v for k, v in sys.modules.items() if self._tracked(k)}
        self.installed = {
            k: v for k, v in after.items() if self._before.get(k, _MISSING) is not v
        }
        self.previous = {k: self._before.get(k, _MISSING) for k in self.installed}
        # An entry the import REMOVED (present before, gone after) is put back too.
        for k, v in self._before.items():
            if k not in after:
                self.installed[k] = _MISSING
                self.previous[k] = v
        self._apply(self.previous)

    def fixture(self):
        scope = self

        @pytest.fixture(scope="module", autouse=True)
        def _scoped_sys_modules():
            found = {k: sys.modules.get(k, _MISSING) for k in scope.installed}
            present = {k for k in sys.modules if scope._tracked(k)}
            scope._apply(scope.installed)
            try:
                yield
            finally:
                # Entries first imported while the file's stubs were live are
                # bound to those stubs: drop them, then restore what was found.
                for k in [k for k in sys.modules if scope._tracked(k)]:
                    if k not in present and k not in found:
                        sys.modules.pop(k, None)
                scope._apply(found)

        return _scoped_sys_modules
