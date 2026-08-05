/**
 * The impure half of playback: a clock, a timer, and a destination.
 *
 * All the timing logic is in scheduler.ts and all the node building is in
 * graph.ts. What is left here is the lookahead loop, which is the one thing
 * that genuinely cannot be pure -- it reads `AudioContext.currentTime`.
 *
 * WHY A TIMER AT ALL
 *
 * setInterval is not accurate enough to fire notes with; it drifts, it is
 * throttled in background tabs, and it is at the mercy of the main thread. It
 * does not have to be accurate. It only has to wake up often enough to hand the
 * audio thread work that is already stamped with an exact time. A 25ms tick
 * against a 100ms window means three missed wakeups in a row still schedule
 * everything on time; the notes themselves are placed by the audio clock.
 */

import type { Kit } from "./kit";
import { VoicePool, renderEvents } from "./graph";
import {
  createState,
  loopMatras,
  matraAt,
  schedule,
  type SchedulerState,
} from "./scheduler";
import type { PatternJSON } from "./types";

export const LOOKAHEAD_SEC = 0.1;
export const TICK_MS = 25;

export interface PlayerOptions {
  readonly lookaheadSec?: number;
  readonly tickMs?: number;
  /** Called with strokes the current kit cannot play. */
  readonly onMissingStrokes?: (strokes: string[]) => void;
  readonly onError?: (err: Error) => void;
}

export class Player {
  readonly ctx: AudioContext;
  private readonly master: GainNode;
  private readonly pool = new VoicePool();
  private readonly lookaheadSec: number;
  private readonly tickMs: number;
  private readonly options: PlayerOptions;

  private pattern: PatternJSON | null = null;
  private kit: Kit | null = null;
  private lay = 120;
  private state: SchedulerState | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private reportedMissing = "";

  constructor(ctx: AudioContext, options: PlayerOptions = {}) {
    this.ctx = ctx;
    this.options = options;
    this.lookaheadSec = options.lookaheadSec ?? LOOKAHEAD_SEC;
    this.tickMs = options.tickMs ?? TICK_MS;
    this.master = ctx.createGain();
    this.master.gain.value = 0.9;
    this.master.connect(ctx.destination);
  }

  get playing(): boolean {
    return this.timer !== null;
  }

  setPattern(pattern: PatternJSON): void {
    this.pattern = pattern;
    // A new composition restarts the loop rather than dropping into the middle
    // of the old one at whatever position the clock happens to be at.
    if (this.playing) this.restart();
  }

  setKit(kit: Kit): void {
    this.kit = kit;
    this.reportedMissing = "";
  }

  /**
   * Change tempo. Safe mid-playback: the scheduler re-anchors at the edge of
   * what it has already committed, so nothing repeats and nothing is skipped.
   */
  setLay(lay: number): void {
    if (!(lay > 0)) return;
    this.lay = lay;
  }

  get currentLay(): number {
    return this.lay;
  }

  /** Matras from sam of the loop currently sounding. Drives the UI readout. */
  get positionMatras(): number {
    if (!this.state || !this.pattern) return 0;
    const span = loopMatras(this.pattern);
    const m = matraAt(this.state, this.ctx.currentTime);
    return ((m % span) + span) % span;
  }

  async play(): Promise<void> {
    if (this.playing) return;
    if (!this.pattern || !this.kit) {
      throw new Error("player needs both a pattern and a kit before play()");
    }
    // Browsers start contexts suspended until a gesture; currentTime does not
    // advance while suspended, so resuming before anchoring matters.
    if (this.ctx.state === "suspended") await this.ctx.resume();

    this.state = createState(this.ctx.currentTime, this.lay);
    this.pool.reset();
    this.tick();
    this.timer = setInterval(() => this.tick(), this.tickMs);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.pool.stopAll(this.ctx.currentTime);
    this.state = null;
  }

  private restart(): void {
    this.stop();
    void this.play();
  }

  private tick(): void {
    const pattern = this.pattern;
    const kit = this.kit;
    const state = this.state;
    if (!pattern || !kit || !state) return;

    try {
      const result = schedule(
        pattern,
        this.lay,
        this.ctx.currentTime,
        this.lookaheadSec,
        state,
      );
      this.state = result.nextState;
      if (result.events.length === 0) return;

      const plan = renderEvents(this.ctx, this.master, result.events, kit, this.pool);
      if (plan.missing.length > 0) {
        // Report a given set once, not sixteen times a second.
        const key = plan.missing.join(",");
        if (key !== this.reportedMissing) {
          this.reportedMissing = key;
          this.options.onMissingStrokes?.(plan.missing);
        }
      }
    } catch (err) {
      // A throw inside setInterval is invisible otherwise, and playback would
      // just quietly stop making sound.
      this.stop();
      this.options.onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  }
}
