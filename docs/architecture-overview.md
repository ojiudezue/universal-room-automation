# URA Architecture Overview

## System Architecture

```mermaid
graph TB
    subgraph HA["Home Assistant Core"]
        direction TB
        Entities["Entity State Machine<br/>(climate, light, lock, person,<br/>media_player, sensor, cover)"]
        Services["Service Registry<br/>(light.turn_on, climate.set_temperature,<br/>lock.lock, media_player.join)"]
        Events["Event Bus<br/>(state_changed, call_service)"]
    end

    subgraph URA["Universal Room Automation Integration"]
        direction TB

        subgraph ConfigEntries["Config Entries"]
            IE["INTEGRATION<br/>(house-level config)"]
            RE["ROOM × N<br/>(per-room sensors,<br/>lights, climate)"]
            ZME["ZONE_MANAGER<br/>(HVAC zones,<br/>thermostat mapping)"]
            CME["COORDINATOR_MANAGER<br/>(domain coordinator<br/>system)"]
        end

        subgraph CM["Coordinator Manager"]
            direction TB
            IntentQueue["Intent Queue<br/>(batched every 100ms)"]
            CR["Conflict Resolver<br/>(priority × severity × confidence)"]
        end

        subgraph Coordinators["Domain Coordinators (Priority-Ordered)"]
            direction LR
            Safety["Safety<br/>P:100<br/>Smoke, CO,<br/>Water, Freeze"]
            Security["Security<br/>P:80<br/>Locks, Alarms,<br/>Cameras"]
            Energy["Energy<br/>P:40<br/>TOU, Battery,<br/>Solar, Load Shed"]
            HVAC["HVAC<br/>P:30<br/>Zones, Presets,<br/>Pre-conditioning"]
            MF["Music Following<br/>P:30<br/>Speaker Handoff"]
            Presence["Presence<br/>House State,<br/>Zone Tracking"]
        end

        subgraph NM["Notification Manager"]
            direction LR
            Pushover["Pushover"]
            Companion["Companion"]
            WhatsApp["WhatsApp"]
            iMessage["iMessage<br/>(BlueBubbles)"]
            TTS["TTS"]
            Lights["Alert Lights"]
        end

        subgraph Helpers["Helper Modules"]
            Auto["Automation Engine<br/>(per-room lights,<br/>climate, covers)"]
            Census["Camera Census<br/>(Frigate + UniFi)"]
            PersonCoord["Person Coordinator<br/>(Bermuda BLE)"]
            HSM["House State Machine<br/>(9 states)"]
        end

        subgraph Platforms["Entity Platforms"]
            Sensors["sensor × 80+"]
            BinSensors["binary_sensor × 30+"]
            Switches["switch × 11"]
            Buttons["button × 6"]
            Numbers["number"]
            Selects["select × 2"]
        end

        DB[("SQLite DB<br/>25+ tables<br/>occupancy, energy,<br/>decisions, census")]
    end

    subgraph External["External Integrations"]
        Enphase["Enphase<br/>Enpower/IQ"]
        Frigate["Frigate NVR"]
        UniFi["UniFi Protect"]
        Bermuda["Bermuda BLE"]
        BB["BlueBubbles<br/>Server"]
        Solcast["Solcast<br/>Solar Forecast"]
        Weather["Weather<br/>Service"]
    end

    %% Data flow
    Entities -->|state changes| Events
    Events -->|triggers| IntentQueue
    IntentQueue -->|dispatch by priority| Coordinators
    Coordinators -->|CoordinatorAction list| CR
    CR -->|winning actions| Services

    %% Signal flow
    Presence -->|SIGNAL_HOUSE_STATE_CHANGED| HVAC
    Presence -->|SIGNAL_HOUSE_STATE_CHANGED| Energy
    Presence -->|SIGNAL_HOUSE_STATE_CHANGED| Security
    Census -->|SIGNAL_CENSUS_UPDATED| Presence
    Energy -->|SIGNAL_ENERGY_CONSTRAINT| HVAC
    Safety -->|SIGNAL_SAFETY_HAZARD| NM
    Security -->|SIGNAL_SECURITY_EVENT| NM

    %% External connections
    Enphase -.->|battery SOC, grid power| Energy
    Solcast -.->|solar forecast| Energy
    Weather -.->|temperature forecast| Energy
    Frigate -.->|person detection| Census
    UniFi -.->|camera counts| Census
    Bermuda -.->|BLE distance| PersonCoord
    BB -.->|webhook inbound| iMessage

    %% DB connections
    Coordinators -->|decisions, compliance| DB
    Energy -->|billing, peak import| DB
    Presence -->|occupancy, transitions| DB
    Census -->|census snapshots| DB

    %% Platform connections
    Coordinators --> Platforms
    Auto --> Platforms
```

## Coordinator Signal Flow

```mermaid
flowchart LR
    subgraph Publish["Publishers"]
        P_Pres["Presence Coordinator"]
        P_Census["Camera Census"]
        P_Energy["Energy Coordinator"]
        P_Safety["Safety Coordinator"]
        P_Security["Security Coordinator"]
        P_NM["Notification Manager"]
    end

    subgraph Signals["Signals"]
        S_HS["HOUSE_STATE_CHANGED"]
        S_CU["CENSUS_UPDATED"]
        S_EC["ENERGY_CONSTRAINT"]
        S_SH["SAFETY_HAZARD"]
        S_SE["SECURITY_EVENT"]
        S_NM["NM_ALERT_STATE_CHANGED"]
    end

    subgraph Subscribe["Subscribers"]
        C_HVAC["HVAC"]
        C_Energy["Energy"]
        C_Security["Security"]
        C_Presence["Presence"]
        C_NM["Notification Manager"]
        C_Safety["Safety"]
    end

    P_Pres --> S_HS
    P_Census --> S_CU
    P_Energy --> S_EC
    P_Safety --> S_SH
    P_Security --> S_SE
    P_NM --> S_NM

    S_HS --> C_HVAC
    S_HS --> C_Energy
    S_HS --> C_Security
    S_CU --> C_Presence
    S_EC --> C_HVAC
    S_SH --> C_NM
    S_SE --> C_NM
    S_NM --> C_Safety
```

## Energy Coordinator Internal Architecture

```mermaid
graph TB
    subgraph EC["Energy Coordinator (P:40)"]
        direction TB
        Main["EnergyCoordinator<br/>Decision Cycle (5 min)"]

        subgraph SubModules["Sub-Modules"]
            TOU["TOU Rate Engine<br/>(PEC rates, period detection)"]
            Battery["Battery Strategy<br/>(reserve SOC, mode selection,<br/>charge-from-grid)"]
            Billing["Cost Tracker<br/>(daily/cycle totals,<br/>import/export cost)"]
            Forecast["Energy Predictor<br/>(temp regression,<br/>accuracy tracking)"]
            Pool["Pool Optimizer<br/>+ EV Controller<br/>+ Smart Plugs"]
            Circuits["SPAN Monitor<br/>+ Generator Monitor"]
        end

        subgraph LoadShed["Load Shedding Cascade"]
            L1["Level 1: Pool"]
            L2["Level 2: EV"]
            L3["Level 3: Smart Plugs"]
            L4["Level 4: HVAC Constraint"]
        end

        PeakDB[("Peak Import History<br/>DB Persistence<br/>(1500 readings)")]
    end

    Main --> TOU
    Main --> Battery
    Main --> Billing
    Main --> Forecast
    Main --> Pool
    Main --> Circuits
    TOU -->|period transition| Battery
    Main -->|sustained import > threshold| LoadShed
    L1 --> L2 --> L3 --> L4
    LoadShed -->|hourly save| PeakDB
```

## HVAC Coordinator Internal Architecture

```mermaid
graph TB
    subgraph HC["HVAC Coordinator (P:30)"]
        direction TB
        HMain["HVACCoordinator<br/>Decision Cycle"]

        subgraph HVACSub["Sub-Modules"]
            Zones["Zone Manager<br/>(zone discovery,<br/>climate entities)"]
            Presets["Preset Manager<br/>(seasonal setpoints,<br/>house state mapping)"]
            Fans["Fan Controller<br/>(temp hysteresis,<br/>occupancy gating)"]
            Covers["Cover Controller<br/>(solar gain,<br/>direction-based)"]
            Predict["Pre-Conditioning<br/>(comfort risk,<br/>zone demand)"]
            Arrester["Override Arrester<br/>(2-tier severity,<br/>startup audit)"]
        end
    end

    HMain --> Zones
    HMain --> Presets
    HMain --> Fans
    HMain --> Covers
    HMain --> Predict
    HMain --> Arrester
    Presets -->|setpoints| Zones
    Arrester -->|revert override| Zones
```

## House State Machine

```mermaid
stateDiagram-v2
    [*] --> away
    away --> arriving: person detected
    arriving --> home_day: dwell > threshold (daytime)
    arriving --> home_evening: dwell > threshold (evening)
    arriving --> home_night: dwell > threshold (night)
    home_day --> home_evening: time transition
    home_evening --> home_night: time transition
    home_night --> sleep: all zones quiet
    sleep --> waking: motion detected
    waking --> home_day: time transition
    home_day --> away: all persons departed
    home_evening --> away: all persons departed
    home_night --> away: all persons departed
    away --> vacation: extended absence
    vacation --> arriving: person detected
```

## Notification Alert Pipeline

```mermaid
flowchart TB
    subgraph Trigger["Alert Sources"]
        SafetyHaz["Safety Hazard<br/>(smoke, CO, water, freeze)"]
        SecEvent["Security Event<br/>(intrusion, entry alert)"]
        EnergyAlert["Energy Alert<br/>(Envoy offline, shed)"]
        HVACAlert["HVAC Alert<br/>(override detected)"]
    end

    subgraph NMPipeline["Notification Manager Pipeline"]
        Dedup["Dedup Window<br/>CRITICAL: 60s<br/>HIGH: 300s<br/>MEDIUM: 900s<br/>LOW: 3600s"]
        Severity["Severity Router"]
        QuietHrs["Quiet Hours<br/>Check"]
        Cooldown["Per-Hazard<br/>Cooldown"]

        subgraph Channels["Channel Dispatch"]
            CH_PO["Pushover"]
            CH_CO["Companion"]
            CH_WA["WhatsApp"]
            CH_IM["iMessage"]
            CH_TT["TTS"]
            CH_LI["Alert Lights"]
        end

        Repeat["CRITICAL Repeat<br/>(every 60s until ack)"]
        SafeWord["Safe Word<br/>System"]
        Digest["Morning/Evening<br/>Digest"]
    end

    subgraph Inbound["Inbound Channels"]
        IB_CO["Companion Actions"]
        IB_WA["WhatsApp Reply"]
        IB_PO["Pushover Reply"]
        IB_IM["iMessage Webhook"]
    end

    Trigger --> Dedup --> Severity --> QuietHrs --> Cooldown --> Channels
    Channels -->|CRITICAL| Repeat
    Inbound --> SafeWord
    SafeWord -->|acknowledge| Repeat
```

## Data Persistence Model

```mermaid
erDiagram
    OCCUPANCY_EVENTS {
        string room_id PK
        string event_type
        float timestamp
    }
    PERSON_VISITS {
        string person_id
        string room_id
        float entry_time
        float exit_time
        float confidence
    }
    ROOM_TRANSITIONS {
        string person_id
        string from_room
        string to_room
        float timestamp
        string validation_method
    }
    ENERGY_DAILY {
        string date PK
        float import_kwh
        float export_kwh
        float net_cost
        float consumption_kwh
        float predicted_consumption_kwh
        float avg_temperature
    }
    ENERGY_PEAK_IMPORT {
        int id PK
        int seq
        float import_kw
    }
    DECISION_LOG {
        float timestamp
        string coordinator_id
        string situation
        string actions
        string scope
    }
    CENSUS_SNAPSHOTS {
        float timestamp
        string zone_id
        int frigate_count
        int unifi_count
    }
    NOTIFICATION_INBOUND {
        int id PK
        string channel
        string person_id
        string message
        string response_type
    }
```
