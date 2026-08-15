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

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    CONF_ENTRY_TYPE,
    CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    CONF_OPTIMIZER_LLM_SYSTEM_PROMPT,
    CONF_OPTIMIZER_LLM_TASK_ENTITY,
    CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
    DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
    DEFAULT_OPTIMIZER_LLM_TASK_ENTITY,
    DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY,
    DOMAIN,
    ENTRY_TYPE_COORDINATOR_MANAGER,
    ENTRY_TYPE_ROOM,
    OPTIMIZER_ALLOWED_DOMAINS_CONFIG,
    OPTIMIZER_ALLOWED_DOMAINS_DEVICE,
    OPTIMIZER_CREATED_BY_TIER2_LLM,
    OPTIMIZER_LLM_AI_TASK_TIMEOUT_S,
    OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX,
    OPTIMIZER_LLM_CONTEXT_CHARS_PER_TOKEN,
    OPTIMIZER_LLM_CONTEXT_MAX_TOKENS,
    OPTIMIZER_LLM_MAX_CRITICAL_PER_CYCLE,
    OPTIMIZER_LLM_MAX_HIGH_PER_CYCLE,
    OPTIMIZER_LLM_SERVICE_DATA_ALLOWED_KEYS,
    OPTIMIZER_LLM_STRUCTURE,
    OPTIMIZER_LLM_SYSTEM_PROMPT,
    OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS,
    OPTIMIZER_LLM_TASK_NAME,
    OPTIMIZER_LLM_TRIAGE_LOCAL_PREFIX,
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

        v4.7.35 fix-up (A-MED-3): final fallback no longer raw byte-slices
        the JSON (which would send malformed JSON to a paid backend).
        Instead we empty ``bayesian_accuracy``, then degrade ``house`` to a
        minimal stub. If STILL over budget, we return the empty sentinel
        ``""`` so the caller can detect that and SKIP the LLM call.
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
        # Still over budget: drop bayesian_accuracy entirely.
        snap_trim["bayesian_accuracy"] = {}
        if len(_serialize(stable, snap_trim)) <= max_chars:
            return _serialize(stable, snap_trim)
        # Last resort: degrade `house` to a minimal stub. Preserve only
        # the status field if it's a short string.
        house = snap_trim.get("house") or {}
        if isinstance(house, dict):
            status = house.get("status")
            stub = {}
            if isinstance(status, str) and len(status) < 64:
                stub["status"] = status
            snap_trim["house"] = stub
        if len(_serialize(stable, snap_trim)) <= max_chars:
            return _serialize(stable, snap_trim)
        # Even the degraded body won't fit. Return empty sentinel so the
        # caller can SKIP the LLM call instead of sending half-JSON to a
        # paid backend.
        return ""


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
        # Rolling-24h premium invocation history. Each entry is a UTC
        # datetime; entries older than 24h are evicted lazily.
        self._premium_invocations: list[datetime] = []
        # A-CRIT-1 / C-MED-3: track whether we've already seeded from
        # the DB. We seed lazily on the first ``run_cycle`` invocation
        # since the DB may not be wired yet at __init__ time.
        self._premium_seeded_from_db: bool = False
        # A-HIGH-2 / B-B3: corpus-derived entity allowlist for hallucination
        # rejection. Populated by ``_assemble_corpus``.
        self._corpus_entity_ids: set[str] = set()
        self._corpus_target_ids: set[str] = set()
        # C-LOW-2: only WARN once per process about an uncapped triage
        # backend (we don't want a 5-min cycle to spam the log).
        self._triage_uncapped_warned: bool = False

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

        # A-CRIT-1 / C-MED-3: lazy seed of premium-invocation history
        # from the DB so a restart can't bypass the rolling-24h cap.
        if not self._premium_seeded_from_db:
            await self._seed_premium_invocations_from_db()
            self._premium_seeded_from_db = True

        # B-B7 fix-up: compute the new signature but do NOT commit it
        # yet. If the delta gate passes but the cycle aborts after this
        # point (parse error, cap exceeded, etc.), we want the next
        # cycle to re-fire on the SAME finding-set.
        new_sig = self._signature(tier1_findings)
        prior_sig = self._last_findings_signature
        if prior_sig is not None and new_sig == prior_sig:
            _LOGGER.debug(
                "OptimizationLLMTier: no finding-set delta — skipping LLM "
                "invocation (cost lever: delta gate)",
            )
            return []
        if prior_sig is not None and prior_sig != new_sig:
            _LOGGER.debug(
                "OptimizationLLMTier: delta gate FIRED — prior_sig=%s "
                "new_sig=%s", prior_sig, new_sig,
            )

        # Build the corpus once, reuse across triage + premium passes.
        corpus = self._assemble_corpus(tier1_findings)
        body = corpus.to_prompt_body()
        if not body:
            _LOGGER.warning(
                "OptimizationLLMTier: corpus body exceeded cap even after "
                "degradation — skipping LLM call this cycle",
            )
            return []
        prompt = self._resolve_system_prompt(config) + "\n\n" + body

        # Optional triage pass.
        triage_entity = config.get(
            CONF_OPTIMIZER_LLM_TRIAGE_ENTITY,
            DEFAULT_OPTIMIZER_LLM_TRIAGE_ENTITY,
        ) or ""
        triage_flagged = True
        if triage_entity and triage_entity != primary_entity:
            # C-LOW-2: WARN once if the triage backend isn't a known-local
            # (zero-cost) provider — otherwise the "triage saves money"
            # premise is silently invalidated.
            if (not triage_entity.startswith(OPTIMIZER_LLM_TRIAGE_LOCAL_PREFIX)
                    and not self._triage_uncapped_warned):
                _LOGGER.warning(
                    "OptimizationLLMTier: triage backend %r is not a known "
                    "local backend (prefix %r) and is uncapped — configure "
                    "a local/zero-cost provider or remove the triage entity "
                    "to disable the route", triage_entity,
                    OPTIMIZER_LLM_TRIAGE_LOCAL_PREFIX,
                )
                self._triage_uncapped_warned = True
            triage_flagged = await self._triage_pass(triage_entity, prompt)
            if not triage_flagged:
                _LOGGER.debug(
                    "OptimizationLLMTier: triage skipped premium (%s flagged "
                    "no deep analysis needed)", triage_entity,
                )
                # Commit the signature — the LLM "decision" for this
                # finding-set has been made (don't re-spam triage).
                self._last_findings_signature = new_sig
                return []

        # Rolling-24h premium cap.
        cap = int(config.get(
            CONF_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
            DEFAULT_OPTIMIZER_LLM_MAX_INVOCATIONS_PER_24H,
        ))
        if not self._under_daily_cap(cap):
            _LOGGER.info(
                "OptimizationLLMTier: rolling-24h premium cap (%d) reached "
                "— skipping premium pass this cycle", cap,
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
            # B-B7: commit signature now — we got a clean response with
            # no usable findings; no point re-asking next cycle.
            self._last_findings_signature = new_sig
            return []

        # B-B4: cap LLM-emitted critical+high findings per cycle.
        findings = self._cap_severity_volume(findings)

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
        # B-B7: commit signature after successful parse path completes.
        self._last_findings_signature = new_sig
        return applied

    # ------------------------------------------------------------------
    # Delta gate
    # ------------------------------------------------------------------

    def _signature(self, findings: list) -> tuple:
        """Reduce a finding list to a hashable dedup signature.

        A-MED-2 fix-up: META rows (per-cycle `cycle_ok` sentinel) are
        EXCLUDED — they fire every cycle by design and would defeat the
        delta gate. Time-varying fields are never included.
        """
        sig: list = []
        for f in findings or []:
            try:
                # Exclude META sentinel rows from the signature.
                dim_str = str(getattr(f, "dimension", ""))
                if dim_str == "meta":
                    continue
                # `dedup_key` is the canonical Phase-1 dedup tuple. Fall
                # back to (level, target_id, dimension) when missing.
                # Note: dedup_key is constructed without timestamps in
                # Phase-1 emitters (see optimization.py: `dedup_key=(...)`
                # built from level/target_id/dimension/entity_id only).
                k = getattr(f, "dedup_key", None)
                if not k:
                    k = (
                        getattr(f, "level", None),
                        getattr(f, "target_id", None),
                        dim_str,
                    )
                sig.append(k)
            except Exception:  # noqa: BLE001
                continue
        return tuple(sorted(str(x) for x in sig))

    def _finding_delta_present(self, tier1_findings: list) -> bool:
        """Return True when the finding-set differs from the prior cycle.

        Updates the cached signature on every call so the very first
        cycle (no prior signature) is treated as a delta.

        Kept for backward-compat with callers / tests; ``run_cycle`` no
        longer routes through this helper (B-B7 — signature must commit
        AFTER the parse, not before the LLM call).
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

    async def _seed_premium_invocations_from_db(self) -> None:
        """A-CRIT-1 / C-MED-3: seed ``_premium_invocations`` from the DB
        so the rolling-24h premium cap survives a restart.

        Same approach Phase-1 uses for its rate-cap deque
        (``OptimizationCoordinator.async_setup`` H2). Counts rows in
        ``optimization_findings`` with ``created_by="tier2_llm"`` in the
        last 24h — each Tier-2 LLM finding represents one premium
        invocation worth of cost. Best-effort: any failure logs at DEBUG
        and leaves the in-memory list empty (caps cold-start, never
        bypassed in the OTHER direction).
        """
        try:
            db = self.hass.data.get(DOMAIN, {}).get("database")
            if db is None or not hasattr(db, "get_recent_optimization_findings"):
                return
            rows = await db.get_recent_optimization_findings(limit=500)
            cutoff = dt_util.utcnow() - timedelta(hours=24)
            seeded = 0
            for r in rows or []:
                if not isinstance(r, dict):
                    continue
                if r.get("created_by") != OPTIMIZER_CREATED_BY_TIER2_LLM:
                    continue
                ts_raw = r.get("timestamp")
                if not ts_raw:
                    continue
                try:
                    ts = datetime.fromisoformat(str(ts_raw))
                except (TypeError, ValueError):
                    ts = dt_util.utcnow()
                if cutoff.tzinfo is None and ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                elif cutoff.tzinfo is not None and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=cutoff.tzinfo)
                if ts >= cutoff:
                    self._premium_invocations.append(ts)
                    seeded += 1
            if seeded:
                _LOGGER.info(
                    "OptimizationLLMTier: seeded premium-invocation history "
                    "with %d Tier-2 LLM rows from the last 24h", seeded,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug(
                "OptimizationLLMTier: premium seed from DB failed (non-fatal)",
                exc_info=True,
            )

    def _cap_severity_volume(self, findings: list) -> list:
        """B-B4: cap LLM-emitted critical/high findings per cycle to
        prevent NM spam. Excess findings get DOWNGRADED to medium with a
        payload note (rather than dropped) so the operator still sees
        the issue, just below the SEVERE notification threshold.
        """
        crit_count = 0
        high_count = 0
        for f in findings:
            sev = getattr(f, "severity", "")
            if sev == "critical":
                if crit_count >= OPTIMIZER_LLM_MAX_CRITICAL_PER_CYCLE:
                    f.severity = "medium"
                    payload = dict(getattr(f, "payload", {}) or {})
                    payload["downgraded_from"] = "critical"
                    payload["downgrade_reason"] = "per_cycle_severity_cap"
                    f.payload = payload
                else:
                    crit_count += 1
            elif sev == "high":
                if high_count >= OPTIMIZER_LLM_MAX_HIGH_PER_CYCLE:
                    f.severity = "medium"
                    payload = dict(getattr(f, "payload", {}) or {})
                    payload["downgraded_from"] = "high"
                    payload["downgrade_reason"] = "per_cycle_severity_cap"
                    f.payload = payload
                else:
                    high_count += 1
        return findings

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

        A-MED-4 fix-up: cap the resolved prompt to
        ``OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS`` so a runaway live
        override can't blow up the prompt body / paid-backend cost.
        Oversized live overrides log WARNING and fall back to the
        const rather than truncating mid-instruction (which could
        accidentally drop a safety clause).
        """
        live = config.get(CONF_OPTIMIZER_LLM_SYSTEM_PROMPT)
        if isinstance(live, str) and live.strip():
            if len(live) > OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS:
                _LOGGER.warning(
                    "OptimizationLLMTier: live system prompt exceeds %d "
                    "chars (got %d) — falling back to in-code const so a "
                    "truncated instruction doesn't lose a safety clause",
                    OPTIMIZER_LLM_SYSTEM_PROMPT_MAX_CHARS, len(live),
                )
                return OPTIMIZER_LLM_SYSTEM_PROMPT
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

        A-HIGH-2 / B-B3 fix-up: as we walk the substrate, accumulate the
        union of every entity_id referenced (rooms, sensors, prior
        actions). Saved as ``self._corpus_entity_ids`` and used by
        :meth:`_parse_findings` to reject LLM findings whose
        ``target_entity`` isn't in the corpus (hallucination guard).
        """
        # A-HIGH-2 / B-B3: reset and rebuild allowlist sets on every cycle.
        self._corpus_entity_ids = set()
        self._corpus_target_ids = {"house"}

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
                    self._corpus_target_ids.add(name)
                    comfort = self.coordinator._read_per_room_comfort(entry)
                    occupied = self.coordinator._is_room_occupied(entry)
                    # A-HIGH-2 / B-B3: harvest every entity_id this room
                    # references, so the LLM hallucination guard knows
                    # what's legal to actuate.
                    room_eids: list[str] = []
                    merged = {**(entry.data or {}), **(entry.options or {})}
                    for v in merged.values():
                        if isinstance(v, str) and "." in v and v.count(".") == 1:
                            # Coarse "looks like an entity_id" filter —
                            # accept "domain.object_id"; never the full
                            # URL/path/text overrides.
                            self._corpus_entity_ids.add(v)
                            room_eids.append(v)
                        elif isinstance(v, list):
                            for x in v:
                                if (isinstance(x, str) and "." in x
                                        and x.count(".") == 1):
                                    self._corpus_entity_ids.add(x)
                                    room_eids.append(x)
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
                        "entities": sorted(set(room_eids)),
                    })
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        corpus.rooms = rooms

        # Recent findings — last 24h, capped at _MAX_RECENT_FINDINGS.
        # OPT-META-BOOT-TRANSIENT-1 (2026-08-15): if the RAM cache
        # `_last_findings` is empty (post-restart transient — the
        # coordinator hasn't run its first cycle yet), fall back to the
        # boot-seed cache populated in `OptimizationCoordinator.async_setup`
        # from `db.get_recent_optimization_findings`. Without this the
        # meta pass sees `findings_recent=[]` alongside a nonzero
        # `_open_findings_count` (durable) and produces a false HIGH
        # "LLM cannot see problems" every restart.
        #
        # Card adjudication: do NOT make corpus assembly async — the DB
        # read is pre-fetched into the coordinator; consumer reads
        # remain sync.
        recent: list[dict] = []
        try:
            ram_cache = getattr(self.coordinator, "_last_findings", []) or []
            if ram_cache:
                source_iter = ram_cache[-_MAX_RECENT_FINDINGS:]
                for f in source_iter:
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
            else:
                # Boot-transient fallback: read the pre-fetched DB rows.
                boot_seed = getattr(
                    self.coordinator, "_boot_findings_seed", []
                ) or []
                for row in boot_seed[-_MAX_RECENT_FINDINGS:]:
                    try:
                        recent.append({
                            "timestamp": row.get("timestamp"),
                            "level": row.get("level"),
                            "target_id": row.get("target_id"),
                            "dimension": str(row.get("dimension") or ""),
                            "severity": row.get("severity"),
                            "confidence": row.get("confidence"),
                            "description": row.get("description"),
                            "created_by": row.get("created_by"),
                        })
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            pass
        # Include the current tier-1 finding set as well so the LLM sees
        # exactly what the rule engine just emitted.
        for f in (tier1_findings or [])[-_MAX_RECENT_FINDINGS:]:
            try:
                tid = getattr(f, "target_id", None)
                if isinstance(tid, str) and tid:
                    self._corpus_target_ids.add(tid)
                payload = getattr(f, "payload", None) or {}
                if isinstance(payload, dict):
                    eid = payload.get("entity_id")
                    if isinstance(eid, str) and "." in eid:
                        self._corpus_entity_ids.add(eid)
                recent.append({
                    "timestamp": getattr(f, "timestamp", None),
                    "level": getattr(f, "level", None),
                    "target_id": tid,
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
        """Pull the last N optimizer-emitted activity rows.

        Side-effect: any ``entity_id`` field on a prior-action row is
        added to ``self._corpus_entity_ids`` so the LLM can legally
        reference an entity it has previously been told to actuate.
        """
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
                        eid = r.get("entity_id")
                        if isinstance(eid, str) and "." in eid:
                            self._corpus_entity_ids.add(eid)
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

        async def _call():
            return await self.hass.services.async_call(
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

        try:
            # A-LOW-2 fix-up: hard timeout so a hung backend can't park
            # the 5-min optimizer cycle. Uses ``asyncio.wait_for`` for
            # portability across the test runtime (Py 3.9) and the HA
            # production runtime (Py 3.12+).
            result = await asyncio.wait_for(
                _call(), timeout=OPTIMIZER_LLM_AI_TASK_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "ai_task.generate_data timed out after %ds (entity=%s) — "
                "skipping this cycle's LLM call",
                OPTIMIZER_LLM_AI_TASK_TIMEOUT_S, entity_id,
            )
            return None
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

        A-MED-1 fix-up: precedence is strict. If ``raw["data"]`` is a
        dict, we ONLY look under ``data["findings"]`` — we do NOT fall
        back to a flat ``findings`` key (that would silently union two
        independent shapes). Mirrors the config_flow AI rule-parser.
        """
        if not isinstance(raw, dict):
            return None
        # v5.2.1: the structured output is a `findings_json` STRING (a JSON
        # array) — see OPTIMIZER_LLM_STRUCTURE. Parse it here. Still tolerate
        # a pre-v5.2.1 `findings` list (some backends may already coerce).
        container = raw["data"] if isinstance(raw.get("data"), dict) else raw
        fjson = container.get("findings_json")
        if isinstance(fjson, str):
            try:
                parsed = json.loads(fjson)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "LLM findings_json was not valid JSON — skipping cycle",
                )
                return None
            return parsed if isinstance(parsed, list) else None
        findings = container.get("findings")
        if isinstance(findings, list):
            return findings
        # If the response nested under `data`, strict precedence: do NOT roll
        # over to a flat key (mirrors the config_flow AI rule-parser).
        if isinstance(raw.get("data"), dict):
            return None
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
                # B-B4 fix-up: soft-clamp LLM-supplied confidence so an
                # operator who pins the confidence gate at 1.0 retains a
                # "no autonomous LLM action" failsafe.
                if confidence > OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX:
                    _LOGGER.info(
                        "OptimizationLLMTier: clamping LLM-supplied "
                        "confidence %.3f → %.3f on finding[%d]",
                        confidence,
                        OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX,
                        idx,
                    )
                    confidence = OPTIMIZER_LLM_CONFIDENCE_CLAMP_MAX
                target_level = str(row.get("target_level") or "").strip()
                if target_level not in ("house", "zone", "room"):
                    raise ValueError(f"bad target_level: {target_level!r}")
                target_id = row.get("target_id")
                if not isinstance(target_id, str) or not target_id:
                    raise ValueError("target_id must be a non-empty string")
                # A-HIGH-2 / B-B3 fix-up: target_id must be in the
                # corpus allowlist. The empty/cold-substrate case
                # (no rooms loaded) is tolerated — only enforce the
                # check when we have at least the "house" sentinel
                # plus one real target.
                if (len(self._corpus_target_ids) > 1
                        and target_id not in self._corpus_target_ids):
                    _LOGGER.info(
                        "OptimizationLLMTier: rejected finding[%d] — "
                        "target_id %r not in corpus (allowed: %s)",
                        idx, target_id,
                        sorted(self._corpus_target_ids),
                    )
                    continue
                description = str(row.get("description") or "").strip()
                if not description:
                    raise ValueError("description must be non-empty")
                # v5.4 D2c — optional `reasoning` row field. Additive +
                # malformed-tolerant: non-string / oversize values are
                # normalized rather than rejected so existing-shape LLM
                # responses keep working.
                _raw_reasoning = row.get("reasoning")
                if isinstance(_raw_reasoning, str):
                    reasoning = _raw_reasoning.strip()[:512]
                else:
                    reasoning = ""
                proposed = row.get("proposed_action_or_null")
                if proposed is not None and not isinstance(proposed, dict):
                    raise ValueError(
                        "proposed_action must be null or an object"
                    )
                action_class = None
                if isinstance(proposed, dict):
                    # B-B1 fix-up: action_class is DERIVED from the
                    # service domain, NEVER trusted from the LLM. This
                    # makes the L2/L3 chokepoint split fully
                    # tamper-resistant.
                    derived_class = self._derive_action_class(proposed)
                    llm_class = proposed.get("action_class")
                    if (isinstance(llm_class, str) and llm_class
                            and llm_class != derived_class):
                        _LOGGER.info(
                            "OptimizationLLMTier: LLM-supplied "
                            "action_class %r disagrees with derived %r "
                            "on finding[%d] — using derived",
                            llm_class, derived_class, idx,
                        )
                    action_class = derived_class
                    if action_class not in (
                        "reversible_device", "config_write",
                    ):
                        raise ValueError(
                            f"bad derived action_class: {action_class!r}"
                        )
                    # A-HIGH-2 / B-B3: target_entity hallucination guard.
                    target_eid = (
                        proposed.get("target_entity")
                        or proposed.get("entity_id")
                        or ""
                    )
                    if (isinstance(target_eid, str) and target_eid
                            and self._corpus_entity_ids
                            and target_eid not in self._corpus_entity_ids):
                        _LOGGER.info(
                            "OptimizationLLMTier: rejected LLM finding — "
                            "target_entity %r not in snapshot (finding[%d])",
                            target_eid, idx,
                        )
                        continue
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
                reasoning=reasoning,
            )
            out.append(finding)

        if out:
            _LOGGER.info(
                "OptimizationLLMTier: emitted %d Tier-2 findings "
                "(created_by=tier2_llm)", len(out),
            )
        return out

    @staticmethod
    def _service_full_name(proposed: dict) -> str:
        """Compose ``<domain>.<service>`` from the LLM-proposed action.

        B-B5 fix-up: returns ``""`` when domain OR service is missing
        (the chokepoint's domain allowlist will reject the empty
        domain). Mirrors the AI rule-parser's expectation that every
        proposed action is fully qualified.
        """
        domain = str(proposed.get("domain") or "").strip()
        service = str(proposed.get("service") or "").strip()
        if not service:
            return ""
        if "." in service:
            # Caller passed "domain.service" — accept and re-derive parts.
            parts = service.split(".", 1)
            if len(parts) == 2 and all(p.strip() for p in parts):
                return service
            return ""
        if not domain:
            return ""
        return f"{domain}.{service}"

    @classmethod
    def _derive_action_class(cls, proposed: dict) -> str:
        """B-B1 fix-up: derive ``action_class`` from the service domain.

        Truth table:
          - domain in OPTIMIZER_ALLOWED_DOMAINS_CONFIG (number, select)
            → ``config_write``
          - domain in OPTIMIZER_ALLOWED_DOMAINS_DEVICE (light, switch,
            fan, cover, climate) → ``reversible_device``
          - anything else → ``""`` (will fail the domain allowlist at
            the chokepoint — explicit failure beats silent fallback).
        """
        full_service = cls._service_full_name(proposed)
        domain = full_service.split(".", 1)[0] if "." in full_service else ""
        if domain in OPTIMIZER_ALLOWED_DOMAINS_CONFIG:
            return "config_write"
        if domain in OPTIMIZER_ALLOWED_DOMAINS_DEVICE:
            return "reversible_device"
        return ""

    @classmethod
    def _filter_service_data(cls, service_data: dict) -> dict:
        """A-HIGH-3 fix-up: allowlist ``service_data`` keys per the
        const ``OPTIMIZER_LLM_SERVICE_DATA_ALLOWED_KEYS``. Unknown keys
        are dropped with an INFO log so the operator can see what the
        LLM tried to pass but was rejected.
        """
        out: dict = {}
        for k, v in (service_data or {}).items():
            if k in OPTIMIZER_LLM_SERVICE_DATA_ALLOWED_KEYS:
                out[k] = v
            else:
                _LOGGER.info(
                    "OptimizationLLMTier: dropped LLM service_data key "
                    "%r (not in allowlist)", k,
                )
        return out

    @classmethod
    def _normalize_proposed_action(cls, proposed: dict) -> dict:
        """Shape the LLM-proposed action dict into the chokepoint's
        expected format: ``{service, service_data, target_entity,
        action_class}``.

        Fix-ups applied:
          - B-B1: action_class derived from domain (not LLM-supplied).
          - B-B5: bare service (missing domain) yields service="" —
            chokepoint's empty-domain allowlist check then rejects it.
          - A-HIGH-3: service_data keys filtered to a per-class allowlist.
        """
        full_service = cls._service_full_name(proposed)
        action_class = cls._derive_action_class(proposed)
        target = (
            proposed.get("target_entity")
            or proposed.get("entity_id")
            or ""
        )
        raw_service_data = proposed.get("service_data") or proposed.get("data") or {}
        if not isinstance(raw_service_data, dict):
            raw_service_data = {}
        filtered_service_data = cls._filter_service_data(raw_service_data)
        return {
            "service": full_service,
            "service_data": filtered_service_data,
            "target_entity": str(target),
            "action_class": action_class,
        }
