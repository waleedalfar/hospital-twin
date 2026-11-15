import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useTwin } from '../src/state/store';
import { ModelsPanel } from '../src/ui/governance/Models';

const models = {
  active_deterioration: 'lgbm-v1',
  active_arrivals: 'arrivals-lgbm-v1',
  error: null,
  models: [
    { version: 'lgbm-v1', kind: 'deterioration', metrics: { validation: { model: { auroc: 0.941 } } }, trained_at: '2026-11-14T20:00:00+00:00' },
    { version: 'fed-mlp-v1', kind: 'deterioration', metrics: { validation: { model: { auroc: 0.9 } } } },
    { version: 'los-lgbm-v1', kind: 'length_of_stay', metrics: {}, trained_at: 'x' },
  ],
};
const quiet = { proposal: null, live_auroc: 0.93, validation_auroc: 0.941, active: 'lgbm-v1', available: ['lgbm-v1', 'fed-mlp-v1'] };
const proposed = { ...quiet, live_auroc: 0.8, proposal: { reason: 'live_auroc_drop', detail: 'AUROC on recent labelled data is 0.800, more than 0.05 below validation (0.941)', from_version: 'lgbm-v1', to_version: 'fed-mlp-v1', created: 't' } };

function routes(review: object, switchResponse: Response = new Response(JSON.stringify({ active_deterioration: 'fed-mlp-v1', previous: 'lgbm-v1' }))): ReturnType<typeof vi.fn> {
  return vi.fn((url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url}`;
    if (key === 'GET /api/models') return Promise.resolve(new Response(JSON.stringify(models)));
    if (key === 'GET /api/models/proposal') return Promise.resolve(new Response(JSON.stringify(review)));
    if (key === 'POST /api/models/active') return Promise.resolve(switchResponse.clone());
    return Promise.resolve(new Response(JSON.stringify({ detail: `no route ${key}` }), { status: 404 }));
  });
}

beforeEach(() => {
  useTwin.setState({ problem: null });
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('models panel', () => {
  it('lists the versions that can score patients, marks the live one, and says how it is doing', async () => {
    vi.stubGlobal('fetch', routes(quiet));
    render(<ModelsPanel />);
    await waitFor(() => { expect(screen.getByTestId('models-panel')).toBeTruthy(); });
    expect(screen.getByTestId('model-row-lgbm-v1').textContent).toContain('lgbm-v1 (live)0.9412026-11-14 20:00in use');
    expect(screen.getByTestId('model-row-fed-mlp-v1').textContent).toContain('0.900n/a');
    expect(screen.queryByTestId('model-row-los-lgbm-v1')).toBeNull(); // the length-of-stay model does not score risk
    expect(screen.getByTestId('live-vs-validation').textContent).toContain('validation AUROC 0.941, recent labelled data 0.930');
    expect(screen.queryByTestId('rollback-proposal')).toBeNull();
  });
  it('makes another version live on request', async () => {
    const f = routes(quiet);
    vi.stubGlobal('fetch', f);
    render(<ModelsPanel />);
    await waitFor(() => { expect(screen.getByTestId('model-row-fed-mlp-v1')).toBeTruthy(); });
    fireEvent.click(screen.getByRole('button', { name: 'Make live' }));
    await waitFor(() => { expect(f).toHaveBeenCalledWith('/api/models/active', expect.objectContaining({ method: 'POST', body: JSON.stringify({ version: 'fed-mlp-v1' }) })); });
  });
  it('shows a rollback proposal and confirming sends the reason', async () => {
    const f = routes(proposed);
    vi.stubGlobal('fetch', f);
    render(<ModelsPanel />);
    await waitFor(() => { expect(screen.getByTestId('rollback-proposal')).toBeTruthy(); });
    expect(screen.getByTestId('rollback-proposal').textContent).toContain('more than 0.05 below validation');
    expect(screen.getByRole('button', { name: 'Roll back to this' })).toBeTruthy();
    fireEvent.click(screen.getByTestId('rollback-confirm'));
    await waitFor(() => { expect(f).toHaveBeenCalledWith('/api/models/active', expect.objectContaining({ body: JSON.stringify({ version: 'fed-mlp-v1', reason: 'live_auroc_drop' }) })); });
  });
  it('shows a refused switch, and an unreachable API', async () => {
    vi.stubGlobal('fetch', routes(quiet, new Response(JSON.stringify({ detail: 'fed-mlp-v1 has not been trained yet' }), { status: 409 })));
    render(<ModelsPanel />);
    await waitFor(() => { expect(screen.getByTestId('model-row-fed-mlp-v1')).toBeTruthy(); });
    fireEvent.click(screen.getByRole('button', { name: 'Make live' }));
    await waitFor(() => { expect(useTwin.getState().problem).toContain('has not been trained yet'); });
    cleanup();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 503 }))));
    render(<ModelsPanel />);
    await waitFor(() => { expect(screen.getByText(/Models unavailable/)).toBeTruthy(); });
  });
});
