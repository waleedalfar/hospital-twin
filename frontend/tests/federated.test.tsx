import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Api } from '../src/state/api';
import { useTwin } from '../src/state/store';
import type { FederatedMessage } from '../src/state/wsTypes';
import { Comparison, FederatedPanel } from '../src/ui/governance/Federated';
import { GovernanceDrawer } from '../src/ui/governance/Governance';

const result = {
  version: 'fed-mlp-v1',
  rounds: 25,
  federated: { test: { auroc: 0.918 }, validation_auroc_by_round: [0.88, 0.9, 0.91] },
  centralized: { test: { auroc: 0.913 } },
  local_only: { mercy: { test: { auroc: 0.88 } }, stlukes: { test: { auroc: 0.87 } }, desert: { test: { auroc: 0.874 } }, mean_auroc: 0.8746 },
  gates: { 'within_0.03_of_centralized': true, beats_local_only_average: true },
};
function msg(o: Partial<FederatedMessage>): FederatedMessage {
  return { v: 1, type: 'federated', status: 'idle', round: 0, rounds: 0, val_auroc: [], error: null, ...o };
}
const idle = { v: 1, type: 'federated', status: 'idle', round: 0, rounds: 0, val_auroc: [], error: null };

function routes(overrides: Record<string, () => Response> = {}): ReturnType<typeof vi.fn> {
  const table: Record<string, () => Response> = {
    'GET /api/federated': () => new Response(JSON.stringify({ state: idle, result, available: true })),
    'POST /api/federated/run': () => new Response(JSON.stringify({ ...idle, status: 'running' }), { status: 202 }),
    'GET /api/models': () => new Response(JSON.stringify({ active_deterioration: 'lgbm-v1', active_arrivals: null, error: null, models: [] })),
    'POST /api/models/active': () => new Response(JSON.stringify({ active_deterioration: 'fed-mlp-v1', previous: 'lgbm-v1' })),
    ...overrides,
  };
  return vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`;
    const make = table[key];
    return Promise.resolve(make ? make() : new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 }));
  });
}

beforeEach(() => {
  useTwin.setState({ federated: null, problem: null });
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('api client', () => {
  it('calls the federated endpoints', async () => {
    const f = routes();
    const api = new Api(f);
    await api.federated();
    await api.runFederated();
    expect((await api.setActiveModel('fed-mlp-v1')).previous).toBe('lgbm-v1');
    expect(f.mock.calls.map((c) => String(c[0]))).toEqual(['/api/federated', '/api/federated/run', '/api/models/active']);
    expect(JSON.parse((f.mock.calls[2]?.[1] as { body: string }).body)).toEqual({ version: 'fed-mlp-v1' });
  });
});

describe('comparison table', () => {
  it('lists federated, centralized, each hospital alone and their average', () => {
    render(<Comparison result={result as never} />);
    const text = screen.getByTestId('fed-comparison').textContent ?? '';
    expect(text).toContain('Federated MLP (FedAvg)0.918');
    expect(text).toContain('Centralized MLP0.913');
    expect(text).toContain("Local only: St. Luke's0.870");
    expect(text).toContain('Local only: average0.875');
  });
});

describe('federated panel', () => {
  it('shows the saved comparison, the curve and the gates, and the live model', async () => {
    vi.stubGlobal('fetch', routes());
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByTestId('fed-comparison')).toBeTruthy(); });
    expect(screen.getByTestId('fed-progress').textContent).toBe('Not running');
    expect(screen.getByTestId('fed-gates').textContent).toContain('Within 0.03 of centralized: pass');
    expect(screen.getByRole('img', { name: /Validation AUROC by round: latest 0.91/ })).toBeTruthy();
    await waitFor(() => { expect(screen.getByLabelText<HTMLInputElement>(/LightGBM/).checked).toBe(true); });
  });
  it('starts a run and shows round-by-round progress from the websocket', async () => {
    const f = routes();
    vi.stubGlobal('fetch', f);
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByTestId('fed-comparison')).toBeTruthy(); });
    fireEvent.click(screen.getByTestId('fed-run'));
    await waitFor(() => { expect(f).toHaveBeenCalledWith('/api/federated/run', expect.objectContaining({ method: 'POST' })); });
    act(() => { useTwin.setState({ federated: msg({ status: 'running', round: 7, rounds: 25, val_auroc: [0.8, 0.85, 0.87], error: null }) }); });
    expect(screen.getByTestId('fed-progress').textContent).toBe('Round 7 of 25');
    expect(screen.getByTestId<HTMLButtonElement>('fed-run').disabled).toBe(true);
    expect(screen.getByRole('img', { name: /latest 0.87/ })).toBeTruthy();
    act(() => { useTwin.setState({ federated: msg({ status: 'done', round: 25, rounds: 25, val_auroc: [0.9, 0.92], error: null }) }); });
    expect(screen.getByTestId('fed-progress').textContent).toBe('Done: 25 rounds');
    await waitFor(() => { expect((f.mock.calls.filter((c) => c[0] === '/api/federated')).length).toBeGreaterThan(1); });
  });
  it('shows a failed run and a missed quality gate', async () => {
    vi.stubGlobal('fetch', routes());
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByTestId('fed-comparison')).toBeTruthy(); });
    act(() => { useTwin.setState({ federated: msg({ status: 'failed', round: 3, rounds: 25, val_auroc: [], error: 'boom' }) }); });
    expect(screen.getByTestId('fed-progress').textContent).toBe('Failed: boom');
    act(() => { useTwin.setState({ federated: msg({ status: 'done', round: 25, rounds: 25, val_auroc: [0.9], error: 'federated below centralized' }) }); });
    expect(screen.getByText(/Quality gate: federated below centralized/)).toBeTruthy();
  });
  it('reports a run that cannot start', async () => {
    vi.stubGlobal('fetch', routes({ 'POST /api/federated/run': () => new Response(JSON.stringify({ detail: 'No training rows yet. Run `make train` first.' }), { status: 409 }) }));
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByTestId('fed-comparison')).toBeTruthy(); });
    fireEvent.click(screen.getByTestId('fed-run'));
    await waitFor(() => { expect(useTwin.getState().problem).toBe('Could not start federated training: No training rows yet. Run `make train` first.'); });
  });
  it('switches the live model and reports a refusal', async () => {
    vi.stubGlobal('fetch', routes());
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByLabelText<HTMLInputElement>(/LightGBM/).checked).toBe(true); });
    fireEvent.click(screen.getByLabelText(/Federated MLP/));
    await waitFor(() => { expect(screen.getByLabelText<HTMLInputElement>(/Federated MLP/).checked).toBe(true); });
    cleanup();
    vi.stubGlobal('fetch', routes({ 'POST /api/models/active': () => new Response(JSON.stringify({ detail: 'fed-mlp-v1 has not been trained yet' }), { status: 409 }) }));
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByLabelText<HTMLInputElement>(/LightGBM/).checked).toBe(true); });
    fireEvent.click(screen.getByLabelText(/Federated MLP/));
    await waitFor(() => { expect(useTwin.getState().problem).toContain('has not been trained yet'); });
  });
  it('disables the federated model until it exists, and explains when nothing was run yet', async () => {
    vi.stubGlobal('fetch', routes({ 'GET /api/federated': () => new Response(JSON.stringify({ state: idle, result: null, available: false })) }));
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByText(/No federated run saved yet/)).toBeTruthy(); });
    expect(screen.getByLabelText<HTMLInputElement>(/Federated MLP/).disabled).toBe(true);
  });
  it('shows an error when the status cannot be loaded or the active model cannot be read', async () => {
    vi.stubGlobal('fetch', routes({ 'GET /api/federated': () => new Response(JSON.stringify({ detail: 'The simulation is not running' }), { status: 503 }), 'GET /api/models': () => new Response('{}', { status: 500 }) }));
    render(<FederatedPanel />);
    await waitFor(() => { expect(screen.getByText(/Federated status unavailable: The simulation is not running/)).toBeTruthy(); });
    await waitFor(() => { expect(useTwin.getState().problem).toContain('Could not read the active model'); });
  });
  it('is a tab of the governance drawer', async () => {
    vi.stubGlobal('fetch', routes());
    render(<GovernanceDrawer onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Federated training' }));
    await waitFor(() => { expect(screen.getByTestId('federated')).toBeTruthy(); });
  });
});
