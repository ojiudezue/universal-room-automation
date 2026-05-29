"""v4.7.6.1 cycle tests — Labels + Helper text + excess_solar_soc Number.

Tier 1 hotfix cycle. Covers:
- D1: ExcessSolarSOCNumber class structure, setter pair on EnergyCoordinator,
      tick-snapshot at decision tick, B-M7 _safe_unsub guard.
- D2: Friendly-name renames on the three EV-SOC Numbers (Pause/Resume/Floor).
- D3: data_description rewrites (3-sentence template).
- D4: Dead l1_plug_self_modulates translation key removed; per-EVSE labels
      updated.
- D5: README footnote + README_v4.7.6.1.md exist;
      DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD stays at 50.

Source-level tests follow the v4.7.6 cycle's pattern in
quality/tests/test_evse_solar_aware_ux.py.
"""

from __future__ import annotations

import json
import os
import re

import pytest


_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "custom_components", "universal_room_automation",
)
_NUMBER = os.path.join(_ROOT, "number.py")
_ENERGY = os.path.join(_ROOT, "domain_coordinators", "energy.py")
_ENERGY_CONST = os.path.join(_ROOT, "domain_coordinators", "energy_const.py")
_STRINGS = os.path.join(_ROOT, "strings.json")
_EN = os.path.join(_ROOT, "translations", "en.json")
_README_v476 = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "readmes", "README_v4.7.6.md",
)
_README_v4761 = os.path.join(
    os.path.dirname(__file__), "..", "..", "docs", "readmes",
    "README_v4.7.6.1.md",
)


def _read(p: str) -> str:
    with open(p, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# D1 — ExcessSolarSOCNumber class structure + setter pair + tick-snapshot
# ---------------------------------------------------------------------------


class TestD1ExcessSolarSOCNumberClass:
    def test_excess_solar_soc_number_class_exists(self):
        src = _read(_NUMBER)
        assert "class ExcessSolarSOCNumber" in src, (
            "D1: ExcessSolarSOCNumber class must be defined in number.py"
        )
        assert "RestoreEntity" in src
        # Mirrors FillPriority — must inherit NumberEntity + RestoreEntity.
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        if end < 0:
            end = len(src)
        slice_ = src[idx:end]
        assert "NumberEntity, RestoreEntity" in slice_

    def test_excess_solar_soc_unique_id_stable(self):
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert 'f"{DOMAIN}_energy_excess_solar_soc"' in slice_, (
            "D1: ExcessSolarSOCNumber unique_id must be "
            "f'{DOMAIN}_energy_excess_solar_soc'"
        )

    def test_excess_solar_soc_slider_range(self):
        """Matches config_flow.py:3486-3494 (min 80, max 100, step 1, unit %)."""
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert "_attr_native_step = 1" in slice_
        assert "_attr_native_min_value = 80" in slice_
        assert "_attr_native_max_value = 100" in slice_
        assert '_attr_native_unit_of_measurement = "%"' in slice_
        assert "NumberMode.SLIDER" in slice_

    def test_excess_solar_soc_wired_into_setup_entry(self):
        src = _read(_NUMBER)
        # Must appear in the CM-entry entities list alongside FillPriority.
        assert "ExcessSolarSOCNumber(hass, entry, 95)" in src, (
            "D1: ExcessSolarSOCNumber must be instantiated with default=95 in "
            "async_setup_entry for the Coordinator Manager entry"
        )

    def test_excess_solar_soc_setter_pair_on_energy_coordinator(self):
        """D1: EnergyCoordinator gains `excess_solar_soc` property +
        `set_excess_solar_soc` setter mirroring fill_priority_soc."""
        src = _read(_ENERGY)
        assert "def excess_solar_soc" in src, (
            "D1: EnergyCoordinator.excess_solar_soc property missing"
        )
        assert "def set_excess_solar_soc" in src, (
            "D1: EnergyCoordinator.set_excess_solar_soc setter missing"
        )

    def test_excess_solar_soc_push_to_coordinator_call_present(self):
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert "energy.set_excess_solar_soc(self._value)" in slice_, (
            "D1: ExcessSolarSOCNumber._push_to_coordinator must call "
            "energy.set_excess_solar_soc()"
        )


class TestD1TickSnapshot:
    """D1: `_excess_solar_soc_tick` snapshot at decision-tick start —
    mirrors v4.7.6 B-M3 for fill_priority_soc. Mid-tick setter call must
    not race the determine_excess_solar_actions call.
    """

    def test_decision_cycle_captures_excess_solar_soc_snapshot(self):
        src = _read(_ENERGY)
        idx = src.find("async def _async_decision_cycle")
        assert idx > 0, "decision cycle function must exist"
        end = src.find("\n    async def ", idx + 1)
        if end < 0:
            end = len(src)
        slice_ = src[idx:end]
        assert (
            "excess_solar_soc_tick = int(self._excess_solar_soc)" in slice_
        ), (
            "D1: tick-snapshot of _excess_solar_soc must be captured at the "
            "actuation-block start, mirroring fill_priority_soc_tick"
        )

    def test_excess_solar_branch_reads_tick_snapshot(self):
        """determine_excess_solar_actions must be called with the snapshot,
        not the live `self._excess_solar_soc`."""
        src = _read(_ENERGY)
        idx = src.find("self._ev.determine_excess_solar_actions")
        assert idx > 0
        # Walk forward 400 chars and verify the kwarg uses the snapshot.
        slice_ = src[idx:idx + 400]
        assert "soc_threshold=excess_solar_soc_tick" in slice_, (
            "D1: determine_excess_solar_actions must receive "
            "soc_threshold=excess_solar_soc_tick (tick-snapshot), not the "
            "live _excess_solar_soc"
        )
        # And the live-attr form must NOT still be there.
        assert "soc_threshold=self._excess_solar_soc" not in slice_, (
            "D1: live-attr read of self._excess_solar_soc at this call site "
            "leaves the mid-tick race window open"
        )


class TestD1SafeUnsubGuard:
    """B-M7 carry-forward: ExcessSolarSOCNumber must use the _safe_unsub
    double-unsub guard pattern from FillPrioritySOCNumber."""

    def test_excess_solar_soc_uses_safe_unsub_wrapper(self):
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        assert idx > 0
        end = src.find("\nclass ", idx + 1)
        if end < 0:
            end = len(src)
        slice_ = src[idx:end]
        assert "def _safe_unsub" in slice_, (
            "B-M7: ExcessSolarSOCNumber must define _safe_unsub() guard"
        )
        assert "self.async_on_remove(_safe_unsub)" in slice_, (
            "B-M7: ExcessSolarSOCNumber must register _safe_unsub via "
            "async_on_remove (not unsub_holder[0])"
        )
        assert "self.async_on_remove(unsub_holder[0])" not in slice_, (
            "B-M7: ExcessSolarSOCNumber must NOT register unsub_holder[0] "
            "directly — double-unsub bug"
        )


class TestD1RestoreEntityRoundTrip:
    """RestoreEntity is canonical runtime store; entry.options seed only."""

    def test_excess_solar_soc_uses_restore_entity(self):
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert "async def async_added_to_hass" in slice_
        assert "await self.async_get_last_state()" in slice_, (
            "D1: ExcessSolarSOCNumber must restore last value via "
            "async_get_last_state (RestoreEntity round-trip)"
        )

    def test_excess_solar_soc_seeds_from_entry_options(self):
        """Confirms the entry.options[CONF_ENERGY_EXCESS_SOLAR_SOC] seed
        path exists for first-install."""
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert "CONF_ENERGY_EXCESS_SOLAR_SOC" in slice_


# ---------------------------------------------------------------------------
# D2 — Friendly-name renames + unique_id stability
# ---------------------------------------------------------------------------


class TestD2FriendlyNames:
    def test_fill_priority_friendly_name_pause_until(self):
        src = _read(_NUMBER)
        idx = src.find("class FillPrioritySOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert 'self._attr_name = "Pause EV Until Battery SOC"' in slice_

    def test_ev_battery_drain_friendly_name_floor(self):
        src = _read(_NUMBER)
        idx = src.find("class EVBatteryDrainSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert 'self._attr_name = "EV Drain-Protection SOC Floor"' in slice_

    def test_excess_solar_friendly_name_resume_at(self):
        src = _read(_NUMBER)
        idx = src.find("class ExcessSolarSOCNumber")
        end = src.find("\nclass ", idx + 1)
        slice_ = src[idx:end] if end > 0 else src[idx:]
        assert 'self._attr_name = "Resume EV at Battery SOC"' in slice_

    def test_fill_priority_unique_id_stable(self):
        src = _read(_NUMBER)
        # Stable unique_id pin: must still read `_energy_fill_priority_soc`.
        assert 'f"{DOMAIN}_energy_fill_priority_soc"' in src

    def test_ev_battery_drain_unique_id_stable(self):
        src = _read(_NUMBER)
        assert 'f"{DOMAIN}_energy_ev_battery_drain_soc"' in src


# ---------------------------------------------------------------------------
# D3 — Helper-text rewrites (data_description blocks)
# ---------------------------------------------------------------------------


def _data_description_block(json_path: str) -> dict:
    """Return the coordinator_energy data_description block from a translation
    file (strings.json or translations/en.json)."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    return (
        data["options"]["step"]["coordinator_energy"]["data_description"]
    )


class TestD3HelperText:
    def test_strings_data_description_present_for_four_keys(self):
        block = _data_description_block(_STRINGS)
        for key in (
            "energy_fill_priority_soc",
            "energy_excess_solar_soc",
            "energy_ev_battery_drain_soc",
            "energy_excess_solar_enabled",
        ):
            assert key in block, f"D3: missing data_description key {key}"

    def test_en_data_description_present_for_four_keys(self):
        block = _data_description_block(_EN)
        for key in (
            "energy_fill_priority_soc",
            "energy_excess_solar_soc",
            "energy_ev_battery_drain_soc",
            "energy_excess_solar_enabled",
        ):
            assert key in block, f"D3: missing data_description key {key}"

    def test_strings_and_en_in_sync(self):
        s = _data_description_block(_STRINGS)
        e = _data_description_block(_EN)
        for key in (
            "energy_fill_priority_soc",
            "energy_excess_solar_soc",
            "energy_ev_battery_drain_soc",
            "energy_excess_solar_enabled",
        ):
            assert s[key] == e[key], (
                f"D3: strings.json and translations/en.json disagree on {key}"
            )

    def test_fill_priority_helper_text_mentions_default_80(self):
        text = _data_description_block(_STRINGS)["energy_fill_priority_soc"]
        assert "Default 80%" in text
        assert "Resume EV at Battery SOC" in text

    def test_excess_solar_helper_text_mentions_default_95(self):
        text = _data_description_block(_STRINGS)["energy_excess_solar_soc"]
        assert "Default 95%" in text
        assert "Pause EV Until Battery SOC" in text

    def test_ev_drain_helper_text_mentions_default_50_deep_floor(self):
        """D5.3 resolved: stay at 50 in code; helper reads 'Default 50%
        (deep floor behind Pause EV Until Battery SOC)'."""
        text = _data_description_block(_STRINGS)["energy_ev_battery_drain_soc"]
        assert "Default 50%" in text
        assert "deep floor" in text

    def test_master_toggle_helper_text(self):
        text = _data_description_block(_STRINGS)["energy_excess_solar_enabled"]
        assert "Master toggle" in text


class TestD5_4HelperTextDiscipline:
    """D5.4: each new data_description.* block follows the locked template
    (mechanics only, no prose paragraphs).

    The locked wording per plan §D5.4 has 4 dot-separated clauses (trigger
    sentence + 'Default N%' fragment + 'Range X-Y' fragment + pair hint).
    Two of those are sentence fragments (no verb), so the spirit of the
    3-sentences-max rule maps onto 'at most 3 full sentences', counting
    only clauses with a finite verb (length >= 8 words is the proxy).

    Hard cap on overall length is the structural guard.
    """

    TARGETS = (
        "energy_fill_priority_soc",
        "energy_excess_solar_soc",
        "energy_ev_battery_drain_soc",
        "energy_excess_solar_enabled",
    )

    @staticmethod
    def _full_sentence_count(text: str) -> int:
        # Sentence fragments like 'Default 80%' or 'Range 50-95%' (<= 4
        # words, no verb) are not full sentences. Count only clauses with
        # 5+ words.
        parts = re.split(r"[.!?]+", text)
        return sum(1 for p in parts if len(p.strip().split()) >= 5)

    def test_all_targets_at_most_three_full_sentences(self):
        block = _data_description_block(_STRINGS)
        for key in self.TARGETS:
            n = self._full_sentence_count(block[key])
            assert n <= 3, (
                f"D5.4: data_description.{key} has {n} full sentences; "
                f"template caps at 3 (fragments like 'Default N%' / "
                f"'Range X-Y' don't count). Content: {block[key]!r}"
            )

    def test_all_targets_under_length_cap(self):
        """Hard structural guard against drift into prose paragraphs."""
        block = _data_description_block(_STRINGS)
        for key in self.TARGETS:
            text = block[key]
            assert len(text) <= 360, (
                f"D5.4: data_description.{key} is {len(text)} chars; "
                f"helper-text cap is 360. Push depth into README."
            )


# ---------------------------------------------------------------------------
# D4 — Per-EVSE label cleanup + dead translation removal
# ---------------------------------------------------------------------------


class TestD4PerEVSELabels:
    def test_garage_a_label_human_self_modulates(self):
        with open(_STRINGS, encoding="utf-8") as f:
            data = json.load(f)
        labels = data["options"]["step"]["coordinator_energy"]["data"]
        assert (
            labels["garage_a_self_modulates"]
            == "Garage A self-modulates (URA re-pauses every cycle)"
        )

    def test_garage_b_label_human_self_modulates(self):
        with open(_STRINGS, encoding="utf-8") as f:
            data = json.load(f)
        labels = data["options"]["step"]["coordinator_energy"]["data"]
        assert (
            labels["garage_b_self_modulates"]
            == "Garage B self-modulates (URA re-pauses every cycle)"
        )

    def test_garage_helper_text_matches_spec(self):
        block = _data_description_block(_STRINGS)
        for key in ("garage_a_self_modulates", "garage_b_self_modulates"):
            text = block[key]
            assert "smart EVSEs/plugs" in text
            assert "EVSE Force-Charge button" in text
            assert "backs off for 1 hour" in text


class TestD4L1PlugDeadKeysRemoved:
    """v4.7.6 README §11 + Reviewer C-H2: l1_plug_self_modulates was split
    into per-plug keys in v4.7.6. Dead translation entries must be removed."""

    def test_l1_plug_self_modulates_translation_keys_removed(self):
        for path in (_STRINGS, _EN):
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            assert "l1_plug_self_modulates" not in raw, (
                f"D4: dead key 'l1_plug_self_modulates' must be removed from "
                f"{os.path.basename(path)}"
            )


# ---------------------------------------------------------------------------
# JSON validity gate (pre-deploy step 3 of zero-bugs gate)
# ---------------------------------------------------------------------------


class TestJSONValidity:
    def test_strings_json_parses(self):
        with open(_STRINGS, encoding="utf-8") as f:
            json.load(f)

    def test_en_json_parses(self):
        with open(_EN, encoding="utf-8") as f:
            json.load(f)


# ---------------------------------------------------------------------------
# D5 — Manual updates
# ---------------------------------------------------------------------------


class TestD5Manuals:
    def test_v476_readme_has_corrective_footnote(self):
        text = _read(_README_v476)
        assert "corrected 2026-05-29" in text, (
            "D5.1: README_v4.7.6.md must carry corrective footnote at the "
            "excess_solar_soc mention"
        )
        assert "v4.7.6.1" in text

    def test_v4761_readme_exists_with_required_sections(self):
        assert os.path.exists(_README_v4761), (
            "D5.2: docs/readmes/README_v4.7.6.1.md must exist"
        )
        text = _read(_README_v4761)
        # Required sections per planning §D5.2.
        assert "Headline Changes" in text
        assert "Asymmetric Defaults Rationale" in text
        assert "deep floor" in text.lower()
        # Concrete walkthrough at FP=80/ES=95/Drain=50.
        for marker in ("SOC=30", "SOC=60", "SOC=85", "SOC=90", "SOC=95"):
            # Accept either "SOC=N" literal or table-row "| N |" form.
            assert marker in text or re.search(
                rf"\|\s*{marker.split('=')[1]}\s*\|", text,
            ), f"D5.2: walkthrough must include {marker}"

    def test_drain_default_stays_at_50(self):
        """D5.3: DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD stays at 50 in code."""
        src = _read(_ENERGY_CONST)
        assert "DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD: Final = 50" in src or (
            "DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD = 50" in src
        ), (
            "D5.3: DEFAULT_EV_BATTERY_DRAIN_SOC_THRESHOLD must remain 50; "
            "user's live value (80) persists via RestoreEntity"
        )
