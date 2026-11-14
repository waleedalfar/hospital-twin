/** Live text for room labels: "ICU 5/6" style counts from the rendered entities (PROMPT.md §10.2). */
import type { Layout, Room } from './layout';
import type { Palette } from './palette';
import type { Entity } from '../state/wsTypes';

export interface LabelText {
  sub: string;
  /** Palette key of the count color, or '' for none. */
  tone: 'low' | 'med' | 'high' | '';
}

export function toneFor(ratio: number): 'low' | 'med' | 'high' {
  if (ratio >= 0.85) return 'high';
  if (ratio >= 0.6) return 'med';
  return 'low';
}

/**
 * The count shown beside a room's name: occupied beds out of beds for bed rooms, people waiting out of seats
 * for the waiting room and triage, the operating table's state for the OR, nothing for other rooms.
 */
export function labelFor(layout: Layout, room: Room, entities: readonly Entity[]): LabelText {
  const beds = layout.beds.filter((b) => b.room === room.id);
  if (beds.length > 0) {
    const bedIds = new Set(beds.map((b) => b.id));
    const occupied = new Set(entities.filter((e) => e.location.bed && bedIds.has(e.location.bed)).map((e) => e.location.bed)).size;
    return { sub: `${occupied}/${beds.length}`, tone: toneFor(occupied / beds.length) };
  }
  if (room.id === 'WAITING' || room.id === 'TRIAGE') {
    const kind = room.id === 'WAITING' ? 'waiting' : 'triage';
    const seats = layout.seats.filter((s) => s.room === room.id && s.kind === kind).length;
    const here = entities.filter((e) => e.kind === 'patient' && e.location.room === room.id).length;
    return { sub: String(here), tone: toneFor(seats ? here / seats : 0) };
  }
  if (room.id === 'OR') {
    const table = layout.spots.find((s) => s.room === 'OR' && s.kind === 'table');
    const busy = entities.some((e) => table && e.location.spot === table.id);
    return { sub: 'OR-1', tone: busy ? 'med' : 'low' };
  }
  return { sub: '', tone: '' };
}

export function toneColor(tone: LabelText['tone'], p: Palette): string {
  return tone === '' ? '' : p[tone];
}
