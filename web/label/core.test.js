import { describe, expect, it } from "vitest";
import {
  actionFor,
  applyCompletion,
  buildDictionary,
  complete,
  nextUnlabelled,
  queueOrder,
  wordAt,
} from "./core.js";

const vocab = {
  bols: [
    { name: "dha", strokes: ["ge", "na"], simultaneous: true, variants: [{ name: "", strokes: ["ge", "na"] }] },
    { name: "dhin", strokes: ["ge", "tin"], simultaneous: true, variants: [{ name: "", strokes: ["ge", "tin"] }] },
    { name: "din", strokes: ["na"], simultaneous: false, variants: [
      { name: "kinar", strokes: ["na"] }, { name: "full", strokes: ["ta"] },
    ] },
    { name: "ta", strokes: ["ta"], simultaneous: false, variants: [{ name: "", strokes: ["ta"] }] },
    { name: "tirakita", strokes: ["te", "re", "ki", "ta"], simultaneous: false, variants: [{ name: "", strokes: ["te", "re", "ki", "ta"] }] },
  ],
  surface_forms: ["tirakita", "tirkit", "dhin", "trkt", "dha", "din", "ta"],
};

describe("dictionary", () => {
  const dict = buildDictionary(vocab);
  it("has bols, non-default variants and aliases", () => {
    const texts = dict.map((e) => e.text);
    expect(texts).toContain("din@full");
    expect(texts).not.toContain("din@kinar");
    expect(dict.find((e) => e.text === "tirkit")?.kind).toBe("alias");
  });
  it("ranks canonical bols before variants and aliases, shortest first", () => {
    expect(complete(dict, "d").map((e) => e.text)).toEqual(["dha", "din", "dhin", "din@full"]);
    expect(complete(dict, "ti").map((e) => e.text)).toEqual(["tirakita", "tirkit"]);
  });
  it("ignores accents and does not offer what is already typed", () => {
    expect(complete(dict, "dh!").map((e) => e.text)).toEqual(["dha", "dhin"]);
    expect(complete(dict, "dha")).toEqual([]);
    expect(complete(dict, "")).toEqual([]);
  });
});

describe("editing", () => {
  it("finds the word under the cursor across bar lines and groups", () => {
    expect(wordAt("dha |dhi", 8)).toEqual({ start: 5, end: 8, word: "dhi" });
    expect(wordAt("{2, ti", 6).word).toBe("ti");
  });
  it("completes in place and adds exactly one space", () => {
    expect(applyCompletion("dha ti", 6, "tirakita")).toEqual({ value: "dha tirakita ", cursor: 13 });
    expect(applyCompletion("ti dha", 2, "tirakita")).toEqual({ value: "tirakita dha", cursor: 9 });
  });
});

describe("keys", () => {
  const k = (key, extra = {}) => ({ key, code: "", altKey: false, shiftKey: false, ...extra });
  it("never fires on plain typing", () => {
    for (const ch of "dha tirakita | - ! .") expect(actionFor(k(ch))).toBeNull();
  });
  it("maps the core loop", () => {
    expect(actionFor(k("Enter"))).toBe("saveNext");
    expect(actionFor(k("Enter", { shiftKey: true }))).toBeNull();
    expect(actionFor(k("Escape"))).toBe("replay");
    expect(actionFor(k("≈", { altKey: true, code: "KeyX" }))).toBe("skip");
    expect(actionFor(k("ArrowRight", { altKey: true, code: "ArrowRight" }))).toBe("next");
    expect(actionFor(k("ArrowDown", { altKey: true, code: "ArrowDown" }))).toBe("draftNext");
  });
  it("lets the completion list own Tab, arrows and Esc while open", () => {
    expect(actionFor(k("Tab"), { suggestionsOpen: true })).toBe("accept");
    expect(actionFor(k("Escape"), { suggestionsOpen: true })).toBe("closeSuggestions");
    expect(actionFor(k("Tab"))).toBeNull();
  });
});

describe("queue", () => {
  const r = (id, at, name, bols = "", skipped = false) => ({ id, recorded_at: at, source: { name }, bols, skipped });
  it("orders by recording time then file name", () => {
    const q = queueOrder([r("c", "2", "b"), r("a", "1", "z"), r("b", "2", "a")]);
    expect(q.map((x) => x.id)).toEqual(["a", "b", "c"]);
  });
  it("walks to the next unlabelled, non-skipped take", () => {
    const q = [r("a", "1", ""), r("b", "2", "", "dha"), r("c", "3", "", "", true), r("d", "4", "")];
    expect(nextUnlabelled(q, 0)).toBe(3);
    expect(nextUnlabelled(q, 3)).toBe(-1);
  });
});
