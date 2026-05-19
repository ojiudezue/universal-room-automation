/**
 * Music following summary with toggleable room switches.
 */
import { useMemo } from "react";
import { Music } from "lucide-react";
import { useEntitiesByPrefix } from "../../hooks/useEntity";
import { Toggle } from "../shared/Toggle";
import { color, space, radius, type as typography } from "../../design/tokens";

export function MusicFollowing() {
  const musicSwitches = useEntitiesByPrefix("switch.");

  const musicEntities = useMemo(
    () =>
      musicSwitches.filter((e) => e.entity_id.includes("music_following")),
    [musicSwitches]
  );

  if (musicEntities.length === 0) return null;

  const activeCount = musicEntities.filter((m) => m.state === "on").length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div style={{
          fontSize: typography.size.xs,
          fontWeight: typography.weight.semibold,
          color: color.text.tertiary,
          textTransform: "uppercase",
          letterSpacing: "0.6px",
        }}>
          Music Following
        </div>
        <span style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          fontSize: typography.size.xs,
          fontWeight: typography.weight.semibold,
          color: activeCount > 0 ? color.accent.primary : color.text.tertiary,
        }}>
          <Music size={12} />
          {activeCount}/{musicEntities.length} active
        </span>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        gap: space.xs,
      }}>
        {musicEntities.map((m) => {
          const name = String(m.attributes.friendly_name ?? m.entity_id)
            .replace("URA ", "")
            .replace("Music Following ", "")
            .replace(/_/g, " ");
          const isActive = m.state === "on";

          return (
            <div
              key={m.entity_id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: space.sm,
                padding: `${space.sm}px ${space.md}px`,
                borderRadius: radius.sm,
                background: isActive ? "rgba(130, 177, 255, 0.08)" : "rgba(255, 255, 255, 0.02)",
                borderLeft: isActive ? `2px solid ${color.accent.primary}` : "2px solid transparent",
              }}
            >
              <Music
                size={14}
                style={{ color: isActive ? color.accent.primary : color.text.disabled }}
              />
              <span style={{
                flex: 1,
                fontSize: typography.size.sm,
                color: color.text.secondary,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {name}
              </span>
              <Toggle
                entityId={m.entity_id}
                currentState={m.state}
                size="sm"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
