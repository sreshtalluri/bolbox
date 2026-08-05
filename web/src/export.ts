/**
 * Offline render to a .wav.
 *
 * The file matches what was heard because it is produced by the same two
 * functions playback uses: `schedule()` decides when every note starts, and
 * `renderEvents()` builds every node. The only differences are the context
 * (OfflineAudioContext instead of AudioContext) and the window -- playback asks
 * for 100ms at a time because it has to keep up with a clock, and export asks
 * for the whole piece in one call because it does not.
 *
 * That single call is the useful consequence of `schedule()` being pure: a
 * lookahead window and a whole composition are the same operation.
 */

import { VoicePool, renderEvents } from "./graph";
import type { Kit } from "./kit";
import { createState, loopMatras, schedule } from "./scheduler";
import type { PatternJSON } from "./types";

export interface RenderOptions {
  /** How many times to play the pattern through. */
  readonly repeats?: number;
  /** Silence after the last stroke so tails are not cut off. */
  readonly tailSec?: number;
  readonly channels?: number;
  /**
   * Defaults to the kit's decode rate. Overriding it means every sample is
   * resampled a second time, which is exactly the drift from playback this
   * module exists to avoid -- so do not, unless you know why you are.
   */
  readonly sampleRate?: number;
  readonly masterGain?: number;
}

/** Anything with the OfflineAudioContext shape. Injectable so tests can fake it. */
export type OfflineContextFactory = (
  channels: number,
  length: number,
  sampleRate: number,
) => OfflineAudioContext;

const defaultFactory: OfflineContextFactory = (channels, length, sampleRate) =>
  new OfflineAudioContext(channels, length, sampleRate);

export async function renderPattern(
  pattern: PatternJSON,
  lay: number,
  kit: Kit,
  options: RenderOptions = {},
  makeContext: OfflineContextFactory = defaultFactory,
): Promise<AudioBuffer> {
  if (!(lay > 0)) throw new RangeError(`lay must be positive, got ${lay}`);

  const repeats = Math.max(1, Math.floor(options.repeats ?? 1));
  const sampleRate = options.sampleRate ?? kit.sampleRate;
  const channels = options.channels ?? 2;
  // Long enough for the longest sample in the kit to ring out, so the last
  // stroke of the composition is not clipped mid-decay.
  const tailSec = options.tailSec ?? Math.max(0.5, kit.longestSampleSec);

  const bodySec = (loopMatras(pattern) * repeats * 60) / lay;
  const totalSec = bodySec + tailSec;
  const frames = Math.max(1, Math.ceil(totalSec * sampleRate));

  const ctx = makeContext(channels, frames, sampleRate);
  const master = ctx.createGain();
  master.gain.value = options.masterGain ?? 0.9;
  master.connect(ctx.destination);

  // One call, [0, bodySec). Same half-open window, same round robin, same
  // anchoring as the 100ms windows playback asks for.
  const { events } = schedule(pattern, lay, 0, bodySec, createState(0, lay));
  renderEvents(ctx, master, events, kit, new VoicePool());

  return ctx.startRendering();
}

export async function renderPatternToWav(
  pattern: PatternJSON,
  lay: number,
  kit: Kit,
  options: RenderOptions = {},
  makeContext: OfflineContextFactory = defaultFactory,
): Promise<Blob> {
  const buffer = await renderPattern(pattern, lay, kit, options, makeContext);
  return new Blob([encodeWav(buffer)], { type: "audio/wav" });
}

/**
 * 16-bit PCM WAV.
 *
 * OfflineAudioContext hands back float samples and no container, so the header
 * has to be written by hand. 16-bit rather than float32 because that is what
 * every DAW, phone and browser opens without asking questions.
 */
export function encodeWav(buffer: AudioBuffer): ArrayBuffer {
  const channels = buffer.numberOfChannels;
  const frames = buffer.length;
  const bytesPerSample = 2;
  const blockAlign = channels * bytesPerSample;
  const dataBytes = frames * blockAlign;

  const out = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(out);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, "WAVE");

  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true); // PCM fmt chunk size
  view.setUint16(20, 1, true); // format: PCM
  view.setUint16(22, channels, true);
  view.setUint32(24, buffer.sampleRate, true);
  view.setUint32(28, buffer.sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 8 * bytesPerSample, true);

  writeAscii(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  const data: Float32Array[] = [];
  for (let c = 0; c < channels; c++) data.push(buffer.getChannelData(c));

  let offset = 44;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < channels; c++) {
      const sample = data[c]?.[i] ?? 0;
      // Clamp before scaling: a summed transient over 1.0 would otherwise wrap
      // to full-scale negative, which is a loud click rather than a soft clip.
      const clamped = sample < -1 ? -1 : sample > 1 ? 1 : sample;
      view.setInt16(offset, Math.round(clamped * 32767), true);
      offset += 2;
    }
  }
  return out;
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
}

/** Hand a blob to the browser as a download. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking immediately can race the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export function safeFilename(title: string, fallback: string): string {
  const cleaned = title.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return cleaned || fallback;
}
