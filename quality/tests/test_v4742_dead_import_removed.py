"""Regression guard: v4.7.4.2 + v4.7.4.3 dead-import removal.

HA 2026.5.4 moved selectors from homeassistant.components.selector to
homeassistant.helpers.selector. The old import path raises ModuleNotFoundError
on any HA version >= 2026.5.4, making the Zone Dynamic Preset form completely
inaccessible.

v4.7.4.2 deleted the broken import block. v4.7.4.3 accidentally reintroduced
it and then removed it again in the post-review fix-up. This test catches any
future merge that brings the dead import back.
"""

import os

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
_CONFIG_FLOW_PATH = os.path.join(
    _REPO_ROOT, "custom_components", "universal_room_automation", "config_flow.py"
)


def test_v4742_v4743_no_broken_selector_import():
    """Regression guard: the dead `from homeassistant.components.selector import ...`
    block must stay deleted. Removed in v4.7.4.2 + reintroduced + re-removed in
    v4.7.4.3 fix-up. Any future merge that brings it back will be caught here."""
    with open(_CONFIG_FLOW_PATH) as f:
        src = f.read()
    assert "from homeassistant.components.selector import" not in src, (
        "Dead import reintroduced — HA 2026.5.4+ moved selector to "
        "homeassistant.helpers.selector; the old path raises ModuleNotFoundError."
    )
