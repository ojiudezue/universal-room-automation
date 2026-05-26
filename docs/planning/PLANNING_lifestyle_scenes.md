# PLANNING — Lifestyle Scenes (All Off / Evening / Movie / Bed)

**Status:** Scoped, not started
**Type:** Config + cross-system spec (HA scenes/scripts + URA service surface + PWA wiring)
**Not versioned:** This is not a URA release cycle. Output is HA YAML / scripts / (optional) URA service handler, plus a one-line edit in the PWA repo.
**Trigger:** PWA Home + House tabs render a 4-button "Scenes" row pointing at placeholder entity_ids (`scene.all_lights_off`, `scene.evening`, `scene.movie`, `scene.bed`) that don't exist. User confirmed 2026-05-24: keep the scaffolding, build the 4 scenes for real.
**Recall hint:** "Resume lifestyle scenes"

---

## 1. Goal + Why

**Problem.** The PWA dashboard ships with 4 scene pills that 404 when clicked. The user has 55 existing scenes — all of them are Tech-Closet shade scenes (per-room open/close/privacy). Zero lifestyle / whole-house scenes exist today.

**Goal.** Build 4 lifestyle scenes the user actually fires daily:
- **All Off** — full-house shutdown (lights + media), used on exit or as a hard reset
- **Evening** — warm dim ambient in living areas, kitchen brightest, bedrooms untouched
- **Movie** — entertainment-room dark, hallways dim, non-TV media stopped
- **Bed** — full shutdown except master bedroom nightlight, doors locked, house mode → `sleep`

**Why HA-native scenes (and not URA services or scripts)?**

| Option | Pros | Cons | Fit |
|---|---|---|---|
| HA `scene.*` (YAML or UI) | Idempotent state restore; native `scene.turn_on` already wired in PWA; user can edit in HA UI | No conditional logic; can't call services beyond setting entity state | **Best for static state snapshots** (All Off, Evening) |
| HA `script.*` | Conditional logic, delays, service calls (lock.lock, mode shifts), iteration | Less idempotent (mid-run failures leave partial state); editing requires YAML or script editor | **Best for scenes that need >1 domain** (Bed, possibly Movie) |
| URA service (`universal_room_automation.scene_*`) | Composable with house-state-aware logic, can defer to coordinators, can react to per-room overrides | Requires a URA cycle; user can't edit in HA UI; couples PWA roadmap to URA release cadence | **Avoid unless logic genuinely needs URA's room/zone model** |

**Recommendation:** mix of A (scene) and B (script). No URA service for v1. If a scene grows logic later, promote it to a script; if a script grows house-mode awareness, promote it to a URA service.

**Orthogonality to House Mode.** The PWA House Mode pill row (Home / Sleep / Away / Guest / Vacation) writes to `select.universal_room_automation_house_state_override` — it's a STATE override, not an action. Lifestyle scenes are the inverse: they fire actions. Only the **Bed** scene crosses the line: it should ALSO flip house mode to `sleep` as a side effect.

---

## 2. Phase 0 — Discovery (PREREQUISITE, do before implementation)

This planning doc cannot enumerate the user's entities. **Run this inventory before Phase 1.** Use `ha_search_entities` (preferred) or SSH + `cat /config/.storage/core.entity_registry`.

### 2.1 Entity inventory checklist

Output expected — fill in a table per category at `docs/planning/lifestyle_scenes_inventory.md`:

**Lights** (`light.*`) — group by HA area:
| Area | entity_id | integration | supports color_temp? | supports brightness? |
|---|---|---|---|---|

**Media players** (`media_player.*`):
| Room | entity_id | integration | supports turn_off? | supports media_stop? |
|---|---|---|---|---|

**Covers** (`cover.*`) — exclude garage doors:
| Room | entity_id | type (shade / blind) | scene already exists in 55-scene set? |
|---|---|---|---|

**Locks** (`lock.*`):
| Door | entity_id | integration |
|---|---|---|

**Existing groups to check for** (don't fabricate — only use if discovered):
- `light.all_lights` / `light.all_indoor` / per-floor groups
- `media_player.everywhere` / `media_player.downstairs`
- `cover.all_motorized` / per-room shade groups

### 2.2 Integration capability spot-check

For each light integration found, confirm:
- **Hue** — exposes `hue.activate_scene` for native group-level activation (smoother than per-light `light.turn_on`). Hue scenes already imported as `scene.*` entities automatically.
- **Lutron Caseta** — `light.turn_on` with brightness_pct works; no native scene service in HA wrapper (verify against installed integration).
- **Z-Wave / generic dimmers** — `light.turn_on` with `brightness_pct` + `transition` if supported.

If integration supports a native "activate scene" service that's smoother than HA's serial per-light loop, prefer the script path (B) calling the native service over the HA scene path (A).

### 2.3 Output of Phase 0

A markdown file at `docs/planning/lifestyle_scenes_inventory.md` with the four tables populated. **Do not start Phase 1 without it.**

---

## 3. Scene-by-scene spec

### 3.1 All Off

**Intent.** Every light off in the house. All active media stopped. Locks unchanged. Covers unchanged. Used on "leaving" or as a panic-reset.

**Scope.** All `light.*` entities discovered in Phase 0. All `media_player.*` entities. Exclude: security cameras, motion-sensing nightlights with hardware fallback, refrigerator-internal lights.

**Implementation path.** **B — HA script.** Even though "all off" looks like a static state, the media domain needs `media_player.media_stop` *then* `media_player.turn_off`, and not every player supports both. A script lets us iterate + tolerate per-entity failures via `continue_on_error: true`.

**Sketch (post-inventory):**
```yaml
script:
  ura_scene_all_off:
    alias: "Lifestyle: All Off"
    sequence:
      - service: light.turn_off
        target:
          entity_id:
            - light.TBD_inventory_all_indoor_lights
        data:
          transition: 1
      - service: media_player.media_stop
        target:
          entity_id:
            - media_player.TBD_inventory_all_active
        continue_on_error: true
      - service: media_player.turn_off
        target:
          entity_id:
            - media_player.TBD_inventory_supports_turn_off
        continue_on_error: true
```

**Edge cases.**
- Lights that are HW-on (lamp switch flipped) cannot be turned off via HA — accept silently.
- A media player that's already off may reject `media_stop` — `continue_on_error: true`.
- Do NOT touch outdoor / security / nightlight `light.*` entities. Phase 0 must explicitly tag these as out-of-scope.

**Acceptance criteria.**
- **Verify:** Fire `script.ura_scene_all_off` from HA dev tools → all in-scope lights off within 2s; all in-scope media players stopped.
- **Verify:** Fire from PWA "All off" pill → same end state.
- **Live:** Walk the house — every in-scope light off, every media player off/stopped.

---

### 3.2 Evening

**Intent.** Warm, dim, ambient lighting in living areas. Kitchen brightest (still functional). Bedrooms untouched.

**Scope (default proposal — confirm with user):**
- IN: Living room, kitchen, dining, entry, hallways
- OUT: Bedrooms, guest rooms, garage, outdoor, basement utility

**Per-room targets (default proposal):**

| Room | Brightness % | Color temp (K) | Notes |
|---|---|---|---|
| Kitchen | 60 | 2700 | Functional, still warm |
| Living room | 35 | 2400 | Warm ambient |
| Dining | 45 | 2400 | Warm, accent |
| Entry | 40 | 2700 | Wayfinding |
| Hallways | 25 | 2700 | Low for path |

**Implementation path.** **A — HA scene.** Pure state snapshot, no conditional logic. Editable in HA UI. `scene.turn_on` with `transition: 2` for smooth fade.

**Sketch:**
```yaml
scene:
  - name: "Lifestyle: Evening"
    id: ura_scene_evening
    entities:
      light.TBD_kitchen_overhead:
        state: on
        brightness_pct: 60
        color_temp_kelvin: 2700
      light.TBD_living_room_lamps:
        state: on
        brightness_pct: 35
        color_temp_kelvin: 2400
```

**Hue optimization.** If inventory shows living-area lights are all Hue, replace with a Hue native scene (single round-trip to the bridge instead of N individual `light.turn_on` calls).

**Acceptance criteria.**
- **Verify:** Fire `scene.ura_scene_evening` from HA dev tools → in-scope lights match table within 2s.
- **Verify:** Fire from PWA "Evening" pill → same.
- **Live:** Walk living areas — warm dim. Walk bedrooms — unchanged.

---

### 3.3 Movie

**Intent.** Entertainment-room lights off. Hallways dim. Non-TV media paused/off. Optionally close motorized covers.

**Scope:**
- IN: Entertainment room (off), hallways adjacent (dim), kitchen/dining (TBD per user)
- OUT: Bedrooms, outdoor

**Implementation path.** **B — HA script.** Spans 2-3 domains (lights + media + maybe covers); needs `continue_on_error` for the media iteration; may need conditional logic (close covers only after sunset).

**Sketch:**
```yaml
script:
  ura_scene_movie:
    alias: "Lifestyle: Movie"
    sequence:
      - service: light.turn_off
        target:
          entity_id:
            - light.TBD_entertainment_room
        data:
          transition: 2
      - service: light.turn_on
        target:
          entity_id:
            - light.TBD_hallway_adjacent
        data:
          brightness_pct: 15
          color_temp_kelvin: 2400
          transition: 2
      - service: media_player.media_pause
        target:
          entity_id:
            - media_player.TBD_non_tv_active
        continue_on_error: true
```

**Edge cases.**
- TV itself must NOT be turned off — explicitly exclude.
- If covers close, they should NOT auto-reopen — that's a separate "Movie End" scene we are NOT building in v1.
- Sound bar / receiver state untouched.

---

### 3.4 Bed

**Intent.** All lights off except master bedroom nightlight. Doors locked. House mode set to `sleep`. Highest-value daily routine — fires once per night.

**Scope.**
- IN: every indoor `light.*` (off), master bedroom nightlight (5% / 2200K), exterior door locks, `select.universal_room_automation_house_state_override` → `sleep`
- OUT: garage interior, outdoor security lights

**Implementation path.** **B — HA script.** Multi-domain (lights + locks + URA select), needs per-lock fault tolerance.

**Sketch:**
```yaml
script:
  ura_scene_bed:
    alias: "Lifestyle: Bed"
    sequence:
      - service: light.turn_off
        target:
          entity_id:
            - light.TBD_all_indoor_except_master_nightlight
        data:
          transition: 3
      - service: light.turn_on
        target:
          entity_id: light.TBD_master_nightlight
        data:
          brightness_pct: 5
          color_temp_kelvin: 2200
      - service: lock.lock
        target:
          entity_id:
            - lock.TBD_front
            - lock.TBD_back
            - lock.TBD_garage_entry
        continue_on_error: true
      - service: select.select_option
        target:
          entity_id: select.universal_room_automation_house_state_override
        data:
          option: sleep
```

**Edge cases.**
- One lock already locked: `lock.lock` is idempotent — no error.
- One lock unreachable: `continue_on_error: true` keeps the sequence going. Surface as a notify later (not in v1).
- House-state override race: if the override is already `sleep`, re-selecting is a no-op.

**Acceptance criteria.**
- **Live:** Hit Bed on PWA at actual bedtime. Within 3s: house dark, locks click, sleep mode engaged.

---

## 4. PWA-side wiring

**File:** `/Users/okosisi/Code/ura-dashboard-pwa/src/data/scenes.ts`

**Change.** Replace placeholder entity_ids with real ones from Phases 1-4.

**Domain-prefix dispatch — ALREADY DONE.** As of 2026-05-24 (v6.0.1 PWA cycle 2 fix-up alongside Reviewer A/B fixes), `SceneButtons.tsx` infers the service domain from the entity_id prefix:
```ts
const [domain] = id.split(".");
await callService(domain, "turn_on", { entity_id: id }, null);
```
This means `scene.ura_scene_evening` and `script.ura_scene_bed` both work without per-pill conditionals. No further PWA-side changes needed beyond updating the 4 entity_id strings in `scenes.ts`.

---

## 5. Phasing

1. **Phase 1 — Bed.** Highest daily-value. Smallest blast radius.
2. **Phase 2 — All Off.** Defensive — clean exit.
3. **Phase 3 — Evening.** Subjective — needs 1-2 rounds of brightness/CT iteration.
4. **Phase 4 — Movie.** Entertainment-room dependent. Lowest frequency.

Each phase: implement YAML → reload `scripts.yaml` / `scenes.yaml` → fire from dev tools → tune → update `scenes.ts` entry → ship to PWA.

---

## 6. Implementation path matrix

| Scene | Recommended path | Entity type |
|---|---|---|
| All Off | B (script) | `script.ura_scene_all_off` |
| Evening | A (scene) | `scene.ura_scene_evening` |
| Movie | B (script) | `script.ura_scene_movie` |
| Bed | B (script) | `script.ura_scene_bed` |

---

## 7. Open questions for the user

1. **Bed → master nightlight:** Default proposed = 5% / 2200K. Confirm or override.
2. **Bed → which locks:** All discovered door locks, or a specific subset?
3. **Bed → house-mode shift:** Confirm yes (default proposal).
4. **Evening → room scope:** Confirm proposed IN/OUT list.
5. **Evening → brightness/CT:** Confirm proposed defaults per room.
6. **Movie → entertainment-room location:** Which room?
7. **Movie → kitchen/dining behavior:** Off entirely, or dim-but-on?
8. **Movie → motorized covers:** Close them, or leave alone?
9. **All Off → outdoor/security exceptions:** Confirm cameras + outdoor security lights are out-of-scope.

---

## 8. Out of scope

- "Movie End" reverse scene
- Time-of-day automation (auto-fire Evening at sunset)
- Per-zone scene variants
- URA service-handler implementation
- Voice activation
- Adaptive Lighting coordination

---

## 9. Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Phase 0 inventory skipped → entity_id fabrication | HIGH | Block Phase 1 dispatch until inventory file exists |
| Adaptive Lighting fights scenes | MED | Phase 0 flags AL-managed rooms; scene script calls `set_manual_control` |
| Lock unreachable during Bed | MED | `continue_on_error: true`; future: persistent notify on partial failure |
| Bed flips house mode → URA sleep-mode actuator collides with the lights the scene just set | MED | Sequence `select.select_option` LAST so URA's response is the final word |

---

## Appendix A — File touch list

| File | Change | Phase |
|---|---|---|
| `docs/planning/lifestyle_scenes_inventory.md` | NEW — Phase 0 output | 0 |
| `/config/scripts.yaml` | `ura_scene_bed` | 1 |
| `/config/scripts.yaml` | `ura_scene_all_off` | 2 |
| `/config/scenes.yaml` | `ura_scene_evening` | 3 |
| `/config/scripts.yaml` | `ura_scene_movie` | 4 |
| `~/Code/ura-dashboard-pwa/src/data/scenes.ts` | 4 entity_id strings | 1-4 (incremental) |
| `~/Code/ura-dashboard-pwa/src/components/SceneButtons.tsx` | DONE — domain inference shipped v6.0.1 | (already merged) |
