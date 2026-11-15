/** Turns simulation events into the short lines of the live feed. Quiet events (moves, vitals) are skipped. */
import type { FeedItem, SimEvent } from './types';

type Tone = FeedItem['tone'];

const MODE: Record<string, string> = { walk_in: 'walk-in', ambulance: 'ambulance', air: 'helicopter' };

export function feedItem(event: SimEvent, key: number): FeedItem | null {
  const make = (who: string, what: string, tone: Tone): FeedItem => ({ time: event.time, who, what, tone, key });
  switch (event.kind) {
    case 'arrival':
      return make(event.patient_id, `arrives by ${MODE[event.mode] ?? event.mode}, ESI ${event.esi}`, event.esi <= 2 ? 'high' : 'info');
    case 'er_admit':
      return make(event.patient_id, `to ${event.bed_id} after ${Math.round(event.wait_min)} min`, 'info');
    case 'admit':
      return make(event.patient_id, `admitted to ${event.unit} (${event.bed_id})`, 'info');
    case 'surgery':
      return make(event.patient_id, event.phase === 'start' ? 'surgery started' : 'surgery done', 'med');
    case 'discharge':
      return make(event.patient_id, event.expedited ? 'discharged early' : 'discharged', 'low');
    case 'transfer':
      return make(event.patient_id, `transferred to ${event.to_hospital}`, 'med');
    case 'critical':
      return make(event.patient_id, event.response === 'icu_transfer' ? 'critical, moved to ICU' : 'critical, rapid response', 'high');
    case 'alert':
      return make(event.patient_id, `risk alert (${event.level})`, 'high');
    case 'staff':
      return make(event.entity_id, event.change === 'on_duty' ? 'on duty' : 'off duty', 'info');
    case 'ambulance':
      return event.status === 'unloading' ? make(event.vehicle_id, `unloading ${event.patient_id ?? ''}`.trim(), 'med') : null;
    case 'hospital_status':
      return make('Hospital', `status ${event.status.toUpperCase()}`, event.status === 'open' ? 'low' : 'high');
    case 'scenario':
      return make('Scenario', `${event.name.replace('_', ' ')} ${event.status}`, 'med');
    case 'action':
      return make('Action', event.result, 'info');
    default:
      return null;
  }
}
