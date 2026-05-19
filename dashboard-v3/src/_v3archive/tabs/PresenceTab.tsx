/**
 * Presence tab -- detailed multi-layer presence view.
 * Shows persons, BLE, cameras, motion, zone occupancy, transitions, music following.
 */
import { useMemo } from "react";
import { Users, MapPin, Activity } from "lucide-react";
import { useEntity, useEntitiesByPrefix, formatState } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import { PersonCard } from "../presence/PersonCard";
import { DetectionLayers } from "../presence/DetectionLayers";
import { RoomTransitions } from "../presence/RoomTransitions";
import { MusicFollowing } from "../presence/MusicFollowing";
import { color, space, type as typography } from "../../design/tokens";

const HOUSE_STATE_ID = "sensor.ura_presence_coordinator_presence_house_state";

export function PresenceTab() {
  const houseState = useEntity(HOUSE_STATE_ID);
  const attrs = houseState.attributes as Record<string, unknown>;
  const persons = useEntitiesByPrefix("person.");

  const personData = useMemo(() => {
    const transitions = (attrs.recent_transitions ?? []) as Array<{
      person?: string;
      from?: string;
      to?: string;
      time?: string;
    }>;

    return persons.map((p) => {
      const name = String(p.attributes.friendly_name ?? p.entity_id.replace("person.", ""));
      return {
        entity_id: p.entity_id,
        name,
        state: p.state,
        picture: p.attributes.entity_picture as string | undefined,
        source: p.attributes.source as string | undefined,
        lastChanged: p.last_changed,
        transitions: transitions.filter(
          (t) => t.person?.toLowerCase() === name.toLowerCase()
        ),
      };
    });
  }, [persons, attrs]);

  const homeCount = personData.filter((p) => p.state === "home").length;
  const awayCount = personData.filter((p) => p.state !== "home").length;
  const censusCount = attrs.census_count as number | undefined;
  const confidence = attrs.confidence as number | undefined;

  // Motion sensor count
  const allBinary = useEntitiesByPrefix("binary_sensor.");
  const activeMotion = useMemo(
    () =>
      allBinary.filter(
        (e) =>
          (e.entity_id.includes("motion") || e.entity_id.includes("occupancy")) &&
          !e.entity_id.includes("ura_") &&
          e.state === "on"
      ).length,
    [allBinary]
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Header bar */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: space.sm,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: space.md }}>
          <StatusBadge value={houseState.state} size="md" />
          <div style={{
            display: "flex",
            gap: space.md,
            fontSize: typography.size.sm,
            color: color.text.tertiary,
          }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Users size={13} /> {homeCount} home
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <MapPin size={13} /> {awayCount} away
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <Activity size={13} /> {activeMotion} motion
            </span>
          </div>
        </div>

        {/* Census + confidence */}
        <div style={{
          display: "flex",
          gap: space.md,
          fontSize: typography.size.sm,
          color: color.text.tertiary,
        }}>
          {censusCount != null && (
            <span>Census: {censusCount}</span>
          )}
          {confidence != null && (
            <span>Confidence: {confidence}%</span>
          )}
        </div>
      </div>

      {/* People */}
      <GlassCard title="People" subtitle={`${homeCount} home, ${awayCount} away`}>
        <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
          {personData.map((p) => (
            <PersonCard key={p.entity_id} person={p} />
          ))}
          {personData.length === 0 && (
            <div style={{
              padding: space.lg,
              color: color.text.tertiary,
              fontSize: typography.size.sm,
              textAlign: "center",
            }}>
              No person entities found
            </div>
          )}
        </div>
      </GlassCard>

      {/* Detection Layers */}
      <DetectionLayers />

      {/* Zone Occupancy + Transitions */}
      <GlassCard title="Zones & Transitions">
        <RoomTransitions />
      </GlassCard>

      {/* Music Following */}
      <GlassCard>
        <MusicFollowing />
      </GlassCard>
    </div>
  );
}
