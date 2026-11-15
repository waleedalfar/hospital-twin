import { useEffect } from 'react';

import { useTwin } from './state/store';
import type { Health } from './state/health';
import { BackendStatus } from './ui/BackendStatus';
import { HospitalView } from './ui/hospital/HospitalView';
import { NetworkMap } from './ui/network/NetworkMap';
import { isFreeze, useRoute } from './ui/route';

export const PRODUCT_NAME = 'Hospital Twin';

interface Props {
  loadHealth?: () => Promise<Health>;
}

export function App({ loadHealth }: Props) {
  const route = useRoute();
  const setFreeze = useTwin((s) => s.setFreeze);
  useEffect(() => {
    setFreeze(isFreeze(location.search));
  }, [setFreeze]);
  return (
    <div className="app">
      {route.page === 'hospital' ? <HospitalView hospitalId={route.hospitalId} /> : <NetworkMap />}
      <footer className="app__footer">
        <span className="app__badge" data-testid="simulated-label">Simulated data</span>
        {loadHealth ? <BackendStatus load={loadHealth} /> : <BackendStatus />}
      </footer>
    </div>
  );
}
