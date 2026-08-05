/**
 * Kit loading: kit.json -> decoded, alias-resolved, cached voices.
 *
 * Mirrors the kit schema owned by `bolbox/kit.py`:
 *
 *   { schema_version: 1, name, description, sample_rate_policy,
 *     strokes:    { ge: { samples: [...], gain_db, pitch_semitones }
 *                 | { alias_of: "ka" } },
 *     composites: { dha: { samples: [...] } },
 *     midi_map:   { ge: 36 } }
 *
 * This reads the raw manifest that server.py mounts at /kits, so `alias_of`
 * still has to be followed here. (`Kit.to_dict()` in kit.py returns an
 * already-flattened table; if an endpoint ever serves that instead, the alias
 * resolution below becomes dead code rather than wrong code.) `schema_version`
 * is checked at load so a drift is a named error, not a kit that plays wrong.
 *
 * Unlike kit.py this does NOT enforce total stroke coverage. The Python loader
 * is the gate for that -- it can see data/strokes.yaml, and it refuses to load
 * an incomplete kit at all. Here, a stroke with no sample surfaces through
 * `PlanResult.missing` and into the UI, because a browser that refused to play
 * anything would be a worse way to find out.
 *
 * WHY A MISSING SAMPLE IS AN ERROR AND NOT A SHRUG
 *
 * bolbox/vocab.py makes the same argument about the stroke list: a kit missing
 * a stroke plays nothing, and silence reads as a sequencing bug rather than a
 * missing WAV. So every failure here names the stroke and the file, and a load
 * reports all of its broken samples at once rather than the first one.
 */

import { rrPick } from "./scheduler";

export const KIT_SCHEMA_VERSION = 1;

export interface KitVoiceJSON {
  readonly samples?: readonly string[];
  readonly gain_db?: number;
  readonly pitch_semitones?: number;
  readonly alias_of?: string;
}

export interface KitJSON {
  readonly schema_version: number;
  readonly name: string;
  readonly sample_rate_policy?: string;
  readonly strokes: Readonly<Record<string, KitVoiceJSON>>;
  readonly composites?: Readonly<Record<string, KitVoiceJSON>>;
  readonly midi_map?: Readonly<Record<string, number>>;
}

/** One playable voice: its round-robin samples plus its fixed adjustments. */
export interface Voice {
  readonly key: string;
  readonly buffers: readonly AudioBuffer[];
  /** Linear, converted from `gain_db`. */
  readonly gain: number;
  /** Converted from `pitch_semitones`; feeds AudioBufferSourceNode.playbackRate. */
  readonly playbackRate: number;
}

export class KitError extends Error {}

export class Kit {
  readonly id: string;
  readonly name: string;
  readonly schemaVersion: number;
  readonly sampleRatePolicy: string;
  readonly midiMap: Readonly<Record<string, number>>;
  /**
   * The rate the buffers were decoded at. Export has to render at this rate or
   * every sample gets resampled a second time and the file stops matching what
   * was heard.
   */
  readonly sampleRate: number;

  private readonly strokes: ReadonlyMap<string, Voice>;
  private readonly composites: ReadonlyMap<string, Voice>;

  constructor(init: {
    id: string;
    name: string;
    schemaVersion: number;
    sampleRatePolicy: string;
    midiMap: Record<string, number>;
    sampleRate: number;
    strokes: Map<string, Voice>;
    composites: Map<string, Voice>;
  }) {
    this.id = init.id;
    this.name = init.name;
    this.schemaVersion = init.schemaVersion;
    this.sampleRatePolicy = init.sampleRatePolicy;
    this.midiMap = init.midiMap;
    this.sampleRate = init.sampleRate;
    this.strokes = init.strokes;
    this.composites = init.composites;
  }

  get strokeNames(): string[] {
    return [...this.strokes.keys()];
  }

  get compositeNames(): string[] {
    return [...this.composites.keys()];
  }

  stroke(name: string): Voice | undefined {
    return this.strokes.get(name.toLowerCase());
  }

  /**
   * The single recorded sample for a spoken bol, if this kit has one.
   *
   * This is the reason `Event.source_bol` exists at all. By the time a `dha` is
   * two strokes the sampler cannot tell it was ever a `dha`, so it fires `ge`
   * and `na` separately and a real recorded `dha` -- the thing that makes a
   * tabla library sound credible -- can never play. Returning undefined here is
   * the normal case for a kit that only ships single strokes.
   */
  resolveComposite(sourceBol: string): Voice | undefined {
    if (!sourceBol) return undefined;
    return this.composites.get(sourceBol.toLowerCase());
  }

  /** Which buffer a round-robin counter selects for this voice. */
  sampleFor(voice: Voice, rrIndex: number): AudioBuffer | undefined {
    return voice.buffers[rrPick(rrIndex, voice.buffers.length)];
  }

  /** Longest sample in the kit. Export uses it to size the release tail. */
  get longestSampleSec(): number {
    let longest = 0;
    for (const v of [...this.strokes.values(), ...this.composites.values()]) {
      for (const b of v.buffers) if (b.duration > longest) longest = b.duration;
    }
    return longest;
  }
}

// -- conversions ------------------------------------------------------------

export function dbToGain(db: number): number {
  return Math.pow(10, db / 20);
}

export function semitonesToRate(semitones: number): number {
  return Math.pow(2, semitones / 12);
}

// -- alias resolution -------------------------------------------------------

const MAX_ALIAS_DEPTH = 8;

/**
 * Follow `alias_of` to the entry that actually owns samples.
 *
 * Chains are allowed (`ki -> ka -> ge`) because the lexicon already treats
 * spelling variants that way, but a cycle would hang the loader, so depth is
 * capped and the path is reported when it blows.
 */
function resolveAlias(
  table: Readonly<Record<string, KitVoiceJSON>>,
  name: string,
  where: string,
): { key: string; entry: KitVoiceJSON } {
  const path: string[] = [name];
  let key = name;
  for (let depth = 0; depth <= MAX_ALIAS_DEPTH; depth++) {
    const entry = table[key];
    if (!entry) {
      throw new KitError(
        `${where}: ${path.join(" -> ")} points at '${key}', which the kit does not define`,
      );
    }
    if (entry.alias_of === undefined) return { key, entry };
    key = entry.alias_of.toLowerCase();
    if (path.includes(key)) {
      throw new KitError(`${where}: alias cycle ${[...path, key].join(" -> ")}`);
    }
    path.push(key);
  }
  throw new KitError(`${where}: alias chain deeper than ${MAX_ALIAS_DEPTH}: ${path.join(" -> ")}`);
}

// -- loading ----------------------------------------------------------------

export interface LoadKitOptions {
  /** Directory holding `<id>/kit.json`. Default `/kits`. */
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly signal?: AbortSignal;
}

type DecodeTarget = Pick<BaseAudioContext, "decodeAudioData" | "sampleRate">;

/**
 * Decoded kits keyed by `id@sampleRate`.
 *
 * The rate is part of the key because `decodeAudioData` resamples to the
 * context it was called on. Handing a 48k-decoded buffer to a 44.1k context
 * would get it resampled a second time -- quietly, and audibly on transients,
 * which is the whole sound of a tabla.
 */
const CACHE_LIMIT = 4;
const cache = new Map<string, Promise<Kit>>();

export function clearKitCache(): void {
  cache.clear();
}

export function cachedKitKeys(): string[] {
  return [...cache.keys()];
}

export async function loadKit(
  id: string,
  ctx: DecodeTarget,
  options: LoadKitOptions = {},
): Promise<Kit> {
  const key = `${id}@${ctx.sampleRate}`;
  const hit = cache.get(key);
  if (hit) {
    // Re-insert to mark as most recently used.
    cache.delete(key);
    cache.set(key, hit);
    return hit;
  }

  const pending = fetchAndDecodeKit(id, ctx, options);
  cache.set(key, pending);
  // A failed load must not poison the cache, or the retry button does nothing.
  pending.catch(() => cache.delete(key));

  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next();
    if (oldest.done) break;
    cache.delete(oldest.value);
  }
  return pending;
}

async function fetchAndDecodeKit(
  id: string,
  ctx: DecodeTarget,
  options: LoadKitOptions,
): Promise<Kit> {
  const doFetch = options.fetchImpl ?? globalThis.fetch;
  const baseUrl = (options.baseUrl ?? "/kits").replace(/\/+$/, "");
  const kitDir = `${baseUrl}/${id}`;
  const manifestUrl = `${kitDir}/kit.json`;

  const res = await doFetch(manifestUrl, options.signal ? { signal: options.signal } : {});
  if (!res.ok) {
    throw new KitError(`kit '${id}': ${manifestUrl} returned ${res.status} ${res.statusText}`);
  }
  const raw: unknown = await res.json();
  const manifest = validateKitJSON(raw, manifestUrl);

  const urls = collectSampleUrls(manifest, kitDir);
  const buffers = await decodeAll(urls, ctx, doFetch, options.signal, id);

  return buildKit(id, manifest, buffers, ctx.sampleRate, kitDir);
}

export function validateKitJSON(raw: unknown, source: string): KitJSON {
  if (typeof raw !== "object" || raw === null) {
    throw new KitError(`${source}: expected an object at the top level`);
  }
  const k = raw as Partial<KitJSON>;
  if (k.schema_version !== KIT_SCHEMA_VERSION) {
    throw new KitError(
      `${source}: schema_version ${String(k.schema_version)}, this build reads ${KIT_SCHEMA_VERSION}`,
    );
  }
  if (typeof k.strokes !== "object" || k.strokes === null) {
    throw new KitError(`${source}: 'strokes' must be an object`);
  }
  return {
    schema_version: k.schema_version,
    name: typeof k.name === "string" ? k.name : source,
    sample_rate_policy: k.sample_rate_policy ?? "resample_on_load",
    strokes: k.strokes,
    composites: k.composites ?? {},
    midi_map: k.midi_map ?? {},
  };
}

function sampleUrl(dir: string, name: string): string {
  return /^(https?:)?\/\//.test(name) || name.startsWith("/") ? name : `${dir}/${name}`;
}

function collectSampleUrls(manifest: KitJSON, kitDir: string): string[] {
  const urls = new Set<string>();
  for (const table of [manifest.strokes, manifest.composites ?? {}]) {
    for (const entry of Object.values(table)) {
      for (const s of entry.samples ?? []) urls.add(sampleUrl(kitDir, s));
    }
  }
  // A Set, so a sample shared by two strokes is fetched and decoded once.
  return [...urls];
}

async function decodeAll(
  urls: string[],
  ctx: DecodeTarget,
  doFetch: typeof fetch,
  signal: AbortSignal | undefined,
  kitId: string,
): Promise<Map<string, AudioBuffer>> {
  type Outcome = { url: string; buffer?: AudioBuffer; error?: string };

  // Every sample in flight at once. Serial loading of a 60-sample kit over a
  // 40ms link is 2.4 seconds of nothing happening.
  const results = await Promise.all<Outcome>(
    urls.map(async (url) => {
      try {
        const res = await doFetch(url, signal ? { signal } : {});
        if (!res.ok) return { url, error: `${res.status} ${res.statusText}` };
        const bytes = await res.arrayBuffer();
        const buffer = await ctx.decodeAudioData(bytes);
        return { url, buffer };
      } catch (err) {
        return { url, error: err instanceof Error ? err.message : String(err) };
      }
    }),
  );

  const decoded = new Map<string, AudioBuffer>();
  const failures: string[] = [];
  for (const r of results) {
    if (r.buffer) decoded.set(r.url, r.buffer);
    else failures.push(`  ${r.url}: ${r.error}`);
  }
  if (failures.length > 0) {
    // All of them, not the first. Fixing one broken path per reload is the kind
    // of friction that makes people stop reloading.
    throw new KitError(
      `kit '${kitId}': ${failures.length} sample(s) failed to load:\n${failures.join("\n")}`,
    );
  }
  return decoded;
}

function buildVoices(
  table: Readonly<Record<string, KitVoiceJSON>>,
  decoded: Map<string, AudioBuffer>,
  kitDir: string,
  where: string,
): Map<string, Voice> {
  const out = new Map<string, Voice>();
  for (const name of Object.keys(table)) {
    const key = name.toLowerCase();
    const { key: targetKey, entry } = resolveAlias(table, key, where);
    const samples = entry.samples ?? [];
    if (samples.length === 0) {
      throw new KitError(`${where}: '${key}' resolves to '${targetKey}', which has no samples`);
    }
    const buffers: AudioBuffer[] = [];
    for (const s of samples) {
      const buf = decoded.get(sampleUrl(kitDir, s));
      if (!buf) throw new KitError(`${where}: '${key}' sample '${s}' was not decoded`);
      buffers.push(buf);
    }
    out.set(key, {
      key,
      buffers,
      gain: dbToGain(entry.gain_db ?? 0),
      playbackRate: semitonesToRate(entry.pitch_semitones ?? 0),
    });
  }
  return out;
}

function buildKit(
  id: string,
  manifest: KitJSON,
  decoded: Map<string, AudioBuffer>,
  sampleRate: number,
  kitDir: string,
): Kit {
  return new Kit({
    id,
    name: manifest.name,
    schemaVersion: manifest.schema_version,
    sampleRatePolicy: manifest.sample_rate_policy ?? "resample_on_load",
    midiMap: { ...(manifest.midi_map ?? {}) },
    sampleRate,
    strokes: buildVoices(manifest.strokes, decoded, kitDir, `kit '${id}' strokes`),
    composites: buildVoices(manifest.composites ?? {}, decoded, kitDir, `kit '${id}' composites`),
  });
}

// -- built-in placeholder ---------------------------------------------------

/**
 * A synthesized stand-in so the app is playable before anyone has recorded a
 * kit. It is not a tabla and is not trying to be -- it exists so that timing,
 * round robins, voice stealing and export can all be heard and tested against
 * something. Delete the picker entry once real WAVs exist.
 */
export function makeSynthKit(ctx: BaseAudioContext, id = "synth"): Kit {
  const spec: Record<string, { freq: number; decay: number; noise: number }> = {
    // bayan
    ge: { freq: 90, decay: 0.6, noise: 0.15 },
    ka: { freq: 110, decay: 0.09, noise: 0.5 },
    ki: { freq: 115, decay: 0.08, noise: 0.5 },
    // dayan
    na: { freq: 330, decay: 0.35, noise: 0.25 },
    ta: { freq: 330, decay: 0.35, noise: 0.25 },
    tin: { freq: 420, decay: 0.3, noise: 0.2 },
    tun: { freq: 260, decay: 0.5, noise: 0.15 },
    te: { freq: 480, decay: 0.06, noise: 0.7 },
    ti: { freq: 520, decay: 0.05, noise: 0.7 },
    re: { freq: 560, decay: 0.04, noise: 0.8 },
  };

  const strokes = new Map<string, Voice>();
  for (const [name, s] of Object.entries(spec)) {
    // Three variants per stroke, detuned and re-shaped, so a round robin has
    // something to actually round-robin over.
    const buffers = [0, 1, 2].map((v) =>
      renderHit(ctx, s.freq * (1 + (v - 1) * 0.02), s.decay * (1 + (v - 1) * 0.08), s.noise, v),
    );
    strokes.set(name, { key: name, buffers, gain: 1, playbackRate: 1 });
  }

  // ge + na struck together, as one sample -- the composite path needs
  // something to resolve or it is never exercised.
  const composites = new Map<string, Voice>();
  for (const [bol, parts] of Object.entries({
    dha: ["ge", "na"],
    dhin: ["ge", "tin"],
    dhun: ["ge", "tun"],
  })) {
    const buffers = [0, 1, 2].map((v) =>
      mixBuffers(
        ctx,
        parts.map((p) => strokes.get(p)!.buffers[v]!),
      ),
    );
    composites.set(bol, { key: bol, buffers, gain: 1, playbackRate: 1 });
  }

  return new Kit({
    id,
    name: "synth (built-in placeholder)",
    schemaVersion: KIT_SCHEMA_VERSION,
    sampleRatePolicy: "generated",
    midiMap: {},
    sampleRate: ctx.sampleRate,
    strokes,
    composites,
  });
}

function renderHit(
  ctx: BaseAudioContext,
  freq: number,
  decaySec: number,
  noiseAmount: number,
  seed: number,
): AudioBuffer {
  const rate = ctx.sampleRate;
  const length = Math.max(1, Math.ceil(rate * (decaySec + 0.02)));
  const buffer = ctx.createBuffer(1, length, rate);
  const data = buffer.getChannelData(0);
  // Deterministic noise: a fixed seed keeps export byte-identical to playback.
  let rng = 0x9e3779b9 ^ (seed * 0x85ebca6b);
  for (let i = 0; i < length; i++) {
    rng = (rng * 1664525 + 1013904223) >>> 0;
    const noise = (rng / 0xffffffff) * 2 - 1;
    const t = i / rate;
    const env = Math.exp(-t / (decaySec / 4));
    const attack = Math.min(1, t / 0.001);
    const tone = Math.sin(2 * Math.PI * freq * t) + 0.3 * Math.sin(4 * Math.PI * freq * t);
    data[i] = attack * env * (tone * (1 - noiseAmount) + noise * noiseAmount) * 0.6;
  }
  return buffer;
}

function mixBuffers(ctx: BaseAudioContext, parts: AudioBuffer[]): AudioBuffer {
  const length = Math.max(...parts.map((b) => b.length));
  const out = ctx.createBuffer(1, length, ctx.sampleRate);
  const data = out.getChannelData(0);
  for (const part of parts) {
    const src = part.getChannelData(0);
    for (let i = 0; i < src.length; i++) data[i] = (data[i] ?? 0) + (src[i] ?? 0) * 0.7;
  }
  return out;
}
