# Review C (test authority, per-site source mutation): b91f4add7 security lock freshness
Verdict: FIX-REQUIRED (test gaps only; no production bug found).
65 single-site mutations over freshness module, security.py, number.py, __init__.py, sensor.py.
Suites: test_security_lock_freshness, retry_cap, nm_cycle_a2_knob_surface, room_options_reload_suppression, lock_arrival_hold.
RED (47): max(), cache-restore filter, boot-grace filters, include_disabled, stale gate terms, debounce, common-mode, dedup, repage, refresh (call/service/target), page hazard/severity, clear-on-report, D4 page/anomaly/repage, Store load/save, listener, fallback recovery, sweep gate branches, stale-unlocked commanded, actions.extend, anomaly emit, setup ordering, knob keys.
GREEN = untested (18):
- ts > now future-stamp guard (FR _sweep cands)
- node_status disabled-sibling skip; non-zwave sibling platform filter
- ref fallback to grace_end when no real report
- common-mode clear (COMMON paged_ts pop); signal_paged_ts clear (D4)
- clear requires `not dead`; clear pops paged_kind
- D4 page requires `swept` (excluded zwave lock)
- _aware naive-tz rejection
- _num negative->default
- Numbers wiring: stale entry conf_key, min_val, repage entity_id
- reload-suppress keys (_NO_LIVE_ATTR_KEYS / OPTIONS_RELOAD_SUPPRESS_KEYS), both
- sensor attrs stale, freshness_age_h
Equivalent mutant: ls_val UNREAL check (parse yields None anyway).
Must-fix: add tests for the GREEN rows (esp. Numbers/reload keys, common-mode clear, future-stamp, excluded D4).
