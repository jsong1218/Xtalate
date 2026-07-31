# Error reference

Every non-2xx response from the Xtalate service uses one envelope shape (MASTER_SPEC Part 6 §6):

```json
{
  "error": {
    "code": "UNKNOWN_FORMAT",
    "message": "The file's format could not be identified.",
    "details": { },
    "request_id": "…",
    "documentation_url": "…/errors#unknown_format"
  }
}
```

`code` is the stable machine string your client branches on — it never changes for a given
condition, even if the human `message` is reworded. `documentation_url` points at the section on this
page for that code (the anchor is the code, lower-cased). `request_id` is the bridge to the
server-side log; quote it when reporting a problem.

**A refused conversion is not an error.** When the engine declines a conversion it returns a
*completed* job at HTTP 200 whose `ConversionReport.status == "refused"` — it never appears here.
This page is for transport failures only: bad input, missing or expired resources, limits, and server
faults. Two exceptions below (`PARSE_ERROR`, `RECOVERY_REQUIRED`, `VALIDATION_UNAVAILABLE`) are
recorded on a *job* body rather than carried as an HTTP status, and are marked as such.

Codes are grouped by concern. Within each group the heading is the exact machine code.

## Request shape and routing

### MALFORMED_REQUEST

**HTTP 400.** The request body or parameters failed validation — a missing field, a wrong type, or an
unparseable body. `details.errors` lists each field-level failure so you can fix the offending field
without scraping the message.

### INVALID_CURSOR

**HTTP 422.** The `cursor` you passed to a paginated listing (e.g. `/v1/history`) is not one this
service issued. Cursors are opaque; start from the first page and follow only the `next_cursor`
values the service returns.

### NOT_FOUND

**HTTP 404.** No route matches the requested path and method. Check the path against the
[API reference](./api). This is distinct from the resource-specific 404s below (`FILE_NOT_FOUND`,
`JOB_NOT_FOUND`, …), which mean the route exists but the named resource does not.

### METHOD_NOT_ALLOWED

**HTTP 405.** The path exists but does not accept this HTTP method.

### HTTP_ERROR

A framework-level HTTP error with no more specific code assigned. The status varies. The
`request_id` links to the server log with the detail; if you see this repeatedly, please report it.

## Authentication and rate limits

### UNAUTHORIZED

**HTTP 401.** This instance requires an API key and the request did not supply a valid one. Send your
key in the configured header. Public read-only endpoints (`/v1/capabilities*`, `/v1/limits`) never
require a key.

### NOT_ENABLED

**HTTP 404.** The requested feature (for example, accounts) is not enabled on this instance. It is
reported as a 404 on purpose, so that a *disabled* feature is indistinguishable from an *absent* one
and cannot be probed for.

### RATE_LIMITED

**HTTP 429.** Too many requests in the current window. The `Retry-After` response header says how many
seconds to wait before retrying. Rate limits are per-caller and instance-configurable.

### TOO_MANY_ACTIVE_JOBS

**HTTP 429.** This caller already has the maximum number of jobs in flight. Wait for one to reach a
terminal state (`completed`, `failed`, `cancelled`, or `expired`) before submitting another.

## Uploads and files

### FILE_TOO_LARGE

**HTTP 413.** The upload exceeds this instance's configured size limit (`/v1/limits` reports the
ceiling). There is **no** size limit on the command-line tool or on a self-hosted instance — see the
[quickstart](./quickstart) for the local path, or the [self-hosting guide](./self-hosting) to run
your own instance with no cap.

### FILE_NOT_FOUND

**HTTP 404.** No uploaded file has this `file_id` on this instance. Either it was never uploaded here,
or the id is wrong.

### FILE_EXPIRED

**HTTP 410.** The uploaded file existed but its retention window has passed and its bytes were
deleted. Re-upload the file to convert it again. Any conversion report the file already produced stays
readable — reports outlive bytes.

### UNKNOWN_FORMAT

**HTTP 422.** The file's format could not be identified with enough confidence to parse it. If you
know the format, pass it explicitly rather than relying on sniffing.

### PARSE_ERROR

**Recorded on the failed job (the job itself is HTTP 200).** The format was identified but the file
could not be parsed. `details.issues` lists the specific parse issues — a truncated record, a
malformed line — so you can see exactly where reading failed.

## Conversion, recovery, and validation

### INVALID_RECOVERY_CHOICE

**HTTP 422.** A supplied recovery choice does not match the paused conversion's offered scenario, or
its value is outside the allowed set for that scenario. The paused job's `awaiting_recovery` block
lists the valid scenarios and choices.

### RECOVERY_REQUIRED

**Recorded as a refusal.** A conversion that paused for a recovery decision was not resolved before
its window expired, so it resolved to a **refusal** — never a silently applied default. Re-run the
conversion and resolve the recovery choice within the window to proceed.

### VALIDATION_ACK_REQUIRED

**HTTP 409.** The download is gated because post-conversion validation failed. The response names the
specific validation failures; acknowledge them to proceed with the download. The conversion record
keeps showing the failure afterward — acknowledging does not erase it.

### VALIDATION_UNAVAILABLE

**Recorded on the job.** Validation could not be run (or re-run) for this conversion. The conversion
itself may still have completed; only the post-conversion validation step is missing.

## Jobs and records

### JOB_NOT_FOUND

**HTTP 404.** No job has this `job_id` on this instance.

### JOB_ALREADY_TERMINAL

**HTTP 409.** The job is already in a terminal state (`completed`, `failed`, `cancelled`, or
`expired`), so the requested transition — cancelling it, for instance — no longer applies.

### JOB_NOT_AWAITING_RECOVERY

**HTTP 409.** A recovery resolution was posted to a job that is not paused at `awaiting_recovery`.
Only a job actually waiting for a recovery decision can accept one.

### CONVERSION_NOT_FOUND

**HTTP 404.** No conversion record has this `conversion_id` on this instance. Either it never existed,
or it has passed the report-retention window and was swept.

### OUTPUT_EXPIRED

**HTTP 410.** The converted output's bytes have passed their retention window and were deleted. The
conversion report remains readable; re-run the conversion to regenerate the output file.

### FORMAT_NOT_FOUND

**HTTP 404.** No format with this id is registered on this instance. See
[`/v1/capabilities`](./api) for the supported set on your instance.

## Server

### INTERNAL_ERROR

**HTTP 500.** An unexpected server error. The message is deliberately generic — it may otherwise quote
file content, which the logs must never carry — so quote the `request_id` when reporting it; that is
how the server-side detail is found.
