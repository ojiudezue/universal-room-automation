"""v4.5.9.2 — Strings + configurable occupied-cover-close delta.

Two pieces shipped together because both surfaced from the v4.5.9 live
validation as half-shipped UI:

1. **CONF_COVER_HVAC_MANAGED strings.** v4.5.9 added the form field but
   forgot the strings.json / translations/en.json entries — field
   appeared in the UI as the raw key "cover_hvac_managed" instead of
   a friendly label. Pure UX bug.

2. **CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA.** v4.5.9 hardcoded the
   threshold as `OCCUPIED_CLOSE_TEMP_DELTA = 2.0` in hvac_covers.py
   (planning doc said "configurable"; implementation drifted). v4.5.9.2
   surfaces it as a CM-level config field in the coordinator_hvac step,
   wired through HVACCoordinator constructor → CoverController →
   _should_close_for_occupied_room.

Both prevented by the same Bug Class #32 detection rule (form field
must have a runtime reader). Source-grep tests below assert each new
piece is wired end-to-end.
"""

import json
import pytest


# ---------------------------------------------------------------------------
# Strings tests — cover_hvac_managed labels exist in BOTH files
# ---------------------------------------------------------------------------

class TestCoverHvacManagedLabelsPresent:
    """v4.5.9.2: strings.json + translations/en.json must both have
    friendly labels for cover_hvac_managed in the cover_behavior step
    AND the options_covers reconfig step.

    Without these, the form field shows as the raw CONF key
    'cover_hvac_managed' in the UI — the v4.5.9 UX bug this fix closes.
    """

    @pytest.fixture
    def strings(self):
        with open("custom_components/universal_room_automation/strings.json") as f:
            return json.load(f)

    @pytest.fixture
    def en_translations(self):
        with open("custom_components/universal_room_automation/translations/en.json") as f:
            return json.load(f)

    def _get_step(self, payload, step_path):
        """Walk a dotted path through the JSON payload."""
        node = payload
        for key in step_path.split("."):
            node = node[key]
        return node

    @pytest.mark.parametrize("step_path", [
        "config.step.cover_behavior",   # Setup flow
        "options.step.options_covers",  # Reconfig flow
    ])
    def test_cover_hvac_managed_label_in_strings(self, strings, step_path):
        step = self._get_step(strings, step_path)
        assert "data" in step, f"Step {step_path} missing 'data' block"
        assert "cover_hvac_managed" in step["data"], (
            f"strings.json {step_path}.data is missing 'cover_hvac_managed' "
            f"label — the form field will show as the raw key. v4.5.9.2 fix."
        )
        # Label should be a non-empty human-readable string
        label = step["data"]["cover_hvac_managed"]
        assert isinstance(label, str) and len(label) > 0
        assert label != "cover_hvac_managed", (
            f"Label is identical to the key — that's the bug we're fixing"
        )

    @pytest.mark.parametrize("step_path", [
        "config.step.cover_behavior",
        "options.step.options_covers",
    ])
    def test_cover_hvac_managed_helper_text_in_strings(self, strings, step_path):
        step = self._get_step(strings, step_path)
        assert "data_description" in step
        assert "cover_hvac_managed" in step["data_description"], (
            f"strings.json {step_path} is missing data_description for "
            f"cover_hvac_managed. Helper text is the user's only signal "
            f"about what the toggle controls."
        )
        helper = step["data_description"]["cover_hvac_managed"]
        assert "HVAC" in helper
        assert "solar" in helper.lower() or "cover" in helper.lower()

    @pytest.mark.parametrize("step_path", [
        "config.step.cover_behavior",
        "options.step.options_covers",
    ])
    def test_translations_en_matches_strings(self, en_translations, step_path):
        """translations/en.json must mirror strings.json (per CLAUDE.md)."""
        step = self._get_step(en_translations, step_path)
        assert "cover_hvac_managed" in step["data"]
        assert "cover_hvac_managed" in step["data_description"]


# ---------------------------------------------------------------------------
# Configurable occupied-cover-close delta — wired through end-to-end
# ---------------------------------------------------------------------------

class TestOccupiedCoverCloseDeltaWired:
    """v4.5.9.2: CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA must be wired
    end-to-end: const → config_flow form → __init__.py reader →
    HVACCoordinator constructor → CoverController constructor →
    _should_close_for_occupied_room uses self._occupied_close_delta.

    Bug Class #32 prevention: every new form field must have a runtime
    read site. Bug Class #33 prevention: when threading a CONF through,
    audit every consumer (here: the CoverController gate that USES the
    threshold value).
    """

    @pytest.fixture
    def hvac_const_src(self):
        path = "custom_components/universal_room_automation/domain_coordinators/hvac_const.py"
        with open(path) as f:
            return f.read()

    @pytest.fixture
    def hvac_covers_src(self):
        path = "custom_components/universal_room_automation/domain_coordinators/hvac_covers.py"
        with open(path) as f:
            return f.read()

    @pytest.fixture
    def hvac_src(self):
        path = "custom_components/universal_room_automation/domain_coordinators/hvac.py"
        with open(path) as f:
            return f.read()

    @pytest.fixture
    def init_src(self):
        with open("custom_components/universal_room_automation/__init__.py") as f:
            return f.read()

    @pytest.fixture
    def config_flow_src(self):
        with open("custom_components/universal_room_automation/config_flow.py") as f:
            return f.read()

    @pytest.fixture
    def strings(self):
        with open("custom_components/universal_room_automation/strings.json") as f:
            return json.load(f)

    def test_const_defined(self, hvac_const_src):
        assert "CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA" in hvac_const_src
        assert "DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA" in hvac_const_src
        assert 'Final = "hvac_occupied_cover_close_delta"' in hvac_const_src

    def test_form_field_in_config_flow(self, config_flow_src):
        assert "CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA" in config_flow_src, (
            "v4.5.9.2 must add the form field to coordinator_hvac step"
        )
        # The field must appear inside the coordinator_hvac step
        idx = config_flow_src.find("async def async_step_coordinator_hvac")
        assert idx > 0, "coordinator_hvac step must exist"
        body = config_flow_src[idx:idx + 8000]
        assert "CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA" in body

    def test_init_reads_and_passes_to_constructor(self, init_src):
        """__init__.py must read CONF and pass to HVACCoordinator."""
        assert "CONF_HVAC_OCCUPIED_COVER_CLOSE_DELTA" in init_src
        assert "occupied_cover_close_delta" in init_src, (
            "Constructor kwarg 'occupied_cover_close_delta' must be set"
        )

    def test_hvac_coordinator_accepts_kwarg(self, hvac_src):
        assert "occupied_cover_close_delta: float" in hvac_src, (
            "HVACCoordinator.__init__ must accept occupied_cover_close_delta"
        )
        # And forward to CoverController
        assert "occupied_close_delta=occupied_cover_close_delta" in hvac_src, (
            "HVACCoordinator must forward delta to CoverController constructor"
        )

    def test_cover_controller_stores_and_uses(self, hvac_covers_src):
        """CoverController accepts kwarg, stores as instance attr, uses
        in the gate."""
        assert "occupied_close_delta" in hvac_covers_src, (
            "CoverController.__init__ must accept occupied_close_delta"
        )
        assert "self._occupied_close_delta" in hvac_covers_src, (
            "Must be stored as instance attr"
        )
        # And used in the gate (not the module constant)
        idx = hvac_covers_src.find("def _should_close_for_occupied_room")
        assert idx > 0
        body = hvac_covers_src[idx:idx + 2500]
        assert "self._occupied_close_delta" in body, (
            "Gate must use self._occupied_close_delta (not the module "
            "constant) — that's the v4.5.9.2 'use the configurable value' fix"
        )

    def test_strings_label_present(self, strings):
        step = strings["options"]["step"]["coordinator_hvac"]
        assert "hvac_occupied_cover_close_delta" in step["data"], (
            "strings.json coordinator_hvac.data missing label for new CONF"
        )
        assert "hvac_occupied_cover_close_delta" in step["data_description"], (
            "Helper text required so user understands the threshold semantics"
        )

    def test_translations_en_matches(self):
        """en.json must mirror strings.json for the new keys."""
        with open("custom_components/universal_room_automation/translations/en.json") as f:
            en = json.load(f)
        step = en["options"]["step"]["coordinator_hvac"]
        assert "hvac_occupied_cover_close_delta" in step["data"]
        assert "hvac_occupied_cover_close_delta" in step["data_description"]


# ---------------------------------------------------------------------------
# Lesson-learned guard: backward-compat check
# ---------------------------------------------------------------------------

class TestBackwardCompatHardcodedDefaultPreserved:
    """v4.5.9.2 must preserve the v4.5.9 default behavior (2.0°F threshold)
    when no CONF override is present. Fresh installs and entries that
    haven't reconfigured should see the same behavior as v4.5.9."""

    def test_default_constant_value(self):
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_const.py") as f:
            src = f.read()
        # Find the default declaration
        idx = src.find("DEFAULT_HVAC_OCCUPIED_COVER_CLOSE_DELTA")
        assert idx > 0
        # Should equal 2.0
        line_end = src.find("\n", idx)
        line = src[idx:line_end]
        assert "2.0" in line, (
            "Default must remain 2.0°F (v4.5.9 behavior preservation). "
            f"Got: {line}"
        )

    def test_module_constant_still_exists(self):
        """The module-level OCCUPIED_CLOSE_TEMP_DELTA constant must still
        exist as a fallback for code that hasn't been threaded yet (and
        as a backward-compat reference). v4.5.9.2 makes it the default
        for the constructor kwarg."""
        with open("custom_components/universal_room_automation/domain_coordinators/hvac_covers.py") as f:
            src = f.read()
        assert "OCCUPIED_CLOSE_TEMP_DELTA" in src
        # Constructor signature default uses the module constant
        idx = src.find("def __init__")
        body = src[idx:idx + 1500]
        assert "occupied_close_delta: float = OCCUPIED_CLOSE_TEMP_DELTA" in body, (
            "Constructor default must point to the module constant for "
            "backward-compat"
        )
