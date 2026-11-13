# House-state step 1a: review D (adversarial completeness, diff-blind)

Branch `feature/house-state-step1a` (HEAD 1c602a1b) vs develop 7d826060, three-dot diff. Plan:
`PLANNING_house_state_axes_step1.md` rev 3 Part A (§A2 invariants). Read first, completely:
`docs/Coordinator/PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `docs/architecture/SENSOR_FLEET_CLASSES.md`. No
corrections-ledger claim is re-asserted here.

Note: during this review `presence.py:5553` (`self._feed_residency(...)`) was deleted in the working tree by a
concurrent framing-C mutation drill in this worktree. This review read the committed source and committed only this file.

## Findings

### HIGH-1: the residency resident set never matches a live `person.*` entity id (Bug Class #53, plus a hollow fixture)

`presence.py` `_residency_residents` builds the resident set as
`str(p) if str(p).startswith("person.") else f"person.{p}"` over `PersonTrackingCoordinator.tracked_persons`.
`tracked_persons` is `integration_entry.data[CONF_TRACKED_PERSONS]` (`person_coordinator.py:166`). Person
names are stored there, and `person_coordinator.py:978` normalizes each one as
`f"person.{name.lower().replace(' ', '_')}"`. The residency path skips that normalization.

Live config (`.storage/core.config_entries`, integration entry): `data.tracked_persons = ['Ezinne', 'Oji Udezue',
'Jaya', 'Ziri']`. Executed against the branch code (`_residency_residents` and `ResidencyTracker` called unbound with this
config shape):

- residents = `{'person.Ezinne', 'person.Jaya', 'person.Oji Udezue', 'person.Ziri'}`
- `tracker.on_event('person.oji_udezue', 'not_home', 'home', ...)` returns `None`. `_resident_status` compares exact
  strings, so **no live resident produces any arrival or departure record**. INV-PRODUCER fails on the live house:
  no `person_arrival` / `person_departure` rows, and the writer-health check pages about 7 days later.
- `get_residents_home()` returns `{Ezinne, Jaya, Ziri}` only because HA `States.get` falls back to `entity_id.lower()`
  (`homeassistant/core.py:2147`). `person.Oji Udezue` lowercases to `person.oji udezue` (a space, not an underscore), so
  **Oji is never counted home**. `effective_person_state`'s overrule match (`person_coordinator.py:807`) is also skipped
  for all four, so a BLE-overruled GPS `home` still counts as home.
- Consequences: an ARRIVING exterior-person alert resolves CRITICAL whenever Oji is the only resident home or arriving.
  `get_recent_resident_arrival` can never return a record. The residents-home sensor never lists Oji. INV-SEV fails in
  the resident-home direction. INV-NO-LOWER still holds, because every error here pushes toward CRITICAL.
- Why the suite is green: `test_residency_wiring.py:52-53, 284, 315` fakes `tracked_persons` in entity-id form
  (`person.oji_udezue`), which is not the production shape. This is the fake-coordinator shape behind the v5.8.0 incident.
- Fix: normalize with the person coordinator's own rule (`person.` + name lowercased with spaces replaced by `_`; keep
  entries that are already `person.*` ids). Add a test that uses the live data shape, including a two-word name.

### LOW-1 (pre-existing, already accepted as plan delta L1): a hand lock found at boot becomes `boot_unknown`

A lockout locked by hand while the reason is NONE has no persisted reason, so `_boot_rebuild`
(`security_lock_regime.py:734`) sets `boot_unknown`, which is sleep-like. The daytime backstop
(`_schedule_backstop(allow_immediate=True)`, `:746`) then releases the hand lock. The trigger is `backstop`, not a house
or boot-recheck trigger, so INV-LOCK does not cover it. No change requested.

### LOW-2 (reachability not demonstrated): a vacation lock restored into a HOME_* boot read with `_episode_saw_empty` False

Required state: persisted `garage_reason = vacation`, a lockout locked, `_episode_saw_empty` False (the vacation engage
clears it, `:1037`), and `_boot_rebuild` reading `home_*`. In that state the recheck returns `house_edge_ignored`, and
the gap page is suppressed because neither condition at `:1185-1188` holds. Vacation has no backstop, and a restored
`home` is not a person edge. The lock therefore stays locked with residents home and nothing pages. Develop released
here, because an untainted HOME_* boot read releases on a provisional reason.

I could not build a legal sequence that reaches this state:
- A live VACATION→ARRIVING/AWAY exit sets the flag (old side).
- A stale restore boots the machine as `away` (`house_state.py:153`), which sets the flag at the rebuild, provided the
  rebuild reads the house before the first settled inference.

It is reachable only if the regime's setup runs after the first post-settle inference has already moved the house to
HOME_*. Framing B or the orchestrator should check that setup ordering. A one-line close is to set the flag at the boot
rebuild when `restored == vacation and house not in (vacation, sleep)`.

## Invariant checklist (falsifiable form, whole surface)

| Invariant | Falsifiable statement | Result | Evidence |
|---|---|---|---|
| INV-LOCK | With the kill switch on, no `_release` with trigger `house_state:*` or `boot_recheck` writes an unlock or ends an episode, except WAKING with a sleep-like reason or an edge whose trigger is in {override_set, override_clear} | **PASS** | All 12 `_release` call sites enumerated (`:946, 1116, 1304, 1317, 1345, 1468, 1481, 1771, 1994, 2555`, plus the disable loop `:893`). Only `:946` and `:1116` carry these triggers. Both go through `_edge_decision` (`:1004-1032`), which releases only on (waking, sleep-like) or (HOME_*/ARRIVING, operator). The recheck passes `operator=False`. The single dispatcher (`presence.py:9566`) has three trigger sources: inference triggers (none named override_*), the override adapter (`house_state.py:283/314`, operator callers only: `select.py:272-280`, `__init__.py:6216-6237`), and the boot-settle re-emit `override_set` (accepted residual, plan L1/L3). `_after_release` ends an episode only on a release. Engage edges (sleep/vacation/guest) replace the reason and never unlock. Hazard, kill switch, SC disable and backstop releases are outside the invariant. |
| INV-NO-LOWER | With the residency switch False, no (state, camera, track) cell resolves below the resolver at `persons_home = 0` | **PASS** | `perimeter_alert.py` `_get_persons_home` returns 0 when the switch is False. `_severity_for_current_house_state` is the only resolver call site (grep). The ARRIVING arm can only raise MEDIUM to CRITICAL (`const.py` arriving branch). Any error sets evidence False, which gives CRITICAL. HIGH-1 also pushes toward CRITICAL. |
| INV-PAGE | The saw-empty flag is never narrower than the old taint. The boot gap page fires on a restored away/arriving house OR the flag. | **PASS** (LOW-2 open) | The set conditions (`:933-939`, `:738-743`, `:1088-1097`) are a superset of develop's taint sites: old/new side, any trigger, plus `away`. The clear sites are unchanged (`_end_episode_flags`, the one site). A legacy `garage_arrival_taint` loads as the flag (`:3046-3050`). |
| INV-RULE | One counted-return and ledger rule, no second copy | **PASS** | No direct `_last_real[...]` writes remain in the lock. `_arrival_counts` / `_really_away` delegate to `arrival_edges` (`:1773-1795`). The restore stamp and S5 call `stamp_restored` / `update_last_real` (`:1405`, `:1485`). The tracker calls the same functions (`residency.py:107, 134, 153`). The arithmetic matches develop's line for line. |
| INV-MACHINE | No hunk in `house_state.py`, `_run_inference`, `_dispatch_house_state_change`, the selects or the service | **PASS** | The diff stat has no `house_state.py`, `select.py` or `__init__.py`. The presence hunks are at 1829, 3127, 4749 (the fan-gate closure, outside `_run_inference`), 5222, 5305 and 8901. |
| INV-PRODUCER / INV-SEV | (in scope for completeness) | **LEAK** | HIGH-1. |

## Verdict: FIX-REQUIRED

Must fix: HIGH-1. Normalize the residency resident set the way `person_coordinator` does, and replace the entity-id-form
`tracked_persons` fakes with the live name form, including a two-word name. Recommended: close LOW-2 with the one-line
rebuild flag, or have B confirm that the setup ordering makes it unreachable.

| Severity | Found | Must fix |
|---|---|---|
| HIGH | 1 | 1 |
| LOW | 2 | 0 |

Bug classes: #53 computed-but-not-consumed (one missed normalization site); hollow fixture (test shape ≠ production config,
v5.8.0 class).

## Fix-up re-check (commit b532b028)

Read-only re-check, framing D. I re-read `PRESENCE_ARCHITECTURE_STATE_OF_PLAY.md` and `SENSOR_FLEET_CLASSES.md` completely
first. No corrections-ledger claim is re-asserted. No source was mutated and no suite was run (the validator owns it).

### Per-finding verification

| Finding | Status | Evidence |
|---|---|---|
| D HIGH-1 / A-H1 / B-H1: resident set never matched a live `person.*` id | **CLOSED** | `presence.py:5247-5251` maps every `tracked_persons` entry through `person_coordinator.tracked_person_entity_id` (`person_coordinator.py:130-141`). That is the coordinator's own rule (`person_coordinator.py:993`, `:821`, `:1743`). The live config (re-read 2026-11-13) is `data.tracked_persons = ['Ezinne', 'Oji Udezue', 'Jaya', 'Ziri']` and `options.tracked_persons = ['person.ezinne', 'person.oji_udezue', 'person.jaya', 'person.ziri']`. The person coordinator reads `data`, so the mapped set equals the options ids exactly. The round trip is lossless for any HA person slug: `__init__.py:3148` builds names by `replace('_',' ').title()`, and lower plus `' '→'_'` inverts it for `[a-z0-9_]`. Every resident-set reader in the diff goes through this one helper: the tracker (`presence.py:5224`), `get_residents_home` (`:5415`) and the residents-home sensor attributes (`sensor.py:6146`). The phone-left-behind slug (`residency.person_slug` → `oji_udezue`) matches the sensor's unique id (`binary_sensor.py:2125`). The BLE-overrule match in `effective_person_state` (`person_coordinator.py:821`) now matches too. Tests use the live display-name shape (`test_house_state_step1a_fixup.py:52-120`, two-word name included). |
| A-M1: recent arrival counted across a later departure | **CLOSED** | `residency.py` `recent_arrival` walks newest-first and collects departures before reaching older arrivals. An arrival is skipped only if the same person has a newer departure. A re-arrival after the departure is seen first and still counts. Deque eviction drops the oldest first, so a departure cannot be evicted while an older arrival it suppresses remains. The skip pushes toward CRITICAL, so INV-NO-LOWER holds. |
| A-M2: the 60 s per-type window dropped real edges | **CLOSED** | `database.py:10733` gates the window block on `window_dedup` (default True). All 12 other `log_memory_episode` callers (fan_veto, coordinator x2, sensor, exterior_track_linker, transit_validator, memory_writers x5, hvac_fans) pass no kwarg, so they are byte-identical. Residency passes `window_dedup=False, dedup_source_ref=True` with `source_ref = person@edge_ts` (`presence.py:5326-5334`), which is unique per edge. Note: `source_ref` has no index (the only `memory_episodes` index is `(node_id, episode_type, started_at)`, `database.py:2014`), so each residency row costs one full-scan SELECT over about 18k rows (live count 18,113). The exterior linker already pays this at a far higher rate. Residency writes are a few dozen a day, so I am not raising it. |
| B-L1: teardown order | **CLOSED** | `presence.py:9159` sets the flag first, and `_persist_residency_event` returns on it (`:5300`), so no row task is created after that point even while the listeners are still live. The bounded gather (`:9292-9297`) now runs after `_cancel_listeners()`. Every await between them is wrapped in try/except (`:9217, 9239, 9255, 9282`), so an earlier failure cannot skip the gather. |
| D LOW-2: a restored VACATION lock in an awake house was silent | **CLOSED** | `security_lock_regime.py:738` sets `_episode_saw_empty` when the restored reason is `vacation`. This branch is only reached when the house is not `sleep` or `vacation` (`:720-726`). The boot recheck then returns `house_edge_ignored` (for HOME_*) or `no_change`, and both call `_boot_gap_return_page` (`:1159-1166`), which now passes its saw-empty condition (`:1189-1192`). It is a page only. |

### N+1 enumeration (what the fixes could have revealed)

- **Readers of `_episode_saw_empty`** (`:940, 1095, 1191, 1512`): all are page conditions (the boot gap page and the D4b uncounted-return page). None gates a `_release` or an engage. Setting the flag at boot can therefore add pages but can never unlock. INV-LOCK holds. The 12 `_release` sites are unchanged by the fix-up (same enumeration as above). The fix also fires for a restored `vacation` read in `waking`. That is correct: `_edge_decision` releases on WAKING only with a sleep-like reason, so the lock is held and the page is the right outcome.
- **Other resident-set builders in the diff**: none. The lock regime's `_residents` is built from live `person.*` states minus exclusions, not from `tracked_persons`. Perimeter severity reads `presence.get_residents_home_count()` and `get_recent_resident_arrival()`, both downstream of the fixed helper.

### Sweep: other `tracked_persons` / `CONF_TRACKED_PERSONS` readers (display name vs entity id)

Stored shapes: config-flow writes entity ids. `__init__.py:3145-3163` rewrites **`entry.data`** to display names on every setup. `entry.options` keeps entity ids once the options form has been saved, which it has on the live house. A reader of `{**data, **options}` therefore sees entity ids live but **display names on an install whose options were never saved**: a fresh install, so this matters for portability.

| Reader | Source | Assumes | Verdict |
|---|---|---|---|
| `presence._residency_residents` (`:5247`) | pc `tracked_persons` (data) | names → mapped | **In diff, fixed** |
| `PersonTrackingCoordinator` (`person_coordinator.py:180, 993, 821`) | data | names | Correct (it defines the rule) |
| `aggregation.py:382-388, 603-616` | data | `split('.')[-1]` → person_id = display name | Pre-existing. It works by construction because the per-person sensors are keyed on the name. Not a bug. |
| `binary_sensor.py:117-125` | merged | handles both forms | Correct |
| `switch.py:6528-6540`, `music_following.py:186-201` | merged | opaque keys; MF canonicalises with `_person_key` (`__init__.py:3444-3452`) | Correct |
| `camera_census.py:6159-6176` (family trackers for guest-VLAN) | merged | **entity id** (`hass.states.get(person_entity_id)`) | **Pre-existing latent LOW.** If options lack the key, it reads `hass.states.get('Oji Udezue')`, gets None, and the family-tracker set is empty. Not reachable on the live house (options hold ids). Not in this diff. |
| `camera_census.py:6311-6320` (face-recognised names) | merged | `replace('person.','')` slug | **Pre-existing latent LOW**, same shape: the slug becomes `'Oji Udezue'` (space, capitals) on a never-saved-options install. Not in this diff. |
| `camera_census.py:3900-3912`, `perimeter_alert.py:5117-5121` | merged | lower + strip `person.` | **Pre-existing latent LOW**, same shape: the slug becomes `'oji udezue'` (space, not `_`). Not in this diff. |

The four latent LOWs share one root cause: `__init__` rewrites `data` to names while `options` keeps ids. The robust fix is for these readers to call `tracked_person_entity_id` (now public) and then slug. I recommend a card (portability). They do not block this cycle.

### Fix-up verdict: **SHIP**

D's invariant checklist re-run: INV-LOCK **PASS**, INV-NO-LOWER **PASS**, INV-PAGE **PASS** (LOW-2 closed), INV-RULE **PASS** (fix-up touches no ledger code), INV-MACHINE **PASS** (no hunk in `house_state.py`, `_run_inference` or `_dispatch_house_state_change`), INV-PRODUCER / INV-SEV **PASS** (HIGH-1 closed against the live config shape). No new CRITICAL, HIGH or MEDIUM. One card is recommended: the latent display-name readers in `camera_census` and `perimeter_alert` (pre-existing, portability).
