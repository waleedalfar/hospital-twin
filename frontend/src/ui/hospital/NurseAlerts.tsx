import { useState } from 'react';

import type { NurseAlertModel, TopFactor } from '../../state/types';
import { useTwin } from '../../state/store';
import { api } from '../common';

/** Pop-ups addressed to the nurse responsible for a patient who has just gone high risk (extra X1). */
export function NurseAlerts() {
  const alerts = useTwin((s) => s.nurseAlerts);
  const pending = alerts.filter((a) => a.status === 'pending').slice(0, 3);
  if (pending.length === 0) return null;
  return (
    <section className="toasts" aria-label="Nurse alerts" data-testid="nurse-alerts">
      {pending.map((a) => <Toast key={a.id} alert={a} />)}
    </section>
  );
}

function Toast({ alert }: { alert: NurseAlertModel }) {
  const [busy, setBusy] = useState(false);
  const setProblem = useTwin((s) => s.setProblem);
  const answer = (kind: 'acknowledge' | 'escalate') => {
    setBusy(true);
    (kind === 'acknowledge' ? api.acknowledgeAlert(alert.id) : api.escalateAlert(alert.id))
      .catch((e: unknown) => {
        console.error(`Could not ${kind} ${alert.id}`, e);
        setProblem(`Could not ${kind} ${alert.id}: ${e instanceof Error ? e.message : String(e)}`);
      })
      .finally(() => { setBusy(false); });
  };
  return (
    <div className="toast" role="alert" data-testid={`nurse-alert-${alert.id}`}>
      <b className="toast__title">{alert.nurse_id}: {alert.patient_id}{alert.bed ? ` in ${alert.bed}` : ''}</b>
      <span className="toast__score">{alert.reason === 'paged' ? `Paged from the inspector · risk ${alert.score.toFixed(2)}` : `High risk ${alert.score.toFixed(2)}`}</span>
      <ul className="toast__why">
        {(alert.top_factors as TopFactor[]).slice(0, 3).map(([name]) => <li key={name}>{name}</li>)}
      </ul>
      <div className="rec__buttons">
        <button type="button" className="btn btn--on" disabled={busy} onClick={() => { answer('acknowledge'); }}>Acknowledge</button>
        <button type="button" className="btn" disabled={busy} onClick={() => { answer('escalate'); }}>Escalate</button>
      </div>
    </div>
  );
}
