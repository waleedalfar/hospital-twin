/** Helpers for engine unit tests. jsdom has no 2D canvas, so tests use a stub that records nothing. */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { CharacterFactory } from '../../src/engine/characters';
import { LabelFactory } from '../../src/engine/labels';
import { Toolkit } from '../../src/engine/materials';
import type { StyleName } from '../../src/engine/palette';
import type { SnapshotMessage } from '../../src/state/wsTypes';

export function stubCanvas(): HTMLCanvasElement {
  const ctx = new Proxy(
    {},
    {
      get: (_t, prop) => (prop === 'measureText' ? () => ({ width: 40 }) : () => undefined),
      set: () => true,
    },
  );
  return { width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement;
}

export function makeKit(style: StyleName = 'iso'): { tk: Toolkit; labels: LabelFactory; chars: CharacterFactory } {
  const tk = new Toolkit(style, stubCanvas);
  const labels = new LabelFactory(tk);
  return { tk, labels, chars: new CharacterFactory(tk, labels) };
}

export function loadSnapshot(): SnapshotMessage {
  // vitest runs with the frontend folder as the working directory.
  return JSON.parse(readFileSync(join(process.cwd(), 'tests/fixtures/snapshot_mercy.json'), 'utf8')) as SnapshotMessage;
}
