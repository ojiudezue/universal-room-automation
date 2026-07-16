# Review record — v5.17.6: D-HIGH-2 exempt-bounded storm precharge (operator-ratified)

**Commit:** cfcd7573. Tier 1 (ura-reviewer-std). Verdict **SHIP**; LOW-only.
**Ratified semantics:** degraded storm precharge STARTS iff full_hold decision fresh (≤30 min; re-stamped every 5-min tick — living hold age ≈ 0, gate only refuses corpses/restored-unstamped) AND SOC resolvable on some tier. Refusals hold BACKUP at the storm reserve_floor with an explanatory reason ("awaiting fresh storm evaluation" / plain-blind).
**Verified by review (executed where it matters):** freshness stamping chain + tz consistency; try/finally suffix save/restore (no system-wide suppression leak); D2 blind de-escalation mutually exclusive by construction (soc-None short-circuit precedes precharge branch); D-MED-1 interaction intended (Enphase dropping CFG mid-storm degraded → no blind re-assert; safety bounded by hardware compliance); healthy path byte-identical (gated + reviewer-executed mutation RED).
| ID | Sev | Finding | Outcome |
|---|---|---|---|
| L-1 | LOW | refusal path double-annotates degraded suffix | accepted (harmless) |
| L-2 | LOW | helper's SOC-None branch dead at live site (caller pre-guards) | kept as defense-in-depth, noted |
**Deploy plan:** with the next deploy window (morning pre-11:00 preferred; stub-off production behavior = v5.5.0 status quo, no storm forecast — no urgency restart tonight).
