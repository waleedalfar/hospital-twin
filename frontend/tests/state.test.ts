import { describe, expect, it, vi } from 'vitest';

import { Api, ApiError, type Fetch } from '../src/state/api';
import { formatSimClock, initialClock, onMessage, simNow } from '../src/state/clock';
import { feedItem } from '../src/state/feed';
import { applyEvents, fromSnapshot } from '../src/state/reducers';
import { backoffDelay, parseMessage, WsClient, type ConnectionStatus, type SocketLike } from '../src/state/socket';
import type { EventsMessage, SimEvent } from '../src/state/types';
import { FEED_LIMIT } from '../src/state/types';
import { loadSnapshot } from './engine/helpers';

const snap = loadSnapshot();
const base = fromSnapshot(snap);
const T = '2026-11-17T23:52:00Z';

function events(list: object[], overrides: Partial<EventsMessage> = {}): EventsMessage {
  return {
    v: 1,
    type: 'events',
    sim_time: T,
    speed: 4,
    paused: false,
    frozen: false,
    events: list as SimEvent[],
    kpis: { census: 1, capacity: 29, er_wait_min: 2, waiting: 0, alerts: 0 },
    ...overrides,
  };
}

describe('reducers', () => {
  it('builds hospital data from a snapshot', () => {
    expect(Object.keys(base.entities)).toHaveLength(snap.entities.length);
    expect(Object.keys(base.beds)).toHaveLength(29);
    expect(base.hospital.id).toBe('mercy');
    expect(base.feed).toEqual([]);
  });

  it('spawns and despawns entities without mutating the old state', () => {
    const entity = { ...Object.values(base.entities)[0]!, id: 'P-9999' };
    const a = applyEvents(base, events([{ kind: 'spawn', time: T, entity }]), 0);
    expect(a.entities['P-9999']).toEqual(entity);
    expect(base.entities['P-9999']).toBeUndefined();
    const b = applyEvents(a, events([{ kind: 'despawn', time: T, entity_id: 'P-9999', reason: 'left' }]), 0);
    expect(b.entities['P-9999']).toBeUndefined();
    expect(Object.keys(b.entities)).toHaveLength(Object.keys(base.entities).length);
  });

  it('a move sets the new location, the path and the walking pose', () => {
    const nurse = Object.values(base.entities).find((e) => e.kind === 'nurse')!;
    const to = { floor: 2, room: 'ICU', bed: null, spot: 'ICU-ws-1', vehicle: null };
    const move = { kind: 'move', time: T, entity_id: nurse.id, from: nurse.location, to, path: ['a', 'b'], times: [T, T], depart: T, arrive: T };
    const next = applyEvents(base, events([move]), 0);
    expect(next.entities[nurse.id]).toMatchObject({ location: to, pose: 'walking', move: { path: ['a', 'b'], arrive: T } });
    expect(applyEvents(base, events([{ ...move, entity_id: 'N-404' }]), 0)).toMatchObject({ entities: base.entities });
  });

  it('applies vitals, risk, beds, hospital status and kpis', () => {
    const patient = Object.values(base.entities).find((e) => e.kind === 'patient' && e.location.bed)!;
    const vitals = { hr: 99, spo2: 91, sbp: 100, dbp: 60, temp: 38, rr: 22 };
    const out = applyEvents(
      base,
      events([
        { kind: 'vitals', time: T, patient_id: patient.id, vitals },
        { kind: 'risk', time: T, patient_id: patient.id, score: 0.9, level: 'high', top_factors: [['SpO2', 0.2]], model_version: 'v1' },
        { kind: 'bed', time: T, bed_id: 'ICU-1', patient_id: null, state: 'cleaning' },
        { kind: 'hospital_status', time: T, status: 'diverting', until: null, reason: 'x' },
        { kind: 'vitals', time: T, patient_id: 'P-404', vitals },
      ]),
      0,
    );
    expect(out.entities[patient.id]?.vitals).toEqual(vitals);
    expect(out.entities[patient.id]?.risk).toMatchObject({ score: 0.9, level: 'high', model_version: 'v1' });
    expect(out.beds['ICU-1']).toEqual({ id: 'ICU-1', patient_id: null, state: 'cleaning' });
    expect(out.hospital.status).toBe('diverting');
    expect(out.kpis.census).toBe(1);
    expect(out.speed).toBe(4);
    expect(out.simTime).toBe(T);
  });

  it('tracks vehicles on the grounds, scenarios and ignores unknown kinds', () => {
    const amb = { kind: 'ambulance', time: T, vehicle_id: 'AMB-1', vehicle_kind: 'ambulance', slot: 'AMB-slot-2', destination: null, patient_id: null };
    let s = applyEvents(base, events([{ ...amb, status: 'unloading' }]), 0);
    expect(s.vehicles.find((v) => v.id === 'AMB-1')).toMatchObject({ status: 'unloading', slot: 'AMB-slot-2' });
    s = applyEvents(s, events([{ ...amb, status: 'at_base' }]), 0);
    expect(s.vehicles.filter((v) => v.id === 'AMB-1')).toHaveLength(1);
    s = applyEvents(s, events([{ ...amb, status: 'to_scene' }]), 0);
    expect(s.vehicles.find((v) => v.id === 'AMB-1')).toBeUndefined();
    s = applyEvents(s, events([{ kind: 'scenario', time: T, scenario_id: 'SC-1', name: 'flu_surge', status: 'started', hospital_id: 'mercy', params: { duration_min: 180 } }]), 0);
    expect(s.scenarios).toHaveLength(1);
    expect(Date.parse(s.scenarios[0]!.ends!) - Date.parse(T)).toBe(180 * 60_000);
    s = applyEvents(s, events([{ kind: 'scenario', time: T, scenario_id: 'SC-2', name: 'hospital_offline', status: 'started', hospital_id: null, params: {} }]), 0);
    expect(s.scenarios.find((x) => x.id === 'SC-2')?.ends).toBeNull();
    s = applyEvents(s, events([{ kind: 'scenario', time: T, scenario_id: 'SC-1', name: 'flu_surge', status: 'stopped', hospital_id: 'mercy', params: {} }]), 0);
    expect(s.scenarios.map((x) => x.id)).toEqual(['SC-2']);
    expect(applyEvents(s, events([{ kind: 'triage', time: T, patient_id: 'P-1', esi: 3 }]), 0).entities).toBe(s.entities);
  });

  it('keeps a bounded feed, newest first', () => {
    const many = Array.from({ length: FEED_LIMIT + 10 }, (_, i) => ({ kind: 'discharge', time: T, patient_id: `P-${i}`, los_h: 1, expedited: false }));
    const out = applyEvents(base, events(many), 100);
    expect(out.feed).toHaveLength(FEED_LIMIT);
    expect(out.feed[0]?.who).toBe(`P-${FEED_LIMIT + 9}`);
    expect(out.feed[0]?.key).toBe(100 + FEED_LIMIT + 9);
    const again = applyEvents(out, events([{ kind: 'discharge', time: T, patient_id: 'P-new', los_h: 1, expedited: true }]), 500);
    expect(again.feed[0]).toMatchObject({ who: 'P-new', what: 'discharged early' });
  });
});

describe('feed lines', () => {
  const line = (e: object) => feedItem({ time: T, ...e } as SimEvent, 1);
  it('describes the events people care about and skips the quiet ones', () => {
    expect(line({ kind: 'arrival', patient_id: 'P-1', mode: 'ambulance', esi: 2, complaint: 'other', encounter_id: 1 })).toMatchObject({ what: 'arrives by ambulance, ESI 2', tone: 'high' });
    expect(line({ kind: 'arrival', patient_id: 'P-1', mode: 'walk_in', esi: 4, complaint: 'other', encounter_id: 1 })?.tone).toBe('info');
    expect(line({ kind: 'er_admit', patient_id: 'P-1', bed_id: 'ER-2', wait_min: 12.4 })?.what).toBe('to ER-2 after 12 min');
    expect(line({ kind: 'admit', patient_id: 'P-1', unit: 'ICU', bed_id: 'ICU-3' })?.what).toContain('ICU');
    expect(line({ kind: 'surgery', patient_id: 'P-1', phase: 'start' })?.what).toBe('surgery started');
    expect(line({ kind: 'surgery', patient_id: 'P-1', phase: 'end' })?.what).toBe('surgery done');
    expect(line({ kind: 'transfer', patient_id: 'P-1', to_hospital: 'stlukes', vehicle_id: 'A' })?.what).toContain('stlukes');
    expect(line({ kind: 'critical', patient_id: 'P-1', unit: 'WARD', response: 'icu_transfer' })?.what).toContain('ICU');
    expect(line({ kind: 'critical', patient_id: 'P-1', unit: 'WARD', response: 'rapid_response' })?.what).toContain('rapid');
    expect(line({ kind: 'alert', patient_id: 'P-1', level: 'high', score: 0.9 })?.tone).toBe('high');
    expect(line({ kind: 'staff', entity_id: 'N-1', change: 'on_duty', reason: '' })?.what).toBe('on duty');
    expect(line({ kind: 'staff', entity_id: 'N-1', change: 'off_duty', reason: '' })?.what).toBe('off duty');
    expect(line({ kind: 'ambulance', vehicle_id: 'A', vehicle_kind: 'ambulance', status: 'unloading', slot: null, destination: null, patient_id: 'P-1' })?.what).toBe('unloading P-1');
    expect(line({ kind: 'ambulance', vehicle_id: 'A', vehicle_kind: 'ambulance', status: 'at_base', slot: null, destination: null, patient_id: null })).toBeNull();
    expect(line({ kind: 'hospital_status', status: 'offline', until: null, reason: '' })?.tone).toBe('high');
    expect(line({ kind: 'hospital_status', status: 'open', until: null, reason: '' })?.tone).toBe('low');
    expect(line({ kind: 'scenario', scenario_id: 'S', name: 'flu_surge', status: 'started', hospital_id: null, params: {} })?.what).toBe('flu surge started');
    expect(line({ kind: 'action', action: 'hold_bed', params: {}, result: 'holding' })?.who).toBe('Action');
    expect(line({ kind: 'discharge', patient_id: 'P-1', los_h: 3, expedited: false })?.what).toBe('discharged');
    expect(line({ kind: 'move', entity_id: 'N-1' })).toBeNull();
    expect(line({ kind: 'vitals', patient_id: 'P-1' })).toBeNull();
  });
});

describe('clock', () => {
  it('keeps time between ticks at the current speed and never runs ahead of the next tick', () => {
    const t = '2026-11-14T15:00:00Z';
    const c = onMessage(t, 4, false, false, 1000);
    expect(simNow(c, 1000)).toBe(Date.parse(t));
    expect(simNow(c, 1100)).toBe(Date.parse(t) + 24_000); // 100 real ms at 4x = 24 sim seconds
    expect(simNow(c, 5000)).toBe(Date.parse(t) + 72_000);
    expect(simNow(c, 500)).toBe(Date.parse(t)); // a clock that runs backwards cannot go back in time
  });
  it('holds still while paused or frozen', () => {
    const t = '2026-11-14T15:00:00Z';
    expect(simNow(onMessage(t, 8, true, false, 0), 9999)).toBe(Date.parse(t));
    expect(simNow(onMessage(t, 8, false, true, 0), 9999)).toBe(Date.parse(t));
    expect(simNow(initialClock(), 5)).toBe(0);
    expect(() => onMessage('nope', 1, false, false, 0)).toThrow('Bad sim time');
  });
  it('formats the sim clock in Phoenix time with a day number', () => {
    expect(formatSimClock(Date.parse('2026-11-14T15:00:00Z'))).toEqual({ day: 1, clock: '08:00' });
    expect(formatSimClock(Date.parse('2026-11-15T21:32:00Z'))).toEqual({ day: 2, clock: '14:32' });
    expect(formatSimClock(Date.parse('2026-11-15T06:59:00Z')).day).toBe(1);
    expect(formatSimClock(Date.parse('2026-11-15T07:00:00Z')).day).toBe(2);
  });
});

describe('socket client', () => {
  class FakeSocket implements SocketLike {
    onopen: SocketLike['onopen'] = null;
    onmessage: SocketLike['onmessage'] = null;
    onclose: SocketLike['onclose'] = null;
    onerror: SocketLike['onerror'] = null;
    closed = false;
    close(): void {
      this.closed = true;
    }
  }

  function harness() {
    const sockets: FakeSocket[] = [];
    const timers: { fn: () => void; ms: number; id: number }[] = [];
    const statuses: ConnectionStatus[] = [];
    const messages: string[] = [];
    const problems: string[] = [];
    const client = new WsClient({
      url: () => 'ws://x/ws?hospital=mercy',
      onMessage: (m) => messages.push(m.type ?? ''),
      onStatus: (s) => statuses.push(s),
      onProblem: (p) => problems.push(p),
      create: () => {
        const s = new FakeSocket();
        sockets.push(s);
        return s;
      },
      setTimer: (fn, ms) => {
        timers.push({ fn, ms, id: timers.length });
        return timers.length - 1;
      },
      clearTimer: (h) => {
        const t = timers[h as number];
        if (t) t.fn = () => undefined;
      },
    });
    return { client, sockets, timers, statuses, messages, problems };
  }

  it('connects, delivers messages, and reconnects with backoff after the server goes away', () => {
    const h = harness();
    h.client.start();
    expect(h.statuses).toEqual(['connecting']);
    h.sockets[0]!.onopen?.({});
    expect(h.statuses.at(-1)).toBe('open');
    h.sockets[0]!.onmessage?.({ data: JSON.stringify({ v: 1, type: 'snapshot' }) });
    expect(h.messages).toEqual(['snapshot']);
    h.sockets[0]!.onclose?.({});
    expect(h.statuses.at(-1)).toBe('reconnecting');
    expect(h.timers[0]!.ms).toBe(500);
    h.timers[0]!.fn();
    expect(h.sockets).toHaveLength(2);
    h.sockets[1]!.onclose?.({}); // still down
    expect(h.timers[1]!.ms).toBe(1000);
    h.timers[1]!.fn();
    h.sockets[2]!.onclose?.({});
    expect(h.timers[2]!.ms).toBe(2000);
    h.timers[2]!.fn();
    h.sockets[3]!.onopen?.({}); // back: the backoff resets
    h.sockets[3]!.onclose?.({});
    expect(h.timers[3]!.ms).toBe(500);
  });

  it('backoff is capped', () => {
    expect([0, 1, 2, 3, 4, 5, 50].map(backoffDelay)).toEqual([500, 1000, 2000, 4000, 8000, 8000, 8000]);
  });

  it('stop closes the socket, cancels retries and reports closed', () => {
    const h = harness();
    h.client.start();
    h.sockets[0]!.onclose?.({});
    h.client.stop();
    h.timers[0]!.fn();
    expect(h.sockets).toHaveLength(1);
    expect(h.statuses.at(-1)).toBe('closed');
    const g = harness();
    g.client.start();
    g.client.stop();
    expect(g.sockets[0]!.closed).toBe(true);
  });

  it('surfaces server error messages and bad messages instead of hiding them', () => {
    const h = harness();
    const spy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    h.client.start();
    h.sockets[0]!.onmessage?.({ data: JSON.stringify({ v: 1, type: 'error', message: 'Unknown hospital' }) });
    h.sockets[0]!.onmessage?.({ data: 'not json' });
    h.sockets[0]!.onmessage?.({ data: JSON.stringify({ v: 2, type: 'snapshot' }) });
    h.sockets[0]!.onerror?.({});
    expect(h.problems[0]).toBe('Unknown hospital');
    expect(h.problems).toHaveLength(3);
    expect(h.messages).toEqual([]);
    spy.mockRestore();
  });

  it('parses and validates messages', () => {
    expect(parseMessage('{"v":1,"type":"events"}').type).toBe('events');
    expect(() => parseMessage('{"v":1,"type":"weird"}')).toThrow('Unknown message type');
    expect(() => parseMessage(5)).toThrow('not text');
  });
});

describe('REST client', () => {
  const ok = (body: unknown): Fetch => vi.fn<Fetch>().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));

  it('calls the typed endpoints', async () => {
    const f = ok({ points: [{ time: 't' }] });
    const api = new Api(f);
    expect(await api.vitals('P-1', '2h')).toEqual([{ time: 't' }]);
    expect(f).toHaveBeenCalledWith('/api/patients/P-1/vitals?window=2h', expect.anything());
    expect(await new Api(ok({ points: [] })).risk('P-1')).toEqual([]);
    expect((await new Api(ok({ id: 'P-1' })).patient('P-1')).id).toBe('P-1');
    const post = vi.fn<Fetch>().mockImplementation(() => Promise.resolve(new Response('{"speed":8}', { status: 200 })));
    await new Api(post).setSpeed(8);
    expect(post).toHaveBeenCalledWith('/api/sim/speed', expect.objectContaining({ method: 'POST', body: '{"speed":8}' }));
    await new Api(post).setPaused(true);
    await new Api(post).setFrozen(true);
    await new Api(post).sim();
    await new Api(post).startScenario('mass_casualty', null, { lat: 1, lon: 2 });
    await new Api(post).startScenario('flu_surge', 'mercy');
    await new Api(post).stopScenario('SC-1');
    expect(post).toHaveBeenCalledWith('/api/scenario/SC-1', expect.objectContaining({ method: 'DELETE' }));
    expect(post.mock.calls.map((c) => c[0])).toContain('/api/sim/freeze');
  });

  it('reports server details, bad statuses and network errors', async () => {
    const detail = vi.fn<Fetch>().mockResolvedValue(new Response('{"detail":"Unknown patient P-9"}', { status: 404 }));
    await expect(new Api(detail).patient('P-9')).rejects.toMatchObject({ message: 'Unknown patient P-9', status: 404 });
    const plain = vi.fn<Fetch>().mockResolvedValue(new Response('oops', { status: 500 }));
    await expect(new Api(plain).patient('P-9')).rejects.toMatchObject({ message: 'HTTP 500', status: 500 });
    const down = vi.fn<Fetch>().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(new Api(down).patient('P-9')).rejects.toBeInstanceOf(ApiError);
    await expect(new Api(down).patient('P-9')).rejects.toThrow('Network error: Failed to fetch');
    const nonError = vi.fn<Fetch>().mockRejectedValue('x');
    await expect(new Api(nonError).sim()).rejects.toThrow('Network error: x');
  });
});
