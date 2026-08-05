import { describe, expect, it } from "vitest";
import { bolLabels } from "./grid-labels";
import type { PatternEventJSON } from "./types";

const ev = (
  pos: [number, number],
  stroke: string,
  source_bol: string,
  bol_offset: number,
  variant = "",
): PatternEventJSON => ({ pos, stroke, velocity: 100, source_bol, bol_offset, variant });

describe("bolLabels", () => {
  it("prints a compound bol once, not once per stroke", () => {
    // tirakita is ONE word across FOUR positions. Keying on position alone
    // printed it four times -- the bug this test exists for.
    const labels = bolLabels([
      ev([0, 1], "te", "tirakita", 0),
      ev([1, 4], "re", "tirakita", 1),
      ev([1, 2], "ki", "tirakita", 2),
      ev([3, 4], "ta", "tirakita", 3),
    ]);
    expect([...labels.values()]).toEqual(["tirakita"]);
  });

  it("prints a composite bol once, not once per simultaneous stroke", () => {
    // dha is one word across two strokes at ONE position.
    const labels = bolLabels([
      ev([0, 1], "ge", "dha", 0),
      ev([0, 1], "na", "dha", 1),
    ]);
    expect(labels.get(0)).toBe("dha");
  });

  it("joins distinct bols that share a matra", () => {
    const labels = bolLabels([
      ev([0, 1], "ge", "dha", 0),
      ev([1, 2], "ge", "ge", 0),
    ]);
    expect(labels.get(0)).toBe("dha");
    expect(labels.get(0.5)).toBe("ge");
  });

  it("shows the variant so the grid reflects what was written", () => {
    const labels = bolLabels([ev([0, 1], "ta", "din", 0, "full")]);
    expect(labels.get(0)).toBe("din@full");
  });

  it("omits the variant suffix for the default realization", () => {
    const labels = bolLabels([ev([0, 1], "na", "din", 0, "")]);
    expect(labels.get(0)).toBe("din");
  });

  it("falls back to the stroke when there is no source_bol", () => {
    const labels = bolLabels([ev([0, 1], "ge", "", 0)]);
    expect(labels.get(0)).toBe("ge");
  });

  it("treats a missing bol_offset as the start of a bol", () => {
    const e = { pos: [0, 1], stroke: "ge", velocity: 100, source_bol: "ge" } as
      unknown as PatternEventJSON;
    expect(bolLabels([e]).get(0)).toBe("ge");
  });
});
