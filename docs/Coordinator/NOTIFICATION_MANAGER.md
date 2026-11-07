# NOTIFICATION MANAGER DESIGN

**Version:** 1.0  
**Status:** Design Complete  
**Last Updated:** 2026-01-24  
**Scope:** Multi-channel notification service for all coordinators

---

## TABLE OF CONTENTS

1. [Overview](#1-overview)
2. [Notification Channels](#2-notification-channels)
3. [Severity & Routing](#3-severity--routing)
4. [Channel Implementations](#4-channel-implementations)
5. [Light Patterns](#5-light-patterns)
6. [Quiet Hours](#6-quiet-hours)
7. [Deduplication & Rate Limiting](#7-deduplication--rate-limiting)
8. [Implementation](#8-implementation)
9. [Configuration](#9-configuration)
10. [Diagnostics](#10-diagnostics)

---

## 1. OVERVIEW

### Purpose

The Notification Manager is a **shared service** that provides:
- Multi-channel notification delivery
- Severity-based routing
- Quiet hours enforcement
- Deduplication and rate limiting
- Visual alert patterns

### Design Principles

| Principle | Description |
|-----------|-------------|
| **Multi-Channel** | Never rely on single notification path |
| **Severity-Aware** | Route based on importance |
| **Non-Fatiguing** | Prevent alert overload |
| **Reliable** | Critical alerts always delivered |
| **Configurable** | User controls channel preferences |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       NOTIFICATION MANAGER                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  COORDINATORS                     NOTIFICATION MANAGER                       │
│  ┌──────────┐                    ┌───────────────────────────────────────┐  │
│  │  Safety  │───notify()────────▶│  Severity Router                      │  │
│  │ Security │───notify()────────▶│  ↓                                    │  │
│  │  Energy  │───notify()────────▶│  Quiet Hours Check                    │  │
│  │   etc.   │                    │  ↓                                    │  │
│  └──────────┘                    │  Deduplication                        │  │
│                                  │  ↓                                    │  │
│                                  │  Channel Dispatcher                   │  │
│                                  └───────────────────────────────────────┘  │
│                                              │                               │
│                    ┌─────────────────────────┼─────────────────────────┐    │
│                    ▼                         ▼                         ▼    │
│              ┌──────────┐             ┌──────────┐             ┌──────────┐ │
│              │ iMessage │             │ Speakers │             │  Lights  │ │
│              │  (MCP)   │             │  (TTS)   │             │ (Visual) │ │
│              └──────────┘             └──────────┘             └──────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. NOTIFICATION CHANNELS

### Available Channels

| Channel | Method | Availability | Use Case |
|---------|--------|--------------|----------|
| **iMessage** | MCP Integration | Now | Primary - hard to ignore |
| **Speakers** | TTS via WiiM | Configure later | Audible announcements |
| **Lights** | Visual patterns | Configure later | Visual alerts |
| **Push** | HA Companion App | Optional | Mobile notifications |

### Channel Capabilities

```python
@dataclass
class ChannelCapabilities:
    """What each channel can do."""
    
    channel_id: str
    
    # Content support
    supports_text: bool = True
    supports_title: bool = False
    supports_image: bool = False
    supports_action: bool = False
    
    # Delivery characteristics
    max_length: int | None = None
    delivery_delay_ms: int = 0
    requires_acknowledgment: bool = False
    
    # Availability
    quiet_hours_overridable: bool = True
    always_available: bool = False


CHANNEL_CAPABILITIES = {
    "imessage": ChannelCapabilities(
        channel_id="imessage",
        supports_text=True,
        max_length=1600,
        requires_acknowledgment=False,
        always_available=True,
    ),
    "speaker": ChannelCapabilities(
        channel_id="speaker",
        supports_text=True,
        max_length=500,  # TTS length limit
        delivery_delay_ms=500,  # Give speakers time to wake
        quiet_hours_overridable=True,
    ),
    "lights": ChannelCapabilities(
        channel_id="lights",
        supports_text=False,
        requires_acknowledgment=False,
        quiet_hours_overridable=True,
        always_available=True,
    ),
}
```

---

## 3. SEVERITY & ROUTING

### Severity Levels

```python
class NotificationSeverity(Enum):
    """Notification severity levels."""
    
    CRITICAL = 4
    # Life safety, immediate attention required
    # Channels: ALL, override quiet hours, repeat until acknowledged
    
    HIGH = 3
    # Urgent but not life-threatening
    # Channels: iMessage + Speaker + Lights
    
    MEDIUM = 2
    # Important, should be seen soon
    # Channels: iMessage, respects quiet hours
    
    LOW = 1
    # Informational
    # Channels: iMessage or log only
    
    INFO = 0
    # Debug/status
    # Channels: Log only
```

### Routing Rules

```python
class NotificationRouter:
    """Route notifications to appropriate channels."""
    
    ROUTING_RULES = {
        NotificationSeverity.CRITICAL: {
            "channels": ["imessage", "speaker", "lights"],
            "override_quiet_hours": True,
            "repeat_until_ack": True,
            "repeat_interval": timedelta(seconds=30),
        },
        NotificationSeverity.HIGH: {
            "channels": ["imessage", "speaker", "lights"],
            "override_quiet_hours": True,
            "repeat_until_ack": False,
        },
        NotificationSeverity.MEDIUM: {
            "channels": ["imessage"],
            "override_quiet_hours": False,
            "repeat_until_ack": False,
        },
        NotificationSeverity.LOW: {
            "channels": ["imessage"],
            "override_quiet_hours": False,
            "repeat_until_ack": False,
        },
        NotificationSeverity.INFO: {
            "channels": [],  # Log only
            "override_quiet_hours": False,
            "repeat_until_ack": False,
        },
    }
    
    def get_channels(
        self,
        severity: NotificationSeverity,
        is_quiet_hours: bool,
    ) -> list[str]:
        """Get channels for notification."""
        
        rules = self.ROUTING_RULES[severity]
        channels = rules["channels"].copy()
        
        # Filter out speaker during quiet hours (unless override)
        if is_quiet_hours and not rules["override_quiet_hours"]:
            channels = [c for c in channels if c != "speaker"]
        
        return channels
```

---

## 4. CHANNEL IMPLEMENTATIONS

### iMessage Channel (MCP)

```python
class IMessageChannel:
    """Send notifications via iMessage using MCP."""
    
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self._recipients = config.get("recipients", [])
        self._enabled = config.get("enabled", True)
    
    async def send(self, notification: Notification) -> bool:
        """Send iMessage notification."""
        
        if not self._enabled:
            return False
        
        if not self._recipients:
            _LOGGER.warning("iMessage: No recipients configured")
            return False
        
        # Build message
        message = self._format_message(notification)
        
        # Send to each recipient via MCP
        success = True
        for recipient in self._recipients:
            try:
                # MCP iMessage integration
                await self.hass.services.async_call(
                    "mcp",
                    "send_imessage",
                    {
                        "recipient": recipient,
                        "message": message,
                    },
                )
            except Exception as e:
                _LOGGER.error(f"iMessage send failed to {recipient}: {e}")
                success = False
        
        return success
    
    def _format_message(self, notification: Notification) -> str:
        """Format notification for iMessage."""
        
        # Add severity emoji
        emoji = {
            NotificationSeverity.CRITICAL: "🚨",
            NotificationSeverity.HIGH: "⚠️",
            NotificationSeverity.MEDIUM: "📢",
            NotificationSeverity.LOW: "ℹ️",
        }.get(notification.severity, "")
        
        parts = []
        
        if emoji:
            parts.append(emoji)
        
        parts.append(notification.message)
        
        if notification.data.get("location"):
            parts.append(f"📍 {notification.data['location']}")
        
        if notification.data.get("value"):
            parts.append(f"Value: {notification.data['value']}")
        
        return " ".join(parts)
```

### Speaker Channel (TTS)

```python
class SpeakerChannel:
    """Send notifications via TTS to speakers."""
    
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self._entity_ids = config.get("entity_ids", [])
        self._enabled = config.get("enabled", False)  # Default off until configured
        self._volume_by_severity = config.get("volume_by_severity", {
            NotificationSeverity.CRITICAL: 100,
            NotificationSeverity.HIGH: 80,
            NotificationSeverity.MEDIUM: 60,
            NotificationSeverity.LOW: 40,
        })
    
    async def send(self, notification: Notification) -> bool:
        """Send TTS notification to speakers."""
        
        if not self._enabled:
            return False
        
        if not self._entity_ids:
            _LOGGER.warning("Speaker: No entities configured")
            return False
        
        # Get volume for severity
        volume = self._volume_by_severity.get(notification.severity, 60) / 100.0
        
        # Build TTS message
        message = self._format_tts(notification)
        
        try:
            # Set volume first
            for entity_id in self._entity_ids:
                await self.hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {"entity_id": entity_id, "volume_level": volume},
                )
            
            # Send TTS
            await self.hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": self._entity_ids,
                    "message": message,
                    "cache": False,
                },
            )
            
            return True
            
        except Exception as e:
            _LOGGER.error(f"TTS send failed: {e}")
            return False
    
    def _format_tts(self, notification: Notification) -> str:
        """Format notification for TTS."""
        
        # Add attention-grabbing prefix for critical
        prefix = ""
        if notification.severity == NotificationSeverity.CRITICAL:
            prefix = "Attention! "
        elif notification.severity == NotificationSeverity.HIGH:
            prefix = "Alert! "
        
        return f"{prefix}{notification.message}"
```

### Lights Channel (Visual)

```python
class LightsChannel:
    """Visual notifications via smart lights."""
    
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self._entity_ids = config.get("entity_ids", [])
        self._enabled = config.get("enabled", False)
    
    async def send(self, notification: Notification) -> bool:
        """Trigger light pattern for notification."""
        
        if not self._enabled:
            return False
        
        if not self._entity_ids:
            return False
        
        # Get pattern for event type
        pattern = self._get_pattern(notification)
        
        if not pattern:
            return False
        
        try:
            await self._execute_pattern(pattern)
            return True
        except Exception as e:
            _LOGGER.error(f"Light pattern failed: {e}")
            return False
    
    def _get_pattern(self, notification: Notification) -> dict | None:
        """Get light pattern for notification."""
        
        # Pattern name from notification data or event type
        pattern_name = notification.data.get(
            "light_pattern",
            notification.event_type,
        )
        
        return LIGHT_PATTERNS.get(pattern_name)
    
    async def _execute_pattern(self, pattern: dict) -> None:
        """Execute a light pattern."""
        
        effect = pattern.get("effect", "solid")
        color = pattern.get("color", (255, 255, 255))
        brightness = pattern.get("brightness", 255)
        duration = pattern.get("duration_seconds", 30)
        
        # Store current state for restoration
        original_states = await self._capture_states()
        
        if effect == "flash":
            await self._flash_pattern(color, pattern.get("interval_ms", 500), duration)
        elif effect == "pulse":
            await self._pulse_pattern(color, duration)
        else:
            await self._solid_pattern(color, brightness, duration)
        
        # Restore original states
        await self._restore_states(original_states)
```

---

## 5. LIGHT PATTERNS

### Pattern Definitions

```python
LIGHT_PATTERNS = {
    # Security patterns
    "intruder": {
        "color": (255, 0, 0),      # Red
        "effect": "flash",
        "interval_ms": 500,
        "duration_seconds": 60,
        "brightness": 255,
    },
    "armed": {
        "color": (255, 0, 0),
        "effect": "solid",
        "brightness": 50,          # Dim red
        "duration_seconds": None,  # Until disarmed
        "lights": ["light.entry_indicator"],  # Specific lights only
    },
    
    # Safety patterns
    "fire": {
        "color": (255, 100, 0),    # Orange
        "effect": "flash",
        "interval_ms": 250,        # Faster flash
        "duration_seconds": 300,
        "brightness": 255,
    },
    "water_leak": {
        "color": (0, 0, 255),      # Blue
        "effect": "pulse",
        "duration_seconds": 120,
        "brightness": 200,
    },
    "carbon_monoxide": {
        "color": (255, 100, 0),
        "effect": "flash",
        "interval_ms": 250,
        "duration_seconds": 300,
    },
    
    # Warning patterns
    "warning": {
        "color": (255, 255, 0),    # Yellow
        "effect": "pulse",
        "duration_seconds": 60,
        "brightness": 180,
    },
    "freeze_risk": {
        "color": (0, 100, 255),    # Light blue
        "effect": "pulse",
        "duration_seconds": 120,
    },
    
    # Info patterns
    "arriving": {
        "color": (0, 255, 0),      # Green
        "effect": "solid",
        "brightness": 100,
        "duration_seconds": 30,
        "lights": ["light.entry_path"],
    },
}
```

### Pattern Execution

```python
class LightPatternExecutor:
    """Execute light patterns."""
    
    async def flash(
        self,
        lights: list[str],
        color: tuple[int, int, int],
        interval_ms: int,
        duration_seconds: int,
    ) -> None:
        """Execute flash pattern."""
        
        end_time = datetime.now() + timedelta(seconds=duration_seconds)
        interval = interval_ms / 1000
        
        while datetime.now() < end_time:
            # On
            await self._set_lights(lights, color, 255)
            await asyncio.sleep(interval)
            
            # Off
            await self._set_lights_off(lights)
            await asyncio.sleep(interval)
    
    async def pulse(
        self,
        lights: list[str],
        color: tuple[int, int, int],
        duration_seconds: int,
    ) -> None:
        """Execute pulse pattern (brightness cycles)."""
        
        end_time = datetime.now() + timedelta(seconds=duration_seconds)
        
        while datetime.now() < end_time:
            # Fade up
            for brightness in range(50, 255, 20):
                await self._set_lights(lights, color, brightness)
                await asyncio.sleep(0.1)
            
            # Fade down
            for brightness in range(255, 50, -20):
                await self._set_lights(lights, color, brightness)
                await asyncio.sleep(0.1)
```

---

## 6. QUIET HOURS

### Quiet Hours Configuration

```python
@dataclass
class QuietHoursConfig:
    """Quiet hours configuration."""
    
    enabled: bool = True
    start_time: time = time(22, 0)   # 10 PM
    end_time: time = time(7, 0)      # 7 AM
    
    # Channels affected
    mute_speakers: bool = True
    dim_lights: bool = True          # Reduced brightness
    reduce_light_duration: bool = True
    
    # Override rules
    override_for_critical: bool = True
    override_for_high: bool = True


class QuietHoursManager:
    """Manage quiet hours enforcement."""
    
    def __init__(self, config: QuietHoursConfig):
        self._config = config
    
    def is_quiet_hours(self) -> bool:
        """Check if currently in quiet hours."""
        
        if not self._config.enabled:
            return False
        
        now = datetime.now().time()
        start = self._config.start_time
        end = self._config.end_time
        
        # Handle overnight wrap
        if start > end:
            return now >= start or now < end
        else:
            return start <= now < end
    
    def should_override(self, severity: NotificationSeverity) -> bool:
        """Check if severity should override quiet hours."""
        
        if severity == NotificationSeverity.CRITICAL:
            return self._config.override_for_critical
        elif severity == NotificationSeverity.HIGH:
            return self._config.override_for_high
        
        return False
    
    def filter_channels(
        self,
        channels: list[str],
        severity: NotificationSeverity,
    ) -> list[str]:
        """Filter channels based on quiet hours."""
        
        if not self.is_quiet_hours():
            return channels
        
        if self.should_override(severity):
            return channels
        
        filtered = channels.copy()
        
        if self._config.mute_speakers:
            filtered = [c for c in filtered if c != "speaker"]
        
        return filtered
```

---

## 7. DEDUPLICATION & RATE LIMITING

### Deduplication

```python
class NotificationDeduplicator:
    """Prevent duplicate notifications."""
    
    def __init__(self):
        self._recent: dict[str, datetime] = {}
        
        # Suppression windows by severity
        self._windows = {
            NotificationSeverity.CRITICAL: timedelta(minutes=1),
            NotificationSeverity.HIGH: timedelta(minutes=5),
            NotificationSeverity.MEDIUM: timedelta(minutes=15),
            NotificationSeverity.LOW: timedelta(hours=1),
        }
    
    def should_send(self, notification: Notification) -> bool:
        """Check if notification should be sent."""
        
        # Build dedup key
        key = f"{notification.event_type}:{notification.data.get('location', 'global')}"
        
        last_sent = self._recent.get(key)
        if last_sent is None:
            self._recent[key] = datetime.now()
            return True
        
        window = self._windows.get(notification.severity, timedelta(minutes=10))
        
        if datetime.now() - last_sent > window:
            self._recent[key] = datetime.now()
            return True
        
        return False
    
    def clear(self, event_type: str, location: str | None = None) -> None:
        """Clear suppression for event (condition resolved)."""
        key = f"{event_type}:{location or 'global'}"
        self._recent.pop(key, None)
```

### Rate Limiting

```python
class NotificationRateLimiter:
    """Prevent notification flooding."""
    
    def __init__(self):
        self._counts: dict[str, list[datetime]] = {}
        
        # Limits per channel per minute
        self._limits = {
            "imessage": 10,
            "speaker": 5,
            "lights": 20,
        }
    
    def check_limit(self, channel: str) -> bool:
        """Check if channel is within rate limit."""
        
        limit = self._limits.get(channel, 10)
        window = timedelta(minutes=1)
        
        now = datetime.now()
        cutoff = now - window
        
        # Clean old entries
        if channel in self._counts:
            self._counts[channel] = [
                t for t in self._counts[channel] if t > cutoff
            ]
        else:
            self._counts[channel] = []
        
        # Check limit
        if len(self._counts[channel]) >= limit:
            return False
        
        # Record this notification
        self._counts[channel].append(now)
        return True
```

---

## 8. IMPLEMENTATION

```python
@dataclass
class Notification:
    """Notification to be sent."""
    
    event_type: str
    severity: NotificationSeverity
    message: str
    source_coordinator: str
    data: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class NotificationManager:
    """Central notification service."""
    
    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        
        # Initialize channels
        self._channels = {
            "imessage": IMessageChannel(hass, config.get("imessage", {})),
            "speaker": SpeakerChannel(hass, config.get("speakers", {})),
            "lights": LightsChannel(hass, config.get("lights", {})),
        }
        
        # Initialize managers
        self._router = NotificationRouter()
        self._quiet_hours = QuietHoursManager(
            QuietHoursConfig(**config.get("quiet_hours", {}))
        )
        self._deduplicator = NotificationDeduplicator()
        self._rate_limiter = NotificationRateLimiter()
        
        # Tracking
        self._pending_acks: dict[str, Notification] = {}
        self._notification_log: list[dict] = []
    
    async def notify(
        self,
        event_type: str,
        severity: NotificationSeverity,
        message: str,
        source_coordinator: str,
        data: dict | None = None,
    ) -> bool:
        """
        Send notification through appropriate channels.
        
        Args:
            event_type: Type of event (e.g., "water_leak", "intruder")
            severity: Notification severity
            message: Human-readable message
            source_coordinator: Which coordinator triggered this
            data: Additional data (location, value, etc.)
        
        Returns:
            True if notification was sent through at least one channel
        """
        
        notification = Notification(
            event_type=event_type,
            severity=severity,
            message=message,
            source_coordinator=source_coordinator,
            data=data or {},
        )
        
        # Check deduplication
        if not self._deduplicator.should_send(notification):
            _LOGGER.debug(f"Notification deduplicated: {event_type}")
            return False
        
        # Get channels
        is_quiet = self._quiet_hours.is_quiet_hours()
        channels = self._router.get_channels(severity, is_quiet)
        channels = self._quiet_hours.filter_channels(channels, severity)
        
        # Send to each channel
        sent_to_any = False
        
        for channel_name in channels:
            # Rate limit check
            if not self._rate_limiter.check_limit(channel_name):
                _LOGGER.warning(f"Rate limited: {channel_name}")
                continue
            
            channel = self._channels.get(channel_name)
            if channel:
                try:
                    success = await channel.send(notification)
                    if success:
                        sent_to_any = True
                        _LOGGER.info(
                            f"Notification sent via {channel_name}: {event_type}"
                        )
                except Exception as e:
                    _LOGGER.error(f"Channel {channel_name} failed: {e}")
        
        # Log notification
        self._log_notification(notification, channels, sent_to_any)
        
        # Handle repeat-until-ack
        rules = self._router.ROUTING_RULES.get(severity, {})
        if rules.get("repeat_until_ack") and sent_to_any:
            self._schedule_repeat(notification, rules.get("repeat_interval"))
        
        return sent_to_any
    
    async def acknowledge(self, event_type: str) -> None:
        """Acknowledge notification (stops repeating)."""
        self._pending_acks.pop(event_type, None)
        self._deduplicator.clear(event_type)
    
    def _log_notification(
        self,
        notification: Notification,
        channels: list[str],
        success: bool,
    ) -> None:
        """Log notification for diagnostics."""
        self._notification_log.append({
            "timestamp": notification.timestamp.isoformat(),
            "event_type": notification.event_type,
            "severity": notification.severity.name,
            "message": notification.message,
            "source": notification.source_coordinator,
            "channels": channels,
            "success": success,
        })
        
        # Keep only recent logs
        if len(self._notification_log) > 1000:
            self._notification_log = self._notification_log[-500:]
```

---

## 9. CONFIGURATION

### Configuration Schema

```yaml
# notification_manager configuration
notification_manager:
  imessage:
    enabled: true
    recipients:
      - "+1234567890"      # Primary
      - "+0987654321"      # Secondary
  
  speakers:
    enabled: false         # Set true when ready
    entity_ids: []         # Fill in WiiM media_player entities
    volume_by_severity:
      CRITICAL: 100
      HIGH: 80
      MEDIUM: 60
      LOW: 40
  
  lights:
    enabled: false         # Set true when ready
    entity_ids: []         # Fill in light entities for patterns
  
  quiet_hours:
    enabled: true
    start_time: "22:00"
    end_time: "07:00"
    mute_speakers: true
    dim_lights: true
    override_for_critical: true
    override_for_high: true
```

### Runtime Configuration Updates

```python
async def update_config(self, channel: str, config: dict) -> None:
    """Update channel configuration at runtime."""
    
    if channel == "speakers":
        self._channels["speaker"] = SpeakerChannel(self.hass, config)
    elif channel == "lights":
        self._channels["lights"] = LightsChannel(self.hass, config)
    elif channel == "imessage":
        self._channels["imessage"] = IMessageChannel(self.hass, config)
```

### Life-safety repeat schedule (shipped with SAFETY-NM-REFIRE-UNWIRED-1, D7)

The code supersedes the `repeat_interval: 30s` sketch above. Unacked CRITICAL alerts repeat on a schedule picked by hazard class (`notification_manager.py` `_repeat_interval_for_active_alert`):

- **Non-life-safety:** decay ladder. Every 5 min (`NM_REPEAT_PHASE1_S`) for the first hour (`NM_REPEAT_PHASE1_WINDOW_S`), then every 30 min (`NM_REPEAT_PHASE2_S`), then daily after 24 h (`NM_REPEAT_DAILY_AFTER_S`).
- **Other life-safety** (`NM_LIFE_SAFETY_HAZARDS` minus the set below, e.g. intruder, plus operator extras): every 30 s (`NM_REPEAT_INTERVAL_LIFE_SAFETY`) until acknowledged, under every setting value.
- **Safety life-safety** (`NM_SCHEDULED_LIFE_SAFETY_HAZARDS` = smoke, carbon_monoxide, flooding, fire, water_leak, freeze_risk): follow the options-flow select "Smoke, CO and flood repeat schedule" `nm_life_safety_repeat_schedule` (Quiet Hours step, rung 2):
  - `standard` (default): the same ladder as non-life-safety.
  - `fast_start`: every 60 s (`NM_REPEAT_FAST_START_S`) for the first 600 s (`NM_REPEAT_FAST_START_WINDOW_S`), then the ladder.
  - `urgent`: every 30 s (`NM_REPEAT_INTERVAL_LIFE_SAFETY`) until acknowledged.
  - Unknown or missing value: `standard`.
- The value is read through `_refresh_config` on every notify and repeat tick. The key is in `_NM_C_KEYS`, so a save applies in place without a CM reload, and `_apply_in_place` calls `reschedule_repeat_for_config_change()` to re-arm an active alert's pending repeat with the new interval. The `repeat_phase` attribute reports `life_safety` (urgent), `fast_start`, `phase1`, `phase2`, `daily` or `legacy`.
- Life-safety classification still drives the DND and mute bypass (severity HIGH and above only), the token-bucket bypass (CRITICAL only), the boot-settle exemption and per-hazard cooldowns. The setting changes only the repeat cadence.

### Inbound house queries (`diag` menu, NM-INBOUND-HOUSE-QUERIES-1)

Plan: `docs/planning/PLANNING_nm_diag_text_menu.md` (rev 2). Read-only. No text ever actuates anything beyond the existing ack / silence / safe-word effects.

**Grammar** (whole message, `strip().lower()`, exact match only; table `DIAG_COMMANDS`):

| Text | Effect |
|---|---|
| `diag`, `menu`, `house` | reply with the menu; opens a per-(person, channel) window when the alert state is IDLE |
| `doors` `garage` `who` `hvac` `energy` `alerts` `health` | that answer, any time (also while silenced) |
| `1`..`7` | menu item N, only inside an open window that no send has closed, while IDLE |
| other digits inside an open window | "Pick 1-7 or a name" |
| anything else | the legacy path, unchanged |

While the alert state is not IDLE, `diag` returns a words-only menu ("Alert active: numbers mean ack/status/silence") and opens no window.

**Answers** come from `custom_components/universal_room_automation/house_status.py` (`doors`, `garage`, `who`, `hvac`, `energy`, `alerts`, `health`, `render`). Each returns a `StatusResult` with a `source` per field (so the OC agent can call the same functions as cited tools later). Sources: SC `security_lock_entities` / `security_garage_entities`; the two garage remote-lockout locks read directly (`HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES`); `CoordinatorManager.house_state`; `census_count`; `person_state_for_trust` + `get_person_location`; HVAC `ZoneState` with "running" from the zone `ac_load_sensor` through the arrester's `_read_kwh_rate(warn=False)` (not `hvac_action`); `battery_soc`, `solar_production_w`, `net_power_w`; NM alert state, `get_active_criticals` age-capped by `_recovery_row_is_stale`, each coordinator's `anomaly_detector.get_sensor_state()`; per-room `*_unavailable_entities` resolved by unique_id, URA repairs.

**Precedence inside `_process_inbound_reply`:** step 0 captures `epoch_at_entry` / `now_at_entry` before any await; echo rail 1; kill switch `_messaging_suppressed`; safe-word pre-parse and match; `_resolve_diag` (synchronous, the only window writer; skipped for a safe word, for Companion `person_id=None`, and when `NM_DIAG_ENABLED` is False); silence gate (diag exempt); safe-word branch; diag dispatch; legacy ack / status / silence / help / unknown.

**Rails that keep `1`/`2`/`3` meaning ack/status/silence:**
- *Send rail (primary; the only guard for HIGH/MEDIUM/LOW alerts):* the first statement of each of the four text senders (`_send_pushover`, `_send_companion`, `_send_whatsapp`, `_send_imessage`) is `if not menu_safe: self._diag_send_epoch += 1`, before the dry-run return. Only `_send_reply` passes `menu_safe=True` (keyword-only). A window whose stored epoch differs from the inbound's captured epoch is closed. Test `test_no_text_service_call_outside_four_senders` fails if a text `async_call` appears anywhere else in NM. Non-NM `notify.*` callers (`aggregation.py` zone safety alert, `button.py` export) carry no response dictionary and are out of scope.
- *State rail (CRITICAL-only defence):* digits stay legacy while `_alert_state` is not IDLE.
- *Closed notice:* a bare `1`/`2`/`3` within `NM_DIAG_CLOSED_NOTICE_S` of opening a window that a send then closed, with the state IDLE and no `_active_alert_data`, gets "Menu closed: an alert was just sent…" and no effect. Accepted cost: a `3` meant as silence right after a HIGH alert needs the word `silence`.

**Rate limits:** diag replies bypass echo rail 2 entirely (`_log_and_reply(..., rail2=False)` neither checks nor stamps `_last_reply_at`), so checking the doors never swallows a later ack / safe-word / silence confirmation. Diag has its own per-(person, channel) budget; over budget gets one "Too many requests" reply, then silence for the window (rows still logged as `diag_rate_limited`).

**Audit:** one `notification_inbound` row per diag query, `parsed_command` = `diag_menu`, `diag_<item>`, `diag_bad_pick`, `diag_closed_notice` or `diag_rate_limited`. Counter key `diag` in `inbound_by_command`. The `help` reply gains `diag = house status menu`; alert bodies (`RESPONSE_DICT_TEXT`) are unchanged.

**Knobs (all rung 1, `notification_manager.py` / `house_status.py`):**

| Knob | Default | Meaning |
|---|---|---|
| `NM_DIAG_ENABLED` | True | the only kill switch; False = pre-cycle behaviour byte for byte |
| `NM_DIAG_MENU_WINDOW_S` | 120 | digit window; 0 = names only |
| `NM_DIAG_CLOSED_NOTICE_S` | 300 | closed-notice span; 0 = no notice |
| `NM_DIAG_REPLY_BUDGET` / `NM_DIAG_REPLY_BUDGET_WINDOW_S` | 10 / 600 | diag loop backstop (not a kill switch) |
| `NM_DIAG_MAX_REPLY_CHARS` | 900 | reply cap incl. title prefix (Pushover limit 1024) |
| `HOUSE_STATUS_AC_RUNNING_KW` | 0.3 | "running" threshold |
| `HOUSE_STATUS_STALE_S` | 300 | "(N min old)" threshold |
| `HOUSE_STATUS_GARAGE_LOCKOUT_ENTITIES` | konnected + ratgdo lockout locks | empty = no lockout lines |

**Known limits:** `doors` lists only the SC-configured locks (live config on 2026-11-07 had only the front-entry lock; add others under the security coordinator options). `health` reads only enabled `*_unavailable_entities` sensors (21 of 47 rooms on 2026-11-07; the rest are disabled by the integration default). Companion actions resolve the person from `event.context.user_id` (`_person_for_companion_event`), so status / silence / text-input replies go back on that person's companion service; an unresolvable user still gets no reply. Companion replies carry no action buttons (`_send_companion(..., reply=True)`), so no safe-word-free Acknowledge sits under a status reply; alert pushes keep theirs. WhatsApp inbound reads the bridge's `from`/`body` keys (`_parse_whatsapp_event`) and is **self-chat only**: the bridge runs on the operator's own number, so a message is parsed only when from-number == to-number == a configured NM WhatsApp phone. Every direct chat from anyone else to that number, configured family included, is personal and never parsed; groups, newsletters and broadcasts are ignored for every payload shape. Kill switch `NM_WHATSAPP_INBOUND_ENABLED` (rung 1, default True; False ignores all WhatsApp inbound). Replays are dropped: an event whose (from, timestamp, body) was already processed within `NM_WHATSAPP_DEDUP_TTL_S` (rung 1, 600 s; 0 disables) is ignored, so a bridge reconnect replay cannot re-apply a safe word or silence. Each text sender also closes menu windows again after its send await returns, so a `diag` that arrives mid-send cannot leave a live window. Kill-switch coverage: `NM_DIAG_ENABLED` = diag menu only; `NM_WHATSAPP_INBOUND_ENABLED` = WhatsApp ingestion; Companion person attribution has no switch (an unresolvable user keeps the old no-reply behaviour). Recorder on 2026-11-07 showed no `fromMe=true` events, so the operator's own self-chat texts may not reach NM until the bridge emits them.

---

## 10. DIAGNOSTICS

### Diagnostic Sensor

```yaml
sensor.ura_notification_manager:
  state: "healthy"
  attributes:
    channels_enabled:
      imessage: true
      speaker: false
      lights: false
    
    notifications_24h:
      total: 47
      by_severity:
        CRITICAL: 0
        HIGH: 2
        MEDIUM: 15
        LOW: 30
      by_channel:
        imessage: 47
        speaker: 0
        lights: 0
    
    deduplication_rate: 0.12
    rate_limit_hits_24h: 3
    quiet_hours_active: false
    pending_acks: 0
```

### Services

| Service | Parameters | Description |
|---------|------------|-------------|
| `ura.test_notification` | severity, message | Test notification |
| `ura.acknowledge_notification` | event_type | Acknowledge alert |
| `ura.update_notification_config` | channel, config | Update config |

---

## KEY DESIGN QUESTIONS

### Q1: iMessage Recipients

**Question:** Who should receive notifications?

**Current Design:** Configurable list of phone numbers.

**Recommendation Needed:** Phone numbers for notification recipients.

---

### Q2: Speaker Entities

**Question:** Which WiiM devices for TTS?

**Current Design:** Placeholder for `media_player.*` entity IDs.

**Recommendation Needed:** List of WiiM media_player entities for TTS.

---

### Q3: Light Entities for Patterns

**Question:** Which lights for visual alerts?

**Options:**
1. All smart lights
2. Specific notification lights
3. Entry/egress path lights only

**Recommendation Needed:** Which lights for visual notification patterns?

---

**Document Status:** Design Complete - Pending Configuration  
**Shared Service:** Used by all coordinators  
**Dependencies:** MCP iMessage integration, WiiM speakers, smart lights
