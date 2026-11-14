"""Person profiles (arc step 8 D1; PLANNING_identity_actions_v6.md §5.1-§5.3).

One store: the Coordinator Manager entry option ``person_profiles``, keyed by
the ``person.*`` entity id from ``person_ids.tracked_person_entity_id`` (the
one person-id rule), so a display-name and an entity-id ``tracked_persons``
config address the same profile. Rooms are stored by room config entry_id.
Room owners are DERIVED from the profiles (``room_owners``), never stored.

Toggle-off semantics live here, in the readers: a dependent field is read
only while its toggle is on. On HA 2026.11 a hidden form field is dropped
from the submission; on older HA it is submitted. Either way the save merges
into the stored profile (``merge_profile_save``), so a stale value under an
off toggle is kept, is harmless, and comes back when the toggle is turned on.

Pure module: no Home Assistant imports. Callers pass the CM options dict.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from .const import (
    CONF_MUSIC_ON_ARRIVAL_START,
    CONF_PERSON_PROFILES,
    DEFAULT_MUSIC_ON_ARRIVAL_START,
    LIGHT_SLOT_DAY,
    LIGHT_SLOT_EVENING,
    PROFILE_AUTO_MUSIC,
    PROFILE_AUTO_SCENE,
    PROFILE_MUSIC_BY_ROOM,
    PROFILE_MUSIC_DAY,
    PROFILE_MUSIC_DEFAULT,
    PROFILE_MUSIC_EVENING,
    PROFILE_MUSIC_VARY_ROOM,
    PROFILE_MUSIC_VARY_TIME,
    PROFILE_MUSIC_VOLUME,
    PROFILE_MUSIC_VOLUME_DEFAULT,
    PROFILE_MUSIC_VOLUME_MAX,
    PROFILE_MUSIC_VOLUME_MIN,
    PROFILE_ROOMS_BATHROOM,
    PROFILE_ROOMS_BEDROOM,
    PROFILE_WELCOME_SCENE,
)
from .person_ids import slug_of, tracked_person_entity_id

# Keys a save may write. Anything else in a submission is ignored.
PROFILE_KEYS: frozenset[str] = frozenset({
    PROFILE_ROOMS_BEDROOM,
    PROFILE_ROOMS_BATHROOM,
    PROFILE_AUTO_MUSIC,
    PROFILE_AUTO_SCENE,
    PROFILE_MUSIC_DEFAULT,
    PROFILE_MUSIC_VOLUME,
    PROFILE_MUSIC_VARY_TIME,
    PROFILE_MUSIC_DAY,
    PROFILE_MUSIC_EVENING,
    PROFILE_MUSIC_VARY_ROOM,
    PROFILE_MUSIC_BY_ROOM,
    PROFILE_WELCOME_SCENE,
})
MEDIA_PICK_KEYS: tuple[str, ...] = (
    PROFILE_MUSIC_DEFAULT, PROFILE_MUSIC_DAY, PROFILE_MUSIC_EVENING,
)


# ---------------------------------------------------------------------------
# Master + store reads
# ---------------------------------------------------------------------------

def arrival_master_on(options: Mapping[str, Any] | None) -> bool:
    """House master for arrival actions. Unset reads ON (day 1, §5.1)."""
    opts = options or {}
    return bool(opts.get(CONF_MUSIC_ON_ARRIVAL_START, DEFAULT_MUSIC_ON_ARRIVAL_START))


def profiles_from_options(options: Mapping[str, Any] | None) -> dict[str, dict]:
    """Every stored profile, keyed by ``person.*`` id. Malformed rows drop."""
    raw = (options or {}).get(CONF_PERSON_PROFILES) or {}
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, dict] = {}
    for key, prof in raw.items():
        if isinstance(prof, Mapping):
            out[tracked_person_entity_id(key)] = dict(prof)
    return out


def get_person_profile(options: Mapping[str, Any] | None, person: Any) -> dict | None:
    """The profile for one tracked person (display name or entity id)."""
    if person is None or not str(person).strip():
        return None
    return profiles_from_options(options).get(tracked_person_entity_id(str(person).strip()))


def _str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [str(v) for v in value if v]
    return []


def own_rooms(profile: Mapping[str, Any] | None) -> set[str]:
    """"My rooms" = bedrooms ∪ bathrooms (room entry_ids)."""
    if not profile:
        return set()
    return set(_str_list(profile.get(PROFILE_ROOMS_BEDROOM))) | set(
        _str_list(profile.get(PROFILE_ROOMS_BATHROOM))
    )


def room_owners(profiles: Mapping[str, Mapping[str, Any]], room_entry_id: str) -> set[str]:
    """Owners of a room, derived: every person whose rooms include it."""
    return {p for p, prof in (profiles or {}).items() if room_entry_id in own_rooms(prof)}


def room_entry_id_for_name(
    name_to_entry_id: Mapping[str, str], room_name: Any,
) -> str | None:
    """Map the layer's room NAME to a room entry_id.

    The person layer reports a room name (``person_coordinator``
    ``resolved_room``); the map is built from URA's OWN room entries'
    ``room_name`` (the one allowed string match). An unmapped name, or a
    non-room location (``unknown`` / ``away`` / blank), never matches.
    """
    if room_name is None:
        return None
    key = str(room_name).strip()
    if not key or key.lower() in ("unknown", "unavailable", "away", "home", "not_home"):
        return None
    return name_to_entry_id.get(key)


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

def media_valid(media: Any) -> bool:
    """A pick is usable only with a non-blank content id AND type."""
    return (
        isinstance(media, Mapping)
        and isinstance(media.get("media_content_id"), str)
        and bool(media.get("media_content_id").strip())
        and isinstance(media.get("media_content_type"), str)
        and bool(media.get("media_content_type").strip())
    )


def normalize_media(media: Any) -> dict | None:
    """Stored shape of a pick: ``media_content_id`` + ``media_content_type``,
    plus the player the person browsed (``entity_id``) when the form sent one.

    The browse player is kept ONLY so the form can re-show the pick: HA's
    MediaSelector without ``accept`` rejects a value with no ``entity_id``
    (helpers/selector.py MediaSelector.__call__, 2026.2.3), so an unchanged
    re-save would fail. Playback never reads it (``play_pick`` drops it).
    """
    if not media_valid(media):
        return None
    out = {
        "media_content_id": media["media_content_id"].strip(),
        "media_content_type": media["media_content_type"].strip(),
    }
    eid = media.get("entity_id")
    if isinstance(eid, str) and "." in eid:
        out["entity_id"] = eid
    return out


def play_pick(media: Any) -> dict | None:
    """What playback uses: id + type only (the browse player is dropped)."""
    norm = normalize_media(media)
    if norm is None:
        return None
    return {"media_content_id": norm["media_content_id"],
            "media_content_type": norm["media_content_type"]}


def pick_media(profile: Mapping[str, Any] | None, room_entry_id: str, slot: str) -> dict | None:
    """Choose the music for one arrival (§5.3), or None.

    ``slot`` is the TARGET room's own ``lighting.resolver.resolve_slot(...)``
    value, so music and the room's lighting scenes agree on "evening".
    Precedence: (1) ``music_by_room[room]`` when "Different music per room"
    is on and the room is one of the person's rooms; (2) ``music_day`` /
    ``music_evening`` for the slot when "Different music by time of day" is
    on; (3) ``music_default``. Each step needs a usable pick, else it falls
    through. ``auto_music`` off, or the ``sleep`` slot (the quiet gate never
    plays in it), gives None.
    """
    if not profile or not profile.get(PROFILE_AUTO_MUSIC):
        return None
    if slot not in (LIGHT_SLOT_DAY, LIGHT_SLOT_EVENING):
        return None
    if profile.get(PROFILE_MUSIC_VARY_ROOM) and room_entry_id in own_rooms(profile):
        by_room = profile.get(PROFILE_MUSIC_BY_ROOM)
        if isinstance(by_room, Mapping):
            pick = play_pick(by_room.get(room_entry_id))
            if pick:
                return pick
    if profile.get(PROFILE_MUSIC_VARY_TIME):
        key = PROFILE_MUSIC_EVENING if slot == LIGHT_SLOT_EVENING else PROFILE_MUSIC_DAY
        pick = play_pick(profile.get(key))
        if pick:
            return pick
    return play_pick(profile.get(PROFILE_MUSIC_DEFAULT))


def music_volume(profile: Mapping[str, Any] | None) -> float:
    """The person's volume, bounded to the form's range."""
    try:
        vol = float((profile or {}).get(PROFILE_MUSIC_VOLUME, PROFILE_MUSIC_VOLUME_DEFAULT))
    except (TypeError, ValueError):
        vol = PROFILE_MUSIC_VOLUME_DEFAULT
    return min(PROFILE_MUSIC_VOLUME_MAX, max(PROFILE_MUSIC_VOLUME_MIN, vol))


# ---------------------------------------------------------------------------
# Save path (People step)
# ---------------------------------------------------------------------------

def merge_profile_save(stored: Mapping[str, Any] | None, submitted: Mapping[str, Any]) -> dict:
    """Merge one form submission into the stored profile.

    Keys absent from ``submitted`` (a field HA 2026.11 hid and dropped) keep
    their stored value. Media picks are normalized; a blank pick clears it.
    Unknown keys are ignored.
    """
    out = dict(stored or {})
    for key, value in (submitted or {}).items():
        if key not in PROFILE_KEYS:
            continue
        if key in MEDIA_PICK_KEYS:
            norm = normalize_media(value)
            if norm is None:
                out.pop(key, None)
            else:
                out[key] = norm
        elif key in (PROFILE_ROOMS_BEDROOM, PROFILE_ROOMS_BATHROOM):
            out[key] = sorted(set(_str_list(value)))
        elif key == PROFILE_MUSIC_BY_ROOM:
            out[key] = {
                str(rid): norm for rid, m in (value or {}).items()
                if (norm := normalize_media(m)) is not None
            } if isinstance(value, Mapping) else {}
        elif key == PROFILE_MUSIC_VOLUME:
            out[key] = music_volume({PROFILE_MUSIC_VOLUME: value})
        elif key == PROFILE_WELCOME_SCENE:
            if isinstance(value, str) and value.startswith("scene."):
                out[key] = value
            else:
                out.pop(key, None)
        else:
            out[key] = bool(value)
    return out


def validate_profile(profile: Mapping[str, Any]) -> str | None:
    """Form error key for a profile that cannot act, else None.

    "Play my music" on with no usable default pick would end every arrival
    in ``skipped_no_media`` (review 3.1 L2): refuse it at save. The welcome
    scene on with no scene picked is refused the same way.
    """
    if profile.get(PROFILE_AUTO_MUSIC) and not media_valid(profile.get(PROFILE_MUSIC_DEFAULT)):
        return "people_music_needs_pick"
    if profile.get(PROFILE_AUTO_SCENE) and not profile.get(PROFILE_WELCOME_SCENE):
        return "people_scene_needs_pick"
    return None


def automated_action_count(profile: Mapping[str, Any] | None) -> int:
    """Number of entry actions the person automated (profile sensor state)."""
    if not profile:
        return 0
    return int(bool(profile.get(PROFILE_AUTO_MUSIC))) + int(bool(profile.get(PROFILE_AUTO_SCENE)))


# ---------------------------------------------------------------------------
# Suggestions (display only; never stored)
# ---------------------------------------------------------------------------

def _parse_naive(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def suggest_rooms(
    visits: Iterable[tuple[Any, Any, Any, Any]],
    person: Any,
    top_n: int,
) -> list[tuple[str, int]]:
    """Room names by share of the person's closed visit time, highest first.

    ``visits`` are ``Database.get_closed_person_visits`` rows
    ``(person_id, room_id, entry_time, exit_time)``; ``person_id`` is matched
    by the one slug rule, so a display-name or entity-id row both count.
    Returns ``[(room_name, percent), ...]`` (whole percent, at most ``top_n``).
    """
    want = slug_of(person)
    if not want or top_n <= 0:
        return []
    totals: dict[str, float] = {}
    for row in visits or ():
        try:
            pid, room, t_in, t_out = row
        except (TypeError, ValueError):
            continue
        if slug_of(pid) != want or not room:
            continue
        a, b = _parse_naive(t_in), _parse_naive(t_out)
        if a is None or b is None or b <= a:
            continue
        totals[str(room)] = totals.get(str(room), 0.0) + (b - a).total_seconds()
    grand = sum(totals.values())
    if grand <= 0:
        return []
    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [(room, int(round(100.0 * secs / grand))) for room, secs in ranked]


def suggestion_window(now_naive: datetime, lookback_days: int) -> tuple[str, str]:
    """``[since, until)`` bounds for the person_visits read, in the writer's
    clock (naive PROCESS-local, presence state of play §10 #32)."""
    since = now_naive - timedelta(days=max(0, int(lookback_days)))
    return str(since), str(now_naive)
