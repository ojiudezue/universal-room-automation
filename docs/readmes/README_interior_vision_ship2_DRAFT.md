# Interior vision ship 2: describe on demand, with a fisheye dewarp (DRAFT)

Card VISION-INTERIOR-SIGHTINGS-1 (ship 2, plan `docs/planning/PLANNING_vision_interior_sightings.md` §9.D3, §8; ship
order §8c item 2) and FOYER-FISHEYE-DEWARP-1. Tier 2-DB. Branch `feature/interior-vision-ship2`. Version is set at
deploy.

## What it does

Send URA a text on iMessage or WhatsApp: `describe family room`, or `describe ezinne`. URA takes one still from that
room's camera, asks the vision model what is happening, and texts the answer back to you only:

> Family Room: 2 people. watching TV (on the sofa). playing with a dog (by the window). An evening at home.

- **Who may ask:** `select.ura_interior_describe_access` (Coordinator Manager device). Default `operator` (the NM
  security-ack persons, else the first NM person). `residents` lets any configured NM person ask; `any_resolved` anyone
  the channel resolves to a person. Anyone else gets "Not available." and no model call.
- **People:** `describe <person>` uses the person's Bluetooth room when its confidence is at least the notification
  bar (0.75), else their newest named face in an interior camera within 5 minutes ("Ezinne was last seen in Family Room
  2 min ago."), else "Can't place Ezinne right now."
- **Never names anyone from the picture.** The prompt forbids names, and URA removes any resident's name the model
  writes anyway.
- **Mood:** recorded with each description (observational, nothing acts on it). It is in the reply only when the Select
  is `operator_affect` and the operator asks.
- **Shared rooms only.** Bedrooms and bathrooms are never covered ("No camera in <room>").
- **Fisheye (Foyer):** a camera whose Protect lens sensor reads `360` is unwarped into two flat views before the call
  (no Frigate change, no new process). Other cameras send the still as is.
- **Limits:** `switch.ura_interior_vision` (off = no calls), `number.ura_interior_vision_daily_calls` (60),
  `number.ura_interior_vision_daily_cost_usd` (0.50 estimated), and one accepted request per person per minute. Replies
  at the limit: "Interior vision is off." / "Interior vision limit reached today." / "Please wait a minute before asking
  again."

Nothing here feeds the census, house state, security, locks, HVAC or room occupancy.

## Operator check before relying on the Foyer

The two Foyer views (`INTERIOR_DEWARP_VIEWS`) were set from a night still with nobody in it. In daylight with someone in
the foyer, send `describe foyer` and confirm the count. If a view misses the floor, the views are a reviewed constant
(per camera: `INTERIOR_DEWARP_VIEWS_BY_DEVICE`).

## Knobs

| Knob | Default | Rung |
|---|---|---|
| `switch.ura_interior_vision` | on | 3 (+ Camera Census option) |
| `number.ura_interior_vision_daily_calls` | 60 | 3 |
| `number.ura_interior_vision_daily_cost_usd` | 0.50 | 3 |
| `select.ura_interior_describe_access` | operator | 3 |
| `INTERIOR_VISION_EST_COST_PER_CALL` | 0.0003 | 1 |
| `INTERIOR_DESCRIBE_RESERVED_CALLS` | 10 (kept for describe from ship-3 sampling) | 1 |
| `INTERIOR_DESCRIBE_NM_COOLDOWN_S` | 60 | 1 |
| `INTERIOR_DESCRIBE_AFFECT_ENABLED` | True | 1 |
| `INTERIOR_VISION_CALL_TIMEOUT_S` / `INTERIOR_VISION_STILL_TIMEOUT_S` | 60 / 10 | 1 |
| `INTERIOR_DEWARP_ENABLED` | True | 1 |
| `INTERIOR_DEWARP_IN_FOV_DEG` / `_OUT_FOV_DEG` / `_OUT_PX` / `_JPEG_QUALITY` | 180 / 110 / 768 / 90 | 1 |
| `INTERIOR_DEWARP_VIEWS` | (-45, 20, 40), (-13, -15, -140) | 1 |
| `INTERIOR_VISION_ZERO_MIN_TRIGGERS` | 5 | 1 |
| `INTERIOR_VISION_ERROR_RATE_MAX` / `_ERRORS_MIN_CALLS` | 0.25 / 4 | 1 |
| `INTERIOR_FRAMES_LEFT_CHECK_ENABLED` | True | 1 |

## Acceptance (live, after restart)

| # | Criterion | How to check |
|---|---|---|
| 1 | Operator `describe family room` gets one description back within ~15 s | the reply text; one new `memory_episodes` row `episode_type = 'interior_description'` with non-null `people` |
| 2 | A second person (not the operator) gets "Not available." under the default | their reply; no new row |
| 3 | `describe foyer` is dewarped | diagnostics `interior_vision.vision.counters.dewarped_calls` >= 1; `groups_dewarp_capable` lists Foyer |
| 4 | No still left behind | `<config>/universal_room_automation/interior_stage/` empty; nothing new under `/media/llmvision/snapshots` |
| 5 | Caps hold | `interior_vision.vision.calls_today` <= `daily_cap` |
| 6 | Census untouched | `sensor.ura_census_guests_around` / census sensors unchanged by a describe |
| 7 | No affect in a non-`operator_affect` reply | the reply text |

Discrimination: a working build shows a row AND a reply; a broken still source shows "camera is not available" replies
and, after 5 such requests, the `interior_vision_zero_calls` page; a broken provider shows "Couldn't describe" replies
and the `interior_vision_errors` page.

## Evidence the dewarp works in HA

- The remap is pure numpy + Pillow (both pinned by HA core in `package_constraints.txt`; HA 2026.11.1 live loads `stream`
  (numpy) and `image_upload` (Pillow)). No ffmpeg subprocess: the HA core container's ffmpeg could not be inspected from
  the SSH add-on (no docker socket, no CLI token).
- Inside the fisheye circle it matches ffmpeg's own v360 (`input=fisheye:ih_fov=180:...:output=flat:h_fov=110`) within
  MAE < 1 grey level and p99 <= 5 for straight, single-axis and compound views (`test_interior_dewarp.py`; synthetic
  fixture generated by `scripts/probes/make_interior_dewarp_fixture.py` with ffmpeg 9.0.2).

Live validation: to be written back here after deploy (CLAUDE.md "Record Live Validation Back Into the README").
