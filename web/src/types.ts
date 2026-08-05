/**
 * The wire shape of `Pattern.to_dict()` in bolbox/pattern.py.
 *
 * Positions arrive as exact `[numerator, denominator]` integer pairs, never as
 * seconds. That is the whole point of the Python representation: seconds are
 * tempo-derived render data, so shipping them would make a lay change on this
 * side re-derive every event from an already-lossy number. The division happens
 * exactly once, in scheduler.ts.
 */

/** `[numerator, denominator]` matras from sam. */
export type RationalPos = readonly [number, number];

export interface PatternEventJSON {
  readonly pos: RationalPos;
  readonly stroke: string;
  readonly velocity: number;
  /**
   * The spoken syllable this stroke came from. Two events at one position with
   * the same `source_bol` are one composite bol (`dha` = ge + na struck
   * together); a kit with a recorded `dha` fires one sample for the pair.
   */
  readonly source_bol: string;
  /**
   * This stroke's index within the bol that produced it, so `0` starts a bol.
   * It is what separates one `tirakita` from four adjacent strokes -- a
   * distinction that matters here because `tirakita` shares a `source_bol`
   * across four DIFFERENT positions, and only same-position groups are
   * composites. Optional: older payloads predate the field.
   */
  readonly bol_offset?: number;
  /**
   * The physical realization chosen for `source_bol`, empty for the default.
   * Some bols can be struck more than one way (`din` full-handed vs one finger
   * on the edge) and are recited identically either way, so the choice cannot
   * come from the audio and travels here instead. Optional: older payloads
   * predate the field.
   */
  readonly variant?: string;
}

export interface PatternJSON {
  readonly tal: string;
  readonly cycle_matras: number;
  /** Matras per minute. NOT quarter-notes per minute. */
  readonly lay: number;
  readonly avartans: number;
  readonly title: string;
  readonly events: readonly PatternEventJSON[];
}

/** A parse failure from the Python side, positioned in the source text. */
export interface ParseErrorJSON {
  readonly message: string;
  readonly line?: number;
  readonly column?: number;
  readonly excerpt?: string;
}

export function isPatternJSON(value: unknown): value is PatternJSON {
  if (typeof value !== "object" || value === null) return false;
  const p = value as Partial<PatternJSON>;
  return (
    typeof p.tal === "string" &&
    typeof p.cycle_matras === "number" &&
    typeof p.lay === "number" &&
    Array.isArray(p.events)
  );
}
