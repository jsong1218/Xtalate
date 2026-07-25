import type { ErrorEnvelope } from "@/lib/report/types";
import type { Schemas } from "./client";

/**
 * The upload path to a file resource (MASTER_SPEC Part 6 §2.2, `POST /v1/upload`).
 *
 * This is the one `/v1` call the typed `openapi-fetch` client does **not** make: `fetch()` cannot
 * report upload progress, and Part 7 §2.4 forbids a fake progress bar — the UI shows real bytes-sent
 * or nothing. So the multipart POST goes through `XMLHttpRequest`, whose `upload.onprogress` gives
 * genuine progress events, and this module owns the two things that makes trustworthy: turning the
 * raw HTTP outcome into a typed result, and never inventing a code for a failure it did not receive.
 *
 * The success body is the generated `UploadResponse` (verbatim, no parallel DTO). Every non-2xx is
 * the single Part 6 §6 error envelope, rendered downstream by the one {@link ErrorEnvelope}
 * component — a failed upload shows the *server's* `code` unchanged. A failure with no server
 * response at all (network down, aborted) is synthesized into the same envelope shape with a
 * clearly client-side `request_id`, so the caller writes exactly one error branch either way.
 */

export type UploadResponse = Schemas["UploadResponse"];

/** Real upload progress from an `XMLHttpRequestUpload` `progress` event. */
export interface UploadProgress {
  loaded: number;
  total: number;
  /** `loaded / total`, or `null` when the total length is not computable. */
  fraction: number | null;
}

/** A completed upload: the stored file handle, or the error envelope to render. */
export type UploadResult =
  | { ok: true; data: UploadResponse }
  | { ok: false; error: ErrorEnvelope };

/**
 * Synthesize the Part 6 §6 envelope for a failure that never reached the server (network error,
 * abort, unreadable body). The `code` is a client-origin token — still shown verbatim, never
 * paraphrased — and `request_id` says plainly there is no server log to bridge to.
 */
export function clientErrorEnvelope(code: string, message: string): ErrorEnvelope {
  return {
    error: {
      code,
      message,
      details: {},
      request_id: "(client-side; no server response)",
      documentation_url: "",
    },
  };
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
 * Turn a raw HTTP status + response body into a typed {@link UploadResult}. Kept a pure function so
 * the envelope handling — the load-bearing "render the server's code verbatim, synthesize honestly
 * when there is none" rule — is unit-testable without a running server.
 *
 *  - 2xx (`201` per the contract): parse the `UploadResponse`; a success status with an unreadable
 *    body is itself a failure, surfaced as a client-side `MALFORMED_RESPONSE` rather than a silent
 *    half-success.
 *  - non-2xx: pass the server's `{ error: {...} }` envelope through **verbatim**; only when the body
 *    is not a recognizable envelope do we synthesize an `UPLOAD_FAILED` carrying the HTTP status.
 */
export function normalizeUploadOutcome(status: number, body: string): UploadResult {
  if (status >= 200 && status < 300) {
    try {
      const data = JSON.parse(body) as UploadResponse;
      if (data && typeof data.file_id === "string") return { ok: true, data };
    } catch {
      /* fall through to the malformed-body envelope */
    }
    return {
      ok: false,
      error: clientErrorEnvelope(
        "MALFORMED_RESPONSE",
        "The upload succeeded but the server returned an unreadable response body.",
      ),
    };
  }

  try {
    const parsed: unknown = JSON.parse(body);
    if (looksLikeEnvelope(parsed)) return { ok: false, error: parsed };
  } catch {
    /* fall through to the synthesized envelope */
  }
  return {
    ok: false,
    error: clientErrorEnvelope(
      "UPLOAD_FAILED",
      `The upload failed (HTTP ${status}) and the server did not return a recognizable error.`,
    ),
  };
}

/**
 * POST a file to `/v1/upload` as `multipart/form-data`, reporting real progress. Resolves (never
 * rejects) to a {@link UploadResult}: every outcome — success, server error, network error, abort —
 * is a value the caller renders, so there is no throw path to forget. `signal` cancels the transfer;
 * a cancelled upload resolves to a client-side `UPLOAD_CANCELLED` envelope.
 */
export function uploadFile(
  file: File,
  opts: { onProgress?: (progress: UploadProgress) => void; signal?: AbortSignal; url?: string } = {},
): Promise<UploadResult> {
  const { onProgress, signal, url = "/v1/upload" } = opts;

  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve({ ok: false, error: clientErrorEnvelope("UPLOAD_CANCELLED", "The upload was cancelled.") });
      return;
    }

    const form = new FormData();
    // The multipart field name matches `Body_upload_v1_upload_post.file` in the generated schema.
    form.append("file", file, file.name);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "text";

    xhr.upload.onprogress = (event) => {
      onProgress?.({
        loaded: event.loaded,
        total: event.total,
        fraction: event.lengthComputable && event.total > 0 ? event.loaded / event.total : null,
      });
    };
    xhr.onload = () => resolve(normalizeUploadOutcome(xhr.status, xhr.responseText));
    xhr.onerror = () =>
      resolve({
        ok: false,
        error: clientErrorEnvelope(
          "NETWORK_ERROR",
          "The upload could not reach the server. Check your connection and try again.",
        ),
      });
    xhr.onabort = () =>
      resolve({ ok: false, error: clientErrorEnvelope("UPLOAD_CANCELLED", "The upload was cancelled.") });

    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}
