export interface SparkPoint {
  t: number;
  v: number;
}

/** A small line chart as SVG. `min` and `max` fix the vertical range; otherwise it fits the data. */
export function Sparkline({ points, label, color = '#2453b0', min, max, width = 260, height = 44 }: { points: SparkPoint[]; label: string; color?: string; min?: number; max?: number; width?: number; height?: number }) {
  if (points.length < 2) {
    return (
      <div className="spark spark--empty" role="img" aria-label={`${label}: not enough data yet`}>
        {label}: not enough data yet
      </div>
    );
  }
  const t0 = points[0]?.t ?? 0;
  const t1 = points[points.length - 1]?.t ?? 1;
  const lo = min ?? Math.min(...points.map((p) => p.v));
  const hi = max ?? Math.max(...points.map((p) => p.v));
  const x = (t: number) => ((t - t0) / (t1 - t0 || 1)) * (width - 4) + 2;
  const y = (v: number) => height - 3 - ((v - lo) / (hi - lo || 1)) * (height - 6);
  const d = points.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];
  return (
    <figure className="spark">
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}: latest ${last?.v ?? ''}`} shapeRendering="crispEdges">
        <rect x="0" y="0" width={width} height={height} fill="#f6f8fb" stroke="#1d1a2c" strokeWidth="2" />
        <polyline points={d} fill="none" stroke={color} strokeWidth="2" />
      </svg>
      <figcaption>{label}</figcaption>
    </figure>
  );
}
