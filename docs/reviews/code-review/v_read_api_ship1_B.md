# Review B: person-awareness read API ship 1 (integration, cross-coordinator ripple, lifecycle)

Branch `feature/person-awareness-read-api-ship1`, HEAD 6b3b6891, base `git merge-base develop HEAD` = 376c1272 (verified, three-dot diff).
Read first, completely: `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md`, `SENSOR_FLEET_CLASSES.md`. No ledger claim re-asserted.

Identity model: RA1 consumes F2 (census house result), RA5 produces an F3 store (CrossingRecord) and consumes nothing; the RA3 table is read by a notification-class consumer (`_arrival_departure_notify`, 0.75) and a security-class consumer (perimeter D10.5, 0.9).

## Verdict: SHIP (no CRITICAL / HIGH / MEDIUM)

## Live-config proof (ground truth, not the doc)

Live integration entry (`/Users/okosisi/ha-config/.storage/core.config_entries`):
- `data.tracked_persons` = `['Ezinne', 'Oji Udezue', 'Jaya', 'Ziri']`
- `options.tracked_persons` = `['person.ezinne', 'person.oji_udezue', 'person.jaya', 'person.ziri']`

All four changed readers take `{**entry.data, **entry.options}` (options win): `camera_census.py:3906` (A), `:6172` (B), `:6330` (C), `perimeter_alert.py:5293` via `_get_integration_config` `:5617-5621` (D). They therefore see entity ids. For each live entry (and a whitespace-padded one) the old expression equals `person_ids.slug_of` / `tracked_person_entity_id` (checked by script). Old Residual C had no `.lower()`; HA entity ids are lowercase, so it is equal too.

Under the live config there is no change to the census identified set, house state, guest mode, perimeter severity or notifications.

## Forward trace per site

| Site | Downstream | Live change | Notes |
|---|---|---|---|
| A `_get_tracked_person_slugs` | sighting producer / egress BLE legs (per plan) | none | equal slugs |
| B `_get_wifi_guest_count` family list | `camera_census.py:6439` only; the docstring at `:6431-6434` and the formula exclude WiFi ("computed for diagnostics") | none | For a data-only install (display names, no options), family phones were counted as WiFi guests before (`hass.states.get('Oji Udezue')` → None → no family trackers). Now they are excluded. That is a fix, and the value only feeds diagnostics, so it cannot move guest mode |
| C `_get_face_recognized_person_names` | face-recognized feed → identified set | none | equal slugs |
| D perimeter `_tracked_person_slugs` | D10.5 known-person de-escalation | none | floor `max(0.9, KNOWN_MIN_CONF)` unchanged (`perimeter_alert.py:5188-5195`) |
| RA3 notify | `transit_validator.py:2683-2687` | none | 0.75 unchanged. The class attribute is kept, but the compare now reads the table. No production or test reader of the attribute (grep), so this is not a live split |

## CrossingRecord store (`transit_validator.py:1099-1119`, `:2257-2269`)
- Bounded: one overall slot plus one per egress camera (the dict is keyed by camera id), so size is bounded by the configured egress cameras. No growth.
- Restart: RAM only, so `None` until the first crossing. Every reader is `None`-safe, and there is no production reader (grep: only `presence.get_last_crossing`, itself uncalled).
- Thread/async: written and read on the event loop, sync, no await. No race.
- Bus payload: untouched (the diff adds no keys). The record copies the same locals the bus used.
- LOW-B1 (hardening, optional): `_record_crossing(CrossingRecord(...))` is not in try/except, and it sits BEFORE the notify, the census `register_egress_face` and the DB write. It cannot raise today: `egress_timestamp.isoformat()` and `resolution.provenance` were already evaluated by the bus fire just above, and a frozen dataclass does no validation. A future field could change that, though. Wrapping it in try/except keeps the "observational, never breaks the emit" contract explicit. Bug class: observational insert on the hot path.

## Import / startup
- `person_ids.py` has no HA or package imports, so it cannot form an import cycle. `person_coordinator` re-exports it at module level (`:130-138`), and existing `person_coordinator.tracked_person_entity_id` imports still resolve.
- `const.validate_consumer_classes` runs at import with active `{display}` ⊂ legal `{display, notification}`, so it cannot raise at HA startup as shipped. It raises only if a reviewer-gated rung-1 edit adds an illegal class. That is the intended fail-loud behaviour, and the tests pin it.
- `MappingProxyType` is read-only, so the doctrine cannot be mutated at runtime.

## view_for_class
`switch.ura_crossing_vision_census_authority` is referenced only at `const.py:6406`; no entity creates it. `hass.states.get` → None → `trust` for every class, including `display` (the only promoted class). Unknown, non-string or error inputs → `trust`. Today every class reads trust. No production caller of `view_for_class` / `get_house_census` (grep), so the presence inference path is untouched.

## Tests
`quality/tests/test_person_awareness_read_api.py`: 32 passed (targeted run only).

| Sev | Finding | Class | Fixed |
|---|---|---|---|
| LOW | B1 unguarded record insert before downstream consumers | observational insert on emit path | no (optional) |

Summary: 0 CRITICAL, 0 HIGH, 0 MEDIUM, 1 LOW. No new bug class for QUALITY_CONTEXT.
