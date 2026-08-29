"""The authoritative catalog of error-envelope codes, and its committed artifact (M34-S1).

Every non-2xx response the service produces carries a stable machine ``code`` and a
``documentation_url`` of the form ``{docs_base_url}#{code.lower()}`` (Part 6 §6). The Web UI renders
that URL as a link, so from M34 on every code must have a resolvable reference section anchored at
``code.lower()`` — enforced two ways:

* the frontend link-check reads :data:`ARTIFACT_PATH` and asserts ``docs/errors.md`` has a section
  per code (the docs analogue of the plain-language mapping-coverage lint), and
* :mod:`tests.backend.test_error_codes_artifact` asserts this registry equals the set of codes the
  backend source actually raises — so it cannot silently fall behind a new error path.

This module is the single source of truth for *which codes exist*; ``docs/errors.md`` is the human
prose for *what each means*, and the lint binds the two. The exporter mirrors
:mod:`backend.vocabulary` / :mod:`backend.openapi` exactly (sorted keys, 2-space indent, a trailing
newline) so two machines produce byte-identical output. Nothing here contains scientific logic.

Run ``python -m backend.error_codes`` to regenerate :data:`ARTIFACT_PATH` after adding or removing a
code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The committed artifact the frontend link-check reads. Kept beside the human docs and
#: ``openapi.json``/``vocabulary.json`` — the machine-readable contracts the UI checks against.
ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "docs" / "error_codes.json"


@dataclass(frozen=True)
class ErrorCodeSpec:
    """One error code: its stable string, a representative HTTP status, and a one-line summary.

    ``http_status`` is the status a caller most often sees the code under; ``None`` marks a code
    that is recorded on a *job* body (a failed or refused conversion is still an HTTP 200 job —
    Part 6 preamble) or whose transport status varies. The reference page states the nuance in text.
    """

    code: str
    http_status: int | None
    summary: str


#: Every code the error envelope can carry. The completeness test binds this to the raise sites in
#: ``backend/``; keep it in lockstep with them. Ordering here is by concern for readability — the
#: exporter sorts by code, so the artifact is deterministic regardless.
ERROR_CODES: tuple[ErrorCodeSpec, ...] = (
    # --- Request shape and routing -------------------------------------------------------------
    ErrorCodeSpec(
        "MALFORMED_REQUEST",
        400,
        "The request body or parameters failed validation (a missing field, a wrong type, an "
        "unparseable body). `details.errors` lists each field-level failure.",
    ),
    ErrorCodeSpec(
        "INVALID_CURSOR",
        422,
        "The `cursor` passed to a paginated listing is not one this service issued. Start from the "
        "first page and follow `next_cursor` values only.",
    ),
    ErrorCodeSpec(
        "INVALID_FRAME_RANGE",
        400,
        "The `frames` parameter on a geometry endpoint is not a well-formed half-open `start:end` "
        "range of non-negative integers (or it is empty/reversed). Geometry serves 0-based frame "
        "windows only (Part 6 §7).",
    ),
    ErrorCodeSpec(
        "EMPTY_BATCH",
        422,
        "A batch_convert submission named no files. A batch must list at least one `file_id` to "
        "fan out to.",
    ),
    ErrorCodeSpec(
        "BATCH_TOO_LARGE",
        422,
        "A batch_convert submission named more `file_ids` than the instance's `batch_max_files` "
        "hard cap. A manifest over the cap is refused outright; a manifest whose fan-out would "
        "exceed the remaining concurrency is separately refused as `TOO_MANY_ACTIVE_JOBS`.",
    ),
    ErrorCodeSpec(
        "JOB_STALE",
        None,
        "A batch child's run went stale: its worker crashed mid-run and never returned, and the "
        "child sat `running` past the instance's `running_child_ttl_minutes`. The parent's "
        "re-drive fails it explicitly so the aggregate cannot hang on it forever. Recorded on "
        "the failed child job.",
    ),
    ErrorCodeSpec(
        "NOT_FOUND",
        404,
        "No route matches the requested path and method. Check the URL against the API reference.",
    ),
    ErrorCodeSpec(
        "METHOD_NOT_ALLOWED",
        405,
        "The path exists but does not accept this HTTP method.",
    ),
    ErrorCodeSpec(
        "HTTP_ERROR",
        None,
        "A framework-level HTTP error with no more specific code. The `request_id` links to the "
        "server log with the detail.",
    ),
    # --- Authentication and rate limits --------------------------------------------------------
    ErrorCodeSpec(
        "UNAUTHORIZED",
        401,
        "This instance requires an API key and the request did not supply a valid one.",
    ),
    ErrorCodeSpec(
        "NOT_ENABLED",
        404,
        "The requested feature (e.g. accounts) is not enabled on this instance. It answers 404 so "
        "a disabled feature is indistinguishable from an absent one.",
    ),
    ErrorCodeSpec(
        "RATE_LIMITED",
        429,
        "Too many requests in the current window. The `Retry-After` header says when to try again.",
    ),
    ErrorCodeSpec(
        "TOO_MANY_ACTIVE_JOBS",
        429,
        "This caller already has the maximum number of jobs in flight. Wait for one to finish "
        "before submitting another.",
    ),
    # --- Uploads and files ---------------------------------------------------------------------
    ErrorCodeSpec(
        "FILE_TOO_LARGE",
        413,
        "The upload exceeds this instance's size limit. There is no size limit on the CLI or a "
        "self-hosted instance — see the self-hosting guide.",
    ),
    ErrorCodeSpec(
        "FILE_NOT_FOUND",
        404,
        "No uploaded file has this `file_id` on this instance.",
    ),
    ErrorCodeSpec(
        "FILE_EXPIRED",
        410,
        "The uploaded file existed but its retention window has passed and its bytes were deleted. "
        "Re-upload to convert again; any conversion report it produced remains readable.",
    ),
    ErrorCodeSpec(
        "UNKNOWN_FORMAT",
        422,
        "The file's format could not be identified with enough confidence to parse it. Pass an "
        "explicit format if you know it.",
    ),
    ErrorCodeSpec(
        "PARSE_ERROR",
        None,
        "The format was identified but the file could not be parsed; recorded on the failed job, "
        "with the parse issues in `details.issues`.",
    ),
    ErrorCodeSpec(
        "FRAME_LIMIT_EXCEEDED",
        422,
        "The trajectory's frame count exceeds this instance's `max_frames` limit; the job was "
        "refused during the streaming read (counted as it streams, before the remaining frames are "
        "parsed). `details.frame_count` and `details.max_frames` state the numbers.",
    ),
    # --- Conversion, recovery, validation ------------------------------------------------------
    ErrorCodeSpec(
        "INVALID_RECOVERY_CHOICE",
        422,
        "A supplied recovery choice does not match the paused conversion's offered scenario or its "
        "allowed values.",
    ),
    ErrorCodeSpec(
        "RECOVERY_REQUIRED",
        None,
        "A conversion paused for a recovery decision was not resolved before its window expired, "
        "so it resolved to a refusal — never a silently applied default.",
    ),
    ErrorCodeSpec(
        "VALIDATION_ACK_REQUIRED",
        409,
        "The download is gated because post-conversion validation failed; acknowledge the named "
        "failures to proceed. The record keeps showing the failure afterward.",
    ),
    ErrorCodeSpec(
        "VALIDATION_UNAVAILABLE",
        None,
        "Validation could not be run or re-run for this conversion; recorded on the job.",
    ),
    # --- Jobs and records ----------------------------------------------------------------------
    ErrorCodeSpec(
        "JOB_NOT_FOUND",
        404,
        "No job has this `job_id` on this instance.",
    ),
    ErrorCodeSpec(
        "JOB_ALREADY_TERMINAL",
        409,
        "The job is already `completed`, `failed`, `cancelled`, or `expired`, so the requested "
        "transition (e.g. cancel) no longer applies.",
    ),
    ErrorCodeSpec(
        "JOB_NOT_AWAITING_RECOVERY",
        409,
        "A recovery resolution was posted to a job that is not paused at `awaiting_recovery`.",
    ),
    ErrorCodeSpec(
        "JOB_CANCELLED",
        None,
        "A batch child job was cancelled before it produced a conversion. Recorded on the "
        "aggregate entry (status `failed`): the child is an abandonment, not a refusal, so it "
        "contributes no report and no output.",
    ),
    ErrorCodeSpec(
        "CONVERSION_NOT_FOUND",
        404,
        "No conversion record has this `conversion_id` on this instance (it never existed, or it "
        "passed report retention).",
    ),
    ErrorCodeSpec(
        "OUTPUT_EXPIRED",
        410,
        "The converted output's bytes have passed their retention window and were deleted. The "
        "conversion report remains readable; re-run the conversion to regenerate the file.",
    ),
    ErrorCodeSpec(
        "FORMAT_NOT_FOUND",
        404,
        "No format with this id is registered on this instance. See the capabilities endpoint for "
        "the supported set.",
    ),
    # --- Server ---------------------------------------------------------------------------------
    ErrorCodeSpec(
        "INTERNAL_ERROR",
        500,
        "An unexpected server error. The message is deliberately generic; quote the `request_id` "
        "when reporting it so the server-side detail can be found.",
    ),
)


def build_error_codes() -> dict[str, Any]:
    """Return the reference catalog as a plain dict: one entry per code, sorted by code."""
    return {
        "codes": [
            {"code": spec.code, "http_status": spec.http_status, "summary": spec.summary}
            for spec in sorted(ERROR_CODES, key=lambda s: s.code)
        ]
    }


def serialize(document: dict[str, Any]) -> str:
    """Canonical text form: sorted keys, 2-space indent, one trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_artifact(path: Path = ARTIFACT_PATH) -> Path:
    """Regenerate the committed artifact at ``path`` and return it."""
    path.write_text(serialize(build_error_codes()), encoding="utf-8")
    return path


if __name__ == "__main__":  # pragma: no cover - CLI entry, exercised via write_artifact() in tests
    written = write_artifact()
    print(f"Wrote {written}")
