import type { ErrorEnvelope } from "@/lib/report/types";
import { clientErrorEnvelope } from "./upload";

/**
 * Fetching the converted bytes — `GET /v1/download/{conversion_id}` (MASTER_SPEC Part 6 §4.3).
 *
 * Like {@link import("./upload").uploadFile}, this is not an `openapi-fetch` call: the response is a
 * *file stream*, not a JSON model, and the typed client is built for the latter. The bytes always
 * come through the API — there is no presigned URL — so this is a plain same-origin `fetch` whose
 * response is either the file or the one Part 6 §6 error envelope.
 *
 * The three refusals this endpoint can answer are the whole reason the download is a request the UI
 * makes rather than an `<a download>` the browser follows: a link would navigate away from the
 * record and drop the envelope on the floor, and the user would learn nothing.
 *
 *  - `404 CONVERSION_NOT_FOUND` — no such conversion.
 *  - `409 VALIDATION_ACK_REQUIRED` — validation **failed**; the caller must re-request with
 *    `?acknowledge_validation_failure=true` to take the unverified output. Rendered verbatim.
 *  - `410 OUTPUT_EXPIRED` — the bytes are gone but the record is not (reports-outlive-bytes); this
 *    is deliberately *not* a `404`, and the UI must not flatten it into one.
 */

/** The bytes, or the envelope to render — never a throw the caller can forget to catch. */
export type DownloadResult =
  | { ok: true; blob: Blob; filename: string }
  | { ok: false; error: ErrorEnvelope };

/**
 * The download URL for a conversion. Same-origin and `/v1`-prefixed, exactly like the typed client
 * (`lib/api/client.ts`). The acknowledgement is a **query parameter the caller opts into**, so the
 * unacknowledged request is the default and taking an unverified file is always a deliberate act.
 */
export function downloadUrl(conversionId: string, acknowledgeValidationFailure = false): string {
  const path = `/v1/download/${encodeURIComponent(conversionId)}`;
  return acknowledgeValidationFailure ? `${path}?acknowledge_validation_failure=true` : path;
}

function looksLikeEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code: unknown }).code === "string"
  );
}

/**
 * Fetch the converted output. Resolves (never rejects) to a {@link DownloadResult}.
 *
 * A non-2xx body is passed through **verbatim** — the server's `code`, `message`, `details` and
 * `request_id` unchanged — because those codes are the contract a user is meant to read. Only when
 * the body is not a recognizable envelope (a proxy's HTML error page, a dropped connection) is one
 * synthesized, and it says plainly that it is client-side.
 *
 * `fallbackFilename` is the record's `download.filename`; it is used only when the response carries
 * no `Content-Disposition` of its own, so the server's naming always wins.
 */
export async function downloadOutput(
  conversionId: string,
  opts: { acknowledgeValidationFailure?: boolean; fallbackFilename?: string } = {},
): Promise<DownloadResult> {
  const { acknowledgeValidationFailure = false, fallbackFilename = "output" } = opts;
  let response: Response;
  try {
    response = await fetch(downloadUrl(conversionId, acknowledgeValidationFailure));
  } catch {
    return {
      ok: false,
      error: clientErrorEnvelope(
        "NETWORK_ERROR",
        "The download could not reach the server. Check your connection and try again.",
      ),
    };
  }

  if (!response.ok) {
    try {
      const parsed: unknown = await response.json();
      if (looksLikeEnvelope(parsed)) return { ok: false, error: parsed };
    } catch {
      /* fall through to the synthesized envelope */
    }
    return {
      ok: false,
      error: clientErrorEnvelope(
        "DOWNLOAD_FAILED",
        `The download failed (HTTP ${response.status}) and the server did not return a recognizable error.`,
      ),
    };
  }

  const blob = await response.blob();
  return { ok: true, blob, filename: filenameFrom(response) ?? fallbackFilename };
}

/** The server's own `Content-Disposition` filename, if it sent one. */
export function filenameFrom(response: Response): string | null {
  const header = response.headers.get("content-disposition");
  if (!header) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Hand a fetched blob to the browser as a save. Isolated here so the panel stays a pure render and
 * the DOM poke has one home; the object URL is revoked immediately after the click.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
