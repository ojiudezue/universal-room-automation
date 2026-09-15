"""Appliance Coordinator constants (v1a — APPLIANCE-MGMT-REFINE-1).

Home for the freshness knob + per-appliance record schema constants. Rung 1
(module-constant) knobs — review-gated, NOT operator-tuned. Model:
``energy_circuits.py:20-44``.

Reuse discipline: intra-integration shadow de-dup relies on ``device_id``
grouping (pattern: ``camera_census.py:589-628``). Cross-integration bridging
is operator-declared only via ``CONF_APPLIANCE_RECORDS`` — the plan's
adjudicated fragile-pattern rule (§ "Fragile patterns — DO NOT use", #2).
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Rung-1 knob: freshness horizon for a per-appliance signal.
# ---------------------------------------------------------------------------
# A signal older than this is treated as STALE by the census reader (still
# reported, but the record's ``freshness`` field is flagged). Value chosen
# on the same order as the SPAN circuit-monitor knobs it lives next to
# (see energy_circuits.py:20-44) — appliance state (media_player, climate)
# updates on the order of seconds-to-a-few-minutes; power sensors on the
# order of 10-60s.
#
# KILL VALUE: setting this to 0 disables freshness reporting entirely
# (every record reported as fresh). Not a safety-critical knob — v1a is
# read-only — but flipping it to 0 makes the freshness column meaningless.
APPLIANCE_STALE_MAX_AGE_S: Final[int] = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Per-appliance record schema (defined + read here in v1a; the flow WRITER
# lands in v1b).
# ---------------------------------------------------------------------------
# Top-level keys.
KEY_NAME: Final[str] = "name"
KEY_FUNCTIONAL_DOMAIN: Final[str] = "functional_domain"
KEY_ROOM: Final[str] = "room"
KEY_ENTITY_REFS: Final[str] = "entity_refs"
KEY_SOURCE_TAGS: Final[str] = "source_tags"

# entity_refs sub-keys (roles). Any role list may be empty — a TV is
# state+control, a warming drawer is power-only, a smart plug is
# power+control, and so on.
ROLE_POWER: Final[str] = "power"
ROLE_ENERGY: Final[str] = "energy"
ROLE_CONTROL: Final[str] = "control"
ROLE_STATE: Final[str] = "state"

ROLES: Final[tuple[str, ...]] = (ROLE_POWER, ROLE_ENERGY, ROLE_CONTROL, ROLE_STATE)

# functional_domain enumeration (used by the flow validator in v1b; v1a
# reads and passes through).
DOMAIN_MEDIA_AV: Final[str] = "media_av"
DOMAIN_KITCHEN: Final[str] = "kitchen"
DOMAIN_LAUNDRY: Final[str] = "laundry"
DOMAIN_CLIMATE: Final[str] = "climate"
DOMAIN_COLD_CHAIN: Final[str] = "cold_chain"
DOMAIN_WATER: Final[str] = "water"
DOMAIN_CLEANING: Final[str] = "cleaning"
DOMAIN_OTHER: Final[str] = "other"

FUNCTIONAL_DOMAINS: Final[tuple[str, ...]] = (
    DOMAIN_MEDIA_AV,
    DOMAIN_KITCHEN,
    DOMAIN_LAUNDRY,
    DOMAIN_CLIMATE,
    DOMAIN_COLD_CHAIN,
    DOMAIN_WATER,
    DOMAIN_CLEANING,
    DOMAIN_OTHER,
)

# source_tags enumeration.
TAG_SPAN: Final[str] = "span"
TAG_EMPORIA: Final[str] = "emporia"
TAG_THINQ: Final[str] = "thinq"
TAG_SMARTPLUG: Final[str] = "smartplug"
TAG_NATIVE: Final[str] = "native"
TAG_URA_CONFIG: Final[str] = "ura_config"

SOURCE_TAGS: Final[tuple[str, ...]] = (
    TAG_SPAN,
    TAG_EMPORIA,
    TAG_THINQ,
    TAG_SMARTPLUG,
    TAG_NATIVE,
    TAG_URA_CONFIG,
)


# The URA-room keys the census reads to surface URA-owned entities. A
# subset of room-config keys (const.py) intersected with the appliance
# domain (fans, humidity fans, power sensors, room climate, room media,
# lights, covers). URA-owned entities are shown with source_tags=[ura_config]
# and require NO onboarding step.
URA_ROOM_APPLIANCE_KEYS: Final[tuple[str, ...]] = (
    "fans",
    "humidity_fans",
    "power_sensors",
    "climate_entity",
    "room_media_player",
    "lights",
    "covers",
)

# Room-key -> functional_domain default (only used when the entity has no
# declared record — declared records always win). "other" is the
# non-claim / uncategorized bucket.
URA_ROOM_KEY_TO_DOMAIN: Final[dict[str, str]] = {
    "climate_entity": DOMAIN_CLIMATE,
    "room_media_player": DOMAIN_MEDIA_AV,
    "fans": DOMAIN_OTHER,
    "humidity_fans": DOMAIN_OTHER,
    "power_sensors": DOMAIN_OTHER,
    "lights": DOMAIN_OTHER,
    "covers": DOMAIN_OTHER,
}
