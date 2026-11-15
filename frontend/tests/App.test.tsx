import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App, PRODUCT_NAME } from '../src/App';
import type { Health } from '../src/state/health';

const OK: Health = { status: 'ok', db: 'ok', timescaledb_version: '2.17.2', migrations_applied: 1, error: null };

class StubSocket {
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close(): void {
    this.onclose = null;
  }
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  location.hash = '';
});

describe('App', () => {
  it('shows the network screen, the simulated-data label and the live backend status', async () => {
    vi.stubGlobal('WebSocket', StubSocket);
    vi.stubGlobal('requestAnimationFrame', () => 0);
    vi.stubGlobal('cancelAnimationFrame', () => undefined);
    HTMLCanvasElement.prototype.getContext = (() => null) as never;
    render(<App loadHealth={() => Promise.resolve(OK)} />);
    expect(PRODUCT_NAME).toBe('Hospital Twin');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Hospital Twin');
    expect(screen.getByTestId('simulated-label').textContent).toBe('Simulated data');
    expect(document.body.textContent).not.toMatch(/pulse/i);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId('backend-status').textContent).toBe('Backend OK - TimescaleDB 2.17.2 - 1 migration applied');
    expect(screen.getByText('Waiting for the simulation…')).toBeTruthy();
  });
});
