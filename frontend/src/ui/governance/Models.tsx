import { useCallback, useEffect, useState } from 'react';

import type { ModelsResponse, RollbackProposal } from '../../state/api';
import { useTwin } from '../../state/store';
import { api } from '../common';

function auroc(metrics: Record<string, unknown>): number | null {
  const v = (metrics['validation'] as { model?: { auroc?: number } } | undefined)?.model?.auroc;
  return typeof v === 'number' ? v : null;
}

/** Governance tab "Models" (extra X3): the versions that can score patients, which one is live, how it is doing on
 *  recent labelled data, and a rollback proposal a person can confirm. */
export function ModelsPanel() {
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [review, setReview] = useState<RollbackProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const setProblem = useTwin((s) => s.setProblem);

  const load = useCallback(() => {
    Promise.all([api.models(), api.rollbackProposal()]).then(
      ([m, r]) => { setModels(m); setReview(r); setError(null); },
      (e: unknown) => {
        console.error('Could not load the models', e);
        setError(e instanceof Error ? e.message : String(e));
      },
    );
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => { clearInterval(timer); };
  }, [load]);

  const switchTo = (version: string, reason?: string) => {
    api.setActiveModel(version, reason).then(load, (e: unknown) => {
      console.error('Could not switch the model', e);
      setProblem(`Could not switch the model: ${e instanceof Error ? e.message : String(e)}`);
    });
  };

  if (error && !models) return <div className="error">Models unavailable: {error}</div>;
  if (!models || !review) return <div className="muted">Loading models…</div>;
  const scorers = models.models.filter((m) => review.available.includes(m.version));
  const proposal = review.proposal;
  return (
    <div data-testid="models-panel">
      {proposal && (
        <div className="error" role="alert" data-testid="rollback-proposal">
          <b>Rollback proposed:</b> {proposal.detail}.{' '}
          <button type="button" className="btn btn--on" data-testid="rollback-confirm" onClick={() => { switchTo(proposal.to_version, proposal.reason); }}>
            Roll back to {proposal.to_version}
          </button>
        </div>
      )}
      <p className="muted" data-testid="live-vs-validation">
        Live model {review.active ?? 'none'}: validation AUROC {review.validation_auroc?.toFixed(3) ?? 'n/a'}, recent labelled data {review.live_auroc?.toFixed(3) ?? 'not enough data yet'}.
        A rollback is proposed if live falls 0.05 below validation, or more than 3 features drift past PSI 0.3. Nothing changes until you confirm.
      </p>
      <table className="heat">
        <thead>
          <tr><th>Version</th><th>Validation AUROC</th><th>Trained</th><th /></tr>
        </thead>
        <tbody>
          {scorers.map((m) => {
            const live = m.version === review.active;
            const a = auroc(m.metrics);
            return (
              <tr key={m.version} data-testid={`model-row-${m.version}`}>
                <th scope="row">{m.version}{live ? ' (live)' : ''}</th>
                <td>{a === null ? 'n/a' : a.toFixed(3)}</td>
                <td>{m.trained_at ? m.trained_at.slice(0, 16).replace('T', ' ') : 'n/a'}</td>
                <td>
                  {live ? <span className="muted">in use</span> : (
                    <button type="button" className="btn" onClick={() => { switchTo(m.version); }}>
                      {proposal?.to_version === m.version ? 'Roll back to this' : 'Make live'}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
