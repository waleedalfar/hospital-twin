import { useEffect, useRef } from 'react';

import { useTwin } from '../../state/store';
import { GovernanceButton } from '../governance/Governance';
import { Banners, ScenarioMenu, SimClock, SpeedControls } from '../common';
import { go } from '../route';
import { drawCity } from './drawCity';
import { makeGrid, MAP_H, MAP_W, minutesLeft, percent, poseOnRoute, statusWord, STATUS_COLORS } from './geo';

/** Screen 1 (PROMPT.md §10.1): the city with three hospitals, live ambulances and a side panel. */
export function NetworkMap() {
  const net = useTwin((s) => s.network);
  const connection = useTwin((s) => s.networkConnection);
  const connect = useTwin((s) => s.connectNetwork);
  const disconnect = useTwin((s) => s.disconnectNetwork);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    connect();
    return disconnect;
  }, [connect, disconnect]);

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext('2d');
    if (!cv || !ctx) return;
    let raf = 0;
    const frame = () => {
      const s = useTwin.getState();
      drawCity(ctx, s.network, { nowMs: performance.now(), simMs: s.networkNowMs() });
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); };
  }, []);

  const grid = net ? makeGrid(net.hospitals) : null;
  const simMs = useTwin.getState().networkNowMs();
  const hospitals = net?.hospitals ?? [];
  const names = new Map(hospitals.map((h) => [h.id, h.name]));
  const incoming = (net?.vehicles ?? []).filter((v) => v.status === 'to_hospital' && v.kind === 'ambulance');

  return (
    <div className="screen screen--network">
      <header className="bar bar--light">
        <h1 className="bar__title">Hospital Twin</h1>
        <span className="bar__sub">Phoenix network · {hospitals.length} hospitals</span>
        <span className="bar__grow" />
        <SimClock simMs={net ? useTwin.getState().networkNowMs() : 0} />
        <SpeedControls speed={net?.speed ?? 1} paused={net?.paused ?? false} />
        <GovernanceButton />
        <ScenarioMenu hospitals={hospitals} defaultHospital={null} active={net?.scenarios ?? []} />
      </header>
      <Banners connection={connection} />
      <div className="network">
        <div className="network__map" style={{ width: MAP_W, height: MAP_H }}>
          <canvas ref={canvas} width={MAP_W} height={MAP_H} className="pixel-canvas" aria-label="Map of the three hospitals with live ambulances" />
          {grid &&
            hospitals.map((h) => {
              const p = grid.toXY(h.lat, h.lon);
              const word = statusWord(h.status, h.kpis.census, h.kpis.capacity);
              const col = STATUS_COLORS[word];
              return (
                <button key={h.id} type="button" className="hospital-tag" data-testid={`hospital-${h.id}`} style={{ left: p.x - 75, top: p.y - 100 }} onClick={() => { go({ page: 'hospital', hospitalId: h.id }); }} aria-label={`Open ${h.name}`}>
                  <span className="hospital-tag__name">{h.name}</span>
                  <span className="hospital-tag__pct" style={{ color: col.text }}>
                    {percent(h.kpis.census, h.kpis.capacity)}%
                  </span>
                  <span className="pill" style={{ background: col.bg, color: col.ink }}>
                    {word}
                  </span>
                </button>
              );
            })}
          {grid &&
            incoming.map((v) => {
              const pose = poseOnRoute(v.route, simMs, v);
              const p = grid.toXY(pose.lat, pose.lon);
              const mins = minutesLeft(v.route, simMs);
              return (
                <div key={v.id} className="route-label" style={{ left: p.x + 22, top: p.y + 14 }}>
                  {v.id} to {names.get(v.destination ?? '') ?? v.destination} · {mins} min
                </div>
              );
            })}
        </div>
        <aside className="side" aria-label="Network panel">
          <div className="side__note">SIMULATED DATA · LIVE FROM THE SIM</div>
          <section className="card">
            <h2>Hospitals</h2>
            {hospitals.length === 0 && <p className="muted">Waiting for the simulation…</p>}
            {hospitals.map((h) => {
              const word = statusWord(h.status, h.kpis.census, h.kpis.capacity);
              const col = STATUS_COLORS[word];
              const filled = Math.round(percent(h.kpis.census, h.kpis.capacity) / 10);
              return (
                <div key={h.id} className="hosp" data-testid={`hospital-row-${h.id}`}>
                  <div className="hosp__head">
                    <span>{h.name}</span>
                    <span className="pill" style={{ background: col.bg, color: col.ink }}>
                      {word}
                    </span>
                  </div>
                  <div className="segs" aria-hidden="true">
                    {Array.from({ length: 10 }, (_, i) => (
                      <span key={i} style={{ background: i < filled ? col.bg : '#e4e1d4' }} />
                    ))}
                  </div>
                  <div className="muted">
                    Census {h.kpis.census}/{h.kpis.capacity} · ER wait {Math.round(h.kpis.er_wait_min)} min · waiting {h.kpis.waiting}
                    {h.status === 'diverting' ? ' · DIVERTING AMBULANCES' : ''}
                  </div>
                </div>
              );
            })}
          </section>
          <section className="card">
            <h2>Incoming ambulances</h2>
            {incoming.length === 0 && <p className="muted">None on the road with a patient.</p>}
            {incoming.map((v) => (
              <div key={v.id} className="muted" data-testid="incoming">
                {v.id} · {v.patient_id ?? 'patient'} → {names.get(v.destination ?? '') ?? v.destination}
              </div>
            ))}
          </section>
        </aside>
      </div>
    </div>
  );
}
