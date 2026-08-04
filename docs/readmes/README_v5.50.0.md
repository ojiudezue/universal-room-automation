# v5.50.0 — Sleep-Onset Bedroom Fans + Working Warning Flash

## Sleep-onset fans (revival of a 2026-06-11 removal, operator-approved)
When the house enters sleep: occupied bedroom-family rooms at or above
`sleep_fan_on_temp_f` (CM → HVAC options; **deployed at 0 = DARK
tonight**, flip to 72 after the v5.48.0 attribution night) get comfort
fans turned on at the temp-delta-ladder speed, policy-capped
(fan_sleep_policy: normal=ladder, reduce=LOW cap, off=never). Works for
BOTH HVAC-managed and room-tier-owned fans (one shared predicate, two
call sites; Ziri included). Contracts: running fans NEVER touched (not
even speed — radar-transition hygiene); manual-off respected both
tiers; staggered turn-ons (5s); flap-proof latch + 6h re-arm (the 6AM
promotion replay yields one burst/night); boot is never an edge.

## Warning flash actually works now
The 10:55 PM warning before shared-space auto-off never fired anywhere
visible: it only dimmed light.* entities and the big common areas are
switch-relays (Kitchen, Game Room) or unlisted (Living Room). Switches
now flash via off/on cycling; the lights-on precheck counts switches;
both the auto-off and the flash write activity-log rows (previously
invisible at INFO).

## Review
docs/reviews/code-review/sleep_fans_and_flash_v5500.md — 3 reviews,
1 HIGH (boot-edge storm) + ladder-speed contract fix + latch isolation;
11 builder + 3 orchestrator mutation-reds. 42 tests, zero drift.

## Live Validation — prospective
- **Live:** boot clean; knob reads 0 (feature dark); no sleep_onset
  activity rows tonight.
- **Live (tomorrow):** flip knob 0→72 via options (NO restart — live-read
  verified); tomorrow night: staggered fan_on rows with trigger
  sleep_onset in warm occupied bedrooms; running/manual-off fans
  untouched; exactly one burst.
- **Live:** first 22:55 with Kitchen/Game Room lights on → flash rows +
  physically observed blink; 23:00 auto-off rows.
- **Live (carried):** v5.49.0 age-gate proof on this restart if
  feasible next boot.

### Validated 2026-08-03 (~17:20 CDT, v5.50.2 boot — carries v5.50.0/1)
| Criterion | Result | Evidence |
|---|---|---|
| Clean boot | **PASS** | v5.50.2 up in ~30s, no URA errors. |
| Feature DARK for attribution night | **PASS** | sleep_fan_on_temp_f=0.0 written via options API (the very API v5.50.0 broke — see below); all HVAC + NM options verified intact post-write. |
| Options-form regression | **FOUND + FIXED in-train** | v5.50.0 shipped the settings-form field WITHOUT its import → NameError render 500 (UI + API). v5.50.1 hotfix itself shipped a SyntaxError (deploy-gate process violation — py_compile red but deploy chained in the same command block; never reached HA). v5.50.2 correct + compile-gated + name-resolution pin test. Process rule hardened: deploy.sh in its own call after visible gate pass. |
| Tomorrow enable | pending | Flip knob 0→72 via same options call after tonight validates v5.48.0. |
