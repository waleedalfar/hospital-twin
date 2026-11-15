import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './App';
import { installDebug } from './engine/debug';
import './styles.css';

// `window.__TWIN_DEBUG__` is always present (PROMPT.md §10.6); the engine replaces it when a scene starts.
installDebug();
const root = document.getElementById('root');
if (!root) throw new Error('index.html has no #root element');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
