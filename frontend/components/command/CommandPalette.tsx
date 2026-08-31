"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { capabilitiesQuery } from "@/lib/api/queries";
import { fuzzySearch, type CommandCandidate } from "@/lib/command/fuzzy";
import { listRecents } from "@/lib/prefs/recents";
import type { CapabilitiesMap } from "@/lib/capabilities/types";

/**
 * The command palette (UI redesign S4, D246; design spec §6 — ⌘K, fuzzy jump, client-side). A
 * focus-trapped, ARIA-correct modal dialog that fuzzy-jumps to formats, docs, recent files, and
 * actions. It reads only client-side data it already has — `/v1/capabilities` (via react-query)
 * and the recents list (localStorage) — so it needs no new backend route.
 *
 * Accessibility is not cosmetic here: the dialog is `role="dialog"` + `aria-modal` with a labelled
 * name, focus is **trapped** (Tab/Shift-Tab cycle inside; it never leaves into the page behind),
 * Escape closes, the trigger's `aria-expanded`/`aria-haspopup` describe it, and focus returns to
 * the trigger on close (the palette's test + the e2e journey pin this). The palette opens with ⌘K
 * (Mac) or Ctrl+K, and the visible trigger button carries the same shortcut label.
 *
 * The fuzzy matcher is `lib/command/fuzzy.ts` (in-repo, pinned by tests). Choosing a result
 * navigates (router.push). Results are grouped: **Formats**, **Docs**, **Recent files**, **Actions**;
 * an empty query shows every candidate ("everything" is the fallback, per `fuzzy.test.ts`).
 */

/** A static action the palette can jump to (navigations only — no hidden behavior). */
const ACTIONS: CommandCandidate<{ href: string }>[] = [
  { id: "act-convert", label: "Convert a file", search: "Convert upload", payload: { href: "/" } },
  { id: "act-formats", label: "Go to Formats", search: "Formats list formats", payload: { href: "/formats" } },
  { id: "act-history", label: "Go to History", search: "History conversions", payload: { href: "/history" } },
  { id: "act-docs", label: "Go to Docs", search: "Docs documentation", payload: { href: "/docs" } },
];

/** The docs pages reachable from the header — listed as palette destinations. */
const DOCS: CommandCandidate<{ href: string }>[] = [
  { id: "doc-errors", label: "Docs · Error reference", search: "Error reference docs errors", payload: { href: "/docs/errors" } },
  { id: "doc-guide", label: "Docs · Conversion guide", search: "guide docs", payload: { href: "/docs" } },
];

interface Grouped {
  group: string;
  items: { candidate: CommandCandidate<{ href: string }>; highlight: readonly number[] }[];
}

export function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState(0);
  const lastActive = useRef<Element | null>(null);

  // The focus trap, on the **panel** (the ancestor of both the input and the row list — a trap on
  // the list alone can never catch a Tab leaving the input, since those are siblings). Tab cycles
  // input ↔ rows; it can never land on the page behind the dialog. Shift+Tab reverses.
  function trapTab(e: React.KeyboardEvent) {
    if (e.key !== "Tab") return;
    const panel = panelRef.current;
    const input = inputRef.current;
    if (!panel) return;
    const rows = Array.from(panel.querySelectorAll<HTMLElement>("[data-result-row]"));
    const focusables = input ? [input, ...rows] : rows;
    if (focusables.length === 0) {
      e.preventDefault();
      return;
    }
    e.preventDefault();
    const idx = focusables.indexOf(document.activeElement as HTMLElement);
    const nextIdx = e.shiftKey
      ? idx <= 0
        ? focusables.length - 1
        : idx - 1
      : (idx + 1) % focusables.length;
    focusables[nextIdx].focus();
  }

  // "Open report as JSON" action context — none globally; the per-report export already covers it.

  // Fetch `/v1/capabilities` only while open — a closed palette should not poll the network.
  const capabilities = useQuery({ ...capabilitiesQuery(), enabled: open });
  const recents = useMemo(() => listRecents(), []);
  const sameRecents = useMemo(
    () =>
      recents.map<CommandCandidate<{ href: string }>>((r) => ({
        id: `recent-${r.key}`,
        label: r.filename,
        search: `${r.filename} ${r.format_id}`,
        payload: { href: r.href },
      })),
    [recents],
  );

  const formatCandidates = useMemo(() => {
    const map = (capabilities.data ?? {}) as CapabilitiesMap;
    const out: CommandCandidate<{ href: string }>[] = [];
    for (const [formatId, dirs] of Object.entries(map)) {
      const name = dirs?.write?.format_name ?? dirs?.read?.format_name ?? formatId;
      out.push({ id: `fmt-${formatId}`, label: name, search: `${name} ${formatId}`, payload: { href: `/formats/${formatId}` } });
    }
    return out;
  }, [capabilities.data]);

  // Reset on open/close, and put focus in the input.
  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      lastActive.current = document.activeElement;
      // The dialog's DOM is committed before this effect runs, so the ref is already valid — focus
      // synchronously rather than via setTimeout(0), which would hand the palette's focus race
      // back to the scheduler (a real source of flakiness under compile/navigation load: the
      // dialog was visible but focus had not yet landed when a test or user hit it).
      inputRef.current?.focus();
    }
    return undefined;
  }, [open]);

  const results = useMemo(() => {
    const groups: Grouped[] = [];
    const push = (group: string, candidates: CommandCandidate<{ href: string }>[]) => {
      const rank = fuzzySearch(query, candidates);
      if (rank.length > 0) groups.push({ group, items: rank.map((r) => ({ candidate: r.candidate, highlight: r.match.highlight })) });
    };
    push("Formats", formatCandidates);
    push("Recent files", sameRecents);
    push("Docs", DOCS);
    push("Actions", ACTIONS);
    return groups;
  }, [query, formatCandidates, sameRecents]);

  const flat = results.flatMap((g) => g.items);
  const activeItem = flat[cursor];

  useEffect(() => {
    setCursor((c) => Math.min(c, Math.max(flat.length - 1, 0)));
  }, [flat.length]);

  function choose(next: { href: string }) {
    // Close, then navigate. The dialog unmounts on the next render (focus returns to the trigger);
    // the navigation is synchronous so a result never feels laggy.
    onClose();
    router.push(next.href);
  }

  // A running index across the flat rendering, so `data-active` maps 1:1 to the cursor without
  // relying on object identity.
  let renderIndex = -1;

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close command palette"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/40"
      />
      {/* Panel — the focus-trap owner: its Tab handler covers the input AND the result rows. */}
      <div
        ref={panelRef}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={trapTab}
        className="relative w-full max-w-xl overflow-hidden rounded-xl border border-line bg-surface shadow-xl focus-within:ring-2 focus-within:ring-accent"
      >
        <div className="flex items-center gap-2 border-b border-line px-3">
          <span aria-hidden="true" className="text-faint">
            ⌘
          </span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => (flat.length === 0 ? 0 : (c + 1) % flat.length));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => (flat.length === 0 ? 0 : (c - 1 + flat.length) % flat.length));
              } else if (e.key === "Enter") {
                if (activeItem) {
                  e.preventDefault();
                  choose(activeItem.candidate.payload);
                }
              }
            }}
            placeholder="Jump to a format, doc, recent file or action…"
            aria-label="Search commands"
            className="w-full bg-transparent py-3 text-sm outline-none placeholder:text-faint"
          />
          <kbd className="shrink-0 rounded border border-line px-1.5 py-0.5 text-xs text-faint">esc</kbd>
        </div>

        <div id="command-list" ref={listRef} className="max-h-[50vh] overflow-y-auto py-2">
          {flat.length === 0 ? (
            <p className="px-4 py-2 text-sm text-faint" role="status">
              No matches.
            </p>
          ) : (
            results.map((group) => (
              <div key={group.group}>
                <p className="px-4 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-faint">
                  {group.group}
                </p>
                {group.items.map(({ candidate, highlight }) => {
                  renderIndex += 1;
                  const isActive = renderIndex === cursor;
                  return (
                    <button
                      key={candidate.id}
                      type="button"
                      data-result-row
                      data-active={isActive}
                      aria-selected={isActive}
                      role="option"
                      onClick={() => choose(candidate.payload)}
                      onMouseEnter={() => setCursor(renderIndex)}
                      className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm ${
                        isActive ? "bg-raised text-strong" : "text-body"
                      }`}
                    >
                      <span className="truncate">{highlightedLabel(candidate.label, highlight)}</span>
                      <span className="ml-auto shrink-0 text-xs text-faint">{candidate.payload.href}</span>
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/** Render a label with its fuzzy-matched characters highlighted (offset by `<mark>` in accent). */
function highlightedLabel(label: string, highlight: readonly number[]): React.ReactNode {
  const set = new Set(highlight);
  return (
    <>
      {label.split("").map((ch, i) =>
        set.has(i) ? (
          <mark key={i} className="rounded-sm bg-accent/10 text-accent-text">
            {ch}
          </mark>
        ) : (
          <span key={i}>{ch}</span>
        ),
      )}
    </>
  );
}