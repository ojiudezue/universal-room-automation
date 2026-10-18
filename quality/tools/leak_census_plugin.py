"""pytest plugin behind ``collect_order_matrix.py --leak-census`` (D7 slice 2).

Per test FILE, records what the file leaves changed in ``sys.modules`` and in
the attributes of the modules under the watched prefixes, separately for
collection (import) time and for run time. Output: JSON at
``$LEAK_CENSUS_OUT`` -> {file nodeid: {"collect": [...], "run": [...]}}.

Entries:
  ``+mod K``       K added to sys.modules (collection time only; at run time a
                   new key is usually a lazy import of a REAL module)
  ``~mod K``       sys.modules[K] replaced by another object
  ``-mod K``       K removed from sys.modules
  ``~attr K.A``    attribute A of a module that stayed in place now points at
                   another object

Watched prefixes: ``$LEAK_CENSUS_PREFIXES`` (comma separated), default
``homeassistant,custom_components``. Read-only: it never restores anything.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

PREFIXES = tuple(
    p for p in os.environ.get(
        "LEAK_CENSUS_PREFIXES", "homeassistant,custom_components"
    ).split(",") if p
)
_SKIP_ATTRS = {"__loader__", "__spec__", "__cached__", "__builtins__"}


def _watched(name: str) -> bool:
    return any(name == p or name.startswith(p + ".") for p in PREFIXES)


def _snap():
    mods = {}
    attrs = {}
    for k, m in list(sys.modules.items()):
        if not _watched(k):
            continue
        mods[k] = id(m)
        try:
            d = vars(m)
        except TypeError:
            continue
        attrs[k] = {
            a: id(v) for a, v in list(d.items())
            if a not in _SKIP_ATTRS and not a.startswith("_d7")
        }
    return mods, attrs


def _diff(before, after):
    bm, ba = before
    am, aa = after
    out = []
    for k in am:
        if k not in bm:
            out.append(f"+mod {k}")
        elif am[k] != bm[k]:
            out.append(f"~mod {k}")
    for k in bm:
        if k not in am:
            out.append(f"-mod {k}")
    for k, av in aa.items():
        bv = ba.get(k)
        if bv is None or am.get(k) != bm.get(k):
            continue
        for a, i in av.items():
            if a in bv and bv[a] != i:
                out.append(f"~attr {k}.{a}")
    return out


RESULTS: dict = {}
_state = {"file": None, "before": None}


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    if not isinstance(collector, pytest.Module):
        yield
        return
    b = _snap()
    yield
    d = _diff(b, _snap())
    if d:
        RESULTS.setdefault(collector.nodeid, {})["collect"] = d


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    f = item.nodeid.split("::")[0]
    if _state["file"] != f:
        _state["file"] = f
        _state["before"] = _snap()
    yield
    nf = nextitem.nodeid.split("::")[0] if nextitem is not None else None
    if nf != f:
        d = _diff(_state["before"], _snap())
        d = [x for x in d if not x.startswith("+mod")]
        if d:
            RESULTS.setdefault(f, {})["run"] = d


def pytest_sessionfinish(session):
    out = os.environ.get("LEAK_CENSUS_OUT")
    if out:
        with open(out, "w") as fh:
            json.dump(RESULTS, fh, indent=1, sort_keys=True)
