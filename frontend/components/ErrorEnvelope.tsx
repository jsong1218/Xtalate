import type { ErrorEnvelope as ErrorEnvelopeModel } from "@/lib/report/types";

/**
 * The one component that renders a `/v1` error (MASTER_SPEC Part 6 §6). Every non-2xx response — a
 * bad upload, an unknown format, an expired output, a rate-limit — comes back in the single
 * `{ error: { code, message, details, request_id, documentation_url } }` envelope, and this is the
 * only place the UI turns one into pixels. Two rules make it trustworthy:
 *
 *  1. **Never paraphrase a code.** `error.code` is a stable machine string ("UNKNOWN_FORMAT",
 *     "FILE_TOO_LARGE", …) and is shown *verbatim* as a badge — a support thread, a doc page, and
 *     the screen all say the same token. The `message` is the human sentence beside it; we never
 *     substitute our own wording for the code.
 *  2. **Surface the request_id.** It is the caller's bridge to the server log for this exact
 *     response (Part 9 §6.1), so it is always shown, selectable, never buried.
 *
 * `details` is structured specifics (offending field, allowed values, size limits). It is rendered
 * as-is only when present; `{}` shows nothing rather than an empty box.
 */
export function ErrorEnvelope({ envelope }: { envelope: ErrorEnvelopeModel }) {
  const { code, message, details, request_id, documentation_url } = envelope.error;
  const detailEntries = Object.entries(details ?? {});

  return (
    <div
      role="alert"
      className="space-y-3 rounded-lg border border-cb-fail bg-cb-fail-bg p-4 text-sm text-slate-800"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          role="img"
          aria-label="Error"
          className="inline-flex h-[1.1em] w-[1.1em] items-center justify-center rounded-full bg-cb-fail text-[0.72em] font-bold leading-none text-white"
        >
          <span aria-hidden="true">✕</span>
        </span>
        {/* Verbatim machine code — the badge a reader can match to the docs and to a support thread. */}
        <code className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-xs font-semibold text-cb-fail">
          {code}
        </code>
        <span className="font-medium text-slate-900">{message}</span>
      </div>

      {detailEntries.length > 0 ? (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs text-slate-700">
          {detailEntries.map(([key, value]) => (
            <div key={key} className="col-span-2 grid grid-cols-subgrid">
              <dt className="font-mono text-slate-500">{key}</dt>
              <dd className="font-mono break-all">
                {typeof value === "string" ? value : JSON.stringify(value)}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}

      <p className="text-xs text-slate-500">
        Reference{" "}
        <code className="select-all font-mono text-slate-600">{request_id}</code>
        {documentation_url ? (
          <>
            {" · "}
            <a
              href={documentation_url}
              className="text-cb-fail underline underline-offset-2"
              target="_blank"
              rel="noreferrer"
            >
              {code} reference
            </a>
          </>
        ) : null}
      </p>
    </div>
  );
}
