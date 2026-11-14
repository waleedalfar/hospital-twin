/** Client for the backend `GET /health` endpoint (served to the browser as `/api/health`). */

export interface Health {
  status: 'ok' | 'degraded';
  db: 'ok' | 'error';
  timescaledb_version: string | null;
  migrations_applied: number | null;
  error: string | null;
}

export const HEALTH_URL = '/api/health';

/** The backend could not be reached, or it answered with something that is not a health report. */
export class HealthFetchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'HealthFetchError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function nullable<T>(value: unknown, check: (v: unknown) => v is T, field: string): T | null {
  if (value === null || value === undefined) return null;
  if (check(value)) return value;
  throw new HealthFetchError(`Health response field "${field}" has the wrong type`);
}

const isString = (v: unknown): v is string => typeof v === 'string';
const isNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Validate an unknown JSON value as a health report. Throws `HealthFetchError` if it is not one. */
export function parseHealth(value: unknown): Health {
  if (!isRecord(value)) throw new HealthFetchError('Health response is not a JSON object');
  const { status, db } = value;
  if (status !== 'ok' && status !== 'degraded') {
    throw new HealthFetchError('Health response field "status" is invalid');
  }
  if (db !== 'ok' && db !== 'error') {
    throw new HealthFetchError('Health response field "db" is invalid');
  }
  return {
    status,
    db,
    timescaledb_version: nullable(value.timescaledb_version, isString, 'timescaledb_version'),
    migrations_applied: nullable(value.migrations_applied, isNumber, 'migrations_applied'),
    error: nullable(value.error, isString, 'error'),
  };
}

/**
 * Fetch the backend health report. A 503 with a valid body is a normal "degraded" report and is returned;
 * network failures and any other response throw `HealthFetchError`.
 */
export async function fetchHealth(fetchImpl: typeof fetch = fetch): Promise<Health> {
  let response: Response;
  try {
    response = await fetchImpl(HEALTH_URL, { headers: { Accept: 'application/json' } });
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : String(cause);
    throw new HealthFetchError(`Network error: ${reason}`);
  }
  if (!response.ok && response.status !== 503) {
    throw new HealthFetchError(`HTTP ${response.status}`);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new HealthFetchError(`HTTP ${response.status} with a body that is not JSON`);
  }
  return parseHealth(body);
}
