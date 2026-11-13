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
