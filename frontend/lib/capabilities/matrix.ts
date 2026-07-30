/**
 * Read-side view helpers over `GET /v1/capabilities` for the `/formats` explorer (MASTER_SPEC
 * Part 7 §2.7; slice M33-S1) — the `writableTargets`-adjacent companion in {@link ./types}.
 *
 * The explorer renders the Capability Matrix as a browsable grid: **rows are formats, columns are
 * canonical fields, cells are per-direction capability levels.** Everything here is derived from the
 * endpoint body alone — there is **no hard-coded format list and no hard-coded field list**. That is
 * the load-bearing rule of the page: the grid can never drift from the running instance's registry,
 * and an installed plugin format (a row the seven built-ins do not contain) appears with zero UI
 * changes — the P6 payoff on screen. These functions are pure and unit-tested so the components stay
 * thin presenters, exactly as `lib/preflight.ts` is to the file page.
 */

import { CUSTOM_CATEGORY_LABELS, PATH_LABELS, labelForPath } from "@/lib/mapping";
import type { CapabilitiesMap, CapabilityLevel, FormatCapabilities } from "./types";

/** One row of the matrix: a format and whichever of its read/write declarations exist. */
export interface FormatRow {
  format_id: string;
  format_name: string;
  read?: FormatCapabilities;
  write?: FormatCapabilities;
}

/** One column of the matrix: a canonical field path and its plain-language header label. */
export interface MatrixField {
  path: string;
  label: string;
}

/**
 * The formats, one row each, sorted by display name. A format present as a parser, an exporter, or
 * both is one row; the inner keys are whichever of `read`/`write` the registry declared. The name is
 * taken from whichever declaration exists (they agree), falling back to the id if neither carries one.
 */
export function formatRows(map: CapabilitiesMap): FormatRow[] {
  return Object.entries(map)
    .map(([format_id, byDirection]) => {
      const read = byDirection.read;
      const write = byDirection.write;
      return {
        format_id,
        format_name: read?.format_name ?? write?.format_name ?? format_id,
        read,
        write,
      };
    })
    .sort((a, b) => a.format_name.localeCompare(b.format_name));
}

// Canonical field order: the mapping table lists fixed paths in schema-category order (frame →
// atoms → cell → dynamics → electronic → trajectory → simulation → user_metadata), then the custom
// containers. Ordering the columns by this index keeps the grid's axis stable and readable across
// instances; anything the mapping table does not name sorts alphabetically after the known set.
const CANONICAL_FIELD_ORDER: readonly string[] = [
  ...Object.keys(PATH_LABELS),
  ...Object.keys(CUSTOM_CATEGORY_LABELS),
];

/**
 * The union of every field path declared by any format on either direction, as ordered columns.
 * Derived from the data, never hard-coded — a plugin that declares a field the built-ins never touch
 * simply adds a column.
 */
export function matrixFields(map: CapabilitiesMap): MatrixField[] {
  const paths = new Set<string>();
  for (const byDirection of Object.values(map)) {
    for (const caps of [byDirection.read, byDirection.write]) {
      if (caps) for (const path of Object.keys(caps.fields)) paths.add(path);
    }
  }
  return [...paths]
    .sort((a, b) => {
      const ia = CANONICAL_FIELD_ORDER.indexOf(a);
      const ib = CANONICAL_FIELD_ORDER.indexOf(b);
      // Both known → by canonical index; one known → it wins; neither → alphabetical.
      if (ia !== -1 && ib !== -1) return ia - ib;
      if (ia !== -1) return -1;
      if (ib !== -1) return 1;
      return a.localeCompare(b);
    })
    .map((path) => ({ path, label: fieldLabel(path) }));
}

/**
 * The capability level of one format-direction for one field. `null` means the format does **not
 * declare that direction at all** (a read-only or write-only format) — distinct from a declared
 * direction that simply omits the field, which reads as `"none"` ("the format cannot express it",
 * Part 3 §4.3, the same safe default the pre-flight applies).
 */
export function cellLevel(
  caps: FormatCapabilities | undefined,
  path: string,
): CapabilityLevel | null {
  if (!caps) return null;
  return caps.fields[path]?.level ?? "none";
}

/**
 * Column/field label. The mapping table's `labelForPath` names fixed leaf paths but not the bare
 * custom *containers* (`user_metadata.custom_per_atom`, which arrives without a `['key']` suffix in a
 * capability declaration), so those resolve through the category table first.
 */
export function fieldLabel(path: string): string {
  return CUSTOM_CATEGORY_LABELS[path]?.label ?? labelForPath(path).label;
}
