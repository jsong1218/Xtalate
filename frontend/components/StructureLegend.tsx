"use client";

/**
 * StructureLegend (v1.6 M60-S2, MASTER_SPEC Part 7 §4/§6) — the color↔element legend beside the
 * structure viewer: one row per species present, pairing the swatch with the **element label as
 * text** — color is never the sole carrier (the icon+text a11y rule from `loss/icons.tsx`,
 * extended to the viewer chrome).
 *
 * The legend's element set is derived from the geometry's `species` (the same species the
 * endpoint returns), so completeness against the species present is a tested invariant — the
 * legend can never list an element the file does not have, or omit one it does.
 *
 * The swatch is the **exact** color Mol* renders: the viewer's `element-symbol` color theme
 * applied with its default params (saturation 0, lightness +0.2), computed through the same
 * molstar color helpers the theme itself uses — so the legend and the pixels cannot drift.
 */
import { ElementSymbolColors, elementSymbolColor } from "molstar/lib/mol-theme/color/element-symbol.js";
import { Color, getAdjustedColorMap } from "molstar/lib/mol-util/color/color.js";
import type { ElementSymbol } from "molstar/lib/mol-model/structure/model/types.js";

/** The render's exact element colors: the `element-symbol` theme defaults (saturation 0, lightness 0.2). */
const RENDERED_ELEMENT_COLORS = getAdjustedColorMap(ElementSymbolColors, 0, 0.2);

/**
 * The CSS color the viewer's `element-symbol` theme draws `element` as (unknown → theme default).
 * The theme keys its color table by Mol*'s normalized **uppercase** symbol (e.g. `NA`, `CL`), so
 * the mixed-case species strings the geometry endpoint returns are uppercased before lookup — the
 * legend and the pixels cannot drift.
 */
export function elementColor(element: string): string {
  return Color.toStyle(
    elementSymbolColor(
      RENDERED_ELEMENT_COLORS,
      element.toUpperCase() as ElementSymbol,
    ),
  );
}

export function StructureLegend({ species }: { species: string[] }) {
  // The endpoint's `species` is one symbol **per atom** (the loader's per-atom type symbols), so
  // the legend dedupes to the unique element set, preserving first-appearance order — one row per
  // element present, never one per atom (a 3-atom H2O lists O + H, not O, H, H).
  const elements = Array.from(new Set(species));
  if (elements.length === 0) return null;
  return (
    <div
      aria-label="Species legend"
      data-testid="structure-legend"
      className="flex flex-wrap gap-x-4 gap-y-1"
    >
      {elements.map((element) => (
        <span
          key={element}
          data-testid={`legend-row-${element}`}
          className="inline-flex items-center gap-1.5 text-xs text-muted"
        >
          {/* Decorative swatch; the element label beside it carries the meaning (never color alone). */}
          <span
            aria-hidden="true"
            data-testid="legend-swatch"
            className="inline-block h-3 w-3 shrink-0 rounded-full border border-line"
            style={{ backgroundColor: elementColor(element) }}
          />
          {element}
        </span>
      ))}
    </div>
  );
}
