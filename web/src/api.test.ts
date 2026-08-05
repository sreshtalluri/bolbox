import { describe, expect, it } from "vitest";

import { normaliseParseError } from "./api";

describe("parse error normalisation", () => {
  it("reads the exact payload bolbox/server.py sends", () => {
    // `_parse_error_payload`: a string `error` NEXT TO the position fields.
    // The bug worth a test: stopping at `error` because it is a string throws
    // away the line and column, which is the only part that saves any time.
    expect(
      normaliseParseError({
        error: "unknown bol 'dhaka'",
        line: 3,
        column: 12,
        text: "dha dhaka dhin dha",
      }),
    ).toEqual({
      message: "unknown bol 'dhaka'",
      line: 3,
      column: 12,
      excerpt: "dha dhaka dhin dha",
    });
  });

  it("reads a BolboxError, which carries no position", () => {
    expect(normaliseParseError({ error: "unknown tal 'jhaptal'" })).toEqual({
      message: "unknown tal 'jhaptal'",
    });
  });

  it("reads FastAPI's own nested detail", () => {
    expect(normaliseParseError({ detail: { message: "boom", line: 1 } })).toEqual({
      message: "boom",
      line: 1,
    });
    expect(normaliseParseError({ detail: "boom" })).toEqual({ message: "boom" });
  });

  it("returns null for a body with nothing to show", () => {
    expect(normaliseParseError(null)).toBeNull();
    expect(normaliseParseError({ ok: true })).toBeNull();
    // A 422 validation array from pydantic has no single message to render.
    expect(normaliseParseError({ detail: [{ loc: ["body"], msg: "field required" }] })).toBeNull();
  });

  it("ignores position fields of the wrong type instead of rendering NaN", () => {
    expect(normaliseParseError({ error: "boom", line: "3", column: null })).toEqual({
      message: "boom",
    });
  });
});
