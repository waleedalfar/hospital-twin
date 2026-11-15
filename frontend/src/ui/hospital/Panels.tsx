import { PRESETS } from '../../engine/camera';
import { BASE } from '../../engine/palette';
import { formatSimClock } from '../../state/clock';
import type { FeedItem, HospitalData } from '../../state/types';

const TONE: Record<FeedItem['tone'], string> = { low: BASE.low, med: BASE.med, high: BASE.high, info: '#6d88b0' };

export function KpiStrip({ kpis }: { kpis: HospitalData['kpis'] }) {
  return (
    <div className="kpis" aria-label="Key numbers" data-testid="kpis">
      <span>
        CENSUS {kpis.census}/{kpis.capacity}
      </span>
      <span>ER WAIT {Math.round(kpis.er_wait_min)}m</span>
      <span>WAITING {kpis.waiting}</span>
      <span>ALERTS {kpis.alerts}</span>
    </div>
  );
}

export function LiveFeed({ feed }: { feed: FeedItem[] }) {
  return (
    <section className="feed" aria-label="Live feed">
      <div className="feed__title">LIVE FEED · WEBSOCKET</div>
      {feed.length === 0 && <div className="feed__row muted">Waiting for events…</div>}
      {feed.slice(0, 6).map((f, i) => (
        <div key={f.key} className="feed__row" style={{ opacity: 1 - i * 0.12 }} data-testid="feed-row">
          <span className="feed__dot" style={{ background: TONE[f.tone] }} />
          <span>{formatSimClock(Date.parse(f.time)).clock}</span>
          <strong>{f.who}</strong>
          <span>{f.what}</span>
        </div>
      ))}
    </section>
  );
}

export function PresetBar({ active, onPick }: { active: string | null; onPick: (id: string) => void }) {
  return (
    <div className="presets" role="group" aria-label="Camera presets">
      {PRESETS.map((p) => (
        <button key={p.id} type="button" className={active === p.id ? 'btn btn--on' : 'btn'} aria-pressed={active === p.id} onClick={() => { onPick(p.id); }}>
          {p.label}
        </button>
      ))}
    </div>
  );
}

const LEGEND: [string, string][] = [
  ['Nurse', BASE.nurse],
  ['Doctor', '#ffffff'],
  ['Surgeon', BASE.surg],
  ['EMT', BASE.emt],
  ['Visitor', '#b48ead'],
];

export function Legend({ xray }: { xray: boolean }) {
  return (
    <div className="legend" aria-label="Legend">
      {xray && (
        <div className="legend__xray" data-testid="xray-legend">
          {LEGEND.map(([name, color]) => (
            <span key={name}>
              <i style={{ background: color }} />
              {name}
            </span>
          ))}
          <span>Patients in beds = risk color</span>
        </div>
      )}
      Drag to look · W A S D move · E up, Q down
      <br />
      Shift = faster · scroll to zoom · click a patient
    </div>
  );
}
