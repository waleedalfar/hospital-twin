import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Api } from '../src/state/api';
import { feedItem } from '../src/state/feed';
import { mergeRecs, recsIn } from '../src/state/reducers';
import { useTwin } from '../src/state/store';
import type { AgentRecModel, EventsMessage } from '../src/state/types';
import { AgentPanel, describeRec } from '../src/ui/hospital/AgentPanel';
import {
  AuditList,
  DriftHeatmap,
  FairnessTable,
  GovernanceButton,
  GovernanceDrawer,
  auditSummary,
  psiTone,
} from '../src/ui/governance/Governance';

function rec(over: Partial<AgentRecModel> = {}): AgentRecModel {
  return {
    id: 'REC-1',
    hospital_id: 'mercy',
    action: 'divert_ambulances',
    targets: ['desert'],
    params: { duration_min: 120 },
    rationale: "Mercy's ER is full.",
    cited_metrics: [{ name: 'ER.occupied', value: 6 }, { name: 'er_wait_min', value: 77.2 }],
    source: 'rules',
    status: 'pending',
    created: '2026-11-14T18:00:00Z',
    label: 'Rules engine — Gemini unavailable',
    ...over,
  };
}

function reply(routes: Record<string, unknown>): typeof fetch {
  return vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const path = (typeof url === "string" ? url : url instanceof URL ? url.href : url.url).replace('/api', '');
    const hit = Object.entries(routes).find(([k]) => (k.startsWith('POST ') ? init?.method === 'POST' && path.startsWith(k.slice(5)) : init?.method !== 'POST' && path.startsWith(k)));
    if (!hit) return Promise.resolve(new Response(JSON.stringify({ detail: `no route ${path}` }), { status: 404 }));
    const body = hit[1];
    if (body instanceof Response) return Promise.resolve(body.clone());
    return Promise.resolve(new Response(JSON.stringify(body)));
  });
}

beforeEach(() => {
  useTwin.setState({ recs: [], problem: null });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('recommendation state', () => {
  it('merges new and updated recommendations, newest first', () => {
    const a = rec({ id: 'REC-2', created: '2026-11-14T18:00:00Z' });
    const b = rec({ id: 'REC-10', created: '2026-11-14T18:15:00Z' });
    const merged = mergeRecs([a], [b, { ...a, status: 'approved' }]);
    expect(merged.map((r) => r.id)).toEqual(['REC-10', 'REC-2']);
    expect(merged[1]?.status).toBe('approved');
    expect(mergeRecs([rec({ id: 'REC-2' }), rec({ id: 'REC-10' })], []).map((r) => r.id)).toEqual(['REC-10', 'REC-2']);
  });
  it('picks the agent_rec events out of a message', () => {
    const msg = {
      v: 1, type: 'events', sim_time: 't', speed: 1, paused: false, frozen: false,
      events: [{ kind: 'agent_rec', time: 't', rec: rec() }, { kind: 'hospital_status', time: 't', status: 'open' }],
    } as unknown as EventsMessage;
    expect(recsIn(msg).map((r) => r.id)).toEqual(['REC-1']);
  });
  it('shows drift alerts and new recommendations in the live feed', () => {
    const drift = feedItem({ kind: 'drift_alert', time: 't', feature: 'spo2', psi: 0.531 }, 1);
    expect(drift).toMatchObject({ who: 'Model drift', what: 'spo2 PSI 0.53' });
    expect(feedItem({ kind: 'agent_rec', time: 't', rec: rec() }, 2)?.what).toBe('recommends divert ambulances');
    expect(feedItem({ kind: 'agent_rec', time: 't', rec: rec({ status: 'approved' }) }, 3)).toBeNull();
  });
});

describe('api client for the agent and governance', () => {
  it('builds the right requests', async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(new Response('[]')));
    const api = new Api(f);
    await api.recs('mercy', 'pending');
    await api.recs(null);
    await api.approve('REC-1');
    await api.dismiss('REC-1');
    await api.drift();
    await api.fairness();
    await api.audit({ actor: 'user', action: 'x', exclude: ['a', 'b'], limit: 5 });
    await api.audit();
    const urls = f.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual([
      '/api/agent/recs?hospital=mercy&status=pending',
      '/api/agent/recs?',
      '/api/agent/recs/REC-1/approve',
      '/api/agent/recs/REC-1/dismiss',
      '/api/governance/drift',
      '/api/governance/fairness',
      '/api/governance/audit?actor=user&action=x&exclude=a%2Cb&limit=5',
      '/api/governance/audit?limit=100',
    ]);
    expect(f.mock.calls[2]?.[1]).toMatchObject({ method: 'POST' });
  });
});

describe('describeRec', () => {
  it('says what approving will do for every action', () => {
    expect(describeRec(rec())).toBe('Send ambulances to desert for 120 min');
    expect(describeRec(rec({ action: 'expedite_discharge', targets: ['P-1', 'P-2'], params: {} }))).toBe('Discharge P-1, P-2 now');
    expect(describeRec(rec({ action: 'move_patient', targets: ['P-1'], params: { bed_id: 'ICU-2' } }))).toBe('Move P-1 to ICU-2');
    expect(describeRec(rec({ action: 'call_in_staff', targets: ['ICU'], params: { count: 1 } }))).toBe('Call 1 nurse to ICU');
    expect(describeRec(rec({ action: 'call_in_staff', targets: ['ICU'], params: { count: 2 } }))).toBe('Call 2 nurses to ICU');
    expect(describeRec(rec({ action: 'hold_bed', targets: ['ICU-6'], params: { minutes: 60 } }))).toBe('Hold ICU-6 for 60 min');
  });
});

describe('agent panel', () => {
  it('lists pending recommendations with their cited metrics and the fallback label', () => {
    useTwin.setState({ recs: [rec(), rec({ id: 'REC-0', status: 'approved', label: null })] });
    render(<AgentPanel />);
    expect(screen.getByText(/1 PENDING/)).toBeTruthy();
    expect(screen.getByTestId('rec-label').textContent).toBe('Rules engine — Gemini unavailable');
    expect(screen.getAllByText('ER.occupied = 6').length).toBe(2);
    expect(screen.getByTestId('rec-status').textContent).toBe('approved');
    fireEvent.click(screen.getByRole('button', { name: /PENDING/ }));
    expect(screen.queryByTestId('rec-REC-1')).toBeNull();
  });
  it('says when there is nothing to recommend', () => {
    render(<AgentPanel />);
    expect(screen.getByText('No recommendations right now.')).toBeTruthy();
  });
  it('approves and dismisses through the API', async () => {
    const f = reply({ 'POST /agent/recs/REC-1/approve': { rec: rec({ status: 'approved' }), result: 'ok' }, 'POST /agent/recs/REC-2/dismiss': rec({ id: 'REC-2', status: 'dismissed' }) });
    vi.stubGlobal('fetch', f);
    useTwin.setState({ recs: [rec(), rec({ id: 'REC-2' })] });
    render(<AgentPanel />);
    fireEvent.click(within('rec-REC-1', 'Approve'));
    fireEvent.click(within('rec-REC-2', 'Dismiss'));
    await waitFor(() => { expect((f as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2); });
  });
  it('shows the error when approving fails', async () => {
    vi.stubGlobal('fetch', reply({ 'POST /agent/recs/REC-1/approve': new Response(JSON.stringify({ detail: 'REC-1 is already approved' }), { status: 409 }) }));
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    useTwin.setState({ recs: [rec()] });
    render(<AgentPanel />);
    fireEvent.click(within('rec-REC-1', 'Approve'));
    await waitFor(() => { expect(useTwin.getState().problem).toBe('Could not approve REC-1: REC-1 is already approved'); });
  });
});

function within(testId: string, name: string): HTMLElement {
  const card = screen.getByTestId(testId);
  const button = Array.from(card.querySelectorAll('button')).find((b) => b.textContent === name);
  if (!button) throw new Error(`no ${name} button`);
  return button;
}

const drift = {
  threshold: 0.2,
  respiratory_features: ['spo2', 'rr'],
  cells: [
    { hospital_id: 'mercy', feature: 'spo2', psi: 0.53, alert: true, time: 't' },
    { hospital_id: 'mercy', feature: 'age', psi: 0.01, alert: false, time: 't' },
    { hospital_id: 'desert', feature: 'spo2', psi: 0.12, alert: false, time: 't' },
  ],
};

describe('governance', () => {
  it('colors PSI by threshold', () => {
    expect(psiTone(0.05, 0.2)).toBe('ok');
    expect(psiTone(0.15, 0.2)).toBe('watch');
    expect(psiTone(0.25, 0.2)).toBe('alert');
  });
  it('draws the drift heatmap with respiratory features first and alerts marked', async () => {
    vi.stubGlobal('fetch', reply({ '/governance/drift': drift }));
    render(<DriftHeatmap />);
    await waitFor(() => { expect(screen.getByTestId('drift-heatmap')).toBeTruthy(); });
    expect(screen.getByTestId('drift-mercy-spo2').getAttribute('data-alert')).toBe('true');
    expect(screen.getByTestId('drift-mercy-spo2').textContent).toBe('0.53');
    expect(screen.getByTestId('drift-desert-age').textContent).toBe('–');
    const rows = Array.from(document.querySelectorAll('tbody th')).map((t) => t.textContent);
    expect(rows).toEqual(['spo2', 'age']);
  });
  it('says when there are no drift readings or the request fails', async () => {
    vi.stubGlobal('fetch', reply({ '/governance/drift': { ...drift, cells: [] } }));
    render(<DriftHeatmap />);
    await waitFor(() => { expect(screen.getByText(/No drift readings yet/)).toBeTruthy(); });
    cleanup();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.stubGlobal('fetch', reply({}));
    render(<DriftHeatmap />);
    await waitFor(() => { expect(screen.getByText(/Drift unavailable/)).toBeTruthy(); });
  });
  it('shows fairness groups and the flag, or why there is no report', async () => {
    const report = {
      available: true, reason: null, as_of: 't', rows: 500, positives: 40, flagged: true, max_auroc_gap: 0.081, threshold: 0.05,
      groups: { 'age 65+': { n: 200, positives: 20, auroc: 0.81, calibration_gap: 0.02 }, male: { n: 10, positives: 0, auroc: null, calibration_gap: null } },
    };
    vi.stubGlobal('fetch', reply({ '/governance/fairness': report }));
    render(<FairnessTable />);
    await waitFor(() => { expect(screen.getByTestId('fairness')).toBeTruthy(); });
    expect(screen.getByTestId('fairness-flag').textContent).toContain('FLAGGED');
    expect(screen.getByText('0.810')).toBeTruthy();
    expect(screen.getAllByText('n/a').length).toBe(2);
    cleanup();
    vi.stubGlobal('fetch', reply({ '/governance/fairness': { available: false, reason: 'No model is scoring yet', groups: null } }));
    render(<FairnessTable />);
    await waitFor(() => { expect(screen.getByText('No model is scoring yet')).toBeTruthy(); });
  });
  it('lists the audit log and filters it', async () => {
    const rows = [
      { time: '2026-11-14T18:00:00Z', actor: 'user', action: 'agent_rec_approved', payload: { id: 'REC-1', result: { ok: 1 } } },
      { time: '2026-11-14T17:00:00Z', actor: 'system', action: 'drift_alert', payload: { feature: 'spo2', psi: 0.5 } },
    ];
    const f = reply({ '/governance/audit': rows });
    vi.stubGlobal('fetch', f);
    render(<AuditList />);
    await waitFor(() => { expect(screen.getAllByTestId('audit-row').length).toBe(2); });
    expect(auditSummary(rows[0]!)).toBe('id: REC-1 · result: {"ok":1}');
    fireEvent.change(screen.getByPlaceholderText('user, agent, system'), { target: { value: 'user' } });
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => {
      const urls = (f as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.includes('actor=user') && !u.includes('exclude'))).toBe(true);
      expect(urls[0]).toContain('exclude=risk_alert%2Cinference_batch');
    });
  });
  it('says when the audit log is empty or unavailable', async () => {
    vi.stubGlobal('fetch', reply({ '/governance/audit': [] }));
    render(<AuditList />);
    await waitFor(() => { expect(screen.getByText('No audit rows match.')).toBeTruthy(); });
    cleanup();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.stubGlobal('fetch', reply({}));
    render(<AuditList />);
    await waitFor(() => { expect(screen.getByText(/Audit log unavailable/)).toBeTruthy(); });
  });
  it('opens as a drawer with tabs, the model card link, and closes', async () => {
    vi.stubGlobal('fetch', reply({ '/governance/drift': drift, '/governance/fairness': { available: false, reason: 'later', groups: null }, '/governance/audit': [] }));
    render(<GovernanceButton />);
    expect(screen.queryByTestId('governance-drawer')).toBeNull();
    fireEvent.click(screen.getByTestId('governance-button'));
    expect(screen.getByTestId('governance-drawer')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Model card' }).getAttribute('href')).toBe('/api/governance/model-card');
    await waitFor(() => { expect(screen.getByTestId('drift-heatmap')).toBeTruthy(); });
    fireEvent.click(screen.getByRole('tab', { name: 'Fairness' }));
    await waitFor(() => { expect(screen.getByText('later')).toBeTruthy(); });
    fireEvent.click(screen.getByRole('tab', { name: 'Audit log' }));
    await waitFor(() => { expect(screen.getByTestId('audit')).toBeTruthy(); });
    fireEvent.click(screen.getByTestId('governance-button'));
    expect(screen.queryByTestId('governance-drawer')).toBeNull();
  });
  it('the drawer has a close button', () => {
    vi.stubGlobal('fetch', reply({}));
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const onClose = vi.fn();
    render(<GovernanceDrawer onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalled();

  });
});
