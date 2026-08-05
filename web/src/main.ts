/**
 * UI wiring. Nothing here decides anything about timing or sound -- it moves
 * values between DOM elements, the Player, and the Python server.
 *
 * The page boots off the bundled `sample-pattern.json` so it is usable, and
 * testable, with no server running. Parsing real bol text needs `/api/pattern`,
 * and when that is not there the error area says so rather than the page
 * silently doing nothing.
 */

import { ApiError, listKits, loadSamplePattern, parsePattern, requestMidi } from "./api";
import { downloadBlob, renderPatternToWav, safeFilename } from "./export";
import { bolLabels } from "./grid-labels";
import { Kit, KitError, loadKit, makeSynthKit } from "./kit";
import { Player } from "./player";
import { getTal, khaliMatras, vibhagStarts } from "./tal";
import type { ParseErrorJSON, PatternJSON } from "./types";

const el = <T extends HTMLElement>(id: string): T => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`missing element #${id}`);
  return found as T;
};

const dom = {
  text: el<HTMLTextAreaElement>("bol-text"),
  parse: el<HTMLButtonElement>("parse"),
  loadSample: el<HTMLButtonElement>("load-sample"),
  status: el<HTMLElement>("status"),
  errors: el<HTMLElement>("errors"),
  title: el<HTMLElement>("pattern-title"),
  talDisplay: el<HTMLElement>("tal-display"),
  grid: el<HTMLElement>("grid"),
  lay: el<HTMLInputElement>("lay"),
  layValue: el<HTMLElement>("lay-value"),
  play: el<HTMLButtonElement>("play"),
  stop: el<HTMLButtonElement>("stop"),
  kit: el<HTMLSelectElement>("kit"),
  midi: el<HTMLButtonElement>("download-mid"),
  wav: el<HTMLButtonElement>("download-wav"),
};

const SYNTH_KIT_ID = "synth";

let pattern: PatternJSON | null = null;
let kit: Kit | null = null;
let ctx: AudioContext | null = null;
let player: Player | null = null;
let matraCells: HTMLElement[] = [];

// -- audio ------------------------------------------------------------------

/**
 * The context is created on first use, not at load.
 *
 * Browsers hand you a suspended context if there has been no user gesture, and
 * a suspended context's currentTime does not advance -- which would silently
 * anchor the very first schedule at a clock that never moves.
 */
function audio(): { ctx: AudioContext; player: Player } {
  if (!ctx || !player) {
    ctx = new AudioContext();
    player = new Player(ctx, {
      onMissingStrokes: (strokes) =>
        showError({
          message:
            `kit '${kit?.id ?? "?"}' has no sample for: ${strokes.join(", ")}. ` +
            "Those strokes are silent.",
        }),
      onError: (err) => {
        setPlaying(false);
        showError({ message: err.message });
      },
    });
  }
  return { ctx, player };
}

async function currentKit(): Promise<Kit> {
  const wanted = dom.kit.value || SYNTH_KIT_ID;
  if (kit && kit.id === wanted) return kit;

  const { ctx: audioCtx } = audio();
  kit = wanted === SYNTH_KIT_ID ? makeSynthKit(audioCtx) : await loadKit(wanted, audioCtx);
  audio().player.setKit(kit);
  return kit;
}

// -- rendering --------------------------------------------------------------

function showError(err: ParseErrorJSON): void {
  const where =
    err.line !== undefined
      ? `line ${err.line}${err.column !== undefined ? `, column ${err.column}` : ""}: `
      : "";
  dom.errors.innerHTML = "";
  const head = document.createElement("div");
  const marker = document.createElement("span");
  marker.className = "where";
  marker.textContent = where;
  head.append(marker, document.createTextNode(err.message));
  dom.errors.append(head);

  if (err.excerpt) {
    const pre = document.createElement("pre");
    // A caret under the offending column is worth more than the number itself.
    const caret = err.column !== undefined ? "\n" + " ".repeat(Math.max(0, err.column - 1)) + "^" : "";
    pre.textContent = err.excerpt + caret;
    dom.errors.append(pre);
  }
  dom.errors.classList.add("visible");
}

function clearError(): void {
  dom.errors.classList.remove("visible");
  dom.errors.textContent = "";
}

function setStatus(text: string): void {
  dom.status.textContent = text;
}

function renderPatternView(p: PatternJSON): void {
  dom.title.textContent = p.title;

  const tal = getTal(p.tal, p.cycle_matras);
  const khali = khaliMatras(tal);
  dom.talDisplay.innerHTML = "";
  dom.talDisplay.append(
    node("b", tal.name),
    document.createTextNode(
      ` — ${tal.matras} matras, vibhags ${tal.vibhags.join("+")}` +
        (tal.khaliVibhags.length ? `, khali on vibhag ${tal.khaliVibhags.map((v) => v + 1).join(", ")}` : "") +
        (p.avartans > 1 ? `, ${p.avartans} avartans` : ""),
    ),
  );

  const bols = bolLabels(p.events);

  dom.grid.innerHTML = "";
  matraCells = [];
  const starts = new Set(vibhagStarts(tal));
  let vibhag = document.createElement("div");
  vibhag.className = "vibhag";

  const span = tal.matras * Math.max(1, p.avartans);
  for (let m = 0; m < span; m++) {
    if (starts.has(m % tal.matras) && m > 0) {
      dom.grid.append(vibhag);
      vibhag = document.createElement("div");
      vibhag.className = "vibhag";
    }
    const cell = document.createElement("div");
    const inCycle = m % tal.matras;
    cell.className = "matra";
    if (inCycle === 0) cell.classList.add("sam");
    if (khali.has(inCycle)) cell.classList.add("khali");
    cell.dataset["matra"] = String(m);

    // Collect anything landing inside this matra, tuplets included.
    const parts: string[] = [];
    for (const [pos, label] of bols) {
      if (pos >= m && pos < m + 1) parts.push(label);
    }
    cell.append(document.createTextNode(parts.join("·") || "–"));
    const mark = document.createElement("span");
    mark.className = "mark";
    mark.textContent = inCycle === 0 ? "×" : khali.has(inCycle) ? "0" : String(inCycle + 1);
    cell.append(mark);

    vibhag.append(cell);
    matraCells.push(cell);
  }
  dom.grid.append(vibhag);
}

function node(tag: string, text: string): HTMLElement {
  const n = document.createElement(tag);
  n.textContent = text;
  return n;
}

function setPattern(p: PatternJSON): void {
  pattern = p;
  clearError();
  renderPatternView(p);
  setLay(p.lay);
  dom.lay.value = String(Math.round(p.lay));
  player?.setPattern(p);
}

// -- transport --------------------------------------------------------------

function setLay(lay: number): void {
  dom.layValue.textContent = `${lay} matras/min`;
  player?.setLay(lay);
}

function setPlaying(on: boolean): void {
  dom.play.disabled = on;
  dom.stop.disabled = !on;
  document.body.dataset["playing"] = on ? "true" : "false";
}

function highlightLoop(): void {
  requestAnimationFrame(highlightLoop);
  if (!player?.playing || matraCells.length === 0) return;
  const current = Math.floor(player.positionMatras);
  for (let i = 0; i < matraCells.length; i++) {
    matraCells[i]?.classList.toggle("on", i === current);
  }
}

// -- actions ----------------------------------------------------------------

async function doParse(): Promise<void> {
  setStatus("parsing…");
  try {
    const p = await parsePattern(dom.text.value);
    setPattern(p);
    setStatus(`${p.events.length} events`);
  } catch (err) {
    if (err instanceof ApiError) {
      showError(err.parse ?? { message: err.message });
      setStatus(err.status === 0 ? "server unreachable" : "parse failed");
    } else {
      showError({ message: err instanceof Error ? err.message : String(err) });
      setStatus("parse failed");
    }
  }
}

async function doPlay(): Promise<void> {
  if (!pattern) {
    // Silently doing nothing here reads as a broken button. It happens for real
    // when the last parse failed and there is nothing to play.
    showError({ message: "nothing to play — parse a composition or load the sample first" });
    return;
  }
  try {
    const loaded = await currentKit();
    const { player: p } = audio();
    p.setKit(loaded);
    p.setPattern(pattern);
    p.setLay(Number(dom.lay.value));
    await p.play();
    setPlaying(true);
    setStatus(`playing · ${loaded.name}`);
  } catch (err) {
    setPlaying(false);
    showError({ message: err instanceof Error ? err.message : String(err) });
  }
}

function doStop(): void {
  player?.stop();
  setPlaying(false);
  setStatus("stopped");
  for (const cell of matraCells) cell.classList.remove("on");
}

async function doDownloadWav(): Promise<void> {
  if (!pattern) return;
  dom.wav.disabled = true;
  setStatus("rendering .wav…");
  try {
    const loaded = await currentKit();
    const blob = await renderPatternToWav(pattern, Number(dom.lay.value), loaded, {
      repeats: 2,
    });
    downloadBlob(blob, `${safeFilename(pattern.title, "bolbox")}.wav`);
    setStatus(`wrote ${(blob.size / 1024).toFixed(0)} kB`);
  } catch (err) {
    showError({ message: err instanceof Error ? err.message : String(err) });
    setStatus("render failed");
  } finally {
    dom.wav.disabled = false;
  }
}

async function doDownloadMidi(): Promise<void> {
  setStatus("requesting .mid…");
  try {
    // MIDI is written by bolbox/midi.py, not here: it rounds to ticks at a PPQ
    // and emits two note-ons for a composite, which is a different rendering
    // decision from the one the sampler makes. Duplicating it in the browser
    // would mean two implementations of the same rounding.
    const blob = await requestMidi(dom.text.value, Number(dom.lay.value));
    downloadBlob(blob, `${safeFilename(pattern?.title ?? "", "bolbox")}.mid`);
    setStatus("wrote .mid");
  } catch (err) {
    if (err instanceof ApiError) showError(err.parse ?? { message: err.message });
    else showError({ message: err instanceof Error ? err.message : String(err) });
    setStatus("midi failed");
  }
}

// -- kits -------------------------------------------------------------------

async function populateKits(): Promise<void> {
  // Real kits first when the server is up, since the built-in is only a
  // stand-in; the built-in stays listed so the page is playable without one.
  const ids: string[] = [];
  try {
    for (const id of await listKits()) if (!ids.includes(id)) ids.push(id);
  } catch {
    // Server down, or no kits/ directory. Not worth an error banner -- the
    // picker simply has one entry.
  }
  ids.push(SYNTH_KIT_ID);

  dom.kit.innerHTML = "";
  for (const id of ids) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = id === SYNTH_KIT_ID ? "synth (built-in placeholder)" : id;
    dom.kit.append(option);
  }
  dom.kit.value = ids[0] ?? SYNTH_KIT_ID;
}

// -- boot -------------------------------------------------------------------

dom.parse.addEventListener("click", () => void doParse());
dom.loadSample.addEventListener("click", () => void boot());
dom.play.addEventListener("click", () => void doPlay());
dom.stop.addEventListener("click", doStop);
dom.wav.addEventListener("click", () => void doDownloadWav());
dom.midi.addEventListener("click", () => void doDownloadMidi());
dom.lay.addEventListener("input", () => setLay(Number(dom.lay.value)));
dom.kit.addEventListener("change", () => {
  kit = null;
  void currentKit().catch((err: unknown) => {
    showError({ message: err instanceof KitError ? err.message : String(err) });
  });
});

async function boot(): Promise<void> {
  document.body.dataset["ready"] = "false";
  await populateKits();
  try {
    setPattern(await loadSamplePattern());
    setStatus("bundled sample loaded — edit and press Parse");
  } catch (err) {
    showError({ message: err instanceof Error ? err.message : String(err) });
  }
  highlightLoop();
  // Boot is async, so `load` firing does not mean there is a pattern yet. This
  // is the flag anything driving the page should wait on.
  document.body.dataset["ready"] = "true";
}

void boot();

// Exposed for the E2E tests: they need to read the audio clock and the
// scheduler's position to assert that playback actually advanced, and there is
// no way to observe either from the DOM alone.
declare global {
  interface Window {
    bolbox: {
      readonly ctxTime: () => number;
      readonly playing: () => boolean;
      readonly positionMatras: () => number;
      readonly lay: () => number;
      readonly pattern: () => PatternJSON | null;
      readonly kit: () => {
        id: string;
        strokes: string[];
        composites: string[];
        sampleRate: number;
      } | null;
    };
  }
}
window.bolbox = {
  ctxTime: () => ctx?.currentTime ?? 0,
  playing: () => player?.playing ?? false,
  positionMatras: () => player?.positionMatras ?? 0,
  lay: () => player?.currentLay ?? Number(dom.lay.value),
  pattern: () => pattern,
  kit: () =>
    kit
      ? {
          id: kit.id,
          strokes: kit.strokeNames,
          composites: kit.compositeNames,
          sampleRate: kit.sampleRate,
        }
      : null,
};
