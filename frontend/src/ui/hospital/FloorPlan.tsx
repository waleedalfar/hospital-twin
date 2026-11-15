import { useEffect, useState } from 'react';

import { LAYOUT, LayoutIndex } from '../../engine/layout';
import { parseTimes, positionAt, restingPlace } from '../../engine/motion';
import { BASE } from '../../engine/palette';
import type { Entity, HospitalData } from '../../state/types';

const idx = new LayoutIndex(LAYOUT);
const ROLE_COLOR: Record<string, string> = { patient: BASE.gown, visitor: '#b48ead', nurse: BASE.nurse, doctor: '#ffffff', surgeon: BASE.surg, emt: BASE.emt };
const RISK_COLOR = { low: BASE.low, medium: BASE.med, high: BASE.high } as const;
const FLOOR_NAMES = ['Ground', 'Wards', 'ICU and support'];

interface Dot {
  id: string;
  x: number;
  z: number;
  entity: Entity;
}

/** Position of an entity on the floor `level` at sim time `simMs`, or null if it is not on that floor. */
export function dotOn(e: Entity, level: number, simMs: number): Dot | null {
  if (e.move) {
    const p = positionAt(idx, e.move.path, parseTimes(e.move.times), simMs);
    if (Date.parse(e.move.arrive) > simMs) return Math.round(p.level) === level ? { id: e.id, x: p.x, z: p.z, entity: e } : null;
  }
  const r = restingPlace(idx, e.location);
  if (!r || r.level !== level) return null;
  return { id: e.id, x: r.x, z: r.z, entity: e };
}

/**
 * The 2D floor plan (PROMPT.md §10.1, screen 3): a top-down plan per floor driven by the same entity store
 * as the 3D view. It has no WebGL dependency, so it keeps working if the 3D scene cannot start. People are
 * plain squares; there are no faces.
 */
export function FloorPlan({ data, simNow, selectedId, onSelect }: { data: HospitalData; simNow: () => number; selectedId: string | null; onSelect: (id: string) => void }) {
  const [level, setLevel] = useState(0);
  const [, tick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => { tick((n) => n + 1); }, 250);
    return () => { clearInterval(t); };
  }, []);
  const floor = LAYOUT.floors[level];
  const sim = simNow();
  const dots = Object.values(data.entities).flatMap((e) => {
    const d = dotOn(e, level, sim);
    return d ? [d] : [];
  });
  const fp = LAYOUT.building.footprint;
  return (
    <section className="plan" aria-label="Floor plan" data-testid="floor-plan">
      <div className="plan__tabs" role="tablist" aria-label="Floors">
        {FLOOR_NAMES.map((name, i) => (
          <button key={name} type="button" role="tab" aria-selected={level === i} className={level === i ? 'btn btn--on' : 'btn'} onClick={() => { setLevel(i); }}>
            Floor {i + 1} · {name}
          </button>
        ))}
      </div>
      <svg viewBox={`${fp.x1 - 1} ${fp.z1 - 1} ${fp.x2 - fp.x1 + 2} ${fp.z2 - fp.z1 + 2}`} className="plan__svg" shapeRendering="crispEdges" role="img" aria-label={`Floor ${level + 1} plan`}>
        {floor?.rooms.filter((r) => r.kind !== 'outside' && r.kind !== 'roof').map((r) => (
          <g key={r.id}>
            <rect x={r.rect.x1} y={r.rect.z1} width={r.rect.x2 - r.rect.x1} height={r.rect.z2 - r.rect.z1} fill={BASE[r.color as keyof typeof BASE]} stroke="#1d1a2c" strokeWidth="0.15" />
            {r.kind === 'room' && (
              <text x={r.label_x} y={r.label_z} fontSize="0.9" textAnchor="middle" fill="#20324a" fontFamily="'Pixelify Sans', monospace">
                {r.name}
              </text>
            )}
          </g>
        ))}
        {LAYOUT.beds.filter((b) => b.floor === level).map((b) => (
          <rect key={b.id} x={b.x - 0.55} y={b.z - 1.05} width="1.1" height="2.1" fill="#ffffff" stroke="#6b7390" strokeWidth="0.1" />
        ))}
        {dots.map(({ id, x, z, entity }) => {
          const risk = entity.risk?.level;
          const fill = entity.location.bed && !entity.move ? (risk ? RISK_COLOR[risk] : '#b8c4d6') : (ROLE_COLOR[entity.kind] ?? '#b48ead');
          return (
            <rect
              key={id}
              data-testid="plan-dot"
              data-entity={id}
              x={x - 0.35}
              y={z - 0.35}
              width="0.7"
              height="0.7"
              fill={fill}
              stroke={selectedId === id ? '#2453b0' : '#1d1a2c'}
              strokeWidth={selectedId === id ? 0.25 : 0.12}
              onClick={() => { onSelect(id); }}
              style={{ cursor: 'pointer' }}
            >
              <title>{`${entity.id} (${entity.kind})`}</title>
            </rect>
          );
        })}
      </svg>
    </section>
  );
}
