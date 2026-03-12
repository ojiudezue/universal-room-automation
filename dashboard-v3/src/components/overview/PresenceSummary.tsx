/**
 * Compact presence summary for the Overview tab.
 * Shows who's home/away with avatars and a total property count.
 */
import { useMemo } from "react";
import { Users, MapPin } from "lucide-react";
import { useEntitiesByPrefix, formatState } from "../../hooks/useEntity";
import { color, space, radius, type as typography } from "../../design/tokens";

export function PresenceSummary() {
  const persons = useEntitiesByPrefix("person.");

  const { home, away } = useMemo(() => {
    const h = persons.filter((p) => p.state === "home");
    const a = persons.filter((p) => p.state !== "home");
    return { home: h, away: a };
  }, [persons]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      {/* Home */}
      <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: space.xs,
          color: color.status.green,
          fontSize: typography.size.sm,
          fontWeight: typography.weight.semibold,
        }}>
          <Users size={14} />
          <span>{home.length} home</span>
        </div>
        <div style={{ display: "flex", gap: space.xs, flexWrap: "wrap" }}>
          {home.map((p) => (
            <PersonChip
              key={p.entity_id}
              name={String(p.attributes.friendly_name ?? p.entity_id.replace("person.", ""))}
              picture={p.attributes.entity_picture as string | undefined}
              isHome
            />
          ))}
        </div>
      </div>

      {/* Away */}
      {away.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: space.xs,
            color: color.status.yellow,
            fontSize: typography.size.sm,
            fontWeight: typography.weight.semibold,
          }}>
            <MapPin size={14} />
            <span>{away.length} away</span>
          </div>
          <div style={{ display: "flex", gap: space.xs, flexWrap: "wrap" }}>
            {away.map((p) => (
              <PersonChip
                key={p.entity_id}
                name={String(p.attributes.friendly_name ?? p.entity_id.replace("person.", ""))}
                picture={p.attributes.entity_picture as string | undefined}
                isHome={false}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PersonChip({
  name,
  picture,
  isHome,
}: {
  name: string;
  picture?: string;
  isHome: boolean;
}) {
  const chipColor = isHome ? color.status.green : color.status.yellow;
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: space.xs,
        padding: `2px ${space.sm}px 2px 2px`,
        borderRadius: radius.full,
        background: `${chipColor}18`,
        border: `1px solid ${chipColor}30`,
        fontSize: typography.size.sm,
        color: color.text.primary,
      }}
    >
      <div
        style={{
          width: 22,
          height: 22,
          borderRadius: radius.full,
          background: chipColor,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          fontSize: typography.size.xs,
          fontWeight: typography.weight.bold,
          color: "#fff",
          flexShrink: 0,
        }}
      >
        {picture ? (
          <img
            src={picture}
            alt={name}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          name.charAt(0).toUpperCase()
        )}
      </div>
      <span style={{ fontWeight: typography.weight.medium }}>{name}</span>
    </div>
  );
}
