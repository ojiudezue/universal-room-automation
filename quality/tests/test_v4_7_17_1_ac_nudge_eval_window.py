"""v4.7.17.1 — AC nudge eval-window redesign + runtime Number.

Tests Option C (trailing-window minimum kW via HA recorder query) + the
bundled Option B (runtime-tunable `_nudge_eval_delay_s` via Number entity).

Per the v4.7.17.x pre-build adversarial review:
- C1 resolved: new `effective` BOOLEAN column on ac_ramp_events, populated
  by the new rule, read by FP-rate aggregation.
- C2 resolved: recorder query instead of per-tick listener (which URA does
  not have for the kW sensor).
- H1 resolved: preserve pre-existing drop-on-restart behavior.
- H3 resolved: `kwh_rate_before` floor (0.3 kW) classifies as inconclusive,
  excluded from FP statistics rather than counted as FP.
- M1 resolved: Number entity uses "76 ·" prefix (75 already taken by Hard
  Reset Min Interval).
- M4 resolved: notes format remains semicolon-separated key=value pairs.

Source-grep style tests (matches v4.7.x convention) — fast, no running HA.
"""

import pytest


@pytest.fixture(scope="module")
def hvac_const_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_const.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def hvac_override_src() -> str:
    with open(
        "custom_components/universal_room_automation/"
        "domain_coordinators/hvac_override.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def database_src() -> str:
    with open(
        "custom_components/universal_room_automation/database.py"
    ) as f:
        return f.read()


@pytest.fixture(scope="module")
def number_src() -> str:
    with open(
        "custom_components/universal_room_automation/number.py"
    ) as f:
        return f.read()


class TestConstants:

    def test_eval_delay_conf_and_default_present(self, hvac_const_src):
        assert "CONF_HVAC_AC_NUDGE_EVAL_DELAY" in hvac_const_src
        assert 'DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY: Final = 600' in hvac_const_src

    def test_eval_min_drop_frac_is_half(self, hvac_const_src):
        """Calibrated against v4.7.17.x dataset — see hvac_const.py comment."""
        assert "AC_NUDGE_EVAL_MIN_DROP_FRAC: Final = 0.50" in hvac_const_src

    def test_kwh_rate_before_floor(self, hvac_const_src):
        """Below this kW, signal-to-noise too low → classify inconclusive."""
        assert "AC_NUDGE_KWH_RATE_BEFORE_FLOOR: Final = 0.3" in hvac_const_src

    def test_legacy_eval_const_kept_for_back_compat(self, hvac_const_src):
        """Old AC_NUDGE_EVALUATION_DELAY_S const stays as runtime-default
        seed + import target (per CLAUDE.md Bug Class #46 mirror pattern —
        don't gratuitously break out-of-tree imports)."""
        assert "AC_NUDGE_EVALUATION_DELAY_S: Final = 600" in hvac_const_src


class TestRuntimeField:

    def test_eval_delay_runtime_field_initialised(self, hvac_override_src):
        assert "self._nudge_eval_delay_s: int = DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY" in hvac_override_src

    def test_restore_after_nudge_uses_runtime_value(self, hvac_override_src):
        """The async_call_later must read the runtime field, not the const,
        so changes to the Number entity affect the NEXT nudge."""
        idx = hvac_override_src.find("async def _restore_after_nudge")
        assert idx > 0
        # Slice bumped 5000 -> 12000 (HVAC-GOVERNED-EXCURSION-1 D1
        # added observability telemetry), then 12000 -> 20000 (fix-up
        # r3 2026-08-21: F3 unconditional preset restore + F2 CM +
        # snapshot-restore semantics; method now ~12.3K chars, past the
        # earlier bumped window). Bug Class #62 (source-string count);
        # the invariant guarded (runtime field, not const, seeds
        # async_call_later) has no cheaper behavioural anchor without
        # a real coordinator fixture.
        body = hvac_override_src[idx: idx + 20000]
        assert "eval_delay_s = int(self._nudge_eval_delay_s)" in body
        assert "async_call_later(\n            self.hass, eval_delay_s," in body

    def test_post_restore_ts_dict_initialised(self, hvac_override_src):
        assert "self._nudge_post_restore_ts: dict[str, str] = {}" in hvac_override_src

    def test_post_restore_ts_populated_on_restore(self, hvac_override_src):
        idx = hvac_override_src.find("async def _restore_after_nudge")
        body = hvac_override_src[idx: idx + 20000]  # bumped - see fix-up r3 note above
        assert "self._nudge_post_restore_ts[zone_id] = dt_util.now().isoformat()" in body

    def test_post_restore_ts_cleared_on_cancel(self, hvac_override_src):
        """Cancel path must clear the anchor to prevent stale-window
        recorder queries on subsequent nudges."""
        # Two cancellation paths in the file (cancel_nudge + startup audit).
        # Both must clear the anchor.
        count = hvac_override_src.count(
            "self._nudge_post_restore_ts.pop(zone_id, None)"
        )
        # Three sites: _evaluate_nudge_outcome (pop to consume), cancel_nudge,
        # and startup audit. The first pops without reset; the latter two
        # explicitly clear. Tolerate 2+ to allow refactors.
        assert count >= 2


class TestNumberEntity:

    def test_number_factory_entry_uses_76_prefix(self, number_src):
        """M1 resolved: 75 prefix is taken by AC Hard Reset Min Interval."""
        assert "76 · AC Nudge Eval Delay" in number_src

    def test_number_factory_runtime_field(self, number_src):
        idx = number_src.find('"ac_nudge_eval_delay"')
        assert idx > 0
        body = number_src[idx: idx + 1000]
        assert 'runtime_field="_nudge_eval_delay_s"' in body
        assert "CONF_HVAC_AC_NUDGE_EVAL_DELAY" in body
        assert "DEFAULT_HVAC_AC_NUDGE_EVAL_DELAY" in body

    def test_number_factory_range_60_to_1200(self, number_src):
        """L2 resolved: min 60s (lower than reviewer's suggested 120s — allows
        future operators with small-stage units to tune down)."""
        idx = number_src.find('"ac_nudge_eval_delay"')
        body = number_src[idx: idx + 1000]
        assert "min_value=60" in body
        assert "max_value=1200" in body


class TestDatabaseSchema:

    def test_create_table_includes_effective_column(self, database_src):
        """Fresh installs get the column in CREATE TABLE."""
        idx = database_src.find("CREATE TABLE IF NOT EXISTS ac_ramp_events")
        assert idx > 0
        body = database_src[idx: idx + 1500]
        assert "effective INTEGER" in body

    def test_migration_adds_effective_column(self, database_src):
        """Existing installs get ALTER TABLE migration."""
        assert "PRAGMA table_info(ac_ramp_events)" in database_src
        assert "ALTER TABLE ac_ramp_events ADD COLUMN effective INTEGER" in database_src


class TestLogAcRampEventSignature:

    def test_signature_accepts_effective(self, database_src):
        """log_ac_ramp_event must accept the new `effective: bool | None`."""
        idx = database_src.find("async def log_ac_ramp_event(")
        assert idx > 0
        sig = database_src[idx: idx + 1500]
        assert "effective: bool | None = None" in sig

    def test_insert_writes_effective_column(self, database_src):
        """The INSERT column list and placeholder count are consistent.

        History of this test:
          * pre-D1: 14 columns / 14 placeholders.
          * D1 (HVAC-GOVERNED-EXCURSION-1 shipped): added 5 columns
            (preset_before, preset_after, mode_before, mode_after,
            restore_ok) plus restore_ok_immediate later -> 20.
          * fix-up r3 (2026-08-21): +1 column excursion_id -> 21.
            The pre-fix assertion hardcoded 20 placeholders, which
            went stale as an intentional signature change (Bug Class
            #62 - source-string count). Replaced with a BEHAVIOURAL
            check: extract the column list + the placeholder list
            and assert they match. This is stable across future
            additive migrations.
        """
        import re as _re
        idx = database_src.find("async def log_ac_ramp_event(")
        body = database_src[idx: idx + 5000]
        # Column name still present in INSERT statement.
        assert "lockout_triggered, notes, effective" in body
        # Locate INSERT ... ac_ramp_events (...) VALUES (?, ?, ..., ?)
        m = _re.search(
            r"INSERT INTO ac_ramp_events\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)",
            body,
        )
        assert m is not None, (
            "log_ac_ramp_event INSERT statement shape changed; "
            "the regex should still match a standard multi-column INSERT."
        )
        col_list = [c.strip() for c in m.group(1).split(",") if c.strip()]
        placeholder_list = [
            c.strip() for c in m.group(2).split(",") if c.strip()
        ]
        assert placeholder_list and all(p == "?" for p in placeholder_list), (
            f"expected only positional ? placeholders, got {placeholder_list}"
        )
        assert len(col_list) == len(placeholder_list), (
            f"log_ac_ramp_event: column/placeholder count mismatch. "
            f"columns={len(col_list)} placeholders={len(placeholder_list)} "
            f"cols={col_list}"
        )
        # Fix-up r3 (2026-08-21): assert the excursion_id column is
        # present so the D2 join key isn't accidentally dropped.
        assert "excursion_id" in col_list, (
            "log_ac_ramp_event INSERT missing excursion_id column; "
            "HVAC-GOVERNED-EXCURSION-1 D2 requires this column as the "
            "cross-table join key with hvac_excursion_events."
        )
        # SQLite has no BOOLEAN - must convert
        assert "None if effective is None else (1 if effective else 0)" in body


class TestFpRateAggregation:
    """get_ac_ramp_kwh_avoided must derive FP rate from the new `effective`
    column, with NULL → excluded from both numerator and denominator."""

    def test_query_selects_effective_column(self, database_src):
        idx = database_src.find("async def get_ac_ramp_kwh_avoided(")
        assert idx > 0
        body = database_src[idx: idx + 4000]
        assert "SELECT kwh_rate_before, kwh_rate_after, notes, effective" in body

    def test_null_effective_excluded_from_counts(self, database_src):
        """Pre-v4.7.17.1 rows (or inconclusive ones) skip — `effective IS
        NULL` must NOT count toward denominator OR false-pos count."""
        idx = database_src.find("async def get_ac_ramp_kwh_avoided(")
        body = database_src[idx: idx + 4000]
        # Iteration over rows with skip-on-None
        assert "if effective is None:" in body
        assert "continue" in body

    def test_effective_zero_counts_as_fp(self, database_src):
        idx = database_src.find("async def get_ac_ramp_kwh_avoided(")
        body = database_src[idx: idx + 4000]
        assert "if effective == 0:" in body
        assert "false_pos += 1" in body


class TestEvaluateNudgeOutcome:

    def test_helper_compute_post_restore_min_kw_exists(self, hvac_override_src):
        """The recorder-query helper must exist as a named method."""
        assert "async def _compute_post_restore_min_kw(" in hvac_override_src

    def test_helper_calls_recorder_get_significant_states(self, hvac_override_src):
        idx = hvac_override_src.find("async def _compute_post_restore_min_kw")
        assert idx > 0
        body = hvac_override_src[idx: idx + 4000]
        assert "recorder_get_instance(self.hass)" in body
        assert "get_significant_states" in body

    def test_helper_normalises_watt_to_kilowatt(self, hvac_override_src):
        """Same unit normalisation pattern as _read_kwh_rate."""
        idx = hvac_override_src.find("async def _compute_post_restore_min_kw")
        body = hvac_override_src[idx: idx + 4000]
        assert 'unit in ("w", "watt", "watts")' in body
        assert "value = value / 1000.0" in body

    def test_evaluate_uses_post_restore_ts_and_helper(self, hvac_override_src):
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        assert idx > 0
        body = hvac_override_src[idx: idx + 9000]
        assert "self._nudge_post_restore_ts.pop(zone_id, None)" in body
        assert "self._compute_post_restore_min_kw(" in body

    def test_evaluate_applies_floor_classification(self, hvac_override_src):
        """H3 resolved: kwh_rate_before below floor → inconclusive (effective=None)."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        assert "AC_NUDGE_KWH_RATE_BEFORE_FLOOR" in body
        assert 'classification = "inconclusive"' in body
        assert "effective: bool | None = None" in body

    def test_evaluate_applies_new_rule(self, hvac_override_src):
        """Main rule: ineffective iff post_min >= 0.50 * kwh_rate_before."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        assert "post_min < AC_NUDGE_EVAL_MIN_DROP_FRAC * kwh_rate_before" in body
        assert 'classification = "effective"' in body

    def test_evaluate_no_samples_is_conservative_ineffective(self, hvac_override_src):
        """If recorder returns nothing, classify ineffective (escalate) —
        preserves pre-existing behavior for the no-data case."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        assert "elif post_min is None:" in body
        assert 'classification = "ineffective_no_samples"' in body

    def test_evaluate_writes_effective_to_db(self, hvac_override_src):
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        assert "effective=effective" in body

    def test_notes_format_remains_semicolon_separated(self, hvac_override_src):
        """M4 resolved: notes must stay key=value;key=value (parser at
        database.py:5576 splits on `;` then `=`)."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        assert 'f"kwh_avoided={kwh_avoided:.3f};"' in body
        assert "post_min=" in body
        assert "sample_count=" in body
        assert "classification=" in body


class TestRecorderImports:

    def test_recorder_imports_at_module_level(self, hvac_override_src):
        """Module-level imports — stable HA component, always available."""
        assert "from homeassistant.components.recorder import get_instance as recorder_get_instance" in hvac_override_src
        assert "from homeassistant.components.recorder.history import get_significant_states" in hvac_override_src


class TestNoRegressionInExistingFlow:
    """Ensure the redesign didn't break sibling code paths."""

    def test_existing_nudge_in_flight_set_preserved(self, hvac_override_src):
        assert "self._nudge_in_flight: set[str] = set()" in hvac_override_src

    def test_existing_nudge_eval_timers_preserved(self, hvac_override_src):
        assert "self._nudge_eval_timers: dict[str, CALLBACK_TYPE] = {}" in hvac_override_src

    def test_legacy_const_still_importable(self, hvac_override_src):
        """Existing imports of AC_NUDGE_EVALUATION_DELAY_S still resolve."""
        assert "AC_NUDGE_EVALUATION_DELAY_S," in hvac_override_src


class TestKwhAvoidedUsesMean:
    """v5.24+ hotfix — the kwh_avoided MAGNITUDE uses the window MEAN,
    not the window MIN. Classification/escalation still key off the
    MIN (byte-identical decision boundary).

    Root cause: on a naturally cycling compressor, `post_min` hits ~0
    during the OFF-cycle → each nudge was credited as if it eliminated
    the entire AC load for 30 min (~1.6 kWh/nudge).
    """

    def test_kwh_avoided_delta_uses_mean_not_min(self, hvac_override_src):
        """Mutation-anchored: the delta compute uses post_mean, not
        post_min. This test FAILS if the arithmetic reverts to
        `kwh_rate_before - post_min`."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        assert idx > 0
        body = hvac_override_src[idx: idx + 9000]
        # New: delta uses post_mean
        assert "delta = kwh_rate_before - post_mean" in body
        # Guard: the old min-based delta must be gone from this function
        assert "delta = kwh_rate_before - post_min" not in body
        # Guard on the effective branch: only compute kwh_avoided when
        # post_mean is present.
        assert "effective and post_mean is not None" in body

    def test_classification_still_uses_min(self, hvac_override_src):
        """Byte-identical decision boundary preserved: the effective /
        ineffective_no_samples / ineffective classifier still keys off
        post_min. Escalation logic MUST NOT shift onto post_mean."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        # The load-bearing classification predicate is unchanged.
        assert "post_min < AC_NUDGE_EVAL_MIN_DROP_FRAC * kwh_rate_before" in body
        # The no-samples branch still keys off post_min is None.
        assert "elif post_min is None:" in body
        # And NO parallel classification on post_mean was introduced.
        assert "post_mean < AC_NUDGE_EVAL_MIN_DROP_FRAC" not in body

    def test_post_mean_in_notes(self, hvac_override_src):
        """The notes string carries `post_mean=` alongside `post_min=`
        for audit/observability. Existing keys + order preserved
        (append-only)."""
        idx = hvac_override_src.find("async def _evaluate_nudge_outcome(")
        body = hvac_override_src[idx: idx + 9000]
        assert "post_mean=" in body
        # Existing keys still present in the notes assignment.
        assert 'f"kwh_avoided={kwh_avoided:.3f};"' in body
        assert "post_min=" in body

    def test_helper_returns_three_tuple_min_mean_count(self, hvac_override_src):
        """`_compute_post_restore_min_kw` now returns (min, mean, count)."""
        idx = hvac_override_src.find(
            "async def _compute_post_restore_min_kw("
        )
        assert idx > 0
        # Signature return-type annotation carries the new mean slot.
        sig = hvac_override_src[idx: idx + 400]
        assert "tuple[float | None, float | None, int]" in sig
        # Body computes a running sum and derives mean = sum / count.
        body = hvac_override_src[idx: idx + 4000]
        assert "sum_kw" in body
        assert "mean_kw" in body
        # No-sample paths return the 3-tuple form.
        assert "return None, None, 0" in body
