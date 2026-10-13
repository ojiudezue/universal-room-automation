# AUDIT — Relay → smart-bulb detach inventory

**Date:** 2026-10-13 · **Mode:** read-only (nothing on HA was changed)
**Sources:** `/config/.storage/core.{entity,device,area}_registry`, `core.config_entries` (URA room configs),
`automations.yaml`, recorder `home-assistant_v2.db` opened `mode=ro` via `ssh ha python3 -`. Window = last 10 days
(2026-10-03 → 2026-10-13 17:55). 18 HA restarts in the window; bulb transitions within 10 min of a restart were
excluded from correlation.

---

## 0. Headline finding — the premise mostly does not hold

**No Shelly or Sonoff relay channel was shown to feed any Wi-Fi smart bulb.** Three independent tests agree:

1. **Event co-drop** (bulb → `unavailable` within 10 s / 90 s of a relay `on→off`; bulb back within 150 s of `off→on`),
   relay × bulb over 10 days: the best Shelly/Sonoff pair reached **2 co-drops in 10 s** against 20–72 relay
   cycles. That is the chance rate for bulbs that flap 80–300×/10 d on their own.
2. **Time-weighted availability lift** (P(bulb available | controller on) − P(available | controller off), sampled
   every 60 s over 10 days, against **every** `switch.*`/`light.*` in HA): for every bulb that was ever reachable, the
   top controller is **not** a Shelly or Sonoff (table §2).
3. **Power signature:** every metered Shelly channel draws one steady wattage when on (e.g. Garage A 112.5 W,
   Laundry1 SW1 50.1 W, Butler Pantry 25.2 W). That is what dumb LED fixtures look like. No channel has an
   "on but near 0 W" mode, which is what a relay feeding smart bulbs that are switched off would show.

What actually gates bulb power (confirmed by the lift test, lift ≥ 0.9):

| Gate (not Shelly or Sonoff) | Bulbs it powers | Evidence |
|---|---|---|
| `light.dimmer_tapo_wifi_matter_kitchenoverhead` (Tapo S515D, Kitchen) | Jullison kitchen1–4 + kitchenpath (`tuya_local` `_2` and cloud) | Available 98–100 % when dimmer on, 0–1 % when off. 9–11 of 13–16 returns came ≤ 150 s after the dimmer turned on |
| `light.switch_mmwave_inovelli` (Inovelli mmWave Zigbee dimmer, Master Bedroom, URA manual switch) | Jullison master1,2,3,4,5,8 (both integrations) | 87–98 % available when on, 0 % when off. Cross-tab: Inovelli off → bulbs `unavailable` in ~5,200 of ~5,260 samples |
| Dewenwils low-voltage transformers `switch.switch_lowvtransformer_dewenwils_wifi_landscape{1,2}_switch_{1,2,3}` (Tuya, plus `_2` duplicates) | All landscape lights: LIFX landscape1/2/3, TreeLeft, Front Right 2, EntryLeft, FrontLeftMagnolia; GK perimeter/sideapproach/corner; FrontPath*; smart_rgbw_13–18 | 85–100 % available when on, 0 % when off. These are switched by the HA automations in §5, every night at about 19:40 on and 01:00, 01:30 or 07:30 off |

So the **wall-switch → relay → bulb** problem behind the 61 `setup_retry` entries comes mainly from (a) bulbs that are
dead or long gone, (b) landscape transformers that HA turns off on purpose every night, and (c) two non-relay dimmers.
It does not come from the Shelly/Sonoff fleet. The detach plan still makes sense for a few circuits (§6), but it will
not clear most of the `setup_retry` entries.

**Gap:** this audit did not read the config-entry `setup_retry` state; the 49 tuya_local / 12 LIFX figures are the
operator's. The registry holds 48 `tuya_local` lights and 12 `lifx` lights.

> Caveat: Sonoff MINI R4M channels have **no power metering**, and several were never toggled in the window
> (Patio lights, Upstairs Hallway, Master Toilet fan). Neither the co-drop test nor the power test can rule
> those channels in or out. For Patio and Dining the pairing is marked **probable** (§2).

---

## 1. Every relay channel

Notes on the columns:
- **Mode entity.** SonoffLAN exposes `switch.*_detach` (all currently `off` = normal/attached). Its `select.sonoff_*_1`
  (`stay`) is the power-on state, not the switch mode. The HA Shelly integration exposes **no** switch-mode or detach
  entity on any of these devices (registry checked). Detached mode has to be set on the device (web UI or RPC),
  and HA has no entity that shows the current mode.
- **Emits when detached.** Sonoff: `sensor.<id>_action`. Shelly: the existing `binary_sensor.*input*` (switch-type input).
  If the input type is changed to *button*, the Shelly integration may create an `event.*` entity instead; that is
  unverified here.
- **On-W** = median W while on (10 d recorder). "—" = never on in the window.

### Shelly (all metered unless noted)

| Relay entity | Device / model | Area | State now | Toggles 10 d (off/on) | On-W (median) | Input entity (detached emitter) |
|---|---|---|---|---|---|---|
| switch.shelly2pmg3_34cdb07765dc_switch_0 | MasterBath 2PM G3 | Master Bathroom | unavailable | 42/41 | 37.2 | binary_sensor.shelly2pmg3_34cdb07765dc_input_0_input |
| switch.shelly2pmg3_34cdb07765dc_switch_1 | MasterBath 2PM G3 | Master Bathroom | unavailable | 64/63 | 25.2 | binary_sensor.shelly2pmg3_34cdb07765dc_input_1_input |
| switch.shelly1pmminig3_34b7daca4214_switch_0 | MasterBathFan 1PM Mini G3 | Master Bathroom | off | 22/21 | 4.3 (fan) | binary_sensor.shelly1pmminig3_34b7daca4214_input_0_input |
| switch.switch_shelly2pmgen3_wifi_guesttoilet1_sw1 | GuestToilet1 2PM G3 | Guest Toilet | off | 32/32 | 16.2 | binary_sensor.switch_shelly2pmgen3_wifi_guesttoilet1_input_0 |
| switch.switch_shelly2pmgen3_wifi_guesttoilet1_sw2 | GuestToilet1 2PM G3 | Guest Toilet | off | 24/25 | 12.6 | …guesttoilet1_input_1 |
| switch.switch_shelly2pmgen3_wifi_guesttoilet2_sw1 | GuestToilet2 2PM G3 | Guest Toilet | off | 10/9 | 3.9 | …guesttoilet2_input_0 |
| switch.switch_shelly2pmgen3_wifi_guesttoilet2_sw2 | GuestToilet2 2PM G3 | Guest Toilet | off | 28/29 | 12.6 (Powder humidity fan) | …guesttoilet2_input_1 |
| switch.switch_shelly2pmgen3_wifi_laundry1_sw1 | Laundry1 2PM G3 | Laundry | off | 25/25 | 50.1 | binary_sensor.shelly2pmg3_b08184f3bd18_input_0 |
| switch.switch_shelly2pmgen3_wifi_laundry1_sw2 | Laundry1 2PM G3 | Laundry | off | 20/20 | 33.1 | …b08184f3bd18_input_1 |
| switch.switch_shelly2pmgen3_wifi_laundry2_sw1 | Laundry2 2PM G3 | Laundry | off | 4/4 | 11.4 | binary_sensor.shelly2pmg3_e4b323135af8_input_0 |
| switch.switch_shelly2pmgen3_wifi_laundry2_sw2 | Laundry2 2PM G3 | Laundry | off | 2/2 | 9.1 (humidity fan) | …e4b323135af8_input_1 |
| switch.switch_shelly_wifi_mediaroom_sw0 | MediaRoom 2PM G3 | Media Room | off | 0/0 | — | none in registry |
| switch.switch_shelly_wifi_mediaroom_sw1 | MediaRoom 2PM G3 | Media Room | off | 6/6 | 65.5 | none in registry |
| switch.switch_shelly2pmgen3_wifi_butlerpantry_overheadlights | ButlerPantry 2PM G3 | Butler Pantry | off | 18/18 | 25.2 | …butlerpantry_input_0 |
| switch.switch_shelly2pmgen3_wifi_butlerpantry_pucks | ButlerPantry 2PM G3 | Butler Pantry | off | 18/18 | 41.9 | …butlerpantry_input_1 |
| switch.switch_shelly2pmgen3_wifi_dnguestroom_light | DNGuestRoom 2PM G3 | Guest Bedroom 1 | off | 2/2 | 49.8 | …dnguestroom_input_0 |
| switch.switch_shelly2pmgen3_wifi_dnguestroom_fan | DNGuestRoom 2PM G3 | Guest Bedroom 1 | off | 1/1 | — | …dnguestroom_input_1 |
| switch.switch_shelly2pmgen4_wifi_dining1_overhead | Dining1 2PM G4 | Dining Room | **unavailable (device offline)** | 0/0 | — | binary_sensor.shelly2pmg4_ccba97de38c4_input_0 |
| switch.switch_shelly2pmgen4_wifi_dining1_pooltable | Dining1 2PM G4 | Dining Room | **unavailable** | 0/0 | — | …ccba97de38c4_input_1 |
| switch.switch_shelly2pmgen4_wifi_dining2_recessed | Dining2 2PM G4 | Dining Room | off (all 10 d) | 0/0 | — | binary_sensor.switch_shelly2pmgen3_wifi_dining1_input_0 |
| switch.switch_shelly2pmgen4_wifi_dining2_divide | Dining2 2PM G4 | Dining Room | off (all 10 d) | 0/0 | — | …dining1_input_1 |
| switch.switch_shelly1pmgen3_wifi_dnguest_closet | DNGuest_Closet 1 Mini G3 | Guest Bedroom 1 | off | 2/2 | **unmetered** | binary_sensor.shelly1minig3_b08184f0c75c_input_0 |
| switch.switch_shelly2pmgen3_wifi_breakfast_chandelier | Breakfast 2PM G3 | Breakfast | off | 0/0 | — | binary_sensor.shelly2pmg3_e4b3233ed9fc_input_0 |
| switch.switch_shelly2pmgen3_wifi_breakfast_overhead | Breakfast 2PM G3 | Breakfast | off | 0/0 | — | …e4b3233ed9fc_input_1 |
| switch.shelly2pmg3_28372f239274_switch_0 | BreakfastCabinet 2PM G3 | Breakfast | off | 2/2 | 56.6 | binary_sensor.shelly2pmg3_28372f239274_input_0 |
| switch.shelly2pmg3_28372f239274_switch_1 | KitchenGlobes 2PM G3 | Kitchen | off | 2/2 | 48.6 | …28372f239274_input_1 |
| switch.switch_shelly2pmgen3_wifi_patio_fan1 / _fan2 | PatioFans 2PM G3 | Patio | off | 0/0 | — | …patiofans_input_0 / _1 |
| light.shellydimmer2_24d7ebe93470 | Dimmer 2 | Master Bedroom | off | 0/0 | — | …channel_1_input / channel_2_input |
| switch.switch_shelly1pmgen4_wifi_receivingroom | 1PM Mini G4 | Receiving Room | **unavailable** | 0/0 | — | binary_sensor.shelly1pmminig4_a085e3bfaf30_input_0 |
| light.dimmer_shellyplus_wifi_receiving1 / receiving2 | Plus Wall Dimmer | Receiving Room | **unavailable** | 0/0 | unmetered | none |
| light.dimmer_shellyplus_wifi_studyb / studyb1 | Plus Wall Dimmer | Study B | off | 0/0 and 1/1 | unmetered | none |
| switch.switch_shelly2pmg3_wifi_dnguestbathrooom1_overheadlights | DNGuestBath1 2PM G3 | GB1 Bathroom | off | 24/24 | 12.3 | …dnguestbathrooom1_input_0 |
| switch.switch_shelly2pmg3_wifi_dnguestbathrooom1_wallsconce | DNGuestBath1 2PM G3 | GB1 Bathroom | off | 25/25 | 22.7 | …dnguestbathrooom1_input_1 |
| switch.switch_shelly2pmg3_wifi_dnguestbathrooom2_humidityfan | DNGuestBath2 2PM G3 | GB1 Bathroom | off | 4/3 | 0.0 (fan load not drawing) | …dnguestbathrooom2_input_0 |
| switch.switch_shelly2pmg3_wifi_dnguestbathrooom2_showerlight | DNGuestBath2 2PM G3 | GB1 Bathroom | off | 3/3 | 12.2 | …dnguestbathrooom2_input_1 |
| switch.switch_shelly1pmgen3_wifi_upguestbathroomfan | 1PM Mini G3 | GB2 Bath | off | 6/7 | 10.4 (fan) | …upguestbathroom_input_0 |
| switch.switch_shelly2pmgen3_wifi_upguestbathroom_overhead | 2PM G3 | GB2 Bath | off | 25/24 | 15.4 | …upguestbathroom_input_0_2 |
| switch.switch_shelly2pmgen3_wifi_upguestbathroom_sconce | 2PM G3 | GB2 Bath | off | 33/32 | 24.8 | …upguestbathroom_input_1 |
| switch.switch_shelly1pmminigen3_wifi_gameroomfan | 1PM Mini G3 | Game Room | off | 0/0 | — | …gameroomfan_input_0 |
| switch.switch_shelly1pmgen3_wifi_gamedeskoverhead | 1PM Mini G4 | Game Room | off | 8/8 | 12.8 | …gamedeskoverhead_input_0 |
| switch.switch_shelly1pmminigen3_wifi_studyacloset | 1PM Mini G3 | Study A Closet | off | 15/16 | 12.5 | binary_sensor.shelly1pmminig3_d0cf13cc8558_input_0 |
| switch.switch_shelly1pmminig3_wifi_staircloset | 1PM Mini G3 | Stair Closet | off | 31/31 | 35.4 | …staircloset_input_0 |
| switch.switch_shelly1pmgen3_wifi_ojivanity | 1PM Mini G3 | Oji Vanity | off | 26/26 | 21.6 | …ojivanity_input_0 |
| switch.switch_shelly1pmgen3_wifi_ezinnevanity | 1PM Mini G3 | Ezinne Vanity | off | 10/11 | 31.5 | …ezinnevanity_input_0 |
| switch.switch_shelly1pmgen3_wifi_ezinnemakeup | 1PM Mini G3 | Ezinne Makeup | off | 4/4 | 21.6 | …ezinnemakeup_input_0 |
| switch.switch_shelly1pmgen3_wifi_mediacloset | 1PM Mini G3 | Media Room Closet | off | 1/1 | 12.8 | …mediacloset_input_0 |
| switch.switch_shelly1pmgen3_wifi_masterbedroom | 1PM Mini G3 | Master Bedroom | **on (all 10 d)** | 0/0 | 57 (0 since 12:39 today) | binary_sensor.shelly1pmg3_masterbedroom_input_0 |
| switch.switch_shelly1pmgen3_wifi_exerciseroomcloset | 1PM Mini G4 | Exercise Room Closet | off | 3/3 | 12.5 | …exerciseroomcloset_input_0 |
| switch.switch_shelly1pmgen3_wifi_garageaoverhead | 1PM Mini G4 | Garage A | off | 5/5 | 112.5 | …garageaoverhead_input_0 |
| switch.switch_shelly2pmg3_wifi_ziribathsconce | ZiriBath 2PM G3 | Ziri Bathroom | off | 1/1 | 15.9 | …ziribath_input_0 |
| switch.switch_shelly2pmg3_wifi_zirioverhead | ZiriBath 2PM G3 | Ziri Bathroom | off | 1/1 | 24.6 | …ziribath_input_1 |
| switch.switch_shelly2pmg3_wifi_jayabathfan | JayaBath 2PM G3 | Jaya Bathroom | off | 4/4 | 12.6 (fan) | …jayabath_input_0 |
| switch.switch_shelly2pmg3_wifi_jayabathshower | JayaBath 2PM G3 | Jaya Bathroom | off | 9/9 | 24.4 | …jayabath_input_1 |
| switch.guest_bedroom_2_closet_switch_shelly1pmg4_wifi_upguestcloset | 1PM Mini G4 | GB2 Closet | off | 1/1 | 12.4 | …upguestcloset_input_0 |
| switch.av_closet_shelly1pmminig4_avcloset | 1PM Mini G4 | AV Closet | off | 2/3 | 12.9 | …avcloset_input_0 |

Excluded from the table as not relays: `switch.*_aioshelly_ble_integration` (BLE-scanner toggles) and the Garage B
PM Mini meters (`em_shelly_wifi_garageb*`, `garageb_plug2`).

### Sonoff (SonoffLAN; none metered)

| Relay entity | Device | Area | State now | Toggles 10 d | Detach entity = value | Emits when detached |
|---|---|---|---|---|---|---|
| switch.switch_sonoffmini4rm_matter_mastertoilet | MINIR4M MasterToilet | Master Toilet | off | 46/46 | switch.sonoff_1002192efa_detach = off | sensor.sonoff_1002192efa_action |
| switch.switch_sonoffm4rm_matter_mastertoiletfan | MINIR4M MasterToiletFan | Master Toilet | off | 0/0 | switch.sonoff_100219a10c_detach (**disabled**) | sensor.sonoff_100219a10c_action |
| switch.sonoff_10021921b0_1 (+ `light.minir4m4_frontdoor` switch_as_x, in `light.outside_lights` group) | MINIR4M FrontDoor | Front Porch | off | 8/8 | switch.sonoff_10021921b0_detach = off | sensor.sonoff_10021921b0_action |
| switch.sonoff_1002197ef7_1 | MINIR4M MasterBathLED | Master Bathroom | off | 59/59 | switch.sonoff_1002197ef7_detach = off | sensor.sonoff_1002197ef7_action |
| switch.switch_sonoffm4rm_matter_mastercloset | MINIR4M MasterCloset | Master Closet | off | 72/72 | switch.minir4m_mastercloset_detach = off | sensor.minir4m_mastercloset_action |
| switch.switch_sonoffm4rm_matter_masterclosetstorage | MINIR4M MasterClosetStorage | Master Closet | off | 57/56 | switch.minir4m3_masterclosetstorage_detach = off | sensor.minir4m3_masterclosetstorage_action |
| switch.upstairs_hallway_switch_sonoffm4rm_matter_upstairshallway | MINIR4M UpstairsHallway | Upstairs Hallway | off | 0/0 | switch.sonoff_100219a3b4_detach = off | sensor.sonoff_100219a3b4_action |
| switch.switch_sonoffm4rm_matter_jayabedroom | MINIR4M JayaBedroom | Jaya Bedroom | off | 25/24 | switch.sonoff_100219a223_detach = off | sensor.sonoff_100219a223_action |
| switch.switch_sonoffm4rm_matter_ziribedroom | MINIR4M ZiriBedroom | Ziri Bedroom | off | 2/2 | switch.sonoff_1002194419_detach = off | sensor.sonoff_1002194419_action |
| switch.switch_sonoffm4rm_matter_upguest | MINIR4M UpGuest | Guest Bedroom 2 | off | 4/4 | switch.sonoff_1002198df8_detach = off | sensor.sonoff_1002198df8_action |
| switch.switch_sonoffm4rm_matter_exercise | MINIR4M Exercise | Exercise Room | off | 8/9 | switch.sonoff_1002193258_detach = off | sensor.sonoff_1002193258_action |
| switch.switch_sonoffm4rm_matter_patiolights | MINIR4M PatioLights | Patio | off (all 10 d) | 0/0 | switch.sonoff_1002193b5a_detach = off | sensor.sonoff_1002193b5a_action |
| switch.minir4m_sonoff_ziribathfan | MINIR4M ZiriBathFan | Ziri Bathroom | off | 1/1 | switch.sonoff_10021980f3_detach = off | sensor.sonoff_10021980f3_action |
| switch.sonoff_1002191ef1_1 | MINIR4M UpGuestRoom Hallway | GB Hallway | off | 1/1 | switch.sonoff_1002191ef1_detach = off | sensor.sonoff_1002191ef1_action |
| switch.sonoff_10021935b6_1 (+ `light.minir4m_jayabath_overhead` switch_as_x) | MINIR4M JayaBath Overhead | Jaya Bathroom | off | 22/21 | switch.sonoff_10021935b6_detach = off | sensor.sonoff_10021935b6_action |
| switch.minir4m_livingroom_sonoff_1002199676_1 | MINIR4M LivingRoom | (no area) | off | 1/1 | detach entity **disabled** | sensor.minir4m_livingroom_sonoff_1002199676_action |
| switch.minir4m_foyer_sonoff_100219a71a_1 | MINIR4M Foyer | (no area) | off | 3/4 | detach entity **disabled** | sensor.minir4m_foyer_sonoff_100219a71a_action |
| switch.sonoff_1002827400_1…4 | Kitchen MINI-2GS (4-gang) | (no area) | **unavailable all 10 d** | 0 | none | sensor.sonoff_1002827400_action |

---

## 2. Bulb → power-gate pairing

Legend: **CONFIRMED** = availability lift ≥ 0.85 with ≥ 30 samples in each state, plus returns timed to the gate's on.
**PROBABLE** = area or name match only, with no usable history because the gate never toggled or the bulb was never
reachable. **UNKNOWN** = nothing found. "Avail" = share of the 10 days the bulb was reachable.

Most bulbs exist twice: once in `tuya` (cloud) and once in `tuya_local` (the `_2`-suffixed or bare-named twin). The
pairings apply to both.

| Bulb group (entities) | Avail | Power gate | Status | Lift (on / off) |
|---|---|---|---|---|
| Kitchen pots: `rgbw_light_jullison_wifi_kitchen{1,2,3,4}`, `_kitchenpath` (+`_2` twins) | 8–12 % | Tapo S515D `light.dimmer_tapo_wifi_matter_kitchenoverhead` | **CONFIRMED** | 0.98–1.00 / 0.00–0.01 (kitchen2/2_2/3_2 weaker: 0.66–0.9) |
| Master pots: `rgb_white_light_jullison_wifi_master{1,2,3,4,5,8}` (+`_2`) | 1 % | Inovelli `light.switch_mmwave_inovelli` | **CONFIRMED** | 0.87–0.98 / 0.00 |
| Landscape A: LIFX `rgbwspotlight_lifx_landscape1/2/3`, `lifx_d0_73_d5_88_83_27` (TreeLeft), GK `perimeter5/7/7_2`, `corner2`, `sideapproach9/10/10_2/11`, `smart_rgbw_18`, `frontpathtopright` | 14–16 % | Dewenwils **landscape2** outlets (`…landscape2_switch_1/2/3`, on 19:4x → off 01:00/01:30) | **CONFIRMED** (all 3 outlets switch together, so which outlet feeds which bulb is not separable) | 0.90–1.00 / 0.00 |
| Landscape B: `smart_rgbw_13/14/15`, GK `perimeter3/3_2`, `frontpathbottomleft`, `frontpathmidleft` | 14–15 % | Dewenwils **landscape1** switch_2/3 (on 19:4x → off 01:00/01:30) | **CONFIRMED** | 0.84–0.96 / 0.00 |
| Landscape C: LIFX `front_right_2`, `rgbwspotlight_lifx_landscape_entryleft`, `_frontleftmagnolia` | 29–34 % | Dewenwils **landscape1 switch_1** (on 19:4x → off 07:30, i.e. the "porch" all-night leg) | **CONFIRMED** | 0.85–0.98 / 0.00 |
| Landscape weak: GK `perimeter1/4/4_2/8`, `corner1`, `sideapproach12/12_2/11_2`, `backdrivewayleft`, `smart_rgbw_17/19/20`, `frontpathbottomright`, `lifx_light_silver_luna` | 3–11 % | Dewenwils (probably), but bulbs are flaky even when powered (lift 0.4–0.78; median outage 50–105 s, all between 19:00 and 07:00) | **PROBABLE** (Dewenwils); Wi-Fi reach at the yard edge is the second problem | — |
| Dining pots: `rgbw_light_jullison_wifi_dining1–4`, `rgbw_smart_slim_pot_light_v2_31–34`, `_v2_21` (DiningDivide3) | 0 % | Shelly Dining1 G4 (device offline) / Dining2 G4 `recessed`, `divide` (off all 10 d) | **PROBABLE** (area + "DiningDivide" name) | no history |
| Patio pots: `rgbw_light_jullison_wifi_patio1–4` (+`_2`) | ~0 % (3 samples) | Sonoff `switch.switch_sonoffm4rm_matter_patiolights` (off all 10 d; both are in the URA Patio room `lights`) | **PROBABLE** | no history |
| Kitchen-dining pots: `rgb_white_light_jullison_wifi_kitchendining1–3` (+`_2`, `_v2_29`) | 0 % | Kitchen MINI-2GS (`switch.sonoff_1002827400_*`, offline all 10 d)? | **PROBABLE**, weak (name only) | no history |
| Balcony: `rgbw_balcony1/2` (+ `_v2_35/36`) | 0 % | — | **UNKNOWN** | — |
| Master Hallway: `rgb_white_light_jullison_wifi_3/4` (+night) | 0 % | — (Master Hallway has no URA lights configured) | **UNKNOWN** | weak lift 0.44 to `dimmer_garagehallway` (n = 87, not credible) |
| Study B: `rgbw_light_jullison_wifi_7/9` | 3 % | Shelly Plus Wall Dimmer Study B (never toggled)? | **UNKNOWN**. The top lift was the staircase chandelier dimmer (0.96, n = 106 samples, one episode), a coincidence | — |
| Study A: `rgbw_light_jullison_wifi_6`, `_2`, `_3`, bare; Govee `study_a_table_lamp` | 0 % | — | **UNKNOWN** | — |
| Always reachable: `rgbw_garage_porch(_2)`, `rgb_white_light_jullison_wifi_studyaporch`/`studybporch`, `rgbw_lumary_wifi_tree1`, Tapo dimmers | 71–100 % | none (constant power) | n/a | — |

**Cross-check against the URA room config:** no URA room lists a Shelly or Sonoff relay *together with* a smart bulb,
except Patio (Sonoff patiolights + Jullison patio1–4).

---

## 3. Standby draw per circuit

**Not measurable for Shelly/Sonoff, because none feed smart bulbs** (see §0, test 3). The metered Shelly channels draw
a single fixed load when on and 0 W when off, so there is no "relay on, bulbs off" state to read.

The real gates:
- **Tapo S515D (kitchen):** exposes `sensor.dimmer_tapo_wifi_matter_kitchenoverhead_current_consumption`. The bulbs are
  only powered while the dimmer is on (and then lit), so standby cannot be isolated.
- **Inovelli mmWave (master):** `sensor.switch_mmwave_inovelli_power` reads 0 when off and 21–64 W when on (bulbs lit).
  Same limitation.
- **Dewenwils (landscape):** has only `*_total_energy`: landscape1 rose 267.13 → 272.07 kWh (≈ 4.9 kWh in 7 d),
  landscape2 479.78 → 485.71 kWh (≈ 5.9 kWh). These figures are lit-load energy, not standby.

**Planning figure (assumed, not measured):** about 0.3–0.5 W per Tuya Wi-Fi pot and 0.5–1 W per LIFX while powered and
off. That is roughly **2.6–4.4 kWh/yr per Tuya bulb** and **4.4–8.8 kWh/yr per LIFX** if kept powered 24/7. For the
three circuits that would be candidates for "always powered":

| Circuit | Bulbs | Est. standby W | kWh/yr if always on |
|---|---|---|---|
| Kitchen (Tapo) | 5 | 1.5–2.5 | 13–22 |
| Master (Inovelli) | 6 | 1.8–3 | 16–26 |
| Landscape (Dewenwils, all) | ~30 (incl. 10 LIFX) | 12–20 | 105–175, of which ~12 h/day is already powered, so the marginal cost is ~55–90 |

If a real number is needed: turn one gate on, command all its bulbs off, and read the Tapo/Inovelli power sensor for
5 minutes. That is a one-time operator action, not something this audit could do read-only.

---

## 4. Bulbs with no relay/gate match — classification

| Class | Entities | Basis |
|---|---|---|
| **Long gone / never reachable in 10 d** (the only state rows are `unavailable` written at each HA restart) | `maxxima_led_6_sq_slim_panel…`, `rgbw_smart_slim_pot_light_v2` (bare), `rgb_white_light_jullison_wifi` / `_2` / `_9` / `_10`, `rgbw_light_jullison_wifi` / `_2` / `_3` (unnamed), `rgbw_gklandscape_wifi_perimeter2`, `perimeter6`, LIFX `landscape4/8/9`, `landscape_entryright`, `frontpathtopleft`, `landscape_entry_mid_left`, `study_a_table_lamp` (Govee), balcony ×2 (+twins) | 0 samples available. Unnamed `_` devices are likely stale cloud registrations |
| **Behind a circuit that was off the whole window** (would come back if powered) | Dining ×4 (+5 cloud twins), Patio ×4 (+twins), Kitchen-dining ×3 (+twins) | Probable gates were never on in 10 d, or their device is offline |
| **Genuinely unreachable while powered (Wi-Fi)** | Landscape "weak" group (§2) | Flap at night every 50–105 s while the Dewenwils outlet is on. A detach changes nothing here; fix RF coverage or accept |
| **Duplicate integration twins** | Every Jullison/GK/FrontPath bulb has a `tuya` cloud entity and a `tuya_local` entity | Doubles the `setup_retry` count. Retiring one side roughly halves the noise |

---

## 5. Automations acting on these relays and bulbs (what a detach would break)

Enabled state as of now. Last-triggered was not recorded in the attributes.

| Automation | Enabled | Touches | What changes if the relay is detached |
|---|---|---|---|
| `automation.landscape_lighting_control` (sunset+60 min on; 01:30 main off; sunrise+30 min porch off) | **on** | Dewenwils ×6, GK, Hampton, LIFX landscape | Not a Shelly/Sonoff; detach does not apply. This is the "software power-off when idle" already in place |
| `automation.landscape_lighting_lifx_matter_version` ("New automation": sunset+30 min; 01:00; sunrise) | **on** | Same Dewenwils + LIFX-Matter entities | **Conflicts with the one above** (two schedules: 01:00 and 01:30). Observed offs at 01:00 and 01:30 match both |
| `automation.guest_toilet_automation2` | on | Shelly GuestToilet1/2 sw1–2 | Detach would leave fixture loads permanently powered. These are dumb fixtures, so **do not detach** |
| `automation.master_closet_storage_smart_lighting_v2` | on | Sonoff mastercloset, masterclosetstorage | Same: dumb loads |
| `automation.media_room_control_v1` | on | Shelly MediaRoom sw0/sw1 | Same |
| `automation.ziri_s_room_automation_v1` | on | Sonoff ziribedroom (turn_off only) | Same |
| Master Bedroom energy automations ×2 (Jullison master1–8) | off | bulbs only | — |
| Master bath ×5, master toilet ×2, master closet ×2, laundry ×2, Jaya room, upstairs guest (blueprint), down guest closet (blueprint), butler pantry (blueprint) | off | Shelly/Sonoff | — |

**URA rooms drive many of these relays directly** (from `core.config_entries`): e.g. Master Bathroom →
`shelly2pmg3_34cdb07765dc_switch_0/1` with night light `sonoff_1002197ef7_1`; Laundry → laundry1 sw1/sw2;
Powder → guesttoilet1 sw1/sw2, guesttoilet2 sw1; Master Closet(+Storage), Jaya/Ziri/Guest Bedroom 2, Exercise,
Upstairs Hallway, GB2 Hallway, Foyer, Patio → Sonoff relays; Kitchen → Tapo `kitchenoverhead` and Shelly KitchenGlobes;
Master Bedroom → Inovelli as a *manual switch*. After a detach, URA would toggle a relay whose load is already
powered and **the light would never go off**. This is the main breakage risk on any dumb-load circuit.

**Wall switch today:** on every Shelly/Sonoff channel the physical switch drives the relay directly (attached mode;
Sonoff `detach = off`; Shelly's input mode is not visible in HA, so "attached" is inferred from the relays following the wall switch). On the Tapo and Inovelli the switch *is*
the dimmer.

---

## 6. Per-circuit recommendation

| Circuit | Recommendation | Reason | Automation needed |
|---|---|---|---|
| **All metered Shelly channels** (MasterBath, GuestToilet, Laundry, ButlerPantry, DN/UpGuest baths, closets, vanities, Garage A, Ziri/Jaya bath, Kitchen Globes, Breakfast, Media) | **Leave as is** | Steady single-wattage loads are dumb fixtures, and detaching would leave them lit all the time | none |
| **Sonoff MINI R4M channels with toggle history and no bulb correlation** (MasterToilet, MasterCloset(+Storage), MasterBathLED, Jaya/Ziri Bedroom, UpGuest, Exercise, JayaBath, FrontDoor, GB Hallway, Foyer, LivingRoom, Ziri bath fan) | **Leave as is** | 8–72 cycles in 10 d with zero bulb co-drops: these feed dumb loads | none |
| **Sonoff PatioLights** (`switch_sonoffm4rm_matter_patiolights`) | **Detach, relay always on**, *after verifying* | Probable feed for Jullison patio1–4 (URA lists them together). Off for all 10 days, which explains why the bulbs never appear. Verify first: turn the relay on and see whether patio1–4 come online within 2 min | Detach automation: trigger `sensor.sonoff_1002193b5a_action` (single press) → `light.toggle` patio1–4. Then remove the Sonoff from URA Patio `lights` |
| **Shelly Dining1 G4 / Dining2 G4** (`dining1_overhead`, `dining2_recessed`, `dining2_divide`) | **Detach, relay always on**, *after verifying and bringing Dining1 back online* | Probable feed for Dining pots ("DiningDivide3" name). Dining1 is offline; Dining2 has been off for 10 days | Shelly detached + input → `light.toggle` the dining pot group. Then move the relays out of URA Dining `manual_switches` |
| **Kitchen MINI-2GS** (`sonoff_1002827400_1–4`) | **Investigate first** | Offline all 10 days. Might feed kitchen-dining pots (name only) | — |
| **Tapo S515D Kitchen** (not a relay) | **Keep powered; use smart-bulb behaviour** | CONFIRMED feed for kitchen pots. S515D has no detach, so leave it at 100 % and drive bulbs via an automation, or accept dimmer-cuts-power | Toggle the bulbs from the Tapo on/off event; take the Tapo out of the URA Kitchen `lights` list |
| **Inovelli mmWave Master** (not a relay) | **Set the Inovelli to smart-bulb mode** (`select.switch_mmwave_inovelli_smartbulbmode`; current value not captured here) | CONFIRMED feed for master pots. Smart-bulb mode is the Inovelli equivalent of detach | Bind or automate `sensor.switch_mmwave_inovelli_action` → `light.toggle` master pots |
| **Dewenwils landscape transformers** (not Shelly/Sonoff) | **Detach-equivalent: software power-off when idle**, which already exists | CONFIRMED feed for all landscape bulbs, and already scheduled by HA. **Action: merge the two conflicting enabled landscape automations into one** | n/a |
| **Master Bedroom Shelly 1PM** (always on, 57 W) | **Leave as is** | Steady 57 W load, not the pots | none |
| **Dead/duplicate bulbs (§4)** | **Remove** stale cloud and unnamed entries | ~30 % of the `setup_retry` noise | — |

**Blueprint/automation pattern for each detached circuit:** a trigger on the detached input (`sensor.<sonoff>_action`
state change, or the Shelly input `binary_sensor` / `event` for that channel) → `light.toggle` on a light group of the
circuit's bulbs, `mode: single`. Add a fallback so that while the bulbs are `unavailable`, a press turns the relay on
and retries after 30 s. The existing `custom/smart_knob_light_fan_z2m.yaml` and `AlanShezar/z2m_ts0041_event.yaml`
blueprints are Z2M-specific and do not fit as written.

---

## Method notes / limits

- The co-drop window of 10 s is too tight for `tuya_local`, which detects loss on a polling or keep-alive delay. The
  90 s and 150 s windows were also run and found nothing.
- The lift test can be confounded by night/day co-occurrence (e.g. `game_room_tv`, `q_series_soundbar` showed 0.8–0.9
  lift on a few yard bulbs with only ~67 on-samples). Those were rejected: they are not wired gates.
- Nothing was written to HA. Scripts ran over `ssh ha python3 -` with read-only sqlite URIs.
