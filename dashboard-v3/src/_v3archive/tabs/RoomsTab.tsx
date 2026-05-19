/**
 * Rooms tab -- room-centric view with device controls.
 * Shows floor plan, room cards with health/occupancy, expandable light/climate controls.
 */
import { useMemo } from "react";
import { Lightbulb, Activity, LayoutGrid } from "lucide-react";
import { useHass } from "@hakit/core";
import { RoomCard } from "../rooms/RoomCard";
import { color, space, type as typography } from "../../design/tokens";

interface EntityLike {
  state: string;
  attributes: Record<string, unknown>;
  last_changed?: string;
  last_updated?: string;
}

export function RoomsTab() {
  const { getAllEntities } = useHass();
  const allEntities = getAllEntities() as Record<string, EntityLike>;

  const rooms = useMemo(() => {
    // Get canonical room list from automation_health sensors
    const healthSensors = Object.entries(allEntities)
      .filter(([id]) => id.includes("automation_health") && id.startsWith("sensor."))
      .map(([id, e]) => ({
        id,
        room: String(e.attributes?.room_name ?? id.replace("sensor.ura_", "").replace("_automation_health", "")),
        state: e.state,
      }));

    // All lights
    const allLights = Object.entries(allEntities)
      .filter(([id]) => id.startsWith("light.") && !id.includes("notification"))
      .map(([id, e]) => ({
        id,
        name: String(e.attributes?.friendly_name ?? id.replace("light.", "")),
        state: e.state,
        brightness: e.attributes?.brightness as number | undefined,
      }));

    // All climate
    const allClimate = Object.entries(allEntities)
      .filter(([id]) => id.startsWith("climate."))
      .map(([id, e]) => ({
        id,
        name: String(e.attributes?.friendly_name ?? id.replace("climate.", "")),
        state: e.state,
        currentTemp: e.attributes?.current_temperature as number | undefined,
        targetTemp: e.attributes?.temperature as number | undefined,
        hvacAction: (e.attributes?.hvac_action ?? e.attributes?.action) as string | undefined,
      }));

    // Motion sensors
    const motionSensors = Object.entries(allEntities)
      .filter(([id]) =>
        id.startsWith("binary_sensor.") &&
        (id.includes("motion") || id.includes("occupancy")) &&
        !id.includes("ura_")
      )
      .map(([id, e]) => ({ id, state: e.state }));

    // Build rooms
    const roomMap: Record<string, {
      name: string;
      displayName: string;
      health: string;
      lights: typeof allLights;
      climate: typeof allClimate;
      motionActive: boolean;
    }> = {};

    for (const hs of healthSensors) {
      const roomKey = hs.room.toLowerCase().replace(/\s+/g, "_");
      const displayName = hs.room
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase());

      const roomWords = roomKey.split("_").filter((w) => w.length > 2);
      const matchesRoom = (entityId: string, entityName: string) => {
        const lower = (entityId + " " + entityName).toLowerCase();
        return roomWords.some((w) => lower.includes(w));
      };

      roomMap[roomKey] = {
        name: roomKey,
        displayName,
        health: hs.state,
        lights: allLights.filter((l) => matchesRoom(l.id, l.name)),
        climate: allClimate.filter((c) => matchesRoom(c.id, c.name)),
        motionActive: motionSensors.some((m) => {
          const lower = m.id.toLowerCase();
          return roomWords.some((w) => lower.includes(w)) && m.state === "on";
        }),
      };
    }

    // Unassigned lights
    const assigned = new Set(Object.values(roomMap).flatMap((r) => r.lights.map((l) => l.id)));
    const unassigned = allLights.filter((l) => !assigned.has(l.id));
    if (unassigned.length > 0) {
      roomMap["_other"] = {
        name: "_other",
        displayName: "Other Lights",
        health: "ok",
        lights: unassigned,
        climate: [],
        motionActive: false,
      };
    }

    return Object.values(roomMap).sort((a, b) => a.displayName.localeCompare(b.displayName));
  }, [allEntities]);

  // Summary
  const totalLightsOn = rooms.reduce((n, r) => n + r.lights.filter((l) => l.state === "on").length, 0);
  const totalLights = rooms.reduce((n, r) => n + r.lights.length, 0);
  const healthyRooms = rooms.filter(
    (r) => r.health === "excellent" || r.health === "good" || r.health === "ok"
  ).length;
  const activeMotion = rooms.filter((r) => r.motionActive).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Stats bar */}
      <div style={{
        display: "flex",
        gap: space.lg,
        flexWrap: "wrap",
        fontSize: typography.size.sm,
        color: color.text.tertiary,
      }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Lightbulb size={13} />
          {totalLightsOn}/{totalLights} lights on
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Activity size={13} />
          {activeMotion} rooms active
        </span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <LayoutGrid size={13} />
          {healthyRooms}/{rooms.length} healthy
        </span>
      </div>

      {/* Room Cards Grid */}
      <div
        className="rooms-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: space.sm,
        }}
      >
        {rooms.map((room) => (
          <RoomCard key={room.name} {...room} />
        ))}
      </div>
      <style>{`
        @media (max-width: 700px) {
          .rooms-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}
