import { useTwin } from '../../state/store';
import type { Entity, TopFactor } from '../../state/types';
import { api } from '../common';
import { Sparkline } from './Sparkline';
import { usePatient } from './usePatient';

const ROLE_LABEL: Record<string, string> = { patient: 'Patient', visitor: 'Visitor', nurse: 'Nurse', doctor: 'Doctor', surgeon: 'Surgeon', emt: 'EMT' };

const LEVEL_COLOR = { low: '#3fb68b', medium: '#f0a830', high: '#e5484d' } as const;

function fmt(n: number | undefined, digits = 0): string {
  return n === undefined ? '--' : n.toFixed(digits);
}

/** Vital signs outside the usual adult range get a flag (text, not only color). */
export function flagged(key: string, v: number): boolean {
  switch (key) {
    case 'hr':
      return v < 50 || v > 110;
    case 'spo2':
      return v < 92;
    case 'sbp':
      return v < 95 || v > 160;
    case 'temp':
      return v < 36 || v >= 38;
    case 'rr':
      return v < 10 || v > 20;
    default:
      return false;
  }
}

function Vital({ k, label, value, unit = '', digits = 0 }: { k: string; label: string; value: number | undefined; unit?: string; digits?: number }) {
  const bad = value !== undefined && flagged(k, value);
  return (
    <div className="vital">
      <span className="vital__k">{label}</span>
      <span className="vital__v" data-flag={bad}>
        {fmt(value, digits)}
        {unit}
        {bad ? ' !' : ''}
      </span>
    </div>
  );
}

export function Inspector({ entity, onFly }: { entity: Entity | undefined; onFly: () => void }) {
  const isPatient = entity?.kind === 'patient';
  const { detail, vitals, risk, error } = usePatient(isPatient ? entity.id : null);
  const setProblem = useTwin((s) => s.setProblem);
  const pageNurse = (patientId: string) => {
    api.pageNurse(patientId).catch((e: unknown) => {
      console.error('Could not page the nurse', e);
      setProblem(`Could not page the nurse: ${e instanceof Error ? e.message : String(e)}`);
    });
  };
  if (!entity) {
    return (
      <aside className="inspector" aria-label="Inspector">
        <div className="inspector__kicker">PATIENT · CLICK ANY BED</div>
        <p className="muted">Select a patient or a staff member in the scene.</p>
      </aside>
    );
  }
  const where = entity.location.bed ?? entity.location.spot ?? entity.location.room ?? '';
  if (!isPatient) {
    return (
      <aside className="inspector" aria-label="Inspector" data-testid="inspector">
        <div className="inspector__kicker">{(ROLE_LABEL[entity.kind] ?? entity.kind).toUpperCase()}</div>
        <div className="inspector__head">
          <span className="inspector__id" data-testid="inspector-id">
            {entity.id}
          </span>
          <span className="muted">{where}</span>
        </div>
        <dl className="facts">
          <dt>Role</dt>
          <dd>{ROLE_LABEL[entity.kind] ?? entity.kind}</dd>
          <dt>Unit</dt>
          <dd>{entity.unit ?? '--'}</dd>
          <dt>Task</dt>
          <dd>{entity.task ?? (entity.move ? 'walking' : 'idle')}</dd>
          <dt>Location</dt>
          <dd>{[entity.location.room, entity.location.spot].filter(Boolean).join(' · ') || '--'}</dd>
        </dl>
      </aside>
    );
  }
  const live = entity.vitals;
  const riskNow = entity.risk ?? (detail?.risk ? { score: detail.risk.score, level: detail.risk.level, top_factors: detail.risk.top_factors, model_version: detail.risk.model_version } : null);
  const factors = (riskNow?.top_factors ?? []) as TopFactor[];
  const hrPoints = vitals.map((p) => ({ t: Date.parse(p.time), v: p.hr }));
  const riskPoints = risk.map((p) => ({ t: Date.parse(p.time), v: p.score }));
  return (
    <aside className="inspector" aria-label="Inspector" data-testid="inspector">
      <div className="inspector__kicker">PATIENT · CLICK ANY BED</div>
      <div className="inspector__head">
        <span className="inspector__id" data-testid="inspector-id">
          {entity.id}
        </span>
        <span className="muted" data-testid="inspector-bed">
          {where} · age {detail?.age ?? '--'}
        </span>
      </div>
      <div className="risk">
        <span className="risk__score">{riskNow ? riskNow.score.toFixed(2) : '--'}</span>
        {riskNow ? (
          <span className="pill" style={{ background: LEVEL_COLOR[riskNow.level], color: riskNow.level === 'medium' ? '#1d2433' : '#ffffff' }}>
            {riskNow.level.toUpperCase()} RISK
          </span>
        ) : (
          <span className="muted">No risk score yet</span>
        )}
        {riskNow && <span className="muted">model {riskNow.model_version}</span>}
      </div>
      <div className="vitals" aria-label="Live vital signs">
        <Vital k="hr" label="HR" value={live?.hr} />
        <Vital k="spo2" label="SpO2" value={live?.spo2} unit="%" />
        <Vital k="bp" label="BP" value={live?.sbp} />
        <Vital k="temp" label="Temp" value={live?.temp} digits={1} />
        <Vital k="rr" label="RR" value={live?.rr} />
        <div className="vital">
          <span className="vital__k">DBP</span>
          <span className="vital__v">{fmt(live?.dbp)}</span>
        </div>
      </div>
      {factors.length > 0 && (
        <>
          <div className="inspector__sub">Why the model flagged this</div>
          {factors.map(([name, weight]) => (
            <div key={name} className="factor">
              <span className="factor__k">{name}</span>
              <span className="factor__bar" style={{ width: Math.round(Math.abs(weight) * 160), background: riskNow ? LEVEL_COLOR[riskNow.level] : '#2453b0' }} />
              <span className="factor__v">{weight.toFixed(2)}</span>
            </div>
          ))}
        </>
      )}
      <Sparkline points={hrPoints} label="Heart rate, 6 h (5-minute averages)" />
      {entity.nurse_id != null && (
        <div className="inspector__nurse" data-testid="inspector-nurse">
          <span className="muted">Nurse {entity.nurse_id}</span>{' '}
          <button type="button" className="btn" data-testid="page-nurse" onClick={() => { pageNurse(entity.id); }}>Page nurse</button>
        </div>
      )}
      {entity.expected_discharge_h != null && (
        <div className="muted" data-testid="expected-discharge">
          Expected discharge in ~{Math.round(entity.expected_discharge_h)} h
        </div>
      )}
      <Sparkline points={riskPoints} label="Risk score, 6 h" color="#e5484d" min={0} max={1} />
      <dl className="facts">
        <dt>FHIR</dt>
        <dd data-testid="inspector-fhir">{detail?.fhir_id ?? '--'}</dd>
        <dt>Encounter</dt>
        <dd>{detail?.encounter ? `${detail.encounter.mode.replace('_', ' ')}, ESI ${detail.encounter.esi}${detail.encounter.disposition ? `, ${detail.encounter.disposition.replace('_', ' ')}` : ''}` : '--'}</dd>
        <dt>Conditions</dt>
        <dd>{detail ? (detail.conditions.slice(0, 4).join(', ') || 'none recorded') + (detail.conditions.length > 4 ? ` +${detail.conditions.length - 4}` : '') : '--'}</dd>
      </dl>
      {error && <p className="error" role="alert">Could not load the record: {error}</p>}
      <button type="button" className="btn" onClick={onFly} disabled={!entity.location.bed}>
        Fly to this bed
      </button>
    </aside>
  );
}
