import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { pushRecent } from "@/lib/prefs/recents";
import { RecentsStrip } from "./RecentsStrip";

/**
 * The recent-files strip (S4, D246) — merges the browser's persisted recents with `/v1/history`.
 * This test pins the persisted half (the `merges with history` path is `lib/prefs/recents.ts`,
 * tested there); here the history query is stubbed to fail fast so only localStorage recents render,
 * and the "no recents → nothing rendered" rule holds.
 */
beforeEach(() => {
  window.localStorage.clear();
});

function renderStrip() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RecentsStrip />
    </QueryClientProvider>,
  );
}

describe("RecentsStrip", () => {
  it("renders nothing when there are no recents", () => {
    renderStrip();
    expect(screen.queryByLabelText("Recent files")).not.toBeInTheDocument();
  });

  it("links a persisted recent into its workspace", async () => {
    pushRecent({ key: "f123", href: "/f/f123", filename: "run.extxyz", format_id: "extxyz", last_seen_at: "2026-08-30T00:00:00Z" });
    renderStrip();
    const link = await screen.findByRole("link", { name: /run\.extxyz/ });
    expect(link).toHaveAttribute("href", "/f/f123");
    expect(screen.getByText("extxyz")).toBeInTheDocument();
  });
});