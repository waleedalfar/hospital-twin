import { describe, expect, it, vi } from 'vitest';

import { createTwinStore, defaultWsUrl, type ClientLike } from '../src/state/store';
import type { WsOptions } from '../src/state/socket';
import type { EventsMessage } from '../src/state/types';
import type { SnapshotMessage } from '../src/state/wsTypes';
import { loadSnapshot } from './engine/helpers';

// The recorded fixture was taken with the sim frozen; these tests need a running one.
const snap: SnapshotMessage = { ...loadSnapshot(), frozen: false };

function harness(freeze = false) {
  const clients: { opts: WsOptions; started: boolean; stopped: boolean }[] = [];
  const setFrozen = vi.fn().mockResolvedValue({});
  let now = 1000;
  const store = createTwinStore({
    createClient: (opts): ClientLike => {
      const c = { opts, started: false, stopped: false };
      clients.push(c);
      return {
        start: () => (c.started = true),
        stop: () => (c.stopped = true),
      };
    },
    api: { setFrozen },
    now: () => now,
    wsUrl: (p) => `ws://test${p}`,
  });
  store.getState().setFreeze(freeze);
  return { store, clients, setFrozen, setNow: (n: number) => (now = n) };
}

const events = (time: string, list: object[]): EventsMessage => ({
  v: 1,
  type: 'events',
  sim_time: time,
  speed: 1,
  paused: false,
  frozen: false,
  events: list as EventsMessage['events'],
  kpis: { census: 3, capacity: 29, er_wait_min: 0, waiting: 0, alerts: 0 },
});

describe('store', () => {
  it('connects to a hospital, applies the snapshot and then events', () => {
    const h = harness();
    h.store.getState().connectHospital('mercy');
    const c = h.clients[0]!;
    expect(c.started).toBe(true);
    expect(c.opts.url()).toBe('ws://test/ws?hospital=mercy');
    expect(h.store.getState().connection).toBe('connecting');
    c.opts.onStatus('open');
    expect(h.store.getState().connection).toBe('open');

    c.opts.onMessage(events(snap.sim_time, [])); // events before the snapshot are ignored
    expect(h.store.getState().data).toBeNull();
    c.opts.onMessage(snap);
    expect(Object.keys(h.store.getState().data!.entities)).toHaveLength(snap.entities.length);
    c.opts.onMessage(events('2026-11-17T23:52:00Z', [{ kind: 'discharge', time: '2026-11-17T23:52:00Z', patient_id: 'P-1', los_h: 2, expedited: false }]));
    expect(h.store.getState().data?.feed[0]).toMatchObject({ who: 'P-1', key: 0 });
    c.opts.onMessage(events('2026-11-17T23:53:00Z', [{ kind: 'discharge', time: '2026-11-17T23:53:00Z', patient_id: 'P-2', los_h: 2, expedited: false }]));
    expect(h.store.getState().data?.feed.map((f) => f.key)).toEqual([1, 0]);
  });

  it('keeps sim time between ticks and holds it while paused', () => {
    const h = harness();
    h.store.getState().connectHospital('mercy');
    const c = h.clients[0]!;
    h.setNow(1000);
    c.opts.onMessage(snap);
    const t0 = Date.parse(snap.sim_time);
    h.setNow(1100);
    expect(h.store.getState().simNowMs()).toBe(t0 + 6_000); // 100 ms at 1x = 6 sim seconds
    c.opts.onMessage({ ...snap, paused: true });
    h.setNow(5000);
    expect(h.store.getState().simNowMs()).toBe(t0);
  });

  it('asks the server to freeze the sim when the page is opened with ?freeze=1', async () => {
    const h = harness(true);
    h.store.getState().connectHospital('mercy');
    h.clients[0]!.opts.onMessage(snap);
    expect(h.setFrozen).toHaveBeenCalledWith(true);
    h.setFrozen.mockClear();
    h.clients[0]!.opts.onMessage({ ...snap, frozen: true });
    expect(h.setFrozen).not.toHaveBeenCalled();
    h.setFrozen.mockRejectedValueOnce(new Error('boom'));
    h.clients[0]!.opts.onMessage(snap);
    await Promise.resolve();
    await Promise.resolve();
    expect(h.store.getState().problem).toContain('Could not freeze');
  });

  it('switching hospitals replaces the connection and clears the selection', () => {
    const h = harness();
    const s = h.store.getState();
    s.connectHospital('mercy');
    h.clients[0]!.opts.onMessage(snap);
    s.select('P-1');
    h.store.getState().connectHospital('stlukes');
    expect(h.clients[0]!.stopped).toBe(true);
    expect(h.store.getState().selectedId).toBeNull();
    expect(h.store.getState().data).toBeNull();
    expect(h.clients[1]!.opts.url()).toBe('ws://test/ws?hospital=stlukes');
    h.store.getState().disconnectHospital();
    expect(h.clients[1]!.stopped).toBe(true);
    expect(h.store.getState()).toMatchObject({ hospitalId: null, connection: 'closed' });
  });

  it('streams the city network and reports problems', () => {
    const h = harness();
    h.store.getState().connectNetwork();
    const c = h.clients[0]!;
    expect(c.opts.url()).toBe('ws://test/ws/network');
    const net = { v: 1, type: 'network', sim_time: snap.sim_time, speed: 4, paused: false, frozen: false, hospitals: [], vehicles: [], scenarios: [] } as const;
    c.opts.onMessage(net as never);
    c.opts.onMessage(snap);
    expect(h.store.getState().network?.speed).toBe(4);
    expect(h.store.getState().networkNowMs()).toBeGreaterThanOrEqual(Date.parse(snap.sim_time));
    c.opts.onProblem?.('Unknown hospital');
    expect(h.store.getState().problem).toBe('Unknown hospital');
    h.store.getState().setProblem(null);
    expect(h.store.getState().problem).toBeNull();
    h.store.getState().disconnectNetwork();
    expect(h.store.getState().network).toBeNull();
    h.store.getState().connectNetwork();
    h.store.getState().connectNetwork();
    expect(h.clients[1]!.stopped).toBe(true);
  });

  it('builds ws and wss URLs from the page location', () => {
    expect(defaultWsUrl('/ws/network')).toBe(`ws://${location.host}/ws/network`);
  });
});
