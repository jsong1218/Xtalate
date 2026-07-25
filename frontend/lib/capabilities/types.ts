/**
 * Frontend capability models — one format's read/write declaration, mirrored verbatim (MASTER_SPEC
 * Part 3 §4.1; `src/xtalate/sdk/capabilities.py`).
 *
 * `GET /v1/capabilities` embeds the library's pydantic `FormatCapabilities` verbatim — one
 * `model_dump(mode="json")` per `(format_id, direction)` — but the OpenAPI schema types the body as
 * opaque `{ [format_id]: { [direction]: unknown } }` (`lib/api/schema.d.ts`). These interfaces
 * re-declare the exact same shape so the target picker and the pre-flight preview have real types.
 * Every field name and literal matches the Python model; if it changes, this file changes with it.
 *
 * The client reads these declarations only to *predict* preservation before conversion (**P5**); it
 * never computes a conversion (Part 7 §2, the faithful presentation layer). The one derived value it
 * takes from here is the pre-flight preview (`lib/preflight.ts`), a capability lookup — not physics.
 *
 * Note on `fields`: the service returns wildcard keys (`"simulation.*"`) already **expanded** to
 * concrete canonical leaf paths (the registry expands at declaration time,
 * `xtalate.capabilities.registry`), so a client lookup is a plain `fields[path]` with no wildcard
 * matching. An undeclared path reads as {@link CapabilityLevel.NONE} — "the format cannot express
 * it" is the safe default (Part 3 §4.3), and the preview applies that same default.
 */

/** How fully a format can express one canonical field — Part 3 §4.1 `CapabilityLevel`. */
export type CapabilityLevel = "full" | "partial" | "none";

/** One field's capability — Part 3 §4.1 `FieldCapability`. */
export interface FieldCapability {
  level: CapabilityLevel;
  /** Human-readable condition, surfaced verbatim in report / pre-flight "Reason" text. */
  notes: string | null;
}

/** One format's read- or write-side declaration — Part 3 §4.1 `FormatCapabilities`. */
export interface FormatCapabilities {
  format_id: string;
  format_name: string;
  direction: "read" | "write";
  /** Keyed by canonical field path (Part 2 §3), wildcards already expanded to leaf paths. */
  fields: Record<string, FieldCapability>;
  /** `null` = unlimited; `1` = single-structure format. */
  max_frames: number | null;
  /** Canonical paths that MUST be present to write this format (write side); drives Recovery. */
  required_fields: string[];
  allows_open_boundaries: boolean;
  representable_constraint_kinds: string[];
  writable_custom_keys: Record<string, string[]>;
  writable_custom_key_pattern: Record<string, string>;
  native_coordinate_system: "cartesian" | "fractional" | "both";
  lossy_notes: string[];
  numeric_precision: Record<string, number | null>;
}

/**
 * The whole `GET /v1/capabilities` body: `{ format_id: { direction: FormatCapabilities } }` — the
 * CLI's exact `capabilities --json` shape (`backend/routers/capabilities.py`). A format present as a
 * parser, an exporter, or both appears once; the inner keys are whichever of `"read"`/`"write"` are
 * declared.
 */
export type CapabilitiesMap = Record<string, Partial<Record<"read" | "write", FormatCapabilities>>>;

/**
 * The formats a caller can convert *to*, newest declaration wins — every format whose map entry
 * carries a `write` declaration, as `FormatCapabilities` objects. The target picker renders exactly
 * these; a read-only format (none in Phase 1, but a plugin could add one) never appears as a target.
 */
export function writableTargets(map: CapabilitiesMap): FormatCapabilities[] {
  return Object.values(map)
    .map((byDirection) => byDirection.write)
    .filter((caps): caps is FormatCapabilities => caps !== undefined)
    .sort((a, b) => a.format_name.localeCompare(b.format_name));
}
