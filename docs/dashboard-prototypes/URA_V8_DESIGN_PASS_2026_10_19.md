# URA v8 dashboard design pass — 2026-10-19 (overnight)

Scope: Lovelace dashboard `ura-v8` only, edited through `ha_config_set_dashboard` (python_transform with config_hash). No entities, code, automations or other dashboards were changed. Every template change was rendered first with `ha_eval_template` against live state.

Passes done: 4 (stopped at plateau; see "Not done").

## Method

- Inventory from the stored config (backup `ura-v8-backups/20261019T032425_pre-pass1.json`).
- Eyes: claude-in-chrome against `http://192.168.13.13:8123/ura-v8/<view>`. Desktop is 1069–1284 px wide. For phone, `resize_window` would not go below 495 px, so "phone" shots are at 495 px. The 390 px check before the pass was done with a same-origin 390 px iframe.
- Speed: in-page JS timing of template render was unreliable. Deep shadow-DOM polling froze the renderer, so speed is judged by (a) whether markdown had rendered about 8–10 s after a cold load and (b) template listener scope from `ha_eval_template` (`all`/domain listeners versus per-entity listeners).

### Scoring

Each view gets 0–2 on 5 axes: glance, one visual language, phone, speed, honesty (units, age, stale). Graphs are scored on Energy only, since it is the only view with a graph. The total is out of 10.

## Inventory (before)

| View | Sections | Notable cards | Heavy bits |
|---|---|---|---|
| Quick Actions | 6 | 20 button-card | none |
| Now | 4 | 8 button-card, 2 markdown | none |
| Residence | 10 | 154 tile, 66 markdown, 53 bubble pop-ups, 47 auto-entities | Heaviest view by far (125 KB config). The pop-ups carry most of the weight |
| Energy & EV | 16 | 8 markdown, 1 mini-graph, energy-sankey + distribution + devices-graph + date-selection | "Top draws" template iterated **all** `states.sensor`. The energy-* cards duplicated the HA Energy panel. The renderer froze several times on this view |
| People | 9 | 10 markdown, 10 tiles | 2 templates iterated `states.sensor` (vacancy countdown, guest evidence) |
| Security | 8 | 24 picture-entity (camera snapshots) | camera snapshot refresh |
| Climate | 11 | 4 markdown, 3 thermostat | none |
| Health | 7 | heroes, NM tiles | NM Delivery and Alert State shown twice |
| Music | 1 | media card | none |

Style references (kept as the target language): Storm Readiness (Energy section 9), Presence Diagnostics (People), HA Health Monitor (Health). Each is a hero button-card, a heading and a markdown table.

## Scores

| View | Before | After | Main driver |
|---|---|---|---|
| Actions (Quick Actions) | 7 | 8 | tab label no longer wraps on phone |
| Now | 6 | 7 | hero colours now carry state, tab label fix |
| Rooms (Residence) | 5 | 7 | gaps of about 70 px between room rows removed (card 110 px in a 184 px slot) |
| Energy | 4 | 7 | 5 one-card sections became one "Energy now" block, the all-sensor template was scoped, duplicate energy-* cards were replaced by a shortcut, and the raw ISO time and entity IDs were cleaned up |
| People | 6 | 7 | census heroes side by side above the detail table, 2 all-sensor templates scoped |
| Security | 6 | 7 | interior cameras hidden below 768 px |
| Climate | 6 | 6 | untouched; markdown is still slow to first paint |
| Health | 6 | 8 | heroes merged, colour follows state (All Clear green, Advisory orange), duplicate NM tiles removed |
| Music | 7 | 7 | untouched |

Screens: `ura-v8-screens/before_*` and `after_*`. The main pairs are:
- Energy: `before_desktop_energy_top.jpg` vs `after_desktop_energy_top.jpg`, `before_phone_energy_top.png` vs `after_phone_energy_top.jpg`, `after_phone_energy_situation.jpg`
- Rooms: `before_desktop_rooms_gaps.jpg` vs `after_desktop_rooms_nogaps.jpg`
- People: `before_desktop_people_top.jpg` vs `after_desktop_people_top.jpg`
- Health: `before_desktop_health_top.jpg` vs `after_desktop_health_top.jpg`, `after_phone_health_top.jpg`
- Phone tab bar: `before_phone_now.png` ("Quick Actions" and "Energy & EV" wrap onto two lines) vs `after_phone_now.jpg`

## What changed and why

### Pass 1: layout, phone and colour
- View titles: "Quick Actions" became "Actions", "Residence" became "Rooms", and "Energy & EV" became "Energy". The labels wrapped onto two lines in the phone tab bar. Paths are unchanged, so deep links still work.
- Rooms: every `room_card` changed from `grid_options.rows` 3 to 2. The card is 110 px tall and sat in a 184 px slot, which left a gap after every row.
- `hero` template: the value font is now `clamp(30px, 9vw, 44px)` (it was 44 px, and "Self Consumption" was clipped on phone). The label now uses nowrap with an ellipsis.
- Energy: the 5 single-hero sections (House Draw, Battery Strategy, Solar, SOC, EV) and Top draws now sit in one `column_span: 2` section, "Energy now", at `columns: 12` each. That gives 2-up on desktop and 1-up on phone.
- Colour means state:
  - Informational heroes (House Draw, Solar, Strategy, EV, Now › House State) are neutral blue.
  - Battery SOC (and the Battery Strategy hero on Now) is green, red below `reserve_soc`, or orange when unknown.
  - EV is orange on error, fault or unknown.
  - Coordinators is green on `all_clear`, otherwise red, or orange when unknown.
  - Safety is green when ok, orange on advisory, watch or unknown, otherwise red.
- Health: the Coordinators and Safety heroes are merged into "Health at a glance". The pv now shows "All Clear" instead of the raw `All_clear`. The duplicate NM Delivery and NM Alert State tiles were removed from Coordinator Health; they remain in Notification Manager.

### Pass 2: Energy speed and honesty
- Top draws: the template now uses `integration_entities('span_panel')` instead of looping over `states.sensor`. It listened to every sensor in the house and now listens to 51 SPAN entities. Output is identical (verified) and is now a Circuit | kW table.
- Energy Situation: the duplicate draw, solar and battery lines were removed, because the heroes show them. It is now a table (Situation / Why / Cost now / Next as "14h 0m") with an "Updated N ago" line.
- Battery Strategy Detail: `charge_window_opens_at` now reads "Mon 2:30 PM" instead of a raw ISO timestamp.
- EV detail: the paused-plugs list shows friendly names instead of `switch.smartplug_...` entity IDs.
- "Energy Dashboard" (date selection, sankey, distribution, devices graph) is replaced by one shortcut to `/energy`. It duplicated the built-in Energy panel and was the heaviest statistics load on the view.
- The graph heading now reads "Solar vs house draw · last 24 h".

### Pass 3: People
- Vacancy countdown and Guest evidence no longer iterate `states.sensor`. They use `integration_entities('universal_room_automation')` (and `expand()` for the guest counts). Output was verified identical.
- "Persons in House" and "Identified People" now sit side by side in one "House Census" block above the census table, which is renamed "Census detail".

### Pass 4: polish
- Hero value weight changed from 100 to 300. The thin dark-green "3" was barely readable on the dark card.
- Security › Interior cameras (9 snapshot cards) are now `visibility: screen (min-width: 768px)`. The phone no longer pulls 9 extra snapshots. Exterior and Egress cameras are unchanged.

## Not done (and why)

- **Climate**: not touched. Its markdown cards (Zone Timers and others) were still blank about 8 s after a cold load, as on other views. The cause is first-paint latency of server-side template subscriptions, not one obvious bad template, so it needs a per-template profile.
- **Residence pop-ups**: the 53 bubble-card pop-ups (47 auto-entities, 50+ cover and light tiles) are the largest render cost in the dashboard. Splitting them into per-room subviews, or slimming them, is a structural change. It needs operator buy-in because it changes how rooms are opened.
- **Forecast vs actual graph**: Solcast forecast against actual solar would need apexcharts-card (not installed) or a statistics-graph with a forecast entity. Not added. The existing mini-graph still mixes kW (solar) and W (house) on two axes; mini-graph has no unit factor I could verify.
- **Room-card colours**: occupied rooms still use the per-zone accent (purple, pink and so on) rather than one state colour. That is a taste call for the operator.
- **Data-age badges** were added only to Energy Situation. Other markdown tables (Storm, Presence Diagnostics, HA Health) already carry their own ages.
- **Speed numbers** are qualitative, because in-page JS timing froze the renderer. The renderer froze several times on Energy at desktop width, both before and after the pass. It did not reproduce on the last after-pass load, but I could not prove the fix.
- Phone shots are at 495 px rather than 390 px, because the browser window would not shrink further.

## Rollback

Backups are full `config` objects taken before each pass in `docs/dashboard-prototypes/ura-v8-backups/`:

| File | Restores the state before |
|---|---|
| `20261019T032425_pre-pass1.json` | everything in this doc (original) |
| `20261019T034113_pre-pass2.json` | pass 2 |
| `20261019T034237_pre-pass3.json` | pass 3 |
| `20261019T034438_pre-pass4.json` | pass 4 |

To restore, call `ha_config_set_dashboard(url_path="ura-v8", config=<file contents>)` with the current BestPracticeKey from `ha_get_skill_guide('references/dashboard-guide.md')`. That is a full replace. View paths never changed, so bookmarks survive either way.
