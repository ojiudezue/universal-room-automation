# URA v5.103.44 — Night lights come on in Sleep even under sleep protection

Operator ruling (a), 2026-10-09: during Sleep, an occupied room's night lights always come on; sleep protection only holds back main lights, fans and covers. Two reviews (SHIP); one review gap fixed in-cycle; full-suite name-diff clean. Card: NIGHT-LIGHT-ACTION-SELECTOR-1.

## Problem
Master Bath Toilet (sleep protection on) got no night light at 04:49 CDT 10-09. Sleep protection ignores the first 2 motions in the room's sleep window (`motion entries needed to override sleep`, default 3), and that stopped all automation for the room — night light included. The background reconciler did not step in because it only reacts to light state changes.

## Fix
- While sleep protection is ignoring motion: an occupied room's night lights turn on with Sleep colour/brightness (manual hold respected). Main lights, fans, covers and the motion counter behave exactly as before.
- When the room empties under the same gate, its night lights turn off (except "leave on when empty" lights) and the motion counter resets, as a normal exit would.

## Live validation (prospective)
- Tonight: a first motion entry into Master Bath Toilet in its sleep window logs a night-light turn_on (sleep) in ura_activity_log with no main-light turn_on; leaving logs a night-light turn_off.
- No URA errors at boot.
