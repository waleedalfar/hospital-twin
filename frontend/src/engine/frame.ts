/**
 * Frame timing. The first `requestAnimationFrame` timestamp can be earlier than `performance.now()`; a
 * negative clock crashed the prototype's elevator code on frame one and nothing rendered (PROMPT.md §10.5).
 * The delta is therefore clamped to [0, MAX_DT].
 */
export const MAX_DT_S = 0.05;

export function frameDelta(now: number, last: number): number {
  return Math.max(0, Math.min(MAX_DT_S, (now - last) / 1000));
}
