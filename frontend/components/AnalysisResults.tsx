/**
 * The generic renderer for one analysis plugin's results (MASTER_SPEC Part 7 §6; v1.8 M70).
 *
 * Analysis is a Secondary Goal that attaches at a defined seam (**P6**): the plugin writes a set of
 * `"<plugin>:"`-namespaced keys into the Canonical Object's `custom_global`, and the analyze job
 * hands them here verbatim. This component is a **view** of those keys, never a second schema and
 * never plugin-aware — it walks the map by *value type* alone, so a third-party plugin renders
 * through exactly the same path as the first-party composition one. There is deliberately **zero
 * branching on any key name or plugin name**; the day someone ships `rdf:` or `msd:`, this file does
 * not change.
 *
 * Two honesty rules carry over from the engine (P1, P3):
 *  1. **A `null` is rendered, not dropped.** A key the plugin computed to "absent" (a mass density it
 *     could not compute because the source declared no cell) shows as *not computed*, so a reader
 *     never mistakes "not shown" for "not measured".
 *  2. **The plain-language note travels with the run.** A plugin pairs a `null` value with a sibling
 *     `*_note`/`*_reason` key carrying the reason in words; that sibling renders as its own annotated
 *     row (the keys need not share a stem — composition's `density_note` sits far from
 *     `mass_density_g_per_cm3` — so pairing is by presence in the same result set, not by name).
 *
 * A `status: "error"` result is the analysis analogue of a refused conversion (D268): the plugin ran
 * and failed (escaped its namespace, returned an unserializable value, raised), the object was left
 * untouched, and the engine's own sentence names the plugin. It renders in the established error
 * styling, not as an empty panel.
 */

/** A JSON value as it arrives on the wire — the plugin returned only JSON-serializable values. */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface AnalysisResultsProps {
  /** The plugin's `name` namespace — used only to strip the `"<name>:"` prefix from labels. */
  pluginName: string;
  /** `"ok"` (the default when results are present) or `"error"` (a reported plugin failure). */
  status?: "ok" | "error";
  /**
   * The namespaced keys the plugin wrote, verbatim; `null`/absent on the error path. Typed with
   * `unknown` values because they arrive off the wire (the job envelope's `result` is untyped); the
   * plugin returned only JSON-serializable values, so each is treated as a {@link JsonValue}.
   */
  results?: Record<string, unknown> | null;
  /** The engine's failure sentence, present only when `status === "error"`. */
  message?: string | null;
}

/** A `*_note`/`*_reason` key is a plain-language annotation, rendered as prose rather than a value. */
function isAnnotationKey(key: string): boolean {
  return key.endsWith("_note") || key.endsWith("_reason");
}

/** Label for a row: drop the `"<plugin>:"` namespace, turn `_` into spaces; raw key kept in `title`. */
function humanizeKey(key: string, pluginName: string): string {
  const prefix = `${pluginName}:`;
  const bare = key.startsWith(prefix) ? key.slice(prefix.length) : key;
  return bare.replace(/_/g, " ");
}

/** One scalar value, rendered verbatim in a monospace cell. `null` is the honest "not computed". */
function ScalarValue({ value }: { value: string | number | boolean | null }) {
  if (value === null) {
    return <span className="text-sm italic text-muted">not computed</span>;
  }
  return <span className="font-mono text-sm text-strong">{String(value)}</span>;
}

/** A nested object → a compact key/value sub-table. Deterministic key order. */
function ObjectValue({ value }: { value: { [key: string]: JsonValue } }) {
  const entries = Object.entries(value);
  if (entries.length === 0) {
    return <span className="text-sm italic text-muted">empty</span>;
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-sm">
      {entries
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => (
          <div key={k} className="col-span-2 grid grid-cols-subgrid">
            <dt className="font-mono text-faint">{k}</dt>
            <dd className="font-mono text-strong break-all">{renderInline(v)}</dd>
          </div>
        ))}
    </dl>
  );
}

/** An array → an ordered list; primitives inline, nested structures as compact JSON. */
function ArrayValue({ value }: { value: JsonValue[] }) {
  if (value.length === 0) {
    return <span className="text-sm italic text-muted">empty</span>;
  }
  return (
    <ol className="space-y-0.5 font-mono text-sm text-strong">
      {value.map((item, i) => (
        <li key={i} className="break-all">
          {renderInline(item)}
        </li>
      ))}
    </ol>
  );
}

/** Inline rendering for a value nested inside an object/array cell — never a null-note row here. */
function renderInline(value: JsonValue): string {
  if (value === null) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Pick the right renderer for a top-level value by its JSON type. */
function ResultValue({ value }: { value: JsonValue }) {
  if (value === null || typeof value !== "object") {
    return <ScalarValue value={value} />;
  }
  if (Array.isArray(value)) {
    return <ArrayValue value={value} />;
  }
  return <ObjectValue value={value} />;
}

export function AnalysisResults({
  pluginName,
  status = "ok",
  results,
  message,
}: AnalysisResultsProps) {
  // Reported plugin failure — the honest reason, in the shared error styling (D268).
  if (status === "error") {
    return (
      <div
        role="alert"
        className="space-y-1 rounded-lg border border-cb-fail bg-cb-fail-bg p-4 text-sm text-strong"
      >
        <p className="font-medium">This analysis plugin reported a failure.</p>
        <p className="text-body">
          {message ?? "The plugin did not produce results and the file was left untouched."}
        </p>
      </div>
    );
  }

  const entries = Object.entries(results ?? {});
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted">
        This plugin ran and produced no results for this file.
      </p>
    );
  }

  // Deterministic order: annotations sort with everything else, so a *_note sits near its siblings.
  const sorted = entries.sort(([a], [b]) => a.localeCompare(b));

  return (
    <dl className="divide-y divide-line-soft rounded-lg border border-line">
      {sorted.map(([key, raw]) => {
        const value = raw as JsonValue;
        const annotation = isAnnotationKey(key) && typeof value === "string";
        return (
          <div
            key={key}
            title={key}
            className="grid grid-cols-1 gap-1 px-4 py-3 sm:grid-cols-[minmax(0,14rem)_1fr] sm:gap-4"
          >
            <dt className="text-sm font-medium text-body">{humanizeKey(key, pluginName)}</dt>
            <dd>
              {annotation ? (
                <span className="text-sm text-muted">{value}</span>
              ) : (
                <ResultValue value={value} />
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
