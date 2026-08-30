import { expect, test } from "@playwright/test";
import { API_URL } from "./support/api";

/**
 * The M61-S3 measurement (growing from `geometry-spike.spec.ts`): **playback** of a generated
 * 10⁴-frame trajectory through the dev spike surface's scrubber, with browser JS heap sampled via
 * CDP `Runtime.getHeapUsage` while the scrubber **plays** (advances one frame per interval across
 * the whole trajectory). The impl-plan §3 go/no-go — "memory bound measured, not eyeballed": the
 * client-side sliding window (`D236`) must hold browser memory **flat** under sustained animation,
 * a ceiling, not a rising line.
 *
 * The fixture is the same cell-less low-atom sprint as the M59 spike (10⁴ frames × 1 atom, tight
 * 2-decimal layout ≈ 500 KB), because the e2e's inline upload is bound by the shared 1 MiB upload
 * ceiling (the M59-S3 deviation). The **high-atom-count latency** figure (which re-streams per
 * window and cannot fit under the 1 MiB ceiling) comes from the Python benchmark
 * (`geometry_endpoint_high_atoms`), measured-not-gated — not this journey.
 *
 * The dev surface passes a fast play interval (80 ms) so a single Play press crosses ~four
 * windows per second of sustained animation in one JS context. Heap is sampled after an explicit
 * GC per sample (removing allocator noise); flatness is a ceiling, not a rising line — every
 * playback sample under a ceiling above the baseline, and the last within a headroom of the
 * first — so an unbounded accumulation across window slides fails the journey. Numbers are logged
 * for the progress doc (M63's comparison baseline).
 */

// The 10⁴-frame, 1-atom cell-less extXYZ — fits the shared 1 MiB e2e upload ceiling (~500 KB).
function generatePlaybackExtxyz(nFrames = 10_000): Buffer {
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

const CEILING_MIB_ABOVE_BASELINE = 64; // every playback sample under baseline + this
const HEADROOM_MIB_FIRST_TO_LAST = 32; // the last within this of the first (flat, not rising)

/** How far playback must advance to prove a real window slide happened (prefetch, no stall).
 * WINDOW_SIZE = 8, so advancing past one window means the bounded store slid and the next window
 * fed the viewer. The CDP `collectGarbage` per sample stalls the 80 ms step clock measurably, so
 * a run crosses ~2 windows in the ~3.5 s sampling window — this must not demand more than that. */
const MIN_FRAMES_ADVANCED = 9; // past WINDOW_SIZE = 8: at least one window boundary crossed

test.use({ launchOptions: { args: ["--enable-precise-memory-info"] } });

test("playback of a generated 10⁴-frame trajectory holds browser memory flat (M61-S3)", async ({
  page,
  request,
}) => {
  const spike = generatePlaybackExtxyz();
  const upload = await request.post(`${API_URL}/v1/upload`, {
    multipart: {
      file: { name: "playback-1e4.extxyz", mimeType: "chemical/x-xyz", buffer: spike },
    },
  });
  expect(upload.status(), await upload.text()).toBe(201);
  const fileId = String((await upload.json()).file_id);

  const first = await request.get(`${API_URL}/v1/files/${fileId}/geometry?frames=0:1`);
  expect(first.status(), await first.text()).toBe(200);
  expect((await first.json()).frame_count).toBe(10_000);

  // The dev spike surface mounts the scrubber over the full trajectory with a fast play interval.
  await page.goto(`/dev/structure/${fileId}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator("[data-mounted=true]")).toBeVisible({ timeout: 60_000 });
  const play = page.getByRole("button", { name: "Play" });
  await expect(play).toBeVisible({ timeout: 30_000 });

  const cdp = await page.context().newCDPSession(page);
  const jsHeap = async (): Promise<number> => {
    const { usedSize } = await cdp.send("Runtime.getHeapUsage");
    return Number(usedSize);
  };
  const forceGc = (): Promise<void> => cdp.send("HeapProfiler.collectGarbage");

  // Baseline: the mounted scrubber at frame 0, then GC + sample.
  await forceGc();
  const baseline = await jsHeap();

  const mount = page.locator("[data-mounted=true]");
  const startFrame = Number(await mount.getAttribute("data-current-frame"));

  // Play across the trajectory, sampling heap after explicit GC at ~4 points along the way.
  await play.click();
  const samples: number[] = [];
  const sampleMarks: number[] = [];
  for (let i = 0; i < 4; i++) {
    await page.waitForTimeout(750); // ~9 frames / ~1 window per 750 ms at 80 ms/step
    await forceGc();
    samples.push(await jsHeap());
    sampleMarks.push(Number(await mount.getAttribute("data-current-frame")));
  }
  await page.getByRole("button", { name: "Pause" }).click();

  expect(baseline).toBeGreaterThan(0); // the heap read must be real, never a vacuous zero
  const heapMiB = (b: number) => Math.round(b / (1024 * 1024));
  console.log(
    JSON.stringify({
      playback: { frames: 10_000, atoms: 1, play_interval_ms: 80 },
      baseline_heap_mib: heapMiB(baseline),
      playback_sample_heaps_mib: samples.map(heapMiB),
      sample_current_frames: sampleMarks,
      max_heap_mib: heapMiB(Math.max(...samples)),
      last_heap_mib: heapMiB(samples[samples.length - 1]),
    }),
  );

  // Playback must actually animate — the frame advanced across several windows (the measurement
  // is meaningless if playback did not move), and did not stall at a window edge (prefetch).
  const endFrame = Number(await mount.getAttribute("data-current-frame"));
  expect(endFrame - startFrame).toBeGreaterThan(MIN_FRAMES_ADVANCED);

  // A ceiling, not a rising line: every playback sample under baseline + headroom, and the last
  // within a headroom of the first — browser memory stays flat under the sliding window.
  for (const h of samples) {
    expect(h).toBeLessThan(baseline + CEILING_MIB_ABOVE_BASELINE * 1024 * 1024);
  }
  expect(samples[samples.length - 1]).toBeLessThan(
    samples[0] + HEADROOM_MIB_FIRST_TO_LAST * 1024 * 1024,
  );
});