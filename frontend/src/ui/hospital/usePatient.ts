import { useEffect, useState } from 'react';

import type { PatientDetail, RiskPoint, VitalsPoint } from '../../state/api';
import { api } from '../common';

export interface PatientData {
  detail: PatientDetail | null;
  vitals: VitalsPoint[];
  risk: RiskPoint[];
  error: string | null;
}

export const POLL_MS = 4000;

/** Loads a patient's record, 6-hour vitals and risk history, and refreshes them while selected. */
export function usePatient(id: string | null): PatientData {
  const [data, setData] = useState<PatientData>({ detail: null, vitals: [], risk: [], error: null });
  useEffect(() => {
    if (!id) {
      setData({ detail: null, vitals: [], risk: [], error: null });
      return;
    }
    let live = true;
    const load = () => {
      Promise.all([api.patient(id), api.vitals(id, '6h'), api.risk(id, '6h')]).then(
        ([detail, vitals, risk]) => {
          if (live) setData({ detail, vitals, risk, error: null });
        },
        (e: unknown) => {
          console.error('Could not load patient', id, e);
          if (live) setData((d) => ({ ...d, error: e instanceof Error ? e.message : String(e) }));
        },
      );
    };
    setData({ detail: null, vitals: [], risk: [], error: null });
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [id]);
  return data;
}
