import { useEffect, useState } from 'react';

import type { ForecastReport, ModelsResponse } from '../../state/api';
import { api } from '../common';

export const FORECAST_POLL_MS = 5000;
const UNIT_NAMES: Record<string, string> = { ER: 'ER', WARD: 'Ward', ICU: 'ICU', REC: 'Recovery' };

function useLoaded<T>(load: () => Promise<T>, everyMs: number | null, key: string): { value: T | null; error: string | null } {
  const [state, setState] = useState<{ value: T | null; error: string | null }>({ value: null, error: null });
  useEffect(() => {
    let live = true;
    const run = () => {
      load().then(
        (value) => {
          if (live) setState({ value, error: null });
        },
        (e: unknown) => {
          console.error('Request failed', e);
          if (live) setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        },
      );
    };
    run();
    const timer = everyMs === null ? null : setInterval(run, everyMs);
    return () => {
      live = false;
      if (timer !== null) clearInterval(timer);
    };
    // `load` is recreated on every render; `key` says when the request really changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, everyMs]);
  return state;
}

/** Expected arrivals for the next 6 hours and hours until each unit is full (PROMPT.md §7.3). */
export function ForecastPanel({ hospitalId }: { hospitalId: string }) {
  const { value: f, error } = useLoaded<ForecastReport>(() => api.forecast(hospitalId), FORECAST_POLL_MS, hospitalId);
  const max = Math.max(1, ...(f?.arrivals.map((a) => a.expected) ?? [1]));
  return (
    <section className="forecast" aria-label="Forecast" data-testid="forecast">
      <div className="feed__title">FORECAST · NEXT 6 H</div>
      {error && <div className="error">Forecast unavailable: {error}</div>}
      {f && f.arrivals.length === 0 && <div className="muted">No forecast yet{f.model_version === null ? ' (no model)' : ''}.</div>}
      {f && f.arrivals.length > 0 && (
        <>
          <div className="bars" role="img" aria-label={`Expected arrivals per hour: ${f.arrivals.map((a) => a.expected.toFixed(1)).join(', ')}`}>
            {f.arrivals.map((a) => (
              <span key={a.hours_ahead} className="bars__col">
                <i style={{ height: `${Math.round((a.expected / max) * 36) + 2}px` }} />
                <b>+{a.hours_ahead}h</b>
              </span>
            ))}
          </div>
          <div className="muted" data-testid="forecast-total">
            Arrivals expected: {f.arrivals.reduce((s, a) => s + a.expected, 0).toFixed(1)} in 6 h
          </div>
          <ul className="full">
            {Object.entries(f.hours_until_full).map(([unit, hours]) => (
              <li key={unit} data-testid={`full-${unit}`}>
                <span>{UNIT_NAMES[unit] ?? unit}</span>
                <span>{hours === null ? 'not within 24 h' : hours === 0 ? 'FULL' : `full in ${hours.toFixed(1)} h`}</span>
              </li>
            ))}
          </ul>
          <div className="muted">Model {f.model_version}</div>
        </>
      )}
    </section>
  );
}

function auroc(metrics: Record<string, unknown> | undefined): number | null {
  const v = (metrics?.['validation'] as { model?: { auroc?: number } } | undefined)?.model?.auroc;
  return typeof v === 'number' ? v : null;
}

/** The risk model in use and how well it did on validation, so the version shows wherever scores appear. */
export function ModelBadge() {
  const { value: m, error } = useLoaded<ModelsResponse>(() => api.models(), null, 'models');
  const version = m?.active_deterioration ?? null;
  const entry = m?.models.find((x) => x.version === version);
  const a = auroc(entry?.metrics);
  return (
    <div className="chip" data-testid="model-badge">
      {error ? `Risk model: unavailable (${error})` : version ? `Risk model ${version}${a !== null ? ` · AUROC ${a.toFixed(2)}` : ''}` : (m?.error ?? 'Risk model: loading')}
    </div>
  );
}
