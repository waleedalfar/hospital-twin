/**
 * Maps server (sim) time to the browser's clock. The server sends the sim time after every tick; between
 * ticks the browser keeps time itself at the current speed, so walkers move smoothly instead of in
 * one-minute jumps. 1x = 1 tick (one sim minute) per real second (PROMPT.md §5.1).
 */
export const SIM_MS_PER_REAL_MS_AT_1X = 60;

export interface ClockState {
  /** Sim time of the last message, ms since the epoch. */
  simMs: number;
  /** performance.now() when that message arrived. */
  receivedAt: number;
  speed: number;
  running: boolean;
}

export function initialClock(): ClockState {
  return { simMs: 0, receivedAt: 0, speed: 1, running: false };
}

export function onMessage(simTime: string, speed: number, paused: boolean, frozen: boolean, now: number): ClockState {
  const simMs = Date.parse(simTime);
  if (Number.isNaN(simMs)) throw new Error(`Bad sim time ${simTime}`);
  return { simMs, receivedAt: now, speed, running: !paused && !frozen };
}

/** Sim time now. While running it never runs more than one tick ahead of the last message. */
export function simNow(c: ClockState, now: number): number {
  if (!c.running) return c.simMs;
  const elapsed = Math.max(0, now - c.receivedAt);
  return c.simMs + Math.min(elapsed * SIM_MS_PER_REAL_MS_AT_1X * c.speed, 60_000 * 1.2);
}

const TZ = 'America/Phoenix';
const DAY_ONE = Date.UTC(2026, 10, 14, 7, 0, 0); // 2026-11-14 00:00 in Phoenix (UTC-7)

/** "SIM DAY 2 14:32" in Phoenix time. */
export function formatSimClock(simMs: number): { day: number; clock: string } {
  const clock = new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(simMs));
  return { day: Math.floor((simMs - DAY_ONE) / 86_400_000) + 1, clock };
}
