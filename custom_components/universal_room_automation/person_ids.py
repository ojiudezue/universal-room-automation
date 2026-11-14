"""One person-id rule (PERSON-AWARENESS-READ-API-1 RA4, INV-ID-ONE-RULE).

Every ``tracked_persons`` entry -> ``person.*`` entity id / URA slug /
display-name conversion goes through this module. ``tracked_persons`` can
hold display names (``'Oji Udezue'``, the config-flow ``entry.data`` form)
or entity ids (``'person.oji_udezue'``, the options-flow form); both must
give the same slug (``'oji_udezue'``).

Pure module: no Home Assistant imports, so the census, the sighting
producer, the egress tracker and the perimeter can import it without the
person coordinator's HA dependency chain.

The face first-name mapper is a different concept and stays in
``camera_census.PersonCensus.canonical_person_slug`` (it maps a Frigate
face-library first name onto a tracked slug).
"""

from __future__ import annotations

from typing import Any

PERSON_ENTITY_PREFIX = "person."


def tracked_person_entity_id(name: Any) -> str:
    """``person.*`` entity id for one ``tracked_persons`` entry.

    Same rule as ``PersonTrackingCoordinator._async_update_data``
    (``person.`` + name lowercased with spaces as ``_``): ``tracked_persons``
    holds display names on the live install (``'Oji Udezue'`` ->
    ``person.oji_udezue``). An entry that is already a ``person.*`` id is
    kept as is.
    """
    s = str(name)
    if s.startswith(PERSON_ENTITY_PREFIX):
        return s
    return f"{PERSON_ENTITY_PREFIX}{s.lower().replace(' ', '_')}"


def slug_of(entity_or_name: Any) -> str:
    """URA person slug (``'oji_udezue'``) for a display name or entity id.

    ``None`` / blank -> ``""``. Surrounding whitespace is ignored. The
    result is lowercase: for an entity-id entry it equals the historical
    ``str(p).replace('person.', '').strip().lower()``; for a display-name
    entry it equals the slug of ``tracked_person_entity_id``.
    """
    if entity_or_name is None:
        return ""
    s = str(entity_or_name).strip()
    if not s:
        return ""
    return tracked_person_entity_id(s)[len(PERSON_ENTITY_PREFIX):].strip().lower()


def display_of(slug: Any) -> str:
    """Display name for a slug (``'oji_udezue'`` -> ``'Oji Udezue'``).

    Same transform as the existing ``.replace('_', ' ').title()`` inverses
    (e.g. the arrival/departure notification name). Accepts an entity id.
    """
    s = slug_of(slug)
    return s.replace("_", " ").title()
