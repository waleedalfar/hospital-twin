import { useState } from 'react';

import { Api, type ScenarioName } from '../state/api';
import { formatSimClock } from '../state/clock';
import { useTwin } from '../state/store';

export const api = new Api();

/** "SIM DAY 1 08:12": the sim clock in Phoenix time, always labelled SIM. */
export function SimClock({ simMs }: { simMs: number }) {
  if (!simMs) return <span className="sim-clock">SIM --:--</span>;
  const { day, clock } = formatSimClock(simMs);
  return (
    <span className="sim-clock" data-testid="sim-clock">
      SIM DAY {day} · {clock}
    </span>
  );
}

/** Shown while the browser cannot reach the live stream, and for the last problem reported. */
export function Banners({ connection }: { connection: string }) {
  const problem = useTwin((s) => s.problem);
  const setProblem = useTwin((s) => s.setProblem);
  const offline = connection === 'reconnecting' || connection === 'closed';
  return (
    <>
      {offline && (
        <div className="banner banner--offline" role="alert" data-testid="disconnected-banner">
          Disconnected: reconnecting to the live simulation…
        </div>
      )}
      {problem && (
        <div className="banner banner--problem" role="alert" data-testid="problem-banner">
          <span>{problem}</span>
          <button type="button" onClick={() => { setProblem(null); }}>
            Dismiss
          </button>
        </div>
      )}
    </>
  );
}

const SPEEDS = [1, 4, 8] as const;

/** Speed and pause controls. They call the API; the new state comes back over the stream. */
export function SpeedControls({ speed, paused }: { speed: number; paused: boolean }) {
  const setProblem = useTwin((s) => s.setProblem);
  const run = (p: Promise<unknown>) => {
    p.catch((e: unknown) => { setProblem(`Sim control failed: ${e instanceof Error ? e.message : String(e)}`); });
  };
  return (
    <div className="group" role="group" aria-label="Simulation speed">
      {SPEEDS.map((s) => (
        <button key={s} type="button" aria-pressed={speed === s} className={speed === s ? 'btn btn--on' : 'btn'} onClick={() => { run(api.setSpeed(s)); }}>
          {s}x
        </button>
      ))}
      <button type="button" aria-pressed={paused} className={paused ? 'btn btn--on' : 'btn'} onClick={() => { run(api.setPaused(!paused)); }}>
        {paused ? 'Resume' : 'Pause'}
      </button>
    </div>
  );
}

const SCENARIOS: { name: ScenarioName; label: string; needsHospital: boolean }[] = [
  { name: 'flu_surge', label: 'Flu surge', needsHospital: false },
  { name: 'mass_casualty', label: 'Mass casualty', needsHospital: false },
  { name: 'staff_shortage', label: 'Staff shortage', needsHospital: true },
  { name: 'hospital_offline', label: 'Hospital offline', needsHospital: true },
];

/** Starts and stops scenarios. `hospitals` lets the user pick where; `defaultHospital` is the one in view. */
export function ScenarioMenu({
  hospitals,
  defaultHospital,
  active,
}: {
  hospitals: { id: string; name: string; lat: number; lon: number }[];
  defaultHospital: string | null;
  active: { id: string; name: string; hospital_id: string | null }[];
}) {
  const [open, setOpen] = useState(false);
  const [hospital, setHospital] = useState(defaultHospital ?? hospitals[0]?.id ?? '');
  const setProblem = useTwin((s) => s.setProblem);
  const fail = (e: unknown) => { setProblem(`Scenario request failed: ${e instanceof Error ? e.message : String(e)}`); };
  const start = (name: ScenarioName) => {
    const h = hospitals.find((x) => x.id === hospital);
    const where = name === 'mass_casualty' && h ? { lat: h.lat, lon: h.lon } : undefined;
    api.startScenario(name, name === 'mass_casualty' ? null : hospital || null, where).catch(fail);
    setOpen(false);
  };
  return (
    <div className="scenario">
      <button type="button" className="btn btn--accent" aria-expanded={open} onClick={() => { setOpen(!open); }}>
        Run scenario
      </button>
      {open && (
        <div className="scenario__menu" role="menu">
          <label>
            At
            <select value={hospital} onChange={(e) => { setHospital(e.target.value); }} aria-label="Hospital for the scenario">
              {hospitals.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}
                </option>
              ))}
            </select>
          </label>
          {SCENARIOS.map((s) => (
            <button key={s.name} type="button" role="menuitem" className="btn" onClick={() => { start(s.name); }}>
              {s.label}
            </button>
          ))}
        </div>
      )}
      {active.length > 0 && (
        <ul className="scenario__active" aria-label="Active scenarios">
          {active.map((s) => (
            <li key={s.id}>
              <span>{s.name.replace('_', ' ')}</span>
              <button type="button" className="btn btn--small" onClick={() => {
                  api.stopScenario(s.id).catch(fail);
                }}>
                Stop
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
