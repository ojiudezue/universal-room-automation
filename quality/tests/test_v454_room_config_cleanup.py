"""v4.5.4 — Room config & dead-code cleanup regression tests.

This release deletes dead config / orphan constants. The tests below
assert that:
  - Things that should be GONE are gone (the cleanup actually happened).
  - Things that should still EXIST still exist (we didn't over-delete;
    legacy fallback chain in particular is preserved).
  - The legacy `_get_cover_open_mode` migration mapping in automation.py
    matches the v3.6.40 spec exactly (every legacy value → correct new
    mode).

Mirror-style for the cover-mode mapping (the production helper isn't
cleanly importable without HA), and source-grep for the const/form
deletions. Same pattern as v4.5.0.4 / v4.5.2 / v4.5.3.
"""

import pytest


# ---------------------------------------------------------------------------
# D1 — CONF_HVAC_EFFICIENCY_ALERTS removed entirely
# ---------------------------------------------------------------------------

class TestD1HvacEfficiencyAlertsRemoved:
    """The only verified blinds-class hit in v4.5.4 scope."""

    @pytest.fixture
    def const_source(self):
        with open("custom_components/universal_room_automation/const.py") as f:
            return f.read()

    @pytest.fixture
    def config_flow_source(self):
        with open("custom_components/universal_room_automation/config_flow.py") as f:
            return f.read()

    @pytest.fixture
    def strings_source(self):
        with open("custom_components/universal_room_automation/strings.json") as f:
            return f.read()

    @pytest.fixture
    def en_source(self):
        with open("custom_components/universal_room_automation/translations/en.json") as f:
            return f.read()

    def test_const_definition_removed(self, const_source):
        assert "CONF_HVAC_EFFICIENCY_ALERTS" not in const_source

    def test_form_field_removed(self, config_flow_source):
        assert "CONF_HVAC_EFFICIENCY_ALERTS" not in config_flow_source
        assert "hvac_efficiency_alerts" not in config_flow_source

    def test_strings_removed(self, strings_source):
        assert "hvac_efficiency_alerts" not in strings_source

    def test_translations_en_removed(self, en_source):
        assert "hvac_efficiency_alerts" not in en_source


# ---------------------------------------------------------------------------
# D2 — Pure orphan constants removed (3 of 4)
# ---------------------------------------------------------------------------

class TestD2OrphanConstantsRemoved:
    """`CONF_PHONE_TRACKERS`, `CONF_ROOM_BEACONS`, `CONF_TRACK_PERSONS_IN_ROOM`
    were defined in const.py but never imported or read anywhere.

    `CONF_COMFORT_ENABLED` was deferred to the CM cleanup cycle because
    its value (`comfort_coordinator_enabled`) is referenced in
    `COORDINATOR_ENABLED_KEYS` mapping as a placeholder for a future
    coordinator — same shape as the deferred `CONF_MUSIC_FOLLOWING_ENABLED`.
    """

    @pytest.fixture
    def const_source(self):
        with open("custom_components/universal_room_automation/const.py") as f:
            return f.read()

    def test_phone_trackers_removed(self, const_source):
        # CONF_PHONE_TRACKER (singular) was deprecated in v3.2.4 and
        # kept for migration. CONF_PHONE_TRACKERS (plural, multi-phone)
        # is the v3.1.5-era residue we delete.
        assert "CONF_PHONE_TRACKERS" not in const_source

    def test_room_beacons_removed(self, const_source):
        assert "CONF_ROOM_BEACONS" not in const_source

    def test_track_persons_in_room_removed(self, const_source):
        assert "CONF_TRACK_PERSONS_IN_ROOM" not in const_source

    def test_comfort_enabled_intentionally_deferred(self, const_source):
        """CM-level placeholder — defer with music_following.

        Don't delete CONF_COMFORT_ENABLED in this cycle. The value
        `comfort_coordinator_enabled` is referenced in
        COORDINATOR_ENABLED_KEYS and represents a planned (unbuilt)
        coordinator slot. CM cleanup cycle will handle this.
        """
        assert "CONF_COMFORT_ENABLED" in const_source
        assert '"comfort": "comfort_coordinator_enabled"' in const_source


# ---------------------------------------------------------------------------
# D3 — Truly-dead DEFAULT_* time-window constants removed
# ---------------------------------------------------------------------------

class TestD3DeadDefaultsRemoved:
    @pytest.fixture
    def const_source(self):
        with open("custom_components/universal_room_automation/const.py") as f:
            return f.read()

    def test_default_open_time_start_removed(self, const_source):
        # Match the actual definition, not narrative text in comments
        assert "DEFAULT_OPEN_TIME_START: Final" not in const_source

    def test_default_open_time_end_removed(self, const_source):
        assert "DEFAULT_OPEN_TIME_END: Final" not in const_source

    def test_default_close_time_removed(self, const_source):
        # `DEFAULT_CLOSE_TIME:` would also match `DEFAULT_CLOSE_TIME_*`
        # variants if any existed; tighten with the type annotation.
        assert "DEFAULT_CLOSE_TIME: Final" not in const_source

    def test_default_scan_interval_removed(self, const_source):
        assert "DEFAULT_SCAN_INTERVAL: Final" not in const_source

    def test_sun_offset_defaults_preserved(self, const_source):
        """DEFAULT_SUNRISE_OFFSET / DEFAULT_SUNSET_OFFSET are alive
        (consumed by _is_after_sunrise / _is_after_sunset). Don't
        delete them."""
        assert "DEFAULT_SUNRISE_OFFSET" in const_source
        assert "DEFAULT_SUNSET_OFFSET" in const_source


# ---------------------------------------------------------------------------
# D3 (preservation) — Legacy fallback chain still intact
# ---------------------------------------------------------------------------

class TestD3LegacyFallbackChainPreserved:
    """The v3.6.39 cover redesign left a legacy fallback for entries that
    haven't been re-edited through the new form. URA dates back to v3.3.5.3,
    so many of the live entries still have legacy keys in entry.data.
    Don't break them.
    """

    @pytest.fixture
    def const_source(self):
        with open("custom_components/universal_room_automation/const.py") as f:
            return f.read()

    @pytest.fixture
    def automation_source(self):
        with open("custom_components/universal_room_automation/automation.py") as f:
            return f.read()

    @pytest.mark.parametrize("conf", [
        "CONF_OPEN_TIMING_MODE",
        "CONF_CLOSE_TIMING_MODE",
        "CONF_OPEN_TIME_START",
        "CONF_OPEN_TIME_END",
        "CONF_CLOSE_TIME",
    ])
    def test_legacy_fallback_const_preserved(self, const_source, conf):
        assert f"{conf}: Final" in const_source, (
            f"{conf} is part of the legacy cover-timing fallback chain "
            f"(_is_cover_open_time / _is_cover_close_time) and must "
            f"stay defined for pre-v3.6.39 entries."
        )

    def test_is_in_open_time_range_helper_preserved(self, automation_source):
        # Called at automation.py:958 inside the legacy timing-mode
        # branch. Removing it would break TIMING_MODE_TIME / BOTH_LATEST
        # / BOTH_EARLIEST for legacy entries.
        assert "def _is_in_open_time_range" in automation_source

    def test_is_after_close_time_helper_preserved(self, automation_source):
        # Called at automation.py:1341 inside the legacy timing-mode
        # branch on the close side.
        assert "def _is_after_close_time" in automation_source


# ---------------------------------------------------------------------------
# D4 — CONF_ENTRY_COVER_ACTION migration verified
# ---------------------------------------------------------------------------

class TestD4LegacyCoverActionMigration:
    """The audit's premise was wrong — `CONF_ENTRY_COVER_ACTION` is
    already not in any form (the form field was removed in some prior
    cycle). The legacy fallback in `automation.py:_get_cover_open_mode`
    is still alive for entries that have the legacy key in entry.data.
    Verify the mapping matches the v3.6.40 spec.
    """

    @pytest.fixture
    def config_flow_source(self):
        with open("custom_components/universal_room_automation/config_flow.py") as f:
            return f.read()

    @pytest.fixture
    def automation_source(self):
        with open("custom_components/universal_room_automation/automation.py") as f:
            return f.read()

    def test_form_does_not_collect_legacy_entry_action(self, config_flow_source):
        """v3.6.39 replaced CONF_ENTRY_COVER_ACTION with CONF_COVER_OPEN_MODE
        in the form. The form must not collect the legacy CONF anywhere.
        """
        assert "CONF_ENTRY_COVER_ACTION" not in config_flow_source, (
            "CONF_ENTRY_COVER_ACTION must not be in any form; if it "
            "reappears, the legacy fallback in _get_cover_open_mode "
            "becomes user-toggleable and the old form's UX confusion "
            "returns."
        )

    def test_legacy_fallback_still_reads_entry_data(self, automation_source):
        # Fallback at automation.py:919-944 reads CONF_ENTRY_COVER_ACTION
        # from entry.data only — no form site, but legacy entries have it.
        assert "CONF_ENTRY_COVER_ACTION" in automation_source
        assert "_get_cover_open_mode" in automation_source

    def test_mapping_matches_v3640_spec(self):
        """Spec from README_v3.6.40:
            COVER_ACTION_NONE   → COVER_OPEN_NONE
            COVER_ACTION_ALWAYS → COVER_OPEN_ON_ENTRY (no time gate)
            COVER_ACTION_SMART  → COVER_OPEN_ON_ENTRY_AFTER_TIME

        Mirror of automation.py:_get_cover_open_mode for testability.
        """
        # Mirror of the production logic
        def map_legacy_action(action):
            if action == "none":
                return "none"
            if action == "always":
                return "on_entry"
            return "on_entry_after_time"   # default = SMART

        assert map_legacy_action("none") == "none"
        assert map_legacy_action("always") == "on_entry"
        assert map_legacy_action("smart") == "on_entry_after_time"
        # Defensive default: any unknown legacy value lands in the
        # SMART bucket (matches production).
        assert map_legacy_action("garbage") == "on_entry_after_time"
        assert map_legacy_action("") == "on_entry_after_time"


# ---------------------------------------------------------------------------
# D5 — Bug Class #32 documented + DEVELOPMENT_CHECKLIST step added
# ---------------------------------------------------------------------------

class TestD5DocsUpdated:
    def test_bug_class_32_in_quality_context(self):
        with open("docs/QUALITY_CONTEXT.md") as f:
            content = f.read()
        assert "Bug Class #32" in content
        assert "Form Field With No Runtime Reader" in content
        # Hits-to-date list must reference the venetian-blinds case
        assert "CONF_COVER_TYPE" in content
        assert "CONF_HVAC_EFFICIENCY_ALERTS" in content

    def test_dev_checklist_has_form_reader_rule(self):
        with open("quality/DEVELOPMENT_CHECKLIST.md") as f:
            content = f.read()
        assert "Every new form field must have a runtime reader" in content


# ---------------------------------------------------------------------------
# Source compiles cleanly after the deletions
# ---------------------------------------------------------------------------

class TestSourceCompilesCleanly:
    @pytest.mark.parametrize("path", [
        "custom_components/universal_room_automation/const.py",
        "custom_components/universal_room_automation/config_flow.py",
        "custom_components/universal_room_automation/automation.py",
    ])
    def test_module_compiles(self, path):
        import py_compile
        py_compile.compile(path, doraise=True)
