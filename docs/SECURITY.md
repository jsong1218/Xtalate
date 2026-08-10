# Security Policy

Xtalate is a loss-aware file-format converter for computational chemistry. Its trust claim —
*never silently lose scientific information* — extends to how it treats the files it is given:
**uploaded files are data, never code.** This document states what that means in practice, how the
project is hardened against the threats a converter faces, and how to report a vulnerability.

## Supported versions

Security fixes land on the latest 1.x release line; there is no long-term-support branch for older
versions. Self-hosters should track the most recent tag.

| Version | Supported |
|---------|-----------|
| 1.x (latest minor) | ✅ |
| Older 1.x / pre-1.0 tags | ❌ (upgrade to the latest) |

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** Report it privately through
GitHub's **private vulnerability reporting**: on the repository, go to the **Security** tab →
**Report a vulnerability**. That opens a private advisory visible only to you and the maintainers.

When reporting, include: the affected version or commit, a description of the issue and its impact,
and — if you can — a minimal reproducer (a malformed input file, a request sequence). If you believe
a fix is straightforward, a suggested patch is welcome but never required.

You can expect an acknowledgement of the report and, once triaged, an assessment of severity and a
target for the fix. Because Xtalate is a solo-maintained project, please allow reasonable time for a
response before any public disclosure; we will coordinate a disclosure timeline with you.

## Threat model

The security surface of a file converter decomposes into three threats, each with its own control.
This is the standing checklist the project is designed against, and the checklist each security drill
re-walks (the most recent walk is in [`docs/security/`](security/)).

### 1. Confidentiality — files are unpublished research data

- **Private storage only.** Object storage is never publicly readable; there are no public object
  URLs. Output bytes are streamed **through the authenticated API**, never handed out as a public
  link. (A short-lived per-request pre-signed URL is an equivalent control the storage adapter seam
  supports, but the shipped default streams through the API.)
- **Ownership scoping and authentication.** Every data endpoint (`/v1/upload`, `/v1/inspect`,
  `/v1/convert`, `/v1/validate`, `/v1/jobs/*`, `/v1/download/*`, history) requires the instance's
  auth policy to pass. Only three surfaces are intentionally open: `/v1/health` (unguarded — an
  orchestrator probe must not need a key), and `/v1/capabilities*` and `/v1/limits` (public but
  rate-limited — a pipeline reads them *before* it authenticates).
- **Retention as a confidentiality control.** Data that no longer exists cannot leak. Uploaded bytes
  and conversion outputs expire on short, independent lifecycle windows; conversion **records**
  (reports) outlive the bytes by a longer, configurable window and then are swept too. The record
  never contains atomic coordinates or file bytes — only field names/paths, statuses, measured
  deviations, and any recovery-supplied parameters the user chose.

### 2. Hostile input — parsers consume untrusted bytes

- **Files are data, never code.** No parser or exporter shells out to an external interpreter,
  `eval`/`exec`s file content, unpickles untrusted data, or loads YAML unsafely. This is enforced by
  review (a files-as-data audit is part of every security drill) and by the architecture: parsers
  produce a Canonical Object and nothing else.
- **Pathological input becomes that job's failure, not the host's.** Malformed, truncated, or
  adversarially-sized input (e.g. a file that declares an impossible atom count) is converted into
  that job's structured error through the parser error contract — not a crash, hang, or memory
  blow-up. The frame-chunked streaming core keeps memory sub-linear in trajectory length, and a
  per-job wall-clock timeout bounds runaway processing.
- **Fuzzing is a standing duty.** A parser fuzz seed corpus (`tests/fuzz/`) asserts the
  graceful-failure contract across every format, and randomized property tests exercise the report
  machinery over generated inputs. Extending the fuzz corpus on every new format is a permanent
  maintenance duty.

### 3. Abuse of a hosted instance — storage/CPU as a free resource

- **Bounded blast radius.** Per-caller rate limits (`429` with `Retry-After`), an upload size cap
  (`413 FILE_TOO_LARGE`, enforced mid-stream), and a concurrent-job cap (`429
  TOO_MANY_ACTIVE_JOBS`) bound what any one caller can consume, and lifecycle expiry bounds what
  accumulates over time.
- **Optional static API key.** A self-hosted instance may require an `Authorization: Bearer <key>`
  on every data endpoint (keys are compared in constant time). With no key configured the instance
  runs in anonymous self-hosted mode, bucketed by client host for the limits above.

## Deployment note for self-hosters

Xtalate is designed to be self-hosted (this is the supported deployment). When you run it:

- **Set an API key** (`XTALATE_API_KEYS`) if the instance is reachable beyond your machine — without
  one, the instance is anonymous.
- **Keep storage private.** Point the object-store adapter at a private bucket; never enable public
  read on it.
- **Never commit secrets.** API keys, database credentials, and object-store keys are supplied via
  environment variables (or an untracked `.env`), never committed.
- **Front the stack with TLS.** The app and API assume a TLS-terminating reverse proxy in front of
  them for any non-local deployment.

See [`docs/self-hosting.md`](self-hosting.md) for the full deployment, backup, and restore posture.
