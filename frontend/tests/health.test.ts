import { describe, expect, it, vi } from 'vitest';

import { fetchHealth, HEALTH_URL, HealthFetchError, parseHealth } from '../src/state/health';

const OK_BODY = {
  status: 'ok',
  db: 'ok',
  timescaledb_version: '2.17.2',
  migrations_applied: 1,
  error: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('parseHealth', () => {
  it('accepts a full ok report', () => {
    expect(parseHealth(OK_BODY)).toEqual(OK_BODY);
  });

  it('fills missing optional fields with null', () => {
    expect(parseHealth({ status: 'degraded', db: 'error', error: 'boom' })).toEqual({
      status: 'degraded',
      db: 'error',
      timescaledb_version: null,
      migrations_applied: null,
      error: 'boom',
    });
  });

  it.each([
    ['null', null],
    ['an array', []],
    ['a string', 'ok'],
    ['a bad status', { ...OK_BODY, status: 'great' }],
    ['a bad db', { ...OK_BODY, db: 'maybe' }],
    ['a numeric version', { ...OK_BODY, timescaledb_version: 2 }],
    ['a string migration count', { ...OK_BODY, migrations_applied: '1' }],
    ['a NaN migration count', { ...OK_BODY, migrations_applied: Number.NaN }],
    ['a non-string error', { ...OK_BODY, error: { message: 'x' } }],
  ])('rejects %s', (_label, value) => {
    expect(() => parseHealth(value)).toThrow(HealthFetchError);
  });
});

describe('fetchHealth', () => {
  it('requests /api/health and returns the parsed report', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(OK_BODY));
    await expect(fetchHealth(fetchImpl)).resolves.toEqual(OK_BODY);
    expect(fetchImpl).toHaveBeenCalledWith(HEALTH_URL, { headers: { Accept: 'application/json' } });
  });

  it('returns a degraded report sent with HTTP 503', async () => {
    const body = { status: 'degraded', db: 'error', error: 'db down' };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(body, 503));
    await expect(fetchHealth(fetchImpl)).resolves.toMatchObject({ status: 'degraded', error: 'db down' });
  });

  it('throws on other HTTP errors', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({}, 500));
    await expect(fetchHealth(fetchImpl)).rejects.toThrow('HTTP 500');
  });

  it('throws when the body is not JSON', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(new Response('<html>', { status: 200 }));
    await expect(fetchHealth(fetchImpl)).rejects.toThrow('not JSON');
  });

  it('wraps network failures', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchHealth(fetchImpl)).rejects.toThrow('Network error: Failed to fetch');
  });

  it('wraps non-Error rejections', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue('offline');
    await expect(fetchHealth(fetchImpl)).rejects.toThrow('Network error: offline');
  });

  it('throws HealthFetchError for a wrong-shaped body', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ hello: 'world' }));
    await expect(fetchHealth(fetchImpl)).rejects.toBeInstanceOf(HealthFetchError);
  });
});
