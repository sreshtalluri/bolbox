/**
 * Display-side mirror of the v1 table in `bolbox/tal.py`.
 *
 * Only what the grid needs: how many matras, where the vibhag lines fall, which
 * vibhag is khali. The Python side stays authoritative -- adding a tal there
 * and forgetting it here degrades to an ungrouped row of cells rather than to a
 * wrong one, which is why `fallbackTal` exists.
 */

export interface Tal {
  readonly name: string;
  readonly matras: number;
  readonly vibhags: readonly number[];
  readonly khaliVibhags: readonly number[];
}

export const TINTAL: Tal = {
  name: "tintal",
  matras: 16,
  vibhags: [4, 4, 4, 4],
  khaliVibhags: [2],
};

export const TALS: Readonly<Record<string, Tal>> = { tintal: TINTAL };

export function getTal(name: string, cycleMatras: number): Tal {
  return TALS[name.trim().toLowerCase()] ?? fallbackTal(name, cycleMatras);
}

function fallbackTal(name: string, cycleMatras: number): Tal {
  return { name, matras: cycleMatras, vibhags: [cycleMatras], khaliVibhags: [] };
}

/** Matra index each vibhag begins on. The first is sam. */
export function vibhagStarts(tal: Tal): number[] {
  const starts: number[] = [];
  let running = 0;
  for (const width of tal.vibhags) {
    starts.push(running);
    running += width;
  }
  return starts;
}

export function khaliMatras(tal: Tal): Set<number> {
  const out = new Set<number>();
  const starts = vibhagStarts(tal);
  for (const index of tal.khaliVibhags) {
    const start = starts[index];
    const width = tal.vibhags[index];
    if (start === undefined || width === undefined) continue;
    for (let m = start; m < start + width; m++) out.add(m);
  }
  return out;
}
