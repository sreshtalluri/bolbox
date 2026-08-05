/**
 * Client for `bolbox/server.py`.
 *
 *   POST /api/pattern  { text, lay? }  -> Pattern.to_dict()
 *   POST /api/midi     { text, lay? }  -> audio/midi bytes
 *   GET  /api/kits                     -> { kits: [name, ...] }
 *
 * A parse failure comes back as 422 with
 * `{ error, line, column, text }` (see `_parse_error_payload`). The normaliser
 * below accepts that plus the other shapes a FastAPI app can produce, because a
 * parse error that renders as "[object Object]" is worse than no error area at
 * all, and the exact wrapper is not worth coupling to.
 */

import { isPatternJSON, type ParseErrorJSON, type PatternJSON } from "./types";

export class ApiError extends Error {
  readonly parse: ParseErrorJSON | null;
  readonly status: number;

  constructor(message: string, status: number, parse: ParseErrorJSON | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.parse = parse;
  }
}

async function post(
  path: string,
  body: { text: string; lay?: number },
  signal?: AbortSignal,
): Promise<Response> {
  return fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
  });
}

/**
 * Parse deliberately sends no `lay`: the composition's own header owns the
 * tempo, and the slider adopts whatever comes back. Overriding here would mean
 * a file could never state its own lay once the slider had been touched.
 */
export async function parsePattern(text: string, signal?: AbortSignal): Promise<PatternJSON> {
  let res: Response;
  try {
    res = await post("/api/pattern", { text }, signal);
  } catch (err) {
    throw new ApiError(
      `could not reach /api/pattern (${err instanceof Error ? err.message : String(err)})`,
      0,
    );
  }

  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const parse = normaliseParseError(body);
    throw new ApiError(parse?.message ?? `/api/pattern returned ${res.status}`, res.status, parse);
  }
  if (!isPatternJSON(body)) {
    throw new ApiError("/api/pattern returned something that is not a Pattern", res.status);
  }
  return body;
}

/**
 * MIDI DOES send the lay, unlike parse: the file you download should be at the
 * tempo you were listening to, not the one the header happened to declare.
 */
export async function requestMidi(
  text: string,
  lay?: number,
  signal?: AbortSignal,
): Promise<Blob> {
  let res: Response;
  try {
    res = await post("/api/midi", lay !== undefined ? { text, lay } : { text }, signal);
  } catch (err) {
    throw new ApiError(
      `could not reach /api/midi (${err instanceof Error ? err.message : String(err)})`,
      0,
    );
  }
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    const parse = normaliseParseError(body);
    throw new ApiError(parse?.message ?? `/api/midi returned ${res.status}`, res.status, parse);
  }
  return res.blob();
}

/**
 * Pull `{message, line, column, excerpt}` out of whatever the server wrapped it in.
 *
 * server.py sends `{error: "...", line, column, text}` -- note that `error` is
 * a STRING sitting alongside the position fields, so reading `error` and
 * stopping there would throw away the line and column, which is the only part
 * of a parse error that saves you any time. FastAPI's own validation errors
 * nest under `detail` instead, hence the fallbacks.
 */
export function normaliseParseError(body: unknown): ParseErrorJSON | null {
  if (typeof body === "string") return { message: body };
  if (typeof body !== "object" || body === null) return null;

  const record = body as Record<string, unknown>;
  const nested = record["detail"];
  if (typeof nested === "object" && nested !== null && !Array.isArray(nested)) {
    return fromFlat(nested as Record<string, unknown>);
  }
  const flat = fromFlat(record);
  if (flat) return flat;
  if (typeof nested === "string") return { message: nested };
  return null;
}

function fromFlat(record: Record<string, unknown>): ParseErrorJSON | null {
  const message = record["error"] ?? record["message"] ?? record["msg"];
  if (typeof message !== "string") return null;
  const line = record["line"];
  const column = record["column"] ?? record["col"];
  // server.py calls the offending source line `text`.
  const excerpt = record["text"] ?? record["excerpt"] ?? record["source_line"];
  return {
    message,
    ...(typeof line === "number" ? { line } : {}),
    ...(typeof column === "number" ? { column } : {}),
    ...(typeof excerpt === "string" ? { excerpt } : {}),
  };
}

/** Kit ids the server can serve from its `kits/` directory. */
export async function listKits(signal?: AbortSignal): Promise<string[]> {
  const res = await fetch("/api/kits", signal ? { signal } : {});
  if (!res.ok) throw new ApiError(`/api/kits returned ${res.status}`, res.status);
  const body: unknown = await res.json();
  const listed = (body as { kits?: unknown })?.kits;
  if (!Array.isArray(listed)) return [];
  return listed.filter((k): k is string => typeof k === "string");
}

/** The bundled fixture, so the UI is usable with no server running. */
export async function loadSamplePattern(): Promise<PatternJSON> {
  const res = await fetch("/sample-pattern.json");
  if (!res.ok) throw new Error(`sample-pattern.json returned ${res.status}`);
  const body: unknown = await res.json();
  if (!isPatternJSON(body)) throw new Error("sample-pattern.json is not a Pattern");
  return body;
}
