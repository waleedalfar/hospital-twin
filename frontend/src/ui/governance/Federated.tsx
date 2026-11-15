import { useCallback, useEffect, useState } from 'react';

import type { FederatedComparison, FederatedStatus, ModelsResponse } from '../../state/api';
import { useTwin } from '../../state/store';
import { api } from '../common';
import { Sparkline } from '../hospital/Sparkline';

export const LIVE_MODELS: { version: string; label: string }[] = [
  { version: 'lgbm-v1', label: 'LightGBM (central)' },
  { version: 'fed-mlp-v1', label: 'Federated MLP' },
];

const HOSPITAL_NAMES: Record<string, string> = { mercy: 'Mercy General', stlukes: "St. Luke's", desert: 'Desert Valley' };

/** The three-way comparison on one held-out test set: federated, centralized and each hospital alone. */
export function Comparison({ result }: { result: FederatedComparison }) {
  const local = Object.entries(result.local_only).filter((e): e is [string, { test: { auroc: number } }] => typeof e[1] === 'object');
  const rows: [string, number, string][] = [
    ['Federated MLP (FedAvg)', result.federated.test.auroc, 'only weights left each hospital'],
    ['Centralized MLP', result.centralized.test.auroc, 'all rows pooled'],
    ...local.map(([h, m]): [string, number, string] => [`Local only: ${HOSPITAL_NAMES[h] ?? h}`, m.test.auroc, 'that hospital alone']),
    ['Local only: average', result.local_only.mean_auroc, ''],
  ];
  return (
    <table className="heat" data-testid="fed-comparison">
      <thead>
        <tr><th>Model</th><th>Test AUROC</th><th /></tr>
      </thead>
      <tbody>
        {rows.map(([name, auroc, note]) => (
          <tr key={name}>
            <th scope="row">{name}</th>
            <td>{auroc.toFixed(3)}</td>
            <td className="muted">{note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function useStatus(): { status: FederatedStatus | null; error: string | null; reload: () => void } {
  const [status, setStatus] = useState<FederatedStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    api.federated().then(
      (s) => { setStatus(s); setError(null); },
      (e: unknown) => {
        console.error('Could not load the federated status', e);
        setError(e instanceof Error ? e.message : String(e));
      },
    );
  }, []);
  useEffect(reload, [reload]);
  return { status, error, reload };
}

/** Governance drawer tab "Federated training" (PROMPT.md §7.6). */
export function FederatedPanel() {
  const { status, error, reload } = useStatus();
  const live = useTwin((s) => s.federated);
  const setProblem = useTwin((s) => s.setProblem);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.models().then(
      (m: ModelsResponse) => { setActive(m.active_deterioration); },
      (e: unknown) => { setProblem(`Could not read the active model: ${e instanceof Error ? e.message : String(e)}`); },
    );
  }, [setProblem]);
  // A finished run has new results on the server.
  const finished = live?.status === 'done' || live?.status === 'failed';
  useEffect(() => { if (finished) reload(); }, [finished, reload]);

  const state = live ?? status?.state ?? null;
  const running = state?.status === 'running';
  const curve = (state?.status === 'idle' || state === null ? status?.result?.federated.validation_auroc_by_round : state.val_auroc) ?? [];
  const run = () => {
    setBusy(true);
    api.runFederated().catch((e: unknown) => {
      console.error('Could not start federated training', e);
      setProblem(`Could not start federated training: ${e instanceof Error ? e.message : String(e)}`);
    }).finally(() => { setBusy(false); });
  };
  const choose = (version: string) => {
    api.setActiveModel(version).then(
      (r) => { setActive(r.active_deterioration); },
      (e: unknown) => {
        console.error('Could not switch the model', e);
        setProblem(`Could not switch the model: ${e instanceof Error ? e.message : String(e)}`);
      },
    );
  };
  return (
    <div data-testid="federated">
      <p className="muted">Hospitals cannot pool patient records. Each one trains on its own data and only model weights are shared (FedAvg, three Flower clients).</p>
      {error && !status && <div className="error">Federated status unavailable: {error}</div>}
      <div className="fed__run">
        <button type="button" className="btn btn--on" data-testid="fed-run" disabled={running || busy} onClick={run}>
          {running ? 'Running…' : 'Run federated training'}
        </button>
        <span data-testid="fed-progress" role="status">
          {state === null || state.status === 'idle' ? 'Not running' : state.status === 'running' ? `Round ${state.round} of ${state.rounds || '…'}` : state.status === 'done' ? `Done: ${state.rounds} rounds` : `Failed: ${state.error ?? 'unknown error'}`}
        </span>
      </div>
      {state?.status === 'done' && state.error && <div className="error">Quality gate: {state.error}</div>}
      <Sparkline points={curve.map((v, i) => ({ t: i, v }))} label="Validation AUROC by round" min={0.5} max={1} width={420} height={80} />
      {status?.result ? <Comparison result={status.result} /> : <div className="muted">No federated run saved yet. Run it here or with `make fed-train`.</div>}
      {status?.result && (
        <ul className="fed__gates" data-testid="fed-gates">
          <li>Within 0.03 of centralized: {status.result.gates['within_0.03_of_centralized'] ? 'pass' : 'FAIL'}</li>
          <li>Beats the average local-only model: {status.result.gates['beats_local_only_average'] ? 'pass' : 'FAIL'}</li>
        </ul>
      )}
      <fieldset className="fed__switch" data-testid="model-switch">
        <legend>Model scoring patients now</legend>
        {LIVE_MODELS.map((m) => (
          <label key={m.version}>
            <input type="radio" name="live-model" checked={active === m.version} disabled={m.version === 'fed-mlp-v1' && status?.available === false} onChange={() => { choose(m.version); }} /> {m.label} <span className="muted">{m.version}</span>
          </label>
        ))}
      </fieldset>
    </div>
  );
}
