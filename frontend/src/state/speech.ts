/**
 * Speech in and out for "Ask Hospital Twin" (PROMPT.md §9.1). The browser's Web Speech API sits behind small
 * interfaces so the push-to-talk logic can be tested with a fake recognizer and the app can fall back to typing
 * where speech is not supported.
 */

export interface RecognizerHandlers {
  /** The transcript so far; `final` is true once the browser is sure of it. */
  onTranscript: (text: string, final: boolean) => void;
  /** The recognizer stopped (after stop(), silence, or an error). */
  onEnd: () => void;
  onError: (message: string) => void;
}

export interface Recognizer {
  start(handlers: RecognizerHandlers): void;
  stop(): void;
}

export interface Speaker {
  speak(text: string): void;
  cancel(): void;
}

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEventLike {
  results: ArrayLike<RecognitionResult>;
}
interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: RecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type RecognitionCtor = new () => RecognitionLike;

export interface SpeechHost {
  SpeechRecognition?: RecognitionCtor;
  webkitSpeechRecognition?: RecognitionCtor;
  speechSynthesis?: { speak(u: unknown): void; cancel(): void };
  SpeechSynthesisUtterance?: new (text: string) => unknown;
}

const ERRORS: Record<string, string> = {
  'not-allowed': 'The microphone is blocked. Allow it in the browser, or type your question.',
  'service-not-allowed': 'The microphone is blocked. Allow it in the browser, or type your question.',
  'no-speech': 'No speech heard. Hold the button while you speak, or type your question.',
  'audio-capture': 'No microphone found. Type your question instead.',
  network: 'Speech recognition needs a network connection. Type your question instead.',
};

export function speechError(code: string): string {
  return ERRORS[code] ?? `Speech recognition failed (${code}). Type your question instead.`;
}

/** A recognizer on the browser's SpeechRecognition, or null when the browser has none (Firefox, for example). */
export function createRecognizer(host: SpeechHost): Recognizer | null {
  const Ctor = host.SpeechRecognition ?? host.webkitSpeechRecognition;
  if (!Ctor) return null;
  let active: RecognitionLike | null = null;
  return {
    start(handlers) {
      const r = new Ctor();
      r.lang = 'en-US';
      r.interimResults = true;
      r.continuous = false;
      r.onresult = (e) => {
        let text = '';
        let final = true;
        for (let i = 0; i < e.results.length; i++) {
          const part = e.results[i];
          if (!part) continue;
          text += part[0].transcript;
          final &&= part.isFinal;
        }
        handlers.onTranscript(text.trim(), final);
      };
      r.onerror = (e) => { handlers.onError(speechError(e.error)); };
      r.onend = () => {
        active = null;
        handlers.onEnd();
      };
      active = r;
      r.start();
    },
    stop() {
      active?.stop();
    },
  };
}

/** Speaks answers with speechSynthesis; does nothing where it does not exist. */
export function createSpeaker(host: SpeechHost): Speaker {
  const synth = host.speechSynthesis;
  const Utterance = host.SpeechSynthesisUtterance;
  return {
    speak(text) {
      if (!synth || !Utterance) return;
      synth.cancel();
      synth.speak(new Utterance(text));
    },
    cancel() {
      synth?.cancel();
    },
  };
}
