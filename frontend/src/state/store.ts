/**
 * The client store (zustand): connection status, the current hospital's live data, the city network, the
 * selection, and the sim clock (PROMPT.md §10.6). The store applies each snapshot, then each events message,
 * and reconnects with a fresh snapshot after any disconnect.
 */
import { create, type StoreApi, type UseBoundStore } from 'zustand';

import { Api } from './api';
import { initialClock, onMessage as clockOnMessage, simNow, type ClockState } from './clock';
import { applyEvents, fromSnapshot, mergeRecs, recsIn } from './reducers';
import { WsClient, type ConnectionStatus, type WsOptions } from './socket';
import type { AgentRecModel, HospitalData, NetworkMessage } from './types';
import type { ServerMessage } from './wsTypes';

export interface ClientLike {
  start(): void;
  stop(): void;
}

export interface StoreDeps {
  createClient: (opts: WsOptions) => ClientLike;
  api: Pick<Api, 'setFrozen' | 'recs'>;
  now: () => number;
  wsUrl: (path: string) => string;
}

export interface TwinState {
  hospitalId: string | null;
  connection: ConnectionStatus;
  data: HospitalData | null;
  /** The operations agent's recommendations for this hospital, newest first. */
  recs: AgentRecModel[];
  clock: ClockState;
  network: NetworkMessage | null;
  networkConnection: ConnectionStatus;
  networkClock: ClockState;
  selectedId: string | null;
  /** The last thing that went wrong that the user should see (bad message, rejected request). */
  problem: string | null;
  /** `?freeze=1`: hold sim time for screenshot tests. */
  freeze: boolean;
  connectHospital: (id: string) => void;
  disconnectHospital: () => void;
  connectNetwork: () => void;
  disconnectNetwork: () => void;
  select: (id: string | null) => void;
  setProblem: (text: string | null) => void;
  setFreeze: (on: boolean) => void;
  simNowMs: () => number;
  networkNowMs: () => number;
}

export type TwinStore = UseBoundStore<StoreApi<TwinState>>;

export function defaultWsUrl(path: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}${path}`;
}

export function createTwinStore(deps: StoreDeps): TwinStore {
  let hospitalClient: ClientLike | null = null;
  let networkClient: ClientLike | null = null;
  let feedKey = 0;

  return create<TwinState>((set, get) => ({
    hospitalId: null,
    connection: 'closed',
    data: null,
    recs: [],
    clock: initialClock(),
    network: null,
    networkConnection: 'closed',
    networkClock: initialClock(),
    selectedId: null,
    problem: null,
    freeze: false,

    connectHospital: (id) => {
      hospitalClient?.stop();
      set({ hospitalId: id, data: null, recs: [], connection: 'connecting', selectedId: null, clock: initialClock() });
      hospitalClient = deps.createClient({
        url: () => deps.wsUrl(`/ws?hospital=${encodeURIComponent(id)}`),
        onStatus: (connection) => { set({ connection }); },
        onProblem: (problem) => { set({ problem }); },
        onMessage: (msg: ServerMessage) => {
          if (msg.type === 'snapshot') {
            const data = fromSnapshot(msg);
            set({ data, clock: clockOnMessage(msg.sim_time, msg.speed, msg.paused, msg.frozen, deps.now()) });
            // Recommendations are not part of the snapshot: load the stored ones, and keep up through events.
            deps.api.recs(id).then(
              (list) => { set((s) => ({ recs: mergeRecs(s.recs, list) })); },
              (e: unknown) => { set({ problem: `Could not load the agent's recommendations: ${String(e)}` }); },
            );
            if (get().freeze && !msg.frozen) {
              deps.api.setFrozen(true).catch((e: unknown) => { set({ problem: `Could not freeze the sim: ${String(e)}` }); });
            }
          } else if (msg.type === 'events') {
            const { data } = get();
            if (!data) return;
            const next = applyEvents(data, msg, feedKey);
            feedKey += msg.events.length;
            const fresh = recsIn(msg);
            set((s) => ({
              data: next,
              recs: fresh.length > 0 ? mergeRecs(s.recs, fresh) : s.recs,
              clock: clockOnMessage(msg.sim_time, msg.speed, msg.paused, msg.frozen, deps.now()),
            }));
          }
        },
      });
      hospitalClient.start();
    },

    disconnectHospital: () => {
      hospitalClient?.stop();
      hospitalClient = null;
      set({ hospitalId: null, data: null, recs: [], connection: 'closed', selectedId: null });
    },

    connectNetwork: () => {
      networkClient?.stop();
      set({ networkConnection: 'connecting' });
      networkClient = deps.createClient({
        url: () => deps.wsUrl('/ws/network'),
        onStatus: (networkConnection) => { set({ networkConnection }); },
        onProblem: (problem) => { set({ problem }); },
        onMessage: (msg: ServerMessage) => {
          if (msg.type === 'network') {
            set({ network: msg, networkClock: clockOnMessage(msg.sim_time, msg.speed, msg.paused, msg.frozen, deps.now()) });
          }
        },
      });
      networkClient.start();
    },

    disconnectNetwork: () => {
      networkClient?.stop();
      networkClient = null;
      set({ networkConnection: 'closed', network: null });
    },

    select: (selectedId) => { set({ selectedId }); },
    setProblem: (problem) => { set({ problem }); },
    setFreeze: (freeze) => { set({ freeze }); },
    simNowMs: () => simNow(get().clock, deps.now()),
    networkNowMs: () => simNow(get().networkClock, deps.now()),
  }));
}

const realDeps: StoreDeps = {
  createClient: (opts) => new WsClient(opts),
  api: new Api(),
  now: () => performance.now(),
  wsUrl: defaultWsUrl,
};

export const useTwin: TwinStore = createTwinStore(realDeps);
