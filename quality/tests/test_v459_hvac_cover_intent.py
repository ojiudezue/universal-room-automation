"""v4.5.9 — HVAC cover dispatch tilt-awareness + intent-respecting management.

Combines two distinct fixes that share the same dataclass + dispatch loop:

1. **Bug Class #33 third hit (dispatch tilt-awareness for HVAC covers):**
   v4.5.0.4 made the per-room cover dispatcher tilt-aware. v4.5.6 made
   the per-room "already in target" gate helpers tilt-aware. Neither
   threaded CONF_COVER_TYPE through `hvac_covers.py:_command_covers`.
   Result on 2026-05-09 18:00 CDT: HVAC reopened Study A and Master
   Bedroom blinds via `cover.open_cover` — venetian blinds raised to
   position=100 with slats stuck at tilt=0 instead of tilting slats
   open at position=0. Live-confirmed.

2. **Indiscriminate intent (user-flagged 2026-05-09):**
   - Closed EVERY discovered cover when conditions converged, regardless
     of whether the room intended the cover to be open.
   - Reopened EVERY cover at 18:00 via `_covers_closed: bool`, including
     covers HVAC didn't close and covers the room never wanted open.
   - Per-room `cover_open_mode = none` rooms were treated identically
     to `at_time` rooms.

v4.5.9 changes:
  - `ManagedCover` dataclass gains `cover_type` + `owning_room_name`
  - `discover_covers` resolves cover_type via three-tier strategy
    (room CONF_COVER_TYPE → entity supported_features bitmask → "shade")
  - `discover_covers` honors per-room `CONF_COVER_HVAC_MANAGED` opt-out
  - Single bool `_covers_closed` replaced with `_hvac_closed: set[str]`
  - Open-after-solar reopens ONLY covers in `_hvac_closed`
  - `_should_hvac_close` per-cover gate consults intent (via
    `RoomAutomation.is_cover_currently_intended_open`) + occupancy +
    manual override
  - `_command_close_one` / `_command_open_one` dispatch the right
    cover.{open,close}_cover[_tilt] service
  - `_is_cover_already_in_target_state` is tilt-aware
  - `get_cover_status` exposes `hvac_closed_set` + `hvac_closed_count`
    diagnostic attrs

Mirror-style tests because hvac_covers.py pulls HA imports that don't
load cleanly in the test env. Same pattern as v4.5.0.4 / v4.5.3 /
v4.5.6 / v4.5.7 / v4.5.8.
"""

from datetime import datetime, timedelta
import pytest


# ---------------------------------------------------------------------------
# Mirror constants (kept in sync with hvac_covers.py + const.py)
# ---------------------------------------------------------------------------

COVER_TYPE_SHADE = "shade"
COVER_TYPE_TILT = "tilt"

OCCUPIED_CLOSE_TEMP_DELTA = 2.0  # °F

_COVER_FEATURE_OPEN_TILT = 128
_COVER_FEATURE_CLOSE_TILT = 256
_COVER_FEATURE_SET_TILT_POSITION = 64
_COVER_FEATURE_TILT_BITS = (
    _COVER_FEATURE_OPEN_TILT
    | _COVER_FEATURE_CLOSE_TILT
    | _COVER_FEATURE_SET_TILT_POSITION
)


# ---------------------------------------------------------------------------
# Mirror helpers — D1 cover_type resolution + dispatch + already-in-target
# ---------------------------------------------------------------------------

class _MockState:
    def __init__(self, state="closed", attributes=None):
        self.state = state
        self.attributes = attributes or {}


def _resolve_cover_type_mirror(entity_state, room_cover_type):
    """Mirror of CoverController._resolve_cover_type."""
    if room_cover_type in (COVER_TYPE_SHADE, COVER_TYPE_TILT):
        return room_cover_type
    if entity_state is None:
        return COVER_TYPE_SHADE
    try:
        features = int(entity_state.attributes.get("supported_features", 0))
    except (TypeError, ValueError):
        features = 0
    has_tilt_bits = bool(features & _COVER_FEATURE_TILT_BITS)
    tilt_pos_present = "current_tilt_position" in entity_state.attributes
    if has_tilt_bits and tilt_pos_present:
        return COVER_TYPE_TILT
    return COVER_TYPE_SHADE


def _is_already_in_target_mirror(entity_state, cover_type, action):
    """Mirror of CoverController._is_cover_already_in_target_state."""
    if entity_state is None:
        return False
    if cover_type == COVER_TYPE_TILT:
        tilt = entity_state.attributes.get("current_tilt_position")
        if tilt is None:
            if action == "close":
                return entity_state.state == "closed"
            if action == "open":
                return entity_state.state == "open"
            return False
        try:
            tp = float(tilt)
        except (TypeError, ValueError):
            return False
        if action == "close":
            return tp <= 5.0
        if action == "open":
            return tp >= 95.0
        return False
    # Shade
    if action == "close" and entity_state.state == "closed":
        return True
    if action == "open" and entity_state.state == "open":
        return True
    return False


def _service_for_action(cover_type, action):
    """Mirror of dispatch in _command_close_one/_command_open_one."""
    if cover_type == COVER_TYPE_TILT:
        return f"{action}_cover_tilt"
    return f"{action}_cover"


# ---------------------------------------------------------------------------
# Mirror helpers — D3 intent predicate (mirrors RoomAutomation method)
# ---------------------------------------------------------------------------

def _intent_predicate_mirror(cover_open_mode, in_open_window, past_close):
    """Mirror of RoomAutomation.is_cover_currently_intended_open."""
    if cover_open_mode == "none":
        return False
    if cover_open_mode == "on_entry":
        return False
    if cover_open_mode in ("at_time", "on_entry_after_time", "at_time_or_on_entry"):
        return in_open_window and not past_close
    return False


# ---------------------------------------------------------------------------
# Mirror helpers — D5 occupancy-aware close gate
# ---------------------------------------------------------------------------

def _should_close_for_occupied_mirror(
    is_occupied, room_temp, target_temp_high, delta_threshold=OCCUPIED_CLOSE_TEMP_DELTA,
):
    """Mirror of CoverController._should_close_for_occupied_room."""
    if not is_occupied:
        return True
    if room_temp is None:
        return True  # No data → defer
    if target_temp_high is None:
        return True  # No setpoint → allow
    try:
        delta = float(room_temp) - float(target_temp_high)
    except (TypeError, ValueError):
        return True
    return delta >= delta_threshold


# ===========================================================================
# Tests
# ===========================================================================

# ---------- D1: cover_type three-tier resolution ----------

class TestCoverTypeResolution:
    """Three-tier resolution: room CONF → feature bitmask → "shade"."""

    def test_room_declared_tilt_wins(self):
        """If room declares tilt, trust it regardless of features."""
        state = _MockState(attributes={"supported_features": 15})  # no tilt bits
        assert _resolve_cover_type_mirror(state, COVER_TYPE_TILT) == COVER_TYPE_TILT

    def test_room_declared_shade_wins(self):
        """If room declares shade, trust it even when features include tilt."""
        state = _MockState(attributes={
            "supported_features": 255,
            "current_tilt_position": 50,
        })
        assert _resolve_cover_type_mirror(state, COVER_TYPE_SHADE) == COVER_TYPE_SHADE

    def test_no_room_decl_features_have_tilt_bits_and_attr_returns_tilt(self):
        """No room cover_type → auto-detect tilt from features+attr."""
        state = _MockState(attributes={
            "supported_features": 255,  # includes tilt bits
            "current_tilt_position": 50,
        })
        assert _resolve_cover_type_mirror(state, None) == COVER_TYPE_TILT

    def test_no_room_decl_features_have_tilt_but_no_attr_returns_shade(self):
        """Features advertise tilt but no current_tilt_position → conservative shade."""
        state = _MockState(attributes={"supported_features": 255})
        assert _resolve_cover_type_mirror(state, None) == COVER_TYPE_SHADE

    def test_no_room_decl_no_tilt_features_returns_shade(self):
        state = _MockState(attributes={"supported_features": 15})
        assert _resolve_cover_type_mirror(state, None) == COVER_TYPE_SHADE

    def test_no_state_returns_shade(self):
        """Missing entity state → defensive default shade."""
        assert _resolve_cover_type_mirror(None, None) == COVER_TYPE_SHADE

    def test_room_invalid_cover_type_falls_back_to_autodetect(self):
        state = _MockState(attributes={
            "supported_features": 255,
            "current_tilt_position": 50,
        })
        assert _resolve_cover_type_mirror(state, "garbage") == COVER_TYPE_TILT


# ---------- D1: dispatch service selection ----------

class TestDispatchServiceSelection:
    def test_tilt_close(self):
        assert _service_for_action(COVER_TYPE_TILT, "close") == "close_cover_tilt"

    def test_tilt_open(self):
        assert _service_for_action(COVER_TYPE_TILT, "open") == "open_cover_tilt"

    def test_shade_close(self):
        assert _service_for_action(COVER_TYPE_SHADE, "close") == "close_cover"

    def test_shade_open(self):
        assert _service_for_action(COVER_TYPE_SHADE, "open") == "open_cover"


# ---------- D1: already-in-target check (tilt-aware) ----------

class TestAlreadyInTargetTiltAware:
    def test_tilt_at_zero_target_close_returns_true(self):
        state = _MockState("closed", {"current_tilt_position": 0})
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "close") is True

    def test_tilt_at_5_target_close_returns_true(self):
        """5 is the threshold — close target satisfied at exactly 5."""
        state = _MockState("closed", {"current_tilt_position": 5})
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "close") is True

    def test_tilt_at_6_target_close_returns_false(self):
        state = _MockState("closed", {"current_tilt_position": 6})
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "close") is False

    def test_tilt_at_97_target_open_returns_true(self):
        state = _MockState("open", {"current_tilt_position": 97})
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "open") is True

    def test_tilt_at_94_target_open_returns_false(self):
        state = _MockState("open", {"current_tilt_position": 94})
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "open") is False

    def test_tilt_no_attr_falls_back_to_state_close(self):
        state = _MockState("closed")  # no current_tilt_position
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "close") is True

    def test_tilt_no_attr_falls_back_to_state_open(self):
        state = _MockState("closed")
        assert _is_already_in_target_mirror(state, COVER_TYPE_TILT, "open") is False

    def test_shade_close_state_closed_returns_true(self):
        state = _MockState("closed", {"current_position": 0})
        assert _is_already_in_target_mirror(state, COVER_TYPE_SHADE, "close") is True

    def test_shade_open_state_open_returns_true(self):
        state = _MockState("open", {"current_position": 100})
        assert _is_already_in_target_mirror(state, COVER_TYPE_SHADE, "open") is True

    def test_shade_close_state_open_returns_false(self):
        state = _MockState("open", {"current_position": 100})
        assert _is_already_in_target_mirror(state, COVER_TYPE_SHADE, "close") is False

    def test_no_state_returns_false(self):
        """Can't verify → don't skip; let the service call go."""
        assert _is_already_in_target_mirror(None, COVER_TYPE_SHADE, "close") is False


# ---------- D3: intent predicate ----------

class TestIntentPredicate:
    def test_mode_none_always_returns_false(self):
        assert _intent_predicate_mirror("none", in_open_window=True, past_close=False) is False

    def test_mode_on_entry_always_returns_false(self):
        """on_entry is occupancy-driven; HVAC can't predict future occupancy → conservative."""
        assert _intent_predicate_mirror("on_entry", in_open_window=True, past_close=False) is False

    def test_mode_at_time_in_window_returns_true(self):
        assert _intent_predicate_mirror("at_time", in_open_window=True, past_close=False) is True

    def test_mode_at_time_before_open_window_returns_false(self):
        assert _intent_predicate_mirror("at_time", in_open_window=False, past_close=False) is False

    def test_mode_at_time_after_close_returns_false(self):
        assert _intent_predicate_mirror("at_time", in_open_window=True, past_close=True) is False

    def test_mode_on_entry_after_time_in_window_returns_true(self):
        assert _intent_predicate_mirror("on_entry_after_time", in_open_window=True, past_close=False) is True

    def test_mode_at_time_or_on_entry_in_window_returns_true(self):
        assert _intent_predicate_mirror("at_time_or_on_entry", in_open_window=True, past_close=False) is True

    def test_unknown_mode_returns_false(self):
        """Defensive default."""
        assert _intent_predicate_mirror("garbage", in_open_window=True, past_close=False) is False


# ---------- D5: occupancy-aware close gate ----------

class TestOccupancyAwareClose:
    def test_vacant_room_always_allows_close(self):
        assert _should_close_for_occupied_mirror(
            is_occupied=False, room_temp=72, target_temp_high=72,
        ) is True

    def test_occupied_room_at_setpoint_blocks_close(self):
        """Occupied + temp == setpoint → delta=0 < 2 → block."""
        assert _should_close_for_occupied_mirror(
            is_occupied=True, room_temp=72, target_temp_high=72,
        ) is False

    def test_occupied_room_one_above_setpoint_blocks_close(self):
        """Occupied + temp = setpoint+1 → delta=1 < 2 → block."""
        assert _should_close_for_occupied_mirror(
            is_occupied=True, room_temp=73, target_temp_high=72,
        ) is False

    def test_occupied_room_at_threshold_allows_close(self):
        """Occupied + temp = setpoint+2 → delta=2 == threshold → allow (>=)."""
        assert _should_close_for_occupied_mirror(
            is_occupied=True, room_temp=74, target_temp_high=72,
        ) is True

    def test_occupied_room_well_above_allows_close(self):
        assert _should_close_for_occupied_mirror(
            is_occupied=True, room_temp=78, target_temp_high=72,
        ) is True

    def test_no_room_temp_data_defers_to_other_gates(self):
        """No data → return True (don't block); other gates can still skip."""
        assert _should_close_for_occupied_mirror(
            is_occupied=True, room_temp=None, target_temp_high=72,
        ) is True

    def test_no_setpoint_data_defers_to_other_gates(self):
        assert _should_close_for_occupied_mirror(
            is_occupied=True, room_temp=78, target_temp_high=None,
        ) is True


# ---------- D2: closed-set lifecycle (semantic mirror) ----------

class _CoverState:
    """Mirror of ManagedCover for set-tracking tests."""
    def __init__(self, entity_id, manual_override_until=""):
        self.entity_id = entity_id
        self.manual_override_until = manual_override_until


class TestClosedSetLifecycle:
    """Verify the open-after-solar branch only reopens HVAC-closed covers
    AND drops covers that the user manually overrode during the closed window."""

    def test_open_phase_only_touches_closed_set(self):
        """Even with 5 covers managed, if HVAC only closed 2, only those
        2 get reopened — not the 3 untouched."""
        all_covers = {f"cover.{i}": _CoverState(f"cover.{i}") for i in range(5)}
        hvac_closed = {"cover.0", "cover.2"}

        # Simulate the open loop
        opened = set()
        for entity_id in list(hvac_closed):
            cover = all_covers.get(entity_id)
            if cover is None:
                hvac_closed.discard(entity_id)
                continue
            if cover.manual_override_until:
                # Manual override → drop, don't open
                hvac_closed.discard(entity_id)
                continue
            opened.add(entity_id)
        hvac_closed.clear()

        assert opened == {"cover.0", "cover.2"}
        assert hvac_closed == set()
        # The 3 untouched covers are not in opened
        assert "cover.1" not in opened
        assert "cover.3" not in opened
        assert "cover.4" not in opened

    def test_manual_override_during_closed_window_drops_from_set(self):
        """User manually re-opened a cover HVAC closed → drop from set; don't reopen."""
        now = datetime(2026, 5, 9, 17, 30)
        future = (now + timedelta(hours=1)).isoformat()
        all_covers = {
            "cover.a": _CoverState("cover.a"),
            "cover.b": _CoverState("cover.b", manual_override_until=future),
        }
        hvac_closed = {"cover.a", "cover.b"}

        opened = set()
        for entity_id in list(hvac_closed):
            cover = all_covers.get(entity_id)
            if cover is None:
                hvac_closed.discard(entity_id)
                continue
            if cover.manual_override_until:
                override_end = datetime.fromisoformat(cover.manual_override_until)
                if now < override_end:
                    hvac_closed.discard(entity_id)
                    continue
            opened.add(entity_id)

        assert opened == {"cover.a"}
        assert "cover.b" not in opened

    def test_cover_removed_from_discovery_drops_from_set(self):
        """Config change removed a cover mid-day → don't error, just drop."""
        all_covers = {"cover.a": _CoverState("cover.a")}
        hvac_closed = {"cover.a", "cover.gone"}  # cover.gone no longer in discovery

        opened = set()
        for entity_id in list(hvac_closed):
            cover = all_covers.get(entity_id)
            if cover is None:
                hvac_closed.discard(entity_id)
                continue
            opened.add(entity_id)

        assert opened == {"cover.a"}
        assert "cover.gone" not in hvac_closed

    def test_set_is_empty_after_open_phase(self):
        all_covers = {"cover.a": _CoverState("cover.a")}
        hvac_closed = {"cover.a"}
        # Open phase processes and clears
        for entity_id in list(hvac_closed):
            cover = all_covers.get(entity_id)
            if cover is None:
                hvac_closed.discard(entity_id)
                continue
        hvac_closed.clear()
        assert hvac_closed == set()


# ---------- D4: opt-out filter (semantic mirror) ----------

class TestOptOutFilter:
    """Per-room CONF_COVER_HVAC_MANAGED=False excludes that room's covers
    from the discovered managed set."""

    def test_optout_room_covers_excluded(self):
        rooms = [
            {"name": "Living Room", "covers": ["cover.living"], "hvac_managed": True},
            {"name": "Master Bedroom", "covers": ["cover.mb"], "hvac_managed": False},  # opt-out
            {"name": "Study A", "covers": ["cover.study"], "hvac_managed": True},
        ]
        managed = []
        for r in rooms:
            if not r["hvac_managed"]:
                continue
            managed.extend(r["covers"])
        assert "cover.living" in managed
        assert "cover.study" in managed
        assert "cover.mb" not in managed

    def test_default_true_includes_room(self):
        """Rooms without explicit hvac_managed default to True (managed)."""
        room = {"name": "Bedroom", "covers": ["cover.b"]}
        hvac_managed = room.get("hvac_managed", True)
        assert hvac_managed is True


# ---------- Source contract: production must implement the mirror ----------

class TestSourceContract:
    @pytest.fixture
    def covers_src(self):
        path = "custom_components/universal_room_automation/domain_coordinators/hvac_covers.py"
        with open(path) as f:
            return f.read()

    @pytest.fixture
    def automation_src(self):
        path = "custom_components/universal_room_automation/automation.py"
        with open(path) as f:
            return f.read()

    def test_managed_cover_dataclass_has_cover_type(self, covers_src):
        """ManagedCover must carry cover_type so dispatch is tilt-aware."""
        idx = covers_src.find("class ManagedCover:")
        assert idx > 0
        body = covers_src[idx:idx + 1500]
        assert "cover_type" in body
        assert "owning_room_name" in body

    def test_resolve_cover_type_method_exists(self, covers_src):
        assert "def _resolve_cover_type" in covers_src

    def test_dispatch_uses_tilt_services_for_tilt_covers(self, covers_src):
        """`_command_close_one`/`_command_open_one` must dispatch tilt
        services when cover_type == "tilt"."""
        for fn_name in ("_command_close_one", "_command_open_one"):
            idx = covers_src.find(f"def {fn_name}")
            assert idx > 0, f"{fn_name} must exist (v4.5.9)"
            body = covers_src[idx:idx + 1500]
            assert "COVER_TYPE_TILT" in body, (
                f"{fn_name} must branch on COVER_TYPE_TILT — Bug Class #33 "
                f"prevention. The HVAC cover dispatch is the third hit of "
                f"this class; this test is the regression net."
            )
            assert "_tilt" in body, (
                f"{fn_name} must call cover.{{open,close}}_cover_tilt for tilt covers"
            )

    def test_already_in_target_check_is_tilt_aware(self, covers_src):
        idx = covers_src.find("def _is_cover_already_in_target_state")
        assert idx > 0, "_is_cover_already_in_target_state must exist (v4.5.9)"
        body = covers_src[idx:idx + 1500]
        assert "current_tilt_position" in body, (
            "Already-in-target check must read current_tilt_position for tilt path"
        )
        # 5/95 thresholds match v4.5.6 + v4.5.0.4 verify path
        assert "5.0" in body
        assert "95.0" in body

    def test_closed_set_replaces_single_bool(self, covers_src):
        """`_hvac_closed: set[str]` must exist; the old `_covers_closed: bool`
        as a runtime field must be gone."""
        assert "_hvac_closed: set[str]" in covers_src, (
            "v4.5.9: per-cover closed-set must replace single bool"
        )
        # The single bool must not be initialized as a runtime field
        assert "self._covers_closed: bool = False" not in covers_src, (
            "v4.5.9: removed `_covers_closed` runtime bool. "
            "Use `_hvac_closed: set[str]` instead."
        )

    def test_should_hvac_close_gate_exists(self, covers_src):
        assert "def _should_hvac_close" in covers_src
        idx = covers_src.find("def _should_hvac_close")
        # Slice to next def/class boundary so the body isn't truncated
        next_def = covers_src.find("\n    def ", idx + 1)
        body = covers_src[idx:next_def] if next_def > 0 else covers_src[idx:idx + 4000]
        # Must consult intent
        assert "is_cover_currently_intended_open" in body, (
            "_should_hvac_close must consult RoomAutomation intent predicate"
        )
        # Must consult occupancy
        assert "_should_close_for_occupied_room" in body, (
            "_should_hvac_close must consult occupancy-aware comfort gate"
        )

    def test_intent_predicate_exists_on_room_automation(self, automation_src):
        assert "def is_cover_currently_intended_open" in automation_src, (
            "RoomAutomation must expose intent predicate for HVAC to call"
        )
        idx = automation_src.find("def is_cover_currently_intended_open")
        body = automation_src[idx:idx + 2500]
        assert "COVER_OPEN_NONE" in body
        assert "COVER_OPEN_ON_ENTRY" in body
        assert "COVER_OPEN_AT_TIME" in body

    def test_conf_cover_hvac_managed_read_in_discover(self, covers_src):
        """Bug Class #32 prevention: form field must have a runtime reader."""
        assert "CONF_COVER_HVAC_MANAGED" in covers_src, (
            "CONF_COVER_HVAC_MANAGED must be imported and read in hvac_covers.py "
            "to satisfy Bug Class #32 (form field with no runtime reader)."
        )
        idx = covers_src.find("def discover_covers")
        body = covers_src[idx:idx + 4000]
        assert "CONF_COVER_HVAC_MANAGED" in body, (
            "discover_covers must read CONF_COVER_HVAC_MANAGED to honor opt-out"
        )

    def test_diagnostic_attrs_exposed(self, covers_src):
        idx = covers_src.find("def get_cover_status")
        assert idx > 0
        body = covers_src[idx:idx + 1500]
        assert "hvac_closed_set" in body, (
            "v4.5.9: get_cover_status must surface hvac_closed_set diagnostic"
        )
        assert "hvac_closed_count" in body
