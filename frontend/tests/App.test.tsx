import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App, PRODUCT_NAME } from '../src/App';
import type { Health } from '../src/state/health';

const OK: Health = {
  status: 'ok',
  db: 'ok',
  timescaledb_version: '2.17.2',
  migrations_applied: 1,
  error: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('App', () => {
  it('shows the product name, the simulated-data label and the live backend status', async () => {
    render(<App loadHealth={() => Promise.resolve(OK)} />);
    expect(PRODUCT_NAME).toBe('Hospital Twin');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Hospital Twin');
    expect(screen.getByText('Simulated data')).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/pulse/i);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId('backend-status').textContent).toBe(
      'Backend OK - TimescaleDB 2.17.2 - 1 migration applied',
    );
  });

  it('reads /api/health by default', async () => {
    const fetchStub = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(OK), { status: 200 }));
    vi.stubGlobal('fetch', fetchStub);
    render(<App />);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(fetchStub).toHaveBeenCalledWith('/api/health', expect.anything());
    expect(screen.getByTestId('backend-status').dataset.tone).toBe('ok');
  });
});
