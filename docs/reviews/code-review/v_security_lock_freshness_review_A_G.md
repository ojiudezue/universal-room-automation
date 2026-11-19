# Review A + G: security lock freshness (b91f4add7, base cb05f181a)

Verdict: SHIP (one MEDIUM to fix in-cycle or card).

Tests from a clean export: test_security_lock_freshness.py 35 passed; lock sweep/retry/check subset 17 passed.

## Findings
1. MEDIUM, Bug Class #53-adjacent (held state not consumed). security_lock_freshness.py clear branch (`elif paged is not None and not p["dead"]`) plus security.py stale gate. A lock paged dead that comes back through a cache restore (unavailable -> locked, no later real report) is not dead, not stale (garage: last_seen disabled; Philips: never stale-eligible), so the record is held with no re-page and the sweep counts the restored "locked" as compliant again. That is the incident lock's exact shape. Zwave is partly covered by the D4 signal page every R; Philips has no cover. Fix: while paged_kind == "dead" and no real report > paged_ts, re-page at R ("back online, state not verified") and set compliance "unverified".
2. LOW. N=0 also turns off D3/D4. The knob comment says so (const.py). An operator can't keep dead pages alone. Acceptable.
3. LOW, cleared. The D4 page has no hazard_type. manager.py:1079 passes None to NM, at HIGH severity, the same quiet-hours path as other HIGH pages. Delivery works; it just has no light pattern.
4. Cleared. Timezones: `_aware` rejects naive stamps. Unavailable stamps are skipped. Recovery stamps are excluded, the boot grace filters stamps, the Store reload is guarded, refresh uses an empty target_device (manager.py:119 non-device path).

## Incident simulation (11-16 07:37 -> 11-18)
Node 10's last_seen is still disabled, so there is no stale page. The first page is D4 "signal disabled" at the first sweep after the grace period, repeated every 6 h. The dead page comes about 20 min after the lock went unavailable at 14:53 on 11-18. If last_seen is enabled and freezes while the lock is silent, the stale page comes about 19:38 on 11-16 (the freeze is not proven, per D0).

## G
No command site changed: the diff adds no lock/unlock/cover call, only comments. A stale unlocked lock still gets the proven lock.lock and retry cap. A stale locked lock is no longer read as compliant, which targets the "seems locked, is open" complaint. Accurate unlocked reports were already handled.
