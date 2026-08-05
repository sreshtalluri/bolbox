/**
 * The one place notes become WebAudio nodes.
 *
 * player.ts and export.ts both call `renderEvents()`. Neither of them builds a
 * source node itself. That is deliberate and it is the whole point of this
 * file: if export duplicated the note-firing logic then "the .wav matches what
 * you heard" would be a property you have to keep testing, and it would rot the
 * first time someone tuned a release curve on the playback side only. Sharing
 * the code makes it true by construction.
 *
 * `BaseAudioContext` is the shared supertype of AudioContext and
 * OfflineAudioContext, so nothing here can accidentally depend on a live clock.
 * Every time is absolute and comes from the scheduler.
 */

import type { Kit, Voice } from "./kit";
import type { ScheduledEvent } from "./scheduler";

/** A note resolved against a kit but not yet turned into nodes. */
export interface RenderNote {
  readonly whenSec: number;
  readonly buffer: AudioBuffer;
  readonly gain: number;
  readonly playbackRate: number;
  /** Voice-cap bucket. Composites count against their own bucket, not `ge`'s. */
  readonly voiceKey: string;
  readonly label: string;
}

export interface PlanResult {
  readonly notes: RenderNote[];
  /** Strokes the pattern asked for that this kit has no sample for. */
  readonly missing: string[];
}

/** MIDI velocity is 1..127. */
const MAX_VELOCITY = 127;

/**
 * Resolve scheduled events against a kit.
 *
 * The composite rule: events sharing a `groupKey` came from one spoken bol. If
 * the kit has a recorded sample for that bol, they become ONE note. Otherwise
 * they stay separate strokes, which is the correct fallback -- a kit with only
 * single strokes still plays `dha` as ge+na, just less convincingly.
 */
export function planNotes(events: readonly ScheduledEvent[], kit: Kit): PlanResult {
  const groups = new Map<string, ScheduledEvent[]>();
  for (const e of events) {
    const g = groups.get(e.groupKey);
    if (g) g.push(e);
    else groups.set(e.groupKey, [e]);
  }

  const notes: RenderNote[] = [];
  const missing = new Set<string>();
  const consumed = new Set<string>();

  for (const e of events) {
    if (consumed.has(e.groupKey)) continue;
    const group = groups.get(e.groupKey) ?? [e];

    // A composite replaces strokes that sound at ONE instant, so the group has
    // to have more than one member. bolbox/kit.py already refuses a composite
    // for a sequential bol, but this reads the raw kit.json rather than going
    // through that loader -- and without this check a hand-written composite
    // for `tirakita` would fire the whole word on each of its four strokes.
    const composite = group.length > 1 ? kit.resolveComposite(e.sourceBol) : undefined;
    if (composite) {
      consumed.add(e.groupKey);
      // The loudest constituent wins. A `dha` whose `ge` is accented and whose
      // `na` is not is still an accented dha; averaging would flatten it.
      const velocity = Math.max(...group.map((g) => g.velocity));
      // The stroke that starts the bol carries the group's round-robin index.
      const head = group.find((g) => g.bolOffset === 0) ?? e;
      const note = noteFor(kit, composite, head.bolRrIndex, velocity, e.whenSec, e.sourceBol);
      if (note) notes.push(note);
      else missing.add(e.sourceBol);
      continue;
    }

    const voice = kit.stroke(e.stroke);
    if (!voice) {
      missing.add(e.stroke);
      continue;
    }
    const note = noteFor(kit, voice, e.rrIndex, e.velocity, e.whenSec, e.stroke);
    if (note) notes.push(note);
    else missing.add(e.stroke);
  }

  return { notes, missing: [...missing] };
}

function noteFor(
  kit: Kit,
  voice: Voice,
  rrIndex: number,
  velocity: number,
  whenSec: number,
  label: string,
): RenderNote | undefined {
  const buffer = kit.sampleFor(voice, rrIndex);
  if (!buffer) return undefined;
  return {
    whenSec,
    buffer,
    gain: voice.gain * (clampVelocity(velocity) / MAX_VELOCITY),
    playbackRate: voice.playbackRate,
    voiceKey: voice.key,
    label,
  };
}

function clampVelocity(v: number): number {
  if (!Number.isFinite(v)) return 100;
  return Math.min(MAX_VELOCITY, Math.max(1, v));
}

// -- voices -----------------------------------------------------------------

export const VOICES_PER_STROKE = 4;
export const STEAL_RELEASE_SEC = 0.02;

interface ActiveVoice {
  readonly gainNode: GainNode;
  readonly source: AudioBufferSourceNode;
  readonly startSec: number;
  endSec: number;
  readonly gain: number;
}

/**
 * Per-stroke voice cap with a short release on steal.
 *
 * Four `na` ringing at once is already more than a hand can produce; past that
 * a fast tirakita just accumulates overlapping tails and turns to mud. Stopping
 * the stolen voice outright would click, so it gets a 20ms ramp to zero.
 *
 * Liveness is decided from SCHEDULED TIMES, never from a wall clock. That is
 * what lets an OfflineAudioContext rendering forty times faster than real time
 * steal exactly the same voices at exactly the same instants as playback did.
 */
export class VoicePool {
  private readonly active = new Map<string, ActiveVoice[]>();

  constructor(
    private readonly maxPerKey: number = VOICES_PER_STROKE,
    private readonly releaseSec: number = STEAL_RELEASE_SEC,
  ) {}

  reset(): void {
    this.active.clear();
  }

  fire(ctx: BaseAudioContext, destination: AudioNode, note: RenderNote): void {
    const list = this.active.get(note.voiceKey) ?? [];

    // Drop anything that has certainly finished by the time this note starts.
    let live = list.filter((v) => v.endSec > note.whenSec);

    while (live.length >= this.maxPerKey) {
      const stolen = live.shift();
      if (!stolen) break;
      const releaseEnd = note.whenSec + this.releaseSec;
      stolen.gainNode.gain.cancelScheduledValues(note.whenSec);
      stolen.gainNode.gain.setValueAtTime(stolen.gain, note.whenSec);
      stolen.gainNode.gain.linearRampToValueAtTime(0, releaseEnd);
      stolen.source.stop(releaseEnd);
      stolen.endSec = releaseEnd;
    }

    const source = ctx.createBufferSource();
    source.buffer = note.buffer;
    source.playbackRate.value = note.playbackRate;

    const gainNode = ctx.createGain();
    gainNode.gain.value = note.gain;

    source.connect(gainNode).connect(destination);
    source.start(note.whenSec);

    const endSec = note.whenSec + note.buffer.duration / note.playbackRate;
    live.push({ gainNode, source, startSec: note.whenSec, endSec, gain: note.gain });
    this.active.set(note.voiceKey, live);
  }

  /** Silence everything still sounding, with the same release used on steal. */
  stopAll(atSec: number): void {
    for (const list of this.active.values()) {
      for (const v of list) {
        const end = atSec + this.releaseSec;
        try {
          v.gainNode.gain.cancelScheduledValues(atSec);
          v.gainNode.gain.setValueAtTime(v.gainNode.gain.value, atSec);
          v.gainNode.gain.linearRampToValueAtTime(0, end);
          v.source.stop(end);
        } catch {
          // Already stopped. Nothing to do, and nothing worth reporting.
        }
      }
    }
    this.active.clear();
  }
}

/**
 * Turn scheduled events into sounding nodes. THE shared path.
 *
 * Callers must pass the same pool across successive calls for one playback run
 * (and a fresh pool per render), because voice stealing is stateful and that
 * state is what has to match between playback and export.
 */
export function renderEvents(
  ctx: BaseAudioContext,
  destination: AudioNode,
  events: readonly ScheduledEvent[],
  kit: Kit,
  pool: VoicePool,
): PlanResult {
  const plan = planNotes(events, kit);
  for (const note of plan.notes) pool.fire(ctx, destination, note);
  return plan;
}
