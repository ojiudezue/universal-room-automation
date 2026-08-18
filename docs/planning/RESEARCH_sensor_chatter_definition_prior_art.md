# RESEARCH: Grounding a Definition of "Sensor Chatter / Flap" in Prior Art

**Status:** Research (unshipped). No version number.
**Author:** Oji Udezue
**Date:** 2026-08-18

## Purpose & the hard requirement

URA wants to quarantine (temporarily untrust) an input sensor that is
"chattering" / "flapping" / "babbling" — emitting state transitions so
fast that the signal is noise, not information. The operator's hard
constraint:

> The quarantine criterion must be one a **CORRECTLY-WORKING sensor
> CANNOT satisfy.** Quarantining on it must never wrongly untrust a
> sensor that is merely legitimately busy.

This reframes the whole problem. Most "flap detection" in the wild is a
**rate / frequency heuristic** — "too many changes in a window." A rate
heuristic is *fakeable*: a genuinely busy-but-healthy sensor (a hallway
PIR during a party, a door contact during move-in) trips it. Rate
heuristics are therefore disqualified as a **sole** quarantine trigger.

What we need instead are criteria grounded in a **physical or protocol
floor** the hardware cannot cross when working correctly:

- **Sub-hardware-dwell:** a transition arriving faster than the device's
  own minimum inter-transition interval (blind time / off-delay /
  debounce floor). A correct unit *physically cannot* re-fire that fast.
- **Protocol / rate-ceiling violation:** a node transmitting outside the
  time budget its protocol allocates it. By construction it cannot exceed
  its slot when working.
- **Duty-cycle physical impossibility:** sustained emission above a
  hardware-imposed duty ceiling (e.g. a battery Zigbee PIR's mandatory
  cooldown), which a correct unit is built to never exceed.

This doc surveys six established fields, extracts each one's
definition + detect→suppress→recover mechanism, and — critically —
labels each criterion **UN-FAKEABLE** (physics/protocol floor) or
**HEURISTIC** (rate threshold a busy healthy unit can trip). It then
synthesizes a URA definition built **only** from un-fakeable criteria,
using BGP's penalty/decay machinery purely for the *auto-release*
schedule (not as the trust trigger).

---

## Per-domain findings

### 1. BGP Route-Flap Damping (RFD) — RFC 2439

**(a) Definition.** A route "flaps" when a prefix is repeatedly withdrawn
and re-advertised. Each flap adds a fixed **penalty** to a per-prefix
"figure of merit" (FOM).

**(b) Detect→suppress→recover mechanism (the canonical model):**
- **Penalty per flap** — default 1000 added on each withdrawal/change.
- **Exponential decay** — the FOM decays continuously with a configurable
  **half-life** (default **15 min**): stability bleeds the penalty away.
- **Suppress-threshold** — when FOM crosses the cutoff (default **2000–3000**,
  range 1–20000) the route is **suppressed** (quarantined).
- **Reuse-threshold** — when the decaying FOM falls back below this
  (default ~750) the route is **released** and used again.
- **Max-suppress-time** (T-hold) — a hard cap on suppression regardless of
  how high the FOM climbed, so a route can't be stuck forever.

This maps **directly** onto sensor quarantine: penalty = chatter event,
suppress-threshold = quarantine, reuse-threshold + half-life =
auto-release schedule, max-suppress-time = safety cap.

**(c) Un-fakeable? NO — HEURISTIC.** The penalty accrues on *raw event
rate*. A genuinely, legitimately frequently-changing route accrues
penalty identically to a broken one and gets damped. This is not
hypothetical: **RIPE-378 (2006) recommended disabling RFD** because
default parameters suppress *well-behaved, stable* prefixes — BGP's own
"path hunting" amplifies a single real flap into many updates that
falsely trip suppression (Mao et al., SIGCOMM 2002, "RFD Exacerbates
Internet Routing Convergence"). RIPE-580 later re-tuned rather than
re-enabled it. **This is the cautionary archetype:** a pure penalty/rate
model *does* wrongly punish the busy-but-healthy. Borrow its
release *schedule*, never its trigger.

**Cites:** https://www.rfc-editor.org/rfc/rfc2439.html ·
https://www.ripe.net/publications/docs/ripe-580/ ·
http://conferences.sigcomm.org/sigcomm/2002/papers/routedampening.pdf ·
https://www.noction.com/blog/bgp-dampening

---

### 2. CAN bus "Babbling Idiot" + Bus Guardian / TTCAN

**(a) Definition.** A "babbling idiot" is a node that transmits
**unscheduled traffic outside its allotted time**, consuming bus resource
and starving correct nodes. The fault is defined by transmission
*outside the node's time budget*, not by raw volume.

**(b) Detect→suppress→recover.** A **bus guardian** is an independent
watchdog that knows each node's schedule; it **physically gates the
node's bus access** to its assigned window and silences transmission
outside it. In **TTCAN (time-triggered CAN)** every message owns an
**exclusive time window inside a basic cycle**; a node may only transmit
in its slot. Even for event-triggered CAN, the guardian *derives a window
from the message schedule* and cuts off out-of-window transmission. Fault
containment is *bounded by construction* — the guardian guarantees a
babbler cannot cause a timing failure elsewhere.

**(c) Un-fakeable? YES — PROTOCOL RATE-CEILING.** The ceiling is derived
from the **communication schedule** (the design-time TDMA allocation /
message period). A correctly-working node, by protocol, transmits only in
its slot; exceeding it is definitionally a fault. The ceiling is not a
tuned "seems too fast" number — it is the node's *own contracted budget*.
This is the model for "a correct unit cannot exceed its rate by design."

**Cites:** https://www.researchgate.net/publication/4232497 (Overcoming
Babbling-Idiot Failures in the FlexCAN Architecture: A Simple
Bus-Guardian) · https://www.semanticscholar.org/paper/38d012a12c3ca9c5c6e3182c5e45f49d7414c23d
(Broster & Burns, The Babbling Idiot in Event-Triggered Real-Time Systems)

---

### 3. Digital-input debounce / glitch filter / Schmitt-trigger hysteresis

**(a) Definition.** A "glitch" / "bounce" is a transition **shorter than
the minimum valid pulse width** — a mechanical contact bounce or a
sub-bit voltage spike. It is defined by *duration below a physical floor*,
not by how many arrive.

**(b) Detect→suppress→recover.**
- **Minimum-pulse-width / dwell-time filter:** a pulse narrower than the
  configured minimum width is rejected outright; only pulses that *persist*
  past the dwell threshold propagate (NI DAQ digital filtering: a pulse
  must exceed the minimum-pulse-width setting to pass).
- **Schmitt-trigger hysteresis:** upper and lower thresholds the signal
  must fully traverse to flip state; narrow/noisy excursions that don't
  cross both bands produce no transition. Self-recovering — the next
  clean, wide pulse passes normally. No quarantine latch needed.

**(c) Un-fakeable? YES — SUB-HARDWARE-DWELL.** A transition faster than
the device's physical settling/pulse-width floor is *not a real state
change*; no correctly-working source produces it. The minimum is derived
from **the datasheet** (contact bounce spec, min pulse width) or
**measured** on the bench. This is the purest un-fakeable criterion:
"shorter than physically possible ⇒ noise."

**Cites:** https://documentation.help/NI-DAQmx-Device-Considerations/digFiltMSeries.html ·
https://patents.google.com/patent/US6529046B1/en

---

### 4. Nagios / Icinga flap detection

**(a) Definition.** A host/service "flaps" when it changes state too often
over recent history. Concretely: store the last **21 check results**,
count state transitions, weight recent ones more, compute a
**percent-state-change**.

**(b) Detect→suppress→recover (hysteresis-banded).**
- Start flapping when **%-state-change ≥ high threshold (default 30%)**.
- Stop flapping when it falls **< low threshold (default 25%)**.
- The two-band gap is deliberate hysteresis so it can't rapidly toggle
  the flapping/not-flapping status itself.
- While flapping, notifications are suppressed; recovery is automatic when
  the percentage drops.

**(c) Un-fakeable? NO — HEURISTIC (the counter-example to document).**
"%-state-change > threshold" is *purely a rate measure over history*. A
**busy-but-healthy** host that legitimately oscillates (a load-sensitive
service, a genuinely intermittent-by-design signal) trips it exactly like
a broken one. Nagios *itself* treats flap detection as advisory
(suppress *notifications*, not *trust the data*), which is the right
posture for a heuristic. **URA lesson:** a %-state-change / N-window rate
must NEVER be the *sole* quarantine (trust-removal) trigger. At most it is
a corroborating signal or a notification-dampener.

**Cites:** https://assets.nagios.com/downloads/nagioscore/docs/nagioscore/3/en/flapping.html ·
https://icinga.com/docs/icinga1/latest/en/flapping.html

---

### 5. Wireless-Sensor-Network fault taxonomies (academic)

**(a) Definitions.** The literature splits faults on two axes:
- **Time-based:** permanent / **intermittent** / transient.
- **Characteristic-based (data-value):** **stuck-at** (variation = 0),
  offset/bias, gain, **spike** (rate-of-change exceeds physical trend),
  noise (variance inflation), out-of-bounds, data-loss, hardover, drift,
  erratic.

A **chattering / babbling / erratic** sensor sits at the intersection of
*intermittent* (time) and *spike/erratic* (value): rapid, repeated,
physically-implausible excursions. A **healthy noisy** sensor differs by
staying *within* the physically plausible rate-of-change and bounds — its
noise has a bounded floor, it does not violate physical limits.

**(b) Detect→suppress→recover.** Mostly *classification*, not quarantine:
SVM / Random-Forest / CNN / extremely-randomized-trees classifiers label
each sample (gain/offset/spike/stuck-at/…). A minority of detectors key on
**physical impossibility** — e.g. rate-of-change exceeding the sensed
quantity's maximum physical slew, or **inter-arrival below the hardware
sampling limit** — rather than on learned rate.

**(c) Un-fakeable? SPLIT.** The *classifier* approaches are heuristic
(learned thresholds). The **physical-limit** detectors are un-fakeable:
"observed slew exceeds the physical maximum for this quantity" or
"inter-arrival below the hardware sampling floor" cannot be produced by a
correct unit. **Lesson for URA:** prefer the physical-impossibility framing
(spike = rate-of-change beyond physical limit; babble = inter-arrival below
hardware floor) over the ML-classifier framing.

**Cites:** https://pmc.ncbi.nlm.nih.gov/articles/PMC9415276/ (Fault
Tolerance Structures in WSNs: Survey & Classification) ·
https://www.mdpi.com/1424-8220/19/7/1568 (Fault Detection via Random
Forest) · https://arxiv.org/html/2511.17537v1 (HiFiNet)

---

### 6. PIR / motion-sensor hardware floors + Zigbee/Z-Wave throttling

**(a) Definition.** A PIR that re-asserts faster than its **hardware
re-trigger blind time** is not seeing new motion — it is chattering /
faulting. The floor is a real, spec'd hardware property.

**(b) The physical floors (the un-fakeable inter-transition minimum):**
- **Blind / blocking time (Tx):** after asserting, the sensor is
  *physically blind* and will not re-transmit for a fixed interval
  (commonly **~30 s** on battery Zigbee PIRs; trimpot-settable on bare
  modules). It *cannot* re-fire inside this window.
- **Off-delay / cooldown (Ti):** OUT stays high for a hold time; in
  retrigger mode each new motion extends it — so a *shorter*-than-hold
  OFF→ON→OFF cycle is impossible from real motion.
- **Warm-up:** 30–60 s after power-up the output is unstable and must be
  ignored (boot-transient, not chatter — URA already has boot-settle gates,
  cf. v4.7.21).
- **Zigbee/Z-Wave "chatty device" throttling:** battery devices enforce a
  **minimum report interval** (cooldown ≥ 60 s common) to save battery —
  a report cadence *below* the device's declared minimum-reporting-interval
  is a protocol violation, not real activity.

**(c) Un-fakeable? YES — SUB-HARDWARE-DWELL + DUTY-CYCLE FLOOR.** A
transition arriving inside the device's blind time / below its declared
min-report-interval **cannot** come from a correctly-working unit — the
hardware is physically incapable of it. The floor is sourced from the
**device-class datasheet** (blind time, off-delay) or the **Zigbee
reporting configuration** (min interval).

**Cites:** https://community.home-assistant.io/t/motion-sensor-pir-retriggering-time-problem/183095 ·
https://www.tweaking4all.com/hardware/pir-sensor/ ·
https://community.home-assistant.io/t/any-zero-cooling-timeout-motion-sensor-out-there/381308

---

## The core separation: UN-FAKEABLE vs HEURISTIC

| Domain | Definition of flap/chatter | Detect→suppress→recover | Criterion type | Un-fakeable by a healthy-but-busy unit? |
|---|---|---|---|---|
| **BGP RFD** (RFC 2439) | Repeated withdraw/re-advertise; penalty per flap | penalty +decay(half-life) → suppress-thresh → reuse-thresh; max-suppress cap | **HEURISTIC (rate)** | **NO** — RIPE-378: damps stable routes. *Cautionary archetype.* |
| **CAN babbling idiot** / TTCAN | Transmit outside allotted time budget | bus guardian gates to schedule slot; TTCAN exclusive windows | **UN-FAKEABLE (protocol rate-ceiling)** | **YES** — ceiling = node's own contracted TDMA slot |
| **Digital debounce / glitch filter** | Pulse shorter than min valid width | min-pulse-width/dwell filter; Schmitt hysteresis; self-recovers | **UN-FAKEABLE (sub-hardware-dwell)** | **YES** — shorter than physically possible ⇒ noise |
| **Nagios/Icinga** | %-state-change over last 21 checks | high(30%)/low(25%) hysteresis band; suppress notifications | **HEURISTIC (rate)** | **NO** — busy host trips it. *Counter-example.* |
| **WSN fault taxonomy** | chatter = intermittent × spike/erratic | ML classifier (heuristic) OR physical-limit detector | **SPLIT** | classifier NO; physical-slew / sub-sample-interval detector YES |
| **PIR / Zigbee** | Re-assert faster than blind time / min-report-interval | hardware blind time, off-delay, warm-up; Zigbee min-interval | **UN-FAKEABLE (sub-dwell + duty-cycle floor)** | **YES** — hardware physically cannot re-fire that fast |

**Un-fakeable family (safe as a sole quarantine trigger):**
1. **Sub-hardware-dwell** — a transition inside the device's minimum
   inter-transition interval (debounce floor, PIR blind time, off-delay).
2. **Protocol / rate-ceiling violation** — cadence above the device's
   contracted budget (TTCAN slot; Zigbee declared min-report-interval).
3. **Duty-cycle physical impossibility** — sustained emission above a
   hardware duty ceiling the device is built never to exceed.

**Heuristic family (MUST NOT be a sole quarantine trigger):**
- Raw event **rate** in a window (BGP penalty accrual).
- **%-state-change** over N transitions (Nagios).
- ML-classified "erratic" without a physical anchor.

These can *corroborate* or *dampen notifications*, but a busy-but-healthy
sensor trips every one of them — exactly the mis-quarantine the operator
forbids.

---

## Proposed definition: URA input-sensor chatter

> **A URA input sensor is *chattering* iff it produces a state transition
> whose interval since the previous transition is BELOW that sensor's
> physical minimum inter-transition floor `T_floor` — i.e. a transition
> the correctly-working device is physically/protocol-incapable of
> producing.** Rate and %-state-change are NEVER the trigger; they may
> only corroborate an already-established sub-floor violation.

A single sub-floor transition is an *impossibility event*, not merely
"fast." Because the trigger is defined against a physical floor, **a
legitimately busy sensor cannot satisfy it** — the party-hallway PIR still
honours its 30 s blind time; the move-in door contact still honours its
debounce floor. This is the operator's hard requirement, met by
construction.

### Sourcing the per-sensor floor `T_floor` (ladder, most-authoritative first)

1. **Device-class default off-delay / blind time** — from the HA
   `device_class` (motion, occupancy, door, window …). Ship a conservative
   built-in table (e.g. PIR motion ≈ 20–30 s blind time, contact debounce
   sub-second) as a **module constant** (`SENSOR_CHATTER_FLOOR_S` by device
   class, per "Numbers Get Knobs" rung 1 — a safety bound that should
   require review to change).
2. **Datasheet / manufacturer spec override** — where a specific device's
   blind time or Zigbee **min-report-interval** is known, use it. Exposed
   as a per-sensor config-flow field (rung 2) for the rare device whose
   floor differs from its class default. Zigbee reporting config is the
   authoritative protocol-ceiling source when available.
3. **Learned `p-low` inter-arrival from recorder history** — for a sensor
   with no reliable spec, mine ≥24 h of the HA recorder for the
   **empirical low percentile (e.g. p1–p5) of inter-transition intervals**
   and set `T_floor` a safety-margin below it. This is a *measure-before-you-
   build* probe (per CLAUDE.md), hand-verified against a few live devices
   before automating, and re-derived rarely. Guardrail: never learn a floor
   from a window in which the device was *already* suspected faulty (poisons
   the fixture) — anchor learning to a known-healthy span.

`T_floor = 0` (or unset) = **kill switch**: the sensor is exempt from
chatter quarantine (documented on the knob, per kill-switch-semantics rule).

### Auto-release: BGP-style penalty/decay, but gated on the un-fakeable trigger

The *trigger* is un-fakeable (sub-floor). The *release schedule* borrows
RFD's proven machinery — but penalty accrues **only** on sub-floor
impossibility events, never on raw rate:

- **Penalty** `+P` on each sub-`T_floor` transition (an impossibility event).
- **Exponential decay** of the penalty with a configurable **half-life**
  (start ~15 min, RFD default) so a device that recovers bleeds its penalty
  and is trusted again automatically.
- **Suppress-threshold** → sensor enters **quarantine** (URA untrusts its
  contribution to the occupancy substrate; siblings carry the room).
- **Reuse-threshold** (below suppress, hysteresis gap) → sensor
  **auto-released** once decay carries it back down after a quiet span.
- **Max-suppress-time** cap → never latch a sensor off forever; force a
  re-trust attempt.

This gives the requested detect→suppress→auto-recover loop with the RFD
release ergonomics **without** RFD's fatal flaw, because the penalty can
only be earned by physically-impossible transitions — a busy-but-healthy
sensor earns zero penalty and is never quarantined.

### Why this satisfies the operator's constraint (discriminating criterion)

- **Under the fix (real chatter):** a faulting PIR re-fires inside its
  20–30 s blind time → sub-floor events accrue penalty → crosses
  suppress-threshold → quarantined → decays → auto-released. Observable:
  penalty sensor climbs, quarantine flag sets, sub-floor event count > 0.
- **Under a plausible different failure (busy-but-healthy):** a hallway PIR
  fires every 25 s during a party — *above* its 20 s floor → **zero**
  sub-floor events → **zero** penalty → **never quarantined**. Observable:
  transition rate high, sub-floor event count == 0, quarantine flag clear.

The two scenarios produce **different** observations (sub-floor event
count is the discriminator), satisfying the "acceptance criteria must
discriminate" rule. A design that quarantined on rate would make these two
identical — which is precisely the forbidden mis-quarantine.

### Non-goals / open items for a planning cycle

- This is a *definition*, not a build. Producer/consumer wiring into the
  occupancy substrate + trust hierarchy is a separate planning doc.
- `T_floor` device-class defaults table needs values validated against
  URA's actual PIR/contact fleet (measure-before-build probe).
- Interaction with existing boot-settle gates (warm-up transients must be
  excluded from penalty, per §6) must be specified.
- Penalty/half-life/threshold defaults are knobs; pick rungs per "Numbers
  Get Knobs" (safety floor = module constant; operator-tunable release
  schedule = entity).

---

## Sources

- RFC 2439 — BGP Route Flap Damping: https://www.rfc-editor.org/rfc/rfc2439.html
- RIPE-580 (recommendations on RFD): https://www.ripe.net/publications/docs/ripe-580/
- Mao et al., "RFD Exacerbates Internet Routing Convergence" (SIGCOMM 2002): http://conferences.sigcomm.org/sigcomm/2002/papers/routedampening.pdf
- Noction, "BGP Dampening: obsolete or still used": https://www.noction.com/blog/bgp-dampening
- FlexCAN Bus-Guardian (babbling-idiot): https://www.researchgate.net/publication/4232497
- Broster & Burns, "The Babbling Idiot in Event-Triggered Real-Time Systems": https://www.semanticscholar.org/paper/38d012a12c3ca9c5c6e3182c5e45f49d7414c23d
- NI-DAQmx digital filtering (min pulse width): https://documentation.help/NI-DAQmx-Device-Considerations/digFiltMSeries.html
- US6529046B1 (minimum pulse width detect/regenerate): https://patents.google.com/patent/US6529046B1/en
- Nagios flap detection: https://assets.nagios.com/downloads/nagioscore/docs/nagioscore/3/en/flapping.html
- Icinga flap detection: https://icinga.com/docs/icinga1/latest/en/flapping.html
- WSN fault-tolerance survey/classification: https://pmc.ncbi.nlm.nih.gov/articles/PMC9415276/
- WSN fault detection via Random Forest: https://www.mdpi.com/1424-8220/19/7/1568
- HiFiNet (hierarchical WSN fault ID): https://arxiv.org/html/2511.17537v1
- PIR retrigger/blind-time (HA community): https://community.home-assistant.io/t/motion-sensor-pir-retriggering-time-problem/183095
- PIR sensor behavior (Tweaking4All): https://www.tweaking4all.com/hardware/pir-sensor/
- Zigbee motion cooldown/throttling (HA community): https://community.home-assistant.io/t/any-zero-cooling-timeout-motion-sensor-out-there/381308
