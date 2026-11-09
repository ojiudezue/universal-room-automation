# AUDIT: Does Bermuda hold an absent phone's last room? (v5.107.4 review MED-3)

Probed Mon 2026-11-09 00:04 CST (read-only). Times below are HA host local clock (US Central; DST ended 2026-11-01 02:00, so all rows are CST).
Scripts (not committed): scratchpad `p.py`, `p2.py`, `p3.py`, `p4.py` under
/private/tmp/claude-501/-Users-okosisi-Code-universal-room-automation/75cc297f-1426-4620-b7aa-da058bc0fab0/scratchpad/
Not a HVAC/presence-state-of-play investigation of design; I did not re-read the STATE_OF_PLAY docs, since this is a narrow recorder measurement.

## Verdict

**MED-3 is REFUTED on live data for the stated scenario.** Bermuda's per-person area sensor does not hold the last room for an absent phone: it goes to state `unknown`, usually 1-5 minutes before `person.*` flips to `not_home`. Over the whole recorder window (2026-11-01 04:12 to 2026-11-09 00:04, ~7.8 days) there were **0 seconds** of an absent-per-`person.*` phone with a real room showing, except two short GPS flaps for Ziri (below) where the phone really was in the house. A restart or Bermuda reload does not re-stamp a stale room for an away person, because there is no stale room to re-stamp.

Caveat: the 10-24 trip named in the review is outside recorder retention (earliest state row 2026-11-01 04:12), so I could not look at it. The longest absence in window is Ziri 2026-11-01 09:08 to 11-06 22:29 (133 h) plus Ezinne 53.7 h.

## 1. Entities and the URA read path

| Person | Bermuda area sensor | platform (core.entity_registry) | person entity | recorder rows |
|---|---|---|---|---|
| Oji | sensor.iphone_oji_area (metadata 9444) | bermuda | person.oji_udezue | 10920 |
| Ezinne | sensor.ezinne_iphone_area (9681) | bermuda | person.ezinne | 5301 |
| Jaya | sensor.iphone_jaya_area (10002) | bermuda | person.jaya | 3415 |
| Ziri | sensor.iphone_ziri_area (15729) | bermuda | person.ziri | 2902 |

URA discovery: `PersonCoordinator._find_bermuda_area_sensor` (person_coordinator.py:1742-1800): config override `CONF_BERMUDA_AREA_SENSORS` (none stored in core.config_entries for URA), then private_ble derivation, then two name patterns, then registry fallback (`sensor.*_area`, platform contains "bermuda", first name in id; :1788-1795). With no override these four resolve via the registry fallback or private_ble path. Read at :1021-1028: state `unknown`/`unavailable` is treated as "no room" (:1023) and never as a room.

## 2. Observed Bermuda behaviour

State vocabulary for absent phones: 55/41/46/28 `unknown` rows (oji/ezinne/jaya/ziri) vs 1 `unavailable` each (the 11-06 22:30:26 reload). So "phone unseen" = `unknown`; `unavailable` = integration reload.

**Time-weighted overlap (p4.py):** `person.*` not_home total vs seconds with a room on the area sensor.

| Person | not_home total | seconds a room was shown while not_home |
|---|---|---|
| Oji | 51.6 h | 0 |
| Ezinne | 77.0 h | 0 (one 0-second tie at 11-02 08:12:40, same-timestamp return) |
| Jaya | 96.2 h | 0 (one 0-second tie at 11-08 17:40:47, the return itself) |
| Ziri | 161.6 h | 833 s, two episodes only (see below) |

**Away starts > 1 h (every one in window):** area was already `unknown` at the moment `person.*` went `not_home` in all of them (Oji 10, Ezinne 7, Jaya 9, Ziri 6; p.py "area_at_start=unknown"). The sensor leads person.* out of the room by roughly 10 s to ~5 min (e.g. Jaya 11-04 area unknown 09:26:44, person not_home 09:31:19). The two first rows on 11-01 show `None` because the recorder window begins after the 11-01 09:08 shutdown (area unknown/unavailable at 09:08:32 for Oji and Ziri, both away).

**The only room-while-not_home spans (Ziri, both < 10 min):** 11-07 01:21:03-01:25:46 and 11-08 00:57:41-01:06:52. Area flips every few seconds between Ziri Bathroom / Ziri Bedroom / Jaya Bedroom / Upstairs Hallway. That is a live phone in the house while Ziri's GPS flapped to not_home (this is the review's LOW-1 shape, not MED-3). The sensor was tracking the phone, not holding stale data.

## 3. HA restarts and Bermuda reloads

16 `homeassistant_start` events (11-01 09:10:20 through 11-08 13:54:29). For every restart, every person who was away (per person.*) had area `unknown` before and **no room afterwards until a real return** (p2.py). Representative:

| Restart | Away persons (per person.*) | Area before | Area after restart |
|---|---|---|---|
| 11-01 09:10:20 | Oji, Ziri | unknown (09:08:32) | unknown (09:12:41 row) |
| 11-07 14:03:41 | all four | unknown (14:02:47) | no new row (stays unknown) |
| 11-08 11:05:30 | all four | unknown (11:03:04) | no new row |
| 11-08 13:54:29 | all four | unknown | rooms appear 13:58:52 (Oji, Jaya Bedroom), 13:58:55 (Ezinne), exactly when person.oji returns home at 13:58:51 and person.ezinne at 13:58:51; a real arrival, not a re-stamp |

Same-room re-stamp does occur, but only for persons who are home: a Bermuda-wide reload at **11-06 22:30:26 (unavailable) -> 22:30:27 (back)**, 1 s gap, hit all four; Oji Kitchen->Kitchen, Ezinne Master Bedroom->Master Bedroom, Jaya Jaya Bedroom->Jaya Bedroom, Ziri Stair Closet->Media Room. All four `person.*` were home (Ziri had arrived 22:29:55). It is not a homeassistant_start event. At 11-01 09:10 and 11-02 06:57 restarts the home persons come back in the same or adjacent room (e.g. Ezinne Master Bedroom -> Master Bedroom 09:12:41), which is present-person behaviour.

Other unavailable->available transitions (full list in p.py output): 70+ across the four sensors. "SAME room" returns with `person=home` are people who stayed put (e.g. Jaya Bedroom 11-06 07:32:36 -> 09:01:19, Ezinne). Long unavailable gaps that end in `Garage A` while `person.*` was not_home and flips to home at that second (Jaya 11-03 07:28:36 -> 22:36:37, Ziri 11-07 10:50:52 -> 17:40:35, etc.) are genuine arrivals: the first room seen on the way back is the garage.

## 4. Would URA read a reappearance as a move?

- Move event: `location_changed = resolved_room != old_location` (person_coordinator.py:1034); the `ura_person_location_change` event + `_log_person_room_change` fire only when `location_changed and old_location not in ("unknown", "")` (:1036-1062).
- Bermuda gap < `decay_timeout` (default 300 s, const.py:179; read :188-191): the Bermuda-unresolved branch keeps `old_location` as STALE (:1163-1190), so a return is either "no change" (same room) or an ordinary move. The 1 s reload on 11-06 and the 2-min gaps on 11-02 02:11/02:24 fall here.
- Gap > 300 s: location becomes "home"/"away" (:1198-1262), so a return from a room-less sensor reads as a "move" from "away"/"home" into the room. That is the intended arrival path for a genuine return (the garage-first returns above). Whether a *face-based* corroboration should accept it is the design question, but the premise of MED-3 (stale room re-stamped for an absent person) did not occur.
- A fresh-boot URA starts with `old_location` unknown, so no event fires on the first resolved tick (:1036 guard).

## 5. Falsification

MED-3 would be proven by any interval where `person.*` = not_home for any time and the area sensor shows a room, spanning a restart/reload. Searched: all four persons, all 16 restarts, the one reload, every unavailable->available transition, and a time-weighted overlap. Found only the two Ziri live-phone flaps (not stale, not re-stamped). Not tested: a Bermuda reload *while a phone is genuinely away and still held by a proxy*; Bermuda's own code path for that case was not read (I did not read the Bermuda source), so the claim is limited to what the recorder shows over 7.8 days.

## 6. Residual (not MED-3)

- LOW-1 shape is real and observed: Ziri 2026-11-07 01:21 and 11-08 00:57, phone in the house while `person.ziri` read not_home for 4.7 and 9.2 min. Both under the review's 15-minute `_really_away` bound.
- 10-24 trip data is purged; if 10-24 behaviour matters, only URA's own DB (person path tables) might still hold it. Unknown.
