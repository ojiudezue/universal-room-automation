# Documentation File Reference

Each file lives in `/docs` unless otherwise noted. Claude reads this file for detailed guidance on what each doc covers and when to update it.

| File | Purpose | Update when... |
|---|---|---|
| `architecture-overview.md` | Top-level system map: HA integration, coordinators, database, external services, MCP servers. Include a high-level Mermaid component diagram. | Adding/removing a coordinator, database, external integration, or MCP server |
| `data-flow.md` | Data lifecycle: HA entities → coordinators → actions/sensors. Mermaid flowcharts for each major pipeline (presence, energy, HVAC, security, notifications). | Adding a new data source, coordinator signal, or action pipeline |
| `data-model.md` | All persistent data: SQLite tables, config entries, in-memory state. Schema, relationships, migration patterns. | Any schema change, new table, or config entry type change |
| `coordinator-map.md` | All domain coordinators: role, priority, owned entities, published signals, consumed signals, sensor list. | Adding/removing/modifying a coordinator |
| `config-map.md` | Config flow steps, options flow steps, all CONF_* constants, their types and defaults. | Adding/changing config flow steps or options |
| `dependency-graph.md` | Internal module dependencies: which files import from which, coordinator cross-references, signal flow. Mermaid flowcharts. | Changing module dependencies or coordinator interactions |
