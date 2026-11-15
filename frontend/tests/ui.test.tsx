import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fromSnapshot } from '../src/state/reducers';
import { useTwin } from '../src/state/store';
import type { Entity, NetworkMessage } from '../src/state/types';
import { Banners, ScenarioMenu, SimClock, SpeedControls } from '../src/ui/common';
import { dotOn, FloorPlan } from '../src/ui/hospital/FloorPlan';
import { flagged, Inspector } from '../src/ui/hospital/Inspector';
import { KpiStrip, Legend, LiveFeed, PresetBar } from '../src/ui/hospital/Panels';
import { Sparkline } from '../src/ui/hospital/Sparkline';
import { NetworkMap } from '../src/ui/network/NetworkMap';
import { loadSnapshot } from './engine/helpers';

const snap = loadSnapshot();
const data = fromSnapshot(snap);

class StubSocket {
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close(): void {
    this.onclose = null;
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', StubSocket);
  vi.stubGlobal('requestAnimationFrame', () => 0);
  vi.stubGlobal('cancelAnimationFrame', () => undefined);
  HTMLCanvasElement.prototype.getContext = (() => null) as never;
  useTwin.setState({ problem: null, network: null, networkConnection: 'closed', selectedId: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('sparkline', () => {
  it('draws a labelled chart and says when there is not enough data', () => {
    render(<Sparkline label="HR" points={[{ t: 0, v: 70 }, { t: 10, v: 90 }, { t: 20, v: 80 }]} />);
    expect(screen.getByRole('img', { name: 'HR: latest 80' })).toBeTruthy();
    cleanup();
    render(<Sparkline label="HR" points={[{ t: 0, v: 70 }]} />);
    expect(screen.getByRole('img', { name: 'HR: not enough data yet' })).toBeTruthy();
  });
  it('fits a flat line without dividing by zero', () => {
    const { container } = render(<Sparkline label="x" min={0} max={1} points={[{ t: 5, v: 0.5 }, { t: 5, v: 0.5 }]} />);
    expect(container.querySelector('polyline')?.getAttribute('points')).not.toContain('NaN');
  });
});

describe('panels', () => {
  it('shows the KPI strip, the feed and the legend', () => {
    render(<KpiStrip kpis={{ census: 22, capacity: 29, er_wait_min: 40.6, waiting: 7, alerts: 1 }} />);
    expect(screen.getByTestId('kpis').textContent).toContain('CENSUS 22/29');
    expect(screen.getByTestId('kpis').textContent).toContain('ER WAIT 41m');
    cleanup();
    render(<LiveFeed feed={[]} />);
    expect(screen.getByText('Waiting for events…')).toBeTruthy();
    cleanup();
    render(<LiveFeed feed={[{ time: '2026-11-14T21:32:00Z', who: 'P-1', what: 'discharged', tone: 'low', key: 1 }]} />);
    expect(screen.getByTestId('feed-row').textContent).toContain('14:32');
    cleanup();
    const { rerender } = render(<Legend xray={false} />);
    expect(screen.queryByTestId('xray-legend')).toBeNull();
    rerender(<Legend xray />);
    expect(screen.getByTestId('xray-legend').textContent).toContain('Surgeon');
  });
  it('lists the nine camera presets and reports the pick', () => {
    const pick = vi.fn();
    render(<PresetBar active="ground" onPick={pick} />);
    expect(screen.getAllByRole('button')).toHaveLength(9);
    expect(screen.getByRole('button', { name: 'Ground floor' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Floor 3' }));
    expect(pick).toHaveBeenCalledWith('floor3');
  });
});

describe('common controls', () => {
  it('shows the sim clock in Phoenix time, labelled SIM', () => {
    render(<SimClock simMs={Date.parse('2026-11-14T15:30:00Z')} />);
    expect(screen.getByTestId('sim-clock').textContent).toBe('SIM DAY 1 · 08:30');
    cleanup();
    render(<SimClock simMs={0} />);
    expect(screen.getByText('SIM --:--')).toBeTruthy();
  });

  it('shows the disconnected banner and a dismissable problem', () => {
    const { rerender } = render(<Banners connection="open" />);
    expect(screen.queryByTestId('disconnected-banner')).toBeNull();
    rerender(<Banners connection="reconnecting" />);
    expect(screen.getByTestId('disconnected-banner').textContent).toContain('Disconnected');
    act(() => useTwin.getState().setProblem('Something broke'));
    expect(screen.getByTestId('problem-banner').textContent).toContain('Something broke');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('problem-banner')).toBeNull();
  });

  it('speed and pause buttons call the API and report failures', async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(json({})));
    vi.stubGlobal('fetch', f);
    render(<SpeedControls speed={4} paused={false} />);
    expect(screen.getByRole('button', { name: '4x' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: '8x' }));
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2));
    expect(f.mock.calls[0]?.[0]).toBe('/api/sim/speed');
    expect(f.mock.calls[1]?.[0]).toBe('/api/sim/pause');
    f.mockImplementation(() => Promise.resolve(json({ detail: 'nope' }, 422)));
    fireEvent.click(screen.getByRole('button', { name: '1x' }));
    await waitFor(() => expect(useTwin.getState().problem).toContain('nope'));
  });

  it('scenario menu starts scenarios at the chosen hospital and stops active ones', async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(json({ id: 'SC-1' })));
    vi.stubGlobal('fetch', f);
    const hospitals = [
      { id: 'mercy', name: 'Mercy General', lat: 33.4, lon: -112.1 },
      { id: 'stlukes', name: "St. Luke's", lat: 33.5, lon: -112.0 },
    ];
    render(<ScenarioMenu hospitals={hospitals} defaultHospital="stlukes" active={[{ id: 'SC-9', name: 'flu_surge', hospital_id: 'mercy' }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    expect(screen.getByLabelText<HTMLSelectElement>('Hospital for the scenario').value).toBe('stlukes');
    fireEvent.click(screen.getByRole('menuitem', { name: 'Flu surge' }));
    await waitFor(() => expect(f).toHaveBeenCalled());
    expect(JSON.parse((f.mock.calls[0]?.[1] as RequestInit).body as string)).toMatchObject({ name: 'flu_surge', hospital_id: 'stlukes' });
    fireEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    fireEvent.change(screen.getByLabelText('Hospital for the scenario'), { target: { value: 'mercy' } });
    fireEvent.click(screen.getByRole('menuitem', { name: 'Mass casualty' }));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2));
    expect(JSON.parse((f.mock.calls[1]?.[1] as RequestInit).body as string)).toMatchObject({ name: 'mass_casualty', hospital_id: null, lat: 33.4, lon: -112.1 });
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(f.mock.calls[2]?.[0]).toBe('/api/scenario/SC-9'));
    f.mockImplementation(() => Promise.resolve(json({ detail: 'bad' }, 422)));
    fireEvent.click(screen.getByRole('button', { name: 'Run scenario' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Hospital offline' }));
    await waitFor(() => expect(useTwin.getState().problem).toContain('Scenario request failed: bad'));
  });
});

describe('inspector', () => {
  const patient = Object.values(data.entities).find((e) => e.kind === 'patient' && e.location.bed === 'ICU-3') as Entity;

  it('asks to select someone when nothing is selected', () => {
    render(<Inspector entity={undefined} onFly={vi.fn()} />);
    expect(screen.getByText(/Select a patient/)).toBeTruthy();
  });

  it('shows a patient with live vitals, risk, factors, FHIR id and history from the API', async () => {
    const f = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith('/vitals?window=6h'))
        return Promise.resolve(json({ points: [{ time: '2026-11-17T22:00:00Z', hr: 80, spo2: 97, sbp: 120, dbp: 80, temp: 37, rr: 16, samples: 1 }, { time: '2026-11-17T22:05:00Z', hr: 90, spo2: 96, sbp: 118, dbp: 78, temp: 37, rr: 17, samples: 1 }] }));
      if (url.endsWith('/risk?window=6h')) return Promise.resolve(json({ points: [] }));
      return Promise.resolve(
        json({ id: patient.id, fhir_id: 'Patient/abc', age: 67, sex: 'male', conditions: ['A', 'B', 'C', 'D', 'E'], comorbidity_count: 3, hospital_id: 'mercy', location: null, encounter: { id: 1, hospital_id: 'mercy', arrived_at: 'x', mode: 'walk_in', esi: 2, disposition: 'admit_icu', ended_at: null }, vitals: null, risk: null }),
      );
    });
    vi.stubGlobal('fetch', f);
    const fly = vi.fn();
    const withVitals: Entity = { ...patient, risk: null, vitals: { hr: 130, spo2: 88, sbp: 104, dbp: 66, temp: 38.4, rr: 24 } };
    render(<Inspector entity={withVitals} onFly={fly} />);
    expect(screen.getByTestId('inspector-id').textContent).toBe(patient.id);
    expect(screen.getByLabelText('Live vital signs').textContent).toContain('130 !');
    expect(screen.getByLabelText('Live vital signs').textContent).toContain('88% !');
    expect(screen.getByText('No risk score yet')).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('inspector-fhir').textContent).toBe('Patient/abc'));
    expect(screen.getByTestId('inspector-bed').textContent).toContain('age 67');
    expect(screen.getByText(/admit icu/)).toBeTruthy();
    expect(screen.getByText(/\+1/)).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('img', { name: /Heart rate.*latest 90/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Fly to this bed' }));
    expect(fly).toHaveBeenCalled();
  });

  it('shows the model score and top factors when the entity has a risk', () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ points: [] }))));
    const scored: Entity = { ...patient, risk: { score: 0.81, level: 'high', top_factors: [['SpO2 drop, 2h', 0.21], ['HR trend', 0.14]], model_version: 'v1' } };
    render(<Inspector entity={scored} onFly={vi.fn()} />);
    expect(screen.getByText('0.81')).toBeTruthy();
    expect(screen.getByText('HIGH RISK')).toBeTruthy();
    expect(screen.getByText('Why the model flagged this')).toBeTruthy();
    expect(screen.getByText('SpO2 drop, 2h')).toBeTruthy();
  });

  it('shows record loading errors instead of hiding them', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ detail: 'Unknown patient' }, 404))));
    render(<Inspector entity={patient} onFly={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Unknown patient'));
    spy.mockRestore();
  });

  it('shows staff with role, unit and task, without calling the patient API', () => {
    const f = vi.fn();
    vi.stubGlobal('fetch', f);
    const nurse = Object.values(data.entities).find((e) => e.kind === 'nurse') as Entity;
    render(<Inspector entity={{ ...nurse, task: 'vitals' }} onFly={vi.fn()} />);
    expect(screen.getByText('Nurse', { selector: 'dd' })).toBeTruthy();
    expect(screen.getByText('vitals')).toBeTruthy();
    expect(f).not.toHaveBeenCalled();
  });

  it('flags vital signs outside the usual range', () => {
    expect(flagged('hr', 120)).toBe(true);
    expect(flagged('hr', 80)).toBe(false);
    expect(flagged('hr', 40)).toBe(true);
    expect(flagged('spo2', 90)).toBe(true);
    expect(flagged('sbp', 90)).toBe(true);
    expect(flagged('sbp', 170)).toBe(true);
    expect(flagged('temp', 38.2)).toBe(true);
    expect(flagged('temp', 35)).toBe(true);
    expect(flagged('rr', 25)).toBe(true);
    expect(flagged('rr', 8)).toBe(true);
    expect(flagged('rr', 16)).toBe(false);
    expect(flagged('bp', 16)).toBe(false);
  });
});

describe('floor plan', () => {
  it('places resting entities at their bed or seat and walking ones along their path, per floor', () => {
    const inBed = Object.values(data.entities).find((e) => e.location.bed === 'ICU-3' && !e.move) as Entity;
    const sim = Date.parse(snap.sim_time);
    expect(dotOn(inBed, 2, sim)).toMatchObject({ x: -11.3, z: -12.4 }) // ICU-3 = -18.5 + 2 x 3.6;
    expect(dotOn(inBed, 0, sim)).toBeNull();
    const walker = Object.values(data.entities).find((e) => e.move && e.move.times.length > 3) as Entity;
    const times = walker.move?.times.map(Date.parse) ?? [];
    const mid = ((times[0] ?? 0) + (times[times.length - 1] ?? 0)) / 2;
    const floors = [0, 1, 2].map((l) => dotOn(walker, l, mid)).filter(Boolean);
    expect(floors).toHaveLength(1);
    const nobody: Entity = { ...inBed, location: { floor: 0, room: 'ER', bed: null, spot: null } };
    expect(dotOn(nobody, 0, sim)).toBeNull();
  });

  it('draws people as plain squares, selects on click and switches floors', () => {
    const onSelect = vi.fn();
    render(<FloorPlan data={data} simNow={() => Date.parse(snap.sim_time)} selectedId={null} onSelect={onSelect} />);
    expect(screen.getAllByRole('tab')).toHaveLength(3);
    fireEvent.click(screen.getByRole('tab', { name: /Floor 3/ }));
    const dots = screen.getAllByTestId('plan-dot');
    expect(dots.length).toBeGreaterThan(3);
    fireEvent.click(dots[0] as Element);
    expect(onSelect).toHaveBeenCalledWith((dots[0] as Element).getAttribute('data-entity'));
    expect(document.querySelectorAll('svg circle, svg ellipse, svg path').length).toBe(0); // no faces, only squares
  });
});

describe('network map', () => {
  const net: NetworkMessage = {
    v: 1,
    type: 'network',
    sim_time: '2026-11-14T15:30:00Z',
    speed: 4,
    paused: false,
    frozen: false,
    hospitals: [
      { id: 'mercy', name: 'Mercy General', lat: 33.4484, lon: -112.074, status: 'open', status_until: null, kpis: { census: 27, capacity: 29, er_wait_min: 52, waiting: 4, alerts: 0 } },
      { id: 'stlukes', name: "St. Luke's", lat: 33.5106, lon: -112.0296, status: 'diverting', status_until: null, kpis: { census: 10, capacity: 29, er_wait_min: 8, waiting: 0, alerts: 0 } },
      { id: 'desert', name: 'Desert Valley', lat: 33.3942, lon: -112.1513, status: 'offline', status_until: null, kpis: { census: 5, capacity: 29, er_wait_min: 0, waiting: 0, alerts: 0 } },
    ],
    vehicles: [
      { id: 'AMB-mercy-1', kind: 'ambulance', home: 'mercy', status: 'to_hospital', destination: 'stlukes', patient_id: 'P-0042', lat: 33.45, lon: -112.07, route: [{ lat: 33.4484, lon: -112.074, t: '2026-11-14T15:20:00Z' }, { lat: 33.5106, lon: -112.0296, t: '2026-11-14T15:40:00Z' }] },
    ],
    scenarios: [],
  };

  it('lists hospitals with status in text, and ambulances on the road with their patient and destination', () => {
    useTwin.setState({ network: net, networkConnection: 'open', networkClock: { simMs: Date.parse(net.sim_time), receivedAt: 0, speed: 4, running: false } });
    render(<NetworkMap />);
    expect(screen.getByTestId('hospital-row-mercy').textContent).toContain('CRITICAL');
    expect(screen.getByTestId('hospital-row-stlukes').textContent).toContain('DIVERTING AMBULANCES');
    expect(screen.getByTestId('hospital-row-desert').textContent).toContain('OFFLINE');
    expect(screen.getByTestId('hospital-mercy').textContent).toContain('93%');
    expect(screen.getByTestId('incoming').textContent).toBe("AMB-mercy-1 · P-0042 → St. Luke's");
    expect(screen.getByText(/AMB-mercy-1 to St. Luke's · 10 min/)).toBeTruthy();
    expect(screen.getByTestId('sim-clock').textContent).toContain('08:30');
    location.hash = '';
    fireEvent.click(screen.getByTestId('hospital-mercy'));
    expect(location.hash).toBe('#/hospital/mercy');
  });

  it('shows a waiting message before the first network message', () => {
    render(<NetworkMap />);
    expect(screen.getByText('Waiting for the simulation…')).toBeTruthy();
    expect(screen.getByText('None on the road with a patient.')).toBeTruthy();
    expect(screen.queryByTestId('disconnected-banner')).toBeNull(); // still connecting, not disconnected
  });
});

describe('forecast and model panels', () => {
  const report = {
    hospital_id: 'mercy',
    as_of: '2026-11-14T15:00:00Z',
    model_version: 'arrivals-lgbm-v1',
    arrivals: [1, 2, 3, 4, 5, 6].map((h) => ({ hours_ahead: h, expected: 1 + h / 10 })),
    hours_until_full: { ER: 0, WARD: 6.5, ICU: null, REC: 12 },
  };

  it('shows expected arrivals and hours until each unit is full', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json(report))));
    const { ForecastPanel } = await import('../src/ui/hospital/MlPanels');
    render(<ForecastPanel hospitalId="mercy" />);
    await waitFor(() => expect(screen.getByTestId('forecast-total').textContent).toBe('Arrivals expected: 8.1 in 6 h'));
    expect(screen.getByTestId('full-ER').textContent).toContain('FULL');
    expect(screen.getByTestId('full-WARD').textContent).toContain('full in 6.5 h');
    expect(screen.getByTestId('full-ICU').textContent).toContain('not within 24 h');
    expect(screen.getByTestId('full-REC').textContent).toContain('Recovery');
    expect(screen.getByRole('img', { name: /Expected arrivals per hour: 1.1, 1.2/ })).toBeTruthy();
    expect(screen.getByText('Model arrivals-lgbm-v1')).toBeTruthy();
  });

  it('says so when there is no forecast or the request fails', async () => {
    const { ForecastPanel } = await import('../src/ui/hospital/MlPanels');
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ ...report, arrivals: [], model_version: null, hours_until_full: {} }))));
    const { unmount } = render(<ForecastPanel hospitalId="mercy" />);
    await waitFor(() => expect(screen.getByText('No forecast yet (no model).')).toBeTruthy());
    unmount();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ detail: 'boom' }, 500))));
    render(<ForecastPanel hospitalId="mercy" />);
    await waitFor(() => expect(screen.getByText('Forecast unavailable: boom')).toBeTruthy());
    spy.mockRestore();
  });

  it('shows the active risk model and its validation AUROC, or why there is none', async () => {
    const { ModelBadge } = await import('../src/ui/hospital/MlPanels');
    const models = { active_deterioration: 'lgbm-v1', active_arrivals: 'a', error: null, models: [{ version: 'lgbm-v1', kind: 'deterioration', metrics: { validation: { model: { auroc: 0.9404 } } } }] };
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json(models))));
    const { unmount } = render(<ModelBadge />);
    await waitFor(() => expect(screen.getByTestId('model-badge').textContent).toBe('Risk model lgbm-v1 · AUROC 0.94'));
    unmount();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(json({ ...models, active_deterioration: null, error: 'Models not available. Run `make train`.', models: [] }))));
    render(<ModelBadge />);
    await waitFor(() => expect(screen.getByTestId('model-badge').textContent).toContain('make train'));
  });
});
