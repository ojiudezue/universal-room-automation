# BACKLOG — Part 2 D4 split-out: per-zone kWh-rate threshold persistence

**Status:** Split out of Part 2 (EC + HVAC options-writeback retrofit). NOT shipped.
**Tier:** Tier 2 (introduces a new per-zone CONF family — institutional-context pass + 2 reviewers).
**Filed:** 2026-06-06 during Part 2 build pass (per `PLANNING_part2_ec_hc_options_writeback_retrofit.md` deferral list).

## Why split out

Part 2's `D4` originally proposed retrofitting `_HVACZoneKwhThresholdNumber`
(factory at `number.py:1972-2096`) to drop RestoreEntity + add writeback +
add to `OPTIONS_RELOAD_SUPPRESS_KEYS`. Build-pass verification confirmed:

1. **No per-zone CONF exists in `entry.options` today.** The constant
   `CONF_HVAC_AC_KWH_RATE_THRESHOLD` at `hvac_const.py:209` is a DEFAULT
   seed value, not a per-zone option key. The factory at `number.py:2006`
   seeds `self._value = float(DEFAULT_HVAC_AC_KWH_RATE_THRESHOLD)` — NOT
   from `entry.options`.
2. **Persistence today is RestoreEntity-only.** Slider drags survive
   restart via the recorder's last-state restore (`number.py:2053-2063`).
   The push target is `ZoneState.kwh_rate_threshold` (per-zone, on the
   in-memory `ZoneState` object — `hvac_zones.py:124`), not entry.options.

Retrofitting this in Part 2 would require **introducing a new per-zone
CONF family** (e.g. `CONF_HVAC_AC_KWH_RATE_THRESHOLD_<zone_id>` or a
dict-shaped per-zone CONF). That is itself a substantive design decision
(parsimonious-config doctrine + new institutional-context pass) that
deserves its own scoped cycle. Per operator instruction (O2 in the Part 2
plan): **split out; do not invent new CONFs in Part 2.**

## Scope (when this cycle is picked up)

- Decide on the CONF shape: per-zone keys vs. one dict-shaped key vs.
  a dedicated per-zone entry sub-table. (Recommend: dict-shaped key
  `CONF_HVAC_AC_KWH_RATE_THRESHOLDS` mapping `zone_id -> float`, to avoid
  CONF proliferation as zones are added.)
- Implement the factory retrofit: drop RestoreEntity + seed from
  `entry.options.get(CONF_HVAC_AC_KWH_RATE_THRESHOLDS, {}).get(zone_id, DEFAULT)`
  + add `async_update_entry` writeback in the setter.
- Add the new CONF to `OPTIONS_RELOAD_SUPPRESS_KEYS` (single key for the
  whole dict).
- Add a dispatch branch in `_apply_in_place` that iterates the new dict
  and pushes each zone's value to `ZoneState.kwh_rate_threshold`.
- Migration helper (if any prior installs already had per-zone slider
  values stored via RestoreEntity): on first boot after the new CONF
  lands, walk existing recorder values and seed them into
  `entry.options` so they aren't lost on the doctrine flip.

## Acceptance criteria (when this cycle ships)

- `_HVACZoneKwhThresholdNumber` no longer inherits from RestoreEntity.
- Setter calls `async_update_entry` with the new CONF.
- New CONF in `OPTIONS_RELOAD_SUPPRESS_KEYS`.
- `_apply_in_place` dispatches per-zone updates.
- Restart-restore: edit a zone threshold → restart → entity reads edited value.
- Live: edit one zone's threshold → no full CM reload → other zones' Numbers'
  `last_changed` does NOT advance.

## Why this is not a blocker for Part 2 deploy

- The per-zone slider's CURRENT behavior is unchanged (RestoreEntity + slider
  push to `ZoneState.kwh_rate_threshold`). The wider Part 2 cycle ships with
  this one factory keeping the legacy pattern, which is fine because the
  consumer (`OverrideArrester` at `hvac_override.py:1034`) reads the
  in-memory ZoneState attr directly — no entry.options dependency.
- The `test_no_restoreentity_left_in_number_py_except_d4_split_out` test
  in `quality/tests/test_part2_ec_hc_writeback.py` explicitly allowlists
  `_HVACZoneKwhThresholdNumber` as the lone permitted leftover, so a
  future code change that accidentally drops the RestoreEntity here
  without filing the per-zone CONF will surface in CI.
