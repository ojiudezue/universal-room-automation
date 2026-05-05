# VibeMemo Decision Point Detection Taxonomy

> How tools detect decision points programmatically.

## Overview

A decision point is a moment where the developer (or AI on their behalf) makes a choice that affects the codebase's architecture, security, data model, or operational characteristics. VibeMemo tools use pattern matching to detect these moments and trigger counseling.

Detection is heuristic, not perfect. False negatives (missing a decision) are worse than false positives (flagging a non-decision), because missed decisions are invisible. Over-flagging can be tuned down; missed decisions are lost forever.

## Detection Categories

### 1. Dependency Addition

**What:** A new package, library, or framework is added to the project.
**Why it matters:** Dependencies are the most common source of architectural lock-in, security vulnerabilities, and maintenance burden.

| Signal | Pattern | Severity |
|--------|---------|----------|
| pip install | `pip\s+install\s+\S+` | medium |
| New entry in requirements.txt / pyproject.toml | Diff adds line to requirements file | medium |
| Database driver added | Package name matches `(pg\|mysql\|mongoose\|prisma\|drizzle\|sequelize\|typeorm\|knex\|sqlite)` | high |
| Auth library added | Package name matches `(passport\|next-auth\|auth0\|clerk\|lucia\|supabase.*auth\|firebase.*auth)` | high |
| HA integration added | New entry in `manifest.json` dependencies | high |

### 2. Database & Data Model

**What:** Schema changes, new tables/collections, migrations.
**Why it matters:** Data model decisions are among the hardest to reverse. Wrong schema = months of migration pain.

| Signal | Pattern | Severity |
|--------|---------|----------|
| SQL CREATE TABLE | `CREATE\s+TABLE` | high |
| SQL ALTER TABLE | `ALTER\s+TABLE` | high |
| New DB method in database.py | New `async def` in `database.py` | medium |
| Index creation | `CREATE\s+(UNIQUE\s+)?INDEX` | medium |

### 3. Home Assistant Integration Patterns

**What:** Config flow changes, coordinator lifecycle, entity platform changes.
**Why it matters:** HA integration patterns are strict and mistakes cascade into production failures.

| Signal | Pattern | Severity |
|--------|---------|----------|
| New config flow step | `async_step_` method added to config_flow.py | high |
| New domain coordinator | New file in `domain_coordinators/` | significant |
| New entity platform | New platform file (sensor.py, switch.py, etc.) | significant |
| Signal/dispatcher change | `SIGNAL_` constant added/modified | high |
| New config entry type | `ENTRY_TYPE_` constant added | high |

### 4. Architecture & Service Boundaries

**What:** New modules, coordinator interactions, cross-coordinator signals.
**Why it matters:** Architecture decisions compound. Early choices constrain years of future development.

| Signal | Pattern | Severity |
|--------|---------|----------|
| New coordinator signal | `async_dispatcher_send` with new signal name | significant |
| Cross-coordinator dependency | One coordinator importing from another | significant |
| New scheduled task | `async_track_time_change` or `async_track_time_interval` | medium |
| New background task pattern | `hass.async_create_task` with sleep/delay | medium |

### 5. Safety & Security

**What:** Safety-critical code paths, hazard handling, alert severity.
**Why it matters:** Safety bugs are silent killers. Dead code in safety paths = unprotected users.

| Signal | Pattern | Severity |
|--------|---------|----------|
| Hazard type handling | `HazardType` enum usage | critical |
| Safety signal dispatch | `SIGNAL_SAFETY_HAZARD` | critical |
| Alert severity assignment | `severity.*CRITICAL` or `severity.*HIGH` | high |
| Observation mode gating | `observation_mode` check added/modified | high |

## Severity Levels

| Level | Meaning | Counseling Behavior |
|-------|---------|-------------------|
| `critical` | Safety vulnerability or irreversible data loss risk | Always counsel |
| `high` | Hard-to-reverse architectural decision | Always counsel |
| `significant` | Load-bearing decision with downstream effects | Counsel when active |
| `medium` | Notable choice with alternatives worth considering | Counsel when active |
| `low` | Minor decision, mostly informational | Log only |
