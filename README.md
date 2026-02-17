# Universal Room Automation (URA)

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-blue.svg)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/version-3.3.5.3-green.svg)](https://github.com/ojiudezue/universal-room-automation)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Advanced Home Assistant integration for event-driven, person-aware whole-house automation**

## 🌟 Overview

Universal Room Automation (URA) is a sophisticated Home Assistant custom integration that transforms individual rooms into intelligent automation zones with whole-house coordination. Built on an event-driven architecture with multi-person tracking, URA delivers 2-5 second response times and 74+ entities per room.

### Key Features

- 🏃 **Event-Driven Architecture** - 2-5 second response time (not polling)
- 👥 **Multi-Person Tracking** - BLE-based presence detection (Bermuda integration)
- 🏠 **Zone Coordination** - Whole-house aggregation and intelligence
- 📊 **74+ Entities Per Room** - Comprehensive automation control
- 🎵 **Music Following** - Cross-room media player coordination
- 🔋 **Energy Tracking** - SQLite-based data collection
- 🧪 **178+ Tests** - Comprehensive test coverage
- 🎯 **Production Ready** - Stable v3.3.5.3 deployed

## 📦 What's Included

### Integration Components

- **Sensors** - Occupancy, person tracking, environmental, energy, patterns
- **Binary Sensors** - Motion, presence, alerts, security
- **Buttons** - Manual triggers and resets
- **Numbers** - Thresholds and timeouts
- **Selects** - Modes and options
- **Switches** - Feature toggles

### Architecture

```
Integration (Parent Entry)
    ├── Zone Entries (e.g., Upstairs, Downstairs)
    │   ├── Room Entries (e.g., Living Room, Bedroom)
    │   │   ├── 74+ Entities
    │   │   ├── Person Tracking
    │   │   ├── Environmental Monitoring
    │   │   └── Automation Engine
    │   └── Zone Aggregation
    └── Whole-House Coordination
```

## 🚀 Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click "Integrations"
3. Click the menu (⋮) and select "Custom repositories"
4. Add `https://github.com/ojiudezue/universal-room-automation`
5. Select "Integration" as category
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Download the latest release
2. Copy the `custom_components/universal_room_automation` folder to your `config/custom_components/` directory
3. Restart Home Assistant
4. Go to Settings → Devices & Services → Add Integration
5. Search for "Universal Room Automation"

## 📖 Documentation

Comprehensive documentation is available in the [`docs/`](docs/) folder:

- **[VISION_v7.md](docs/VISION_v7.md)** - Project vision and philosophy
- **[ROADMAP_v9.md](docs/ROADMAP_v9.md)** - Development roadmap and future features
- **[CURRENT_STATE.md](docs/CURRENT_STATE.md)** - Current development status
- **[QUALITY_CONTEXT.md](docs/QUALITY_CONTEXT.md)** - Quality standards and best practices

### Planning Documents

- **[v3.5.0 Camera Intelligence](docs/PLANNING_v3_5_0_Camera_Intelligence.md)** - Next major release (Q2 2026)
- **[v3.4.0 AI Custom Automation](docs/PLANNING_v3.4.0.md)** - Natural language customization
- **[v3.6.0 Domain Coordinators](docs/PLANNING_v3.6.0.md)** - Security, energy, comfort coordination

## 🔧 Configuration

### Basic Setup

After installation, add the integration through the UI:

1. Navigate to **Settings → Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"Universal Room Automation"**
4. Follow the configuration flow:
   - Create integration (parent)
   - Add zones (e.g., Upstairs, Downstairs)
   - Add rooms to zones
   - Configure sensors and devices per room

### Requirements

- **Home Assistant** 2024.1.0 or newer
- **BLE Tracking** (recommended): [Bermuda BLE Trilateration](https://github.com/agittins/bermuda) for person tracking
- **SQLite** support (built-in)

### Optional Integrations

- **Bermuda BLE** - Enhanced person tracking
- **UniFi Protect** - Camera intelligence (planned v3.5.0)
- **Frigate** - Person detection (planned v3.5.0)

## 🎯 Current Status

**Production Version:** v3.3.5.3 (Stable)  
**Development Focus:** v3.3.x.x bug fixes → v3.5.0 Camera Intelligence  
**Test Coverage:** 178+ passing tests  
**Response Time:** 2-5 seconds (event-driven)

### Recent Updates (v3.3.5.x)

- ✅ Music transition logic refinements
- ✅ Zone management improvements
- ✅ Person tracking enhancements
- ✅ BLE room-level precision tuning

## 🛠️ Development

### Quality Standards

See [`quality/DEVELOPMENT_CHECKLIST.md`](quality/DEVELOPMENT_CHECKLIST.md) for:
- Development workflow
- Testing requirements
- Code review checklist
- Deployment procedures

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=custom_components/universal_room_automation

# Expected: 178+ passing tests
```

### Contributing

This is currently a personal project, but contributions are welcome! Please:

1. Read the [VISION](docs/VISION_v7.md) to understand the project philosophy
2. Check the [ROADMAP](docs/ROADMAP_v9.md) for planned features
3. Review [QUALITY_CONTEXT](docs/QUALITY_CONTEXT.md) for standards
4. Submit pull requests with tests

## 📊 Project Stats

- **Version:** v3.3.5.3
- **Lines of Code:** ~500KB across 22 modules
- **Test Coverage:** 178+ tests
- **Documentation:** ~36,000 words
- **Development Time:** 18+ months
- **Architecture Evolution:** v2.0 → v3.3.5.3

## 🗺️ Roadmap

### Upcoming Features

- **v3.5.0** - Camera Intelligence & Whole-House Census (Q2 2026)
  - UniFi Protect + Frigate integration
  - Guest detection
  - Person-specific automation
  
- **v3.4.0** - AI Custom Automation (Q3 2026)
  - Natural language room customization
  - Person-specific rules
  
- **v4.0.0** - Bayesian Predictive Intelligence (Q1 2027)
  - Person-specific predictions
  - Pattern learning
  
See [ROADMAP_v9.md](docs/ROADMAP_v9.md) for complete roadmap.

## 📝 License

MIT License - See [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- **Home Assistant** community for the amazing platform
- **Bermuda BLE** integration for person tracking capabilities
- **Claude AI** (Anthropic) for development assistance

## 📞 Support

- **Issues:** [GitHub Issues](https://github.com/ojiudezue/universal-room-automation/issues)
- **Documentation:** [docs/](docs/)
- **Discussions:** [GitHub Discussions](https://github.com/ojiudezue/universal-room-automation/discussions)

---

**Made with ❤️ for Home Assistant**
