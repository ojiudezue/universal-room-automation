# AUDIT: ura-v8 wall-panel renderer spin (URA-V8-PANEL-RENDER-SPIN-1)

Read-only static audit, 2026-10-26 02:0x CDT. No panel screen, dashboard, or adb write touched.
Sources: `/Users/okosisi/ha-config/.storage/lovelace.ura_v8` (385,809 B JSON), `lovelace_resources`, `themes/material-clean.yaml`,
`www/community/*/*.js` (grep only), HA recorder (`ssh ha sqlite3 mode=ro`, last 3600 s), homelab `docs/CONFIGS.md:714-718`.
Baseline: `adb -s 192.168.12.154:5555 shell top -b -n 1` at 02:03 CDT, screen off: `me.jxl.kiosk_satellite` 12.9%, nothing else hot (baseline only).

## Answer (honest version)
The config contains NO CSS animation, `@keyframes`, `mdi:loading`, `transition: all`, card-mod, `backdrop-filter`, apexcharts/power-flow-card
or seconds-clock on `now` or `rooms` (grep of the whole dashboard JSON: `animation`=0, `keyframes`=0, `backdrop`=0, `blur`=0, `card_mod`=0;
the only `pulse`/`gradient` hits are `health` and static gradients in templates). So there is no single "smoking gun" card in the config.
The cause is therefore in a shared runtime/library behaviour, not a card option. Ranked suspects below; the bisect order is the deliverable.

Also note a contradicting data point: `docs/CONFIGS.md:714` says on 2026-10-24 Up Hallway `map` ALSO spun at 104%, and that
navigating away and back (no reload) cleared it. So the spin is a renderer STATE entered on wake, not strictly a view property;
`rooms`/`now` may just be where panels sit. Treat view-specific attribution with caution.

## Facts gathered
- Views (path: raw size, sections): quick-actions 17 KB, now 7.9 KB (14 button-card, 1 auto-entities, 1 markdown), rooms 228 KB, energy 36 KB, people 25 KB, security 16 KB, climate 18 KB, health 8 KB, music 2 KB. All use theme `Material-Clean`.
- rooms section 8 (`views[2].sections[8]`) is 181 KB: 53 `custom:bubble-card` pop-ups (card_type pop-up, `#living_room` etc.), containing 175 markdown, 159 tile (many with features: 36 light-brightness, 47 cover-position, 50 cover-open-close, 13 fan-speed), 94 entities, 47 `custom:auto-entities`. Every pop-up body is instantiated at view load (hidden), not lazily.
- rooms sections 1-7: 47 `room_card` button-cards (`button_card_templates.room_card`, 5.9 KB, each with 1 nested button-card custom_field `icon2` plus a long JS `chips` field that reads `states[...]` of ~10 other entities).
- now: 10 `stat`, 2 `hero` (height 260 px, gradient), 1 `weather_hero` (260 px, 9 gradients, 5 nested button-cards), 1 `security_score` (5 nested button-cards), 1 auto-entities `binary_sensor.*_occupied` (wildcard over all states), welcome markdown with `now()` (re-renders ~1/min only).
- Recorder churn of entities referenced (1 h to 02:03): HA-wide 27.6 state writes/s. `now`: 19 literal entity ids, 1,362 changes/h (0.38/s), 14 distinct; top `sensor.span_panel_current_power_2` 238, `..._current_power` 233, `persons_in_house` 177, `ura_hvac_coordinator_mode` 134. `rooms`: 818 literal ids, 1,981 changes/h (0.55/s), 64 distinct; top same SPAN power pair, `zone_master_suite_energy_cost_today` 120, `master_bathroom_energy_saving_active` 118. => dashboard-referenced churn is LOW (<1/s); churn is not what burns a core. (Night-time; daytime rate is higher, not measured.)
- Wake-specific code in loaded resources (grep counts of `visibilitychange`/`requestAnimationFrame`/`setInterval`/`MutationObserver`):
  bubble-card 8/63/5/7, material-you-utilities 1/1/0/4, card-mod 0/0/1/1, kiosk-mode 0/0/0/5, button-card 0/0/2/0, auto-entities all 0, layout-card 0/0/0/1.
- `lovelace.map` has a different shape (no `views` key at that path; not inspected further) and carries no Material-Clean theme evidence; unverified.

## Ranked suspects
1. **material-you-utilities (global resource, wake handler).** `material-you-utilities.min.js`: `window.addEventListener("visibilitychange", async()=>{if(!document.hidden) for k of ["base_color","card_type","css_file"] await handler(...)})`, plus a MutationObserver on `style` that does `disconnect(); r(); observe()` (re-apply `background-color: var(--md-sys-color-surface)`). Fires exactly on screen wake and rewrites theme CSS across the whole DOM; a style-mutation feedback loop with the theme/card-mod root styling would pin CrRendererMain and raster. Matches "starts on wake, stops on screen off". Caveat: it loads on every dashboard incl. `/map`, so it only explains the asymmetry if MYU's stored settings or `Material-Clean` theme (set per view via `theme:`) interact. Whether MYU is enabled/configured on the panels is UNKNOWN (settings live in browser localStorage).
2. **Theme `Material-Clean` + `card-mod-root-yaml` on every view** (`themes/material-clean.yaml:7-14`; `card-mod-theme: Material-Clean`). `ura-v8` sets `theme: Material-Clean` on all 9 views; a theme change/re-apply on resume restyles the whole tree (`:host ha-app-layout, #view {padding-left:200px}` with `@media (min-width:768px)`; panels are 1600x900 at density 200, so the media query is likely true and the layout reflows). Differentiator vs `/map`: map is a different dashboard.
3. **rooms: 53 hidden bubble-card pop-ups (rooms only).** `views[2].sections[8].cards[0..52]`. bubble-card CSS uses `backdrop-filter: var(--custom-popup-filter)` with blur from `bg_blur` (default value NOT verified; none of the 53 configs set `bg_blur`), `.bubble-backdrop` position:fixed full-screen layer, 63 rAF sites, 8 visibilitychange sites. 53 compositor layers with possible backdrop blur on Mali is the best GPU/raster candidate for `rooms`, but it cannot explain `now` (no bubble-card there). Also 175 markdown + 47 auto-entities in that section each hold a websocket template/filter subscription and re-evaluate on hass updates.
4. **auto-entities with wildcard filter (now `sections[3].cards[1]`; rooms 47 per-room ones use literal ids, cheap).** `binary_sensor.*_occupied` + 4 excludes scans every state on each hass update (27.6/s HA-wide). CPU on main thread, not raster/GPU; plausible contributor to CrRendererMain on `now` but it is one card.
5. **now: tall gradient hero cards** `sections[2].cards[0,1,2]` (`hero`, `security_score` 260 px, `border-radius:30px`) and `sections[0].cards[5]` (`weather_hero`, 260 px, 9 gradient variants, 4 translucent `rgba(255,255,255,0.18)` nested cards over a gradient). Clip + gradient + alpha layers raster cost; static content so it should be cheap unless something invalidates it every frame (suspect 1/2).
6. **rooms: 47 `room_card` with long JS label/chips and nested button-card** (`button_card_templates.room_card`). Each re-renders on its own entity only (no `triggers_update` in rooms; 5 hits elsewhere on energy/people/health), so low rate. Side finding: `chips` reads other entities' `states[...]` without `triggers_update`, so the chips can go stale (correctness, not CPU).
7. **Kiosk/WebView, not the dashboard:** kiosk-mode (5 MutationObservers), custom-sidebar, browser_mod 3.4.0 all load on every dashboard. Kiosk Satellite's own wake path (screensaver dismiss, `ws_filter`) was ruled out by HomeLab; listed for completeness only.

Not found / ruled out by grep: card-mod per-card CSS, `@keyframes` in config, `mdi:loading`, `transition: all`, apexcharts (only on `energy`, 2), power-flow-card-plus (not in ura-v8 at all), layout-card (0 uses), clock-with-seconds, `now()` in high-rate templates (4 on `now`, 4 on `energy`, 1 `climate`; `now()` re-renders at most per minute).

## Bisect order for the attended session
Use a single test panel (Media Room, 192.168.12.154) with a fresh renderer each step; success = renderer <20% for 5 min after wake (`top`/`ks-spin-logger.sh`), failure = >80% within 15 s as already reproduced.
0. Control: wake on HA `/map` (known ~5%) and on a trivial new test dashboard with default theme and ONE markdown card. If the trivial dashboard spins, it is global (suspects 1/2/7), not ura-v8.
1. Same trivial dashboard but `theme: Material-Clean` (isolates suspect 2). Then default theme with `now` view JSON copied in (isolates cards from theme).
2. If still clean: copy `now` unmodified into a test dashboard with Material-Clean. If it spins, drop in order: weather_hero, security_score+heroes, auto-entities, stat cards (halving each time).
3. For `rooms`: test copy with section 8 (53 pop-ups) removed. If it calms, re-add pop-ups in halves; then set `bg_blur: 0` on all (a config knob, no code) and re-test.
4. Toggle MYU: in the browser's material-you-utilities settings (or temporarily disable the resource in a test profile) and wake again; this is the cheapest test of suspect 1 and needs no dashboard edit.
5. Navigate-away-and-back (as HomeLab did) is itself diagnostic: if the spin clears without reload, favour a resume-time style/observer loop (suspects 1/2) over a per-card cost.
Do not edit `ura-v8` itself until a test copy reproduces; all test dashboards need a backup per the ura-v8-backups convention.

## Falsifiers
- If a trivial default-theme dashboard (step 0) spins after wake, suspects 3-6 are dead.
- If disabling MYU (step 4) leaves the spin, suspect 1 is dead.
- If rooms still spins with section 8 removed, suspect 3 is dead.
