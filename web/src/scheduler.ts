/**
 * The pure half of playback.
 *
 * `schedule()` takes the current audio-clock reading and a lookahead window and
 * returns exactly the events that start inside `[nowSec, nowSec + windowSec)`,
 * each stamped with an absolute time. It touches no AudioContext, no globals,
 * no clock. Everything that would otherwise be hidden mutable state -- how far
 * we have scheduled, what the tempo anchor is, where each stroke's round robin
 * has got to -- is carried in and out as a value.
 *
 * That is not tidiness for its own sake. The three properties that make a
 * sequencer usable (nothing fires twice, nothing is dropped, nothing drifts)
 * are timing properties, and timing properties are only testable if you can
 * drive the clock yourself. With this signature the whole test suite is
 * arithmetic.
 *
 * THREE INVARIANTS, AND HOW EACH IS BOUGHT
 *
 * 1. Exactly once. The window is half-open and `state.cursorSec` remembers the
 *    exclusive lower bound already covered. An event landing precisely on a
 *    window boundary belongs to the later window, never both and never neither.
 *
 * 2. No drift. Every event time is `anchorSec + (absoluteMatra - anchorMatra) *
 *    secPerMatra` -- one multiply from a fixed anchor. Cycle N's sam is derived
 *    from N, never from cycle N-1 plus a cycle duration, so the error at cycle
 *    10000 is the same single rounding as at cycle 1.
 *
 * 3. A lay change re-anchors. See `reanchor()`.
 */

import type { PatternJSON } from "./types";

export interface ScheduledEvent {
  /** Absolute time on the audio clock. */
  readonly whenSec: number;
  readonly stroke: string;
  readonly velocity: number;
  readonly sourceBol: string;
  /** Index of this stroke within its bol. 0 starts the bol. */
  readonly bolOffset: number;
  /**
   * Monotonic per-stroke counter. The kit does `samples[rrIndex %
   * samples.length]`. It lives in scheduler state rather than in the sampler
   * because it has to survive across scheduler calls -- a counter reset every
   * 25ms tick is a counter that always picks sample 0, which is exactly the
   * machine-gun artifact round robins exist to kill.
   */
  readonly rrIndex: number;
  /** Same counter, keyed by `sourceBol`, advanced once per composite group. */
  readonly bolRrIndex: number;
  /**
   * Events struck at one instant by one bol share this. The graph builder uses
   * it to notice that `ge` + `na` here were a `dha`, and to fire a single
   * composite sample if the kit has one.
   */
  readonly groupKey: string;
  /** Which repetition of the whole pattern this came from. */
  readonly loopIndex: number;
  /** Matras from sam, within the loop. */
  readonly posMatras: number;
}

export interface SchedulerState {
  /**
   * Time/tempo anchor. `anchorMatra` is the absolute matra count (across loops)
   * that falls at `anchorSec`, and `lay` is the tempo in force since then.
   */
  readonly anchorSec: number;
  readonly anchorMatra: number;
  readonly lay: number;
  /** Everything strictly before this has already been handed out. */
  readonly cursorSec: number;
  readonly rr: Readonly<Record<string, number>>;
  readonly bolRr: Readonly<Record<string, number>>;
}

export interface ScheduleResult {
  readonly events: ScheduledEvent[];
  readonly nextState: SchedulerState;
}

/** Fresh state for a playback run starting at `startSec` on the audio clock. */
export function createState(startSec: number, lay: number): SchedulerState {
  if (!(lay > 0)) throw new RangeError(`lay must be positive, got ${lay}`);
  return {
    anchorSec: startSec,
    anchorMatra: 0,
    lay,
    cursorSec: startSec,
    rr: {},
    bolRr: {},
  };
}

/**
 * Matras in one repetition of the whole pattern.
 *
 * Not `cycle_matras`: with `avartans > 1` the pattern is several avartans long
 * and carries events at positions past the first cycle, which looping on
 * `cycle_matras` would either drop or fire twice. When `avartans === 1` -- the
 * common case -- this is exactly `cycle_matras`.
 */
export function loopMatras(pattern: PatternJSON): number {
  const avartans = pattern.avartans > 0 ? pattern.avartans : 1;
  return pattern.cycle_matras * avartans;
}

/** Absolute audio time at which loop `loopIndex` begins. */
export function loopStartSec(
  pattern: PatternJSON,
  state: SchedulerState,
  loopIndex: number,
): number {
  const m = loopIndex * loopMatras(pattern);
  return state.anchorSec + (m - state.anchorMatra) * (60 / state.lay);
}

/** Musical position (absolute matras) at an absolute time. */
export function matraAt(state: SchedulerState, timeSec: number): number {
  return state.anchorMatra + (timeSec - state.anchorSec) * (state.lay / 60);
}

/**
 * Move the anchor so the new lay takes effect without a seam.
 *
 * The pivot is `cursorSec`, not `nowSec`. Events out to the cursor have already
 * been handed to the audio graph and started; a pure function cannot recall
 * them. Re-anchoring at `nowSec` would therefore re-derive times for material
 * that is already committed and either repeat it or leave a hole. Pivoting at
 * the cursor means the tempo change lands at the edge of the committed region
 * -- at most one lookahead window late, which is 100ms -- and the musical
 * position is continuous across it by construction, because we read the
 * position off the OLD map and write it into the NEW one at the same instant.
 */
export function reanchor(state: SchedulerState, lay: number): SchedulerState {
  if (!(lay > 0)) throw new RangeError(`lay must be positive, got ${lay}`);
  if (lay === state.lay) return state;
  const pivotSec = state.cursorSec;
  return {
    ...state,
    anchorSec: pivotSec,
    anchorMatra: matraAt(state, pivotSec),
    lay,
  };
}

export function schedule(
  pattern: PatternJSON,
  lay: number,
  nowSec: number,
  windowSec: number,
  state: SchedulerState,
): ScheduleResult {
  if (!(lay > 0)) throw new RangeError(`lay must be positive, got ${lay}`);
  if (!(windowSec >= 0)) throw new RangeError(`windowSec must be >= 0, got ${windowSec}`);

  const s = reanchor(state, lay);
  const from = Math.max(nowSec, s.cursorSec);
  const until = nowSec + windowSec;
  // Cursor only ever moves forward: a caller that ticks faster than the window
  // is long must not be able to re-open a region it already covered.
  const nextCursor = Math.max(s.cursorSec, until);

  if (until <= from || pattern.events.length === 0) {
    return { events: [], nextState: { ...s, cursorSec: nextCursor } };
  }

  const span = loopMatras(pattern);
  if (span <= 0) {
    return { events: [], nextState: { ...s, cursorSec: nextCursor } };
  }
  const secPerMatra = 60 / s.lay;

  // Bound the loop indices to inspect from the time window, then filter on the
  // exact times. The slack absorbs float error in this estimate and any event
  // sitting past the end of its own loop (a malformed pattern, but silently
  // dropping it would be worse than scanning a few extra candidates). The
  // half-open time comparison below is what actually decides membership.
  let maxPos = 0;
  for (const e of pattern.events) {
    const p = e.pos[0] / (e.pos[1] === 0 ? 1 : e.pos[1]);
    if (p > maxPos) maxPos = p;
  }
  const slack = 1 + Math.ceil(maxPos / span);
  const firstLoop = Math.max(0, Math.floor(matraAt(s, from) / span) - slack);
  const lastLoop = Math.floor(matraAt(s, until) / span) + 1;

  const out: ScheduledEvent[] = [];
  for (let loopIndex = firstLoop; loopIndex <= lastLoop; loopIndex++) {
    for (const e of pattern.events) {
      const num = e.pos[0];
      const den = e.pos[1] === 0 ? 1 : e.pos[1];
      // Keep the loop offset inside the numerator so the integer part of the
      // position stays exact however many loops in we are; this is the one
      // place the [num, den] pair becomes a float.
      const absMatra = (loopIndex * span * den + num) / den;
      const whenSec = s.anchorSec + (absMatra - s.anchorMatra) * secPerMatra;
      if (whenSec >= from && whenSec < until) {
        out.push({
          whenSec,
          stroke: e.stroke,
          velocity: e.velocity,
          sourceBol: e.source_bol,
          bolOffset: e.bol_offset ?? 0,
          rrIndex: 0,
          bolRrIndex: 0,
          groupKey: `${loopIndex}:${num}/${den}:${e.source_bol || e.stroke}`,
          loopIndex,
          posMatras: num / den,
        });
      }
    }
  }

  // Array.prototype.sort is stable, so events at one instant keep pattern
  // order. Composite grouping downstream depends on that being deterministic.
  out.sort((a, b) => a.whenSec - b.whenSec);

  const rr: Record<string, number> = { ...s.rr };
  const bolRr: Record<string, number> = { ...s.bolRr };
  const perGroup = new Map<string, number>();
  const stamped: ScheduledEvent[] = out.map((e) => {
    const rrIndex = rr[e.stroke] ?? 0;
    rr[e.stroke] = rrIndex + 1;
    // One advance per composite group, not per stroke in it: a `dha` steps the
    // `dha` round robin once, however many strokes it decomposes to. Both
    // members of a group are always in the same window -- they share a
    // whenSec -- so a per-call map is enough to keep them on one index.
    let bolRrIndex = perGroup.get(e.groupKey);
    if (bolRrIndex === undefined) {
      const bolKey = e.sourceBol || e.stroke;
      bolRrIndex = bolRr[bolKey] ?? 0;
      bolRr[bolKey] = bolRrIndex + 1;
      perGroup.set(e.groupKey, bolRrIndex);
    }
    return { ...e, rrIndex, bolRrIndex };
  });

  return {
    events: stamped,
    nextState: { ...s, cursorSec: nextCursor, rr, bolRr },
  };
}

/** Which sample a round-robin counter selects out of `count`. */
export function rrPick(index: number, count: number): number {
  if (count <= 0) return 0;
  return ((index % count) + count) % count;
}
