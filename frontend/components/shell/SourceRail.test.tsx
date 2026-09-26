import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { pushRecent } from "@/lib/prefs/recents";
import { SourceRail } from "./SourceRail";

/**
 * The workbench Sources rail (v2.0 addendums, Task 9; design spec §"Shell architecture" — "Session
 * files with format badges; drop-to-add; collapsible"). It shares its data source with
 * `RecentsStrip` (this browser's localStorage recents merged with `/v1/history`) — see that
 * component's test for the merge behavior itself; this test pins the persisted half the same way
 * (the history query is left to fail fast against no server, exactly like `RecentsStrip.test.tsx`).
 */
beforeEach(() => {
  window.localStorage.clear();
});

function renderRail(
  props: Partial<{ activeFileId: string | null; collapsed: boolean; onToggle: () => void }> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const onToggle = props.onToggle ?? vi.fn();
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <SourceRail
        activeFileId={props.activeFileId ?? null}
        collapsed={props.collapsed ?? false}
        onToggle={onToggle}
      />
    </QueryClientProvider>,
  );
  return { onToggle, ...utils };
}

describe("SourceRail", () => {
  it("renders a labeled Sources landmark, distinct from the Inspector", () => {
    renderRail();
    expect(screen.getByRole("navigation", { name: "Sources" })).toBeInTheDocument();
  });

  it("shows the empty state when there are no session files", () => {
    renderRail();
    expect(screen.getByText("No files yet. Drop one to begin.")).toBeInTheDocument();
  });

  it("offers a simple add-file affordance in the empty state", () => {
    renderRail();
    expect(screen.getByRole("link", { name: /add file/i })).toHaveAttribute("href", "/");
  });

  it("lists a session file with its format badge, linking to its workspace", async () => {
    pushRecent({
      key: "f123",
      href: "/f/f123",
      filename: "run.extxyz",
      format_id: "extxyz",
      last_seen_at: "2026-08-30T00:00:00Z",
    });
    renderRail();
    const link = await screen.findByRole("link", { name: /run\.extxyz/ });
    expect(link).toHaveAttribute("href", "/f/f123");
    expect(screen.getByText("extxyz")).toBeInTheDocument();
  });

  it("marks the active file with aria-current, leaving other files unmarked", async () => {
    pushRecent({
      key: "f123",
      href: "/f/f123",
      filename: "run.extxyz",
      format_id: "extxyz",
      last_seen_at: "2026-08-30T00:00:00Z",
    });
    pushRecent({
      key: "f456",
      href: "/f/f456",
      filename: "other.xyz",
      format_id: "xyz",
      last_seen_at: "2026-08-30T00:01:00Z",
    });
    renderRail({ activeFileId: "f123" });
    const active = await screen.findByRole("link", { name: /run\.extxyz/ });
    expect(active).toHaveAttribute("aria-current", "page");
    const inactive = screen.getByRole("link", { name: /other\.xyz/ });
    expect(inactive).not.toHaveAttribute("aria-current");
  });

  it("exposes a collapse toggle button with aria-expanded reflecting the expanded state", () => {
    const { onToggle } = renderRail({ collapsed: false });
    const button = screen.getByRole("button", { name: /collapse/i });
    expect(button).toHaveAttribute("aria-expanded", "true");
    button.click();
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("hides the file list and shows an expand control when collapsed", async () => {
    pushRecent({
      key: "f123",
      href: "/f/f123",
      filename: "run.extxyz",
      format_id: "extxyz",
      last_seen_at: "2026-08-30T00:00:00Z",
    });
    renderRail({ collapsed: true });
    const button = screen.getByRole("button", { name: /expand/i });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: /run\.extxyz/ })).not.toBeInTheDocument();
  });
});
