# DRAFT: Optimizer "meta" findings no longer page (OPTIMIZER-META-NEVER-PAGES-1)

## What changed
About every two to three days the optimizer's AI layer raised a CRITICAL "URA Optimizer — meta" alert on Pushover, WhatsApp, the companion app and iMessage. It complained that its own input had been trimmed ("findings_recent is truncated, running blind"). In the 30 days to 2026-11-04 this happened 9 times, and all 9 were this complaint. Several went out between 1 and 2:30 am. None was about the house.

`_notify_if_severe` (domain_coordinators/optimization.py) now returns before paging when a finding's dimension is META. Enum values, strings and any letter case are treated the same. META findings are still saved and still appear in the digest and on the dashboards. Only the page is gone. The only non-AI META producer is the low-severity `cycle_ok` sentinel, which never paged anyway. There is no new knob. Ticking "meta" in the HIGH-page allowlist now has no effect, and the constant's comment says so.

Review: Tier 1, SHIP (`docs/reviews/code-review/optimizer_meta_never_pages_review.md`). Two LOW findings, both fixed.
Tests: `quality/tests/test_optimizer_meta_never_pages.py`, mutation-anchored (removing the guard turns 4 tests red). The source-text test `test_optimizer_consumer_wired_to_should_defer_helper` was replaced by the behavioural `test_high_finding_honours_should_defer_helper`.

## Live acceptance (prospective)
| Criterion | How to check |
|---|---|
| No meta pages | `notification_log`: no `title='URA Optimizer — meta'` rows after the restart |
| Meta still recorded | `optimization_findings`: META rows from the AI tier still appear when it emits them |
| Other optimizer pages unchanged | A critical `sensor_health` finding still pages (none expected on demand; proven in-suite) |
| Load clean | No URA ERROR after restart |
