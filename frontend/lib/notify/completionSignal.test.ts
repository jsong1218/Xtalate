import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The completion-signal module (v1.1 M39-S4, C1), with the two browser APIs mocked: WebAudio
 * (`AudioContext`) and the Notification API. Neither exists in jsdom, and neither can be asserted
 * in Playwright — the sound and the OS notification are browser-owned surfaces — so this is the
 * suite that proves the module's contract: a synthesized chime (two oscillators, one shared
 * context, resumed by the gesture), permission requested at the right moments and never on load,
 * and every path a graceful no-op when a channel is unavailable.
 *
 * The module holds one shared `AudioContext` in module state (deliberately — the gesture that arms
 * it and the page that plays it are different pages), so each test loads a fresh module with
 * `vi.resetModules()` to start from a clean context.
 */

interface FakeOscillator {
  type: string;
  frequency: { value: number };
  connect: ReturnType<typeof vi.fn>;
  start: ReturnType<typeof vi.fn>;
  stop: ReturnType<typeof vi.fn>;
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  static reset(): void {
    FakeAudioContext.instances = [];
  }
  constructor() {
    FakeAudioContext.instances.push(this);
  }
  state: string = "suspended";
  currentTime = 0;
  destination = {};
  oscillators: FakeOscillator[] = [];
  resume = vi.fn(async () => {
    this.state = "running";
  });
  createOscillator(): FakeOscillator {
    const oscillator: FakeOscillator = {
      type: "",
      frequency: { value: 0 },
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    };
    this.oscillators.push(oscillator);
    return oscillator;
  }
  createGain() {
    return { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn() };
  }
}

interface FakeNotificationConstructor {
  title: string;
  body: string;
  onclick: (() => void) | null;
}

class FakeNotification {
  static instances: FakeNotificationConstructor[] = [];
  static permission: NotificationPermission = "default";
  static requestPermission = vi.fn(async (): Promise<NotificationPermission> => "granted");
  static reset(): void {
    FakeNotification.instances = [];
    FakeNotification.permission = "default";
    FakeNotification.requestPermission = vi.fn(
      async (): Promise<NotificationPermission> => "granted",
    );
  }
  title: string;
  body: string;
  onclick: (() => void) | null = null;
  constructor(title: string, options?: { body?: string }) {
    this.title = title;
    this.body = options?.body ?? "";
    FakeNotification.instances.push(this);
  }
  close(): void {}
}

beforeEach(() => {
  vi.resetModules();
  sessionStorage.clear();
  FakeAudioContext.reset();
  FakeNotification.reset();
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("Notification", FakeNotification);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function loadModule() {
  return await import("./completionSignal");
}

describe("playChime / unlockAudio (WebAudio)", () => {
  it("plays a synthesized two-tone chime on one shared AudioContext", async () => {
    const { playChime } = await loadModule();
    playChime();

    expect(FakeAudioContext.instances).toHaveLength(1);
    const ctx = FakeAudioContext.instances[0]!;
    // The two tones of the rising fourth.
    expect(ctx.oscillators.map((o) => o.frequency.value)).toEqual([659.25, 880]);
    for (const osc of ctx.oscillators) {
      expect(osc.start).toHaveBeenCalled();
      expect(osc.stop).toHaveBeenCalled();
    }
  });

  it("unlockAudio resumes a suspended context and is idempotent afterwards", async () => {
    const { unlockAudio } = await loadModule();
    unlockAudio();
    expect(FakeAudioContext.instances).toHaveLength(1);
    expect(FakeAudioContext.instances[0]!.state).toBe("running");

    unlockAudio();
    unlockAudio();
    // One shared context for the session; repeated gestures are no-ops.
    expect(FakeAudioContext.instances).toHaveLength(1);
    expect(FakeAudioContext.instances[0]!.resume).toHaveBeenCalledTimes(1);
  });

  it("playChime is a graceful no-op when WebAudio is unavailable", async () => {
    const { playChime } = await loadModule();
    vi.unstubAllGlobals(); // remove the AudioContext stub → feature-detect fails
    expect(() => playChime()).not.toThrow();
  });
});

describe("notify / requestNotificationPermission (Notification API)", () => {
  it("requests permission on first use, then posts the notification on grant", async () => {
    const { notify } = await loadModule();
    await notify("Xtalate", "Your conversion finished.");

    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1);
    expect(FakeNotification.instances).toHaveLength(1);
    expect(FakeNotification.instances[0]!.title).toBe("Xtalate");
    expect(FakeNotification.instances[0]!.body).toBe("Your conversion finished.");
  });

  it("posts directly when permission is already granted — no re-request", async () => {
    FakeNotification.permission = "granted";
    const { notify } = await loadModule();
    await notify("Xtalate", "Your conversion finished.");

    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
    expect(FakeNotification.instances).toHaveLength(1);
  });

  it("is a silent no-op when permission is denied (the sound still plays)", async () => {
    FakeNotification.permission = "denied";
    const { notify } = await loadModule();
    await notify("Xtalate", "Your conversion finished.");

    expect(FakeNotification.requestPermission).not.toHaveBeenCalled();
    expect(FakeNotification.instances).toHaveLength(0);
  });

  it("requestNotificationPermission reports whether notifications may post", async () => {
    const { requestNotificationPermission } = await loadModule();
    await expect(requestNotificationPermission()).resolves.toBe(true);

    FakeNotification.requestPermission.mockResolvedValueOnce("denied");
    // The previous call already moved permission to granted; force the default path again.
    FakeNotification.permission = "default";
    await expect(requestNotificationPermission()).resolves.toBe(false);
  });

  it("notify is a graceful no-op when the Notification API is unavailable", async () => {
    const { notify } = await loadModule();
    vi.unstubAllGlobals(); // remove the Notification stub → feature-detect fails
    await expect(notify("Xtalate", "Your conversion finished.")).resolves.toBeUndefined();
  });
});

describe("signalCompletion", () => {
  it("fires both channels together, each independently degrading", async () => {
    const { signalCompletion } = await loadModule();
    signalCompletion();

    // The chime is synchronous; the notification posts after the (mocked) permission round-trip.
    expect(FakeAudioContext.instances).toHaveLength(1);
    await vi.waitFor(() => expect(FakeNotification.instances).toHaveLength(1));
    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(1);
  });
});

describe("armCompletionSignal / consumeCompletionSignalArm (the Finding-1 launch guard)", () => {
  it("consumes an armed job exactly once, then reports it unarmed", async () => {
    const { armCompletionSignal, consumeCompletionSignalArm } = await loadModule();
    armCompletionSignal("job-1");
    expect(consumeCompletionSignalArm("job-1")).toBe(true);
    // A second consume (a reload of the same finished job) finds nothing armed.
    expect(consumeCompletionSignalArm("job-1")).toBe(false);
  });

  it("reports an unarmed job as false without disturbing others", async () => {
    const { armCompletionSignal, consumeCompletionSignalArm } = await loadModule();
    armCompletionSignal("job-1");
    // A different id (a shared link to some other finished job) was never armed.
    expect(consumeCompletionSignalArm("job-2")).toBe(false);
    // Arming is idempotent and independent, so job-1 still consumes cleanly.
    armCompletionSignal("job-1");
    expect(consumeCompletionSignalArm("job-1")).toBe(true);
  });

  it("tolerates a corrupt storage value as simply unarmed (best-effort, never throws)", async () => {
    sessionStorage.setItem("xtalate-armed-jobs", "{not json");
    const { consumeCompletionSignalArm } = await loadModule();
    expect(() => consumeCompletionSignalArm("job-1")).not.toThrow();
    expect(consumeCompletionSignalArm("job-1")).toBe(false);
  });
});
