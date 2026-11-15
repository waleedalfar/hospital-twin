import { useEffect, useState } from 'react';

import type { AuditEntry, AuditFilter, DriftReport, FairnessReport } from '../../state/api';
import { api } from '../common';
import { FederatedPanel } from './Federated';

export const GOVERNANCE_POLL_MS = 5000;
const NOISE = ['risk_alert', 'inference_batch'];

function useLoaded<T>(load: () => Promise<T>, key: string): { value: T | null; error: string | null } {
  const [state, setState] = useState<{ value: T | null; error: string | null }>({ value: null, error: null });
  useEffect(() => {
    let live = true;
    const run = () => {
      load().then(
        (value) => { if (live) setState({ value, error: null }); },
        (e: unknown) => {
          console.error('Governance request failed', e);
          if (live) setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        },
      );
    };
    run();
    const timer = setInterval(run, GOVERNANCE_POLL_MS);
    return () => { live = false; clearInterval(timer); };
    // `load` changes every render; `key` says when the request really changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

/** Heatmap color class from the PSI: green below 0.1, amber to 0.2, red above (the alert threshold). */
export function psiTone(psi: number, threshold: number): 'ok' | 'watch' | 'alert' {
  if (psi > threshold) return 'alert';
  return psi > threshold / 2 ? 'watch' : 'ok';
}

export function DriftHeatmap() {
  const { value: d, error } = useLoaded<DriftReport>(() => api.drift(), 'drift');
  if (error && !d) return <div className="error">Drift unavailable: {error}</div>;
  if (!d) return <div className="muted">Loading drift…</div>;
  if (d.cells.length === 0) return <div className="muted">No drift readings yet (they start after the first sim hour).</div>;
  const hospitals = [...new Set(d.cells.map((c) => c.hospital_id))].sort();
  const resp = new Set(d.respiratory_features);
  const features = [...new Set(d.cells.map((c) => c.feature))].sort((a, b) => Number(resp.has(b)) - Number(resp.has(a)) || a.localeCompare(b));
  const cell = (h: string, f: string) => d.cells.find((c) => c.hospital_id === h && c.feature === f);
  return (
    <div className="drift" data-testid="drift-heatmap">
      <div className="muted">PSI of each feature against the training data, last 2 sim hours. Alert above {d.threshold}.</div>
      <table className="heat">
        <thead>
          <tr>
            <th />
            {hospitals.map((h) => <th key={h}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {features.map((f) => (
            <tr key={f}>
              <th scope="row" className={resp.has(f) ? 'heat__resp' : undefined}>{f}</th>
              {hospitals.map((h) => {
                const c = cell(h, f);
                return (
                  <td key={h} className={c ? `heat__${psiTone(c.psi, d.threshold)}` : undefined} data-testid={`drift-${h}-${f}`} data-alert={c?.alert ? 'true' : 'false'}>
                    {c ? c.psi.toFixed(2) : '–'}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const HOSPITAL_CHOICES: { id: string; label: string }[] = [
  { id: '', label: 'Whole network' },
  { id: 'mercy', label: 'Mercy General' },
  { id: 'stlukes', label: "St. Luke's" },
  { id: 'desert', label: 'Desert Valley' },
];

export function FairnessTable() {
  const [hospital, setHospital] = useState('');
  const { value: f, error } = useLoaded<FairnessReport>(() => api.fairness(hospital || null), `fairness-${hospital}`);
  const picker = (
    <label className="fair__filter">
      Hospital{' '}
      <select value={hospital} aria-label="Fairness by hospital" onChange={(e) => { setHospital(e.target.value); }}>
        {HOSPITAL_CHOICES.map((h) => <option key={h.id} value={h.id}>{h.label}</option>)}
      </select>
    </label>
  );
  if (error && !f) return <div className="error">Fairness unavailable: {error}</div>;
  if (!f) return <div className="muted">Loading fairness…</div>;
  if (!f.available || !f.groups) return <div>{picker}<div className="muted">{f.reason ?? 'No fairness report yet.'}</div></div>;
  return (
    <div data-testid="fairness">
      {picker}
      <div className={f.flagged ? 'error' : 'muted'} data-testid="fairness-flag">
        Largest AUROC gap {(f.max_auroc_gap ?? 0).toFixed(3)} (flag above {f.threshold}){f.flagged ? ' — FLAGGED' : ''} · {f.rows} rows, {f.positives} events
      </div>
      <table className="heat">
        <thead>
          <tr><th>Group</th><th>n</th><th>AUROC</th><th>Calibration gap</th></tr>
        </thead>
        <tbody>
          {Object.entries(f.groups).map(([name, g]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td>{g.n}</td>
              <td>{g.auroc === null ? 'n/a' : g.auroc.toFixed(3)}</td>
              <td>{g.calibration_gap === null ? 'n/a' : g.calibration_gap.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function auditSummary(e: AuditEntry): string {
  const p = e.payload;
  const bits = Object.entries(p).slice(0, 4).map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`);
  return bits.join(' · ');
}

export function AuditList() {
  const [actor, setActor] = useState('');
  const [action, setAction] = useState('');
  const [quiet, setQuiet] = useState(true);
  const filter: AuditFilter = { limit: 100, ...(actor ? { actor } : {}), ...(action ? { action } : {}), ...(quiet ? { exclude: NOISE } : {}) };
  const key = JSON.stringify(filter);
  const { value: rows, error } = useLoaded<AuditEntry[]>(() => api.audit(filter), key);
  return (
    <div data-testid="audit">
      <div className="audit__filters">
        <label>Actor <input value={actor} onChange={(e) => { setActor(e.target.value); }} placeholder="user, agent, system" /></label>
        <label>Action <input value={action} onChange={(e) => { setAction(e.target.value); }} placeholder="drift_alert" /></label>
        <label><input type="checkbox" checked={quiet} onChange={(e) => { setQuiet(e.target.checked); }} /> Hide routine scoring rows</label>
      </div>
      {error && !rows && <div className="error">Audit log unavailable: {error}</div>}
      {rows?.length === 0 && <div className="muted">No audit rows match.</div>}
      <ul className="audit__list">
        {rows?.map((r, i) => (
          <li key={`${r.time}-${r.action}-${i}`} data-testid="audit-row">
            <span className="muted">{r.time.slice(11, 19)}</span> <b>{r.actor}</b> {r.action} <span className="muted">{auditSummary(r)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Tab = 'drift' | 'fairness' | 'audit' | 'federated';
const TABS: { id: Tab; label: string }[] = [
  { id: 'drift', label: 'Drift' },
  { id: 'fairness', label: 'Fairness' },
  { id: 'audit', label: 'Audit log' },
  { id: 'federated', label: 'Federated training' },
];

/** Governance drawer (PROMPT.md §8): drift heatmap, fairness, audit log, and the model card. */
export function GovernanceDrawer({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>('drift');
  return (
    <aside className="drawer" role="dialog" aria-label="Governance" data-testid="governance-drawer">
      <header className="drawer__head">
        <h2>Governance</h2>
        <a className="btn" href="/api/governance/model-card" target="_blank" rel="noreferrer">Model card</a>
        <button type="button" className="btn" onClick={onClose}>Close</button>
      </header>
      <div className="group" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'btn btn--on' : 'btn'} onClick={() => { setTab(t.id); }}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="drawer__body">
        {tab === 'drift' && <DriftHeatmap />}
        {tab === 'fairness' && <FairnessTable />}
        {tab === 'audit' && <AuditList />}
        {tab === 'federated' && <FederatedPanel />}
      </div>
    </aside>
  );
}

export function GovernanceButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={open ? 'btn btn--on' : 'btn'} aria-pressed={open} data-testid="governance-button" onClick={() => { setOpen(!open); }}>
        Governance
      </button>
      {open && <GovernanceDrawer onClose={() => { setOpen(false); }} />}
    </>
  );
}
