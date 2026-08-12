import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { signalCompletion } from "./completionSignal";
import { NOTIFY_STORAGE_KEY, NotifyPreferenceProvider } from "./NotifyPreferenceProvider";
import { useCompletionSignal } from "./useCompletionSignal";

/**
 * The completion-signal hook (v1.1 M39-S4, C1): fires `signalCompletion()` exactly once on the
 * non-terminal → terminal transition of a specific job — never on a re-render or re-poll of a
 * terminal envelope, never for a job that mounts already terminal (a shared link), and never while
 * the persisted preference is off. The module's signal is mocked; these tests pin the *gating*.
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
  signalMock.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("useCompletionSignal", () => {
  it("fires exactly once across the non-terminal → terminal transition", () => {
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
    const { rerender } = renderHookWithState({ state: "running", jobId: "job-1" });
    rerender({ state: "failed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);

    // And a refusal arrives as a completed job — also terminal.
    const second = renderHookWithState({ state: "running", jobId: "job-2" });
    second.rerender({ state: "completed", jobId: "job-2" });
    expect(signalMock).toHaveBeenCalledTimes(2);
  });

  it("never fires for a job that mounts already terminal (a shared link is not a transition)", () => {
    const { rerender } = renderHookWithState({ state: "completed", jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
  });

  it("does not fire while the preference is off", () => {
    localStorage.setItem(NOTIFY_STORAGE_KEY, "0");
    const { rerender } = renderHookWithState({ state: "queued", jobId: "job-1" });
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
  });

  it("starts a fresh watch when the job id changes", () => {
    const { rerender } = renderHookWithState({ state: "queued", jobId: "job-1" });
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);

    // The same component instance is reused for a new job — it must not inherit the fired flag.
    rerender({ state: "queued", jobId: "job-2" });
    rerender({ state: "completed", jobId: "job-2" });
    expect(signalMock).toHaveBeenCalledTimes(2);
  });

  it("handles a loading envelope (undefined state) without firing until the transition", () => {
    const { rerender } = renderHookWithState({ state: undefined, jobId: "job-1" });
    expect(signalMock).not.toHaveBeenCalled();
    rerender({ state: "completed", jobId: "job-1" });
    expect(signalMock).toHaveBeenCalledTimes(1);
  });
});
