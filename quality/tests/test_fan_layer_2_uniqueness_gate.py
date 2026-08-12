"""FAN-LAYER-2 D1 build-gate: room-name uniqueness + key derivability.

PLAN §5.2 + §10-D1 + §11-Risk-1: SINGLE mechanism, named
``test_room_name_uniqueness_gate``, reading the committed snapshot at
``quality/tests/fixtures/config_entries_snapshot.json``. Failure of this
test BLOCKS build dispatch — remediation is a config-flow rename before
re-dispatch, not a plan weakening.
"""

from __future__ import annotations

import json
import os
import sys
import types
import unicodedata
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Home Assistant stubs — matches the pattern used by test_hvac_fan_control.py
# so this test collects cleanly on a machine without the ``homeassistant``
# package installed (the CI / dev container path).
# ---------------------------------------------------------------------------
_identity = lambda fn: fn  # noqa: E731

_mods = {
    "homeassistant": {},
    "homeassistant.core": {
        "HomeAssistant": MagicMock, "callback": _identity,
    },
    "homeassistant.config_entries": {"ConfigEntry": MagicMock},
    "homeassistant.const": MagicMock(),
    "homeassistant.util": {},
    "homeassistant.util.dt": {
        "utcnow": MagicMock(), "now": MagicMock(),
        "as_local": lambda dt: dt, "parse_datetime": MagicMock(),
    },
}
for name, attrs in _mods.items():
    if isinstance(attrs, dict):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules.setdefault(name, mod)
    else:
        sys.modules.setdefault(name, attrs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Bypass custom_components __init__ (imports the full integration surface).
_cc = types.ModuleType("custom_components")
_cc.__path__ = [os.path.join(os.path.dirname(__file__), "..", "..", "custom_components")]
sys.modules.setdefault("custom_components", _cc)

_ura_path = os.path.join(_cc.__path__[0], "universal_room_automation")
_ura = types.ModuleType("custom_components.universal_room_automation")
_ura.__path__ = [_ura_path]
_ura.__package__ = "custom_components.universal_room_automation"
sys.modules.setdefault("custom_components.universal_room_automation", _ura)

_ura_const = types.ModuleType(
    "custom_components.universal_room_automation.const"
)
_ura_const.DOMAIN = "universal_room_automation"
_ura_const.ROOM_TYPE_GENERIC = "generic"
_ura_const.DEFAULT_FAN_SLEEP_POLICY = "reduce"
sys.modules.setdefault(
    "custom_components.universal_room_automation.const", _ura_const,
)

# Import _room_key from the module under test. We isolate the import to
# just this one helper — hvac_fans.py's transitive imports (fan_veto etc.)
# are heavy, but the plain `unicodedata`-based _room_key doesn't need any
# of that machinery at call time.


def _load_room_key():
    """Load _room_key from hvac_fans.py source without triggering the full
    HVAC-tier import graph (fan_veto, hvac_zones, signals ...).

    We do this by execing just the helper's source into an isolated
    namespace. This keeps the build-gate independent of the wider test
    harness — if the helper regresses, the gate fails; if some sibling
    module fails to import, the gate is unaffected.
    """
    import ast
    hvac_fans_src = Path(
        _ura_path,
    ) / "domain_coordinators" / "hvac_fans.py"
    tree = ast.parse(hvac_fans_src.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_room_key":
            ns: dict = {"unicodedata": unicodedata,
                        "_LOGGER": MagicMock()}
            exec(compile(ast.Module(body=[node], type_ignores=[]),
                         str(hvac_fans_src), "exec"), ns)
            return ns["_room_key"]
    raise RuntimeError("_room_key not found in hvac_fans.py")


_room_key = _load_room_key()


_FIXTURE = (
    Path(__file__).parent / "fixtures" / "config_entries_snapshot.json"
)


def _room_entries() -> list[dict]:
    payload = json.loads(_FIXTURE.read_text())
    return [
        e for e in payload["entries"] if e.get("entry_type") == "room"
    ]


def test_room_name_uniqueness_gate():
    """FAN-LAYER-2 D1 build gate (PLAN §10-D1). Blocks build on failure.

    Asserts, across every ENTRY_TYPE_ROOM entry in the committed
    snapshot:
      (a) ``room_name`` is present and non-empty;
      (b) ``_room_key(room_name)`` does not raise (NFC + trim + no
          control chars);
      (c) ``_room_key(room_name)`` is UNIQUE across all rooms.

    A collision here means two rooms would share an oracle ledger row,
    breaking INV-DTA and losing per-room hold/cooldown isolation. The
    fix is an operator-side rename of one of the colliding rooms; do
    not weaken the gate.
    """
    entries = _room_entries()
    assert entries, "no room entries in fixture — snapshot is empty"

    keys: dict[str, list[str]] = {}
    empty_names: list[str] = []
    for e in entries:
        name = e.get("room_name")
        if not name:
            empty_names.append(e.get("entry_id", "<no entry_id>"))
            continue
        # (b) — must not raise
        key = _room_key(name)
        keys.setdefault(key, []).append(name)

    assert not empty_names, (
        f"rooms with empty CONF_ROOM_NAME (each would collide on "
        f"room:__unkeyed__): {empty_names}"
    )

    dupes = {k: v for k, v in keys.items() if len(v) > 1}
    assert not dupes, (
        "duplicate room keys after NFC-normalization would collide in the "
        f"oracle ledger — rename one of each set before build: {dupes}"
    )


def test_room_key_normalizes_nfc_vs_nfd():
    """PLAN §5.2 MED-2-round-2: NFC vs NFD forms hash to the same key."""
    nfc = unicodedata.normalize("NFC", "Café")
    nfd = unicodedata.normalize("NFD", "Café")
    assert nfc != nfd  # sanity — codepoints differ
    assert _room_key(nfc) == _room_key(nfd)


def test_room_key_rejects_control_chars():
    """PLAN §5.2 MED-2-round-2: control chars raise ValueError."""
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _room_key("bad\x00name")


def test_room_key_trims_whitespace():
    """PLAN §5.2: trailing whitespace collapses to the trimmed form."""
    assert _room_key("Living Room ") == _room_key("Living Room")
    assert _room_key("  Kitchen  ") == "room:Kitchen"


def test_room_key_empty_returns_unkeyed_sentinel():
    """Empty name maps to ``room:__unkeyed__`` (never bare empty string)."""
    assert _room_key("") == "room:__unkeyed__"
    assert _room_key("   ") == "room:__unkeyed__"
