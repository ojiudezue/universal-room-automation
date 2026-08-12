# AUDIT — CONSOL-1 D0 Probe (measure-before-build gate)

Date: 2026-08-11 (probe run ~19:30–21:45 PT). Read-only toward URA/HA
config; 25 llmvision service calls consumed (budget: ≤25).
Plan: `PLANNING_consol_1_alerting_llmvision.md` §4 (D0.1/D0.2/D0.3).

---

## D0.1 — Working llmvision invocation shape (extracted VERBATIM)

Source: `/config/automations.yaml` (read via Samba mount
`/Users/okosisi/ha-config/automations.yaml`). Two automations call
llmvision; the operator's doorbell alert is
`automation.doorbell_detection_whatsapp_alert` (id `1770938962914`,
alias "Doorbell Detection WhatsApp Alert").

### Service call (verbatim YAML, doorbell automation)

```yaml
  - data:
      provider: 01KHB0EV5AP8ANWQ7RWT30M2CC
      message: Describe what you see in this image. What type of detection is this
        (person, vehicle, or animal)? Provide a brief, clear description.
      image_file: '{{ snapshot_path }}'
      max_tokens: 300
    response_variable: image_analysis
    action: llmvision.image_analyzer
```

### Consumption / WhatsApp threading (verbatim)

```yaml
  - data:
      number: '14258299520'
      message: "\U0001F6A8 {{ detection_type }} Detected at {{ camera_name }}\n\n\U0001F4F8
        {{ image_analysis.response_text }}"
      media_path: '{{ snapshot_path }}'
    action: whatsapp.send_message
```

Preceded by `camera.snapshot` (writes
`/config/www/doorbell_alerts/<Camera>_<Type>_<ts>.jpg`) and a
`delay: {seconds: 2}`. `mode: queued`, `max: 10`.

The second caller, `automation.phase_1_all_detections_dual_system`
("Phase 1: All Detections - Dual System (AI)", id `1770938962920`), uses
the same shape but with a LIST-valued `image_file:` (`- '{{ unifi_filepath }}'`)
and `max_tokens: 100`. **It is currently DISABLED**
(`automation_enabled: false`, last_triggered 2026-02-18) — the doorbell
automation is the only live caller.

### Provider config (from `.storage/core.config_entries`)

Provider ID `01KHB0EV5AP8ANWQ7RWT30M2CC` = llmvision **OpenAI** entry:
`"provider": "OpenAI"`, `"default_model": "gpt-5-mini"`,
`"temperature": 0.5`, `"top_p": 0.9` (entry created/modified
2026-02-13). A separate llmvision "Settings" entry carries system_prompt
(≤255-char event-description instruction) + title_prompt,
`fallback_provider: no_fallback`, `retention_time: 7.0`.

### Adapter contract (for D3)

- Service: `llmvision.image_analyzer` (call with `return_response`).
- Args: `provider` (config-entry id string), `message` (prompt),
  `image_file` (string or list; local file path readable by HA —
  `/media/ura/snapshots/...` works), `max_tokens` (int), optional
  `model` (overrides provider `default_model` — verified working).
- Response: `{"response_text": "<description>"}` via
  `response_variable` / `service_response`.

### CRITICAL D0.1 FINDING — the "working" automation is currently BROKEN

The live doorbell automation returns **empty** `response_text` today.
Trace `b89133514c1e6785db94e2399eab93a2` (2026-08-12T00:37Z,
front_door_aerial person): action/2 llmvision result
`{"image_analysis": {"response_text": ""}}`; the WhatsApp message sent
was `"🚨 Person Detected at Front Door\n\n📸"` — no AI text. All 3
recent traces identical.

Mechanism (probe-verified, not assumed): `gpt-5-mini` is a reasoning
model; its reasoning tokens consume the completion budget, so
`max_tokens: 300` (and 100) yields an empty visible completion.
Verified both directions:
- `max_tokens: 1500` on gpt-5-mini → full 200+ char description, ~4.5 s.
- `model: gpt-4o-mini`, `max_tokens: 300` → full description, ~1.5 s.

The provider entry was switched to gpt-5-mini on 2026-02-13; the
operator's doorbell descriptions have presumably been silently empty
since then. **D3's adapter must NOT copy the automation's
max_tokens=300 with the current default model.**

---

## D0.2 — Latency distribution on real snapshots

Method: 16 recent files sampled from `/media/ura/snapshots` (838 files,
back_yard / front_side_ptz / rear_ptz / utilities_ptz / hot_tub), each
sent through `llmvision.image_analyzer` with the doorbell automation's
provider + prompt shape via the HA REST API, wall-clock timed
(script: scratchpad `llmvision_probe.py`). Plus targeted shape probes.

### Batch (16 calls, provider default gpt-5-mini, max_tokens 100 → EMPTY responses)

| n | ok | err | min | p50 | p90 | p99/max | mean |
|---|----|-----|-----|-----|-----|---------|------|
| 16 | 16 | 0 | 1.46 s | 1.74 s | 2.35 s | 3.60 s | 1.90 s |

Caveat: these calls "succeeded" HTTP-wise but returned empty
response_text (reasoning-truncated), so they under-measure a *useful*
call. Treat as a lower bound only.

### Useful-response samples (non-empty text)

| Shape | Samples (s) | Approx. |
|---|---|---|
| gpt-5-mini, max_tokens 1500 | 4.65, 4.06, 4.47 | ~4.0–4.7 s |
| gpt-4o-mini, max_tokens 300 | 1.43, 1.62, 1.98 | ~1.4–2.0 s |

Failure count across all 25 calls: **0** (no HTTP/service errors).

### Timeout-knob recommendation (`perimeter_enrichment_timeout_s`)

- If adapter pins `model: gpt-4o-mini` (recommended): observed max
  ~2.0 s → **default 4.0 s stands** (p90 + ~2x margin). Plan gate
  "p90 ≤ 4 s and error rate < 5 %" is met.
- If gpt-5-mini (provider default) is kept with max_tokens ≥ 1500:
  observed ~4.7 s max on n=3 → 4.0 s default would clip; set **6–8 s**.
  Plan's "intermediate: retimeout per data" branch applies.

---

## D0.3 — Cost accounting

Dispatched-alert rate, URA `notification_log` (read-only, via ssh on
the live DB):

- `hazard_type IN ('exterior_person','exterior_vehicle')`: **219 rows**,
  all `exterior_person`, 0 `exterior_vehicle`.
- Data span is only 5.7 days (first row 2026-08-06T05:57Z — perimeter
  logging began then; a full 14-day window does not exist yet).
- Daily: 08-06: 6, 08-07: 18, 08-08: 90, 08-09: 30, 08-10: 45, 08-11: 30.
- **Mean ≈ 38/day; median day ≈ 30; peak day 90.**

Per-call cost (OpenAI list pricing; token counts estimated —
llmvision does not expose usage in the service response):
snapshot images are small (26–85 KB, single tile).

| Model | Est. tokens/call | Est. $/call | @38/day (mo) | @90/day (mo) |
|---|---|---|---|---|
| gpt-5-mini ($0.25/M in, $2/M out), max_tokens 1500, ~500–1000 reasoning+text out | ~1–2 k in + ~1 k out | ~$0.002–0.003 | ~$2.5–3.5 | ~$6–8 |
| gpt-4o-mini ($0.15/M in, $0.60/M out; image-token multiplier makes images ≈ gpt-4o-priced) | image-dominated | ~$0.003–0.008 | ~$4–9 | ~$9–22 |

Both are single-digit-dollars/month at the measured rate. Cost is NOT
the binding constraint; the 50-calls/day default-ON gate is:
- Mean 38/day < 50 → gate passes on average, BUT that is the
  **all-perimeter** rate; peak day (08-08) was 90.
- Enrichment scoped to the two doorbell cams only (plan §alternative)
  would be well under the gate.

---

## Verdicts

| Probe | Verdict | Basis |
|---|---|---|
| **D0.1 (gates D3 buildability)** | **GO — with mandatory ADJUST** | Invocation shape extracted and probe-verified end-to-end (service, args, response_variable, WhatsApp threading). BUT the reference automation is itself silently broken (empty response_text since the 2026-02-13 gpt-5-mini switch). D3's adapter must either pin `model: gpt-4o-mini` or raise max_tokens to ≥1500 for gpt-5-mini, and MUST treat empty `response_text` as a failure (fall through to unenriched message) — "HTTP OK + empty text" is a real observed mode, not hypothetical. |
| **D0.2 (gates timeout default)** | **GO / ADJUST default per model choice** | 0 errors in 25 calls. gpt-4o-mini: max ~2.0 s → keep 4.0 s default. gpt-5-mini@1500: ~4.0–4.7 s → default 6.0 s (range 1–15 stands). |
| **D0.3 (gates default-ON policy)** | **GO for doorbell-cams default-ON; ADJUST (keep default OFF) for full perimeter** | Mean 38/day all-perimeter (< 50 gate) but only 5.7 days of data and one 90/day spike; two-cam scope is comfortably under. Cost immaterial (< $10/mo worst case). Re-check rate after a full 14 days of notification_log data. |

### Operator flag (out of CONSOL-1 scope, worth a hotfix)

The production doorbell WhatsApp alert has been sending image-only
messages (no AI description) — fix is a one-line automation change
(`max_tokens: 300` → `1500`, or add `model: gpt-4o-mini` to the call/
provider). Independent of this cycle.
