import { describe, expect, it } from "vitest";

import {
  createState,
  loopStartSec,
  matraAt,
  rrPick,
  schedule,
  type ScheduledEvent,
  type SchedulerState,
} from "./scheduler";
import type { PatternEventJSON, PatternJSON } from "./types";

// -- fixtures ---------------------------------------------------------------

function ev(
  num: number,
  den: number,
  stroke: string,
  sourceBol = stroke,
): PatternEventJSON {
  return { pos: [num, den], stroke, velocity: 100, source_bol: sourceBol };
}

function pattern(events: PatternEventJSON[], over: Partial<PatternJSON> = {}): PatternJSON {
  return {
    tal: "tintal",
    cycle_matras: 16,
    lay: 120,
    avartans: 1,
    title: "test",
    events,
    ...over,
  };
}

/** dha na dhin na -- four matras of tintal, with dha as a composite pair. */
const FOUR_BEAT = pattern([
  ...[ev(0, 1, "ge", "dha"), ev(0, 1, "na", "dha")],
  ev(1, 1, "na"),
  ...[ev(2, 1, "ge", "dhin"), ev(2, 1, "tin", "dhin")],
  ev(3, 1, "na"),
]);

/** One stroke on every matra of the cycle. Easy to count. */
const EVERY_MATRA = pattern(
  Array.from({ length: 16 }, (_, i) => ev(i, 1, i % 2 === 0 ? "na" : "te")),
);

/**
 * Drive the scheduler the way player.ts does: fixed tick, fixed lookahead,
 * clock advancing by the tick. `layAt` lets a test change tempo mid-run.
 */
function run(
  p: PatternJSON,
  opts: {
    startSec?: number;
    tickSec?: number;
    windowSec?: number;
    untilSec: number;
    layAt?: (timeSec: number) => number;
  },
): { events: ScheduledEvent[]; state: SchedulerState } {
  const startSec = opts.startSec ?? 0;
  const tickSec = opts.tickSec ?? 0.025;
  const windowSec = opts.windowSec ?? 0.1;
  const layAt = opts.layAt ?? (() => p.lay);

  let state = createState(startSec, layAt(startSec));
  const events: ScheduledEvent[] = [];
  for (let t = startSec; t < opts.untilSec; t += tickSec) {
    // Clamp the last window so the run covers exactly [startSec, untilSec).
    // Without this the lookahead reaches past the end and the counts a test
    // asserts stop being the counts it meant to assert.
    const w = Math.min(windowSec, opts.untilSec - t);
    const r = schedule(p, layAt(t), t, w, state);
    events.push(...r.events);
    state = r.nextState;
  }
  return { events, state };
}

function sams(events: ScheduledEvent[]): ScheduledEvent[] {
  return events.filter((e) => e.posMatras === 0);
}

// -- exactly once -----------------------------------------------------------

describe("every event is scheduled exactly once", () => {
  it("does not emit an event that lands on a window boundary twice", () => {
    // lay 120 => 0.5s per matra. The event at matra 2 lands at exactly 1.0s,
    // which is the boundary between the two windows below.
    const p = pattern([ev(2, 1, "na")], { cycle_matras: 16 });
    let state = createState(0, 120);

    const first = schedule(p, 120, 0.9, 0.1, state); // [0.9, 1.0)
    state = first.nextState;
    const second = schedule(p, 120, 1.0, 0.1, state); // [1.0, 1.1)

    expect(first.events).toHaveLength(0);
    expect(second.events).toHaveLength(1);
    expect(second.events[0]!.whenSec).toBe(1.0);
  });

  it("does not drop an event that lands on a window boundary", () => {
    const p = pattern([ev(2, 1, "na")]);
    const { events } = run(p, { untilSec: 2, tickSec: 0.1, windowSec: 0.1 });
    expect(events.filter((e) => e.whenSec === 1.0)).toHaveLength(1);
  });

  it("emits nothing twice when the caller ticks faster than the window", () => {
    // 5ms tick against a 100ms window: every call overlaps the previous one
    // twenty-fold. Only the cursor stops that from being twenty copies.
    const { events } = run(EVERY_MATRA, { untilSec: 8, tickSec: 0.005, windowSec: 0.1 });
    const stamps = events.map((e) => `${e.loopIndex}:${e.posMatras}:${e.stroke}`);
    expect(new Set(stamps).size).toBe(stamps.length);
  });

  it("emits every event of every cycle exactly once over a long run", () => {
    // 16 matras at lay 120 = 8s per cycle; 10 cycles = 80s.
    const { events } = run(EVERY_MATRA, { untilSec: 80 });
    expect(events).toHaveLength(16 * 10);
    const stamps = events.map((e) => `${e.loopIndex}:${e.posMatras}`);
    expect(new Set(stamps).size).toBe(stamps.length);
  });

  it("hands events out in non-decreasing time order", () => {
    const { events } = run(FOUR_BEAT, { untilSec: 30 });
    for (let i = 1; i < events.length; i++) {
      expect(events[i]!.whenSec).toBeGreaterThanOrEqual(events[i - 1]!.whenSec);
    }
  });

  it("advances the cursor even when the window is empty of events", () => {
    const p = pattern([ev(0, 1, "na")]);
    const state = createState(0, 120);
    const r = schedule(p, 120, 5.0, 0.1, state);
    expect(r.events).toHaveLength(0);
    expect(r.nextState.cursorSec).toBe(5.1);
  });

  it("never moves the cursor backwards", () => {
    let state = createState(0, 120);
    state = schedule(EVERY_MATRA, 120, 1.0, 0.1, state).nextState;
    const after = schedule(EVERY_MATRA, 120, 0.5, 0.1, state).nextState;
    expect(after.cursorSec).toBe(1.1);
  });
});

// -- no drift ---------------------------------------------------------------

describe("looping does not drift", () => {
  it("puts the 100th cycle's sam at exactly 100 * cycleMatras * 60 / lay", () => {
    const p = pattern([ev(0, 1, "ge", "dha"), ev(0, 1, "na", "dha")]);
    const cycleSec = (p.cycle_matras * 60) / p.lay; // 8s
    const total = cycleSec * 101;

    const { events } = run(p, { untilSec: total, tickSec: 0.25, windowSec: 0.5 });
    const cycle100 = events.filter((e) => e.loopIndex === 100);

    expect(cycle100).toHaveLength(2);
    // Exact float equality, not a tolerance. 100 * 16 * 60 / 120 = 800.
    expect(cycle100[0]!.whenSec).toBe(800);
    expect(cycle100[0]!.whenSec).toBe((100 * p.cycle_matras * 60) / p.lay);
  });

  it("stays exact for 100+ cycles at a lay with no clean binary representation", () => {
    const p = pattern([ev(0, 1, "na"), ev(7, 3, "te")], { lay: 97 });
    const cycleSec = (p.cycle_matras * 60) / p.lay;
    const { events } = run(p, {
      untilSec: cycleSec * 120,
      tickSec: 0.25,
      windowSec: 0.5,
    });

    for (const e of sams(events)) {
      const ideal = (e.loopIndex * p.cycle_matras * 60) / p.lay;
      // One rounding, not `loopIndex` roundings. Accumulating a cycle duration
      // instead would put cycle 100 microseconds out, not nanoseconds.
      expect(Math.abs(e.whenSec - ideal)).toBeLessThan(1e-9);
    }
    expect(sams(events).length).toBeGreaterThan(100);
  });

  it("keeps fractional positions exact deep into a run", () => {
    // Tisra: three strokes to the matra. 1/3 is not representable in binary, so
    // this is the case where accumulation would show up first.
    const p = pattern([ev(0, 1, "na"), ev(1, 3, "te"), ev(2, 3, "re")]);
    const { events } = run(p, { untilSec: 8 * 60, tickSec: 0.25, windowSec: 0.5 });
    for (const e of events) {
      const absMatra = e.loopIndex * p.cycle_matras + e.posMatras;
      expect(e.whenSec).toBeCloseTo((absMatra * 60) / p.lay, 9);
    }
  });

  it("derives loopStartSec from the index, not from an accumulator", () => {
    const p = pattern([ev(0, 1, "na")]);
    const state = createState(0, 120);
    expect(loopStartSec(p, state, 0)).toBe(0);
    expect(loopStartSec(p, state, 1)).toBe(8);
    expect(loopStartSec(p, state, 10_000)).toBe(80_000);
  });
});

// -- lay changes ------------------------------------------------------------

describe("a lay change re-anchors cleanly", () => {
  it("keeps musical position continuous across the change", () => {
    const p = pattern([ev(0, 1, "na")]);
    let state = createState(0, 120);
    state = schedule(p, 120, 0, 0.1, state).nextState;

    const before = matraAt(state, state.cursorSec);
    const after = schedule(p, 240, 0.1, 0.1, state).nextState;

    // Same instant, same position on the composition -- only the rate ahead of
    // it differs. This is what "no seam" means.
    expect(matraAt(after, state.cursorSec)).toBeCloseTo(before, 12);
    expect(after.lay).toBe(240);
  });

  it("does not repeat or skip an event when the lay doubles mid-playback", () => {
    const changeAt = 3.0;
    const { events } = run(EVERY_MATRA, {
      untilSec: 20,
      layAt: (t) => (t < changeAt ? 120 : 240),
    });

    const stamps = events.map((e) => `${e.loopIndex}:${e.posMatras}`);
    expect(new Set(stamps).size).toBe(stamps.length);

    // No gap either: within the first cycle every matra index still shows up.
    const firstCycle = events.filter((e) => e.loopIndex === 0).map((e) => e.posMatras);
    expect(new Set(firstCycle).size).toBe(16);
  });

  it("never jumps backwards in time across the change", () => {
    const { events } = run(EVERY_MATRA, {
      untilSec: 20,
      layAt: (t) => (t < 3 ? 120 : t < 9 ? 300 : 60),
    });
    for (let i = 1; i < events.length; i++) {
      expect(events[i]!.whenSec).toBeGreaterThanOrEqual(events[i - 1]!.whenSec);
    }
  });

  it("spaces post-change events at the new lay", () => {
    const { events } = run(EVERY_MATRA, {
      untilSec: 30,
      layAt: (t) => (t < 3 ? 120 : 240),
    });
    // Well clear of the pivot, consecutive matras are 60/240 = 0.25s apart.
    const late = events.filter((e) => e.whenSec > 6);
    for (let i = 1; i < late.length; i++) {
      expect(late[i]!.whenSec - late[i - 1]!.whenSec).toBeCloseTo(0.25, 9);
    }
  });

  it("re-anchors only once per change, so repeated identical lays are free", () => {
    let state = createState(0, 120);
    state = schedule(EVERY_MATRA, 120, 0, 0.1, state).nextState;
    const anchored = schedule(EVERY_MATRA, 200, 0.1, 0.1, state).nextState;
    const again = schedule(EVERY_MATRA, 200, 0.2, 0.1, anchored).nextState;
    expect(again.anchorSec).toBe(anchored.anchorSec);
    expect(again.anchorMatra).toBe(anchored.anchorMatra);
  });

  it("rejects a non-positive lay rather than producing infinities", () => {
    const state = createState(0, 120);
    expect(() => schedule(EVERY_MATRA, 0, 0, 0.1, state)).toThrow(RangeError);
    expect(() => schedule(EVERY_MATRA, -1, 0, 0.1, state)).toThrow(RangeError);
  });
});

// -- round robin ------------------------------------------------------------

describe("round robin", () => {
  it("advances per stroke and survives across scheduler calls", () => {
    const p = pattern(Array.from({ length: 4 }, (_, i) => ev(i, 1, "na")));
    const { events } = run(p, { untilSec: 8 });
    const na = events.filter((e) => e.stroke === "na");
    expect(na.map((e) => e.rrIndex)).toEqual([0, 1, 2, 3]);
  });

  it("counts each stroke independently", () => {
    const { events } = run(FOUR_BEAT, { untilSec: 8 });
    expect(events.filter((e) => e.stroke === "na").map((e) => e.rrIndex)).toEqual([
      0, 1, 2,
    ]);
    expect(events.filter((e) => e.stroke === "ge").map((e) => e.rrIndex)).toEqual([0, 1]);
  });

  it("does not reset when a tick produces no events", () => {
    // Two matras apart at lay 120 is 1s, i.e. ten empty 100ms windows between
    // strokes. A counter living in the sampler would be back at 0 each time.
    const p = pattern([ev(0, 1, "na"), ev(2, 1, "na")]);
    const { events } = run(p, { untilSec: 16, tickSec: 0.025, windowSec: 0.1 });
    expect(events.map((e) => e.rrIndex)).toEqual([0, 1, 2, 3]);
  });

  it("advances the bol counter once per composite, not once per stroke", () => {
    // Each `dha` is two events; the dha round robin must step by one.
    const { events } = run(FOUR_BEAT, { untilSec: 24 });
    const dha = events.filter((e) => e.sourceBol === "dha");
    expect(dha).toHaveLength(6); // 3 cycles x 2 strokes
    expect(dha.map((e) => e.bolRrIndex)).toEqual([0, 0, 1, 1, 2, 2]);
  });

  it("gives the two strokes of one composite the same groupKey", () => {
    const { events } = run(FOUR_BEAT, { untilSec: 8 });
    const atSam = events.filter((e) => e.whenSec === 0);
    expect(atSam).toHaveLength(2);
    expect(atSam[0]!.groupKey).toBe(atSam[1]!.groupKey);
    expect(atSam[0]!.groupKey).not.toBe(
      events.find((e) => e.sourceBol === "dhin")!.groupKey,
    );
  });

  it("wraps at the sample count", () => {
    expect([0, 1, 2, 3, 4, 5].map((i) => rrPick(i, 3))).toEqual([0, 1, 2, 0, 1, 2]);
    expect(rrPick(7, 1)).toBe(0);
    expect(rrPick(7, 0)).toBe(0); // a stroke with no samples must not divide by zero
  });

  it("cycles samples for a repeated identical bol", () => {
    // The machine-gun case: sixteen `na` in a row must not all pick sample 0.
    const p = pattern(Array.from({ length: 16 }, (_, i) => ev(i, 1, "na")));
    const { events } = run(p, { untilSec: 8 });
    const picks = events.map((e) => rrPick(e.rrIndex, 3));
    expect(new Set(picks).size).toBe(3);
    expect(picks.slice(0, 6)).toEqual([0, 1, 2, 0, 1, 2]);
  });
});

// -- degenerate inputs ------------------------------------------------------

describe("degenerate inputs", () => {
  it("handles an empty pattern", () => {
    const p = pattern([]);
    const { events, state } = run(p, { untilSec: 10 });
    expect(events).toHaveLength(0);
    expect(state.cursorSec).toBeGreaterThan(9.9);
  });

  it("handles a single event, looping it forever", () => {
    const p = pattern([ev(0, 1, "na")]);
    const { events } = run(p, { untilSec: 40 });
    expect(events).toHaveLength(5); // 8s cycle, loops 0..4
    expect(events.map((e) => e.whenSec)).toEqual([0, 8, 16, 24, 32]);
  });

  it("emits an event at position 0 on the very first call", () => {
    const p = pattern([ev(0, 1, "na")]);
    const state = createState(0, 120);
    const r = schedule(p, 120, 0, 0.1, state);
    expect(r.events).toHaveLength(1);
    expect(r.events[0]!.whenSec).toBe(0);
  });

  it("emits an event at position 0 when playback starts at a non-zero clock", () => {
    // AudioContext.currentTime is never 0 in practice -- it is whatever the
    // context has been running for.
    const p = pattern([ev(0, 1, "na")]);
    const startSec = 1234.567;
    const state = createState(startSec, 120);
    const r = schedule(p, 120, startSec, 0.1, state);
    expect(r.events).toHaveLength(1);
    expect(r.events[0]!.whenSec).toBe(startSec);
  });

  it("returns nothing for a zero-length window", () => {
    const p = pattern([ev(0, 1, "na")]);
    const state = createState(0, 120);
    expect(schedule(p, 120, 0, 0, state).events).toHaveLength(0);
  });

  it("loops the whole pattern when avartans > 1, not one avartan", () => {
    // An event past matra 16 only exists because the pattern is two avartans
    // long. Looping on cycle_matras would fire it in the wrong cycle.
    const p = pattern([ev(0, 1, "na"), ev(20, 1, "te")], { avartans: 2 });
    const { events } = run(p, { untilSec: 40, tickSec: 0.25, windowSec: 0.5 });
    const te = events.filter((e) => e.stroke === "te");
    expect(te.map((e) => e.whenSec)).toEqual([10, 26]); // 20 matras, then +32
  });

  it("does not mutate the state it is given", () => {
    const state = createState(0, 120);
    const snapshot = JSON.stringify(state);
    schedule(EVERY_MATRA, 240, 0, 1.0, state);
    expect(JSON.stringify(state)).toBe(snapshot);
  });

  it("is deterministic: same inputs, same output", () => {
    const state = createState(0, 120);
    const a = schedule(FOUR_BEAT, 120, 0, 2.0, state);
    const b = schedule(FOUR_BEAT, 120, 0, 2.0, state);
    expect(a.events).toEqual(b.events);
    expect(a.nextState).toEqual(b.nextState);
  });
});
