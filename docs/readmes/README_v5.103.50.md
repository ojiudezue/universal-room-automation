# URA v5.103.50 — Rooms never pick up device-settings switches

Tier 2: measured first (D0), plan + plan review, build, two reviews (A correctness/test authority — FIX-REQUIRED then fixed and re-drilled; B live impact — SHIP), full-suite name-diff 0 new. Card: ROOM-CREATE-AREA-PREFILL-DETRITUS-1.

## Problem
Creating rooms from an area (especially bulk create) filled their switch lists with every switch in the area — Sonoff relay `detach` modes, mmWave `anti_interference`, LED/indicator and firmware toggles, even URA's own switches (Wigton's House room got `switch.universal_room_automation_domain_coordinators`). URA then switched those on/off with occupancy. Measured: the worst offenders (Sonoff `detach`, Z2M `anti_interference`, Alexa `do_not_disturb`, Dreo `child_lock`) carry no entity category, so a category filter alone would not stop them.

## Fix
- **Room creation** (single + bulk share one choke point, `_get_area_entities`): never prefill URA's own entities, config/diagnostic entities, hidden/disabled entities, helper platforms, or entities whose name has a whole word `detach`, `anti_interference`, `do_not_disturb`, `child_lock`, `indicator` (whole-word: `detachable_cover_cam` is kept).
- **Runtime guard** at all four places URA switches entities from a room's switch/device lists: URA-own, config/diagnostic, and the name words are never actuated — even if already in a stored config. Helpers (input_boolean, template, groups) and hidden relays still work.
- **Boot scan:** one `URA-PREFILL-DETRITUS-GUARD` warning per room/entity/rule for leftovers already stored (it also lists lights/fans/covers, warn-only for those).
- One shared token rule (`const.PREFILL_DETRITUS_TOKEN_RE`).

## Live impact
Main house: exactly one stored leftover is now blocked — Kitchen Hallway Garage `switch.dimmer_wifi_matter_tapo550d_garagekitehenhallway_auto_update_enabled` (a firmware auto-update toggle). No real light/relay/fan affected. Wigton was cleaned by hand on 2026-10-10.

## Live validation (prospective)
- After restart: exactly one `URA-PREFILL-DETRITUS-GUARD` warning (Kitchen Hallway Garage tapo auto_update_enabled); no other URA errors.
- Kitchen Hallway Garage occupancy change ⇒ no service call to the tapo auto_update switch.
