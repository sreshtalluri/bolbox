// The labeling page. Thin shell: state + DOM + WebAudio playback.
// Logic worth testing lives in core.js.

import {
  actionFor,
  applyCompletion,
  buildDictionary,
  complete,
  median,
  nextUnlabelled,
  queueOrder,
  wordAt,
} from "./core.js";

const $ = (id) => document.getElementById(id);
const els = {
  progress: $("progress"), empty: $("empty"), clipPanel: $("clip-panel"),
  clipName: $("clip-name"), clipMeta: $("clip-meta"), state: $("state"),
  start: $("start"), wave: $("wave"), waveWrap: $("wave-wrap"),
  onsetInfo: $("onset-info"), draftInfo: $("draft-info"), rateInfo: $("rate-info"),
  label: $("label"), suggest: $("suggest"), check: $("check"), timer: $("timer"),
  covSummary: $("cov-summary"), covUnits: $("cov-units"),
};

const state = {
  dictionary: [],
  queue: [],
  index: -1,
  buffer: null,
  pre: null,          // prelabel response
  draftIndex: 0,      // position in draftOptions()
  units: [],          // CTC units of the current label, for drawing
  valid: false,
  suggestions: [],
  selected: 0,
  source: null,
  startedAt: 0,       // ctx time when playback began
  offset: 0,          // clip position playback began at
  rate: 1,
  shownAt: 0,
  times: [],
  checkSeq: 0,
};

let ctx = null;
function audio() {
  if (!ctx) ctx = new AudioContext();
  return ctx;
}

async function api(path, init) {
  const res = await fetch(path, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.error || res.statusText), { body });
  return body;
}

// -- playback ------------------------------------------------------------

function stop() {
  if (state.source) {
    state.source.onended = null;
    try { state.source.stop(); } catch { /* already stopped */ }
    state.source = null;
  }
}

function playing() {
  return state.source !== null;
}

function position() {
  if (!playing()) return state.offset;
  return state.offset + (audio().currentTime - state.startedAt) * state.rate;
}

async function play(from = 0) {
  if (!state.buffer) return;
  const c = audio();
  if (c.state !== "running") {
    try { await c.resume(); } catch { /* needs a gesture */ }
  }
  if (c.state !== "running") {
    els.start.classList.add("visible");
    return;
  }
  els.start.classList.remove("visible");
  stop();
  const src = c.createBufferSource();
  src.buffer = state.buffer;
  src.playbackRate.value = state.rate;
  src.connect(c.destination);
  state.offset = Math.max(0, Math.min(from, state.buffer.duration));
  state.startedAt = c.currentTime;
  src.onended = () => {
    if (state.source === src) {
      state.source = null;
      state.offset = 0;
      draw();
    }
  };
  src.start(0, state.offset);
  state.source = src;
  requestAnimationFrame(tick);
}

function tick() {
  draw();
  if (playing()) requestAnimationFrame(tick);
}

// -- drawing -------------------------------------------------------------

function draw() {
  const canvas = els.wave;
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
  const h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const g = canvas.getContext("2d");
  g.clearRect(0, 0, w, h);
  g.fillStyle = "#100e0c";
  g.fillRect(0, 0, w, h);
  const buf = state.buffer;
  if (!buf) return;

  const top = 22 * dpr; // room for the bol names
  const mid = top + (h - top) / 2;
  const amp = (h - top) / 2 - 2 * dpr;
  const data = buf.getChannelData(0);
  const per = data.length / w;
  g.fillStyle = "#8c8377";
  for (let x = 0; x < w; x++) {
    let lo = 0;
    let hi = 0;
    const a = Math.floor(x * per);
    const b = Math.min(data.length, Math.floor((x + 1) * per) + 1);
    for (let i = a; i < b; i++) {
      const v = data[i];
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    g.fillRect(x, mid - hi * amp, 1, Math.max(1, (hi - lo) * amp));
  }

  const onsets = state.pre?.onsets ?? [];
  const toX = (t) => (t / buf.duration) * w;
  g.font = `${12 * dpr}px ui-monospace, Menlo, monospace`;
  g.textBaseline = "top";
  onsets.forEach((t, i) => {
    const x = toX(t);
    g.fillStyle = "#6f8fa8";
    g.fillRect(x, top, Math.max(1, dpr), h - top);
    const unit = state.units[i];
    if (unit) {
      g.fillStyle = "#ece5d8";
      g.fillText(unit, x + 2 * dpr, 4 * dpr);
    }
  });
  // Units with no onset to sit under: show them, flagged, at the right edge.
  const extra = state.units.slice(onsets.length);
  if (extra.length) {
    g.fillStyle = "#e06a5a";
    const text = `+${extra.length}: ${extra.join(" ")}`;
    const tw = g.measureText(text).width;
    g.textBaseline = "bottom";
    g.fillText(text, Math.max(0, w - tw - 4 * dpr), h - 4 * dpr);
  }

  const px = toX(position());
  g.fillStyle = "#d9a441";
  g.fillRect(px, 0, Math.max(1, 2 * dpr), h);
}

// -- label editing -------------------------------------------------------

function renderSuggestions() {
  els.suggest.innerHTML = "";
  state.suggestions.forEach((s, i) => {
    const li = document.createElement("li");
    li.textContent = s.text;
    if (s.detail || s.kind === "alias") {
      const small = document.createElement("small");
      small.textContent = s.kind === "alias" ? "alias" : s.detail;
      li.append(small);
    }
    if (i === state.selected) li.classList.add("sel");
    li.addEventListener("mousedown", (e) => {
      e.preventDefault();
      state.selected = i;
      accept();
    });
    els.suggest.append(li);
  });
}

function refreshSuggestions() {
  const { word } = wordAt(els.label.value, els.label.selectionStart);
  state.suggestions = complete(state.dictionary, word);
  state.selected = 0;
  renderSuggestions();
}

function accept() {
  const choice = state.suggestions[state.selected];
  if (!choice) return;
  const { value, cursor } = applyCompletion(els.label.value, els.label.selectionStart, choice.text);
  els.label.value = value;
  els.label.setSelectionRange(cursor, cursor);
  state.suggestions = [];
  renderSuggestions();
  validate();
}

let checkTimer = 0;
function validate() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(runCheck, 80);
}

async function runCheck() {
  const text = els.label.value;
  const seq = ++state.checkSeq;
  if (!text.trim()) {
    state.valid = false;
    state.units = [];
    els.label.className = "";
    els.check.className = "";
    els.check.textContent = "empty — type the bols, or Alt+↓ for a draft";
    draw();
    return;
  }
  const res = await api("/api/labels/check", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (seq !== state.checkSeq) return; // a newer keystroke already won
  state.valid = res.ok;
  els.label.className = res.ok ? "valid" : "invalid";
  if (!res.ok) {
    state.units = [];
    els.check.className = "bad";
    els.check.textContent = res.error;
  } else {
    state.units = res.units;
    const n = state.pre?.onset_count ?? 0;
    const d = res.units.length - n;
    // The detector under-counts compounds (bolbox.md: the /r/ flap has no
    // onset), so a small shortfall is expected, a surplus of onsets less so.
    const tol = Math.max(1, Math.round(res.units.length * 0.15));
    const agree = Math.abs(d) <= tol;
    els.check.className = agree ? "ok" : "bad";
    els.check.textContent =
      `${res.bols.length} bols → ${res.units.length} syllables; detector heard ${n}` +
      (agree ? " ✓" : ` — off by ${d > 0 ? "+" : ""}${d}, check the label`);
  }
  draw();
}

function setLabel(text) {
  els.label.value = text;
  const end = text.length;
  els.label.setSelectionRange(end, end);
  state.suggestions = [];
  renderSuggestions();
  validate();
}

function draftOptions() {
  const pre = state.pre;
  if (!pre) return [];
  const out = [];
  const seen = new Set();
  const add = (text, source) => {
    const key = text.split(/\s+/).join(" ").trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push({ text, source });
  };
  add(pre.draft, pre.draft_source);
  for (const c of pre.candidates) add(c.text, c.source);
  return out;
}

function cycleDraft(step) {
  const options = draftOptions();
  if (!options.length) return;
  state.draftIndex = (Math.max(0, state.draftIndex) + step + options.length) % options.length;
  const pick = options[state.draftIndex];
  setLabel(pick.text);
  els.draftInfo.textContent = `draft ${state.draftIndex + 1}/${options.length}: ${pick.source}`;
}

// -- navigation ----------------------------------------------------------

function current() {
  return state.queue[state.index];
}

function updateProgress() {
  const total = state.queue.length;
  const done = state.queue.filter((r) => r.bols.trim()).length;
  const skipped = state.queue.filter((r) => r.skipped).length;
  els.progress.textContent =
    `clip ${state.index + 1} / ${total} · ${done} labelled · ${total - done - skipped} to go` +
    (skipped ? ` · ${skipped} skipped` : "");
  const r = current();
  if (r) {
    els.state.textContent = r.skipped ? "skipped" : r.bols.trim() ? "labelled" : "unlabelled";
    els.state.className = "badge" + (r.bols.trim() || r.skipped ? "" : " warn");
  }
}

async function load(index) {
  if (index < 0 || index >= state.queue.length) return;
  stop();
  state.index = index;
  state.offset = 0;
  state.draftIndex = 0;
  const r = current();
  els.clipName.textContent = r.source?.name || r.id;
  els.clipMeta.textContent = `${r.duration_sec.toFixed(1)} s · ${r.sample_rate} Hz` + (r.speaker !== "self" ? ` · speaker ${r.speaker}` : "");
  updateProgress();

  const [buf, pre] = await Promise.all([
    fetch(`/api/recordings/${r.id}/file`).then((res) => res.arrayBuffer()).then((ab) => audio().decodeAudioData(ab)),
    api(`/api/recordings/${r.id}/prelabel`),
  ]);
  if (state.index !== index) return; // navigated away while loading
  state.buffer = buf;
  state.pre = pre;
  els.onsetInfo.textContent = `${pre.onset_count} syllable onsets detected`;
  const more = draftOptions().length - 1;
  els.draftInfo.textContent = pre.draft
    ? `draft: ${pre.draft_source}` + (more > 0 ? ` (Alt+↓ for ${more} more)` : "")
    : "no draft yet — type it";
  setLabel(pre.draft);
  els.label.focus();
  state.shownAt = performance.now();
  draw();
  play(0);
}

function advance() {
  const n = nextUnlabelled(state.queue, state.index);
  if (n >= 0) return load(n);
  if (state.index + 1 < state.queue.length) return load(state.index + 1);
  stop();
  els.check.className = "ok";
  els.check.textContent = "That was the last clip. Everything in the queue has a label or a skip.";
}

async function save() {
  const text = els.label.value.trim();
  if (!text) {
    els.check.className = "bad";
    els.check.textContent = "Nothing to save. Alt+X marks it a bad take; Alt+→ moves on without saving.";
    return;
  }
  clearTimeout(checkTimer);
  await runCheck();
  if (!state.valid) return;
  const r = current();
  try {
    const updated = await api(`/api/recordings/${r.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ bols: text, skipped: false }),
    });
    state.queue[state.index] = updated;
  } catch (err) {
    els.check.className = "bad";
    els.check.textContent = `not saved: ${err.message}`;
    return;
  }
  const secs = (performance.now() - state.shownAt) / 1000;
  state.times.push(secs);
  try { localStorage.setItem("bolbox.label.times", JSON.stringify(state.times.slice(-200))); } catch { /* private mode */ }
  showTimes(secs);
  refreshCoverage();
  advance();
}

function showTimes(last) {
  const m = median(state.times);
  els.timer.textContent =
    (last != null ? `last ${last.toFixed(1)} s · ` : "") +
    (m != null ? `median ${m.toFixed(1)} s over ${state.times.length}` : "");
}

async function skip() {
  const r = current();
  const updated = await api(`/api/recordings/${r.id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ skipped: true }),
  });
  state.queue[state.index] = updated;
  refreshCoverage();
  advance();
}

// -- coverage ------------------------------------------------------------

async function refreshCoverage() {
  const d = await api("/api/dataset");
  els.covSummary.textContent =
    `coverage: ${d.labelled} labelled (${d.labelled_minutes.toFixed(1)} min) of ${d.takes} takes · ` +
    `floors for a first CTC run: ${d.unit_floor} per syllable, ${d.compound_floor} per compound`;
  els.covUnits.innerHTML = "";
  const rows = [
    ...Object.entries(d.units).map(([k, v]) => [k, v, d.unit_floor]),
    ...Object.entries(d.compounds).map(([k, v]) => [k, v, d.compound_floor]),
  ];
  for (const [name, n, floor] of rows) {
    const row = document.createElement("div");
    row.className = "cov";
    const pct = Math.min(100, (100 * n) / floor);
    row.innerHTML = `<span></span><span class="bar"><i style="width:${pct}%"></i></span><span>${n}</span>`;
    row.firstChild.textContent = name;
    if (n >= floor) row.querySelector("i").classList.add("full");
    els.covUnits.append(row);
  }
}

// -- wiring --------------------------------------------------------------

function onKey(e) {
  const action = actionFor(e, { suggestionsOpen: state.suggestions.length > 0 });
  if (!action) return;
  e.preventDefault();
  switch (action) {
    case "accept": return accept();
    case "suggestNext":
      state.selected = (state.selected + 1) % state.suggestions.length;
      return renderSuggestions();
    case "suggestPrev":
      state.selected = (state.selected - 1 + state.suggestions.length) % state.suggestions.length;
      return renderSuggestions();
    case "closeSuggestions":
      state.suggestions = [];
      return renderSuggestions();
    case "saveNext": return save();
    case "replay": return play(0);
    case "togglePlay":
      if (playing()) {
        state.offset = position();
        stop();
        draw();
      } else {
        play(state.offset);
      }
      return;
    case "next": return load(state.index + 1);
    case "prev": return load(state.index - 1);
    case "skip": return skip();
    case "draftNext": return cycleDraft(1);
    case "draftPrev": return cycleDraft(-1);
    case "clear": return setLabel("");
    case "slower":
      state.rate = state.rate === 1 ? 0.7 : 1;
      els.rateInfo.textContent = state.rate === 1 ? "" : "playing at 0.7×";
      return play(0);
  }
}

async function init() {
  const [vocab, list] = await Promise.all([api("/api/vocabulary"), api("/api/recordings")]);
  state.dictionary = buildDictionary(vocab);
  state.queue = queueOrder(list.recordings);
  try {
    state.times = JSON.parse(localStorage.getItem("bolbox.label.times") || "[]");
  } catch { state.times = []; }
  showTimes(null);
  refreshCoverage();

  if (!state.queue.length) {
    els.empty.classList.add("visible");
    els.clipPanel.style.display = "none";
    document.body.dataset.ready = "true";
    return;
  }

  els.label.addEventListener("keydown", onKey);
  els.label.addEventListener("input", () => { refreshSuggestions(); validate(); });
  els.label.addEventListener("click", refreshSuggestions);
  document.addEventListener("keydown", (e) => { if (e.target !== els.label) onKey(e); });
  els.waveWrap.addEventListener("click", (e) => {
    if (!state.buffer) return;
    const rect = els.wave.getBoundingClientRect();
    play(((e.clientX - rect.left) / rect.width) * state.buffer.duration);
    els.label.focus();
  });
  els.start.addEventListener("click", () => { audio().resume().then(() => play(0)); els.label.focus(); });
  $("save").addEventListener("click", save);
  $("replay").addEventListener("click", () => { play(0); els.label.focus(); });
  $("skip").addEventListener("click", skip);
  $("prev").addEventListener("click", () => load(state.index - 1));
  $("next").addEventListener("click", () => load(state.index + 1));
  window.addEventListener("resize", draw);

  const first = state.queue.findIndex((r) => !r.bols.trim() && !r.skipped);
  await load(first >= 0 ? first : 0);
  document.body.dataset.ready = "true";
}

init().catch((err) => {
  els.check.className = "bad";
  els.check.textContent = `could not start: ${err.message}. Is \`python -m bolbox label\` running?`;
});
