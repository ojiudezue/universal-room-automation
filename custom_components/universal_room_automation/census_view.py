"""F2 house census read view (PERSON-AWARENESS-READ-API-1 RA1 / RA7).

One read of ``hass.data[DOMAIN]["census"].last_result.house`` for every
reader outside the census. ``PresenceCoordinator.get_house_census`` is the
public API and delegates here; display entities call :func:`house_census_view`
directly so they do not depend on the presence coordinator being registered
yet (the old direct reads did not either, so the boot window is unchanged).

Pure module: no Home Assistant imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

_DOMAIN = "universal_room_automation"


@dataclass(frozen=True)
class HouseCensusView:
    """F2 house census as one consumer class reads it
    (PERSON-AWARENESS-READ-API-1 RA1). Built by
    ``house_census_view`` / ``PresenceCoordinator.get_house_census``; values
    are copied from ``census.last_result.house`` (never ``_census_count``).

    view: ``trust`` or ``awareness``.
    identified: house ``identified_count``.
    unidentified_or_guests: house ``unidentified_count``.
    total: house ``total_persons``.
    provenance: where the count came from (``camera`` until the census
        deconfliction plan adds vision).
    agreement: house ``source_agreement``.
    as_of: house ``timestamp``.
    confidence: house ``confidence`` (``high`` / ``medium`` / ``low`` /
        ``none``), copied verbatim (RA7: the zone guest-count attributes).
    """

    view: str
    identified: int
    unidentified_or_guests: int
    total: int
    provenance: str
    agreement: str
    as_of: Any
    confidence: Any = None


def house_census_view(hass: Any, view: str = "trust") -> HouseCensusView | None:
    """F2 house census for ``view`` (``trust`` / ``awareness``).

    Sync, never raises; no census, no result yet, no house, or any error ->
    None. Until the census deconfliction plan adds the awareness fields, the
    awareness view returns the trust values with provenance ``camera``. Any
    view string other than ``awareness`` reads trust.
    """
    try:
        census = hass.data.get(_DOMAIN, {}).get("census")
        if census is None:
            return None
        last = census.last_result
        if last is None:
            return None
        house = last.house
        if house is None:
            return None
        return HouseCensusView(
            view="awareness" if view == "awareness" else "trust",
            identified=int(house.identified_count),
            unidentified_or_guests=int(house.unidentified_count),
            total=int(house.total_persons),
            provenance="camera",
            agreement=str(house.source_agreement),
            as_of=house.timestamp,
            confidence=getattr(house, "confidence", None),
        )
    except Exception:  # noqa: BLE001 - read API never raises
        _LOGGER.debug("house_census_view failed", exc_info=True)
        return None
