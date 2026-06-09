"""Optimization LLM Tier-2 — provider-agnostic via `ai_task.generate_data`.

Phase 2 of the URA Optimization Coordinator. Sits on top of the Phase-1
deterministic loop and reasons over the RAW substrate + the two Phase-1
dimensions. Every LLM-proposed action is funnelled through the SAME
Phase-1 chokepoint (`OptimizationCoordinator._apply_action`) tagged
``created_by="tier2_llm"`` — the LLM CANNOT bypass the autonomy ladder,
matrix gate, confidence gate, rate cap, quiet hours, kill switch, or
handshake broker.

Pipeline (one pass per Optimizer cycle):
1. Assemble :class:`OptimizerContextCorpus` from the RAW substrate.
2. Pre-LLM compression — corpus is bounded to ``OPTIMIZER_LLM_CONTEXT_MAX_TOKENS``.
3. Optional cheap triage pass (local backend) — only when triage flags
   "worth deep analysis" does the premium primary backend run.
4. Premium deep pass → parse + validate structured output.
5. Emit findings with ``created_by="tier2_llm"`` through the Phase-1
   chokepoint.

Cost levers (stacked, per backend):
- Provider selection (incl. local Ollama = $0)
- Cheap-triage → premium-deep routing
- Delta-trigger gate (only invoke when finding-set changed since last)
- Hard daily premium cap
- <8KB corpus + structured output keep tokens small

Anchors:
- Phase-1 chokepoint: domain_coordinators/optimization.py:_apply_action
- ai_task call shape: config_flow.py:1602-1636 (AI_RULE_PARSING)
- Prompt const: const.py:OPTIMIZER_LLM_SYSTEM_PROMPT

Bug-class guardrails:
- #44 (test authority): the canonical parse/validate path lives here and
  is driven directly by tests — they mock `hass.services.async_call` at
  the boundary, not the parser.
- #50: any signal/listener unsubs are stored on
  ``OptimizationCoordinator._unsub_listeners`` by the caller — this
  module subscribes to nothing on its own.
- C-CRIT-1 (Phase-1 review): all CONF keys this module reads are in
  ``OPTIONS_RELOAD_SUPPRESS_KEYS`` so editing them does not full-reload
  the CM entry.

Note: HA `ai_task` does NOT surface Anthropic-style ``cache_control``
today. The corpus is serialized with a ``# === STABLE CONTEXT ===`` /
``# === CURRENT SNAPSHOT ===`` split as forward-compat scaffolding for
prompt caching — no `cache_control` param is fabricated.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_DAY,
    CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
    CONF_OPTIMIZER_LLM_TASK_ENTITY,
    CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
    DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_DAY,
    DEFAULT_OPTIMIZER_LLM_TASK_ENTITY,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
    OPTIMIZER_CREATED_BY_TIER2_LLM,
    OPTIMIZER_LLM_CONTEXT_CHARS_PER_TOKEN,
    OPTIMIZER_LLM_CONTEXT_MAX_TOKENS,
    OPTIMIZER_LLM_STRUCTURE,
    OPTIMIZER_LLM_SYSTEM_PROMPT,
    OPTIMIZER_LLM_TASK_NAME,
)

_LOGGER = logging.getLogger(__name__)


# Maximum bytes of corpus payload (after token→char conversion). Used to
# defensively bound serialized JSON sections even before the LLM call.
_CORPUS_MAX_CHARS = (
    OPTIMIZER_LLM_CONTEXT_MAX_TOKENS * OPTIMIZER_LLM_CONTEXT_CHARS_PER_TOKEN
)

# Trim caps per corpus section — keeps any single section from eating the
# whole budget so a noisy `findings_recent` can't crowd out `house`.
_MAX_RECENT_FINDINGS = 50
_MAX_PRIOR_ACTIONS = 20
_MAX_ROOMS_SERIALIZED = 30
_MAX_ZONES_SERIALIZED = 12


@dataclass
class OptimizerContextCorpus:
    """Structured snapshot fed to the LLM (plan §1)."""

    house: dict = field(default_factory=dict)
    zones: list[dict] = field(default_factory=list)
    rooms: list[dict] = field(default_factory=list)
    findings_recent: list[dict] = field(default_factory=list)
    goals_active: list[dict] = field(default_factory=list)
    bayesian_accuracy: dict = field(default_factory=dict)
    prior_actions: list[dict] = field(default_factory=list)

    def stable_sections(self) -> dict:
        """Sections that don't change cycle-to-cycle — eligible for
        forward-compat prompt-cache reuse."""
        return {
            "goals_active": self.goals_active,
        }

    def snapshot_sections(self) -> dict:
        """Sections that DO change cycle-to-cycle."""
        return {
            "house": self.house,
            "zones": self.zones,
            "rooms": self.rooms,
            "findings_recent": self.findings_recent,
            "bayesian_accuracy": self.bayesian_accuracy,
            "prior_actions": self.prior_actions,
        }

    def to_prompt_body(self, max_chars: int = _CORPUS_MAX_CHARS) -> str:
        """Serialize the corpus as a single prompt body with stable /
        snapshot markers. Trims sections greedily until under ``max_chars``.

        Trim order: findings_recent → prior_actions → rooms → zones. The
        ``house`` summary and ``goals_active`` are preserved last.
        """
        stable = self.stable_sections()
        snap = self.snapshot_sections()

        def _serialize(stable_d, snap_d) -> str:
            return (
                "# === STABLE CONTEXT ===\n"
                + json.dumps(stable_d, default=str, sort_keys=True)
                + "\n# === CURRENT SNAPSHOT ===\n"
                + json.dumps(snap_d, default=str, sort_keys=True)
            )

        body = _serialize(stable, snap)
        if len(body) <= max_chars:
            return body

        # Greedy trim — operate on COPIES so the original corpus is intact.
        snap_trim = {k: list(v) if isinstance(v, list) else v
                     for k, v in snap.items()}
        for section_key in ("findings_recent", "prior_actions",
                            "rooms", "zones"):
            section = snap_trim.get(section_key)
            if not isinstance(section, list):
                continue
            # Halve repeatedly until we either fit or empty the section.
            while section and len(_serialize(stable, snap_trim)) > max_chars:
                section.pop()
            if len(_serialize(stable, snap_trim)) <= max_chars:
                return _serialize(stable, snap_trim)
        # Final fallback — even after trimming all four sections we may
        # still be over budget if `house` is huge. Truncate the body.
        body = _serialize(stable, snap_trim)
        if len(body) > max_chars:
            body = body[:max_chars]
        return body


# ============================================================================
# OptimizationLLMTier
# ============================================================================


class OptimizationLLMTier:
    """LLM Tier-2 wrapper for the Phase-1 optimizer.

    Stateless across cycles except for:
    - ``_last_findings_signature``: tuple of dedup keys observed in the
      previous Tier-1 finding-set — used by the delta-trigger gate.
    - ``_premium_invocations_today``: list of ISO timestamps for the
      premium backend, rolling-day window.

    Owns no signal subscriptions; the caller is the Phase-1 coordinator,
    which holds all unsubs on its ``_unsub_listeners`` (Bug Class #50).
    """

    def __init__(self, hass: HomeAssistant, coordinator) -> None:
        """Initialize the LLM tier wrapper.

        Args:
            hass: Home Assistant instance.
            coordinator: The Phase-1 ``OptimizationCoordinator`` — call
                target for the chokepoint and source of the substrate.
        """
        self.hass = hass
        self.coordinator = coordinator
        self._last_findings_signature: tuple | None = None
        # Rolling-day premium invocation history. Each entry is a UTC
        # datetime; entries older than 24h are evicted lazily.
        self._premium_invocations: list[datetime] = []

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def run_cycle(self, tier1_findings: list) -> list:
        """Run one LLM cycle on top of the current Tier-1 finding-set.

        Returns the list of LLM-emitted findings (after parse+validate),
        each already routed through the Phase-1 chokepoint. The caller
        (Phase-1 coordinator) persists / dispatches them alongside its
        own Tier-1 findings.

        Hard gates (in order):
        1. LLM task entity configured? (else no-op)
        2. Finding-set delta ≥ 1? (else no-op)
        3. Under daily premium cap? (else triage-only mode at most)
        """
        config = self._read_cm_config()
        primary_entity = config.get(
            CONF_OPTIMIZER_LLM_TASK_ENTITY, DEFAULT_OPTIMIZER_LLM_TASK_ENTITY,
        )
        if not primary_entity:
            return []

        if not self._finding_delta_present(tier1_findings):
            _LOGGER.debug(
                "OptimizationLLMTier: no finding-set delta — skipping LLM "
                "invocation (cost lever: delta gate)",
            )
            return []

        # Build the corpus once, reuse across triage + premium passes.
        corpus = self._assemble_corpus(tier1_findings)
        prompt = self._resolve_system_prompt(config) + "\n\n" + (
            corpus.to_prompt_body()
        )

        # Optional triage pass.
        triage_entity = config.get(CONF_OPTIMIZER_LLM_TRIAGE_ENTITY) or ""
        triage_flagged = True
        if triage_entity and triage_entity != primary_entity:
            triage_flagged = await self._triage_pass(triage_entity, prompt)
            if not triage_flagged:
                _LOGGER.debug(
                    "OptimizationLLMTier: triage skipped premium (%s flagged "
                    "no deep analysis needed)", triage_entity,
                )
                return []

        # Daily premium cap.
        cap = int(config.get(
            CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_DAY,
            DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_DAY,
        ))
        if not self._under_daily_cap(cap):
            _LOGGER.info(
                "OptimizationLLMTier: daily premium cap (%d) reached — "
                "skipping premium pass this cycle", cap,
            )
            return []

        # Premium deep pass.
        raw = await self._invoke_ai_task(primary_entity, prompt)
        self._premium_invocations.append(dt_util.utcnow())
        findings = self._parse_findings(raw)
        if not findings:
            _LOGGER.debug(
                "OptimizationLLMTier: premium pass returned no parseable "
                "findings (%s)", primary_entity,
            )
            return []

        # Route every LLM finding through the Phase-1 chokepoint.
        applied: list = []
        for f in findings:
            try:
                await self.coordinator._consider_apply(f)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "OptimizationLLMTier: _consider_apply raised for "
                    "LLM finding (%s) — skipping; %s",
                    getattr(f, "description", "<no desc>"), exc,
                )
                continue
            applied.append(f)
        return applied

    # ------------------------------------------------------------------
    # Delta gate
    # ------------------------------------------------------------------

    def _signature(self, findings: list) -> tuple:
        """Reduce a finding list to a hashable dedup signature."""
        sig: list = []
        for f in findings or []:
            try:
                # `dedup_key` is the canonical Phase-1 dedup tuple. Fall
                # back to (level, target_id, dimension) when missing.
                k = getattr(f, "dedup_key", None)
                if not k:
                    k = (
                        getattr(f, "level", None),
                        getattr(f, "target_id", None),
                        str(getattr(f, "dimension", "")),
                    )
                sig.append(k)
            except Exception:  # noqa: BLE001
                continue
        return tuple(sorted(str(x) for x in sig))

    def _finding_delta_present(self, tier1_findings: list) -> bool:
        """Return True when the finding-set differs from the prior cycle.

        Updates the cached signature on every call so the very first
        cycle (no prior signature) is treated as a delta.
        """
        sig = self._signature(tier1_findings)
        prior = self._last_findings_signature
        self._last_findings_signature = sig
        if prior is None:
            return True
        return sig != prior

    # ------------------------------------------------------------------
    # Daily cap
    # ------------------------------------------------------------------

    def _under_daily_cap(self, cap: int) -> bool:
        """Evict invocations older than 24h, then compare to ``cap``."""
        cutoff = dt_util.utcnow() - timedelta(hours=24)
        self._premium_invocations = [
            t for t in self._premium_invocations if t >= cutoff
        ]
        if cap <= 0:
            # Operator pinned cap to 0 → premium disabled entirely.
            return False
        return len(self._premium_invocations) < cap

    # ------------------------------------------------------------------
    # Config read + prompt resolution
    # ------------------------------------------------------------------

    def _read_cm_config(self) -> dict:
        """Mirror ``OptimizationCoordinator._read_cm_config`` so the LLM
        tier doesn't depend on a private helper.
        """
        try:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_COORDINATOR_MANAGER:
                    return {**(entry.data or {}), **(entry.options or {})}
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _resolve_system_prompt(self, config: dict) -> str:
        """Two-tier resolution: live edited prompt → in-code const.

        Empty string / None / non-string all fall back to the const so
        the optimizer can never crash on a malformed override.
        """
        live = config.get(CONF_OPTIMIZER_LLM_SYSTEM_PROMPT)
        if isinstance(live, str) and live.strip():
            return live
        return OPTIMIZER_LLM_SYSTEM_PROMPT

    # ------------------------------------------------------------------
    # Corpus assembly
    # ------------------------------------------------------------------

    def _assemble_corpus(self, tier1_findings: list) -> OptimizerContextCorpus:
        """Build the snapshot fed to the LLM.

        Draws from the RAW substrate (room data, recent findings, Bayesian
        summary, activity log). Pre-LLM compression happens in
        :meth:`OptimizerContextCorpus.to_prompt_body`.
        """
        corpus = OptimizerContextCorpus()

        # House summary — last_findings + scoreboard from the Phase-1
        # coordinator are the canonical aggregate. Defensive: every read
        # is guarded — corpus assembly NEVER crashes the optimizer.
        try:
            corpus.house = {
                "score": getattr(self.coordinator, "_house_score", None),
                "status": getattr(self.coordinator, "status", None),
                "open_findings_count": getattr(
                    self.coordinator, "_open_findings_count", 0,
                ),
                "last_evaluation_iso": getattr(
                    self.coordinator, "_last_evaluation_iso", None,
                ),
            }
        except Exception:  # noqa: BLE001
            corpus.house = {}

        # Rooms — iterate Phase-1's room entries.
        rooms: list[dict] = []
        try:
            for entry in self.coordinator._iter_room_entries():
                if len(rooms) >= _MAX_ROOMS_SERIALIZED:
                    break
                try:
                    name = self.coordinator._room_name(entry)
                    comfort = self.coordinator._read_per_room_comfort(entry)
                    occupied = self.coordinator._is_room_occupied(entry)
                    rooms.append({
                        "room": name,
                        "occupied": occupied,
                        "comfort_band": {
                            "temp_min": comfort.get("min"),
                            "temp_max": comfort.get("max"),
                            "humidity_max": comfort.get("hum_max"),
                        },
                        "score": (
                            self.coordinator.get_room_score(name)
                            if hasattr(self.coordinator, "get_room_score")
                            else None
                        ),
                    })
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        corpus.rooms = rooms

        # Recent findings — last 24h, capped at _MAX_RECENT_FINDINGS.
        recent: list[dict] = []
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is not None and hasattr(db, "get_recent_optimization_findings"):
                # `get_recent_optimization_findings` is an AsyncMock in
                # tests; the coordinator already awaits it during setup.
                # Here we ONLY use what's already cached on the
                # coordinator via `_last_findings` to keep corpus
                # assembly synchronous and side-effect free.
                pass
            for f in (getattr(self.coordinator, "_last_findings", []) or [])[
                -_MAX_RECENT_FINDINGS:
            ]:
                try:
                    recent.append({
                        "timestamp": getattr(f, "timestamp", None),
                        "level": getattr(f, "level", None),
                        "target_id": getattr(f, "target_id", None),
                        "dimension": str(getattr(f, "dimension", "")),
                        "severity": getattr(f, "severity", None),
                        "confidence": getattr(f, "confidence", None),
                        "description": getattr(f, "description", None),
                        "created_by": getattr(f, "created_by", None),
                    })
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        # Include the current tier-1 finding set as well so the LLM sees
        # exactly what the rule engine just emitted.
        for f in (tier1_findings or [])[-_MAX_RECENT_FINDINGS:]:
            try:
                recent.append({
                    "timestamp": getattr(f, "timestamp", None),
                    "level": getattr(f, "level", None),
                    "target_id": getattr(f, "target_id", None),
                    "dimension": str(getattr(f, "dimension", "")),
                    "severity": getattr(f, "severity", None),
                    "confidence": getattr(f, "confidence", None),
                    "description": getattr(f, "description", None),
                    "created_by": getattr(f, "created_by", None),
                })
            except Exception:  # noqa: BLE001
                continue
        corpus.findings_recent = recent[-_MAX_RECENT_FINDINGS:]

        # Goals + Bayesian + prior actions are read best-effort. The
        # plan acknowledges these are optional sub-corpus blocks that
        # phases 3-5 will EXTEND but never INVALIDATE.
        corpus.goals_active = self._read_active_goals()
        corpus.bayesian_accuracy = self._read_bayesian_summary()
        corpus.prior_actions = self._read_prior_actions()

        return corpus

    def _read_active_goals(self) -> list[dict]:
        """Read built-in + user-injected optimization goals. Plan §1 —
        Phase 2 ships with a static built-in goal list; user-injected
        goals land in a later phase.
        """
        return [
            {"kind": "safety", "target": "no_safety_violations", "priority": 1},
            {"kind": "comfort", "target": "stay_within_band", "priority": 3},
            {"kind": "energy", "target": "minimize_waste", "priority": 4},
        ]

    def _read_bayesian_summary(self) -> dict:
        """Best-effort read of the Bayesian predictor summary."""
        try:
            ura = self.hass.data.get(DOMAIN, {})
            pred = ura.get("bayesian_predictor")
            if pred is None:
                return {}
            for attr in ("get_summary", "summary"):
                getter = getattr(pred, attr, None)
                if callable(getter):
                    out = getter()
                    if isinstance(out, dict):
                        return out
        except Exception:  # noqa: BLE001
            return {}
        return {}

    def _read_prior_actions(self) -> list[dict]:
        """Pull the last N optimizer-emitted activity rows."""
        out: list[dict] = []
        try:
            logger = self.hass.data.get(DOMAIN, {}).get("activity_logger")
            if logger is None:
                return out
            recent = getattr(logger, "recent_entries", None)
            if callable(recent):
                rows = recent(coordinator="optimization",
                              limit=_MAX_PRIOR_ACTIONS) or []
                for r in rows[-_MAX_PRIOR_ACTIONS:]:
                    if isinstance(r, dict):
                        out.append(r)
        except Exception:  # noqa: BLE001
            return out
        return out

    # ------------------------------------------------------------------
    # AI Task invocation
    # ------------------------------------------------------------------

    async def _invoke_ai_task(
        self, entity_id: str, prompt: str,
    ) -> dict | None:
        """Call ``ai_task.generate_data`` with structured output.

        Mirrors config_flow.py:1602-1636 but passes ``entity_id`` for
        provider-agnostic routing (the rule-parser uses the default).

        Returns the raw response dict (or None on failure). Parsing is
        the caller's job.
        """
        if not entity_id:
            return None
        try:
            result = await self.hass.services.async_call(
                "ai_task",
                "generate_data",
                {
                    "entity_id": entity_id,
                    "task_name": OPTIMIZER_LLM_TASK_NAME,
                    "instructions": prompt,
                    "structure": OPTIMIZER_LLM_STRUCTURE,
                },
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "ai_task.generate_data failed (entity=%s): %s",
                entity_id, err,
            )
            return None
        if not result or not isinstance(result, dict):
            return None
        return result

    async def _triage_pass(self, triage_entity: str, prompt: str) -> bool:
        """Cheap triage pass — local/Ollama backend asked "anything here?".

        Returns True when the triage backend flags ≥1 finding worth deep
        analysis OR when the response shape is unparseable (fail-open so
        a flaky triage backend can't silently mute the premium tier).
        """
        triage_prompt = (
            prompt
            + "\n\n# === TRIAGE TASK ===\n"
            "Return findings ONLY if you would flag at least one issue "
            "worth deep analysis. If nothing is actionable, return an "
            "empty findings list. Do NOT propose actions in the triage pass."
        )
        raw = await self._invoke_ai_task(triage_entity, triage_prompt)
        if raw is None:
            return True  # fail-open
        findings = self._extract_findings_list(raw)
        if findings is None:
            return True  # malformed — fail-open
        return len(findings) > 0

    # ------------------------------------------------------------------
    # Parse + validate
    # ------------------------------------------------------------------

    def _extract_findings_list(self, raw: dict) -> list | None:
        """Pull the `findings` list out of the response, tolerating both
        nested (``raw['data']['findings']``) and flat (``raw['findings']``)
        shapes per config_flow.py:1627-1634.
        """
        if not isinstance(raw, dict):
            return None
        if isinstance(raw.get("data"), dict):
            findings = raw["data"].get("findings")
            if isinstance(findings, list):
                return findings
        findings = raw.get("findings")
        if isinstance(findings, list):
            return findings
        return None

    def _parse_findings(self, raw: dict | None) -> list:
        """Convert structured-output JSON into ``OptimizationFinding`` rows.

        Rejects malformed individual findings but KEEPS the good ones.
        Logs + skips on a bad row — never silently swallows the whole
        batch into one partial finding.
        """
        if raw is None:
            return []
        # Local import — avoids a circular module dep at import time.
        from .optimization import OptimizationDimension, OptimizationFinding

        rows = self._extract_findings_list(raw)
        if rows is None:
            _LOGGER.warning(
                "OptimizationLLMTier: structured output missing `findings` "
                "list — rejecting whole response",
            )
            return []

        out: list[OptimizationFinding] = []
        now_iso = dt_util.utcnow().isoformat()
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                _LOGGER.info(
                    "OptimizationLLMTier: rejected finding[%d] — not a dict",
                    idx,
                )
                continue
            try:
                dimension = str(row.get("dimension") or "").strip()
                severity = str(row.get("severity") or "").strip().lower()
                if severity not in ("critical", "high", "medium", "low"):
                    raise ValueError(f"bad severity: {severity!r}")
                confidence = float(row.get("confidence"))
                if not (0.0 <= confidence <= 1.0):
                    raise ValueError(
                        f"confidence out of [0,1]: {confidence}"
                    )
                target_level = str(row.get("target_level") or "").strip()
                if target_level not in ("house", "zone", "room"):
                    raise ValueError(f"bad target_level: {target_level!r}")
                target_id = row.get("target_id")
                if not isinstance(target_id, str) or not target_id:
                    raise ValueError("target_id must be a non-empty string")
                description = str(row.get("description") or "").strip()
                if not description:
                    raise ValueError("description must be non-empty")
                proposed = row.get("proposed_action_or_null")
                if proposed is not None and not isinstance(proposed, dict):
                    raise ValueError(
                        "proposed_action must be null or an object"
                    )
                action_class = None
                if isinstance(proposed, dict):
                    action_class = str(
                        proposed.get("action_class") or "reversible_device"
                    )
                    if action_class not in (
                        "reversible_device", "config_write",
                    ):
                        raise ValueError(
                            f"bad action_class: {action_class!r}"
                        )
            except (TypeError, ValueError, KeyError) as exc:
                _LOGGER.info(
                    "OptimizationLLMTier: rejected finding[%d] — %s "
                    "(row=%r)", idx, exc, row,
                )
                continue

            # Map dimension string onto the existing Phase-1 enum where
            # possible; keep the raw string when the LLM proposes a
            # forward-looking dimension we haven't shipped yet (Phase 3+).
            try:
                dim_enum = OptimizationDimension(dimension)
            except ValueError:
                dim_enum = dimension

            finding = OptimizationFinding(
                timestamp=now_iso,
                level=target_level,
                target_id=target_id,
                dimension=dim_enum,
                severity=severity,
                confidence=confidence,
                score=0.0,
                description=description,
                proposed_action=(
                    self._normalize_proposed_action(proposed)
                    if isinstance(proposed, dict) else None
                ),
                action_class=action_class,
                payload={"source": "tier2_llm", "row": row},
                created_by=OPTIMIZER_CREATED_BY_TIER2_LLM,
                dedup_key=(
                    "tier2_llm", target_level, target_id, dimension,
                ),
            )
            out.append(finding)

        if out:
            _LOGGER.info(
                "OptimizationLLMTier: emitted %d Tier-2 findings "
                "(created_by=tier2_llm)", len(out),
            )
        return out

    @staticmethod
    def _normalize_proposed_action(proposed: dict) -> dict:
        """Shape the LLM-proposed action dict into the chokepoint's
        expected format: ``{service, service_data, target_entity,
        action_class}``."""
        domain = str(proposed.get("domain") or "").strip()
        service = str(proposed.get("service") or "").strip()
        # Accept both `service` and `domain.service`.
        if domain and "." not in service:
            full_service = f"{domain}.{service}" if service else ""
        else:
            full_service = service
        target = proposed.get("target_entity") or proposed.get("entity_id") or ""
        service_data = proposed.get("service_data") or proposed.get("data") or {}
        if not isinstance(service_data, dict):
            service_data = {}
        action_class = str(
            proposed.get("action_class") or "reversible_device"
        )
        return {
            "service": full_service,
            "service_data": dict(service_data),
            "target_entity": str(target),
            "action_class": action_class,
        }
