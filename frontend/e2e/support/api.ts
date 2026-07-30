import { readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, type APIRequestContext } from "@playwright/test";

/**
 * Server-side setup helpers for the end-to-end journeys (M30-S1).
 *
 * Two of the honest states the UI must render — the `awaiting_recovery` pause and the `cancelled`
 * job — cannot be produced by clicking through the app itself: the convert button submits
 * `allow_recovery: false` (v0.6 has no interactive recovery cards yet), so a recovery-needed
 * conversion *refuses* rather than pausing. The pause is a real, first-class API state, so the
 * faithful way to exercise its page is to create it the way a caller who *did* ask for interactive
 * recovery would — over the `/v1` API — and then drive the browser to the resulting job. That is
 * genuine end-to-end coverage of the running stack: the same backend, the same worker, the same
 * pause; only the trigger is the API rather than a button that does not exist yet.
 *
 * These helpers therefore talk to the backend **directly** (`E2E_API_URL`, the compose stack's
 * `8000`), not through the browser's same-origin proxy — setup is not the thing under test, and a
 * direct call keeps multipart uploads off the Next dev proxy. The browser assertions still hit the
 * frontend at `E2E_BASE_URL`; the two share one backend and one database, so a job seeded here is
 * visible to the page that polls it.
 */

/** The backend's own origin, for setup calls. The browser uses `E2E_BASE_URL` (see the config). */
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

// Playwright transpiles specs to CommonJS (this package is not `"type": "module"`), so `__dirname`
// is the portable way to locate the fixtures beside the specs, independent of the invoking cwd.
const FIXTURES_DIR = join(__dirname, "..", "fixtures");

/** Upload fixtures, by role. Kept here so a rename touches one place, not six specs. */
export const FIXTURES = {
  /** Extended XYZ carrying a lattice, forces, charge, masses, energy — all dropped by plain XYZ. */
  workedExample: { file: "worked-example.extxyz", mimeType: "chemical/x-xyz" },
  /** A 3-frame ASE relaxation trajectory: → POSCAR needs a frame choice, so the job pauses. */
  relaxTraj: { file: "relax.traj", mimeType: "application/octet-stream" },
  /**
   * A single structure in a 6 Å cubic cell **rotated 45° in the xy-plane** — the lattice matrix is
   * not in a standard orientation (a is not along x). Converting it to CIF genuinely fails
   * validation: see `seedFailedValidationConversion`.
   */
  rotatedLattice: { file: "rotated-lattice.extxyz", mimeType: "chemical/x-xyz" },
  /** A Word document's byte signature — the sniffer must answer UNKNOWN_FORMAT for it. */
  notAStructure: { file: "not-a-structure.docx", mimeType: "application/octet-stream" },
} as const;

/** Absolute path to an `e2e/fixtures/` file, for `setInputFiles`. */
export function fixturePath(name: string): string {
  return join(FIXTURES_DIR, name);
}

/** The raw bytes of an `e2e/fixtures/` file, for multipart API uploads. */
export function fixtureBuffer(name: string): Buffer {
  return readFileSync(fixturePath(name));
}

const TERMINAL = new Set(["completed", "failed", "cancelled", "expired"]);

interface JobEnvelope {
  job_id: string;
  state: string;
  [key: string]: unknown;
}

/** Upload a fixture over the API and return its `file_id`. */
export async function uploadFixture(
  request: APIRequestContext,
  fixture: { file: string; mimeType: string },
): Promise<string> {
  const resp = await request.post(`${API_URL}/v1/upload`, {
    multipart: {
      file: {
        name: fixture.file,
        mimeType: fixture.mimeType,
        buffer: fixtureBuffer(fixture.file),
      },
    },
  });
  expect(resp.status(), await resp.text()).toBe(201);
  return String((await resp.json()).file_id);
}

/**
 * Poll `GET /v1/jobs/{id}` until it reaches one of `states` (or any terminal state), then return
 * the envelope. The Tier-1 worker runs jobs off the queue, so a submit returns before the work is
 * done and the caller must poll — exactly as the UI's own long-poll does.
 */
export async function pollJob(
  request: APIRequestContext,
  jobId: string,
  states: string[],
  timeoutMs = 30_000,
): Promise<JobEnvelope> {
  const want = new Set(states);
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const resp = await request.get(`${API_URL}/v1/jobs/${jobId}`);
    expect(resp.ok(), await resp.text()).toBeTruthy();
    const env = (await resp.json()) as JobEnvelope;
    if (want.has(env.state) || TERMINAL.has(env.state)) return env;
    if (Date.now() > deadline) throw new Error(`job ${jobId} stuck in ${env.state} after ${timeoutMs}ms`);
    await new Promise((r) => setTimeout(r, 400));
  }
}

/**
 * Cancel a job over the API, best-effort. A seeded `awaiting_recovery` pause is a **non-terminal**
 * job, so it holds one of the instance's `max_concurrent_jobs` slots until something ends it. The
 * specs that seed a pause call this in an `afterEach` so the slot is freed whether the test passed
 * or failed — otherwise repeated runs against a persistent stack accumulate parked jobs until the
 * cap is saturated and every later job is refused `429 TOO_MANY_ACTIVE_JOBS`. Cancelling a job that
 * is already terminal is a no-op here (the backend answers `JOB_ALREADY_TERMINAL`, which is fine to
 * ignore) — cleanup must never itself fail a test.
 */
export async function cancelJob(request: APIRequestContext, jobId: string): Promise<void> {
  try {
    await request.post(`${API_URL}/v1/jobs/${jobId}/cancel`);
  } catch {
    // Best-effort teardown; a failed cancel is not a test failure.
  }
}

/**
 * Seed a paused conversion: upload the relaxation trajectory and ask to convert it to POSCAR *with
 * interactive recovery*, so the engine pauses on the frame-selection decision (a 3-frame trajectory
 * → a single-frame POSCAR) rather than refusing. Returns the paused job's id.
 */
export async function seedAwaitingRecoveryJob(request: APIRequestContext): Promise<string> {
  const fileId = await uploadFixture(request, FIXTURES.relaxTraj);
  const resp = await request.post(`${API_URL}/v1/convert`, {
    data: {
      file_id: fileId,
      target_format_id: "poscar",
      options: { allow_recovery: true },
    },
  });
  expect([200, 201, 202]).toContain(resp.status());
  const jobId = String((await resp.json()).job_id);
  const paused = await pollJob(request, jobId, ["awaiting_recovery"]);
  expect(paused.state, "expected the trajectory→POSCAR conversion to pause for a decision").toBe(
    "awaiting_recovery",
  );
  return jobId;
}

/**
 * Seed a **completed conversion whose validation failed**, and return its `conversion_id` so a spec
 * can drive the browser to `/conversions/{id}` and exercise the acknowledgment gate (slice M32-S1).
 *
 * The failure is **real**, not mocked, and it is produced by a genuine representational limit of the
 * target format — no test hooks, no doctored bytes, no exotic tolerance. The source is a cubic cell
 * rotated 45° in the xy-plane (`FIXTURES.rotatedLattice`): its lattice matrix is not in a standard
 * orientation. CIF stores a cell as **lengths + angles** (`_cell_length_*` / `_cell_angle_*`), which
 * cannot express lattice *orientation* — so the re-parse reconstructs the cell in CIF's canonical
 * orientation (a along x) and the atoms, carried as fractional coordinates, come back **rotated** in
 * Cartesian space. That is a large, deterministic ~2.4 Å position residual — orders of magnitude
 * above the default `positions_rmsd` fail bound (1e-3 Å) — so validation fails under **default**
 * tolerances, on the same worker and validator that serve every user.
 *
 * (This replaces the slice's original attempt to force the failure with a sub-femtometre tolerance
 * on an extXYZ→POSCAR conversion: POSCAR writes **Cartesian** coordinates at full `repr` precision,
 * so its `positions_rmsd` is always *exactly* 0.0 and no tolerance can ever fail it. The rotation
 * loss is a genuine format limit rather than a floating-point residual, so it is deterministic
 * across platforms instead of flaking on BLAS-dependent ulp noise.)
 *
 * The conversion itself still **completes** — CIF holds the species, cell parameters and (rotated)
 * positions — so this is exactly the state the gate exists for: a real file the service could not
 * verify faithfully.
 */
export async function seedFailedValidationConversion(request: APIRequestContext): Promise<string> {
  const fileId = await uploadFixture(request, FIXTURES.rotatedLattice);
  const resp = await request.post(`${API_URL}/v1/convert`, {
    data: {
      file_id: fileId,
      target_format_id: "cif",
      options: {},
    },
  });
  expect([200, 201, 202]).toContain(resp.status());
  const jobId = String((await resp.json()).job_id);
  const done = await pollJob(request, jobId, ["completed"]);
  expect(done.state, "expected the rotated-cell → CIF conversion to complete").toBe("completed");
  const result = done.result as { conversion_id: string; download: { requires_ack: boolean } };
  expect(
    result.download.requires_ack,
    "expected CIF's loss of lattice orientation to fail validation (requires_ack)",
  ).toBe(true);
  return result.conversion_id;
}

/**
 * Seed a **refused** conversion and return its durable record id plus the still-valid source
 * `file_id`. The same trajectory→POSCAR conversion, but submitted **without** interactive recovery
 * (`allow_recovery: false`), so the unresolved frame + lattice decisions make it *refuse* rather than
 * pause — a completed job at HTTP 200 whose report status is `refused` (Part 6 §1). The refusal is
 * persisted as an immutable record, and the upload is still in hand, which is exactly the state
 * "resolve and retry" acts on (M32-S2): the browser opens the record with `?file_id=` and re-enters
 * the cards. Seeding over the API is the honest way here — the UI now always submits
 * `allow_recovery: true`, so a refusal is no longer reachable by clicking (it would pause instead).
 */
export async function seedRefusedConversion(
  request: APIRequestContext,
): Promise<{ conversionId: string; fileId: string }> {
  const fileId = await uploadFixture(request, FIXTURES.relaxTraj);
  const resp = await request.post(`${API_URL}/v1/convert`, {
    data: {
      file_id: fileId,
      target_format_id: "poscar",
      options: { allow_recovery: false },
    },
  });
  expect([200, 201, 202]).toContain(resp.status());
  const jobId = String((await resp.json()).job_id);
  const done = await pollJob(request, jobId, ["completed"]);
  expect(done.state, "expected the no-recovery conversion to complete as a refusal").toBe("completed");
  const result = done.result as { conversion_id?: string; conversion_report?: { status?: string } };
  expect(result?.conversion_report?.status, "expected a refused conversion report").toBe("refused");
  const conversionId = String(result.conversion_id);
  expect(conversionId, "a refused conversion is persisted as a record").toBeTruthy();
  return { conversionId, fileId };
}
