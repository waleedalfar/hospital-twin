import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Health } from '../src/state/health';
import { BackendStatus, describeBackend } from '../src/ui/BackendStatus';

const OK: Health = {
  status: 'ok',
  db: 'ok',
  timescaledb_version: '2.17.2',
  migrations_applied: 3,
  error: null,
};
const DEGRADED: Health = {
  status: 'degraded',
  db: 'error',
  timescaledb_version: null,
  migrations_applied: null,
  error: 'connection refused',
};

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('describeBackend', () => {
  it('describes each state in words', () => {
    expect(describeBackend({ phase: 'loading' })).toEqual({ tone: 'pending', text: 'Backend: checking' });
    expect(describeBackend({ phase: 'ready', health: OK })).toEqual({
      tone: 'ok',
      text: 'Backend OK - TimescaleDB 2.17.2 - 3 migrations applied',
    });
    expect(describeBackend({ phase: 'ready', health: DEGRADED })).toEqual({
      tone: 'error',
      text: 'Backend degraded: connection refused',
    });
    expect(describeBackend({ phase: 'unreachable', message: 'HTTP 500' })).toEqual({
      tone: 'error',
      text: 'Backend unreachable: HTTP 500',
    });
  });

  it('uses the singular for one migration and handles missing fields', () => {
    expect(describeBackend({ phase: 'ready', health: { ...OK, migrations_applied: 1 } }).text).toBe(
      'Backend OK - TimescaleDB 2.17.2 - 1 migration applied',
    );
    expect(
      describeBackend({ phase: 'ready', health: { ...OK, timescaledb_version: null, migrations_applied: null } })
        .text,
    ).toBe('Backend OK - TimescaleDB unknown - 0 migrations applied');
    expect(describeBackend({ phase: 'ready', health: { ...DEGRADED, error: null } }).text).toBe(
      'Backend degraded: database check failed',
    );
  });
});

describe('BackendStatus', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('shows loading, then the report from the API', async () => {
    const load = vi.fn<() => Promise<Health>>().mockResolvedValue(OK);
    render(<BackendStatus load={load} />);
    const status = screen.getByTestId('backend-status');
    expect(status.textContent).toBe('Backend: checking');
    expect(status.dataset.tone).toBe('pending');
    await flush();
    expect(status.textContent).toBe('Backend OK - TimescaleDB 2.17.2 - 3 migrations applied');
    expect(status.dataset.tone).toBe('ok');
    expect(status.getAttribute('role')).toBe('status');
  });

  it('polls and reflects a change of state', async () => {
    const load = vi
      .fn<() => Promise<Health>>()
      .mockResolvedValueOnce(OK)
      .mockResolvedValueOnce(DEGRADED)
      .mockRejectedValueOnce(new Error('Network error: down'))
      .mockRejectedValueOnce('plain failure');
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(<BackendStatus load={load} pollMs={1000} />);
    const status = screen.getByTestId('backend-status');
    await flush();
    expect(status.dataset.tone).toBe('ok');
    await flush(1000);
    expect(status.textContent).toBe('Backend degraded: connection refused');
    await flush(1000);
    expect(status.textContent).toBe('Backend unreachable: Network error: down');
    expect(console.error).toHaveBeenCalledTimes(1);
    await flush(1000);
    expect(status.textContent).toBe('Backend unreachable: plain failure');
    expect(load).toHaveBeenCalledTimes(4);
  });

  it('stops polling and ignores late answers after unmount', async () => {
    let resolveLate: (health: Health) => void = () => undefined;
    const load = vi.fn<() => Promise<Health>>().mockImplementation(
      () =>
        new Promise<Health>((resolve) => {
          resolveLate = resolve;
        }),
    );
    const { unmount } = render(<BackendStatus load={load} pollMs={1000} />);
    expect(load).toHaveBeenCalledTimes(1);
    unmount();
    resolveLate(OK);
    await flush(5000);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('ignores a late failure after unmount', async () => {
    let rejectLate: (reason: Error) => void = () => undefined;
    const load = vi.fn<() => Promise<Health>>().mockImplementation(
      () =>
        new Promise<Health>((_resolve, reject) => {
          rejectLate = reject;
        }),
    );
    const logged = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { unmount } = render(<BackendStatus load={load} />);
    unmount();
    rejectLate(new Error('too late'));
    await flush();
    expect(logged).toHaveBeenCalledTimes(1);
  });
});
