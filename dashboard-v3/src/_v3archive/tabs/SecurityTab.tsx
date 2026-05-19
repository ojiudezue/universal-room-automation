/**
 * Security tab -- cameras (grouped), locks, alarm panel.
 */
import { useMemo } from "react";
import { Lock, Unlock, DoorOpen, Users, Clock } from "lucide-react";
import { useEntity, useEntitiesByPrefix, formatState, timeAgo } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { StatusBadge } from "../shared/StatusBadge";
import { CameraGroup } from "../security/CameraGroup";
import { LockControls } from "../security/LockControls";
import { AlarmControls } from "../security/AlarmControls";
import { color, space, radius, type as typography } from "../../design/tokens";

const SECURITY = {
  armedState: "sensor.ura_security_coordinator_security_armed_state",
  openEntries: "sensor.ura_security_coordinator_security_open_entries",
  lastLockSweep: "sensor.ura_security_coordinator_security_last_lock_sweep",
  expectedArrivals: "sensor.ura_security_coordinator_security_expected_arrivals",
};

const ENTRY_KEYWORDS = ["door", "entry", "front", "garage", "gate"];
const INSIDE_KEYWORDS = ["indoor", "inside", "living", "kitchen", "office", "bedroom"];

function categorizeCamera(name: string): "entry" | "inside" | "outside" {
  const lower = name.toLowerCase();
  if (ENTRY_KEYWORDS.some((k) => lower.includes(k))) return "entry";
  if (INSIDE_KEYWORDS.some((k) => lower.includes(k))) return "inside";
  return "outside";
}

interface EntityLike {
  state: string;
  attributes: Record<string, unknown>;
}

export function SecurityTab() {
  const armedState = useEntity(SECURITY.armedState);
  const openEntries = useEntity(SECURITY.openEntries);
  const lastLockSweep = useEntity(SECURITY.lastLockSweep);
  const expectedArrivals = useEntity(SECURITY.expectedArrivals);

  const cameraEntities = useEntitiesByPrefix("camera.");
  const lockEntities = useEntitiesByPrefix("lock.");
  const alarmEntities = useEntitiesByPrefix("alarm_control_panel.");

  const cameras = useMemo(() => {
    const all = cameraEntities.map((e) => ({
      id: e.entity_id,
      name: String(e.attributes.friendly_name ?? e.entity_id.replace("camera.", "")),
      state: e.state,
      category: categorizeCamera(
        String(e.attributes.friendly_name ?? e.entity_id)
      ),
      entityPicture: e.attributes.entity_picture as string | undefined,
    }));
    return {
      entry: all.filter((c) => c.category === "entry"),
      outside: all.filter((c) => c.category === "outside"),
      inside: all.filter((c) => c.category === "inside"),
    };
  }, [cameraEntities]);

  const locks = useMemo(
    () =>
      lockEntities.map((e) => ({
        id: e.entity_id,
        name: String(e.attributes.friendly_name ?? e.entity_id.replace("lock.", "")),
        state: e.state,
      })),
    [lockEntities]
  );

  const alarmPanels = useMemo(
    () =>
      alarmEntities.map((e) => ({
        id: e.entity_id,
        name: String(e.attributes.friendly_name ?? e.entity_id),
        state: e.state,
      })),
    [alarmEntities]
  );

  const lockedCount = locks.filter((l) => l.state === "locked").length;
  const allLocked = lockedCount === locks.length && locks.length > 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Stats bar */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: space.sm,
      }}>
        <StatTile
          icon={allLocked ? <Lock size={18} /> : <Unlock size={18} />}
          value={`${lockedCount}/${locks.length}`}
          label={allLocked ? "All Locked" : "Locked"}
          accentColor={allLocked ? color.status.green : color.status.red}
        />
        <StatTile
          icon={<DoorOpen size={18} />}
          value={String(openEntries.state)}
          label="Open Entries"
          accentColor={color.status.blue}
        />
        <StatTile
          icon={<Users size={18} />}
          value={String(expectedArrivals.state)}
          label="Expected Arrivals"
          accentColor={color.status.yellow}
        />
      </div>

      {/* Alarm Panel */}
      {alarmPanels.length > 0 && (
        <GlassCard title="Alarm Panel">
          <AlarmControls panel={alarmPanels[0]} />
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: space.sm,
            fontSize: typography.size.sm,
            color: color.text.tertiary,
            borderTop: `1px solid rgba(255, 255, 255, 0.05)`,
            paddingTop: space.sm,
          }}>
            <Clock size={12} />
            Last Lock Sweep:
            <span className="tabular" style={{ color: color.text.secondary }}>
              {lastLockSweep.state !== "unknown" && lastLockSweep.state !== "unavailable"
                ? new Date(lastLockSweep.state).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : "--"}
            </span>
          </div>
        </GlassCard>
      )}

      {/* Locks */}
      {locks.length > 0 && (
        <GlassCard
          title="Locks"
          subtitle={allLocked ? "All secured" : `${locks.length - lockedCount} unlocked`}
        >
          <LockControls locks={locks} />
        </GlassCard>
      )}

      {/* Camera Groups */}
      <div
        className="camera-groups"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: space.md,
        }}
      >
        <CameraGroup title="Entryways" cameras={cameras.entry} />
        <CameraGroup title="Outside" cameras={cameras.outside} />
        <CameraGroup title="Inside" cameras={cameras.inside} />
      </div>

      <style>{`
        @media (max-width: 900px) {
          .camera-groups { grid-template-columns: repeat(2, 1fr) !important; }
        }
        @media (max-width: 600px) {
          .camera-groups { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

function StatTile({
  icon,
  value,
  label,
  accentColor,
}: {
  icon: React.ReactNode;
  value: string;
  label: string;
  accentColor: string;
}) {
  return (
    <div style={{
      background: color.glass.bg,
      border: `1px solid ${color.glass.border}`,
      borderLeft: `3px solid ${accentColor}`,
      borderRadius: radius.lg,
      padding: space.md,
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: space.xs,
      textAlign: "center",
    }}>
      <div style={{
        width: 36,
        height: 36,
        borderRadius: radius.full,
        background: `${accentColor}18`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: accentColor,
      }}>
        {icon}
      </div>
      <span className="tabular" style={{
        fontSize: typography.size.xl,
        fontWeight: typography.weight.semibold,
        color: color.text.primary,
      }}>
        {value === "unknown" || value === "unavailable" ? "--" : value}
      </span>
      <span style={{
        fontSize: typography.size.xs,
        color: color.text.tertiary,
        fontWeight: typography.weight.medium,
      }}>
        {label}
      </span>
    </div>
  );
}
