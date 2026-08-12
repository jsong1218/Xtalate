import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { armCompletionSignal, signalCompletion } from "./completionSignal";
import { NOTIFY_STORAGE_KEY, NotifyPreferenceProvider } from "./NotifyPreferenceProvider";
import { useCompletionSignal } from "./useCompletionSignal";

/**
 * The completion-signal hook (v1.1 M39-S4, C1): fires `signalCompletion()` exactly once on the
 * non-terminal → terminal transition of a job the user *armed* (launched via Convert) — never on a
 * re-render or re-poll of a terminal envelope, never for an *unarmed* job (a refresh or a shared
 * link to an already-finished job), and never while the persisted preference is off. The module's
 * signal is mocked; `armCompletionSignal`/`consumeCompletionSignalArm` (real `sessionStorage`) are
 * not — these tests pin the *gating*.
 */

vi.mock("./completionSignal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./completionSignal")>();
  return { ...actual, signalCompletion: vi.fn() };
});

const signalMock = vi.mocked(signalCompletion);

function wrapper({ children }: { children: ReactNode }) {
  return <NotifyPreferenceProvider>{children}</NotifyPreferenceProvider>;
}

function renderHookWithState(initial: { state: string | undefined; jobId: string }) {
  return renderHook(({ state, jobId }) => useCompletionSignal(state, jobId), {
    initialProps: initial,
    wrapper,
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  signalMock.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useCompletionSignal", () => {
  it("fires exactly once across the non-terminal → terminal transition of an armed job", () => {
    armCompletionSignal("job-1");
    const { rerender } = renderHookWithState({ state: "queued", jobId: "job-1" });
    rerender({ state: "running", jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();

    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);

    // A re-render / re-poll of the same terminal envelope cannot double-fire.
    rerender({ state: "completed", jobId: "job-1" });
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);
  });

  it("fires on any terminal outcome, not just completed", () => {
    armCompletionSignal("job-1");
    const { rerender } = renderHookWithState({ state: "running", jobId: "job-1" });
    rerender({ state: "failed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);

    // And a refusal arrives as a completed job — also terminal.
    armCompletionSignal("job-2");
    const second = renderHookWithState({ state: "running", jobId: "job-2" });
    second.rerender({ state: "completed", jobId: "job-2" });
    expect(signalMock).toHaveBeenCalledTimes(2);
  });

  it("never fires for an UNARMED job — a refresh / shared link is not a launch (Finding 1)", () => {
    // No arm: this is a reload of, or a link to, an already-finished job. The real job page always
    // loads cold, so the transition it sees is undefined → terminal — which must stay silent.
    const { rerender } = renderHookWithState({ state: undefined, jobId: "job-1" });
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
    // And a job that mounts already terminal (a synchronously-cached envelope) is silent too.
    renderHookWithState({ state: "completed", jobId: "job-2" });
    expect(signalMock).not.toHaveBeenCalled();
  });

  it("fires at most once even if the armed job page is later reloaded", () => {
    armCompletionSignal("job-1");
    const first = renderHookWithState({ state: "running", jobId: "job-1" });
    first.rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);

    // A fresh mount of the same finished job (a reload) finds the arm already consumed → silent.
    first.unmount();
    renderHookWithState({ state: undefined, jobId: "job-1" });
    renderHookWithState({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);
  });

  it("does not fire while the preference is off, and does not signal on a later unmute", () => {
    localStorage.setItem(NOTIFY_STORAGE_KEY, "0");
    armCompletionSignal("job-1");
    const { rerender } = renderHookWithState({ state: "queued", jobId: "job-1" });
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
    // The arm was consumed at the transition, so re-enabling later cannot resurrect a stale finish.
    expect(sessionStorage.getItem("xtalate-armed-jobs")).not.toContain("job-1");
  });

  it("starts a fresh watch when the job id changes", () => {
    armCompletionSignal("job-1");
    armCompletionSignal("job-2");
    const { rerender } = renderHookWithState({ state: "queued", jobId: "job-1" });
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);

    // The same component instance is reused for a new job — it must not inherit the fired flag.
    rerender({ state: "queued", jobId: "job-2" });
    rerender({ state: "completed", jobId: "job-2" });
    expect(signalMock).toHaveBeenCalledTimes(2);
  });

  it("handles a loading envelope (undefined state) without firing until the transition", () => {
    armCompletionSignal("job-1");
    const { rerender } = renderHookWithState({ state: undefined, jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);
  });
});
