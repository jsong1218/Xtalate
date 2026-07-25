import type { ConversionRecord } from "@/lib/report/types";

/**
 * The provenance strip on a conversion record (MASTER_SPEC Part 2 §3.7 Provenance, Part 7 §2.6).
 *
 * The identifying facts a collaborator needs to *cite* a conversion rather than describe it: which
 * bytes went in, when it ran, under which mode and tolerance profile, and the two report IDs. This
 * is what makes the page quotable in a methods section or a code review — "conversion `cnv_…`,
 * source sha256 `4f2a…`, permissive mode, `default` tolerances" — instead of "I converted it".
 *
 * Where each value comes from matters, because the record's own `source`/`target` are a *reduced*
 * projection: the service strips the hashes out of them (`routers/conversions.py::_endpoint`). The
 * full-precision facts are read off the **embedded** `conversion_report.source`, which keeps them,
 * and the tolerance profile off the Validation Report's self-contained `tolerance_profile` (Part 5
 * §4.2 — the report carries the profile in force so it stays re-thresholdable and auditable later).
 *
 * Nothing here is computed. A field the service did not send renders as an explicit em dash with a
 * reason, never as a blank cell or an invented default — an unknown hash must not look like no hash.
 */

/** The first 12 hex characters — enough to cite, with the full digest in `title` and on the clipboard. */
export function shortHash(sha256: string): string {
  return sha256.slice(0, 12);
}

function Field({
  label,
  children,
  title,
}: {
  label: string;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-800" title={title}>
        {children}
      </dd>
    </div>
  );
}

/** A value the service did not send — said plainly, so absence never reads as a value (P3). */
function Unknown({ reason }: { reason: string }) {
  return (
    <span className="text-slate-500">
      <span aria-hidden="true">—</span> <span className="text-xs">{reason}</span>
    </span>
  );
}

function Timestamp({ iso }: { iso: string }) {
  const date = new Date(iso);
  return (
    <time dateTime={iso} title={iso}>
      {Number.isNaN(date.getTime()) ? iso : date.toLocaleString()}
    </time>
  );
}

export function Provenance({ record }: { record: ConversionRecord }) {
  const report = record.conversion_report;
  const sha256 = typeof report.source.sha256 === "string" ? report.source.sha256 : null;
  const schemaVersion =
    typeof report.source.schema_version === "string" ? report.source.schema_version : null;
  const validation = record.validation_report;
  const profileName = validation?.tolerance_profile?.name;

  return (
    <section
      aria-label="Provenance"
      data-testid="provenance"
      className="rounded-lg border border-slate-200 bg-slate-50 p-4"
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
        <Field label="Conversion">
          <span className="font-mono text-xs">{record.conversion_id}</span>
        </Field>

        <Field label="Source sha256" title={sha256 ?? undefined}>
          {sha256 ? (
            <span className="font-mono text-xs">{shortHash(sha256)}…</span>
          ) : (
            <Unknown reason="not recorded" />
          )}
        </Field>

        <Field label="Converted">
          <Timestamp iso={record.created_at} />
        </Field>

        <Field label="Mode">
          <span className="rounded bg-white px-1.5 py-0.5 text-xs text-slate-700">
            {report.mode}
          </span>
        </Field>

        <Field label="Tolerance profile">
          {typeof profileName === "string" ? (
            <span className="font-mono text-xs">{profileName}</span>
          ) : validation === null ? (
            <Unknown reason="no validation ran" />
          ) : (
            <Unknown reason="not recorded" />
          )}
        </Field>

        <Field label="Canonical schema">
          {schemaVersion ? (
            <span className="font-mono text-xs">{schemaVersion}</span>
          ) : (
            <Unknown reason="not recorded" />
          )}
        </Field>

        <Field label="Conversion report">
          <span className="font-mono text-xs">{report.report_id}</span>
        </Field>

        <Field label="Validation report">
          {validation ? (
            <span className="font-mono text-xs">{validation.report_id}</span>
          ) : (
            <Unknown reason="none" />
          )}
        </Field>
      </dl>
    </section>
  );
}
