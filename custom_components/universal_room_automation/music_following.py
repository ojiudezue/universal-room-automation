"""Music following for Universal Room Automation v3.3.5.5.

Seamlessly transfer music playback when person moves between rooms.

v3.3.5.2: WiiM-to-WiiM synchronized multiroom fix
          - WiiM integration DOES support media_player.join for synchronized playback
          - Changed WiiM-to-WiiM from wiim.play_url to media_player.join
          - Added PLATFORM_WIIM to MULTIROOM_PLATFORMS set
          - Unified same-platform transfers into _transfer_same_platform_join()
          - Cross-platform transfers remain independent (different protocols)
v3.3.5.1: Cross-platform transfer improvements
          - Added PLATFORM_DENON for Denon/Marantz AVR detection
          - Added PLATFORM_MASS for Music Assistant player detection
          - Improved cross-platform transfer logging (source→target platforms)
          - Generic transfer now logs platform mismatch reason
          - Entity registry remains primary detection method
v3.3.5: BUG-008a FIX - Entity registry platform detection
        - Use entity registry to detect actual integration (linkplay vs wiim vs sonos)
        - Added PLATFORM_WIIM for WiiM custom integration entities
        - Fixed misdetection: WiiM entities no longer treated as Linkplay
        - Attribute-based detection as fallback only
v3.3.4: BUG-008 FIX - Platform-agnostic music transfer
        - Added _get_player_platform() for Sonos/Linkplay/generic detection
        - Fixed Sonos join only used when BOTH players are Sonos
        - Added Linkplay (WiiM) multiroom support via native integration
        - Added comprehensive INFO-level logging for diagnostics
        - Generic play_media fallback for mixed/unknown platforms
v3.3.2: Added zone config lookup from zone entries (now that zone OptionsFlow works).
v3.3.1: Added explicit room_media_player and zone_player_entity config support.
v3.3.1: Fixed _get_room_entries to properly merge entry.options over entry.data.
"""

import logging
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.components.media_player import (
    ATTR_MEDIA_POSITION,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_VOLUME_SET,
)
from homeassistant.const import (
    STATE_PLAYING,
    STATE_PAUSED,
)

from .transitions import RoomTransition

_LOGGER = logging.getLogger(__name__)

# Platform identifiers
PLATFORM_SONOS = "sonos"
PLATFORM_LINKPLAY = "linkplay"  # Linkplay integration entities
PLATFORM_WIIM = "wiim"  # WiiM custom integration entities
PLATFORM_DENON = "denonavr"  # Denon/Marantz AVR integration
PLATFORM_MASS = "music_assistant"  # Music Assistant players
PLATFORM_GENERIC = "generic"

# Platforms that support native multiroom sync via media_player.join
# v3.3.5.2: Added PLATFORM_WIIM - WiiM integration DOES support join
# v3.3.5.2: Added PLATFORM_DENON - HEOS integration supports join for Denon/Marantz
MULTIROOM_PLATFORMS = {PLATFORM_SONOS, PLATFORM_LINKPLAY, PLATFORM_WIIM, PLATFORM_DENON}


class MusicFollowing:
    """Seamless music following between rooms.
    
    Features:
    - Transfer playback on room transition
    - Maintain playback position
    - Preserve volume settings
    - Fade out source room
    - Platform-aware transfer (Sonos, Linkplay, WiiM, Denon, generic)
    - Graceful fallback handling
    - Zone-level media player configuration (v3.3.2)
    
    v3.3.5.2: Updated Platform Transfer Matrix
    
    Same-platform transfers use media_player.join for synchronized multiroom:
    ┌─────────────┬─────────────┬─────────────┬─────────────┬─────────────┐
    │ Source →    │ Sonos       │ Linkplay    │ WiiM        │ HEOS/Denon  │
    │ Target ↓    │             │             │             │             │
    ├─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤
    │ Sonos       │ join(SYNC)  │ play_media  │ play_media  │ play_media  │
    │ Linkplay    │ play_media  │ join(SYNC)  │ play_media  │ play_media  │
    │ WiiM        │ play_media  │ play_media  │ join(SYNC)  │ play_media  │
    │ HEOS/Denon  │ play_media  │ play_media  │ play_media  │ join(SYNC)  │
    └─────────────┴─────────────┴─────────────┴─────────────┴─────────────┘
    
    Cross-platform transfers use play_media (independent playback) because
    each platform uses incompatible hardware-level multiroom protocols:
    - Sonos: SonosNet / WiFi Direct
    - WiiM/Linkplay: LinkPlay multiroom protocol
    - Denon/Marantz: HEOS protocol
    """
    
    # Configuration
    FADE_OUT_VOLUME = 0.1  # Fade source to 10%
    TRANSFER_DELAY_MS = 500  # Wait before starting target
    MIN_CONFIDENCE = 0.6  # Minimum transition confidence to trigger
    
    def __init__(
        self,
        hass: HomeAssistant,
        config: dict,
        transition_detector
    ) -> None:
        """Initialize music following."""
        self.hass = hass
        self.config = config
        self.transition_detector = transition_detector
        
        # Track which person we're following music for
        self._enabled_persons: set[str] = set()
        
        _LOGGER.info("MusicFollowing v3.3.5.5 initialized")
    
    async def async_init(self) -> None:
        """Initialize music following and subscribe to transitions."""
        # Subscribe to transition events
        self.transition_detector.async_add_listener(self._on_person_transition)
        
        _LOGGER.info(
            "MusicFollowing ready: confidence_threshold=%.2f, fade_volume=%.2f",
            self.MIN_CONFIDENCE, self.FADE_OUT_VOLUME
        )
    
    def enable_for_person(self, person_id: str) -> None:
        """Enable music following for specific person."""
        self._enabled_persons.add(person_id)
        _LOGGER.info("Music following enabled for: %s", person_id)
    
    def disable_for_person(self, person_id: str) -> None:
        """Disable music following for specific person."""
        self._enabled_persons.discard(person_id)
        _LOGGER.info("Music following disabled for: %s", person_id)
    
    async def _on_person_transition(self, transition: RoomTransition) -> None:
        """Handle person transition - transfer music if appropriate."""
        person_id = transition.person_id
        from_room = transition.from_room
        to_room = transition.to_room
        confidence = transition.confidence

        if from_room == to_room:
            _LOGGER.debug("🎵 Ignoring same-room transition: %s in %s", person_id, from_room)
            return

        _LOGGER.info(
            "🎵 Transition detected: %s moving %s → %s (confidence=%.2f)",
            person_id, from_room, to_room, confidence
        )
        
        # Skip if not enabled for this person
        if person_id not in self._enabled_persons:
            _LOGGER.info(
                "🎵 Music transfer skipped: %s not in enabled_persons=%s",
                person_id, list(self._enabled_persons)
            )
            return
        
        # Skip low-confidence transitions
        if confidence < self.MIN_CONFIDENCE:
            _LOGGER.info(
                "🎵 Music transfer skipped: low confidence %.2f < %.2f threshold",
                confidence, self.MIN_CONFIDENCE
            )
            return
        
        # Get media player entities for rooms
        from_player = await self._get_room_player(from_room)
        to_player = await self._get_room_player(to_room)
        
        if not from_player:
            _LOGGER.info(
                "🎵 Music transfer skipped: no player found for source room '%s'",
                from_room
            )
            return
        
        if not to_player:
            _LOGGER.info(
                "🎵 Music transfer skipped: no player found for target room '%s'",
                to_room
            )
            return
        
        _LOGGER.info("🎵 Players found: %s → %s", from_player, to_player)
        
        # Check if source is playing
        from_state = self.hass.states.get(from_player)
        if not from_state:
            _LOGGER.info(
                "🎵 Music transfer skipped: source player '%s' state unavailable",
                from_player
            )
            return
            
        if from_state.state != STATE_PLAYING:
            _LOGGER.info(
                "🎵 Music transfer skipped: source '%s' not playing (state=%s)",
                from_player, from_state.state
            )
            return
        
        # Get platform info for logging
        source_platform = self._get_player_platform(from_player)
        target_platform = self._get_player_platform(to_player)
        
        _LOGGER.info(
            "🎵 Starting transfer: %s (%s) → %s (%s) for %s",
            from_player, source_platform, to_player, target_platform, person_id
        )
        
        # Transfer playback
        success = await self._transfer_media(from_player, to_player, from_state)
        
        if success:
            _LOGGER.info(
                "🎵 ✓ Music transfer complete: %s %s → %s",
                person_id, from_room, to_room
            )
        else:
            _LOGGER.warning(
                "🎵 ✗ Music transfer failed: %s %s → %s",
                person_id, from_room, to_room
            )
    
    def _get_player_platform(self, entity_id: str) -> str:
        """Detect the platform/integration for a media player.
        
        Returns: 'sonos', 'linkplay', 'wiim', 'denonavr', 'music_assistant', or 'generic'
        """
        # Strategy 1: Entity registry lookup (most accurate)
        try:
            from homeassistant.helpers import entity_registry
            ent_reg = entity_registry.async_get(self.hass)
            entry = ent_reg.async_get(entity_id)
            
            if entry and entry.platform:
                platform = entry.platform.lower()
                
                platform_map = {
                    "sonos": PLATFORM_SONOS,
                    "linkplay": PLATFORM_LINKPLAY,
                    "wiim": PLATFORM_WIIM,
                    "denonavr": PLATFORM_DENON,
                    "music_assistant": PLATFORM_MASS,
                    "denon": PLATFORM_DENON,
                    "marantz": PLATFORM_DENON,
                }
                
                if platform in platform_map:
                    detected = platform_map[platform]
                    _LOGGER.debug(
                        "Platform detection: %s is %s (entity registry: %s)", 
                        entity_id, detected, platform
                    )
                    return detected
                
                _LOGGER.debug(
                    "Platform detection: %s has platform '%s' in registry (treating as generic)", 
                    entity_id, platform
                )
                return PLATFORM_GENERIC
                
        except Exception as e:
            _LOGGER.debug("Entity registry lookup failed for %s: %s", entity_id, e)
        
        # Strategy 2: Entity ID pattern matching (fallback)
        entity_id_lower = entity_id.lower()
        
        if "sonos" in entity_id_lower:
            _LOGGER.debug("Platform detection: %s is Sonos (entity_id match)", entity_id)
            return PLATFORM_SONOS
        
        if "denon" in entity_id_lower or "marantz" in entity_id_lower:
            _LOGGER.debug("Platform detection: %s is Denon/Marantz (entity_id match)", entity_id)
            return PLATFORM_DENON
        
        # Strategy 3: Attribute-based detection (last resort)
        state = self.hass.states.get(entity_id)
        if not state:
            _LOGGER.debug("Platform detection: %s has no state, returning generic", entity_id)
            return PLATFORM_GENERIC
        
        attrs = state.attributes
        firmware = attrs.get("firmware_version", "")
        if firmware and "linkplay" in firmware.lower():
            _LOGGER.debug(
                "Platform detection: %s likely Linkplay (firmware=%s) - use entity registry for certainty", 
                entity_id, firmware
            )
            return PLATFORM_GENERIC
        
        _LOGGER.debug("Platform detection: %s is generic (no match found)", entity_id)
        return PLATFORM_GENERIC
    
    async def _get_room_player(self, room_name: str) -> Optional[str]:
        """Get media player entity for room."""
        _LOGGER.debug("Looking for media player in room '%s'", room_name)
        
        room_name_lower = room_name.lower().replace(' ', '_')
        
        # Strategy 1: Check room config for explicit room_media_player
        room_entries = self._get_room_entries()
        room_zone = None
        
        for entry_id, entry_data in room_entries.items():
            entry_room = entry_data.get("room_name", "").lower().replace(' ', '_')
            if entry_room == room_name_lower:
                media_player = entry_data.get("room_media_player")
                if media_player:
                    state = self.hass.states.get(media_player)
                    if state:
                        _LOGGER.info(
                            "Room '%s': Found player via room_media_player config: %s",
                            room_name, media_player
                        )
                        return media_player
                    else:
                        _LOGGER.warning(
                            "Room '%s': Configured room_media_player '%s' not found in HA",
                            room_name, media_player
                        )
                room_zone = entry_data.get("zone")
                break
        
        # Strategy 2: Check zone config for zone_player_entity
        if room_zone:
            zone_player, zone_mode = self._get_zone_player_config(room_zone)
            if zone_player:
                state = self.hass.states.get(zone_player)
                if state:
                    _LOGGER.info(
                        "Room '%s': Found player via zone '%s' config: %s (mode=%s)",
                        room_name, room_zone, zone_player, zone_mode
                    )
                    return zone_player
                else:
                    _LOGGER.warning(
                        "Room '%s': Zone '%s' player '%s' not found in HA",
                        room_name, room_zone, zone_player
                    )
        
        # Strategy 3: HA Area lookup
        try:
            from homeassistant.helpers import area_registry, entity_registry
            
            area_reg = area_registry.async_get(self.hass)
            entity_reg = entity_registry.async_get(self.hass)
            
            matching_area = None
            for area in area_reg.async_list_areas():
                if area.name.lower().replace(' ', '_') == room_name_lower:
                    matching_area = area
                    break
            
            if matching_area:
                area_players = []
                for entity in entity_reg.entities.values():
                    if (entity.area_id == matching_area.id and 
                        entity.domain == "media_player" and
                        not entity.disabled):
                        area_players.append(entity.entity_id)
                
                if area_players:
                    sonos_players = [p for p in area_players if "sonos" in p.lower()]
                    if sonos_players:
                        player = sonos_players[0]
                        _LOGGER.info(
                            "Room '%s': Found Sonos player via HA Area '%s': %s (of %d players)",
                            room_name, matching_area.name, player, len(area_players)
                        )
                        return player
                    
                    player = area_players[0]
                    _LOGGER.info(
                        "Room '%s': Found player via HA Area '%s': %s (of %d players)",
                        room_name, matching_area.name, player, len(area_players)
                    )
                    if len(area_players) > 1:
                        _LOGGER.info(
                            "Room '%s' has %d media players in area. Using '%s'. "
                            "Configure room_media_player for explicit control. Others: %s",
                            room_name, len(area_players), player, area_players[1:]
                        )
                    return player
                else:
                    _LOGGER.debug(
                        "Room '%s': HA Area '%s' found but has no media_player entities",
                        room_name, matching_area.name
                    )
            else:
                _LOGGER.debug("Room '%s': No matching HA Area found", room_name)
        except Exception as e:
            _LOGGER.debug("Room '%s': HA Area lookup failed: %s", room_name, e)
        
        # Strategy 4: Naming convention fallback
        room_entity = f"media_player.{room_name_lower}"
        state = self.hass.states.get(room_entity)
        if state:
            _LOGGER.info(
                "Room '%s': Found player via naming convention: %s",
                room_name, room_entity
            )
            return room_entity
        
        _LOGGER.debug(
            "Room '%s': No media player found. Tried: config, zone, HA Area, naming (%s)",
            room_name, room_entity
        )
        return None
    
    def _get_room_entries(self) -> dict:
        """Get all room entry configurations from config entries."""
        try:
            from .const import DOMAIN, CONF_ENTRY_TYPE, ENTRY_TYPE_ROOM
            
            room_entries = {}
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ROOM:
                    merged_config = {**entry.data, **entry.options}
                    room_entries[entry.entry_id] = merged_config
            
            return room_entries
        except Exception as e:
            _LOGGER.debug("Failed to get room entries: %s", e)
            return {}
    
    def _get_zone_player_config(self, zone_name: str) -> tuple[Optional[str], str]:
        """Get zone media player config from zone entries."""
        try:
            from .const import (
                DOMAIN, 
                CONF_ENTRY_TYPE, 
                ENTRY_TYPE_ZONE,
                CONF_ZONE_NAME,
                CONF_ZONE_PLAYER_ENTITY,
                CONF_ZONE_PLAYER_MODE,
                ZONE_PLAYER_MODE_FALLBACK,
            )
            
            zone_name_lower = zone_name.lower()
            
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ZONE:
                    entry_zone = entry.data.get(CONF_ZONE_NAME, "").lower()
                    if entry_zone == zone_name_lower:
                        merged_config = {**entry.data, **entry.options}
                        
                        player = merged_config.get(CONF_ZONE_PLAYER_ENTITY)
                        mode = merged_config.get(CONF_ZONE_PLAYER_MODE, ZONE_PLAYER_MODE_FALLBACK)
                        
                        _LOGGER.debug(
                            "Zone '%s': Found config - player=%s, mode=%s",
                            zone_name, player, mode
                        )
                        return player, mode
            
            _LOGGER.debug("Zone '%s': No config entry found", zone_name)
            return None, "fallback"
            
        except Exception as e:
            _LOGGER.debug("Failed to get zone player config for '%s': %s", zone_name, e)
            return None, "fallback"
    
    async def _transfer_media(
        self,
        from_player: str,
        to_player: str,
        from_state
    ) -> bool:
        """Transfer media playback from one player to another.
        
        v3.3.5.2: Fixed WiiM-to-WiiM to use media_player.join for synchronized playback
        
        Transfer methods:
        - Same platform with multiroom support: media_player.join (SYNCHRONIZED)
        - Cross-platform/Generic: play_media (INDEPENDENT)
        """
        try:
            source_platform = self._get_player_platform(from_player)
            target_platform = self._get_player_platform(to_player)
            
            _LOGGER.info(
                "🎵 Transfer method: %s (%s) → %s (%s)",
                from_player, source_platform, to_player, target_platform
            )
            
            # Get current playback info
            volume = from_state.attributes.get(ATTR_MEDIA_VOLUME_LEVEL, 0.5)
            position = from_state.attributes.get(ATTR_MEDIA_POSITION)
            media_content_id = from_state.attributes.get("media_content_id")
            media_content_type = from_state.attributes.get("media_content_type")
            
            _LOGGER.info(
                "🎵 Source state: volume=%.2f, position=%s, content_id=%s, content_type=%s",
                volume, position, 
                media_content_id[:50] + "..." if media_content_id and len(media_content_id) > 50 else media_content_id,
                media_content_type
            )
            
            transfer_success = False
            
            _LOGGER.info(
                "🎵 Platform transfer: %s → %s (source: %s, target: %s)",
                source_platform, target_platform, from_player, to_player
            )
            
            # CASE 1: Same platform with multiroom support - Use native grouping
            if source_platform == target_platform and source_platform in MULTIROOM_PLATFORMS:
                _LOGGER.info(
                    "🎵 Using %s-to-%s native multiroom (media_player.join, SYNCHRONIZED)",
                    source_platform.upper(), target_platform.upper()
                )
                transfer_success = await self._transfer_same_platform_join(
                    from_player, to_player, volume, source_platform
                )
            
            # CASE 2: Cross-platform or unsupported platform - Use generic play_media
            else:
                if source_platform != target_platform:
                    _LOGGER.info(
                        "🎵 Cross-platform transfer (%s → %s): using generic play_media (INDEPENDENT). "
                        "Different platforms use incompatible multiroom protocols.",
                        source_platform, target_platform
                    )
                else:
                    _LOGGER.info(
                        "🎵 Same platform (%s) but no native sync support: using generic play_media (INDEPENDENT)",
                        source_platform
                    )
                transfer_success = await self._transfer_generic(
                    from_player, to_player, volume, position, 
                    media_content_id, media_content_type
                )
            
            if not transfer_success:
                _LOGGER.warning("🎵 Primary transfer failed, playback may not have started on target")
            
            # Fade out source regardless of transfer success
            _LOGGER.info("🎵 Fading source %s to %.0f%%", from_player, self.FADE_OUT_VOLUME * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {
                    "entity_id": from_player,
                    "volume_level": self.FADE_OUT_VOLUME
                },
                blocking=False
            )
            
            return transfer_success
            
        except Exception as e:
            _LOGGER.error("🎵 Music transfer failed with exception: %s", e)
            import traceback
            _LOGGER.debug("🎵 Traceback: %s", traceback.format_exc())
            return False
    
    async def _transfer_same_platform_join(
        self,
        from_player: str,
        to_player: str,
        volume: float,
        platform: str
    ) -> bool:
        """Transfer between two players of the same platform using native grouping.
        
        v3.3.5.2: Unified method for Sonos, Linkplay, and WiiM
        
        All these platforms support media_player.join for synchronized multiroom.
        """
        try:
            _LOGGER.info(
                "🎵 %s: Joining %s to group with %s (synchronized multiroom)",
                platform.upper(), to_player, from_player
            )
            
            # Join target to source's group
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                "join",
                {
                    "entity_id": to_player,
                    "group_members": [from_player]
                },
                blocking=True
            )
            
            # Set volume on target
            _LOGGER.info("🎵 %s: Setting target volume to %.0f%%", platform.upper(), volume * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {
                    "entity_id": to_player,
                    "volume_level": volume
                },
                blocking=False
            )
            
            _LOGGER.info("🎵 %s: Synchronized transfer successful", platform.upper())
            return True
            
        except Exception as e:
            _LOGGER.warning(
                "🎵 %s: media_player.join failed (%s), trying fallback",
                platform.upper(), e
            )
            return False
    
    async def _transfer_generic(
        self,
        from_player: str,
        to_player: str,
        volume: float,
        position: Optional[int],
        media_content_id: Optional[str],
        media_content_type: Optional[str]
    ) -> bool:
        """Generic transfer using play_media service.
        
        Used for cross-platform transfers. Starts INDEPENDENT playback.
        """
        try:
            if not media_content_id or not media_content_type:
                _LOGGER.warning(
                    "🎵 Generic transfer failed: No media_content_id/type available. "
                    "Source may be playing from Line In or unsupported source."
                )
                return False
            
            _LOGGER.info(
                "🎵 Generic: Playing media on %s (content_type=%s, INDEPENDENT playback)",
                to_player, media_content_type
            )
            
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                "play_media",
                {
                    "entity_id": to_player,
                    "media_content_id": media_content_id,
                    "media_content_type": media_content_type
                },
                blocking=True
            )
            
            _LOGGER.info("🎵 Generic: Setting volume to %.0f%%", volume * 100)
            await self.hass.services.async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_VOLUME_SET,
                {
                    "entity_id": to_player,
                    "volume_level": volume
                },
                blocking=False
            )
            
            if position and position > 0:
                _LOGGER.info("🎵 Generic: Seeking to position %d seconds", position)
                try:
                    await self.hass.services.async_call(
                        MEDIA_PLAYER_DOMAIN,
                        "media_seek",
                        {
                            "entity_id": to_player,
                            "seek_position": position
                        },
                        blocking=False
                    )
                except Exception as seek_error:
                    _LOGGER.debug("🎵 Generic: Seek failed (not supported): %s", seek_error)
            
            _LOGGER.info("🎵 Generic: Transfer successful (independent playback)")
            return True
            
        except Exception as e:
            _LOGGER.error("🎵 Generic transfer failed: %s", e)
            return False
    
    async def manual_transfer(self, person_id: str, from_room: str, to_room: str) -> bool:
        """Manually trigger music transfer (for testing/automation)."""
        _LOGGER.info(
            "🎵 Manual transfer requested: %s from '%s' to '%s'",
            person_id, from_room, to_room
        )
        
        from_player = await self._get_room_player(from_room)
        to_player = await self._get_room_player(to_room)
        
        if not from_player:
            _LOGGER.warning("🎵 Manual transfer failed: no player in source room '%s'", from_room)
            return False
        
        if not to_player:
            _LOGGER.warning("🎵 Manual transfer failed: no player in target room '%s'", to_room)
            return False
        
        from_state = self.hass.states.get(from_player)
        if not from_state:
            _LOGGER.warning("🎵 Manual transfer failed: source player '%s' unavailable", from_player)
            return False
        
        if from_state.state != STATE_PLAYING:
            _LOGGER.warning(
                "🎵 Manual transfer failed: source '%s' not playing (state=%s)",
                from_player, from_state.state
            )
            return False
        
        return await self._transfer_media(from_player, to_player, from_state)
