import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEMO_PRIVACY_ACK_KEY, DemoPrivacyGate } from "./DemoPrivacyGate";

/**
 * The public-demo privacy gate (v1.2) is env-flagged like the {@link DemoBanner}: it must exist
 * only on the hosted demo and be **absent** everywhere else — a self-host must never gate its own
 * users. The load-bearing invariants, each a test:
 *  1. flag-off → nothing renders (a private instance shows no gate).
 *  2. flag-on, not yet acknowledged → a blocking dialog renders, stating that the demo is shared
 *     and that data is public, and it does not persist anything until the user acts.
 *  3. flag-on, acknowledged → nothing renders, and the acknowledgment persisted (once per browser).
 *  4. flag-on, already acknowledged in storage → nothing renders (the gate stays out of the way).
 *  5. Escape does not dismiss — acknowledgment is deliberate, not incidental.
 */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllEnvs();
  document.body.style.overflow = "";
});

describe("DemoPrivacyGate", () => {
  it("renders nothing when the demo flag is off", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "");
    render(<DemoPrivacyGate />);
    expect(screen.queryByTestId("demo-privacy-gate")).not.toBeInTheDocument();
  });

  it("shows an advisory privacy notice on the demo before it is acknowledged", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    render(<DemoPrivacyGate />);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    // The privacy consequence is stated, not merely "ephemeral": others can see the data.
    expect(dialog).toHaveTextContent(/anyone else using the\s+demo can see/i);
    expect(dialog).toHaveTextContent(/don.?t upload sensitive/i);
    // Nothing is persisted until the user actually acknowledges.
    expect(localStorage.getItem(DEMO_PRIVACY_ACK_KEY)).toBeNull();
  });

  it("dismisses and persists the acknowledgment once per browser", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    render(<DemoPrivacyGate />);

    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: /read the notice/i }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(DEMO_PRIVACY_ACK_KEY)).toBe("1");
  });

  it("renders nothing when this browser already acknowledged", () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    localStorage.setItem(DEMO_PRIVACY_ACK_KEY, "1");
    render(<DemoPrivacyGate />);
    expect(screen.queryByTestId("demo-privacy-gate")).not.toBeInTheDocument();
  });

  it("does not dismiss on Escape — the notice remains deliberate", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_BANNER", "1");
    render(<DemoPrivacyGate />);

    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(dialog).toBeInTheDocument();
    expect(localStorage.getItem(DEMO_PRIVACY_ACK_KEY)).toBeNull();
  });
});
