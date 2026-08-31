/**
 * The in-repo fuzzy matcher for the command palette (UI redesign S4, D246). **No dependency by
 * design** (the slice plan cuts fuzzy libraries: "a small in-repo implementation — no new
 * dependency"). It finds and scores subsequence matches with the ordering cues a jump-to-anything
 * palette needs: an exact substring and a matching word-start rank higher than scattered letters,
 * and among matches the earlier and more-contiguous wins. Small, deterministic, unit-tested.
 *
 * The matcher is a *score + index return*, not a `filter` — callers feed it a large list and sort
 * by score (or keep top-N), so the palette can include every candidate it knows and let the score
 * decide, with a zero score meaning "does not match".
 */
import { useMemo } from "react";

/** The match quality. Zero (falsy) means the candidate does not match at all. */
export type FuzzyScore = null | {
  score: number;
  /** Indices of the matched characters in `target` (already lower-cased per its own casing). */
  highlight: readonly number[];
};

/** Scoring weights — tuned for a command palette, pinned by `fuzzy.test.ts`. The load-bearing rule:
 *  an **exact substring** (every query char contiguous in the target) beats a scattered subsequence.
 *  Below that, match-at-start and a word start (after `.`/`-`/`_`/`/`/space, or a camelCase hump)
 *  are the ordering cues a jump-to-anything palette is expected to respect. */
const WEIGHTS = {
  /** Per matched character. */
  base: 1,
  /** The match begins at the very start of the target. */
  start: 2,
  /** A matched character that starts a word (separator or camelCase hump). */
  boundary: 2,
  /** Per adjacent matched pair within the longest contiguous run. */
  contiguous: 3,
  /** The whole query matched contiguously — an exact substring, the strongest signal. */
  substring: 12,
};

type Indexed = { ch: string; index: number; boundary: number };

function tokenize(target: string): Indexed[] {
  // Tokenize the *original-cased* target so a camelCase hump is still visible as one; matching
  // compares on the lower-cased char below.
  const low = target.toLowerCase();
  const out: Indexed[] = [];
  for (let i = 0; i < target.length; i += 1) {
    const raw = target[i];
    const prev = i > 0 ? target[i - 1] : null;
    // A word-start: the SEARCHABLE char that a separator, slash, or a camelCase hump precedes.
    const boundary =
      prev !== null && (prev === "." || prev === "-" || prev === "_" || prev === "/" || prev === " " || prev === "(")
        ? WEIGHTS.boundary
        : /[A-Z]/.test(raw) && prev !== null && /[a-z0-9]/.test(prev)
          ? WEIGHTS.boundary
          : 0;
    out.push({ ch: low[i], index: i, boundary });
  }
  return out;
}

/** The length of the longest contiguous run among sorted indices. */
function longestRun(indices: readonly number[]): number {
  let best = 1;
  let run = 1;
  for (let i = 1; i < indices.length; i += 1) {
    if (indices[i] === indices[i - 1] + 1) {
      run += 1;
      best = Math.max(best, run);
    } else {
      run = 1;
    }
  }
  return indices.length === 0 ? 0 : best;
}

/**
 * Return the match score + highlight indices for `query` as a (case-insensitive) subsequence of
 * `target`, or `null` when it does not match at all. The query's characters must appear in `target`
 * in order; beyond that, the score rewards contiguity, word starts, and a match at position zero.
 */
export function fuzzyMatch(query: string, target: string): FuzzyScore {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return { score: 0, highlight: [] };
  const t = target.toLowerCase();
  if (q.length > t.length) return null;

  const tokens = tokenize(target); // original casing, for camelCase hump detection
  let qi = 0;
  let base = 0;
  let boundaries = 0;
  let startBonus = 0;
  const highlight: number[] = [];
  // Greedy leftmost subsequence — simple, deterministic, and the *matching* decision never depends
  // on the scoring under it (a char either completes the query in order or it does not).
  for (let i = 0; i < tokens.length && qi < q.length; i += 1) {
    if (tokens[i].ch !== q[qi]) continue;
    base += WEIGHTS.base;
    if (tokens[i].index === 0) startBonus += WEIGHTS.start;
    boundaries += tokens[i].boundary;
    highlight.push(tokens[i].index);
    qi += 1;
  }
  if (qi < q.length) return null; // not all query chars found in order

  const run = longestRun(highlight);
  const runBonus = (run - 1) * WEIGHTS.contiguous;
  // An exact substring (every query char contiguous) gets the big bonus — the strongest match.
  const substringBonus = run === q.length ? WEIGHTS.substring : 0;
  const score = base + boundaries + startBonus + runBonus + substringBonus - t.length * 0.001;
  return { score, highlight };
}

/** A command-palette candidate: an id, a human label, and the string the matcher ranks on. */
export interface CommandCandidate<T> {
  id: string;
  /** The primary label shown in the palette. */
  label: string;
  /** The searchable text — usually the label, sometimes label + a category/shortcut hint. */
  search: string;
  /** Opaque payload the palette's handler receives when this candidate is chosen. */
  payload: T;
}

/** Rank `candidates` against `query`, best-first, keeping only non-zero scores. */
export function fuzzySearch<T>(
  query: string,
  candidates: readonly CommandCandidate<T>[],
): { candidate: CommandCandidate<T>; match: NonNullable<FuzzyScore> }[] {
  const scored: { candidate: CommandCandidate<T>; match: NonNullable<FuzzyScore> }[] = [];
  for (const candidate of candidates) {
    const match = fuzzyMatch(query, candidate.search);
    if (match && match.score > 0) {
      scored.push({ candidate, match });
    }
  }
  scored.sort((a, b) => b.match.score - a.match.score);
  return scored;
}

/** Sort a list of candidates import-stably / for React — a hook to memoize a ranked query. */
export function useFuzzySearch<T>(
  query: string,
  candidates: readonly CommandCandidate<T>[],
  limit?: number,
): { candidate: CommandCandidate<T>; match: NonNullable<FuzzyScore> }[] {
  return useMemo(() => {
    const ranked = fuzzySearch(query, candidates);
    return limit ? ranked.slice(0, limit) : ranked;
  }, [query, candidates, limit]);
}