/**
 * Detection layers: BLE, Motion, Camera detections in a compact grid.
 */
import { useMemo } from "react";
import { Bluetooth, Activity, Camera } from "lucide-react";
import { useEntitiesByPrefix, timeAgo } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { color, space, radius, type as typography } from "../../design/tokens";

export function DetectionLayers() {
  // BLE / Bermuda
  const allSensors = useEntitiesByPrefix("sensor.");
  const bleDevices = useMemo(
    () =>
      allSensors.filter(
        (e) =>
          (e.entity_id.includes("bermuda") || e.entity_id.includes("ble_")) &&
          !e.entity_id.includes("ura_")
      ),
    [allSensors]
  );

  // Motion / occupancy
  const allBinary = useEntitiesByPrefix("binary_sensor.");
  const motionSensors = useMemo(
    () =>
      allBinary.filter(
        (e) =>
          (e.entity_id.includes("motion") || e.entity_id.includes("occupancy")) &&
          !e.entity_id.includes("ura_")
      ),
    [allBinary]
  );
  const activeMotion = motionSensors.filter((m) => m.state === "on");

  // Camera detections
  const cameras = useEntitiesByPrefix("camera.");
  const activeDetections = useMemo(
    () => cameras.filter((c) => c.state === "recording" || c.state === "streaming"),
    [cameras]
  );

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: space.sm,
      }}
      className="detection-grid"
    >
      <style>{`
        @media (max-width: 700px) {
          .detection-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>

      {/* Motion */}
      <GlassCard
        title="Motion"
        badge={
          <CountBadge
            count={activeMotion.length}
            total={motionSensors.length}
            icon={<Activity size={12} />}
            active={activeMotion.length > 0}
          />
        }
      >
        <DetectionList
          items={motionSensors.map((m) => ({
            id: m.entity_id,
            name: String(m.attributes.friendly_name ?? m.entity_id).replace("binary_sensor.", "").replace(/_/g, " "),
            active: m.state === "on",
            time: m.last_changed,
          }))}
          icon={<Activity size={12} />}
          emptyText="No motion sensors"
        />
      </GlassCard>

      {/* BLE */}
      <GlassCard
        title="BLE Tracking"
        badge={
          <CountBadge
            count={bleDevices.length}
            total={bleDevices.length}
            icon={<Bluetooth size={12} />}
            active={bleDevices.length > 0}
          />
        }
      >
        <DetectionList
          items={bleDevices.map((b) => ({
            id: b.entity_id,
            name: String(b.attributes.friendly_name ?? b.entity_id).replace("sensor.", "").replace(/_/g, " "),
            active: true,
            area: b.attributes.area as string | undefined,
            distance: b.attributes.distance as number | undefined,
          }))}
          icon={<Bluetooth size={12} />}
          emptyText="No BLE devices"
        />
      </GlassCard>

      {/* Camera */}
      <GlassCard
        title="Cameras"
        badge={
          <CountBadge
            count={activeDetections.length}
            total={cameras.length}
            icon={<Camera size={12} />}
            active={activeDetections.length > 0}
          />
        }
      >
        <DetectionList
          items={cameras.map((c) => ({
            id: c.entity_id,
            name: String(c.attributes.friendly_name ?? c.entity_id).replace("camera.", "").replace(/_/g, " "),
            active: c.state === "recording" || c.state === "streaming",
            state: c.state,
          }))}
          icon={<Camera size={12} />}
          emptyText="No cameras"
        />
      </GlassCard>
    </div>
  );
}

/* -- Sub components -- */

function CountBadge({
  count,
  total,
  icon,
  active,
}: {
  count: number;
  total: number;
  icon: React.ReactNode;
  active: boolean;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        fontSize: typography.size.xs,
        fontWeight: typography.weight.semibold,
        color: active ? color.status.green : color.text.tertiary,
      }}
    >
      {icon}
      {count}/{total}
    </span>
  );
}

interface DetectionItem {
  id: string;
  name: string;
  active: boolean;
  time?: string;
  area?: string;
  distance?: number;
  state?: string;
}

function DetectionList({
  items,
  icon,
  emptyText,
}: {
  items: DetectionItem[];
  icon: React.ReactNode;
  emptyText: string;
}) {
  if (items.length === 0) {
    return (
      <div
        style={{
          padding: space.md,
          color: color.text.tertiary,
          fontSize: typography.size.sm,
          textAlign: "center",
        }}
      >
        {emptyText}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {items.slice(0, 8).map((item) => (
        <div
          key={item.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: `${space.xs}px ${space.sm}px`,
            borderRadius: radius.sm,
            background: item.active ? "rgba(102, 187, 106, 0.06)" : "rgba(255, 255, 255, 0.02)",
            borderLeft: item.active ? `2px solid ${color.status.green}` : "2px solid transparent",
            fontSize: typography.size.sm,
          }}
        >
          <span style={{ color: item.active ? color.status.green : color.text.disabled }}>
            {icon}
          </span>
          <span
            style={{
              flex: 1,
              color: color.text.secondary,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.name}
          </span>
          {item.area && (
            <span
              style={{
                fontSize: typography.size.xs,
                color: color.accent.primary,
                background: color.accent.primaryDim,
                padding: "1px 6px",
                borderRadius: radius.sm,
                flexShrink: 0,
              }}
            >
              {item.area}
            </span>
          )}
          {item.distance != null && (
            <span className="tabular" style={{ fontSize: typography.size.xs, color: color.text.tertiary, flexShrink: 0 }}>
              {item.distance.toFixed(1)}m
            </span>
          )}
          {item.time && (
            <span style={{ fontSize: typography.size.xs, color: color.text.tertiary, flexShrink: 0 }}>
              {timeAgo(item.time)}
            </span>
          )}
        </div>
      ))}
      {items.length > 8 && (
        <div style={{ fontSize: typography.size.xs, color: color.text.tertiary, textAlign: "center", padding: 4 }}>
          +{items.length - 8} more
        </div>
      )}
    </div>
  );
}
