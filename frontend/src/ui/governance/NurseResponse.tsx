import { useEffect, useState } from 'react';

import type { NurseResponseStats } from '../../state/api';
import { api } from '../common';

export function minutes(seconds: number | null): string {
  return seconds === null ? 'n/a' : `${(seconds / 60).toFixed(1)} sim min`;
}

/** Governance tab "Nurse response" (extra X1): how fast nurses answer high-risk alerts. */
export function NurseResponsePanel() {
  const [stats, setStats] = useState<NurseResponseStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const run = () => {
      api.nurseResponse().then(
        (s) => { if (live) { setStats(s); setError(null); } },
        (e: unknown) => {
          console.error('Could not load the nurse response times', e);
          if (live) setError(e instanceof Error ? e.message : String(e));
        },
      );
    };
    run();
    const timer = setInterval(run, 5000);
    return () => { live = false; clearInterval(timer); };
  }, []);
  if (error && !stats) return <div className="error">Nurse response unavailable: {error}</div>;
  if (!stats) return <div className="muted">Loading…</div>;
  return (
    <div data-testid="nurse-response">
      <p className="muted">A high-risk alert goes to the nurse responsible for the patient, who is sent to the bedside. The time until someone acknowledges it is recorded and audited.</p>
      <table className="heat">
        <tbody>
          <tr><th scope="row">Alerts raised</th><td data-testid="nr-raised">{stats.raised}</td></tr>
          <tr><th scope="row">Waiting for an answer</th><td>{stats.pending}</td></tr>
          <tr><th scope="row">Acknowledged</th><td>{stats.acknowledged}</td></tr>
          <tr><th scope="row">Escalated to a doctor</th><td>{stats.escalated}</td></tr>
          <tr><th scope="row">Mean time to answer</th><td data-testid="nr-mean">{minutes(stats.mean_seconds_to_ack)}</td></tr>
          <tr><th scope="row">Median time to answer</th><td>{minutes(stats.median_seconds_to_ack)}</td></tr>
        </tbody>
      </table>
    </div>
  );
}
