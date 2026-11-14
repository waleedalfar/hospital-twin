import type { Health } from './state/health';
import { BackendStatus } from './ui/BackendStatus';

export const PRODUCT_NAME = 'Hospital Twin';

interface Props {
  loadHealth?: () => Promise<Health>;
}

export function App({ loadHealth }: Props) {
  return (
    <div className="app">
      <header className="app__header">
        <h1 className="app__title">{PRODUCT_NAME}</h1>
        <span className="app__badge">Simulated data</span>
      </header>
      <main className="app__main">
        {loadHealth ? <BackendStatus load={loadHealth} /> : <BackendStatus />}
      </main>
    </div>
  );
}
