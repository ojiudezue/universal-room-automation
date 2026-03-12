/**
 * Camera group -- categorized camera list with thumbnails.
 */
import { Camera } from "lucide-react";
import { formatState } from "../../hooks/useEntity";
import { GlassCard } from "../layout/GlassCard";
import { color, space, radius, type as typography } from "../../design/tokens";

interface CameraData {
  id: string;
  name: string;
  state: string;
  entityPicture?: string;
}

interface Props {
  title: string;
  cameras: CameraData[];
}

export function CameraGroup({ title, cameras }: Props) {
  return (
    <GlassCard title={title} subtitle={`${cameras.length} cameras`}>
      {cameras.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
          {cameras.map((c) => (
            <div
              key={c.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: space.md,
                padding: space.sm,
                borderRadius: radius.md,
                background: "rgba(255, 255, 255, 0.03)",
              }}
            >
              {/* Thumbnail */}
              <div style={{
                position: "relative",
                width: 52,
                height: 38,
                borderRadius: radius.sm,
                overflow: "hidden",
                flexShrink: 0,
                background: "rgba(255, 255, 255, 0.05)",
              }}>
                {c.entityPicture ? (
                  <img
                    src={c.entityPicture}
                    alt={c.name}
                    style={{ width: "100%", height: "100%", objectFit: "cover" }}
                    loading="lazy"
                  />
                ) : (
                  <div style={{
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: color.text.disabled,
                  }}>
                    <Camera size={16} />
                  </div>
                )}
                {/* Recording indicator */}
                {c.state === "recording" && (
                  <div
                    className="animate-pulse-glow"
                    style={{
                      position: "absolute",
                      top: 3,
                      right: 3,
                      width: 7,
                      height: 7,
                      borderRadius: radius.full,
                      background: color.status.red,
                      boxShadow: `0 0 4px ${color.status.red}`,
                    }}
                  />
                )}
              </div>

              {/* Info */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: typography.size.sm,
                  fontWeight: typography.weight.medium,
                  color: color.text.primary,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}>
                  {c.name.replace(/_/g, " ")}
                </div>
                <div style={{
                  fontSize: typography.size.xs,
                  color: c.state === "recording" ? color.status.red : color.text.tertiary,
                  textTransform: "uppercase",
                }}>
                  {c.state === "recording" ? "Recording" : formatState(c.state)}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{
          padding: space.lg,
          textAlign: "center",
          color: color.text.tertiary,
          fontSize: typography.size.sm,
        }}>
          No cameras in this group
        </div>
      )}
    </GlassCard>
  );
}
