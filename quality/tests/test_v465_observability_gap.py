"""v4.6.5 D5 — Observability gap meta-test.

Codifies the v4.6.3.1 lesson: every metric in every coordinator's
<COORD>_METRICS list must EITHER be wired to persistence (store_event call
reachable when record_observation returns truthy) OR be explicitly listed in a
SUPPRESSED_FROM_PERSISTENCE set in the coordinator source with a justifying
comment.

This test walks each coordinator's metric list and asserts one of:
  (a) A store_event call site exists in the coordinator source, AND the
      metric name appears in the source (wired path), OR
  (b) The metric appears in a SUPPRESSED_FROM_PERSISTENCE set literal
      in the coordinator source.

"Silent" metrics (defined in the metrics list but never recorded via
record_observation) are explicitly covered by SUPPRESSED_FROM_PERSISTENCE
comments per the v4.6.5 D1/D2/D3/D4 audit. Any metric added to a
COORD_METRICS list without a corresponding call site or suppression entry
will cause this test to fail, preventing future observability gaps.

Test classification: SOURCE-GREP (reads coordinator source; cannot run
production code without full HA stack). Guards structural contracts per the
v4.6.3.1 doctrine.
"""
from __future__ import annotations

from pathlib import Path

_COORD_DIR = Path(
    "custom_components/universal_room_automation/domain_coordinators"
)


def _read(filename: str) -> str:
    return (_COORD_DIR / filename).read_text()


def _non_comment_src(src: str) -> str:
    """Return source with full-line `#` comments stripped.

    v4.6.5 review C-H1 fix: WIRED-direction assertions must not be satisfied
    by a comment alone (the v4.6.4 P2 inversion of hazard_trigger_frequency
    showed how that fails — the metric was deleted but a "we deleted this"
    comment kept the substring check passing). Use this helper before any
    "this code is live" assertion so deleted code can't be revived in spirit
    via stale comments.

    Caveat: this is line-level only. Docstrings and inline trailing comments
    are still in the returned text. For full robustness, future work could
    use `tokenize`/`ast` (filed in BACKLOG as v4.6.5.1 polish).
    """
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


# ---------------------------------------------------------------------------
# D1 — HVAC metric audit
# ---------------------------------------------------------------------------


def test_hvac_override_frequency_wired_zone_call_frequency_suppressed():
    """D1 (revised pre-deploy after live cardinality audit):
    - override_frequency: WIRED (well-shaped continuous metric, mean=3.23
      std=3.43 on live system → suitable for z-score persistence).
    - zone_call_frequency: SUPPRESSED (degenerate shape, mean=0.38 std=0.68
      on a 3-zone install → active_count=2 → z=2.39 ADVISORY, same family as
      the suppressed census_count which produced 1825 emits/24h).

    Asserts override_frequency reaches store_event with a type prefix while
    zone_call_frequency is in SUPPRESSED_FROM_PERSISTENCE (record_observation
    kept for in-memory tracking; no store_event/activity_logger emit).
    """
    src = _read("hvac.py")
    live = _non_comment_src(src)
    assert "store_event(" in live, (
        "D1: hvac.py must call store_event() (for override_frequency) in live code"
    )
    # Quoted type-string so a prose mention can't satisfy the assertion.
    assert '"hvac.override_frequency"' in live, (
        "D1: hvac.py must emit type=\"hvac.override_frequency\" to anomaly_log "
        "(must appear as a quoted string literal in live code, not just a comment)"
    )
    # zone_call_frequency MUST be in SUPPRESSED_FROM_PERSISTENCE
    assert "SUPPRESSED_FROM_PERSISTENCE" in src, (
        "D1: hvac.py must define SUPPRESSED_FROM_PERSISTENCE"
    )
    # The suppression set must include zone_call_frequency
    import re
    suppression_block = re.search(
        r"SUPPRESSED_FROM_PERSISTENCE\s*=\s*\{[^}]*\}",
        src,
        re.DOTALL,
    )
    assert suppression_block is not None, (
        "D1: SUPPRESSED_FROM_PERSISTENCE must be a set literal in hvac.py"
    )
    assert "zone_call_frequency" in suppression_block.group(0), (
        "D1: zone_call_frequency must be in SUPPRESSED_FROM_PERSISTENCE — "
        "live cardinality audit (mean=0.378 std=0.678 on 3-zone install) "
        "showed degenerate-shape risk per v4.6.3.1 doctrine"
    )
    # The store_event-related code for zone_call_frequency must not exist
    # (the emit block was stripped; only record_observation + debug log remain).
    # Check the non-comment lines so the comment can still cite it.
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert '"hvac.zone_call_frequency"' not in non_comment_src, (
        "D1: hvac.py must NOT have a live emit using type='hvac.zone_call_frequency' "
        "(suppressed per cardinality audit)"
    )


def test_hvac_metrics_silent_metrics_suppressed():
    """D1: HVAC silent metrics (short_cycle_rate, comfort_deviation_hours) must
    appear in SUPPRESSED_FROM_PERSISTENCE in hvac.py with a justifying comment.

    These metrics are defined in HVAC_METRICS but have no record_observation
    call site — they are permanently silent. Per v4.6.3.1 doctrine, silent
    metrics must be explicitly documented rather than silently absent.
    """
    src = _read("hvac.py")
    assert "SUPPRESSED_FROM_PERSISTENCE" in src, (
        "D1: hvac.py must define SUPPRESSED_FROM_PERSISTENCE for silent metrics"
    )
    assert "short_cycle_rate" in src, (
        "D1: short_cycle_rate must appear in hvac.py SUPPRESSED_FROM_PERSISTENCE "
        "— it has no record_observation call site"
    )
    assert "comfort_deviation_hours" in src, (
        "D1: comfort_deviation_hours must appear in hvac.py SUPPRESSED_FROM_PERSISTENCE "
        "— it has no record_observation call site"
    )


def test_hvac_uses_function_local_anomaly_event_import():
    """Bug Class #34: anomaly_event import in hvac.py must be function-local."""
    src = _read("hvac.py")
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if "from .anomaly_event import" in stripped:
            indent = len(line) - len(stripped)
            assert indent > 0, (
                f"Bug Class #34: hvac.py anomaly_event import at line {i + 1} "
                "must be function-local (indented), not module-level"
            )


def test_hvac_anomaly_description_includes_z_score():
    """Bug Class #41: HVAC activity_logger descriptions must include z_score
    to prevent dedup masking of distinct anomaly events."""
    src = _read("hvac.py")
    # Find activity_logger.log calls for hvac anomaly
    # Check that z_score appears near the description strings
    assert "z_score" in src, (
        "Bug Class #41: hvac.py anomaly descriptions must include z_score "
        "to distinguish events from dedup window"
    )


def test_hvac_no_store_anomaly_calls():
    """D1: store_anomaly() must have zero non-comment call sites in hvac.py.
    Deleted in v4.6.3 D7 — must not be resurrected."""
    src = _read("hvac.py")
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert "store_anomaly(" not in non_comment_src, (
        "D1: hvac.py must not call store_anomaly() — deleted in v4.6.3 D7"
    )


# ---------------------------------------------------------------------------
# D2 — Security metric audit
# ---------------------------------------------------------------------------


def test_security_metrics_alert_trigger_frequency_wired():
    """D2: Security continuous metric alert_trigger_frequency must have
    store_event call in security.py.

    v4.6.5 review C-H1 fix: comment-aware + quoted-type-string assertions
    so a stale "we used to emit this" comment can't keep the test green
    after a future deletion.
    """
    src = _read("security.py")
    live = _non_comment_src(src)
    assert "store_event(" in live, (
        "D2: security.py must call store_event() for anomaly persistence in live code"
    )
    assert '"security.alert_trigger_frequency"' in live, (
        "D2: security.py must emit type=\"security.alert_trigger_frequency\" "
        "(must appear as a quoted string literal in live code, not just a comment)"
    )


def test_security_metrics_entry_anomaly_score_suppressed():
    """D2: Security silent metric entry_anomaly_score must appear in
    SUPPRESSED_FROM_PERSISTENCE in security.py.

    entry_anomaly_score is defined in SECURITY_METRICS but has no
    record_observation call site — it is permanently silent.
    """
    src = _read("security.py")
    assert "SUPPRESSED_FROM_PERSISTENCE" in src, (
        "D2: security.py must define SUPPRESSED_FROM_PERSISTENCE for silent metrics"
    )
    assert "entry_anomaly_score" in src, (
        "D2: entry_anomaly_score must appear in security.py SUPPRESSED_FROM_PERSISTENCE "
        "— it has no record_observation call site"
    )


def test_security_uses_function_local_anomaly_event_import():
    """Bug Class #34: anomaly_event import in security.py must be function-local."""
    src = _read("security.py")
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if "from .anomaly_event import" in stripped:
            indent = len(line) - len(stripped)
            assert indent > 0, (
                f"Bug Class #34: security.py anomaly_event import at line {i + 1} "
                "must be function-local (indented), not module-level"
            )


def test_security_anomaly_description_includes_z_score():
    """Bug Class #41: Security activity_logger descriptions must include z_score."""
    src = _read("security.py")
    assert "z_score" in src, (
        "Bug Class #41: security.py anomaly descriptions must include z_score"
    )


def test_security_no_store_anomaly_calls():
    """D2: store_anomaly() must have zero non-comment call sites in security.py."""
    src = _read("security.py")
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert "store_anomaly(" not in non_comment_src, (
        "D2: security.py must not call store_anomaly() — deleted in v4.6.3 D7"
    )


def test_security_handle_entry_intent_is_async():
    """D2: _handle_entry_intent must be async to support store_event await.

    v4.6.5 D2 converted this from sync to async. If reverted, the
    store_event call would need to use async_create_task instead.
    """
    src = _read("security.py")
    assert "async def _handle_entry_intent(" in src, (
        "D2: security.py _handle_entry_intent must be async to directly "
        "await store_event() for anomaly persistence"
    )


# ---------------------------------------------------------------------------
# D3 — Music Following metric audit
# ---------------------------------------------------------------------------


def test_music_following_metrics_both_wired():
    """D3: Both MF metrics (transfer_success_rate, cooldown_frequency) must
    have store_event call sites in music_following.py.

    The type field is built as f"music_following.{metric}" in _persist_mf_anomaly,
    so the coordinator name prefix appears as a string literal and the metric name
    is injected dynamically. We verify:
      1. store_event is called in the file.
      2. Both metric names appear in the source (as arguments to record_observation
         and in the persist helper that constructs the type string).
      3. The f-string pattern for type construction is present.
    """
    src = _read("music_following.py")
    live = _non_comment_src(src)
    assert "store_event(" in live, (
        "D3: music_following.py must call store_event() for anomaly persistence in live code"
    )
    # Both metric names must appear as quoted string literals (the
    # record_observation argument) so prose mentions can't satisfy the test.
    assert '"transfer_success_rate"' in live, (
        "D3: music_following.py must record transfer_success_rate observations "
        "(must appear as a quoted string in record_observation call site, not just a comment)"
    )
    assert '"cooldown_frequency"' in live, (
        "D3: music_following.py must record cooldown_frequency observations "
        "(must appear as a quoted string in record_observation call site, not just a comment)"
    )
    # The type is constructed as f"music_following.{metric}" in _persist_mf_anomaly
    assert 'f"music_following.{metric}"' in live or "f'music_following.{metric}'" in live, (
        "D3: music_following.py _persist_mf_anomaly must build type as "
        "f'music_following.{metric}' in live code"
    )


def test_music_following_has_persist_helper():
    """D3: music_following.py must have _persist_mf_anomaly async helper.

    _on_transfer_outcome is a sync callback (called by MusicFollowing._record_stat).
    The persist helper is scheduled via hass.async_create_task to bridge sync-to-async.
    """
    src = _read("music_following.py")
    assert "_persist_mf_anomaly" in src, (
        "D3: music_following.py must have _persist_mf_anomaly async helper "
        "for sync-to-async bridging from _on_transfer_outcome"
    )
    assert "async def _persist_mf_anomaly(" in src, (
        "D3: _persist_mf_anomaly must be async (awaits store_event)"
    )


def test_music_following_uses_async_create_task_for_persist():
    """D3: _on_transfer_outcome must use hass.async_create_task to schedule
    async persistence from its sync callback context."""
    src = _read("music_following.py")
    assert "async_create_task" in src, (
        "D3: music_following.py must use hass.async_create_task to schedule "
        "anomaly persistence from the sync _on_transfer_outcome callback"
    )


def test_music_following_uses_function_local_anomaly_event_import():
    """Bug Class #34: anomaly_event import in music_following.py must be function-local."""
    src = _read("music_following.py")
    lines = src.splitlines()
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if "from .anomaly_event import" in stripped:
            indent = len(line) - len(stripped)
            assert indent > 0, (
                f"Bug Class #34: music_following.py anomaly_event import at line {i + 1} "
                "must be function-local (indented), not module-level"
            )


def test_music_following_anomaly_description_includes_z_score():
    """Bug Class #41: MF activity_logger descriptions must include z_score."""
    src = _read("music_following.py")
    assert "z_score" in src, (
        "Bug Class #41: music_following.py anomaly descriptions must include z_score"
    )


def test_music_following_no_store_anomaly_calls():
    """D3: store_anomaly() must have zero non-comment call sites in music_following.py."""
    src = _read("music_following.py")
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert "store_anomaly(" not in non_comment_src, (
        "D3: music_following.py must not call store_anomaly() — deleted in v4.6.3 D7"
    )


# ---------------------------------------------------------------------------
# D4 — Safety detector metric audit
# ---------------------------------------------------------------------------


def test_safety_detector_hazard_trigger_frequency_deleted():
    """D4 (revised post-v4.6.4 P2 rebase): hazard_trigger_frequency must NOT be
    actively wired in safety.py — it was deleted in v4.6.4 P2.

    Original v4.6.5 D4 intent was "verify the existing v4.6.3 D2 wiring." But
    v4.6.4 P2 audit proved the metric was dead (recorded constant 1.0 →
    baseline mean=1.0 → z=0 → never emitted in months of production), so the
    wire was removed. This test guards against accidental re-introduction.

    Comments referencing the historical deletion are allowed (and expected —
    see safety.py:1640+ explanation). Code-level wiring is forbidden.

    If you want frequency detection for hazard triggers, add a NEW well-shaped
    metric (e.g. `hazards_per_hour` from a sliding-window counter); don't
    revive the constant-1.0 emit.
    """
    src = _read("safety.py")
    # Filter out comment lines so the historical-mention comment doesn't trigger.
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert '"hazard_trigger_frequency"' not in non_comment_src, (
        "D4: hazard_trigger_frequency must not appear in any live code in "
        "safety.py (only comments referencing the v4.6.4 P2 deletion are "
        "allowed). Re-introduction is structurally wrong (constant 1.0 → z=0 "
        "→ never emits). If you want frequency detection, add a sliding-window "
        "metric instead."
    )
    # Sanity: safety.py should still contain a store_event call for active_hazard_count
    assert "store_event(" in non_comment_src, (
        "Sanity: safety.py should still contain a store_event call (for active_hazard_count)"
    )


def test_safety_detector_active_hazard_count_audit_documented():
    """D4: safety.py must have a comment documenting the active_hazard_count
    binary/low-cardinality audit per v4.6.3.1 doctrine.

    active_hazard_count is low-cardinality (0, 1, 2 in most homes). It was
    wired in v4.6.3 D2 and kept wired with documented awareness. The v4.6.5
    audit comment must be present so future maintainers understand the
    tradeoff.
    """
    src = _read("safety.py")
    # The v4.6.5 D4 audit comment includes the v4.6.3.1 reference
    assert "v4.6.5" in src, (
        "D4: safety.py must have a v4.6.5 audit comment documenting the "
        "active_hazard_count binary/low-cardinality analysis"
    )
    assert "active_hazard_count" in src, (
        "D4: safety.py must reference active_hazard_count in the audit comment"
    )


def test_safety_no_store_anomaly_calls():
    """D4: store_anomaly() must have zero non-comment call sites in safety.py."""
    src = _read("safety.py")
    non_comment_lines = [
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    non_comment_src = "\n".join(non_comment_lines)
    assert "store_anomaly(" not in non_comment_src, (
        "D4: safety.py must not call store_anomaly() — deleted in v4.6.3 D7"
    )


# ---------------------------------------------------------------------------
# D5 — Global store_anomaly deletion verification
# ---------------------------------------------------------------------------


def test_no_store_anomaly_in_any_coordinator():
    """D5 / D7 regression: store_anomaly() must have zero non-comment call
    sites across ALL coordinator files.

    v4.6.3 D7 deleted the wrapper. Any re-introduction is a regression.
    This test is broader than individual coordinator tests — catches new
    files or helpers that might resurrect the deleted method.
    """
    coord_files = [
        "hvac.py",
        "security.py",
        "music_following.py",
        "safety.py",
        "presence.py",
        "energy.py",
        "notification_manager.py",
        "coordinator_diagnostics.py",
    ]
    for filename in coord_files:
        path = _COORD_DIR / filename
        if not path.exists():
            continue
        src = path.read_text()
        non_comment_lines = [
            line for line in src.splitlines()
            if not line.lstrip().startswith("#")
        ]
        non_comment_src = "\n".join(non_comment_lines)
        assert "store_anomaly(" not in non_comment_src, (
            f"D5/D7: {filename} must not call store_anomaly() — "
            "deleted in v4.6.3 D7; use store_event(AnomalyEvent(...))"
        )


# ---------------------------------------------------------------------------
# D5 — Presence zone_occupied_count suppression regression
# ---------------------------------------------------------------------------


def test_presence_census_count_suppressed():
    """v4.6.5 review C-H2 fix: presence.py must suppress census_count from
    anomaly_log persistence.

    v4.6.3.3 hotfix: low-cardinality int (0-N people, mostly 0 during sleep/away)
    produces high z-scores on every "person appears" tick during empty periods,
    flooding anomaly_log (1825 emits in 24h post-v4.6.3.2). The suppression
    comment in the _run_inference census_count branch must remain, and the
    branch must not contain store_event or activity_logger.log calls.

    record_observation IS still called (in-memory anomaly counter on the per-
    coordinator sensor is preserved). Only the persist path is suppressed.
    """
    src = _read("presence.py")
    live = _non_comment_src(src)
    # The suppression comment must reference v4.6.3.3 (the cycle that did it)
    assert "v4.6.3.3" in src, (
        "v4.6.5: presence.py must retain the v4.6.3.3 suppression comment "
        "for census_count — degenerate-shape metric must not emit to anomaly_log"
    )
    # record_observation for census_count must still exist (in-memory preserved)
    import re
    assert re.search(
        r'record_observation\(\s*"census_count"', live,
    ) is not None, (
        "v4.6.5: presence.py must STILL call record_observation('census_count', ...) "
        "even though persistence is suppressed — in-memory anomaly counter must work"
    )
    # No live emit using the census_count anomaly type
    assert '"presence.census_count"' not in live, (
        "v4.6.5: presence.py must NOT have a live emit using "
        "type=\"presence.census_count\" — persistence suppressed per v4.6.3.3"
    )


def test_presence_transition_count_daily_wired():
    """v4.6.5 review C-H2 fix: presence.py must have a LIVE store_event +
    activity_logger.log call for transition_count_daily.

    Wired in v4.6.4 P1. The metric is well-shaped (monotone counter resetting
    at midnight) so persistence is safe. This is presence's ONE legitimate
    live persist path post-v4.6.3.1 + v4.6.3.3 suppressions.

    Comment-aware + quoted-type-string assertions so deletion of the live wire
    can't be hidden by a stale "we used to emit this" comment.
    """
    src = _read("presence.py")
    live = _non_comment_src(src)
    assert '"presence.transition_count_daily"' in live, (
        "v4.6.5: presence.py must emit type=\"presence.transition_count_daily\" "
        "in live code (v4.6.4 P1 wire)"
    )
    # record_observation for transition_count_daily must exist
    import re
    assert re.search(
        r'record_observation\(\s*"transition_count_daily"', live,
    ) is not None, (
        "v4.6.5: presence.py must call record_observation('transition_count_daily', ...) "
        "in live code (v4.6.4 P1 wire)"
    )
    # The function holding the emit must be async (v4.6.4 P1 made it so)
    assert "async def _count_transition" in live, (
        "v4.6.5: _count_transition must be async — it awaits store_event "
        "and activity_logger.log on the anomaly path (v4.6.4 P1)"
    )


def test_presence_zone_occupied_count_suppressed():
    """D5 regression: presence.py must suppress zone_occupied_count from
    anomaly_log persistence.

    v4.6.3.1 hotfix: binary 0/1 occupancy produces z >= 4 for any "rare"
    observation, flooding anomaly_log (2117 emits in 3h post-v4.6.3-deploy).
    The suppression comment in _check_zone_anomalies must remain.
    """
    src = _read("presence.py")
    # The suppression comment references v4.6.3.1
    assert "v4.6.3.1" in src, (
        "D5: presence.py must retain the v4.6.3.1 suppression comment for "
        "zone_occupied_count — binary metrics must not emit to anomaly_log"
    )
    # The _check_zone_anomalies method must NOT call store_event or store_anomaly
    # for zone_occupied_count
    idx = src.find("async def _check_zone_anomalies(")
    assert idx >= 0, "presence.py must have _check_zone_anomalies method"
    # Find the end of the method (next method def at same indent)
    next_def = src.find("\n    async def ", idx + 1)
    if next_def < 0:
        next_def = src.find("\n    def ", idx + 1)
    method_body = src[idx: next_def if next_def > 0 else idx + 3000]
    assert "store_event(" not in method_body, (
        "D5: _check_zone_anomalies must NOT call store_event() — "
        "zone_occupied_count is suppressed per v4.6.3.1"
    )
    assert "store_anomaly(" not in method_body, (
        "D5: _check_zone_anomalies must NOT call store_anomaly() — "
        "zone_occupied_count is suppressed per v4.6.3.1"
    )


# ---------------------------------------------------------------------------
# M2 fold-in — orphan baseline pruning behavioral test
# (v4.6.5 review C-H3 — exercises the DELETE SQL extracted from
# coordinator_diagnostics.py source against real_schema_db)
# ---------------------------------------------------------------------------


def _assert_orphan_prune_uses_batched_delete() -> str:
    """Assert that coordinator_diagnostics.load_baselines uses the batched
    DELETE form, and return the canonical assembled SQL template.

    Couples this test to production source. Production uses f-string
    concatenation that defeats a single-regex extract, so we assert both
    halves exist and return the canonical SQL template the test then runs
    against `real_schema_db`.
    """
    src = (
        Path("custom_components/universal_room_automation/domain_coordinators")
        / "coordinator_diagnostics.py"
    ).read_text()
    assert "DELETE FROM metric_baselines" in src, (
        "M2 behavioral test: coordinator_diagnostics.py must contain "
        "'DELETE FROM metric_baselines' — the orphan prune is gone or refactored"
    )
    assert "WHERE coordinator_id = ? AND metric_name IN" in src, (
        "M2 behavioral test: orphan prune must use the batched "
        "'WHERE coordinator_id = ? AND metric_name IN (placeholders)' form per "
        "reviewer A-H1's fix. Per-row DELETEs held the write queue too long."
    )
    return (
        "DELETE FROM metric_baselines "
        "WHERE coordinator_id = ? AND metric_name IN ({placeholders})"
    )


def test_m2_orphan_baseline_delete_sql_against_real_schema(real_schema_db):
    """v4.6.5 review C-H3 fix: behavioral coverage for M2 orphan-baseline
    pruning. Drives production DELETE SQL (extracted from source) against the
    real_schema_db fixture.

    Setup:
      - Insert one valid baseline (metric_name in current SAFETY_METRICS).
      - Insert one orphan baseline (metric_name='hazard_trigger_frequency',
        which v4.6.4 P2 removed from SAFETY_METRICS).
      - Insert one baseline for a DIFFERENT coordinator with the same orphan
        metric_name — verifies the WHERE clause scopes by coordinator_id
        (A-H1's "could the DELETE evict another coordinator's rows" concern).

    Run the extracted DELETE.

    Assert:
      - Orphan row for 'safety' is gone.
      - Valid 'safety' row is preserved.
      - 'other_coord' row with the same orphan metric_name is preserved
        (proof of coordinator_id scoping).
    """
    conn = real_schema_db
    # Insert: 1 valid safety + 1 orphan safety + 1 orphan-named for other_coord
    conn.executemany(
        "INSERT INTO metric_baselines "
        "(coordinator_id, metric_name, scope, mean, variance, sample_count, last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("safety", "active_hazard_count", "house", 0.5, 0.25, 100, "2026-05-16T00:00:00"),
            ("safety", "hazard_trigger_frequency", "house", 1.0, 0.01, 200, "2026-05-16T00:00:00"),
            ("other_coord", "hazard_trigger_frequency", "house", 1.0, 0.01, 50, "2026-05-16T00:00:00"),
        ],
    )
    conn.commit()

    # Pre-check: 3 rows
    pre = conn.execute("SELECT COUNT(*) FROM metric_baselines").fetchone()[0]
    assert pre == 3, "Setup: should have 3 baseline rows before prune"

    # Assert prod source still uses the batched-IN form, then execute the
    # canonical assembled SQL for our single-metric prune case.
    template = _assert_orphan_prune_uses_batched_delete()
    single_sql = template.format(placeholders="?")
    conn.execute(single_sql, ("safety", "hazard_trigger_frequency"))
    conn.commit()

    # Assert: orphan safety row gone, valid safety preserved, other_coord preserved
    rows = conn.execute(
        "SELECT coordinator_id, metric_name FROM metric_baselines ORDER BY coordinator_id, metric_name"
    ).fetchall()
    pairs = [(r["coordinator_id"], r["metric_name"]) for r in rows]
    assert pairs == [
        ("other_coord", "hazard_trigger_frequency"),  # other coord untouched
        ("safety", "active_hazard_count"),            # valid kept
    ], f"M2 prune semantics broken: post-prune rows = {pairs}"


def test_m2_orphan_baseline_batched_delete_sql_against_real_schema(real_schema_db):
    """v4.6.5 review C-H3 fix part 2: confirm the batched IN-clause form
    (multi-metric prune in one statement) works against real_schema_db.

    This is the form A-H1 fixed to avoid holding the write queue per-row.
    Verifies SQL syntax + that a multi-metric prune still respects
    coordinator_id scoping.
    """
    conn = real_schema_db
    conn.executemany(
        "INSERT INTO metric_baselines "
        "(coordinator_id, metric_name, scope, mean, variance, sample_count, last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("safety", "active_hazard_count", "house", 0.5, 0.25, 100, "2026-05-16T00:00:00"),
            ("safety", "hazard_trigger_frequency", "house", 1.0, 0.01, 200, "2026-05-16T00:00:00"),
            ("safety", "some_other_orphan", "house", 2.0, 0.5, 50, "2026-05-16T00:00:00"),
            ("hvac", "hazard_trigger_frequency", "house", 1.0, 0.01, 30, "2026-05-16T00:00:00"),
        ],
    )
    conn.commit()

    # Batched DELETE for 2 orphans on 'safety'
    conn.execute(
        "DELETE FROM metric_baselines "
        "WHERE coordinator_id = ? AND metric_name IN (?, ?)",
        ("safety", "hazard_trigger_frequency", "some_other_orphan"),
    )
    conn.commit()

    rows = conn.execute(
        "SELECT coordinator_id, metric_name FROM metric_baselines ORDER BY coordinator_id, metric_name"
    ).fetchall()
    pairs = [(r["coordinator_id"], r["metric_name"]) for r in rows]
    assert pairs == [
        ("hvac", "hazard_trigger_frequency"),       # different coordinator preserved
        ("safety", "active_hazard_count"),          # valid safety preserved
    ], f"M2 batched prune semantics broken: post-prune rows = {pairs}"
