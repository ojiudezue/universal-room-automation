import sys
from pathlib import Path

# Make custom_components importable from the repo root (quality/real_construction/ -> repo).
REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# NOTE: pytest-homeassistant-custom-component auto-registers via entry points
# when installed (providing the `hass` fixture). We deliberately do NOT list it
# in `pytest_plugins` — that would hard-fail collection on a mock-only dev box
# that lacks the package. The test module importorskips it instead, so it skips
# cleanly where HA is absent and runs where HA is present.
