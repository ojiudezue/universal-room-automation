# Review A (Tier 1, local correctness): EC-CFG-SELFHEAL-FALSE-CRITICAL-1

Branch fix/ec-cfg-selfheal-reread, diff develop...HEAD (base 15d6ae73). Verdict: **SHIP**.

| Sev | Where | Finding |
|---|---|---|
| none | energy_write_verify.py:842-860 | The re-read goes through `_desire_matches_oracle` -> `_compare` (:1438), the same comparator the 15-min maturity check uses for OK (:1029). Unit handling (reserve %/fraction) and unit-mismatch return non-OK, so they still page. Unavailable/unknown oracle -> `_read_oracle_raw` returns None (:1477) -> not OK -> pages. No new trust is granted: whatever the oracle reports at the n>=3 tick, the maturity check would have accepted the same reading as OK and reset the same counter. |
| LOW (accepted) | :855 | Flap or stale-cache scenario: if the oracle reads the commanded value at each n=3 tick while the device is actually wrong, the page is suppressed forever. The same oracle reading already passes the maturity check, so this is the oracle trust boundary, not a new hole. The reserve local-witness tier is the defence against a lying cloud, and it only suppresses, it never confirms. |
| none | ordering | pending-episode check -> oracle re-read -> reserve local witness -> page. The order of the two suppressors does not change the page decision. The oracle branch resets the streak and the local-witness branch does not, which matches pre-existing behaviour. |
| none | test_energy_write_verification.py:1302 | The fixture change from 50 to 40 is legitimate. The old fixture paged while the oracle matched the commanded value, which is the false-CRITICAL this card removes. The test still asserts the page when the oracle disagrees. |

Tests: the 4 named files, 253 passed. Bug class: none new (closes a false-positive page; #53 does not apply because one shared comparator is reused).
