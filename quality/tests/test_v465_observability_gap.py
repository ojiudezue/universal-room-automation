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
    """Return source with full-line `#` comments stripped (legacy behavior).

    Preserved under its original name so existing tests that check for quoted
    string literals (e.g. `"hvac.override_frequency"`) continue to work — a
    tokenizer-based stripper would discard string literals entirely and false-
    negative those assertions.

    Use this for "this quoted-string literal appears in live code" checks.
    For identifier/method-name negative assertions where docstring leakage is
    a concern, use `_non_string_src` (tokenizer-based) instead.
    """
    return "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )


def _non_string_src(src: str) -> str:
    """Return source with comments AND string literals stripped — leaves only
    bare code tokens (identifiers, operators, numbers, statement breaks).

    v4.6.5.1 P3 (review C-M2/M4 follow-up): the line-level filter above leaves
    docstrings and inline trailing comments intact. For negative assertions
    like "this method/identifier must NOT appear in live code", a docstring
    or trailing comment that mentions the identifier would silently satisfy
    the check and let a regression slip through.

    Uses the `tokenize` module to walk Python tokens and emit only NAME, OP,
    NUMBER, and structural tokens — discarding COMMENT and STRING tokens
    entirely. Output is whitespace-joined; line numbers and formatting are
    NOT preserved.

    Use this for identifier/method-name checks. Do NOT use this for assertions
    that look for a specific string literal (e.g. `"hvac.foo"`) — those
    literals are gone from the output by design.
    """
    import io
    import tokenize

    keep_tokens: list[str] = []
    try:
        readline = io.StringIO(src).readline
        for tok in tokenize.generate_tokens(readline):
            tok_type = tok.type
            tok_str = tok.string
            if tok_type in (tokenize.COMMENT, tokenize.STRING):
                continue
            if tok_type in (
                tokenize.NAME,
                tokenize.OP,
                tokenize.NUMBER,
                tokenize.NEWLINE,
                tokenize.NL,
                tokenize.INDENT,
                tokenize.DEDENT,
            ):
                if tok_str:
                    keep_tokens.append(tok_str)
    except tokenize.TokenizeError:
        # Defensive fallback if a source file has a tokenize anomaly
        return _non_comment_src(src)
    return " ".join(keep_tokens)


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
    # zone_call_frequency MUST be in HVAC_SUPPRESSED_FROM_PERSISTENCE
    # (v4.6.5.1 P2: constant promoted from inline set in hvac.py to
    # module-level in hvac_const.py).
    const_src = _read("hvac_const.py")
    assert "HVAC_SUPPRESSED_FROM_PERSISTENCE" in const_src, (
        "D1: hvac_const.py must define HVAC_SUPPRESSED_FROM_PERSISTENCE"
    )
    suppressed = _parse_list_literal(const_src, "HVAC_SUPPRESSED_FROM_PERSISTENCE")
    assert "zone_call_frequency" in suppressed, (
        "D1: zone_call_frequency must be in HVAC_SUPPRESSED_FROM_PERSISTENCE — "
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
    appear in HVAC_SUPPRESSED_FROM_PERSISTENCE in hvac_const.py with a justifying
    comment.

    These metrics are defined in HVAC_METRICS but have no record_observation
    call site — they are permanently silent. Per v4.6.3.1 doctrine, silent
    metrics must be explicitly documented rather than silently absent.

    v4.6.5.1 P2: constant lives in hvac_const.py (module-level) rather than
    inline in hvac.py, so the parametric meta-test can introspect it.
    """
    const_src = _read("hvac_const.py")
    assert "HVAC_SUPPRESSED_FROM_PERSISTENCE" in const_src, (
        "D1: hvac_const.py must define HVAC_SUPPRESSED_FROM_PERSISTENCE for silent metrics"
    )
    suppressed = _parse_list_literal(const_src, "HVAC_SUPPRESSED_FROM_PERSISTENCE")
    # HVAC-ANOMALY-BLIND-1 D2: short_cycle_rate is now WIRED (event-driven
    # per-zone daily producer in hvac.py) and REMOVED from the suppressed
    # set — its per-day cardinality is well-conditioned (measured std
    # 0.78-1.71). The forward-compatible `test_every_metric_is_wired_or_suppressed`
    # holds the invariant that every HVAC_METRICS entry is EITHER wired OR
    # suppressed, so removing the assertion for a now-wired metric here
    # does not weaken coverage.
    assert "short_cycle_rate" not in suppressed, (
        "HVAC-ANOMALY-BLIND-1 D2: short_cycle_rate is now wired via an "
        "event-driven per-zone daily producer and must NOT be in "
        "HVAC_SUPPRESSED_FROM_PERSISTENCE."
    )
    assert "comfort_deviation_hours" in suppressed, (
        "D1: comfort_deviation_hours must appear in HVAC_SUPPRESSED_FROM_PERSISTENCE "
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


# ---------------------------------------------------------------------------
# v4.6.5.1 P2 — Parametric metric audit
# Walks each coordinator's *_METRICS constant and its companion
# *_SUPPRESSED_FROM_PERSISTENCE constant, asserts every metric is either
# wired (has a record_observation call) or explicitly suppressed.
# Forward-compat: a future-added metric must be EITHER wired OR explicitly
# suppressed — it can't slip in silently.
# ---------------------------------------------------------------------------


def _parse_list_literal(src: str, var_name: str) -> set[str]:
    """Parse a Python `var_name = [...]` literal from source text and return
    the contents as a set of string members.

    Used to introspect *_METRICS and *_SUPPRESSED_FROM_PERSISTENCE constants
    without importing the coordinator modules (which would require the HA
    stack at test time).
    """
    import re
    # Match either list [...] or frozenset({...}) literal after the var name
    pattern = rf"{re.escape(var_name)}\s*(?::\s*[\w\[\]., ]+\s*)?=\s*"
    m = re.search(pattern, src)
    if not m:
        return set()
    # Find the matching bracket
    start = m.end()
    # Skip 'frozenset(' wrapper if present
    if src[start : start + len("frozenset(")] == "frozenset(":
        start += len("frozenset(")
        # Handle empty frozenset() — next char is `)` directly
        if src[start] == ")":
            return set()
    open_char = src[start]
    if open_char not in "[{(":
        return set()
    close_char = {"[": "]", "{": "}", "(": ")"}[open_char]
    depth = 1
    i = start + 1
    while i < len(src) and depth > 0:
        if src[i] == open_char:
            depth += 1
        elif src[i] == close_char:
            depth -= 1
        i += 1
    body = src[start + 1 : i - 1]
    # Extract quoted string members
    return set(re.findall(r"""['"]([^'"]+)['"]""", body))


_AUDIT_SPEC = [
    # (coordinator_name, metrics_source_file, metrics_var, suppression_source_file, suppression_var)
    # hvac_const.py is in domain_coordinators/ alongside hvac.py
    ("hvac", "hvac_const.py", "HVAC_METRICS", "hvac_const.py", "HVAC_SUPPRESSED_FROM_PERSISTENCE"),
    ("security", "security.py", "SECURITY_METRICS", "security.py", "SECURITY_SUPPRESSED_FROM_PERSISTENCE"),
    ("music_following", "music_following.py", "MUSIC_FOLLOWING_METRICS", "music_following.py", "MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE"),
    ("presence", "presence.py", "PRESENCE_METRICS", "presence.py", "PRESENCE_SUPPRESSED_FROM_PERSISTENCE"),
    ("safety", "safety.py", "SAFETY_METRICS", "safety.py", "SAFETY_SUPPRESSED_FROM_PERSISTENCE"),
]


def _resolve(relpath: str) -> Path:
    """Resolve a file path relative to _COORD_DIR."""
    return _COORD_DIR / relpath


def test_every_metric_is_wired_or_suppressed():
    """v4.6.5.1 P2 (review C-M1 fix): forward-compatible audit that EVERY
    metric in EVERY coordinator's METRICS list is either wired or explicitly
    suppressed.

    For each (coordinator, METRICS constant, SUPPRESSED constant) tuple in
    _AUDIT_SPEC:
      - Parse METRICS list and SUPPRESSED frozenset from source
      - For each metric: it must be in SUPPRESSED OR appear as the first
        positional argument to a record_observation(...) call in the
        coordinator source file

    Without this test, a future cycle that adds a new metric to <COORD>_METRICS
    but forgets to either wire it or suppress it would slip through — exactly
    the failure mode v4.6.5 review C-M1 flagged. With this test, the cycle
    has to make an explicit decision and the meta-test holds the line.

    Coordinator source file is read for record_observation site detection
    (the wire signal). The metric must appear as a quoted string literal
    in a record_observation call. Live code only — comments stripped via
    _non_comment_src (line-level filter, preserves string literals).
    """
    import re
    failures: list[str] = []
    for coord_name, metrics_file, metrics_var, supp_file, supp_var in _AUDIT_SPEC:
        metrics_src = _resolve(metrics_file).read_text()
        supp_src = (
            metrics_src if supp_file == metrics_file
            else _resolve(supp_file).read_text()
        )
        metrics = _parse_list_literal(metrics_src, metrics_var)
        suppressed = _parse_list_literal(supp_src, supp_var)

        if not metrics:
            failures.append(
                f"{coord_name}: failed to parse {metrics_var} from {metrics_file}"
            )
            continue

        # Suppression set must be a subset of METRICS (no orphan suppressions)
        orphan_suppressions = suppressed - metrics
        if orphan_suppressions:
            failures.append(
                f"{coord_name}: {supp_var} contains metrics not in {metrics_var}: "
                f"{sorted(orphan_suppressions)}"
            )

        # The COORDINATOR source file (where record_observation lives) — for
        # hvac, this is hvac.py (NOT hvac_const.py where the metrics live).
        coord_source_file = {
            "hvac": "hvac.py",
            "security": "security.py",
            "music_following": "music_following.py",
            "presence": "presence.py",
            "safety": "safety.py",
        }[coord_name]
        coord_src = _non_comment_src(_read(coord_source_file))

        for metric in sorted(metrics):
            if metric in suppressed:
                continue  # Explicitly suppressed — OK
            # Otherwise must have a record_observation call site
            pattern = rf'record_observation\(\s*["\']{re.escape(metric)}["\']'
            if not re.search(pattern, coord_src):
                failures.append(
                    f"{coord_name}.{metric} is in {metrics_var} but has no "
                    f"record_observation call site in {coord_source_file} AND "
                    f"is not in {supp_var}. Wire it or suppress it."
                )

    assert not failures, (
        "Forward-compat metric audit failed — every metric must be wired or "
        "suppressed (v4.6.3.1 doctrine):\n  - " + "\n  - ".join(failures)
    )


def test_all_suppression_constants_are_frozenset():
    """v4.6.5.1 P2: every *_SUPPRESSED_FROM_PERSISTENCE constant must be a
    frozenset literal (immutable) to prevent accidental mutation at runtime.

    Asserted via source-grep on each suppression-source file: the assignment
    must use `frozenset(` (allows `frozenset()` for empty, `frozenset({...})`
    for non-empty).
    """
    failures: list[str] = []
    for coord_name, _mfile, _mvar, supp_file, supp_var in _AUDIT_SPEC:
        src = _resolve(supp_file).read_text()
        import re
        pattern = rf"{re.escape(supp_var)}\s*(?::\s*[\w\[\]., ]+\s*)?=\s*frozenset\("
        if not re.search(pattern, src):
            failures.append(
                f"{coord_name}: {supp_var} in {supp_file} must be a frozenset literal"
            )
    assert not failures, (
        "Suppression-constant immutability check failed:\n  - "
        + "\n  - ".join(failures)
    )


def test_hvac_override_frequency_emits_delta_not_cumulative():
    """v4.6.5.1 P1 (review B-M2 fix): hvac.py override_frequency emit must
    pass the per-cycle DELTA (today's overrides minus last cycle's), not the
    raw cumulative total_overrides.

    Pre-v4.6.5.1 the emit passed cumulative `total_overrides` which resets
    at midnight — late-day high values produced ADVISORY z-fires just from
    natural accumulation (the v4.6.3.1 cumulative-counter-misclassified-as-
    continuous class). Post-v4.6.5.1 the emit passes `delta`, which is
    stable-variance through the day.

    Asserts (source-grep):
      - hvac.py tracks `_last_total_overrides_observed` instance state.
      - record_observation("override_frequency", ...) passes a name
        containing "delta" (not "total_overrides").
      - The reset-detection (`delta < 0`) path skips the observation.
    """
    src = _read("hvac.py")
    live = _non_comment_src(src)
    assert "_last_total_overrides_observed" in live, (
        "v4.6.5.1 P1: hvac.py must track _last_total_overrides_observed "
        "instance state to compute per-cycle delta"
    )
    # The record_observation for override_frequency must use the delta value,
    # not the raw cumulative total. Match the call site.
    import re
    m = re.search(
        r'record_observation\(\s*"override_frequency"\s*,\s*"house"\s*,\s*float\((\w+)\)',
        live,
    )
    assert m is not None, (
        "v4.6.5.1 P1: hvac.py must have record_observation("
        "\"override_frequency\", \"house\", float(<var>)) with the delta as <var>"
    )
    observed_var = m.group(1)
    assert observed_var == "delta", (
        f"v4.6.5.1 P1: override_frequency record_observation must pass `delta` "
        f"(per-cycle change), not `{observed_var}` (cumulative count). The "
        f"sawtooth shape of total_overrides fires ADVISORY at late-day values."
    )
    # Reset detection must skip the observation
    assert "if delta < 0:" in live, (
        "v4.6.5.1 P1: hvac.py must detect daily reset (delta < 0) and skip "
        "the observation to avoid polluting baseline with the reset artifact"
    )


# ---------------------------------------------------------------------------
# v4.6.5.1 P4 — _transitions_today RestoreEntity hydration (M3 from v4.6.4)
# ---------------------------------------------------------------------------


def test_presence_hydrates_transitions_today_from_house_state_log():
    """v4.6.5.1 P4 (review M3 from v4.6.4): PresenceCoordinator.async_setup
    must hydrate `_transitions_today` from `house_state_log` so the daily
    counter survives reload/restart.

    Pre-fix: the counter resets to 0 on every restart → `transition_count_daily`
    baseline distribution skews low → future thrashy-day anomalies fire more
    often than they should.

    Asserts (source-grep + DAO presence):
      - database.py defines `count_house_state_changes_since(self, since_iso)` DAO
      - The DAO uses `SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?`
      - presence.async_setup calls `count_house_state_changes_since(today_iso)`
      - The hydration block assigns the result to `self._transitions_today`
      - The hydration block also sets `self._transition_reset_date`
    """
    db_src = (
        Path("custom_components/universal_room_automation/database.py")
    ).read_text()
    assert "async def count_house_state_changes_since" in db_src, (
        "v4.6.5.1 P4: database.py must define count_house_state_changes_since DAO"
    )
    assert (
        "SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?"
        in db_src
    ), (
        "v4.6.5.1 P4: count_house_state_changes_since must use the canonical "
        "SELECT COUNT(*) ... WHERE timestamp >= ? SQL"
    )

    pres_src = _read("presence.py")
    live = _non_comment_src(pres_src)
    assert "count_house_state_changes_since(" in live, (
        "v4.6.5.1 P4: presence.py must call db.count_house_state_changes_since "
        "in async_setup to hydrate _transitions_today"
    )
    # The hydration must assign to _transitions_today
    import re
    assert re.search(
        r"self\._transitions_today\s*=\s*count",
        live,
    ) is not None, (
        "v4.6.5.1 P4: hydration block must assign the DAO result to "
        "self._transitions_today"
    )
    # And reset_date must be set in the same block (so the reset check is satisfied)
    assert re.search(
        r"self\._transition_reset_date\s*=\s*today_iso",
        live,
    ) is not None, (
        "v4.6.5.1 P4: hydration block must also set _transition_reset_date "
        "so the daily-reset check is consistent post-hydration"
    )


def test_count_house_state_changes_since_sql_against_real_schema(real_schema_db):
    """v4.6.5.1 P4: behavioral test for the count DAO using real_schema_db.

    Drives the production SQL against the live schema. Validates:
      - The SQL parses (table + column names match the schema)
      - The lexicographic `>= since_iso` comparison includes today's rows
        and excludes yesterday's
    """
    conn = real_schema_db
    # Insert 5 rows: 3 today (2026-05-16), 2 yesterday (2026-05-15)
    conn.executemany(
        "INSERT INTO house_state_log "
        "(timestamp, state, confidence, trigger, previous_state) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("2026-05-16T03:14:15.123", "sleep", 0.9, "occupancy", "home_night"),
            ("2026-05-16T07:42:00.000", "home_morning", 0.8, "wake", "sleep"),
            ("2026-05-16T18:30:00.000", "home_evening", 0.85, "occupancy", "home_morning"),
            ("2026-05-15T22:01:11.500", "home_night", 0.8, "occupancy", "home_evening"),
            ("2026-05-15T08:00:00.000", "home_morning", 0.8, "wake", "sleep"),
        ],
    )
    conn.commit()

    # Production SQL: SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?
    count_today = conn.execute(
        "SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?",
        ("2026-05-16",),
    ).fetchone()[0]
    assert count_today == 3, (
        f"P4 SQL semantics: 3 rows from 2026-05-16 should be counted, got {count_today}"
    )

    # Future date returns 0
    count_future = conn.execute(
        "SELECT COUNT(*) FROM house_state_log WHERE timestamp >= ?",
        ("2026-05-17",),
    ).fetchone()[0]
    assert count_future == 0, (
        f"P4 SQL semantics: no rows from future date, got {count_future}"
    )


# ---------------------------------------------------------------------------
# v4.6.5.2 — Investigation fixes (MF denominator + recent_anomalies retry)
# ---------------------------------------------------------------------------


def _on_transfer_outcome_body(src: str) -> str:
    """Extract just the _on_transfer_outcome method body from MF coordinator
    source. Used by the v4.6.5.2 Fix 1 tests so assertions are scoped to the
    method that changed, not the whole file.
    """
    import re
    m = re.search(
        r"def _on_transfer_outcome\(self\).*?(?=\n    (?:async )?def )",
        src,
        re.DOTALL,
    )
    return m.group(0) if m else ""


def test_mf_success_rate_uses_transfer_keys_as_denominator():
    """v4.6.5.2 Fix 1: transfer_success_rate must divide by music-involved
    attempts only (MusicFollowing._TRANSFER_KEYS), not sum(stats.values()).

    Pre-v4.6.5.2 the denominator included pre-music rejections
    (low_confidence, cooldown_blocked, ping_pong_suppressed) which dominated
    the live baseline and crushed success_rate to ~0.0 over 1594 samples
    even when actual music transfers succeeded.

    v4.6.5.2 review L1 fix: asserts SEMANTIC INTENT (presence of
    `music_attempts`, absence of `sum(stats.values())`) rather than the
    exact syntactic shape of the assignment — so benign refactors like
    `float(stats.get(...))` or `(stats.get(...) or 0)` don't false-positive.
    """
    src = _read("music_following.py")
    # POSITIVE checks (identifiers must appear in live code, excluding
    # comments but allowing docstrings — `_non_comment_src` is line-level):
    live = _non_comment_src(src)
    body = _on_transfer_outcome_body(live)
    assert body, "Could not extract _on_transfer_outcome body"
    assert "_TRANSFER_KEYS" in body, (
        "v4.6.5.2 Fix 1: _on_transfer_outcome must reference _TRANSFER_KEYS "
        "to scope the denominator to music-involved outcomes"
    )
    assert "music_attempts" in body, (
        "v4.6.5.2 Fix 1: _on_transfer_outcome must compute `music_attempts` "
        "(sum over _TRANSFER_KEYS) and use it as the success_rate denominator"
    )
    # NEGATIVE check (the legacy denominator must NOT be reintroduced as
    # actual code). Extract the raw method body first, THEN tokenize, so
    # docstring mentions of the historical pattern don't trip the assertion.
    raw_body = _on_transfer_outcome_body(src)
    assert raw_body, "Could not extract raw _on_transfer_outcome body"
    tok_body = _non_string_src(
        # Indentation-strip so tokenize can parse the method body standalone
        "\n".join(line.lstrip() for line in raw_body.splitlines())
    )
    assert "sum ( stats . values ( ) )" not in tok_body, (
        "v4.6.5.2 Fix 1: _on_transfer_outcome must NOT use sum(stats.values()) "
        "as a denominator — pre-music rejections (low_confidence, "
        "ping_pong_suppressed) dominate it and crush success_rate to ~0."
    )


def test_mf_cooldown_frequency_uses_post_confidence_denominator():
    """v4.6.5.2 Fix 1 part 2: cooldown_frequency must divide by post-confidence
    decisions (music_attempts + cooldown_blocked), giving "of decisions past
    the confidence check, fraction blocked by cooldown".

    Pre-v4.6.5.2 divided by sum(stats.values()) (all 7 outcomes), so when
    low_confidence dominated, cooldown_rate was crushed regardless of how
    often cooldown actually fired.

    v4.6.5.2 review L1 fix: semantic-intent assertions.
    """
    src = _read("music_following.py")
    live = _non_comment_src(src)
    body = _on_transfer_outcome_body(live)
    assert body, "Could not extract _on_transfer_outcome body"
    assert "post_confidence_total" in body, (
        "v4.6.5.2 Fix 1: _on_transfer_outcome must compute "
        "`post_confidence_total` (music_attempts + cooldown_blocked) and use "
        "it as the cooldown_rate denominator"
    )
    # NEGATIVE check (tokenizer-based — docstring-immune)
    raw_body = _on_transfer_outcome_body(src)
    assert raw_body, "Could not extract raw _on_transfer_outcome body"
    tok_body = _non_string_src(
        "\n".join(line.lstrip() for line in raw_body.splitlines())
    )
    assert "sum ( stats . values ( ) )" not in tok_body, (
        "v4.6.5.2 Fix 1: see success-rate test — same denominator concern"
    )


def test_recent_anomalies_sensor_subscribes_to_database_ready_signal():
    """v4.6.5.3 M2: URARecentAnomaliesSensor's async_added_to_hass must use
    SIGNAL_DATABASE_READY (event-driven) instead of the v4.6.5.2 polling
    helper. Replaces test_recent_anomalies_sensor_retries_db_ready_on_startup.

    v4.6.5.2 closed the bug (sensor populated correctly) with a 30s polling
    loop. v4.6.5.3 M2 replaces the loop with a one-shot dispatcher
    subscription that fires from __init__.py the moment the DB is assigned
    to hass.data — deterministic and cheaper than polling.

    Asserts:
      - URARecentAnomaliesSensor subscribes to SIGNAL_DATABASE_READY
      - The polling helper _initial_load_with_db_retry is GONE
      - async_added_to_hass either does immediate refresh (DB already
        present) OR subscribes to the signal — no direct race
      - SIGNAL_DATABASE_READY is dispatched from __init__.py at every DB-
        assignment site (both setup paths)
    """
    src = (
        Path("custom_components/universal_room_automation/sensor.py")
    ).read_text()
    cls_start = src.find("class URARecentAnomaliesSensor(")
    assert cls_start >= 0, "Could not find URARecentAnomaliesSensor class"
    next_cls = src.find("\nclass ", cls_start + 1)
    cls_body = src[cls_start : next_cls if next_cls > 0 else len(src)]
    cls_body_live = _non_comment_src(cls_body)

    # Subscribe to the new signal
    assert "SIGNAL_DATABASE_READY" in cls_body_live, (
        "v4.6.5.3 M2: URARecentAnomaliesSensor must reference "
        "SIGNAL_DATABASE_READY to event-drive the initial load"
    )
    # The v4.6.5.2 polling helper is GONE
    assert "_initial_load_with_db_retry" not in cls_body_live, (
        "v4.6.5.3 M2: the v4.6.5.2 polling helper _initial_load_with_db_retry "
        "must be removed (replaced by SIGNAL_DATABASE_READY subscription)"
    )
    # async_added_to_hass body must reference SIGNAL_DATABASE_READY
    import re
    aath_match = re.search(
        r"async def async_added_to_hass\(self\).*?(?=\n    (?:async )?def )",
        cls_body_live,
        re.DOTALL,
    )
    assert aath_match is not None, "Could not find async_added_to_hass body"
    aath_body = aath_match.group(0)
    assert "SIGNAL_DATABASE_READY" in aath_body, (
        "v4.6.5.3 M2: async_added_to_hass must subscribe to "
        "SIGNAL_DATABASE_READY when the DB isn't yet in hass.data"
    )
    # The signal must be defined in signals.py
    signals_src = Path(
        "custom_components/universal_room_automation/domain_coordinators/signals.py"
    ).read_text()
    assert "SIGNAL_DATABASE_READY" in signals_src, (
        "v4.6.5.3 M2: SIGNAL_DATABASE_READY must be defined in signals.py"
    )
    # The signal must be dispatched from __init__.py at every DB-assignment
    # site so a sensor that subscribes after one site can still get notified
    # by the second site (defensive — only one site should fire in practice).
    init_src = Path(
        "custom_components/universal_room_automation/__init__.py"
    ).read_text()
    # Count the dispatcher calls (must be >= number of DB-assignment sites)
    db_assign_count = init_src.count('hass.data[DOMAIN]["database"] = database')
    dispatch_count = init_src.count("async_dispatcher_send(hass, SIGNAL_DATABASE_READY)")
    assert dispatch_count >= db_assign_count, (
        f"v4.6.5.3 M2: __init__.py has {db_assign_count} DB-assignment "
        f"site(s) but only {dispatch_count} SIGNAL_DATABASE_READY dispatch(es). "
        "Each site must dispatch the signal so subscribers don't miss it."
    )
    # v4.6.5.3 M2: the direct `await self._async_refresh()` is allowed in
    # async_added_to_hass IFF gated by the "DB already present" branch
    # (the alternative is the signal subscription). We assert the gate:
    # any direct refresh must be preceded by a hass.data check in the body.
    if "await self._async_refresh()" in aath_body:
        assert 'hass.data.get(DOMAIN' in aath_body, (
            "v4.6.5.3 M2: if async_added_to_hass calls _async_refresh "
            "directly, it must first check the DB is present in hass.data. "
            "Otherwise the race we fixed in v4.6.5.2 returns."
        )


# ---------------------------------------------------------------------------
# v4.6.5.3 — Item 1 surface fix: per-coordinator severity ignores SUPPRESSED
# ---------------------------------------------------------------------------


def test_anomaly_detector_accepts_suppressed_metric_names():
    """v4.6.5.3 surface fix: AnomalyDetector.__init__ must accept a
    `suppressed_metric_names` parameter so get_worst_severity() can exclude
    in-memory anomalies for metrics suppressed from persistence.

    Pre-fix: per-coordinator anomaly sensor showed state=critical whenever
    a degenerate-shape suppressed metric (e.g. hvac.zone_call_frequency)
    fired in-memory. Misleading — the metric was suppressed precisely
    BECAUSE its shape is degenerate; it shouldn't drive operator-facing
    severity.
    """
    src = (
        Path("custom_components/universal_room_automation/domain_coordinators/coordinator_diagnostics.py")
    ).read_text()
    live = _non_comment_src(src)
    # Constructor parameter
    assert "suppressed_metric_names" in live, (
        "v4.6.5.3 surface fix: AnomalyDetector.__init__ must accept "
        "suppressed_metric_names parameter"
    )
    # New helper that filters _active_anomalies
    assert "_persisted_active_anomalies" in live, (
        "v4.6.5.3 surface fix: AnomalyDetector must define "
        "_persisted_active_anomalies() helper that filters out suppressed metrics"
    )
    # get_worst_severity must call the filtered helper
    import re
    gws_match = re.search(
        r"def get_worst_severity\(self\).*?(?=\n    def )",
        live,
        re.DOTALL,
    )
    assert gws_match is not None, "Could not find get_worst_severity body"
    assert "_persisted_active_anomalies" in gws_match.group(0), (
        "v4.6.5.3 surface fix: get_worst_severity must use "
        "_persisted_active_anomalies (not raw _active_anomalies) so suppressed "
        "metrics don't drive the reported severity"
    )
    # get_status_summary should expose both counts
    assert "suppressed_active_anomalies" in live, (
        "v4.6.5.3 surface fix: get_status_summary must expose "
        "suppressed_active_anomalies for operator visibility into in-memory-"
        "only firings"
    )


def test_all_coordinators_pass_suppression_set_to_anomaly_detector():
    """v4.6.5.3 surface fix: every coordinator that constructs an
    AnomalyDetector must pass its module-level *_SUPPRESSED_FROM_PERSISTENCE
    constant as `suppressed_metric_names`. Without this, the surface fix is
    inert because the detector's filter set is empty by default.
    """
    coord_files_and_consts = [
        ("hvac.py", "HVAC_SUPPRESSED_FROM_PERSISTENCE"),
        ("security.py", "SECURITY_SUPPRESSED_FROM_PERSISTENCE"),
        ("music_following.py", "MUSIC_FOLLOWING_SUPPRESSED_FROM_PERSISTENCE"),
        ("presence.py", "PRESENCE_SUPPRESSED_FROM_PERSISTENCE"),
        ("safety.py", "SAFETY_SUPPRESSED_FROM_PERSISTENCE"),
    ]
    failures: list[str] = []
    for filename, const_name in coord_files_and_consts:
        src = _read(filename)
        live = _non_comment_src(src)
        # Find AnomalyDetector( instantiation — balanced-paren walk so nested
        # calls in keyword args don't truncate the body early
        idx = live.find("AnomalyDetector(")
        if idx < 0:
            failures.append(f"{filename}: no AnomalyDetector( instantiation found")
            continue
        start = idx + len("AnomalyDetector(")
        depth = 1
        i = start
        while i < len(live) and depth > 0:
            ch = live[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        body = live[start : i - 1]
        if "suppressed_metric_names" not in body:
            failures.append(
                f"{filename}: AnomalyDetector instantiation missing "
                f"`suppressed_metric_names=`"
            )
            continue
        if const_name not in body:
            failures.append(
                f"{filename}: AnomalyDetector instantiation should pass "
                f"`suppressed_metric_names={const_name}`"
            )
    assert not failures, (
        "v4.6.5.3 surface fix — all 5 coordinators must wire their "
        "*_SUPPRESSED_FROM_PERSISTENCE constant into AnomalyDetector init:\n"
        "  - " + "\n  - ".join(failures)
    )


# ---------------------------------------------------------------------------
# v4.6.5.3 — Item 3 M4: one-shot info-log on first MF emit
# ---------------------------------------------------------------------------


def test_mf_first_emit_info_log_one_shot():
    """v4.6.5.3 M4 (review note from v4.6.5.2): MF coordinator must log INFO
    on the FIRST post-deploy observation for each metric so operators can
    spot when the v4.6.5.2 Fix 1 denominator change starts feeding the
    baseline. Without this, the only signal is the baseline slowly moving
    over weeks.

    Asserts:
      - `_first_emit_logged` set initialized in __init__
      - Both metric names (transfer_success_rate, cooldown_frequency) have
        a gated INFO log + add-to-set guard inside _on_transfer_outcome
    """
    src = _read("music_following.py")
    live = _non_comment_src(src)
    assert "_first_emit_logged" in live, (
        "v4.6.5.3 M4: MusicFollowingCoordinator must initialize "
        "`_first_emit_logged` set in __init__"
    )
    body = _on_transfer_outcome_body(live)
    assert body, "Could not extract _on_transfer_outcome body"
    # Both metric guards must be present
    assert '"transfer_success_rate" not in self._first_emit_logged' in body, (
        "v4.6.5.3 M4: _on_transfer_outcome must guard the first-emit info-log "
        "for transfer_success_rate with `not in self._first_emit_logged`"
    )
    assert '"cooldown_frequency" not in self._first_emit_logged' in body, (
        "v4.6.5.3 M4: _on_transfer_outcome must guard the first-emit info-log "
        "for cooldown_frequency"
    )
    # The guards must add the metric name to the set after logging
    assert 'self._first_emit_logged.add("transfer_success_rate")' in body, (
        "v4.6.5.3 M4: after logging, transfer_success_rate must be added to "
        "_first_emit_logged so the log fires once per restart"
    )
    assert 'self._first_emit_logged.add("cooldown_frequency")' in body, (
        "v4.6.5.3 M4: after logging, cooldown_frequency must be added to "
        "_first_emit_logged"
    )
