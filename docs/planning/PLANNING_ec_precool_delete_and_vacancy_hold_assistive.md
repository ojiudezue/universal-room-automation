# PLANNING — EC pre_cool vestige delete + assistive room vacancy-hold UI

**Cards:** `EC-SOLAR-CLASS-DAYTIME-FORECAST-PROVENANCE-1` (D1) + folded UX ask (D2, new sub of `HVAC-DEMAND-KNOBS-AND-OBS-GAPS-1` lineage).
**Tier:** 2-DB (3 framing-disjoint reviews) — D1 touches EC decision logic (delete), D2 touches config-flow correctness for live rooms. **Combined cycle, one deploy** (disjoint files: energy.py vs config_flow.py + translations).

## Institutional context verified
- **D1 producer/consumer (done, this session):** `_hvac_constraint_mode = "pre_cool"` set ONLY at energy.py:7432 (sole emitter). No positive consumer — offset applied only under coast/shed (hvac.py:1922); Path A (`_should_energy_precool`, hvac_predict.py:686) decides independently and its docstring says it "replaces the v3.17.0 solar-banking branch." Only readers of a non-normal mode are predictor gates requiring `normal` (hvac_predict.py:719, :335) → pre_cool mode only ever BLOCKS Path A. Fan/cover controllers do NOT branch on pre_cool. Git blame: born v3.7/v3.9 phase-blind, June phase-fix (b53e6e97) skipped it, superseded by v5.7.1, never deleted.
- **D2 good-values source REUSED:** `ROOM_TYPE_HVAC_HOLD` (const.py:1203) + `ROOM_TYPE_HVAC_HOLD_NIGHT` (:1214) — per-type day/night hold defaults; `0 = never-hold` (hallway circulation exclusion); runtime clamp `night >= day` in `hvac_zones.py:_effective_hvac_hold_seconds`. Types present: bedroom, media_room, common_area, generic, closet, bathroom, garage, utility, infrastructure, hallway.
- **D2 control (current):** config_flow.py:11713-11736 — both fields `NumberSelector(min=0, max=7200, unit=s, mode=BOX)`, `suggested_value = self._get_current(...)`; NO help text, NO per-type default hint, NO "0=disabled" note. Field help text lives in `translations/en.json` + `strings.json` under `options→step→climate→data_description`.

## D1 — Delete the EC pre_cool vestige (branch), TOMBSTONE the constant, PRESERVE the principle
**Re-check (producer/consumer, thorough, 2026-09-18):** Path B's outputs are inert-except-harmful — offset stored in `_energy_offset` but applied to setpoints ONLY under coast/shed (hvac.py:1922; hvac.py:3211 is a log line, not application); `fan_assist=False` for pre_cool; `mode=="pre_cool"` consumed only by Path A's `!=normal` gates (blocks it). BUT Path B is a **distinct capability**, not a dup: Path A requires live **PV export** (hvac_predict.py:717), so it does NOT cover a **hot-forecast day with LOW morning SOC** (no surplus). Path B reached for that (anticipatory off-peak GRID pre-cool) but was phase-blind + inert.

- **Delete** the pre_cool `elif` branch (energy.py:7427-7434) → falls through to `else: normal`. Misleading 9pm label gone; Path A eligible (`mode==normal`) in its 10am-2pm window.
- **TOMBSTONE (KEEP+DOCUMENT), do NOT delete:** `CONF_ENERGY_CONSTRAINT_PRECOOL_OFFSET` + `DEFAULT_CONSTRAINT_PRECOOL_OFFSET` + the `self._constraint_precool_offset = ec.get(...)` read (energy.py:665-666). Add a retirement comment at the read pointing to card `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1`. Config key kept = a stored config entry doesn't strand (S14 tombstone pattern); comment preserves the principle in-code.
- **Principle preserved out-of-code:** parked card `EC-GRID-ANTICIPATORY-PRECOOL-GAP-1` (Path A surplus-only leaves low-SOC hot mornings uncovered; a phase-aware grid-anticipatory pre-cool reusing `summer_peak_ahead` is the future design axis; measure-first).

### Acceptance (D1)
- **Verify:** `sensor.ura_energy_coordinator_hvac_constraint` never reports `pre_cool` again (only normal/coast/shed/pre_heat).
- **Verify:** real afternoon banking still works — `pre_cool_active` (Path A) can go true in the 10am-2pm window on a PV-surplus day (this is the honest signal now).
- **Test:** a test that at off_peak+soc<50+good-solar the EC mode is `normal` (not pre_cool); and that Path A eligibility (`mode==normal`) holds in its window. Mutation: re-add the branch → test RED.
- **Live:** no URA ERROR; EC mode sensor shows normal in the evening off-peak instead of pre_cool.
- **Non-goal:** pre_heat branch untouched; Path A untouched.

## D2 — Assistive room vacancy-hold day/night fields
Make the two per-room fields self-explanatory while preserving free-entry override AND current room values.

- **Default/suggested:** when the field is UNSET for a room, suggest the room's **type default** from `ROOM_TYPE_HVAC_HOLD[type]` / `_NIGHT[type]` (not a flat blank/60) so the operator sees what "good" is for THIS room type. Do NOT overwrite an explicit existing value (keep `suggested_value = current if set else type_default`).
- **Control:** keep `NumberSelector` (free override preserved) but add a sensible `step` (e.g. 30s) and consider `mode=SLIDER` for the 0-7200 range; keep unit=s. (If a dropdown of named presets is preferred, use it — but free custom entry must remain; NumberSelector+guidance is the parsimonious choice.)
- **Text (translations `data_description`):** state plainly — **"0 = disabled (never hold; used for hallways/circulation). Typical: bedrooms ~1 min day / 30 min night; common areas ~1 / 15 min; closets/baths ~5-10 min night; hallways 0. Night must be ≥ day (auto-clamped)."** Keep it short + assistive.
- **Correctness invariants (maintain):** existing per-room configured values unchanged after deploy; the runtime fallback to `ROOM_TYPE_HVAC_HOLD` when unset still works; the night≥day clamp still applies; `0` still preserved as explicit never-hold (not blanked).

### Acceptance (D2)
- **Verify:** opening a room's climate step shows the two fields with the room-type default suggested (for an unset room) and the assistive help text incl. "0 = disabled" + per-type ranges.
- **Verify:** a room with an explicit value still shows that value (not overwritten); saving round-trips; `0` persists as 0.
- **Test:** unset room → suggested = type default; explicit value preserved; monotonicity clamp intact; translations JSON valid.
- **Live:** the current rooms' effective holds unchanged post-deploy (spot-check 2-3 room types via `_effective_hvac_hold_seconds` or the room's hold sensor).

## Review framings (Tier 2-DB, 3 disjoint)
- **A — D1 correctness:** branch removal complete, no orphaned refs (`_constraint_precool_offset`, reason string, tests), EC mode chain still valid (shed>coast>pre_heat>normal), no dangling `pre_cool`.
- **B — D1 integration + restart:** Path A now eligible (mode==normal) and still gated by PV-surplus+hour; no other consumer of pre_cool mode broke; EC constraint sensor + downstream (fans/covers) fine; restart.
- **C — D2 config correctness + UX:** existing room values preserved (no overwrite), suggested=type-default only when unset, `0` preserved, night≥day clamp intact, round-trip, translations valid + genuinely assistive; mutation on the suggested-default logic REDs a test.
