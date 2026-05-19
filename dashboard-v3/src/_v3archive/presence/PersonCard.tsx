/**
 * Person card showing location, detection source, and recent transitions.
 */
import { User, MapPin, Radio, ArrowRight } from "lucide-react";
import { formatState, timeAgo } from "../../hooks/useEntity";
import { StatusBadge } from "../shared/StatusBadge";
import { color, space, radius, type as typography } from "../../design/tokens";

interface PersonData {
  entity_id: string;
  name: string;
  state: string;
  picture?: string;
  source?: string;
  lastChanged?: string;
  transitions?: Array<{ from?: string; to?: string; time?: string }>;
}

interface Props {
  person: PersonData;
}

export function PersonCard({ person }: Props) {
  const isHome = person.state === "home";
  const accentColor = isHome ? color.status.green : color.status.yellow;

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        padding: `${space.md}px`,
        borderRadius: radius.md,
        background: "rgba(255, 255, 255, 0.03)",
        borderLeft: `3px solid ${accentColor}`,
      }}
    >
      {/* Left: Avatar + details */}
      <div style={{ display: "flex", gap: space.md, alignItems: "flex-start" }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: radius.full,
            background: accentColor,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            flexShrink: 0,
            overflow: "hidden",
          }}
        >
          {person.picture ? (
            <img
              src={person.picture}
              alt={person.name}
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          ) : (
            <User size={20} />
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{
            fontSize: typography.size.base,
            fontWeight: typography.weight.semibold,
            color: color.text.primary,
          }}>
            {person.name}
          </span>
          <span style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            fontSize: typography.size.sm,
            color: color.text.secondary,
          }}>
            <MapPin size={11} />
            {formatState(person.state)}
            {person.lastChanged && (
              <span style={{ color: color.text.tertiary, marginLeft: 4 }}>
                {timeAgo(person.lastChanged)}
              </span>
            )}
          </span>
          {person.source && (
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              fontSize: typography.size.xs,
              color: color.text.tertiary,
            }}>
              <Radio size={10} />
              {person.source.replace("device_tracker.", "")}
            </span>
          )}
        </div>
      </div>

      {/* Right: status + transitions */}
      <div style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-end",
        gap: space.xs,
      }}>
        <StatusBadge value={person.state} />
        {person.transitions?.slice(0, 2).map((t, i) => (
          <div
            key={i}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              fontSize: typography.size.xs,
              color: color.text.tertiary,
            }}
          >
            {t.from} <ArrowRight size={9} /> {t.to}
            {t.time && (
              <span style={{ marginLeft: 3 }}>{timeAgo(t.time)}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
