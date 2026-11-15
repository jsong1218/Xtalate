"use client";

import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { IconButton } from "./IconButton";

/**
 * A modal sheet (redesign §7, §9): the full-width form the drawers take under 1024 px and the `?`
 * shortcut sheet. `role="dialog"` + `aria-modal`, named by its title; focus moves to the panel on
 * open and returns to the previously focused element on close; Escape and the close button both
 * call `onClose`. Mounted only while open, and the backdrop swallows pointer events behind it.
 */
export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  side?: "right" | "bottom";
  children: ReactNode;
  className?: string;
}

export function Sheet({ open, onClose, title, side = "right", children, className }: SheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const opener = openerRef.current;
      if (opener instanceof HTMLElement) opener.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const titleId = `sheet-title-${title.replace(/\s+/g, "-").toLowerCase()}`;
  const placement =
    side === "right"
      ? "inset-y-0 right-0 w-full max-w-md border-l"
      : "inset-x-0 bottom-0 max-h-[80vh] border-t";

  return (
    <div className="fixed inset-0 z-50">
      <div aria-hidden="true" className="absolute inset-0 bg-inverse/40" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`absolute ${placement} flex flex-col border-wb-hairline bg-wb-panel shadow-lg focus-visible:outline-none ${className ?? ""}`}
      >
        <header className="flex items-center justify-between gap-4 border-b border-wb-hairline px-4 py-3">
          <h2 id={titleId} className="text-sm font-semibold text-strong">
            {title}
          </h2>
          <IconButton icon={X} label={`Close ${title}`} onClick={onClose} />
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
      </div>
    </div>
  );
}
