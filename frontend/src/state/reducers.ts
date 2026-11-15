/**
 * Applies the server's WebSocket messages to the client's copy of a hospital (PROMPT.md §10.6): the store
 * applies the snapshot, then events. These functions are pure; they never mutate their input.
 */
import { feedItem } from './feed';
import type { AgentRecModel, Entity, EventsMessage, FeedItem, HospitalData, SimEvent, SnapshotMessage } from './types';
import { FEED_LIMIT } from './types';

export function fromSnapshot(msg: SnapshotMessage): HospitalData {
  return {
    hospital: msg.hospital,
    simTime: msg.sim_time,
    speed: msg.speed,
    paused: msg.paused,
    frozen: msg.frozen,
    entities: Object.fromEntries(msg.entities.map((e) => [e.id, e])),
    beds: Object.fromEntries(msg.beds.map((b) => [b.id, b])),
    vehicles: msg.vehicles,
    scenarios: msg.scenarios,
    kpis: msg.kpis,
    feed: [],
  };
}

/** Vehicle statuses in which a vehicle is on the hospital's grounds. */
const ON_GROUNDS = new Set(['at_base', 'unloading']);

function applyEvent(state: HospitalData, event: SimEvent, nextKey: () => number, feed: FeedItem[]): HospitalData {
  const item = feedItem(event, nextKey());
  if (item) feed.push(item);
  switch (event.kind) {
    case 'spawn':
      return { ...state, entities: { ...state.entities, [event.entity.id]: event.entity } };
    case 'despawn': {
      const rest = Object.fromEntries(Object.entries(state.entities).filter(([id]) => id !== event.entity_id));
      return { ...state, entities: rest };
    }
    case 'move': {
      const e = state.entities[event.entity_id];
      if (!e) return state;
      const moved: Entity = {
        ...e,
        location: event.to,
        move: { path: event.path, times: event.times, depart: event.depart, arrive: event.arrive },
        pose: 'walking',
      };
      return { ...state, entities: { ...state.entities, [e.id]: moved } };
    }
    case 'vitals': {
      const e = state.entities[event.patient_id];
      if (!e) return state;
      return { ...state, entities: { ...state.entities, [e.id]: { ...e, vitals: event.vitals } } };
    }
    case 'risk': {
      const e = state.entities[event.patient_id];
      if (!e) return state;
      const risk = { score: event.score, level: event.level, top_factors: event.top_factors, model_version: event.model_version };
      return { ...state, entities: { ...state.entities, [e.id]: { ...e, risk } } };
    }
    case 'bed':
      return { ...state, beds: { ...state.beds, [event.bed_id]: { id: event.bed_id, patient_id: event.patient_id, state: event.state } } };
    case 'ambulance': {
      const others = state.vehicles.filter((v) => v.id !== event.vehicle_id);
      if (!ON_GROUNDS.has(event.status)) return { ...state, vehicles: others };
      return {
        ...state,
        vehicles: [...others, { id: event.vehicle_id, kind: event.vehicle_kind, status: event.status, slot: event.slot ?? null }],
      };
    }
    case 'hospital_status':
      return { ...state, hospital: { ...state.hospital, status: event.status } };
    case 'scenario': {
      const rest = state.scenarios.filter((s) => s.id !== event.scenario_id);
      if (event.status !== 'started') return { ...state, scenarios: rest };
      const minutes = Number(event.params['duration_min'] ?? event.params['window_min'] ?? 0);
      const ends = minutes > 0 ? new Date(Date.parse(event.time) + minutes * 60_000).toISOString() : null;
      return {
        ...state,
        scenarios: [...rest, { id: event.scenario_id, name: event.name, hospital_id: event.hospital_id ?? null, started: event.time, ends }],
      };
    }
    default:
      return state;
  }
}

export function applyEvents(state: HospitalData, msg: EventsMessage, firstKey: number): HospitalData {
  let key = firstKey;
  const feed: FeedItem[] = [];
  let next = state;
  for (const event of msg.events) next = applyEvent(next, event, () => key++, feed);
  return {
    ...next,
    simTime: msg.sim_time,
    speed: msg.speed,
    paused: msg.paused,
    frozen: msg.frozen,
    kpis: msg.kpis,
    feed: feed.length > 0 ? [...feed.reverse(), ...next.feed].slice(0, FEED_LIMIT) : next.feed,
  };
}

/** Newest first; a recommendation that arrives again (new status) replaces the old copy. */
export function mergeRecs(current: AgentRecModel[], incoming: AgentRecModel[]): AgentRecModel[] {
  const byId = new Map(current.map((r) => [r.id, r]));
  for (const r of incoming) byId.set(r.id, r);
  return [...byId.values()].sort((a, b) => b.created.localeCompare(a.created) || b.id.localeCompare(a.id, undefined, { numeric: true }));
}

export function recsIn(msg: EventsMessage): AgentRecModel[] {
  return msg.events.flatMap((e) => (e.kind === 'agent_rec' ? [e.rec] : []));
}
