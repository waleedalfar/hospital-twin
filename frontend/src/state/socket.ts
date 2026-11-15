/**
 * WebSocket client with reconnect and backoff (PROMPT.md §10.6). Each connection starts with a fresh
 * snapshot from the server, so after any reconnect the client resyncs from scratch. Status is reported to the
 * UI ("Disconnected" banner while offline).
 */
import type { ServerMessage } from './wsTypes';

export type ConnectionStatus = 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface SocketLike {
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
  close(): void;
}

export interface WsOptions {
  url: () => string;
  onMessage: (msg: ServerMessage) => void;
  onStatus: (status: ConnectionStatus) => void;
  /** Called with a problem the user should see (bad message, server error message). */
  onProblem?: (text: string) => void;
  create?: (url: string) => SocketLike;
  setTimer?: (fn: () => void, ms: number) => unknown;
  clearTimer?: (handle: unknown) => void;
}

export const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];

export function backoffDelay(attempt: number): number {
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] as number;
}

export function parseMessage(data: unknown): ServerMessage {
  if (typeof data !== 'string') throw new Error('WebSocket message is not text');
  const msg = JSON.parse(data) as { v?: unknown; type?: unknown };
  if (msg.v !== 1) throw new Error(`Unsupported message version ${String(msg.v)}`);
  if (msg.type !== 'snapshot' && msg.type !== 'events' && msg.type !== 'network' && msg.type !== 'error') {
    throw new Error(`Unknown message type ${String(msg.type)}`);
  }
  return msg as ServerMessage;
}

export class WsClient {
  private socket: SocketLike | null = null;
  private attempt = 0;
  private timer: unknown = null;
  private stopped = true;
  private status: ConnectionStatus = 'closed';

  constructor(private readonly o: WsOptions) {}

  private setStatus(s: ConnectionStatus): void {
    if (s !== this.status) {
      this.status = s;
      this.o.onStatus(s);
    }
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) (this.o.clearTimer ?? clearTimeout)(this.timer as number);
    this.timer = null;
    const s = this.socket;
    this.socket = null;
    if (s) {
      s.onclose = null;
      s.close();
    }
    this.setStatus('closed');
  }

  private connect(): void {
    this.setStatus(this.attempt === 0 ? 'connecting' : 'reconnecting');
    const create = this.o.create ?? ((url: string) => new WebSocket(url) as unknown as SocketLike);
    const socket = create(this.o.url());
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.setStatus('open');
    };
    socket.onmessage = (ev) => {
      try {
        const msg = parseMessage(ev.data);
        if (msg.type === 'error') this.o.onProblem?.(msg.message);
        else this.o.onMessage(msg);
      } catch (error) {
        console.error('Bad WebSocket message', error);
        this.o.onProblem?.(error instanceof Error ? error.message : String(error));
      }
    };
    socket.onerror = () => undefined; // a close event always follows and is handled there
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.stopped) return;
      this.setStatus('reconnecting');
      const delay = backoffDelay(this.attempt++);
      this.timer = (this.o.setTimer ?? setTimeout)(() => {
        this.timer = null;
        if (!this.stopped) this.connect();
      }, delay);
    };
  }
}
