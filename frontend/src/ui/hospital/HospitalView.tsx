import { useEffect, useRef, useState } from 'react';

import { Engine } from '../../engine/engine';
import type { CameraMode } from '../../engine/camera';
import { MAX_PIXEL_FACTOR, MIN_PIXEL_FACTOR } from '../../engine/palette';
import { useTwin } from '../../state/store';
import { Banners, ScenarioMenu, SimClock, SpeedControls } from '../common';
import { go } from '../route';
import { FloorPlan } from './FloorPlan';
import { GovernanceButton } from '../governance/Governance';
import { AgentPanel } from './AgentPanel';
import { AskPanel } from './AskPanel';
import { Inspector } from './Inspector';
import { ForecastPanel, ModelBadge } from './MlPanels';
import { KpiStrip, Legend, LiveFeed, PresetBar } from './Panels';

/** Creates the 3D engine on a canvas and keeps it in step with the store. Returns the engine or an error. */
function useEngine(canvas: React.RefObject<HTMLCanvasElement | null>, box: React.RefObject<HTMLDivElement | null>, hospitalName: string | null) {
  const [engine, setEngine] = useState<Engine | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<string | null>('outside');
  useEffect(() => {
    const cv = canvas.current;
    const el = box.current;
    if (!cv || !el || hospitalName === null) return;
    let eng: Engine;
    try {
      const r = el.getBoundingClientRect();
      eng = new Engine({
        canvas: cv,
        hospitalName,
        width: r.width || 1280,
        height: r.height || 744,
        frozen: useTwin.getState().freeze,
        cameraMode: 'free', // fly through the building by default; the Isometric button switches

        simClock: () => useTwin.getState().simNowMs(),
        onPick: (id) => { useTwin.getState().select(id); },
        onView: (v) => { setPreset(v.preset); },
      });
    } catch (e) {
      console.error('The 3D view could not start', e);
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    setEngine(eng);
    const ro = new ResizeObserver((entries) => {
      const box0 = entries[0]?.contentRect;
      if (box0 && box0.width > 0 && box0.height > 0) eng.resize(box0.width, box0.height);
    });
    ro.observe(el);
    const unsub = useTwin.subscribe((s, prev) => {
      if (s.data !== prev.data && s.data) {
        eng.setEntities(Object.values(s.data.entities));
        eng.setVehicles(s.data.vehicles);
      }
      if (s.selectedId !== prev.selectedId) eng.select(s.selectedId);
      if (s.highlightIds !== prev.highlightIds) eng.highlight(s.highlightIds);
    });
    const now = useTwin.getState();
    if (now.data) {
      eng.setEntities(Object.values(now.data.entities));
      eng.setVehicles(now.data.vehicles);
    }
    return () => {
      unsub();
      ro.disconnect();
      eng.dispose();
      setEngine(null);
    };
    // The engine is created once per hospital name; later renames are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hospitalName === null]);
  return { engine, error, preset };
}

/** Screen 2 (PROMPT.md §10.1): the 3D hospital with the HUD around it. */
export function HospitalView({ hospitalId }: { hospitalId: string }) {
  const data = useTwin((s) => s.data);
  const connection = useTwin((s) => s.connection);
  const selectedId = useTwin((s) => s.selectedId);
  const select = useTwin((s) => s.select);
  const connect = useTwin((s) => s.connectHospital);
  const disconnect = useTwin((s) => s.disconnectHospital);
  const network = useTwin((s) => s.network);
  const connectNetwork = useTwin((s) => s.connectNetwork);
  const canvas = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [xray, setXray] = useState(false);
  const [night, setNight] = useState(false);
  const [mode, setMode] = useState<CameraMode>('free');
  const [pixel, setPixel] = useState(2);
  const [plan, setPlan] = useState(false);
  const { engine, error, preset } = useEngine(canvas, box, data?.hospital.name ?? null);

  useEffect(() => {
    connect(hospitalId);
    connectNetwork();
    return disconnect;
  }, [connect, disconnect, connectNetwork, hospitalId]);

  useEffect(() => {
    if (data) engine?.setHospitalName(data.hospital.name);
  }, [data?.hospital.name, engine]); // eslint-disable-line react-hooks/exhaustive-deps

  const showPlan = plan || error !== null;
  const entity = selectedId && data ? data.entities[selectedId] : undefined;
  const clockMs = data ? useTwin.getState().simNowMs() : 0;
  const hospitals = network?.hospitals ?? [];

  return (
    <div className="screen screen--hospital">
      <header className="bar">
        <button type="button" className="btn btn--back" onClick={() => { go({ page: 'network' }); }}>
          ← City
        </button>
        <h1 className="bar__title">Hospital Twin</h1>
        <span className="bar__sub">{data?.hospital.name ?? hospitalId} · 3 floors · {mode === 'iso' ? 'Isometric' : 'Free-fly'}{night ? ' · night' : ''}</span>
        <span className="bar__grow" />
        <SimClock simMs={clockMs} />
        <SpeedControls speed={data?.speed ?? 1} paused={data?.paused ?? false} />
        <button type="button" className={xray ? 'btn btn--on' : 'btn'} aria-pressed={xray} onClick={() => { setXray(!xray); engine?.setXray(!xray); }}>
          {xray ? 'X-ray on' : 'X-ray'}
        </button>
        <button type="button" className={night ? 'btn btn--on' : 'btn'} aria-pressed={night} onClick={() => { setNight(!night); engine?.setNight(!night); }}>
          Night
        </button>
        <button type="button" className="btn" aria-pressed={mode === 'free'} onClick={() => { const m = mode === 'iso' ? 'free' : 'iso'; setMode(m); engine?.setCameraMode(m); }}>
          {mode === 'iso' ? 'Free-fly camera' : 'Isometric camera'}
        </button>
        <label className="btn btn--select">
          Pixels
          <select value={pixel} aria-label="Pixel factor" onChange={(e) => { setPixel(Number(e.target.value)); engine?.setPixelFactor(Number(e.target.value)); }}>
            {Array.from({ length: MAX_PIXEL_FACTOR - MIN_PIXEL_FACTOR + 1 }, (_, i) => i + MIN_PIXEL_FACTOR).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <button type="button" className={showPlan ? 'btn btn--on' : 'btn'} aria-pressed={showPlan} disabled={error !== null} onClick={() => { setPlan(!plan); }}>
          2D plan
        </button>
        <GovernanceButton />
        <ScenarioMenu hospitals={hospitals} defaultHospital={hospitalId} active={data?.scenarios ?? []} />
      </header>
      <Banners connection={connection} />
      {error && (
        <div className="banner banner--problem" role="alert" data-testid="webgl-banner">
          The 3D view could not start ({error}). The 2D floor plan below shows the same live data.
        </div>
      )}
      <div className="stage" ref={box}>
        <canvas
          ref={canvas}
          className="pixel-canvas stage__canvas"
          style={{ visibility: showPlan ? 'hidden' : 'visible' }}
          tabIndex={0}
          aria-label="3D view of a three-floor hospital. Drag to look around, W A S D to move, click a patient to inspect."
          data-testid="scene"
        />
        {showPlan && data && <FloorPlan data={data} simNow={() => useTwin.getState().simNowMs()} selectedId={selectedId} onSelect={select} />}
        {!data && <div className="stage__loading">Loading the hospital…</div>}
        {data && (
          <>
            <div className="hud hud--tl">
              <KpiStrip kpis={data.kpis} />
              <div className="chip" data-testid="viewing">Viewing: {preset ?? 'custom'} · simulated data</div>
              <ModelBadge />
              <LiveFeed feed={data.feed} />
              <ForecastPanel hospitalId={hospitalId} />
            </div>
            <div className="hud hud--tr">
              <AskPanel hospitalId={hospitalId} onFly={() => engine?.focusSelected()} />
              <AgentPanel />
              <Inspector entity={entity} onFly={() => engine?.focusSelected()} />
            </div>
            <div className="hud hud--bl">
              <PresetBar active={preset} onPick={(id) => engine?.preset(id)} />
              <div className="chip" data-testid="controls-hint">
                {mode === 'iso' ? 'W A S D pan · Q/E down/up · Shift faster · drag to rotate · wheel to zoom · "Free-fly camera" flies through the building' : 'W A S D fly · Q/E down/up · Shift faster · drag to look · "Isometric camera" for the top-down view'}
              </div>
            </div>
            <div className="hud hud--br">
              <Legend xray={xray} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
