"""Writer-B removal + preset reason-ledger cycle (2026-08-06).

Spec: docs/planning/AUDIT_writer_b_removal_study.md (Option a — outright
deletion) and docs/planning/AUDIT_hvac_preset_flap_fix_implications.md
§Cross-cutting Finding X + §Ledger reason shape.

Tests fall into three groups:

  1. Removal anchor — aggregation.py must not contain a
     `climate.set_preset_mode` service call (Writer B is gone). Mutation
     drill: re-adding such a call must turn this test RED.

  2. Sensor invariance — ZoneAnyoneBinarySensor.is_on continues to compute
     via Layer 1 (room rollup) + Layer 2 (sleep person fallback) + Layer 3
     (non-sleep person fallback). The is_on body is extracted and executed
     against a shim with sentinel layer values to prove behavioral parity
     with the pre-removal implementation.

  3. Reason ledger — every preset_change activity row and every
     preset_change DecisionLog gains a `reason` derived from the actual
     decision branch that produced effective_preset. Approved reason
     vocabulary (single-valued) plus the two underlying input booleans
     (`zone_vacant_past_grace`, `runtime_exceeded`) are recorded in
     details_json so mixed causes remain visible. The night-trust
     suppression fires a synthetic `preset_change_suppressed` row with
     reason=`night_trust_suppressed`. Mutation drill: stripping the
     `reason` field from the details dicts must turn these tests RED.
"""

from __future__ import annotations

import ast
import os
import re
import types

import pytest


ROOT = "custom_components/universal_room_automation"
AGGREGATION_PY = os.path.join(ROOT, "aggregation.py")
CONST_PY = os.path.join(ROOT, "const.py")
HVAC_PY = os.path.join(ROOT, "domain_coordinators", "hvac.py")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


@pytest.fixture(scope="module")
def agg_src() -> str:
    return _read(AGGREGATION_PY)


@pytest.fixture(scope="module")
def const_src() -> str:
    return _read(CONST_PY)


@pytest.fixture(scope="module")
def hvac_src() -> str:
    return _read(HVAC_PY)


# ============================================================================
# 1. Writer-B removal anchor
# ============================================================================


class TestWriterBRemoved:
    """aggregation.py must contain zero direct preset writers (Writer B gone)."""

    def test_no_set_preset_mode_call_in_aggregation(self, agg_src: str):
        """AST-anchor: no `services.async_call(..., 'set_preset_mode', ...)` remains.

        Writer B was the only site in aggregation.py that called
        climate.set_preset_mode. Any re-introduction (a resurrected second
        writer) is exactly the flap-audit Finding-X hazard and must fail
        this test loudly. We AST-walk so the docstring/comment mentioning
        the string does not false-fire.
        """
        tree = ast.parse(agg_src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Look for `<...>.services.async_call(<domain>, <service>, ...)`
            if not (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "async_call"
            ):
                continue
            # Second positional or a "service" kwarg carrying "set_preset_mode"
            svc_literals = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    svc_literals.append(arg.value)
            for kw in node.keywords:
                if (
                    kw.arg in ("service", None)
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    svc_literals.append(kw.value.value)
            assert "set_preset_mode" not in svc_literals, (
                "aggregation.py must not invoke `climate.set_preset_mode` — "
                "Writer B was deleted 2026-08-06. If HVAC preset writes "
                "belong somewhere new, put them behind HVACCoordinator "
                "(Writer A) and route via the arrester's suppress() "
                "handshake, not from the aggregation layer."
            )

    def test_writer_b_method_names_gone(self, agg_src: str):
        """The four bolt-on Writer-B methods must be deleted from aggregation.py."""
        for name in (
            "_schedule_hvac_listener_setup",
            "_setup_hvac_occupancy_listeners",
            "_handle_zone_occupancy_change",
            "_get_zone_climate_entity",
        ):
            assert f"def {name}" not in agg_src, (
                f"Writer B method `{name}` must be deleted from aggregation.py"
            )

    def test_writer_b_fields_gone(self, agg_src: str):
        """The two Writer-B-only fields must be deleted."""
        assert "_last_zone_occupied" not in agg_src, (
            "Writer B field _last_zone_occupied must be deleted (used only "
            "by the removed write path)."
        )
        assert "_hvac_unsub_listeners" not in agg_src, (
            "Writer B field _hvac_unsub_listeners must be deleted."
        )

    def test_dead_preset_constants_deleted(self, const_src: str):
        """const.py must not DEFINE the Writer-B-only preset constants.

        Uses AST to scan module-level assignments so the removal-note
        comment (which names the deleted constants for durability) does
        not false-fire.
        """
        tree = ast.parse(const_src)
        top_names: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        top_names.add(tgt.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                top_names.add(node.target.id)
        for name in (
            "CONF_ZONE_VACANT_PRESET",
            "CONF_ZONE_OCCUPIED_PRESET",
            "DEFAULT_ZONE_VACANT_PRESET",
            "DEFAULT_ZONE_OCCUPIED_PRESET",
            "HVAC_PRESET_SKIP",
        ):
            assert name not in top_names, (
                f"Dead Writer-B constant `{name}` must be deleted from const.py"
            )

    def test_removal_note_present_in_aggregation(self, agg_src: str):
        """A durable comment must explain WHY Writer B is gone (flap anchor)."""
        # We anchor on the two spec files' names so future edits that
        # thoughtlessly re-introduce a second writer will at least trip a
        # comment-scan reviewer.
        assert "AUDIT_writer_b_removal_study" in agg_src
        assert "2026-08-06" in agg_src


# ============================================================================
# 2. ZoneAnyoneBinarySensor.is_on — behavioral parity with sentinel exec
# ============================================================================


def _extract_class_method(src: str, cls_name: str, method_name: str) -> ast.FunctionDef:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return item
    raise AssertionError(f"{cls_name}.{method_name} not found")


class _ShimZoneAnyone:
    """Shim standing in for ZoneAnyoneBinarySensor for sentinel exec.

    Only the three collaborators is_on touches are stubbed:
      - self._get_zone_coordinators() -> iterable of coordinators with
        `.data` (dict-like) that may carry STATE_OCCUPIED == True.
      - self._sleep_person_fallback_occupied() -> bool
      - self._nonsleep_person_fallback_occupied() -> bool
    """

    def __init__(
        self,
        layer1_rooms: list[bool],
        layer2: bool,
        layer3: bool,
    ) -> None:
        self._layer1_rooms = layer1_rooms
        self._layer2 = layer2
        self._layer3 = layer3

    def _get_zone_coordinators(self):
        for occ in self._layer1_rooms:
            coord = types.SimpleNamespace()
            coord.data = {"occupied": occ} if occ else {}
            yield coord

    def _sleep_person_fallback_occupied(self):
        return self._layer2

    def _nonsleep_person_fallback_occupied(self):
        return self._layer3


def _exec_is_on(agg_src: str, shim: _ShimZoneAnyone) -> bool:
    """Extract ZoneAnyoneBinarySensor.is_on and execute it against the shim."""
    fn = _extract_class_method(agg_src, "ZoneAnyoneBinarySensor", "is_on")
    # Rebuild a plain function (strip decorators, drop @property) so we can
    # call it directly with `shim` as self.
    fn_naked = ast.FunctionDef(
        name=fn.name,
        args=fn.args,
        body=fn.body,
        decorator_list=[],
        returns=fn.returns,
        type_comment=None,
    )
    mod = ast.Module(body=[fn_naked], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: dict = {"STATE_OCCUPIED": "occupied"}
    exec(compile(mod, "<is_on_extract>", "exec"), ns)
    return ns["is_on"](shim)


class TestZoneAnyoneIsOnParity:
    """Sentinel-driven parity: is_on returns True iff any of the 3 layers is True."""

    @pytest.mark.parametrize(
        "layer1_rooms,layer2,layer3,expected",
        [
            ([False, False], False, False, False),  # all-off
            ([True, False], False, False, True),    # Layer 1 hit
            ([False, False], True, False, True),    # Layer 2 hit (sleep trust)
            ([False, False], False, True, True),    # Layer 3 hit (non-sleep trust)
            ([True, False], True, True, True),      # all layers agree
            ([], False, False, False),              # no rooms, no fallback
        ],
    )
    def test_is_on_layers_match(
        self, agg_src: str, layer1_rooms, layer2, layer3, expected
    ):
        shim = _ShimZoneAnyone(layer1_rooms, layer2, layer3)
        assert _exec_is_on(agg_src, shim) is expected

    def test_is_on_still_calls_all_three_layer_helpers(self, agg_src: str):
        """Layer 2/3 helper calls must remain — post-removal parity guard."""
        fn = _extract_class_method(agg_src, "ZoneAnyoneBinarySensor", "is_on")
        src = ast.unparse(fn)
        assert "_sleep_person_fallback_occupied" in src, (
            "Layer 2 (sleep trust) must still be wired in is_on"
        )
        assert "_nonsleep_person_fallback_occupied" in src, (
            "Layer 3 (non-sleep trust) must still be wired in is_on"
        )


# ============================================================================
# 3. Reason ledger — hvac.py preset_change rows carry `reason` + inputs
# ============================================================================


def _extract_fn(src: str, cls_name: str, method_name: str) -> str:
    """Return the unparsed source of a method inside a class."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return ast.unparse(item)
    raise AssertionError(f"{cls_name}.{method_name} not found")


@pytest.fixture(scope="module")
def apply_presets_src(hvac_src: str) -> str:
    return _extract_fn(hvac_src, "HVACCoordinator", "_apply_house_state_presets")


class TestPresetChangeReasonLedger:
    """Every preset_change row must carry `reason` + input booleans.

    Reason vocabulary approved 2026-08-06 (audit §reason-ledger):
      house_state_transition | vacant_past_grace | runtime_exceeded |
      night_trust_suppressed | manual_detected | pre_arrival.
    """

    def test_reason_local_derived_before_write(self, apply_presets_src: str):
        """`preset_change_reason` must be assigned before the set_preset_mode call."""
        # The reason derivation must lexically precede the write. If someone
        # accidentally moves it after the service call, the activity row's
        # details would reference a stale/undefined value.
        assert "preset_change_reason" in apply_presets_src, (
            "reason ledger: `preset_change_reason` local must be derived"
        )
        idx_reason = apply_presets_src.find("preset_change_reason =")
        idx_call = apply_presets_src.find("'set_preset_mode'")
        if idx_call < 0:
            idx_call = apply_presets_src.find('"set_preset_mode"')
        assert idx_reason >= 0 and idx_call >= 0, (
            "expected both reason assignment and set_preset_mode call"
        )
        assert idx_reason < idx_call, (
            "reason must be derived BEFORE the preset_change service call so "
            "the activity/DecisionLog rows record a fresh, branch-derived reason"
        )

    def test_reason_vocabulary_present(self, apply_presets_src: str):
        """Approved reason literals must appear in the derivation block."""
        for literal in (
            "vacant_past_grace",
            "runtime_exceeded",
            "pre_arrival",
            "house_state_transition",
        ):
            assert f"'{literal}'" in apply_presets_src or f'"{literal}"' in apply_presets_src, (
                f"reason vocabulary missing: `{literal}`"
            )

    def test_vacant_past_grace_maps_to_that_reason(self, apply_presets_src: str):
        """Branch integrity: zone_vacant_past_grace → 'vacant_past_grace'."""
        # Match `if effective_preset == "away" and zone_vacant_past_grace`
        # followed within a few lines by the vacant_past_grace literal
        # assignment.
        pattern = re.compile(
            r"zone_vacant_past_grace.*?preset_change_reason\s*=\s*['\"]vacant_past_grace['\"]",
            re.DOTALL,
        )
        assert pattern.search(apply_presets_src), (
            "vacant_past_grace branch must map to reason='vacant_past_grace'"
        )

    def test_runtime_exceeded_maps_to_that_reason(self, apply_presets_src: str):
        pattern = re.compile(
            r"zone\.runtime_exceeded.*?preset_change_reason\s*=\s*['\"]runtime_exceeded['\"]",
            re.DOTALL,
        )
        assert pattern.search(apply_presets_src), (
            "runtime_exceeded branch must map to reason='runtime_exceeded'"
        )

    def test_activity_details_carry_reason_and_inputs(self, apply_presets_src: str):
        """The activity_logger.log details dict must include reason + inputs."""
        # Locate the activity_logger.log call and inspect its details kwarg.
        # We do a text-window scan to keep this robust across minor edits.
        idx = apply_presets_src.find("activity_logger.log")
        assert idx >= 0, "activity_logger.log call missing"
        # 800 char window comfortably spans the log() kwargs block.
        window = apply_presets_src[idx : idx + 1200]
        for key in ("'reason'", "'zone_vacant_past_grace'", "'runtime_exceeded'"):
            assert key in window, (
                f"activity_logger.log details missing `{key}`"
            )
        assert "preset_change_reason" in window, (
            "activity_logger details must reference preset_change_reason local"
        )

    def test_decision_log_context_carries_reason(self, apply_presets_src: str):
        """DecisionLog context dict must include `reason`."""
        idx = apply_presets_src.find("decision_type='preset_change'")
        if idx < 0:
            idx = apply_presets_src.find('decision_type="preset_change"')
        assert idx >= 0, "DecisionLog preset_change block missing"
        window = apply_presets_src[idx : idx + 1200]
        assert "'reason'" in window or '"reason"' in window, (
            "DecisionLog context must include `reason` key"
        )
        assert "preset_change_reason" in window, (
            "DecisionLog context must reference preset_change_reason local"
        )


class TestNightTrustSuppressedRow:
    """Night-trust suppression must fire a preset_change_suppressed row."""

    def test_night_trust_reason_present(self, apply_presets_src: str):
        assert "'night_trust_suppressed'" in apply_presets_src or (
            '"night_trust_suppressed"' in apply_presets_src
        ), "night_trust_suppressed reason literal missing"

    def test_preset_change_suppressed_action_present(self, apply_presets_src: str):
        assert "'preset_change_suppressed'" in apply_presets_src or (
            '"preset_change_suppressed"' in apply_presets_src
        ), (
            "night-trust branch must log a `preset_change_suppressed` activity row"
        )

    def test_suppressed_row_details_carry_reason_and_inputs(
        self, apply_presets_src: str
    ):
        """The suppressed row's details must carry reason + input bools."""
        idx = apply_presets_src.find("preset_change_suppressed")
        assert idx >= 0
        # 1500 char window covers the log() call + kwargs.
        window = apply_presets_src[idx : idx + 1500]
        for key in (
            "'reason'",
            "'night_trust_suppressed'",
            "'zone_vacant_past_grace'",
            "'runtime_exceeded'",
        ):
            assert key in window, (
                f"night-trust suppressed row details missing `{key}`"
            )
