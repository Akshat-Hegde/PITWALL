// Moment sounds, synthesised in the browser (no audio files, nothing to license). Off unless the hub's
// [sounds] enabled is true. TV browsers may block audio until someone clicks the page once; kiosk Chrome
// can be started with --autoplay-policy=no-user-gesture-required (see README).

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

/** One short tone: frequency (Hz), start offset and length (s). */
function tone(ac: AudioContext, freq: number, at: number, length: number, volume: number, type: OscillatorType) {
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const t0 = ac.currentTime + at;
  gain.gain.setValueAtTime(0, t0);
  gain.gain.linearRampToValueAtTime(volume, t0 + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + length);
  osc.connect(gain).connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + length + 0.05);
}

export type SoundKind = "session_start" | "record";

export function playSound(kind: SoundKind, volume: number): void {
  const ac = audio();
  if (!ac || volume <= 0) return;
  const v = Math.min(1, volume) * 0.25;
  if (kind === "session_start") {
    // two rising tones, like a pit-lane light going green
    tone(ac, 660, 0, 0.18, v, "triangle");
    tone(ac, 990, 0.16, 0.32, v, "triangle");
  } else {
    // short three-note fanfare
    tone(ac, 523, 0, 0.16, v, "sawtooth");
    tone(ac, 659, 0.14, 0.16, v, "sawtooth");
    tone(ac, 784, 0.28, 0.5, v, "sawtooth");
    tone(ac, 1047, 0.28, 0.5, v * 0.5, "triangle");
  }
}
