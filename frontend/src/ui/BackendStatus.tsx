import { useEffect, useState } from 'react';

import { fetchHealth, type Health } from '../state/health';

export type BackendState =
  | { phase: 'loading' }
  | { phase: 'ready'; health: Health }
  | { phase: 'unreachable'; message: string };

export const DEFAULT_POLL_MS = 5000;

/** Status word and sentence for a backend state. Status is always given as text, never by color alone. */
export function describeBackend(state: BackendState): { tone: 'pending' | 'ok' | 'error'; text: string } {
  if (state.phase === 'loading') return { tone: 'pending', text: 'Backend: checking' };
  if (state.phase === 'unreachable') {
    return { tone: 'error', text: `Backend unreachable: ${state.message}` };
  }
  const { health } = state;
  if (health.status === 'ok') {
    const version = health.timescaledb_version ?? 'unknown';
    const migrations = health.migrations_applied ?? 0;
    return {
      tone: 'ok',
      text: `Backend OK - TimescaleDB ${version} - ${migrations} migration${migrations === 1 ? '' : 's'} applied`,
    };
  }
  return { tone: 'error', text: `Backend degraded: ${health.error ?? 'database check failed'}` };
}

interface Props {
  load?: () => Promise<Health>;
  pollMs?: number;
}

/** Live backend and database status, read from the API every few seconds. */
export function BackendStatus({ load = fetchHealth, pollMs = DEFAULT_POLL_MS }: Props) {
  const [state, setState] = useState<BackendState>({ phase: 'loading' });

  useEffect(() => {
    let active = true;
    const refresh = () => {
      load().then(
        (health) => {
          if (active) setState({ phase: 'ready', health });
        },
        (error: unknown) => {
          console.error('Health check failed', error);
          if (active) {
            setState({ phase: 'unreachable', message: error instanceof Error ? error.message : String(error) });
          }
        },
      );
    };
    refresh();
    const timer = setInterval(refresh, pollMs);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [load, pollMs]);

  const { tone, text } = describeBackend(state);
  return (
    <p className={`backend-status backend-status--${tone}`} role="status" data-testid="backend-status" data-tone={tone}>
      <span className="backend-status__dot" aria-hidden="true" />
      {text}
    </p>
  );
}
