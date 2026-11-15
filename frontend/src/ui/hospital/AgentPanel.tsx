import { useState } from 'react';

import type { AgentRecModel } from '../../state/types';
import { api } from '../common';
import { useTwin } from '../../state/store';

export const ACTION_TITLES: Record<string, string> = {
  divert_ambulances: 'Divert ambulances',
  expedite_discharge: 'Expedite discharge',
  move_patient: 'Move patient',
  call_in_staff: 'Call in staff',
  hold_bed: 'Hold bed',
};

/** One line saying what approving the recommendation will do, from its own fields. */
export function describeRec(rec: AgentRecModel): string {
  const n = (k: string): string => String(rec.params[k] ?? '');
  const to = rec.targets.join(', ');
  switch (rec.action) {
    case 'divert_ambulances':
      return `Send ambulances to ${to} for ${n('duration_min')} min`;
    case 'expedite_discharge':
      return `Discharge ${to} now`;
    case 'move_patient':
      return `Move ${to} to ${n('bed_id')}`;
    case 'call_in_staff':
      return `Call ${n('count')} nurse${n('count') === '1' ? '' : 's'} to ${to}`;
    case 'hold_bed':
      return `Hold ${to} for ${n('minutes')} min`;
    default:
      return rec.action;
  }
}

function RecCard({ rec }: { rec: AgentRecModel }) {
  const [busy, setBusy] = useState(false);
  const setProblem = useTwin((s) => s.setProblem);
  const decide = (kind: 'approve' | 'dismiss') => {
    setBusy(true);
    const call = kind === 'approve' ? api.approve(rec.id) : api.dismiss(rec.id);
    call
      .catch((e: unknown) => {
        console.error(`Could not ${kind} ${rec.id}`, e);
        setProblem(`Could not ${kind} ${rec.id}: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => { setBusy(false); });
  };
  return (
    <li className={`rec rec--${rec.status}`} data-testid={`rec-${rec.id}`}>
      <div className="rec__head">
        <b>{ACTION_TITLES[rec.action] ?? rec.action}</b>
        <span className="muted">{rec.id}</span>
      </div>
      <div className="rec__what">{describeRec(rec)}</div>
      <p className="rec__why">{rec.rationale}</p>
      <ul className="rec__metrics" aria-label="Cited metrics">
        {rec.cited_metrics.map((m) => (
          <li key={m.name} className="chip chip--small">{m.name} = {m.value}</li>
        ))}
      </ul>
      {rec.label && <div className="rec__label" data-testid="rec-label">{rec.label}</div>}
      {rec.status === 'pending' ? (
        <div className="rec__buttons">
          <button type="button" className="btn btn--on" disabled={busy} onClick={() => { decide('approve'); }}>Approve</button>
          <button type="button" className="btn" disabled={busy} onClick={() => { decide('dismiss'); }}>Dismiss</button>
        </div>
      ) : (
        <div className="muted" data-testid="rec-status">{rec.status}</div>
      )}
    </li>
  );
}

/** The operations agent's recommendations for this hospital (PROMPT.md §9). Approving applies them to the sim. */
export function AgentPanel() {
  const recs = useTwin((s) => s.recs);
  const [open, setOpen] = useState(true);
  const pending = recs.filter((r) => r.status === 'pending');
  const handled = recs.filter((r) => r.status !== 'pending').slice(0, 3);
  return (
    <section className="agent" aria-label="Operations agent" data-testid="agent-panel">
      <button type="button" className="feed__title agent__title" aria-expanded={open} onClick={() => { setOpen(!open); }}>
        AGENT · {pending.length} PENDING {open ? '▾' : '▸'}
      </button>
      {open && (
        <>
          {recs.length === 0 && <div className="muted">No recommendations right now.</div>}
          <ul className="rec__list">
            {[...pending, ...handled].map((r) => (
              <RecCard key={`${r.id}-${r.status}`} rec={r} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
