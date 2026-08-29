import { expect, test } from "@playwright/test";
import { API_URL } from "./support/api";

/**
 * The M59-S3 spike measurement (the M60 go/no-go evidence): a **generated 10⁴-frame trajectory**
 * scrubbed through the loader + ranged geometry endpoint in a real browser, with browser JS heap
 * and per-scrub latency measured. The committed number that says whether the M61 budget is real.
 *
 * The trajectory is generated at run time — never committed (the golden-corpus discipline): a
 * deterministic synthetic extXYZ (10⁴ frames × 8 atoms, 20 Å cubic lattice) written inline here,
 * matching the corpus generator's shape (`tests/streaming/_generators.py`). The spike consumes it
 * through the real S1 endpoint and the dev spike surface's scrub harness.
 *
 * The scrub model is the M61 story: **client-side** window navigation on the spike surface, so all
 * scrubs share one JS context and each mount replaces the previous one (the old Mol* plugin is
 * disposed on unmount). Heap is sampled after an explicit GC per scrub (removing allocator noise);
 * the flatness assertion is a **ceiling, not a rising line** — every scrub heap under a ceiling
 * above the baseline and the final scrub within a headroom of the first — so a per-mount leak or
 * an unbounded accumulation across scrubs fails the journey. Numbers are logged for the progress
 * doc.
 */

// The browser journey runs against the shared e2e stack, whose upload ceiling is deliberately small
// (``XTALATE_MAX_UPLOAD_BYTES=1048576`` so the oversized-upload journey stays kilobyte-scale), so
// the generated file must fit 1 MB: **10⁴ frames × 1 atom**, tight formatting (2 decimals, no
// per-frame extras) ≈ 500 KB. The celled 10⁴×8 case is the Python benchmark's — it boots its own
// server at the default 100 MB ceiling and keeps the lattice.
function generateSpikeExtxyz(nFrames = 10_000): Buffer {
  const lines: string[] = [];
  for (let f = 0; f < nFrames; f++) {
    lines.push("1");
    lines.push("Properties=species:S:1:pos:R:3");
    const base = (1234 * 131 + f * 7) % 1000 / 100.0;
    const x = (base + 0.01 * f) % 20.0;
    const y = (base * 1.3) % 20.0;
    const z = (base * 0.7 + 0.005 * f) % 20.0;
    lines.push(`C ${x.toFixed(2)} ${y.toFixed(2)} ${z.toFixed(2)}`);
  }
  return Buffer.from(lines.join("\n") + "\n", "utf-8");
}

/** The scrub windows, mirroring the spike surface's harness row. */
const SCRUB_WINDOWS = [
  "0:100",
  "1000:1100",
  "2000:2100",
  "3000:3100",
  "4000:4100",
  "5000:5100",
  "6000:6100",
  "7000:7100",
  "8000:8100",
  "9000:9100",
];

/** The generous headrooms (a ceiling, not a rising line — a leak far below these still fails). */
const CEILING_MIB_ABOVE_BASELINE = 128;
const HEADROOM_MIB_FIRST_TO_LAST = 48;

test.use({
  launchOptions: { args: ["--enable-precise-memory-info"] },
});

test("a generated 10⁴-frame trajectory scrubs with browser memory flat under a sliding window", async ({
  page,
  request,
}) => {
  // Seed the generated trajectory through the real API (the S1 endpoint serves it from live bytes).
  const spike = generateSpikeExtxyz();
  const upload = await request.post(`${API_URL}/v1/upload`, {
    multipart: {
      file: {
        name: "spike-1e4.extxyz",
        mimeType: "chemical/x-xyz",
        buffer: spike,
      },
    },
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const fileId = String((await upload.json()).file_id);

  // The endpoint counted the whole trajectory on the first ranged read — the scrub's total is real.
  const first = await request.get(`${API_URL}/v1/files/${fileId}/geometry?frames=0:1`);
  expect(first.status(), await first.text()).toBe(200);
  expect((await first.json()).frame_count).toBe(10_000);

  const cdp = await page.context().newCDPSession(page);
  // V8's direct heap-usage read (usedSize in bytes) — `Performance.getMetrics`' JSHeapUsedSize is
  // unreliable across Chromium versions, and `performance.memory` is deprecated, so CDP it is.
  const jsHeap = async (): Promise<number> => {
    const { usedSize } = await cdp.send("Runtime.getHeapUsage");
    return Number(usedSize);
  };
  const forceGc = (): Promise<void> => cdp.send("HeapProfiler.collectGarbage");

  // Baseline: the spike surface at the default structure read (frame 0), then GC + sample.
  // ``domcontentloaded`` — the mounted selector below is the real readiness signal, and waiting
  // for full ``load`` can stall on the dev server's first compile of the route.
  await page.goto(`/dev/structure/${fileId}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("[data-mounted=true]")).toBeVisible({ timeout: 60_000 });
  await forceGc();
  const baseline = await jsHeap();

  // The sliding window: client-side scrubs across the trajectory (one JS context; each mount
  // replaces the previous), sampling heap + latency after each window.
  const heaps: number[] = [];
  const latencies: number[] = [];
  for (const window of SCRUB_WINDOWS) {
    const t0 = Date.now();
    await page.getByRole("link", { name: window }).click();
    await expect(
      page.locator(`text=frames=${window}`).first(),
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.locator("[data-mounted=true]")).toBeVisible({ timeout: 60_000 });
    latencies.push(Date.now() - t0);
    await forceGc();
    heaps.push(await jsHeap());
  }

  expect(baseline).toBeGreaterThan(0); // the heap read must be real, never a vacuous zero
  const heapMiB = (b: number) => Math.round(b / (1024 * 1024));
  console.log(
    JSON.stringify({
      spike: { frames: 10_000, atoms: 1 },
      baseline_heap_mib: heapMiB(baseline),
      scrub_heaps_mib: heaps.map(heapMiB),
      scrub_latency_ms: latencies,
      max_heap_mib: heapMiB(Math.max(...heaps)),
      last_heap_mib: heapMiB(heaps[heaps.length - 1]),
    }),
  );

  // A ceiling, not a rising line: every scrub heap under baseline + headroom, and the final scrub
  // within a headroom of the first — memory stays flat under the sliding window (the M61 budget).
  for (const h of heaps) {
    expect(h).toBeLessThan(baseline + CEILING_MIB_ABOVE_BASELINE * 1024 * 1024);
  }
  expect(heaps[heaps.length - 1]).toBeLessThan(
    heaps[0] + HEADROOM_MIB_FIRST_TO_LAST * 1024 * 1024,
  );
});
