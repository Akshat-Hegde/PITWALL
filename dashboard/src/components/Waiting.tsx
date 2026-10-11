import type { DashboardState } from "../state/reducer";

/**
 * Shown on the map while no car is on track. Customers see this, so it never shows addresses or ports:
 * the game setup (UDP IP and port) is on the staff page's Health tab.
 */
export function Waiting({ state }: { state: DashboardState }) {
  const anyRig = state.rigs.length > 0;
  return (
    <div className="waiting">
      <h2 className="waiting__title">{anyRig ? "No car on track" : "Waiting for cars"}</h2>
      <p className="waiting__lead">Cars appear on the map as soon as a rig drives out.</p>
    </div>
  );
}
