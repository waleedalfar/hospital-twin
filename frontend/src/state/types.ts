/** Convenience types over the generated WebSocket types (src/state/wsTypes.ts). */
import type {
  BedInfo,
  Entity,
  EventsMessage,
  HospitalRef,
  Kpis,
  NetworkMessage,
  ScenarioInfo,
  SnapshotMessage,
  VehicleAtHospital,
} from './wsTypes';

export type { BedInfo, Entity, EventsMessage, HospitalRef, Kpis, NetworkMessage, ScenarioInfo, SnapshotMessage, VehicleAtHospital };
export type SimEvent = EventsMessage['events'][number];

/** The model's top factors arrive as [name, weight] pairs (the generated type loses the tuple). */
export type TopFactor = [string, number];

export interface FeedItem {
  /** Sim time of the event (ISO). */
  time: string;
  who: string;
  what: string;
  /** Dot color token: low, med, high or info. */
  tone: 'low' | 'med' | 'high' | 'info';
  key: number;
}

/** Everything the 3D view and the HUD need about one hospital, built from a snapshot and its events. */
export interface HospitalData {
  hospital: HospitalRef;
  simTime: string;
  speed: number;
  paused: boolean;
  frozen: boolean;
  entities: Record<string, Entity>;
  beds: Record<string, BedInfo>;
  vehicles: VehicleAtHospital[];
  scenarios: ScenarioInfo[];
  kpis: Kpis;
  feed: FeedItem[];
}

export const FEED_LIMIT = 40;
