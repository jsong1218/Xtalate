# Security review — M37 hardening pass

- **Date:** 2026-08-06
- **Scope:** the `xtalate` library + CLI (`src/xtalate/`), the FastAPI service (`backend/`), and the
  Next.js Web UI (`frontend/`), at the M37 branch head.
- **Method:** a walk of the project [threat model](../SECURITY.md#threat-model) point by point,
  cross-checked against the code; a mechanical files-as-data audit; a per-job resource-cap
  demonstration (a new test); a dependency audit; and a parser fuzz-posture review.
- **Prior art:** this extends the v0.5 service-security review (which cleared the first networked
  version: constant-time key compare, ORM-parameterized queries, path/header sanitization, no
  `eval`/`pickle`/unsafe-YAML over the wire). M37 re-runs that as a dated, committed result and adds
  the v0.6 Web UI to the surface. The difference between "we checked" and "it is checked" is this
  artifact.

**Outcome:** the threat model holds. The files-as-data audit is clean, the dependency audit is
clean, the parser fuzz corpus is green across all seven formats, and the enforced per-job resource
caps demonstrably isolate a pathological request. One finding (**F1**, below) records a *documented*
resource cap that is not actually enforced; it is a contract/honesty gap, not an exploitable
resource exhaustion, and is reconciled in docs + ticketed rather than fixed under the M37 code
freeze.

---

## 1. Files-as-data audit

The claim "uploaded files are data, never code" made concrete: no parser/exporter shells out,
`eval`/`exec`s file content, unpickles untrusted data, loads YAML unsafely, or otherwise turns bytes
into execution. Grep over `src/xtalate/` and `backend/` (`*.py`), each hit reviewed:

| Pattern | Hits (src + backend) | Verdict |
|---|---|---|
| `subprocess` | 0 | clean |
| `os.system` / `os.popen` | 0 | clean |
| `eval(` | 0 | clean |
| `exec(` | 0 | clean |
| `pickle` | 0 | clean |
| `marshal` | 0 | clean |
| `__import__` | 0 | clean |
| `shell=True` | 0 | clean |
| `yaml.load` (unsafe) / `yaml.unsafe_load` | 0 | clean |
| `yaml.safe_load` | 1 (`src/xtalate/cli/main.py`) | **safe** — the safe API, and the input is a CLI-supplied tolerance-table *path* the operator names, not wire data |

Frontend XSS surface (`frontend/`, `*.ts`/`*.tsx`), grep for `dangerouslySetInnerHTML`, `innerHTML`,
`eval(`, `new Function`:

| Pattern | Hits | Verdict |
|---|---|---|
| `dangerouslySetInnerHTML` | 1 (`frontend/app/layout.tsx`) | **safe** — a static compile-time theme-script literal (no interpolation, no user/report data); the standard Next.js no-flash-of-theme pattern |
| `innerHTML` / `eval(` / `new Function` | 0 | clean |

Report text is rendered through React's auto-escaping JSX everywhere — there is no path from
report/report-derived content into raw HTML.

**Verdict: clean.** Files remain data on every path audited.

---

## 2. Threat-model walk

### 2.1 Confidentiality

- **Private storage, no public URLs.** Output bytes stream *through* the authenticated API
  (`backend/routers/downloads.py` — a `StreamingResponse` behind the not-found/ack/expiry gates);
  the module comment states outright the bytes never leave through a presigned URL. Verified.
- **Authenticated data surface; minimal public surface.** `backend/app.py` wires exactly three
  tiers: `health` + `accounts` unguarded (accounts answer `404 NOT_ENABLED`), `capabilities` +
  `limits` public-but-rate-limited, and every data router (`uploads`, `jobs`, `downloads`,
  `conversions`) behind the full request policy. This matches the intended public surface —
  `/v1/capabilities*`, `/v1/limits`, `/v1/health` — and nothing more. Verified.
- **Auth is constant-time.** `backend/security.py::resolve_principal` compares a presented bearer
  token against each configured key with `secrets.compare_digest`, never logs or echoes the key, and
  buckets the caller by key. Verified.
- **Retention bounds exposure.** Two windows exist and are swept: the byte window
  (`upload_retention_hours`/`output_retention_hours`, observed lazily → `410`) and the record window
  (`report_retention_days`, the daily `sweep_reports`; `None` = indefinite, the self-host default).
  Records outlive bytes by FK direction and never hold coordinates or file bytes. Verified.

### 2.2 Hostile input

- **Files-as-data:** §1 above — clean.
- **Pathological input → structured failure, not host exhaustion:** demonstrated by the fuzz corpus
  (§4) — a file declaring 999,999,999 atoms `ParseError`s on EOF rather than pre-allocating — and by
  the resource-cap test (§3). Memory is bounded by the frame-chunked streaming core (a 100k-frame
  file completes under a peak-RSS bound; `benchmarks._bench_frame_limit_ceiling`), and wall-clock by
  `job_timeout_seconds`.
- **Fuzzing is a standing duty:** the seed corpus lands in this milestone (§4).

### 2.3 Abuse of a hosted instance

- **Rate limit:** `backend/security.py::RateLimiter` — a bounded, per-caller fixed-window limiter →
  `429 RATE_LIMITED` + `Retry-After`. Verified (and the limiter's memory is bounded by design — it
  sweeps stale buckets each minute).
- **Upload size cap:** `413 FILE_TOO_LARGE`, enforced mid-stream, no orphaned bytes — see §3.
- **Concurrent-job cap:** `429 TOO_MANY_ACTIVE_JOBS` on the submit endpoints — see §3.
- **Lifecycle expiry:** §2.1 retention windows bound accumulation.

**Verdict: the three-threat model holds**, with the one caveat recorded as F1.

---

## 3. Per-job resource caps — demonstrated

The claim is that each per-job cap "exhausts *its own* job and nothing else." The new test
`tests/backend/test_resource_caps.py` demonstrates the isolation property over the caps the service
**actually enforces**:

- **Upload byte cap.** One byte past `max_upload_bytes` is refused mid-stream with the bounded
  `413 FILE_TOO_LARGE` envelope (not an OOM, not a 500) and leaves no orphaned bytes; a concurrent
  well-formed upload immediately succeeds — the instance is not wedged.
- **Concurrent-job cap.** With the pool saturated, the *excess* submit is refused with
  `429 TOO_MANY_ACTIVE_JOBS`; the jobs already holding slots are untouched, and freeing one slot
  restores capacity for the next submit — the cap bounds, it does not permanently wedge.

Two further per-job bounds are evidence elsewhere: the **memory** bound (frame-chunked streaming,
`benchmarks._bench_frame_limit_ceiling`) and the **wall-clock** bound (`job_timeout_seconds`).

### Finding F1 — the advertised frame-count cap is not enforced

`max_frames` (default 100,000) is published by `GET /v1/limits` and described in
`backend/config.py` as *"Hard cap on trajectory frames a single job will read; already enforced by
the parser (`FRAME_LIMIT_EXCEEDED`)."* The canonical spec's limits table likewise mandates a
`422 PARSE_ERROR` with code `FRAME_LIMIT_EXCEEDED` past 100,000 frames.

**Reality:** the string `FRAME_LIMIT_EXCEEDED` exists in **no source file**; it is not a registered
error code; no parser takes a frame-count limit; and `settings.max_frames` is passed **only** to
`/v1/limits` for display — never into any parse or convert call. The cap is advertised but not
enforced.

**Assessment:** a contract/honesty gap, **not** an exploitable resource exhaustion. Memory is
already bounded regardless of frame count (streaming core), and wall-clock by `job_timeout_seconds`;
input size is bounded by the upload byte cap. The gap is that the byte cap does **not** subsume the
frame cap — a tiny-structure trajectory (~30 bytes/frame) can pack millions of frames under the
100 MB byte ceiling — so the *specific* `FRAME_LIMIT_EXCEEDED` contract is unmet even though no OOM
results.

**Disposition (M37 code freeze — no `src/` change):**

1. **Reconcile the docs to reality** (M37 S4): correct the `backend/config.py` docstring so it
   describes `max_frames` as an advisory sizing hint, not an enforced cap, and names the effective
   bounds (upload byte cap + streaming memory ceiling + job timeout); mark the spec's limits-table
   row as a known deviation.
2. **Ticket real enforcement for a future minor** (v1.1): wire a frame-count limit into the parser
   layer and register `FRAME_LIMIT_EXCEEDED (422)`. This touches `src/xtalate/parsers/` and is
   deliberately **not** done under the 1.0 freeze.

Recording the gap honestly, rather than papering over it, is P1 applied to the project's own
process.

---

## 4. Parser fuzz posture

**Existing coverage.** Hand-written negative cases exist per parser (`tests/parsers/` — CIF 21 +
POSCAR/XDATCAR/XYZ/extXYZ 6–9 each), plus a vendored Crystallography Open Database "wild" corpus for
CIF (`tests/wild/`) asserting exact issue-code sets. Randomized **property** tests
(`tests/property/`, Hypothesis, with shrinking) exercise the report machinery — but by design over
*valid* Canonical Objects, i.e. the object→export→report direction, not malformed *parser input*.

**Gap identified & addressed.** There was no systematic input-fuzz corpus feeding malformed *bytes*
to the parsers. M37 lands one: `tests/fuzz/test_parser_fuzz.py`, a curated, deterministic seed
corpus (a generic battery × all 7 built-in parsers, plus format-tailored malformations) asserting
the single robustness invariant —

> a parse of arbitrary bytes yields **either** a valid `ParseResult` **or** a `ParseError`, and
> nothing else: no leaked `ValueError`/`KeyError`/`UnicodeDecodeError`, no crash, no hang, no
> unbounded allocation.

**Result:** all 80 cases pass — zero non-graceful outcomes across every format, including the
"declares 10⁹ atoms" case (it `ParseError`s on EOF, never pre-allocates).

**Remaining gaps (ticketed, not blockers):**

- **Continuous / coverage-guided fuzzing** (random byte mutation, e.g. `atheris`/`hypothesis`
  byte-level, run under the nightly extended profile) — the seed corpus is the reviewable seed set it
  would grow from, not a replacement for it.
- **`ase_traj`** has no hand-written malformed-input negative case of its own (it delegates to ASE,
  which the parser normalizes to `ParseError`); the fuzz corpus now covers it, but a dedicated
  regression suite for ASE-delegated failure modes is worth adding.

---

## 5. Dependency audit

`pip-audit` over the installed environment: **no known vulnerabilities found.** The two skipped
entries (`xtalate-example-format`, `xtalate-toyfmt`) are the local editable test-fixture plugins,
not on PyPI and not runtime dependencies — an expected, benign skip.

---

## 6. Follow-ups

| # | Item | Where | Blocker for 1.0? |
|---|---|---|---|
| F1 | Reconcile `max_frames`/`FRAME_LIMIT_EXCEEDED` docs to reality | M37 S4 | reconciliation: yes; enforcement: no |
| F1 | Ticket real per-job frame-count enforcement | v1.1 | no |
| — | Continuous/coverage-guided parser fuzzing under nightly | v1.1 | no |
| — | Dedicated `ase_traj` malformed-input regression suite | v1.1 | no |

None of the follow-ups is an exploitable defect; F1's documentation reconciliation is the only
1.0-scoped item, and it lands in M37 S4.
