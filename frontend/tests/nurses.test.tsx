import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { feedItem } from '../src/state/feed';
import { alertsIn, highlightTargets, mergeAlerts } from '../src/state/reducers';
import { useTwin } from '../src/state/store';
import type { Entity, EventsMessage, NurseAlertModel } from '../src/state/types';
import { GovernanceDrawer } from '../src/ui/governance/Governance';
import { NurseResponsePanel, minutes } from '../src/ui/governance/NurseResponse';
import { Inspector } from '../src/ui/hospital/Inspector';
import { NurseAlerts } from '../src/ui/hospital/NurseAlerts';
import { loadSnapshot } from './engine/helpers';

function alert(over: Partial<NurseAlertModel> = {}): NurseAlertModel {
  return {
    id: 'NA-1',
    hospital_id: 'mercy',
    patient_id: 'P-0412',
    nurse_id: 'N-14',
    unit: 'ICU',
    bed: 'ICU-3',
    score: 0.83,
    top_factors: [['SpO2 drop, 2h', 0.3], ['HR trend', 0.2], ['Age', 0.1]],
    status: 'pending',
    reason: 'high_risk',
    created: '2026-11-14T18:00:00Z',
    responded: null,
    seconds_to_ack: null,
    ...over,
  };
}

beforeEach(() => {
  useTwin.setState({ nurseAlerts: [], problem: null });
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('alert state', () => {
  it('merges new and updated alerts, newest first', () => {
    const merged = mergeAlerts([alert({ id: 'NA-2', created: '2026-11-14T18:00:00Z' })], [alert({ id: 'NA-10', created: '2026-11-14T18:30:00Z' }), alert({ id: 'NA-2', status: 'acknowledged' })]);
    expect(merged.map((a) => a.id)).toEqual(['NA-10', 'NA-2']);
    expect(merged[1]?.status).toBe('acknowledged');
  });
  it('picks the alerts out of an events message', () => {
    const msg = { v: 1, type: 'events', sim_time: 't', speed: 1, paused: false, frozen: false, events: [{ kind: 'nurse_alert', time: 't', alert: alert() }, { kind: 'hospital_status', time: 't', status: 'open' }] } as unknown as EventsMessage;
    expect(alertsIn(msg).map((a) => a.id)).toEqual(['NA-1']);
  });
  it('rings the nurses with a pending alert as well as the entities of an answer, once each', () => {
    expect(highlightTargets(['P-1', 'N-14'], [alert(), alert({ id: 'NA-2', nurse_id: 'N-3' }), alert({ id: 'NA-3', nurse_id: 'N-9', status: 'acknowledged' })])).toEqual(['P-1', 'N-14', 'N-3']);
    expect(highlightTargets([], [])).toEqual([]);
  });
  it('puts a new alert in the live feed and ignores answered ones', () => {
    expect(feedItem({ kind: 'nurse_alert', time: 't', alert: alert() }, 1)).toMatchObject({ who: 'N-14', what: 'alerted for P-0412 in ICU-3', tone: 'high' });
    expect(feedItem({ kind: 'nurse_alert', time: 't', alert: alert({ bed: null }) }, 2)?.what).toBe('alerted for P-0412');
    expect(feedItem({ kind: 'nurse_alert', time: 't', alert: alert({ status: 'acknowledged' }) }, 3)).toBeNull();
  });
});

describe('pop-ups', () => {
  it('shows nothing without pending alerts', () => {
    useTwin.setState({ nurseAlerts: [alert({ status: 'acknowledged' })] });
    render(<NurseAlerts />);
    expect(screen.queryByTestId('nurse-alerts')).toBeNull();
  });
  it('addresses the alert to the nurse with the top reasons', () => {
    useTwin.setState({ nurseAlerts: [alert()] });
    render(<NurseAlerts />);
    const toast = screen.getByTestId('nurse-alert-NA-1');
    expect(toast.textContent).toContain('N-14: P-0412 in ICU-3');
    expect(toast.textContent).toContain('High risk 0.83');
    expect(toast.textContent).toContain('SpO2 drop, 2h');
    expect(toast.textContent).toContain('Age');
  });
  it('acknowledges and escalates through the API', async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(alert({ status: 'acknowledged' })))));
    vi.stubGlobal('fetch', f);
    useTwin.setState({ nurseAlerts: [alert(), alert({ id: 'NA-2', patient_id: 'P-1' })] });
    render(<NurseAlerts />);
    fireEvent.click(within('nurse-alert-NA-1', 'Acknowledge'));
    fireEvent.click(within('nurse-alert-NA-2', 'Escalate'));
    await waitFor(() => { expect(f.mock.calls.map((c) => String(c[0]))).toEqual(['/api/nurse-alerts/NA-1/acknowledge', '/api/nurse-alerts/NA-2/escalate']); });
  });
  it('shows a refused answer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: 'NA-1 is already acknowledged' }), { status: 409 }))));
    useTwin.setState({ nurseAlerts: [alert()] });
    render(<NurseAlerts />);
    fireEvent.click(within('nurse-alert-NA-1', 'Acknowledge'));
    await waitFor(() => { expect(useTwin.getState().problem).toBe('Could not acknowledge NA-1: NA-1 is already acknowledged'); });
  });
  it('shows at most three at a time', () => {
    useTwin.setState({ nurseAlerts: [1, 2, 3, 4, 5].map((n) => alert({ id: `NA-${n}` })) });
    render(<NurseAlerts />);
    expect(screen.getAllByRole('alert')).toHaveLength(3);
  });
});

function within(testId: string, name: string): HTMLElement {
  const card = screen.getByTestId(testId);
  const button = Array.from(card.querySelectorAll('button')).find((b) => b.textContent === name);
  if (!button) throw new Error(`no ${name} button`);
  return button;
}

describe('paging from the inspector', () => {
  const patient = loadSnapshot().entities.find((e) => e.kind === 'patient' && e.location.bed) as Entity;
  it('shows the responsible nurse and pages them', async () => {
    const f = vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(url.includes('page-nurse') ? alert({ reason: 'paged' }) : { points: [] }))));
    vi.stubGlobal('fetch', f);
    render(<Inspector entity={{ ...patient, nurse_id: 'N-14' }} onFly={vi.fn()} />);
    expect(screen.getByTestId('inspector-nurse').textContent).toContain('Nurse N-14');
    fireEvent.click(screen.getByTestId('page-nurse'));
    await waitFor(() => { expect(f.mock.calls.some((c) => String(c[0]) === `/api/patients/${patient.id}/page-nurse` && (c[1] as RequestInit).method === 'POST')).toBe(true); });
  });
  it('has no page button without an assigned nurse, and reports a refusal', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(url.includes('page-nurse') ? new Response(JSON.stringify({ detail: 'No nurse is on duty in ICU' }), { status: 409 }) : new Response(JSON.stringify({ points: [] })))));
    render(<Inspector entity={{ ...patient, nurse_id: null }} onFly={vi.fn()} />);
    expect(screen.queryByTestId('page-nurse')).toBeNull();
    cleanup();
    render(<Inspector entity={{ ...patient, nurse_id: 'N-2' }} onFly={vi.fn()} />);
    fireEvent.click(screen.getByTestId('page-nurse'));
    await waitFor(() => { expect(useTwin.getState().problem).toBe('Could not page the nurse: No nurse is on duty in ICU'); });
  });
  it('words a paged alert differently from a high-risk one', () => {
    useTwin.setState({ nurseAlerts: [alert({ reason: 'paged', score: 0.2 })] });
    render(<NurseAlerts />);
    expect(screen.getByTestId('nurse-alert-NA-1').textContent).toContain('Paged from the inspector · risk 0.20');
  });
});

describe('response panel', () => {
  const stats = { raised: 5, pending: 1, acknowledged: 3, escalated: 1, mean_seconds_to_ack: 150, median_seconds_to_ack: 120 };
  it('formats times', () => {
    expect(minutes(null)).toBe('n/a');
    expect(minutes(150)).toBe('2.5 sim min');
  });
  it('shows the counts and the response times', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(stats)))));
    render(<NurseResponsePanel />);
    await waitFor(() => { expect(screen.getByTestId('nurse-response')).toBeTruthy(); });
    expect(screen.getByTestId('nr-raised').textContent).toBe('5');
    expect(screen.getByTestId('nr-mean').textContent).toBe('2.5 sim min');
  });
  it('reports an unreachable API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 503 }))));
    render(<NurseResponsePanel />);
    await waitFor(() => { expect(screen.getByText(/Nurse response unavailable/)).toBeTruthy(); });
  });
  it('is a tab of the governance drawer', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(stats)))));
    render(<GovernanceDrawer onClose={vi.fn()} />);
    act(() => { fireEvent.click(screen.getByRole('tab', { name: 'Nurse response' })); });
    await waitFor(() => { expect(screen.getByTestId('nurse-response')).toBeTruthy(); });
  });
});
