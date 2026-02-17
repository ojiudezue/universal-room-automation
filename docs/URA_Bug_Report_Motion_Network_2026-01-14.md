# URA Bug Report & Improvement Request (Revised)

**Date:** January 14, 2026  
**Version:** 3.3.5.4  
**Reporter:** Oji

---

## 🔴 Critical Bug: Spurious Motion Activations & Failed Auto-Shutoff

### Problem Statement
Upon waking, lights are found on in unoccupied rooms where motion-triggered automation should have deactivated them hours ago. No one has entered these rooms, yet they remain in active state indefinitely.

### Observed Behavior
- Wake up to find lights on in empty rooms
- Lights appear to have been on for extended periods (multiple hours)
- Rooms are motion-activated but show no recent occupancy
- No manual intervention occurred to activate these rooms

### Two-Dimensional Problem

#### Dimension 1: Spurious Motion Triggers
**Hypothesis:** False positive motion detection causing inappropriate activations

**Potential Sources:**
1. **Sensor hardware issues**
   - mmWave sensor false positives (environmental interference, HVAC vibrations)
   - PIR sensor drift or electrical noise
   - Zigbee2MQTT event entity triggering on noise/reconnections
   
2. **Environmental factors**
   - Pets/animals triggering sensors
   - Shadows from outdoor light changes (sunrise/sunset)
   - HVAC airflow patterns affecting sensors
   - Temperature changes causing IR sensor false positives

3. **Network/integration artifacts**
   - Zigbee network congestion causing duplicate events
   - Sensor reconnection events misinterpreted as motion
   - Event entity state changes without actual motion (similar to person sensor staleness)
   - Delayed message delivery creating phantom activations

4. **Multi-sensor fusion issues**
   - Conflicting signals from multiple motion sensors
   - Bermuda BLE triangulation creating false presence signals
   - Coordinator subscription receiving stale/repeated events

#### Dimension 2: Unreliable Shutoff Sequences
**Hypothesis:** Deactivation automation failing to execute after timeout

**Potential Failure Points:**
1. **Timer/timeout logic**
   - Hysteresis period not triggering properly
   - Timeout reset on spurious motion re-triggers
   - Clear condition never met due to sensor state issues

2. **Automation execution failures**
   - Network congestion preventing service calls (ties to network resilience issue)
   - Silent automation failures with no error logging
   - State machine stuck in occupied state
   - Coordinator not processing motion clear events

3. **State tracking issues**
   - Occupancy state not transitioning to unoccupied
   - Room entity not reflecting actual sensor state
   - Database occupancy events not closing properly
   - Multiple motion sensors preventing clear state (OR logic issues)

4. **Trigger pattern problems**
   - Deactivation trigger not firing on motion clear
   - Template conditions preventing shutoff execution
   - Event entity behavior not triggering state-based timeouts

### Debug Data Needed

#### For Spurious Triggers:
1. **Event log analysis**
   - Timestamp correlation: motion events vs light activations
   - Frequency distribution: which rooms, which sensors, what times
   - Pattern detection: environmental correlations (sunset times, HVAC cycles)

2. **Sensor health metrics**
   - Signal strength/quality for Zigbee sensors
   - Battery levels (if applicable)
   - Reconnection event frequency
   - Event duplicate detection

3. **Database query**
   ```sql
   SELECT room_name, event_type, timestamp, sensor_id
   FROM occupancy_events
   WHERE event_type = 'motion_detected'
     AND timestamp > datetime('now', '-7 days')
   ORDER BY room_name, timestamp
   -- Analyze gaps and anomalies
   ```

#### For Failed Shutoffs:
1. **Automation trace logs**
   - Last successful deactivation per room
   - Failed deactivation attempts (if logged)
   - Service call success/failure rates

2. **State transition tracking**
   - Room occupancy state changes
   - Motion sensor state history
   - Light entity state duration

3. **Coordinator status**
   - Active subscriptions per room
   - Event processing queue depth
   - Error/warning counts

### Proposed Solutions

#### Short-term Mitigations:
1. **Add comprehensive logging**
   - Log every motion detected/clear event with sensor ID and timestamp
   - Log every activation/deactivation attempt with success/failure
   - Track timeout periods and why they expire/reset

2. **Implement safety shutoff**
   - Maximum active duration (e.g., 2-4 hours) as failsafe
   - Automated alert when room exceeds expected occupancy duration
   - Manual override detection to prevent inappropriate shutoffs

3. **Sensor validation layer**
   - Require multiple sensor confirmations for activation (configurable)
   - Debounce rapid on/off events (< 30 seconds)
   - Ignore motion events during known false-positive periods

#### Long-term Solutions:
1. **Smart spurious trigger filtering**
   - Machine learning anomaly detection on motion patterns
   - Time-of-day probability scoring (unlikely motion at 3 AM)
   - Cross-sensor validation (motion without other corroborating data)
   - Bayesian confidence scoring before activation

2. **Reliable shutoff guarantee**
   - Implement network resilience layer (see enhancement below)
   - Dual-path deactivation: timeout-based AND explicit motion clear
   - State reconciliation loop checking for hung active states
   - Forced deactivation on sustained absence (database-confirmed)

3. **Enhanced hysteresis logic**
   - Variable timeout based on time of day (shorter at night)
   - Room-type specific timeouts (bathroom vs media room)
   - Occupancy history weighting (frequent use = longer timeout)
   - Multi-sensor consensus before timeout start

### Reproduction Steps
1. Enable detailed motion and automation logging
2. Monitor specific problem rooms overnight
3. Check room states upon waking
4. Correlate light state durations with motion event timestamps
5. Identify pattern: sensors involved, timing, environmental conditions

### Success Criteria
- Zero instances of lights on in unoccupied rooms for >30 minutes
- Motion-triggered activations only during verified occupancy
- 100% deactivation success rate within configured timeout period
- Clear audit trail for every activation/deactivation event

### Priority
**Critical** - Core functionality broken, wasting energy, indicates unreliable automation behavior that affects user trust in system

---

## 🟡 Enhancement: Network Resilience & Retry Logic

### Problem Statement
In congested network conditions with multiple concurrent broadcasts, automation calls may fail silently, leading to inconsistent room states and unreliable automation execution.

### Impact
- Music transfer failures between zones
- Entity state updates lost
- Automation triggers missed
- Cross-room coordination breaks down

### Requirements
1. **Guaranteed delivery** for critical automation calls
2. **Retry mechanism** with exponential backoff
3. **Failure detection** and alerting
4. **Graceful degradation** when network unavailable

### Proposed Implementation Approach

#### 1. Call Reliability Layer
```python
async def reliable_service_call(
    hass,
    domain: str,
    service: str,
    data: dict,
    max_retries: int = 3,
    timeout: float = 5.0
) -> bool:
    """Execute service call with retry logic"""
    # - Exponential backoff (1s, 2s, 4s)
    # - Timeout per attempt
    # - Success/failure tracking
    # - Error logging with context
```

#### 2. Network Health Monitoring
- Track failed call ratio per room/domain
- Detect congestion patterns (burst failures)
- Adaptive timeout adjustments
- Integration-level health metrics

#### 3. Critical vs Non-Critical Categorization
- **Critical:** Music transfer, security state changes, occupancy updates
- **Non-Critical:** Diagnostic sensors, statistics, low-priority updates
- Queue critical calls for guaranteed execution

#### 4. Broadcast Optimization
- Batch related entity updates into single calls
- Rate limiting for large sensor arrays (74 entities/room)
- Stagger updates across rooms to prevent congestion

### Priority
**High** - Production stability issue, affects reliability at scale

---

## 🟡 Known Issue: Music Transfer Brittleness

### Problem Statement
Music following functionality between WiiM media players experiences failures requiring manual intervention or integration reloads.

### Recent Context
- Already addressed in recent development sessions
- Related to zone management interface issues
- Person sensor staleness contributing factor

### Outstanding Work
- Continue platform-agnostic music transfer refinement
- Improve error recovery without reload requirements
- Add resilience to network-related failures (see above)
- Validate transfer completion before cleaning up source

### Priority
**Medium** - Active development area, partial solutions implemented

---

## 🟢 Enhancement: Digest Alert Mode

### Problem Statement
At scale (multiple rooms, 74+ entities per room), real-time alerts become spammy and unusable. Need intelligent aggregation for large URA instances.

### Requirements
1. **Configurable alert modes:** Real-time, Digest (hourly/daily), Critical-only
2. **Smart aggregation:** Group similar events, deduplicate redundant alerts
3. **Priority filtering:** Critical alerts break through digest mode
4. **Summary formatting:** Clear, actionable digest notifications

### Proposed Implementation

#### Configuration
```yaml
# Per-room or instance-wide
alert_mode: digest  # real_time, digest, critical_only
digest_interval: 3600  # seconds (hourly)
critical_bypass: true  # critical alerts always immediate
```

#### Digest Content
- Event counts by category (motion failures, network errors, etc.)
- Top 5 most frequent issues
- Critical events listed individually
- System health summary
- Action recommendations

#### Alert Categories
- **Critical:** Motion detection failures, security breaches, system offline
- **Warning:** Network retry exhaustion, sensor staleness, coordinator failures
- **Info:** Configuration changes, routine maintenance, statistics

### Benefits
- Reduced notification fatigue
- Better signal-to-noise ratio
- Scalable to dozens of rooms
- Historical problem pattern visibility

### Priority
**Medium** - Quality of life improvement, important for adoption at scale

---

## Recommended Development Order

1. **Add comprehensive logging to diagnose motion bug** (Immediate, information gathering)
2. **Implement safety shutoff as temporary mitigation** (Critical, prevents continued energy waste)
3. **Debug and fix spurious trigger root cause** (Critical, permanent fix)
4. **Implement reliable shutoff guarantee** (Critical, permanent fix)
5. **Add network resilience layer** (High, supports #4)
6. **Complete music transfer refinements** (Medium, active development)
7. **Add digest alert mode** (Medium, scaling enhancement)

---

## Testing Requirements

### Motion Bug Fix
- [ ] Manual testing with real motion sensors (5+ minute observation)
- [ ] Verify logs show motion clear events
- [ ] Test with multiple simultaneous motion events
- [ ] Validate timeout/hysteresis behavior
- [ ] Confirm coordinator subscription patterns

### Network Resilience
- [ ] Simulate network congestion (burst API calls)
- [ ] Test retry logic with forced failures
- [ ] Verify timeout handling
- [ ] Monitor performance impact of retry layer
- [ ] Validate critical vs non-critical prioritization

### Digest Alerts
- [ ] Test aggregation logic with synthetic events
- [ ] Verify critical bypass functionality
- [ ] Validate digest formatting and clarity
- [ ] Test configuration options
- [ ] Monitor memory/performance at scale

---

**Next Session Focus:** Enable detailed motion/automation logging and gather diagnostic data from overnight monitoring
