import { formatDelta } from "../format";
import type { Comparison, RigInfo } from "../schema";

interface Props {
  comparison: Comparison | null;
  rigs: RigInfo[];
}

const BAR_RANGE_MS = 2000; // the delta bar is full at ±2 s

export function ComparisonPanel({ comparison, rigs }: Props) {
  const byId = new Map(rigs.map((r) => [r.rig_id, r]));
  if (!comparison || comparison.rigs.length < 2) {
    return (
      <section className="panel compare" aria-label="Head to head">
        <h2 className="panel__title">Head to head</h2>
        <p className="panel__empty">The comparison starts when two rigs are on the same track.</p>
      </section>
    );
  }
  const title = comparison.rigs.length === 2 ? "Head to head" : "Against the fastest other rig";
  return (
    <section className="panel compare" aria-label={title}>
      <h2 className="panel__title">{title}</h2>
      <table className="compare__table">
        <thead>
          <tr>
            <th scope="col">Rig</th>
            <th scope="col" className="num">Best lap gap</th>
            <th scope="col" className="compare__live-head">Live on this lap</th>
          </tr>
        </thead>
        <tbody>
          {comparison.rigs.map((entry) => {
            const rig = byId.get(entry.rig_id);
            const ref = entry.reference_rig_id ? byId.get(entry.reference_rig_id) : undefined;
            return (
              <tr key={entry.rig_id} style={{ "--rig-colour": rig?.colour ?? "#888" } as React.CSSProperties}>
                <th scope="row">
                  <span className="compare__rig">
                    <span className="stripe" aria-hidden="true" />
                    {rig?.name ?? entry.rig_id}
                    {ref && <span className="compare__ref">vs {ref.name}</span>}
                  </span>
                </th>
                <td className="num compare__gap">
                  {entry.best_gap_ms == null ? <span className="muted">No lap yet</span> : formatDelta(entry.best_gap_ms)}
                </td>
                <td className="compare__live-cell">
                  <span className="compare__live">
                    <DeltaBar ms={entry.live_delta_ms} />
                    <span className="compare__live-value">
                      {entry.live_delta_ms == null ? <span className="muted">–</span> : formatDelta(entry.live_delta_ms, 2)}
                    </span>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

/** Centre = level with the reference lap; bar grows left when ahead, right when behind. */
function DeltaBar({ ms }: { ms: number | null }) {
  const k = ms == null ? 0 : Math.max(-1, Math.min(1, ms / BAR_RANGE_MS));
  const width = `${Math.abs(k) * 50}%`;
  const style = k < 0 ? { right: "50%", width } : { left: "50%", width };
  return (
    <span className="delta-bar" aria-hidden="true">
      <span className="delta-bar__fill" style={style} />
      <span className="delta-bar__axis" />
    </span>
  );
}
