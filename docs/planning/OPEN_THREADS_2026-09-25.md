# Open Threads — 2026-09-25

**How to use:** each thread has an `> **ANSWER:**` line. Type inline, save, tell me "read the open
threads doc". Leave blank = no decision yet.

---

## 1. COVERAGE-RATING-FALSE-ANOMALOUS-1 — built, reviewed, awaiting deploy

### The problem
`sensor.*_energy_coverage_delta` publishes a `coverage_rating`. Live recorder evidence 2026-09-19:
`delta_percent` was **-635.30 at 22:56** (rated `INCOMPLETE`) and **-643.90 at 00:11** (rated
`ANOMALOUS`). The value barely moved; the **classification flipped** — purely because the
post-restart excuse window closed at local midnight.

Root cause: the in-memory tiers re-anchor **lazily** (`_maybe_reclassify_at_midnight` only *flags*
entries; the re-classify happens on each sensor's next read), so the negative-delta asymmetry
survives the midnight boundary by up to ~an hour. The old docstring asserted it "will converge at
next midnight re-anchor" — measurement falsified that. Secondary defect: the ANOMALOUS warning
asserted a unit-of-measurement mismatch **as fact** when the signature has more than one cause.

### The solution (`c5ea7dfc7` + fix-up `ca69d45c2`)
- New `COVERAGE_MIDNIGHT_REANCHOR_WINDOW_MIN = 120` (rung-1 module constant — sized from 10d of
  recorder history: midnight re-anchor ANOMALOUS runs ended by 01:20 local; the *separate* sustained
  evening-drift pattern never began before 14:00 local, so the window can't swallow it).
- `_get_coverage_rating` gains `midnight_reanchor_window`; the existing negative-delta excuse fires
  for **either** window. `>100` / `None` / `NaN` are still **never** excused.
- `midnight_reanchor_window` published as an attribute so live validation can **discriminate** a
  suppressed boundary artifact from a real mid-day ANOMALOUS.
- Warning text now reports what was observed and *names* candidates instead of diagnosing.
- **Deliberately NOT suppressed:** the sustained evening attribution drift (the majority of ANOMALOUS
  samples, a candidate real defect) keeps its signal. Carded separately as
  `COVERAGE-EVENING-ATTRIBUTION-DRIFT-1`.

### How it passed the gate
| Gate | Result |
|---|---|
| **Hollow-anchor fix** | `test_coverage_rating_bounds.py` loaded `aggregation.py` **without a parent package**, so its relative imports always raised and the **whole file silently skipped in every env** — the D3 bounds tests and the B-H4 post-restart test had **never executed**. Now imported as a package member: 1 skip → 31 passing. |
| **Wire-in anchor** | A mutation drill showed deleting the call-site argument left the helper tests green. That deletion now fails 2 tests. |
| **Review A** (local correctness) | SHIP, no CRIT/HIGH. Invariant held under falsification; discharge structural; consumer count re-grepped. Raised MEDIUM-1 (shared warn-throttle) + LOW-3. |
| **Review B** (test authority) | SHIP. 5 mutation drills; build *understated* its own coverage (4 red, not 2); discriminator proven non-tautological; time **injected**, not wall-clock. Raised a pre-existing HIGH → new card `TEST-SILENT-WHOLE-FILE-SKIPS-1` (10 never-executed tests elsewhere). |
| **Fix-up** | MEDIUM-1: split the shared throttle so a re-anchor warning at 00:05 can't swallow a genuine ANOMALOUS at 00:50. LOW-3: publish `midnight_reanchor_window` on the no-data early-return too. Reviewer-B LOW: added an **absolute 15:00-local** backstop test that does *not* read the constant, so widening it 120→900 can't leave the suite green. |
| **Orchestrator verify** | Diff re-read, **163 pass / 0 skip** (baseline 160), own mutation drill red-then-restored, `git status --porcelain` residue 0. |
| **Out of scope** (declared) | Review-A LOW-1 (DST fall-back lengthens the window) and LOW-2 (`-inf` via the negative branch, unreachable behind `whole_house > 0`). Constant `120` unchanged. |

> **ANSWER — deploy now?** (yes / hold / questions):
>

---

## 2. Camera fleet — CLOSED by operator

Operator 2026-09-25: *"the camera fleet is fine now. Frigate is having periodic degrades on the
hardware side that I am working on. The quick fix is a docker reload."*

→ The 74.7h one-instant fleet freeze is **explained** (Frigate hardware-side degrade, not 16 faults,
not a URA defect). I'll close `CAMERA-SILENT-PRODUCER-TRIPWIRE-1`'s freeze evidence as
attributed-and-owned-by-operator.

Two residuals that are still mine:

**2a. `FRONT-SIDE-PTZ-CHATTER-1`** — blocked on your answer, not on the freeze. The Sep-17 evidence
(which predates the freezes) stands; the re-measurement was only needed to discriminate an
individual camera fault from a fleet event. Given 2 above, a fleet event is now the better
explanation and the card can probably close.

> **ANSWER — close FRONT-SIDE-PTZ-CHATTER-1 as fleet-attributed?** (close / still investigate):
>

**2b. Should URA *detect* a fleet-wide silent producer?** A Frigate degrade currently goes unnoticed
until someone looks. A cheap trip-wire (all exterior detection producers silent > N hours → NM
notification) would tell you to docker-reload without you discovering it days later. Per *No Soak
Watching*, this is exactly the "trip-wire in code" shape. Tier 1-2.

> **ANSWER — build the fleet-silence trip-wire?** (yes / no / later):
>

---

## 3. Envoy — MEASURED. You were right: it is flapping.

### Measurement (read-only, recorder, run 2026-09-25)

`sensor.envoy_482543015950_battery`, all state changes (not significant-only), 2026-09-18 04:13 →
2026-09-20 19:10 local — the recorder returned **1000 state rows in 2.6 days** and the window filled
before exhausting retention.

| Local day | available↔unavailable transitions |
|---|---|
| 2026-09-18 | **220** |
| 2026-09-19 | **324** |
| 2026-09-20 | **223** |
| 2026-09-24 | **~246** (~123 down-events) |
| 2026-09-25 | **27 down-events by 09:40** (~2.8/hr → ~67/day pace) |

That is roughly **110-160 complete down/up cycles per day** — one every 5-10 minutes, all day,
every day, **unbroken across seven consecutive days with no recovery period at any point.**

*(The first query stopped at 09-20 only because the 1000-row API cap filled, not because the data
ended — your challenge was right. The 09-24→now re-query returned 418 rows with `has_more=false`,
so that window is complete, not truncated. Any future check must use a bounded window and confirm
`has_more=false`; a row cap on a 10-day request silently truncates and makes a still-flapping
integration look like it stopped.)*

Two things the fuller window adds:
- **Not correlated with battery activity.** 09-24 flapped continuously *through* the daytime charge
  (SOC 8→99, 09:20-16:29) and *through* the overnight discharge (99→10, 16:29-21:13). Constant
  background failure, consistent with a timer-driven background task — not load- or state-dependent.
- **Outage lengths are bimodal.** The large majority are 15s-10min, but 09-24 carried two long ones
  (15:07→16:29 = 82min; 23:02→23:51 = 49min) and the current one is open since 09:40. **The long
  tail is where SOC actually goes stale for URA.**

**This is not a rare hard failure. It is a continuous flap.** My prior handoff framed it as
"frozen / dead-until-restart", which understated it — flapping is the dominant mode, and the freeze
is where a flap fails to recover.

### Current state (2026-09-25)
- Config entry `01KNYRAGVP5XESS6N8PD6BVQP2` is back in **`setup_in_progress`** — the frozen state,
  i.e. the flap failed to recover again. Options carry `disable_keep_alive: true` (prior mitigation).
- `sensor.envoy_482543015950_battery` = `unavailable` since **09:40:57 today**.
- Live core log confirms the mechanism, repeating: `enphase_envoy/coordinator.py:201
  _async_try_refresh_firmware` → `pyenphase/envoy.py:233 setup` → `pyenphase/firmware.py:123 setup`
  → `firmware.py:81 _get_info`. This is the **second** unguarded background task from upstream bug
  **#181243** (the first, `_async_fetch_and_compare_mac`, was what we caught on 09-19).
- URA degrades gracefully — `energy_battery` holds state; no URA defect in the loop.
- Separate benign artifact: `consumption_today` = **28,999 kWh** (99.8% off) → URA's cross-check
  WARN. Already recorder-excluded; URA holds state.

### Mechanism, stated falsifiably
Upstream #181243 (OPEN, affects core 2026.8.3 **and 2026.9.0** = your version; no fix merged):
`_async_try_refresh_firmware` and `_async_fetch_and_compare_mac` run unguarded, so a
`RuntimeError: Session is closed` **escapes** the task. Each escape kills the coordinator's refresh
→ entities go `unavailable` → HA retries → sometimes recovers (a flap), sometimes doesn't (the
freeze). Prediction this makes: flap frequency should track how often those two tasks fire, and the
only true cure is upstream or a local core patch. `disable_keep_alive` reduces the session-close
rate but cannot eliminate it.

### Your question: "I think we said we need to reboot the HA host?"
**I can't confirm that — and I don't want to fabricate it.** What the record shows is an HA **core
restart** on 2026-09-19 (which moved the entry `setup_in_progress` → `setup_retry`, an improvement
that has since regressed). I have **no record of a host-reboot decision.** My read: a host reboot is
unlikely to help, because the failure is a Python exception escaping a task inside the core
container, not an OS/network-stack condition — a core restart reaches it and a host reboot adds
nothing but downtime.

What would *actually* move it, in order of value:

### ⭐ UPSTREAM STATUS — RESOLVED QUESTION: the fix exists and is ONE RELEASE away

Verified via the GitHub API this session (not recalled). **This supersedes the 09-21 "no fix exists,
track it indefinitely" read.**

| Thing | Version | Date |
|---|---|---|
| **We run** | core **2026.9.2** → pins `pyenphase==4.0.3` | 09-11 |
| Latest stable | core **2026.9.3** → **still pins `4.0.3`** | 09-18 |
| The fix | pyenphase PR **#503** → released **v4.0.5** | 09-16 |
| Fix reaches core | PR **#182473**, merged to dev, **milestone 2026.9.4** | 09-17 |
| core dev now | pins `4.0.6` (PR #183094) | 09-25 |

**Two consequences that change the decision:**
1. **Updating to 2026.9.3 would buy nothing** — it carries the same unfixed `4.0.3`. Worth knowing
   before anyone "just updates HA."
2. **The fix lands in 2026.9.4, which is not yet released.** So the wait is *one patch release*, not
   an unbounded upstream vigil.

A trap worth recording: **issue #181243 is still OPEN** (17 comments) even though its fix has merged.
Reading the issue state alone would conclude "no fix exists." The library release + the core manifest
pin are the authoritative signals. (Also checked and discarded: core #125418 "Envoy frequently
returns Unavailable" is a 2024.9-era HTTPX-timeout issue, closed — different mechanism.)

### URA interaction — exonerated, by procedure not analogy

You asked whether URA is causing this. It is not, and here is the evidence rather than an assurance:
- **No network access to the Envoy from URA at all** — zero hits for `192.168.12.191`, `envoy.local`,
  `pyenphase`, `httpx`, `requests`. The only `aiohttp` use in the package is the Frigate snapshot
  proxy (`perimeter_alert.py:3594-3604`).
- **No service call into the `enphase` domain.**
- **URA never reloads the Envoy config entry.** Every reload site was opened individually:
  `switch.py:686/697` iterate `async_entries(DOMAIN)` and reload only URA's own INTEGRATION entry;
  `hvac.py:5453` does call `homeassistant.reload_config_entry` but is scoped to a resolved
  `ha_carrier` entry *and* carries a guard refusing to proceed if the resolved entry is URA's own.
- **URA's entire consumption is passive state reads** — `hass.states.get` at `energy.py:3022` and
  `energy_const.py:1445`. Those read the HA state machine and put **zero load on the Envoy local API**.
- **Independent corroboration:** 09-24 flapped straight through a full charge *and* a full discharge.
  A URA-driven cause would have to be uncorrelated with URA's own energy activity — the opposite of
  causal coupling.

### ⛔ The contention hypothesis is REFUTED — and the add-on has one wrong field

You asked me to check the MQTT add-on. Doing so **killed my own hypothesis from two hours ago.**

**`ENVOY_HOST` is set to `192.168.13.118`, which does not exist.** From the HA host: ping =
100% packet loss, `curl https://192.168.13.118/info` = no response, and the address isn't even in the
ARP table (neighbours `.116` and `.119` are). Meanwhile `192.168.12.191` answers **HTTP 200 in 0.41s**
and reports `sn=482543015950` — matching our `sensor.envoy_482543015950_*` namespace, so provably the
same Envoy (`pn 800-00663-r05`, firmware **D8.3.6087**).

So the add-on has been in `error` state with `watchdog: true`, restart-looping, **publishing nothing
since install.** And therefore: **it cannot be contending for the Envoy local API, because it has
never connected to it.** That's a refutation, not a weakening — and it removes part of the
justification for the investigation I proposed. Carded as `ENVOY-MQTT-ADDON-WRONG-HOST-1`.

**Everything else checks out against the upstream repo** (`vk2him/Enphase-Envoy-mqtt-json`):

| Setting | Verdict |
|---|---|
| `ENVOY_HOST: 192.168.13.118` | ❌ **the one wrong field** → should be `192.168.12.191` |
| `ENVOY_USE_HTTPS: true` | ✅ **required for us** — repo notes FW D8.3.5286+ removed the non-SSL port-80 endpoints; we're on D8.3.6087 |
| `BATTERY_INSTALLED: true` | ✅ correct and supported (repo: FW7/FW8 only; we're FW8 with Encharge) |
| `MQTT_HOST: 192.168.13.13` | ✅ HA itself |
| `ENVOY_USER` / `ENVOY_USER_PASS` | ✅ correct — FW7/8 downloads a token from Enphase on every start |
| `ENVOY_PASSWORD: "envoy.password"` | ⚠️ literal placeholder, but this field **isn't in the repo's settings table at all** — legacy/unused, harmless, not the failure |

**Second-order effect worth stopping on its own:** because the token is fetched from the Enphase
*cloud* on every start, and the watchdog restarts a failing add-on forever, this misconfiguration is
running a **repeating cloud-auth loop against Enlighten**.

> **ANSWER — fix `ENVOY_HOST` to `192.168.12.191` and restart the add-on, or remove the add-on?**
> (it produces nothing either way today; on a fix I'll verify the topic actually publishes):
>

*(Minor, unrelated: the add-on options store the Enlighten account password in plaintext, and it's
the same string as the MQTT and Samba passwords. Normal for add-on storage; flagging only because
the Enlighten one is an internet-facing account.)*

### The original contention candidate — now closed out

Confirmed: HA is **quad-homed** — `enp4s0` 192.168.13.13 plus sub-interfaces `enp4s0.2` 192.168.15.13,
`enp4s0.3` 192.168.8.13, `enp4s0.5` 192.168.12.13 (the Envoy's subnet). The `enphase_ev` cloud
integration remains a separate consumer but talks to Enphase's cloud, not the local Envoy.

**What I now expect the dual-homed investigation to find — asked and answered honestly:**

You asked what I expect. The honest answer is **less than I implied when I proposed it**, and the
add-on check above is why. My reasoning then was: multiple local clients + multi-homing ⇒ plausible
local-API contention raising the session-close rate. Two of those three legs have since fallen:

- The second local client **never connected** (refuted above).
- The Envoy answers `/info` in **0.41s** from the HA host on the configured path — no sign of a
  congested or marginal local API.
- And you've added the strongest datum: **the Enphase app sees the Envoy fine.**

So my genuine prediction is now: **I expect to find nothing actionable.** The most likely result is
"HA routes to 192.168.12.191 via `enp4s0.5`, single path, no contention" — which changes no decision,
because the cure is already identified and dated (2026.9.4). That makes it a **low-value** use of the
time, and I'd be rationalising if I kept recommending it at the priority I gave it an hour ago.

**Revised recommendation: drop B from the critical path.** The one thing that *would* justify running
it is if flapping persists after 2026.9.4 lands — at that point a network-side contributor becomes
the live hypothesis again and the investigation has a real question to answer. Parked with that
trigger rather than dropped.

### Options, re-priced against the above

| Option | Effect | Cost / risk |
|---|---|---|
| **C′. Update to 2026.9.4 when it lands** ⭐ | **The real cure, now bounded to one patch release.** | Short wait. **Do NOT update to 2026.9.3 expecting relief** — same unfixed pin. |
| **A. Local core patch** (wrap the two tasks / vendor `pyenphase` 4.0.5) | Closes the gap *today* instead of waiting. | Lives in the container; **lost on every core update**. Only worth it if the wait is intolerable — and it now bridges days, not months. |
| **B. Dual-homed + second-client investigation** (your lead, now sharper) | May cut the session-close *rate* independent of the library fix; also covers the MQTT add-on. | Read-only, cheap, **still un-run**. Complements C′ rather than competing with it. |
| **D. Nothing** | — | **Weaker than it looked this morning:** seven days, no self-recovery, and the long-tail outages (82min, 49min) are exactly when battery strategy runs on stale SOC. Your "we cannot manage the energy system effectively this way" is the correct read. |
| **E. Host reboot** | Not indicated. | Mechanism is inside the core container; a Core restart already reaches it. |

**My recommendation:** **C′ + B** — take the bounded wait for 2026.9.4 as the cure, and let me run B
now (read-only, no risk) since it's the one thing that could reduce the flap rate independently *and*
it checks the second-client hypothesis your hardware restart won't settle.

> **ANSWER — which of C′ / A / B / D / E?** (multiple allowed; B costs you nothing):
>
> **ANSWER — want me to also set a watch so you're told the moment 2026.9.4 is available?**
>

### Note on your Envoy hardware restart

Worth setting expectations: the hardware restart will clear the *current* stuck entry and any
device-side condition, but the mechanism above is a Python exception escaping a background task
**inside HA**, so a healthy Envoy will still be flapped by it. If flapping resumes at a similar rate
within a day of the restart, that is the predicted outcome and confirms the library diagnosis rather
than indicating the restart failed. I'll re-measure transitions afterward to check — that is a
**discriminating** observation: sharply reduced rate ⇒ a device-side contributor existed; unchanged
rate ⇒ purely the pyenphase bug.

---

## 4. Jev decision-classifier spike — blocked on you

Harness ran, but hit **label leakage**: the labels were derived from the classifier's own inputs
(`persons_in_house` / `sensors_on`), so 100% / 88.9% accuracy is meaningless. Verdict INCONCLUSIVE.
Needs an **independent** occupancy truth source before re-running. No URA behavior change either way
— this is pure measurement.

Candidate disjoint source: recorder + operator-confirmed episodes (e.g. Jaya empty 2026-09-18
17:44-19:26).

> **ANSWER — provide labels / approve the recorder+confirmed-episodes source / park the spike?**
>

---

## 5. HVAC conditioning-demand step-4-B — blocked on a policy call

On `feature/hvac-conditioning-demand`. **Daytime path clean. Night-trust path fails review** on
three counts: D9 defeats the backstop at the setpoint layer; the throttle strands; establishment is
permanently-off on a disabled room. Recommendation: **DECOUPLE** — ship the daytime path, hold
night-trust.

Needs your **backstop-breadth policy call** (how broadly the backstop is allowed to override
night-trust).

⚠️ **Do NOT re-run the daytime manual-% remeasure** — it is non-stationary (zone_1 swings
46 / 81 / 50 / 50.3), and the acceptance criterion "zone_1 → ~6%" **fires falsification**. I
over-claimed a PASS on this and retracted it; it stays retracted.

Residual: Bryant native-schedule reclaim, blocked on your Bryant-schedule decision.
(Zone tonnage: 1 = 4-ton, 2 & 3 = 3-ton — you are the oracle here, the doc is wrong.)

> **ANSWER — backstop breadth policy:**
>
> **ANSWER — Bryant native schedule (keep / reclaim):**
>
> **ANSWER — decouple and ship daytime now?** (yes / no):
>

---

## 6. v5.103.14 README write-back — mine to do, no decision needed

`docs/readmes/README_v5.103.14.md` (reload-suppression, Tier 2-DB, shipped) still carries
**prospective** live-validation bullets at §21-26. Per the MANDATORY write-back rule the cycle is not
closed until the observed post-restart results replace them. Two things to verify live:
1. A room **Climate & Fans** save (non-entity change) produces **NO ROOM reload** and no websocket backup.
2. A `CONF_CLIMATE_ENTITY` change **DOES** reload.

Siblings parked: `SUBSTRATE-PER-ROOM-REFRESH-1`, `ZM-CLIMATE-DEFERRED-UPDATE-SUPPRESS-1`.

> **ANSWER — anything to add, or shall I just do it?** (default: I do it):
>

---

## 7. Housekeeping

- `WORKTREE-BACKLOG-PRUNE-1` **reopened**: 52 worktrees / 3.3GB, some **3542 commits behind**,
  **25 dirty** → explicitly *not* a blind delete. Needs a triage pass (dirty ones inspected before
  removal).
- `TEST-SILENT-WHOLE-FILE-SKIPS-1`: 10 tests that have **never executed** (same hollow-anchor class
  as the one fixed above, found by Review B). Worth a sweep — a test file that silently skips is
  worse than no test, because it reads as coverage.
- `MEMORY.md` at 20KB of a 24.4KB read limit; four `project_session_pickup_*` entries where the
  older three are largely superseded. Compaction pass available on request.

> **ANSWER — priority order for these three (or "you pick")?**
>
