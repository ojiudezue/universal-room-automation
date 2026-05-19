---
description: Run a URA code review via ura-reviewer agent. For Tier 2 cycles, run this command TWICE in parallel with different framings.
---

Use the `ura-reviewer` agent to adversarially review the current cycle.

**Cycle / version + framing:** $ARGUMENTS

**For Tier 1 cycles:** invoke once with framing `"correctness + edge cases"`.

**For Tier 2 cycles:** invoke TWICE IN PARALLEL with different framings. Recommended pair:
- Reviewer A: `"correctness + edge cases + bug class hits"`
- Reviewer B: `"async + lifecycle + race conditions + restart resilience"`

**For Tier 2-DB cycles:** invoke THREE TIMES IN PARALLEL per the Tier 2-DB protocol in CLAUDE.md:
- Reviewer A: `"data integrity + DB architecture preservation"`
- Reviewer B: `"migration correctness + signal chain integrity"`
- Reviewer C: `"new surfaces + test fixture authority"`

**Required output per reviewer:**

```
## CRITICAL (must fix before deploy)
1. [Title] — file:line. [What + why critical + suggested fix]

## HIGH (must fix before deploy)
1. ...

## MEDIUM (should fix this cycle)
1. ...

## LOW / NITS (defer to next cycle or backlog)
1. ...

## Verdict
[PASS / PASS WITH FIXES / FAIL] — [one-line summary]
```

Each finding must include:
- The **bug class** (existing class from `docs/QUALITY_CONTEXT.md` or a proposed new class name)
- file:line reference
- Suggested fix (concrete code or pattern)

Don't soften findings. If something is dead code, call it dead code. Better to over-flag than ship a regression.

Pre-read (mandatory):
- The cycle's planning doc
- `docs/QUALITY_CONTEXT.md`
- The diff: `git diff pre-review-v<version>..HEAD`
- Builder's deviation report (if any was reported)

Under 800 words total. Concise findings, file:line refs, suggested fixes.
