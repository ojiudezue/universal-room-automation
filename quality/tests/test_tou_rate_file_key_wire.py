"""TOU-RATE-FILE-KEY-UNWIRED-1: verify CONF_ENERGY_TOU_RATE_FILE is wired.

Prior to this cycle, `CONF_ENERGY_TOU_RATE_FILE` was defined in
`domain_coordinators/energy_const.py` but never read anywhere. The
`async_setup_entry` block that pre-builds `TOURateEngine` passed the
hardcoded `DEFAULT_TOU_RATE_FILE` as the filename. This test file
provides:

1. Helper unit tests for `_resolve_tou_rate_file` covering unset/empty
   values, a custom value, and path-safety rejections
   (absolute path / `..` traversal).
2. A WIRE-IN ANCHOR that inspects `__init__.async_setup_entry`'s source
   and asserts the `TOURateEngine.async_from_json_file` call takes
   `_resolve_tou_rate_file(cm_config)` as its filename argument (i.e.
   the read site actually uses the resolver — a helper-only test would
   stay green even if the call site were reverted to the hardcoded
   default, which is exactly the bug class we're fixing).
"""

from __future__ import annotations

import inspect
import re
import sys
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Homeassistant module shims (mirrors quality/tests/test_energy_tou.py)
# ---------------------------------------------------------------------------

_identity = lambda fn: fn  # noqa: E731


def _install_ha_shims():
    if "homeassistant" in sys.modules:
        return

    def _mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    _mod("homeassistant")
    _mod("homeassistant.core", HomeAssistant=MagicMock, callback=_identity)
    _mod("homeassistant.config_entries", ConfigEntry=MagicMock,
         SOURCE_IMPORT="import", ConfigEntryState=MagicMock())
    _mod("homeassistant.const")
    _mod("homeassistant.helpers")
    _mod("homeassistant.helpers.device_registry", DeviceInfo=dict)
    _mod("homeassistant.helpers.entity", DeviceInfo=dict,
         EntityCategory=MagicMock())
    _mod("homeassistant.helpers.entity_platform",
         AddEntitiesCallback=MagicMock)
    _mod("homeassistant.helpers.event")
    _mod("homeassistant.helpers.dispatcher",
         async_dispatcher_connect=lambda *a, **k: (lambda: None),
         async_dispatcher_send=lambda *a, **k: None)
    _mod("homeassistant.helpers.update_coordinator",
         DataUpdateCoordinator=MagicMock, UpdateFailed=Exception)
    _mod("homeassistant.helpers.selector", selector=MagicMock())
    _mod("homeassistant.exceptions", HomeAssistantError=Exception,
         ConfigEntryNotReady=Exception, ConfigEntryError=Exception)
    _mod("homeassistant.util")
    _mod("homeassistant.util.dt", utcnow=lambda: None, as_local=lambda x: x,
         now=lambda: None, parse_datetime=lambda s: None)


_install_ha_shims()


# ---------------------------------------------------------------------------
# Load target module without importing the whole package (avoids heavy init).
# ---------------------------------------------------------------------------

import importlib.util
import pathlib

_INIT_PATH = pathlib.Path(__file__).resolve().parents[2] / (
    "custom_components/universal_room_automation/__init__.py"
)


@pytest.fixture(scope="module")
def ura_init_source() -> str:
    return _INIT_PATH.read_text()


@pytest.fixture(scope="module")
def resolver():
    """Import just the resolver by exec'ing its slice — avoids importing
    the full package (which pulls in HA integration machinery).

    We compile the whole __init__.py in a namespace that stubs out the
    HA-specific symbols; failing that, we extract the function source and
    exec it in isolation.
    """
    src = _INIT_PATH.read_text()
    m = re.search(
        r"^def _resolve_tou_rate_file\(cm_config: dict\) -> str:.*?(?=\n\n\S)",
        src, re.DOTALL | re.MULTILINE,
    )
    assert m, "Could not locate _resolve_tou_rate_file in __init__.py"
    ns: dict = {"__name__": "ura_resolver_test"}
    # Provide a logger + the two constants the helper reads.
    import logging
    ns["_LOGGER"] = logging.getLogger("ura_resolver_test")
    # Inline-import inside the helper works because sys.path has the
    # custom_components tree available via the ha shim setup used by
    # other tests; but the resolver's import uses relative form
    # (`from .domain_coordinators.energy_const`). Rewrite it to absolute.
    body = m.group(0).replace(
        "from .domain_coordinators.energy_const import",
        "from custom_components.universal_room_automation."
        "domain_coordinators.energy_const import",
    )
    exec(compile(body, str(_INIT_PATH), "exec"), ns)
    return ns["_resolve_tou_rate_file"]


# ---------------------------------------------------------------------------
# Unit tests for the resolver
# ---------------------------------------------------------------------------

def test_resolver_unset_returns_default(resolver):
    from custom_components.universal_room_automation.domain_coordinators \
        .energy_const import DEFAULT_TOU_RATE_FILE
    assert resolver({}) == DEFAULT_TOU_RATE_FILE


def test_resolver_none_config_returns_default(resolver):
    from custom_components.universal_room_automation.domain_coordinators \
        .energy_const import DEFAULT_TOU_RATE_FILE
    assert resolver(None) == DEFAULT_TOU_RATE_FILE


def test_resolver_empty_string_returns_default(resolver):
    from custom_components.universal_room_automation.domain_coordinators \
        .energy_const import DEFAULT_TOU_RATE_FILE
    assert resolver({"energy_tou_rate_file": "   "}) == DEFAULT_TOU_RATE_FILE


def test_resolver_custom_value_passes_through(resolver):
    assert resolver({"energy_tou_rate_file": "custom_tou.json"}) == \
        "custom_tou.json"


def test_resolver_rejects_absolute_path(resolver):
    from custom_components.universal_room_automation.domain_coordinators \
        .energy_const import DEFAULT_TOU_RATE_FILE
    assert resolver({"energy_tou_rate_file": "/etc/passwd"}) == \
        DEFAULT_TOU_RATE_FILE


def test_resolver_rejects_dotdot_traversal(resolver):
    from custom_components.universal_room_automation.domain_coordinators \
        .energy_const import DEFAULT_TOU_RATE_FILE
    assert resolver(
        {"energy_tou_rate_file": "../../etc/passwd"}
    ) == DEFAULT_TOU_RATE_FILE
    assert resolver(
        {"energy_tou_rate_file": "sub/../../secret"}
    ) == DEFAULT_TOU_RATE_FILE


# ---------------------------------------------------------------------------
# WIRE-IN ANCHOR — verify __init__.py's setup path actually calls the resolver
# to produce the filename argument to TOURateEngine.async_from_json_file.
#
# Rationale: a helper-only test stays green if the read site reverts to the
# hardcoded DEFAULT_TOU_RATE_FILE (the pre-cycle state). This test asserts
# the call site itself is wired to the resolver — killing that mutation.
# ---------------------------------------------------------------------------

def test_wire_in_call_site_uses_resolver(ura_init_source):
    """__init__.py's TOU engine build MUST pass the resolver's output.

    We search for the block that constructs TOURateEngine and assert that
    it references `_resolve_tou_rate_file(cm_config)` and that the third
    argument to `async_from_json_file` is the resolved value, NOT
    `DEFAULT_TOU_RATE_FILE` directly.
    """
    src = ura_init_source

    # Isolate the TOURateEngine build block: walk paren depth to capture
    # the full argument list (there is a nested call, hass.config.path("")).
    start = src.find("await TOURateEngine.async_from_json_file(")
    assert start != -1, "TOURateEngine.async_from_json_file call not found"
    open_paren = src.find("(", start)
    depth = 0
    end = -1
    for i in range(open_paren, len(src)):
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    assert end != -1, "Unbalanced parens around async_from_json_file call"
    args = src[open_paren + 1:end]

    # Split on top-level commas.
    parts = []
    cur = ""
    depth = 0
    for c in args:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        parts.append(cur.strip())
    arg_list = [a for a in parts if a]
    assert len(arg_list) >= 3, f"Expected >=3 args, got: {arg_list!r}"
    third = arg_list[2]
    assert third != "DEFAULT_TOU_RATE_FILE", (
        "Read site still passes hardcoded DEFAULT_TOU_RATE_FILE — "
        "CONF_ENERGY_TOU_RATE_FILE is unwired."
    )
    assert "tou_rate_file" in third, (
        f"Expected resolved local (e.g. tou_rate_file), got {third!r}"
    )

    # And the resolver call itself must appear immediately above the build.
    assert "_resolve_tou_rate_file(cm_config)" in src, (
        "Resolver `_resolve_tou_rate_file(cm_config)` not invoked in "
        "async_setup_entry — the CM config key is not being read."
    )
