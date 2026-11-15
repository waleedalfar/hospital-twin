/** Typed REST client for the backend (`/api/*` in the browser; PROMPT.md §6.2). */
import type { TopFactor } from './types';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export interface PatientDetail {
  id: string;
  fhir_id: string;
  age: number;
  sex: string;
  conditions: string[];
  comorbidity_count: number;
  hospital_id: string | null;
  location: { floor: number | null; room: string | null; bed?: string | null; spot?: string | null } | null;
  encounter: { id: number; hospital_id: string; arrived_at: string; mode: string; esi: number; disposition: string | null; ended_at: string | null } | null;
  vitals: { time: string; hr: number; spo2: number; sbp: number; dbp: number; temp: number; rr: number } | null;
  risk: { time: string; score: number; level: 'low' | 'medium' | 'high'; model_version: string; top_factors: TopFactor[] } | null;
}
export interface VitalsPoint {
  time: string;
  hr: number;
  spo2: number;
  sbp: number;
  dbp: number;
  temp: number;
  rr: number;
  samples: number;
}
export interface RiskPoint {
  time: string;
  score: number;
  level: 'low' | 'medium' | 'high';
  model_version: string;
  top_factors: TopFactor[];
}
export interface SimState {
  sim_time: string;
  speed: number;
  paused: boolean;
  frozen: boolean;
  ready: boolean;
}
export interface ForecastReport {
  hospital_id: string;
  as_of: string | null;
  model_version: string | null;
  arrivals: { hours_ahead: number; expected: number }[];
  hours_until_full: Record<string, number | null>;
}
export interface ModelsResponse {
  active_deterioration: string | null;
  active_arrivals: string | null;
  error: string | null;
  models: { version: string; kind: string; metrics: Record<string, unknown> }[];
}
export type ScenarioName = 'flu_surge' | 'mass_casualty' | 'staff_shortage' | 'hospital_offline';

export type Fetch = typeof fetch;

export class Api {
  constructor(
    private readonly fetchImpl: Fetch = (...args) => fetch(...args),
    private readonly base = '/api',
  ) {}

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response;
    try {
      res = await this.fetchImpl(this.base + path, { headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) }, ...init });
    } catch (cause) {
      throw new ApiError(`Network error: ${cause instanceof Error ? cause.message : String(cause)}`, 0);
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === 'string') detail = body.detail;
      } catch {
        // The error body was not JSON; the status line is all there is to show.
      }
      throw new ApiError(detail, res.status);
    }
    return (await res.json()) as T;
  }

  patient(id: string): Promise<PatientDetail> {
    return this.call(`/patients/${encodeURIComponent(id)}`);
  }
  async vitals(id: string, window = '6h'): Promise<VitalsPoint[]> {
    return (await this.call<{ points: VitalsPoint[] }>(`/patients/${encodeURIComponent(id)}/vitals?window=${window}`)).points;
  }
  async risk(id: string, window = '6h'): Promise<RiskPoint[]> {
    return (await this.call<{ points: RiskPoint[] }>(`/patients/${encodeURIComponent(id)}/risk?window=${window}`)).points;
  }
  forecast(hospitalId: string): Promise<ForecastReport> {
    return this.call(`/forecast/${encodeURIComponent(hospitalId)}`);
  }
  models(): Promise<ModelsResponse> {
    return this.call('/models');
  }
  sim(): Promise<SimState> {
    return this.call('/sim');
  }
  setSpeed(speed: number): Promise<SimState> {
    return this.call('/sim/speed', { method: 'POST', body: JSON.stringify({ speed }) });
  }
  setPaused(paused: boolean): Promise<SimState> {
    return this.call('/sim/pause', { method: 'POST', body: JSON.stringify({ paused }) });
  }
  setFrozen(frozen: boolean): Promise<SimState> {
    return this.call('/sim/freeze', { method: 'POST', body: JSON.stringify({ frozen }) });
  }
  startScenario(name: ScenarioName, hospitalId: string | null, location?: { lat: number; lon: number }): Promise<{ id: string }> {
    return this.call('/scenario', { method: 'POST', body: JSON.stringify({ name, hospital_id: hospitalId, ...(location ?? {}) }) });
  }
  stopScenario(id: string): Promise<{ id: string }> {
    return this.call(`/scenario/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }
}
