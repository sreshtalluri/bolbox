import { describe, expect, it } from "vitest";

import { VOICES_PER_STROKE, VoicePool, planNotes, renderEvents } from "./graph";
import { Kit, type Voice } from "./kit";
import { createState, schedule, type ScheduledEvent } from "./scheduler";
import type { PatternEventJSON, PatternJSON } from "./types";
import { encodeWav } from "./export";

// -- fakes ------------------------------------------------------------------
//
// WebAudio nodes, minus the audio. Enough surface for VoicePool and enough
// recording to assert on what it did.

interface ParamCall {
  readonly kind: "set" | "ramp" | "cancel";
  readonly value: number;
  readonly time: number;
}

class FakeParam {
  value = 1;
  readonly calls: ParamCall[] = [];
  setValueAtTime(value: number, time: number): void {
    this.calls.push({ kind: "set", value, time });
  }
  linearRampToValueAtTime(value: number, time: number): void {
    this.calls.push({ kind: "ramp", value, time });
  }
  cancelScheduledValues(time: number): void {
    this.calls.push({ kind: "cancel", value: 0, time });
  }
}

class FakeGain {
  readonly gain = new FakeParam();
  connect<T>(node: T): T {
    return node;
  }
}

class FakeSource {
  buffer: AudioBuffer | null = null;
  readonly playbackRate = { value: 1 };
  startedAt: number | null = null;
  stoppedAt: number | null = null;
  connect<T>(node: T): T {
    return node;
  }
  start(t: number): void {
    this.startedAt = t;
  }
  stop(t: number): void {
    this.stoppedAt = t;
  }
}

class FakeContext {
  readonly sampleRate = 48000;
  readonly destination = new FakeGain();
  readonly sources: FakeSource[] = [];
  readonly gains: FakeGain[] = [];
  createBufferSource(): FakeSource {
    const s = new FakeSource();
    this.sources.push(s);
    return s;
  }
  createGain(): FakeGain {
    const g = new FakeGain();
    this.gains.push(g);
    return g;
  }
}

const asCtx = (c: FakeContext): BaseAudioContext => c as unknown as BaseAudioContext;
const asDest = (c: FakeContext): AudioNode => c.destination as unknown as AudioNode;

function fakeBuffer(durationSec: number, tag: string): AudioBuffer {
  return { duration: durationSec, tag } as unknown as AudioBuffer;
}

function voice(key: string, sampleCount: number, durationSec = 0.4): Voice {
  return {
    key,
    buffers: Array.from({ length: sampleCount }, (_, i) => fakeBuffer(durationSec, `${key}-${i}`)),
    gain: 1,
    playbackRate: 1,
  };
}

function testKit(opts: { composites?: string[] } = {}): Kit {
  const strokes = new Map<string, Voice>([
    ["ge", voice("ge", 3)],
    ["na", voice("na", 3)],
    ["tin", voice("tin", 2)],
  ]);
  const composites = new Map<string, Voice>();
  for (const c of opts.composites ?? []) composites.set(c, voice(c, 3));
  return new Kit({
    id: "test",
    name: "test",
    schemaVersion: 1,
    sampleRatePolicy: "generated",
    midiMap: {},
    sampleRate: 48000,
    strokes,
    composites,
  });
}

function ev(
  num: number,
  stroke: string,
  sourceBol: string,
  over: Partial<ScheduledEvent> = {},
): ScheduledEvent {
  return {
    whenSec: num,
    stroke,
    velocity: 100,
    sourceBol,
    bolOffset: 0,
    rrIndex: 0,
    bolRrIndex: 0,
    groupKey: `g${num}:${sourceBol}`,
    loopIndex: 0,
    posMatras: num,
    ...over,
  };
}

// -- composites -------------------------------------------------------------

describe("composite resolution", () => {
  it("fires ONE sample for a dha when the kit has a composite", () => {
    const events = [ev(0, "ge", "dha"), ev(0, "na", "dha")];
    const { notes } = planNotes(events, testKit({ composites: ["dha"] }));
    expect(notes).toHaveLength(1);
    expect(notes[0]!.voiceKey).toBe("dha");
  });

  it("falls back to both strokes when the kit has no composite", () => {
    const events = [ev(0, "ge", "dha"), ev(0, "na", "dha")];
    const { notes } = planNotes(events, testKit());
    expect(notes.map((n) => n.voiceKey)).toEqual(["ge", "na"]);
  });

  it("takes the loudest constituent's velocity for the composite", () => {
    const events = [
      ev(0, "ge", "dha", { velocity: 120 }),
      ev(0, "na", "dha", { velocity: 60 }),
    ];
    const { notes } = planNotes(events, testKit({ composites: ["dha"] }));
    expect(notes[0]!.gain).toBeCloseTo(120 / 127, 9);
  });

  it("uses the bol round robin for a composite and the stroke one otherwise", () => {
    const kit = testKit({ composites: ["dha"] });
    const composite = planNotes(
      [ev(0, "ge", "dha", { bolRrIndex: 2, rrIndex: 99 }), ev(0, "na", "dha", { bolRrIndex: 2 })],
      kit,
    );
    expect((composite.notes[0]!.buffer as unknown as { tag: string }).tag).toBe("dha-2");

    const single = planNotes([ev(0, "na", "na", { rrIndex: 4 })], kit);
    // 4 % 3 = 1
    expect((single.notes[0]!.buffer as unknown as { tag: string }).tag).toBe("na-1");
  });

  it("does not fire a composite for a bol whose strokes are spread over time", () => {
    // `tirakita` is one word across four positions, not four strokes at one
    // instant. kit.py refuses to define such a composite, but the browser reads
    // the raw manifest, so a hand-written one must not play the word four times.
    const kit = testKit({ composites: ["tirakita"] });
    const spread = [0, 0.25, 0.5, 0.75].map((t, i) =>
      ev(t, ["ge", "na", "ge", "na"][i]!, "tirakita", {
        bolOffset: i,
        groupKey: `tk-${t}`,
      }),
    );
    const { notes } = planNotes(spread, kit);
    expect(notes.map((n) => n.voiceKey)).toEqual(["ge", "na", "ge", "na"]);
  });

  it("names strokes the kit cannot play instead of playing silence", () => {
    const { notes, missing } = planNotes([ev(0, "te", "te"), ev(1, "na", "na")], testKit());
    expect(notes).toHaveLength(1);
    expect(missing).toEqual(["te"]);
  });
});

// -- voice cap --------------------------------------------------------------

describe("voice cap", () => {
  function fireN(count: number, spacingSec: number): FakeContext {
    const ctx = new FakeContext();
    const pool = new VoicePool();
    const kit = testKit();
    const events = Array.from({ length: count }, (_, i) =>
      ev(i * spacingSec, "na", "na", { rrIndex: i, groupKey: `g${i}` }),
    );
    renderEvents(asCtx(ctx), asDest(ctx), events, kit, pool);
    return ctx;
  }

  it("lets four voices of one stroke overlap", () => {
    // 0.4s samples, 10ms apart: all four are still sounding.
    const ctx = fireN(VOICES_PER_STROKE, 0.01);
    expect(ctx.sources.every((s) => s.stoppedAt === null)).toBe(true);
  });

  it("steals the oldest voice on the fifth, with a 20ms release", () => {
    const ctx = fireN(VOICES_PER_STROKE + 1, 0.01);
    const oldest = ctx.sources[0]!;
    const fifthStart = 4 * 0.01;
    expect(oldest.stoppedAt).toBeCloseTo(fifthStart + 0.02, 9);

    // Ramped to zero rather than cut, or the steal would click.
    const ramp = ctx.gains[0]!.gain.calls.find((c) => c.kind === "ramp");
    expect(ramp?.value).toBe(0);
    expect(ramp?.time).toBeCloseTo(fifthStart + 0.02, 9);
    expect(ctx.sources.slice(1).every((s) => s.stoppedAt === null)).toBe(true);
  });

  it("does not steal when the earlier voice has already finished", () => {
    // 0.5s apart against 0.4s samples: nothing overlaps, so nothing is stolen.
    const ctx = fireN(8, 0.5);
    expect(ctx.sources.every((s) => s.stoppedAt === null)).toBe(true);
  });

  it("counts each stroke's voices separately", () => {
    const ctx = new FakeContext();
    const pool = new VoicePool();
    const events: ScheduledEvent[] = [];
    for (let i = 0; i < 4; i++) {
      events.push(ev(i * 0.01, "na", "na", { groupKey: `n${i}` }));
      events.push(ev(i * 0.01, "tin", "tin", { groupKey: `t${i}` }));
    }
    renderEvents(asCtx(ctx), asDest(ctx), events, testKit(), pool);
    expect(ctx.sources.every((s) => s.stoppedAt === null)).toBe(true);
  });
});

// -- the shared path --------------------------------------------------------

describe("export uses the same graph as playback", () => {
  const pattern: PatternJSON = {
    tal: "tintal",
    cycle_matras: 16,
    lay: 120,
    avartans: 1,
    title: "shared",
    events: ((): PatternEventJSON[] => {
      const out: PatternEventJSON[] = [];
      for (let m = 0; m < 16; m++) {
        // Dense enough to trigger voice stealing, so the comparison covers the
        // stateful part of the graph and not just the note times.
        out.push({ pos: [m, 1], stroke: "ge", velocity: 100, source_bol: "dha" });
        out.push({ pos: [m, 1], stroke: "na", velocity: 100, source_bol: "dha" });
        out.push({ pos: [m * 4 + 1, 4], stroke: "na", velocity: 80, source_bol: "na" });
        out.push({ pos: [m * 4 + 2, 4], stroke: "na", velocity: 80, source_bol: "na" });
        out.push({ pos: [m * 4 + 3, 4], stroke: "na", velocity: 80, source_bol: "na" });
      }
      return out;
    })(),
  };

  function timeline(ctx: FakeContext): string[] {
    return ctx.sources.map(
      (s, i) =>
        `${s.startedAt}|${s.stoppedAt}|${(s.buffer as unknown as { tag: string } | null)?.tag}|` +
        `${ctx.gains[i]!.gain.value}`,
    );
  }

  it("produces an identical node timeline from 100ms windows and from one call", () => {
    const kit = testKit({ composites: ["dha"] });
    const lay = 120;
    const bodySec = (16 * 60) / lay; // one cycle

    // Playback: 25ms ticks, 100ms lookahead, one pool across all of them.
    const live = new FakeContext();
    const livePool = new VoicePool();
    let state = createState(0, lay);
    for (let t = 0; t < bodySec; t += 0.025) {
      const w = Math.min(0.1, bodySec - t);
      const r = schedule(pattern, lay, t, w, state);
      state = r.nextState;
      renderEvents(asCtx(live), asDest(live), r.events, kit, livePool);
    }

    // Export: the whole span in one call, fresh pool. What export.ts does.
    const offline = new FakeContext();
    const { events } = schedule(pattern, lay, 0, bodySec, createState(0, lay));
    renderEvents(asCtx(offline), asDest(offline), events, kit, new VoicePool());

    expect(offline.sources.length).toBeGreaterThan(60);
    expect(timeline(offline)).toEqual(timeline(live));
  });
});

// -- wav encoding -----------------------------------------------------------

describe("wav encoder", () => {
  function buffer(channels: number, frames: number, sampleRate: number, fill: number): AudioBuffer {
    const data = Array.from({ length: channels }, () => new Float32Array(frames).fill(fill));
    return {
      numberOfChannels: channels,
      length: frames,
      sampleRate,
      duration: frames / sampleRate,
      getChannelData: (c: number) => data[c]!,
    } as unknown as AudioBuffer;
  }

  it("writes a 16-bit PCM header of the right size", () => {
    const wav = encodeWav(buffer(2, 100, 44100, 0));
    const view = new DataView(wav);
    const ascii = (o: number) =>
      String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(o + i)));

    expect(ascii(0)).toBe("RIFF");
    expect(ascii(8)).toBe("WAVE");
    expect(ascii(12)).toBe("fmt ");
    expect(ascii(36)).toBe("data");
    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(2); // channels
    expect(view.getUint32(24, true)).toBe(44100);
    expect(view.getUint16(34, true)).toBe(16); // bits
    expect(view.getUint32(40, true)).toBe(100 * 2 * 2);
    expect(wav.byteLength).toBe(44 + 100 * 2 * 2);
  });

  it("clamps rather than wrapping when a summed transient exceeds full scale", () => {
    // Wrapping 1.4 into int16 gives a full-scale NEGATIVE sample: a loud click
    // exactly where the music is loudest.
    const wav = encodeWav(buffer(1, 4, 48000, 1.4));
    const view = new DataView(wav);
    expect(view.getInt16(44, true)).toBe(32767);
  });

  it("round-trips a mid-scale sample", () => {
    const wav = encodeWav(buffer(1, 1, 48000, 0.5));
    expect(new DataView(wav).getInt16(44, true)).toBe(Math.round(0.5 * 32767));
  });
});
