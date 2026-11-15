import { useEffect, useMemo, useRef, useState } from 'react';

import type { AskResponse } from '../../state/api';
import { createRecognizer, createSpeaker, type Recognizer, type Speaker, type SpeechHost } from '../../state/speech';
import { useTwin } from '../../state/store';
import { api } from '../common';

export interface AskDeps {
  recognizer: Recognizer | null;
  speaker: Speaker;
}

export function browserDeps(host: SpeechHost = window): AskDeps {
  return { recognizer: createRecognizer(host), speaker: createSpeaker(host) };
}

interface Props {
  hospitalId: string;
  /** Called to fly the camera to a patient (the engine is not available in unit tests). */
  onFly?: (entityId: string) => void;
  deps?: AskDeps;
}

/** "Ask Hospital Twin" (PROMPT.md §9.1): push-to-talk or typed questions, a spoken and written answer, and the
 *  patients it is about highlighted in the 3D view. */
export function AskPanel({ hospitalId, onFly, deps }: Props) {
  const resolved = useMemo(() => deps ?? browserDeps(), [deps]);
  const [text, setText] = useState('');
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<{ question: string; response: AskResponse } | null>(null);
  const [speak, setSpeak] = useState(true);
  const setHighlight = useTwin((s) => s.setHighlight);
  const textRef = useRef('');
  textRef.current = text;

  const send = (question: string) => {
    const q = question.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    api.ask(q, hospitalId).then(
      (response) => {
        setAnswer({ question: q, response });
        setHighlight(response.entity_ids);
        if (speak) resolved.speaker.speak(response.answer_text);
      },
      (e: unknown) => {
        console.error('The question failed', e);
        setError(e instanceof Error ? e.message : String(e));
      },
    ).finally(() => { setBusy(false); });
  };

  const startListening = () => {
    const r = resolved.recognizer;
    if (!r || listening) return;
    resolved.speaker.cancel();
    setError(null);
    setListening(true);
    r.start({
      onTranscript: (t) => { setText(t); },
      onEnd: () => {
        setListening(false);
        if (textRef.current.trim()) send(textRef.current);
      },
      onError: (message) => { setError(message); setListening(false); },
    });
  };
  const stopListening = () => { resolved.recognizer?.stop(); };

  // Hold Space while the 3D view has focus.
  useEffect(() => {
    const isCanvas = (t: EventTarget | null) => t instanceof HTMLCanvasElement;
    const down = (e: KeyboardEvent) => {
      if (e.code === 'Space' && !e.repeat && isCanvas(e.target) && resolved.recognizer) {
        e.preventDefault();
        startListening();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space' && listening) stopListening();
    };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
    };
    // startListening/stopListening close over state that changes every render; the handlers are re-bound with it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listening, resolved, hospitalId, speak]);

  useEffect(() => () => { setHighlight([]); resolved.speaker.cancel(); }, [resolved, setHighlight]);

  const close = () => { setAnswer(null); setHighlight([]); resolved.speaker.cancel(); };
  return (
    <section className="ask" aria-label="Ask Hospital Twin" data-testid="ask-panel">
      <div className="feed__title">ASK HOSPITAL TWIN</div>
      <form className="ask__form" onSubmit={(e) => { e.preventDefault(); send(text); }}>
        {resolved.recognizer ? (
          <button
            type="button"
            className={listening ? 'btn btn--on' : 'btn'}
            data-testid="ask-mic"
            aria-pressed={listening}
            onPointerDown={startListening}
            onPointerUp={stopListening}
            onPointerLeave={() => { if (listening) stopListening(); }}
          >
            {listening ? 'Listening…' : 'Hold to talk'}
          </button>
        ) : (
          <span className="muted" data-testid="ask-no-speech">Speech is not supported in this browser: type your question.</span>
        )}
        <input value={text} onChange={(e) => { setText(e.target.value); }} placeholder="Who is most likely to crash in the ICU?" aria-label="Question" data-testid="ask-input" />
        <button type="submit" className="btn" disabled={busy || !text.trim()} data-testid="ask-send">Ask</button>
      </form>
      {resolved.recognizer && <div className="muted">Or hold Space while the 3D view has focus.</div>}
      {listening && <div className="ask__live" data-testid="ask-transcript">{text || '…'}</div>}
      {error && <div className="error" role="alert" data-testid="ask-error">{error}</div>}
      {busy && <div className="muted">Thinking…</div>}
      {answer && (
        <div className="ask__answer" role="dialog" aria-label="Answer" data-testid="ask-answer">
          <div className="muted">{answer.question}</div>
          <p data-testid="ask-answer-text">{answer.response.answer_text}</p>
          {answer.response.label && <div className="rec__label" data-testid="ask-label">{answer.response.label}</div>}
          <ul className="ask__entities">
            {answer.response.entity_ids.map((id) => (
              <li key={id}>
                <span>{id}</span>
                <button type="button" className="btn" onClick={() => { useTwin.getState().select(id); onFly?.(id); }}>Fly to</button>
              </li>
            ))}
          </ul>
          <ul className="rec__metrics" aria-label="Cited metrics">
            {answer.response.cited_metrics.map((m) => <li key={m.name} className="chip chip--small">{m.name} = {m.value}</li>)}
          </ul>
          <div className="ask__buttons">
            <label><input type="checkbox" checked={speak} onChange={(e) => { setSpeak(e.target.checked); if (!e.target.checked) resolved.speaker.cancel(); }} /> Speak answers</label>
            <button type="button" className="btn" onClick={close}>Close</button>
          </div>
        </div>
      )}
    </section>
  );
}
