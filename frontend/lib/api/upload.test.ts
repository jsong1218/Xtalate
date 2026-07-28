import { describe, expect, it } from "vitest";
import { clientErrorEnvelope, normalizeUploadOutcome } from "./upload";
import created from "./__fixtures__/upload.created.json";
import tooLarge from "@/components/__fixtures__/error.file_too_large.json";

/**
 * The upload outcome normalizer (MASTER_SPEC Part 6 §2.2 / §6). The load-bearing rule proven here:
 * a server error reaches the UI as the **server's own `code`, verbatim**, and only a failure with no
 * usable server body is synthesized — with a clearly client-side `request_id` so the two can never
 * be confused. Fixtures are the real wire shapes (`UploadResponse`, the §6 error envelope), never
 * hand-mocked.
 */
describe("normalizeUploadOutcome (Part 6 §2.2 / §6)", () => {
  it("parses a 201 body into the stored file handle", () => {
    const outcome = normalizeUploadOutcome(201, JSON.stringify(created));
    expect(outcome.ok).toBe(true);
    if (outcome.ok) {
      expect(outcome.data.file_id).toBe(created.file_id);
      expect(outcome.data.filename).toBe(created.filename);
    }
  });

  it("passes a non-2xx error envelope through verbatim — code never paraphrased", () => {
    const outcome = normalizeUploadOutcome(413, JSON.stringify(tooLarge));
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      // The server's stable machine code and its structured details survive unchanged.
      expect(outcome.error.error.code).toBe("FILE_TOO_LARGE");
      expect(outcome.error.error.details.limit_bytes).toBe(52428800);
      expect(outcome.error.error.request_id).toBe(tooLarge.error.request_id);
    }
  });

  it("treats a 2xx with an unreadable body as a client-side failure, not a half-success", () => {
    const outcome = normalizeUploadOutcome(201, "<!doctype html> not json");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) expect(outcome.error.error.code).toBe("MALFORMED_RESPONSE");
  });

  it("synthesizes an UPLOAD_FAILED envelope when a non-2xx body is not a recognizable envelope", () => {
    const outcome = normalizeUploadOutcome(502, "Bad Gateway");
    expect(outcome.ok).toBe(false);
    if (!outcome.ok) {
      expect(outcome.error.error.code).toBe("UPLOAD_FAILED");
      // A synthesized envelope is honest that no server log backs it.
      expect(outcome.error.error.request_id).toContain("client-side");
    }
  });

  it("marks a synthesized envelope as client-side, with no doc link to a non-existent code page", () => {
    const envelope = clientErrorEnvelope("NETWORK_ERROR", "unreachable");
    expect(envelope.error.code).toBe("NETWORK_ERROR");
    expect(envelope.error.documentation_url).toBe("");
    expect(envelope.error.details).toEqual({});
  });
});
