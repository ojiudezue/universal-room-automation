# NM Routing Audit Card (Cycle C-2 D4)

Small Lovelace markdown card showing the last ~10 routing decisions
(who / what / why) for matrix-authoring feedback. Ship this on a new
NM tab on the ura-v7 dashboard.

The audit-log data source is the `NotificationManager`'s in-memory
`_routing_audit_log` ring buffer, surfaced via the
`nm_routing_audit_recent` attribute on
`sensor.ura_notification_manager_notification_diagnostics` (attribute-carrier, populated by NM
Cycle C — see `notification_manager.py` `_publish_routing_audit`).

If the attribute is not yet populated on your instance (an older Cycle-C
build), replace the card body with a `custom:auto-entities` variant
that queries the URA websocket API `ura/nm/audit_recent`.

## Apply-via-MCP snippet

```yaml
# Add this card to the ura-v7 dashboard under a new "Notifications" tab.
# Apply via MCP `ha_update_dashboard` — dashboards live in HA storage,
# not this repo.
type: markdown
title: "NM Routing — Recent Decisions"
content: |
  {% set audit = state_attr('sensor.ura_notification_manager_notification_diagnostics',
                            'nm_routing_audit_recent') or [] %}
  {% if audit | length == 0 %}
  _No recent routing decisions._ Author a routing matrix under
  **Settings → Devices & services → URA → Configure → Coordinator
  Manager → Notification Routing (Cycle C-2)** to seed decisions.
  {% else %}
  | When | Recipient | Hazard / Sev | Channels fired | Suppressed by |
  |---|---|---|---|---|
  {% for row in audit[-10:] | reverse %}
  | {{ as_timestamp(row.at) | timestamp_custom('%H:%M:%S', True) }} |
  {{ row.person or 'global' }} |
  {{ row.hazard or '—' }} / {{ row.severity }} |
  {{ (row.channels_fired or []) | join(', ') or '—' }} |
  {{ row.suppressed_reason or '—' }} |
  {% endfor %}
  {% endif %}
```

## Fallback (websocket API)

```yaml
type: custom:auto-entities
card:
  type: markdown
  title: "NM Routing — Recent Decisions"
filter:
  template: |
    {% set audit = states | selectattr('entity_id', 'eq',
       'sensor.ura_notification_manager_notification_diagnostics') | list %}
    {{ audit }}
```

## Deploy notes

- Not committed to `dashboards/` in this repo; dashboards live in HA
  storage (`.storage/lovelace_*`). Apply via MCP `ha_update_dashboard`.
- If the operator ships this card BEFORE running the entity-rename
  script (see AUDIT_nm_rename_impact.md), the `sensor.ura_notification_manager_notification_diagnostics`
  reference here is stable. If the rename script is run, update this
  markdown to `sensor.ura_nm_summary` in the same edit.
- Card refresh cadence: markdown cards re-evaluate on any state change
  of referenced entities — the audit attribute updates on every routing
  decision, so the card is effectively live.
