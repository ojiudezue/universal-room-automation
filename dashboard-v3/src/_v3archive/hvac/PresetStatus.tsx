/**
 * HVAC preset and constraint status display.
 */
import { useEntity, formatState } from "../../hooks/useEntity";
import { StatusBadge } from "../shared/StatusBadge";
import { Toggle } from "../shared/Toggle";
import { color, space, type as typography } from "../../design/tokens";

const ENTITIES = {
  mode: "sensor.ura_hvac_coordinator_mode",
  arresterState: "sensor.ura_hvac_coordinator_override_arrester_state",
  arresterSwitch: "switch.ura_hvac_coordinator_override_arrester",
  observationMode: "switch.ura_hvac_coordinator_hvac_observation_mode",
  hvacConstraint: "sensor.ura_energy_coordinator_hvac_constraint",
  loadShedding: "sensor.ura_energy_coordinator_load_shedding",
};

export function PresetStatus() {
  const mode = useEntity(ENTITIES.mode);
  const arresterState = useEntity(ENTITIES.arresterState);
  const arresterSwitch = useEntity(ENTITIES.arresterSwitch);
  const observationMode = useEntity(ENTITIES.observationMode);
  const hvacConstraint = useEntity(ENTITIES.hvacConstraint);
  const loadShedding = useEntity(ENTITIES.loadShedding);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      {/* Mode + Arrester */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div>
          <div style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            HVAC Mode
          </div>
          <StatusBadge value={mode.state} size="md" />
        </div>
        <div>
          <div style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            Arrester
          </div>
          <StatusBadge value={arresterState.state} />
        </div>
      </div>

      {/* Toggle controls */}
      <div style={{
        display: "flex",
        flexDirection: "column",
        gap: space.sm,
        borderTop: `1px solid rgba(255, 255, 255, 0.05)`,
        paddingTop: space.sm,
      }}>
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <span style={{ fontSize: typography.size.base, color: color.text.secondary }}>
            Override Arrester
          </span>
          <Toggle
            entityId={arresterSwitch.entity_id}
            currentState={arresterSwitch.state}
            size="sm"
          />
        </div>
        <div style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <span style={{ fontSize: typography.size.base, color: color.text.secondary }}>
            Observation Mode
          </span>
          <Toggle
            entityId={observationMode.entity_id}
            currentState={observationMode.state}
            size="sm"
          />
        </div>
      </div>

      {/* Energy constraints */}
      <div style={{
        borderTop: `1px solid rgba(255, 255, 255, 0.05)`,
        paddingTop: space.sm,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.xs }}>
          <span style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            Energy Constraint
          </span>
          <StatusBadge value={hvacConstraint.state} />
        </div>
        <div style={{ fontSize: typography.size.sm, color: color.text.secondary }}>
          {formatState(String(hvacConstraint.attributes?.detail ?? hvacConstraint.state))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: space.sm, marginTop: space.sm }}>
          <span style={{
            fontSize: typography.size.xs,
            color: color.text.tertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            Load Shedding
          </span>
          <StatusBadge value={loadShedding.state} />
        </div>
      </div>
    </div>
  );
}
