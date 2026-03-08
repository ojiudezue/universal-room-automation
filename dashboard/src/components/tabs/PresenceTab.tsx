import { useMemo } from "react";
import { useHass } from "@hakit/core";
import { usePresenceData } from "../../hooks/usePresenceData";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";

function fmt(v: string | undefined): string {
  if (!v || v === "unknown" || v === "unavailable") return "--";
  return v.replace(/_/g, " ");
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function PresenceTab() {
  const { getAllEntities } = useHass();
  const { houseState } = usePresenceData();
  const allEntities = getAllEntities();

  // Person entities (memoized)
  const persons = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.startsWith("person."))
      .map(([id, e]) => ({
        id,
        state: e.state,
        name: e.attributes?.friendly_name ?? id.replace("person.", ""),
        lastChanged: e.last_changed,
        source: e.attributes?.source as string | undefined,
        entityPicture: e.attributes?.entity_picture as string | undefined,
      })),
    [allEntities]
  );

  // Zone occupancy from house state attributes
  const houseAttrs = houseState.attributes ?? {};
  const zoneOccupancy = (houseAttrs.zone_occupancy ?? houseAttrs.zones ?? {}) as Record<string, number | string>;
  const transitions = (houseAttrs.recent_transitions ?? []) as Array<{
    person?: string; from?: string; to?: string; time?: string;
  }>;

  // Music following entities (memoized)
  const musicEntities = useMemo(() =>
    Object.entries(allEntities)
      .filter(([id]) => id.includes("music_following") && id.startsWith("switch."))
      .map(([id, e]) => ({ id, name: e.attributes?.friendly_name ?? id, state: e.state })),
    [allEntities]
  );

  return (
    <div>
      {/* House State Hero */}
      <div className="hero-section">
        <h1 className="hero-greeting">Presence</h1>
        <StatusBadge value={houseState.state} large />
      </div>

      {/* Persons Grid */}
      <GlassCard title="People" subtitle={`${persons.filter(p => p.state === "home").length} home`}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {persons.map(p => (
            <div className="person-card" key={p.id}>
              <div
                className="person-avatar"
                style={{
                  background: p.state === "home" ? "var(--status-green)" : "var(--status-yellow)",
                }}
              >
                {p.name.charAt(0).toUpperCase()}
              </div>
              <div className="person-info">
                <div className="person-name">{p.name}</div>
                <div className="person-detail">
                  {fmt(p.state)}
                  {p.lastChanged && (
                    <span style={{ marginLeft: 8, opacity: 0.7 }}>
                      {timeAgo(p.lastChanged)}
                    </span>
                  )}
                </div>
                {/* Recent transitions for this person */}
                {transitions
                  .filter(t => t.person?.toLowerCase() === p.name.toLowerCase())
                  .slice(0, 2)
                  .map((t, i) => (
                    <div key={i} style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.4)", marginTop: 2 }}>
                      {t.from} &rarr; {t.to}
                      {t.time && <span style={{ marginLeft: 6 }}>{timeAgo(t.time)}</span>}
                    </div>
                  ))
                }
              </div>
              <StatusBadge value={p.state} />
            </div>
          ))}
          {persons.length === 0 && (
            <div style={{ color: "rgba(255,255,255,0.4)", fontSize: "0.85rem", textAlign: "center", padding: 16 }}>
              No person entities found
            </div>
          )}
        </div>
      </GlassCard>

      {/* Zone Occupancy */}
      {Object.keys(zoneOccupancy).length > 0 && (
        <div style={{ marginTop: 16 }}>
          <GlassCard title="Zone Occupancy" compact>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {Object.entries(zoneOccupancy).map(([zone, count]) => (
                <div
                  key={zone}
                  style={{
                    padding: "8px 16px",
                    background: Number(count) > 0 ? "rgba(129,199,132,0.15)" : "rgba(255,255,255,0.04)",
                    borderRadius: "var(--radius-md)",
                    display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
                    minWidth: 80,
                  }}
                >
                  <span style={{ fontSize: "1.2rem", fontWeight: 600 }}>{count}</span>
                  <span className="metric-label">{zone.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>
          </GlassCard>
        </div>
      )}

      {/* Music Following */}
      {musicEntities.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <GlassCard title="Music Following" compact>
            {musicEntities.map(m => (
              <div className="info-row" key={m.id}>
                <span className="info-label">{m.name.replace("URA ", "").replace("Music Following ", "")}</span>
                <StatusBadge value={m.state} />
              </div>
            ))}
          </GlassCard>
        </div>
      )}
    </div>
  );
}
