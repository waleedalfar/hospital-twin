import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Highlighter, pulseScale } from '../src/engine/highlight';
import type { RenderedEntity } from '../src/engine/entities';
import { Api, type AskResponse } from '../src/state/api';
import { createRecognizer, createSpeaker, speechError, type Recognizer, type RecognizerHandlers, type Speaker, type SpeechHost } from '../src/state/speech';
import { useTwin } from '../src/state/store';
import { AskPanel, browserDeps, type AskDeps } from '../src/ui/hospital/AskPanel';

class FakeRecognizer implements Recognizer {
  handlers: RecognizerHandlers | null = null;
  started = 0;
  stopped = 0;
  start(h: RecognizerHandlers): void {
    this.handlers = h;
    this.started++;
  }
  stop(): void {
    this.stopped++;
    this.handlers?.onEnd();
  }
}

class FakeSpeaker implements Speaker {
  said: string[] = [];
  cancelled = 0;
  speak(text: string): void {
    this.said.push(text);
  }
  cancel(): void {
    this.cancelled++;
  }
}

const answer: AskResponse = {
  answer_text: 'At Mercy General in the ICU, the patient most likely to deteriorate is P-0042 in ICU-3 (risk 0.81, high).',
  entity_ids: ['P-0042'],
  cited_metrics: [{ name: 'patient.P-0042.score', value: 0.81 }],
  source: 'gemini',
  label: null,
  tools: [{ name: 'list_high_risk_patients', args: { hospital: 'mercy', unit: 'ICU' } }],
};

function stubAsk(response: AskResponse | Response = answer): ReturnType<typeof vi.fn> {
  const f = vi.fn().mockImplementation(() => Promise.resolve(response instanceof Response ? response.clone() : new Response(JSON.stringify(response))));
  vi.stubGlobal('fetch', f);
  return f;
}

beforeEach(() => {
  useTwin.setState({ highlightIds: [], problem: null, selectedId: null });
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('speech adapters', () => {
  it('reports no recognizer where the browser has none, and speaks nothing', () => {
    expect(createRecognizer({})).toBeNull();
    const speaker = createSpeaker({});
    expect(() => { speaker.speak('hi'); speaker.cancel(); }).not.toThrow();
  });
  it('wraps SpeechRecognition: interim and final transcripts, end and errors', () => {
    const made: FakeNative[] = [];
    class FakeNative {
      lang = '';
      interimResults = false;
      continuous = true;
      onresult: ((e: { results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null = null;
      onerror: ((e: { error: string }) => void) | null = null;
      onend: (() => void) | null = null;
      started = false;
      stopped = false;
      constructor() { made.push(this); }
      start() { this.started = true; }
      stop() { this.stopped = true; this.onend?.(); }
    }
    const recognizer = createRecognizer({ webkitSpeechRecognition: FakeNative as never });
    expect(recognizer).not.toBeNull();
    const seen: [string, boolean][] = [];
    const errors: string[] = [];
    let ended = 0;
    recognizer?.start({ onTranscript: (t, f) => seen.push([t, f]), onEnd: () => { ended++; }, onError: (m) => errors.push(m) });
    const native = made[0];
    expect(native).toMatchObject({ lang: 'en-US', interimResults: true, continuous: false, started: true });
    native?.onresult?.({ results: [{ isFinal: false, 0: { transcript: ' who is ' } }] });
    native?.onresult?.({ results: [{ isFinal: true, 0: { transcript: 'who is ' } }, { isFinal: true, 0: { transcript: 'at risk' } }] });
    expect(seen).toEqual([['who is', false], ['who is at risk', true]]);
    native?.onerror?.({ error: 'not-allowed' });
    expect(errors[0]).toContain('microphone is blocked');
    recognizer?.stop();
    expect(native?.stopped).toBe(true);
    expect(ended).toBe(1);
    recognizer?.stop(); // nothing active any more
  });
  it('has a readable message for each failure', () => {
    expect(speechError('no-speech')).toContain('No speech heard');
    expect(speechError('audio-capture')).toContain('No microphone');
    expect(speechError('network')).toContain('network');
    expect(speechError('weird')).toContain('(weird)');
  });
  it('speaks answers by replacing whatever is being said', () => {
    const calls: string[] = [];
    const host: SpeechHost = {
      speechSynthesis: { speak: (u) => calls.push(`speak:${(u as { text: string }).text}`), cancel: () => calls.push('cancel') },
      SpeechSynthesisUtterance: class { constructor(readonly text: string) {} },
    };
    const speaker = createSpeaker(host);
    speaker.speak('hello');
    speaker.cancel();
    expect(calls).toEqual(['cancel', 'speak:hello', 'cancel']);
  });
});

describe('highlighter', () => {
  const at = (id: string, x: number, floor: number | null = 1): RenderedEntity => ({ id, kind: 'patient', floor, room: null, bed: null, position: { x, y: 3, z: 2 }, pose: 'lying', mode: 'bed' });
  it('pulses between 1 and 1.35 times the size', () => {
    const values = Array.from({ length: 40 }, (_, i) => pulseScale(i / 40));
    expect(Math.min(...values)).toBeGreaterThanOrEqual(1);
    expect(Math.max(...values)).toBeLessThanOrEqual(1.35 + 1e-9);
    expect(Math.max(...values) - Math.min(...values)).toBeGreaterThan(0.3);
  });
  it('rings and marks the highlighted entities that are drawn, and clears them', () => {
    const scene = new THREE.Group();
    const h = new Highlighter(scene);
    h.set(['P-1', 'P-2', 'P-1', 'P-404']);
    expect(h.highlighted).toEqual(['P-1', 'P-2', 'P-404']);
    h.update([at('P-1', 5), at('P-2', 9, 2)], 0.2, (level) => level === 1);
    expect(h.drawn).toBe(1); // P-2 is on a hidden floor, P-404 is not drawn at all
    const ring = h.group.getObjectByName('highlight-P-1');
    expect(ring?.position.x).toBe(5);
    expect(ring?.children).toHaveLength(2); // the ring on the floor and the marker above
    h.update([at('P-1', 6)], 0.4);
    expect(h.group.getObjectByName('highlight-P-1')?.position.x).toBe(6);
    h.set(['P-1']);
    expect(h.group.getObjectByName('highlight-P-2')).toBeUndefined();
    h.set([]);
    expect(h.drawn).toBe(0);
    expect(h.group.children).toHaveLength(0);
  });
});

describe('ask panel', () => {
  function setup(): { recognizer: FakeRecognizer; speaker: FakeSpeaker; deps: AskDeps } {
    const recognizer = new FakeRecognizer();
    const speaker = new FakeSpeaker();
    return { recognizer, speaker, deps: { recognizer, speaker } };
  }
  it('asks a typed question, shows and speaks the answer, and highlights the patient', async () => {
    const f = stubAsk();
    const { speaker, deps } = setup();
    render(<AskPanel hospitalId="mercy" deps={deps} />);
    fireEvent.change(screen.getByTestId('ask-input'), { target: { value: 'who is most likely to crash in the ICU' } });
    fireEvent.click(screen.getByTestId('ask-send'));
    await waitFor(() => { expect(screen.getByTestId('ask-answer-text').textContent).toContain('P-0042 in ICU-3'); });
    expect(JSON.parse((f.mock.calls[0]?.[1] as { body: string }).body)).toEqual({ question: 'who is most likely to crash in the ICU', hospital_id: 'mercy' });
    expect(useTwin.getState().highlightIds).toEqual(['P-0042']);
    expect(speaker.said).toEqual([answer.answer_text]);
    expect(screen.queryByTestId('ask-label')).toBeNull();
    expect(screen.getByText('patient.P-0042.score = 0.81')).toBeTruthy();
  });
  it('flies to a patient, and closing clears the highlight and the speech', async () => {
    stubAsk();
    const { speaker, deps } = setup();
    const fly = vi.fn();
    render(<AskPanel hospitalId="mercy" deps={deps} onFly={fly} />);
    fireEvent.change(screen.getByTestId('ask-input'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('ask-send'));
    await waitFor(() => { expect(screen.getByTestId('ask-answer')).toBeTruthy(); });
    fireEvent.click(screen.getByRole('button', { name: 'Fly to' }));
    expect(useTwin.getState().selectedId).toBe('P-0042');
    expect(fly).toHaveBeenCalledWith('P-0042');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByTestId('ask-answer')).toBeNull();
    expect(useTwin.getState().highlightIds).toEqual([]);
    expect(speaker.cancelled).toBeGreaterThan(0);
  });
  it('labels fallback answers and stays quiet when speaking is turned off', async () => {
    stubAsk({ ...answer, source: 'fallback', label: 'Fallback intent parser — Gemini unavailable' });
    const { speaker, deps } = setup();
    render(<AskPanel hospitalId="mercy" deps={deps} />);
    fireEvent.change(screen.getByTestId('ask-input'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('ask-send'));
    await waitFor(() => { expect(screen.getByTestId('ask-label').textContent).toBe('Fallback intent parser — Gemini unavailable'); });
    fireEvent.click(screen.getByLabelText(/Speak answers/));
    fireEvent.change(screen.getByTestId('ask-input'), { target: { value: 'y' } });
    fireEvent.submit(screen.getByTestId('ask-input').closest('form') as HTMLFormElement);
    await waitFor(() => { expect(speaker.said).toHaveLength(1); });
  });
  it('does not send an empty question', () => {
    const f = stubAsk();
    render(<AskPanel hospitalId="mercy" deps={setup().deps} />);
    expect(screen.getByTestId<HTMLButtonElement>('ask-send').disabled).toBe(true);
    fireEvent.submit(screen.getByTestId('ask-input').closest('form') as HTMLFormElement);
    expect(f).not.toHaveBeenCalled();
  });
  it('shows errors from the server', async () => {
    stubAsk(new Response(JSON.stringify({ detail: 'Questions are limited to 400 characters' }), { status: 422 }));
    render(<AskPanel hospitalId="mercy" deps={setup().deps} />);
    fireEvent.change(screen.getByTestId('ask-input'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('ask-send'));
    await waitFor(() => { expect(screen.getByTestId('ask-error').textContent).toBe('Questions are limited to 400 characters'); });
  });
  it('push to talk: holds the button, shows the live transcript, and asks when released', async () => {
    const f = stubAsk();
    const { recognizer, speaker, deps } = setup();
    render(<AskPanel hospitalId="mercy" deps={deps} />);
    fireEvent.pointerDown(screen.getByTestId('ask-mic'));
    expect(recognizer.started).toBe(1);
    expect(speaker.cancelled).toBe(1); // stops speaking when you start talking
    expect(screen.getByTestId('ask-mic').textContent).toBe('Listening…');
    act(() => { recognizer.handlers?.onTranscript('who is most', false); });
    expect(screen.getByTestId('ask-transcript').textContent).toBe('who is most');
    act(() => { recognizer.handlers?.onTranscript('who is most likely to crash', true); });
    fireEvent.pointerDown(screen.getByTestId('ask-mic')); // already listening: ignored
    expect(recognizer.started).toBe(1);
    fireEvent.pointerUp(screen.getByTestId('ask-mic'));
    await waitFor(() => { expect(screen.getByTestId('ask-answer')).toBeTruthy(); });
    expect((JSON.parse((f.mock.calls[0]?.[1] as { body: string }).body) as { question: string }).question).toBe('who is most likely to crash');
    expect(screen.getByTestId<HTMLInputElement>('ask-input').value).toBe('who is most likely to crash');
  });
  it('releasing without having said anything does not ask', () => {
    const f = stubAsk();
    const { recognizer, deps } = setup();
    render(<AskPanel hospitalId="mercy" deps={deps} />);
    fireEvent.pointerDown(screen.getByTestId('ask-mic'));
    fireEvent.pointerLeave(screen.getByTestId('ask-mic'));
    expect(recognizer.stopped).toBe(1);
    expect(f).not.toHaveBeenCalled();
    fireEvent.pointerLeave(screen.getByTestId('ask-mic')); // not listening any more: nothing to stop
    expect(recognizer.stopped).toBe(1);
  });
  it('holding Space on the canvas talks; Space elsewhere does not', async () => {
    stubAsk();
    const { recognizer, deps } = setup();
    render(<><canvas data-testid="scene" /><input data-testid="other" /><AskPanel hospitalId="mercy" deps={deps} /></>);
    fireEvent.keyDown(screen.getByTestId('other'), { code: 'Space' });
    expect(recognizer.started).toBe(0);
    fireEvent.keyDown(screen.getByTestId('scene'), { code: 'Space' });
    expect(recognizer.started).toBe(1);
    fireEvent.keyDown(screen.getByTestId('scene'), { code: 'Space', repeat: true });
    expect(recognizer.started).toBe(1);
    act(() => { recognizer.handlers?.onTranscript('how full is the ICU', true); });
    fireEvent.keyUp(window, { code: 'KeyA' });
    expect(recognizer.stopped).toBe(0);
    fireEvent.keyUp(window, { code: 'Space' });
    expect(recognizer.stopped).toBe(1);
    await waitFor(() => { expect(screen.getByTestId('ask-answer')).toBeTruthy(); });
  });
  it('shows microphone errors and keeps typing available', () => {
    stubAsk();
    const { recognizer, deps } = setup();
    render(<AskPanel hospitalId="mercy" deps={deps} />);
    fireEvent.pointerDown(screen.getByTestId('ask-mic'));
    act(() => { recognizer.handlers?.onError(speechError('not-allowed')); });
    expect(screen.getByTestId('ask-error').textContent).toContain('microphone is blocked');
    expect(screen.getByTestId('ask-mic').textContent).toBe('Hold to talk');
    expect(screen.getByTestId('ask-input')).toBeTruthy();
  });
  it('without speech support it says so and only offers the text box', () => {
    render(<AskPanel hospitalId="mercy" deps={{ recognizer: null, speaker: new FakeSpeaker() }} />);
    expect(screen.getByTestId('ask-no-speech')).toBeTruthy();
    expect(screen.queryByTestId('ask-mic')).toBeNull();
    fireEvent.keyDown(window, { code: 'Space' });
  });
  it('builds browser adapters from the window (jsdom has no speech)', () => {
    const deps = browserDeps({});
    expect(deps.recognizer).toBeNull();
    deps.speaker.speak('x');
    const api = new Api(vi.fn().mockResolvedValue(new Response(JSON.stringify(answer))));
    return expect(api.ask('q', 'mercy')).resolves.toMatchObject({ source: 'gemini' });
  });
});
