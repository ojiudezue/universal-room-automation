# Review C (mutation) - room-occupied-registry @4761b7919

45 single-site source mutations, 7 test files (new room_entities x3, fan_sweep_trio, memory_mvp, occupied_fan_off_guard, notification_manager; 210 pass baseline). Tree clean after.

RED (36): uid build, domain arg, options-merge, tie->first, tie uncounted, miss/no-entry uncounted, fallback counter, boot window, daily latch, warn..., built-id-on-miss, slug inexact, entry_id carry/ignore/name-fallback, guard+observer slug-built, key, baseline x3, facade x3, NM x4, coordinator/switch/fan_veto fallback counts, house_status misses.

GREEN (findings):
- M03 room_name exact -> substring: GREEN. MEDIUM (Bath/Bathroom mis-resolve untested).
- M17 slug miss uncounted: GREEN. MEDIUM (R3/R4 trip-wire path for unknown slug).
- M19 page kind/severity: GREEN. LOW.
- M13 ENTRY_TYPE_ROOM filter: GREEN. LOW.
- M12 WARN on 1st (not 2nd) miss: GREEN. LOW.
- M16 consecutive-miss reset on hit: GREEN. LOW.
- M21 summary fallback-count: GREEN. LOW.
- M45 house_status fallbacks field: GREEN. LOW.
Equivalent/trivial: M26 (None->absent entity), M29 (log text), M18 (_note_first_call always precedes).

Verdict: FIX-REQUIRED (add 2 MEDIUM tests; LOWs in-cycle).
