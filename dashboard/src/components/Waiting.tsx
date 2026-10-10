import type { DashboardState } from "../state/reducer";

/** Shown on the map while no rig is driving and none has ever sent data: how to connect a game. */
export function Waiting({ state }: { state: DashboardState }) {
  const { address, port } = state.telemetryTarget;
  const host = address ?? (location.hostname === "localhost" ? null : location.hostname);
  const anyRig = state.rigs.length > 0;
  return (
    <div className="waiting">
      <h2 className="waiting__title">{anyRig ? "No car on track" : "Waiting for telemetry"}</h2>
      <p className="waiting__lead">
        {anyRig
          ? "Cars appear on the map as soon as a rig drives out in Time Trial."
          : "Set this up in F1 25 on each rig, then drive out in Time Trial."}
      </p>
      {!anyRig && (
        <dl className="waiting__settings">
          <div>
            <dt>Where</dt>
            <dd>Settings, Telemetry Settings</dd>
          </div>
          <div>
            <dt>UDP Telemetry</dt>
            <dd>On</dd>
          </div>
          <div>
            <dt>UDP Broadcast Mode</dt>
            <dd>Off</dd>
          </div>
          <div>
            <dt>UDP IP Address</dt>
            <dd>{host ?? "this hub PC's IP address"}</dd>
          </div>
          <div>
            <dt>UDP Port</dt>
            <dd>{port}</dd>
          </div>
          <div>
            <dt>UDP Format</dt>
            <dd>2025, the same on every rig</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
