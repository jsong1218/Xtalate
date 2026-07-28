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
