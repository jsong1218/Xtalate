"use client";

import { useEffect, useRef, useState } from "react";
import { CommandPalette } from "./CommandPalette";

/**
 * The ⌘K trigger (UI redesign S4, D246) — the client island the app-shell header renders: a
 * visible "Search" button plus the global ⌘K / Ctrl+K shortcut to open the command palette. Its
 * `aria-expanded`/`aria-haspopup` describe the dialog it toggles, and focus is handed to (and
 * returned from) the palette via the dialog itself, so a keyboard user's place in the page
 * survives an open-close.
 */
export function CommandPaletteTrigger() {
  const [open, setOpen] = useState(false);
  const openRef = useRef(false);
  openRef.current = open;

  // Global open shortcut — one listener, reads the live `open` from the ref so Escape closes is
  // always current. Deliberately suppressed while typing in an input/textarea/editable so ⌘K inside
  // a search field never hijacks the keystroke (the same guard `/` uses on the report tab).
  useEffect(() => {
    function isEditable(target: EventTarget | null): boolean {
      if (!(target instanceof HTMLElement)) return false;
      return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
    }
    function onKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (!isEditable(e.target)) setOpen((v) => !v);
      } else if (e.key === "Escape" && openRef.current) {
        e.preventDefault();
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        data-testid="command-palette-trigger"
        className="inline-flex items-center gap-2 rounded-md border border-line px-2.5 py-1 text-sm text-body transition-colors hover:bg-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        <span aria-hidden="true">⌘</span>
        <span className="hidden sm:inline">Search</span>
        <kbd className="rounded border border-line px-1 text-xs text-faint">K</kbd>
      </button>
      <CommandPalette open={open} onClose={() => setOpen(false)} />
    </>
  );
}