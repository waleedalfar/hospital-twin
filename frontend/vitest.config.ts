import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{ts,tsx}'],
    passWithNoTests: false,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        // Render glue: mounts <App /> into #root. It has no logic of its own; the e2e smoke test covers it.
        'src/main.tsx',
        // WebGL renderer, render loop and DOM input wiring. jsdom has no WebGL, so this file is exercised by
        // the Playwright scene tests (e2e/scene.spec.ts) against headless Chrome with SwiftShader. All logic it
        // calls (camera math, walls, motion, entities, X-ray, picking, labels) is unit tested.
        'src/engine/engine.ts',
        // Type declarations only; nothing to execute.
        'src/**/*.d.ts',
        // Generated type declarations from shared/ws_schema.json; contains no executable code.
        'src/state/wsTypes.ts',
      ],
      reporter: ['text', 'json-summary'],
      thresholds: { lines: 80, statements: 80, functions: 80, branches: 80 },
    },
  },
});
