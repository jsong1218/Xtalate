"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";

/**
 * The public-demo privacy gate (v1.2): a blocking, must-acknowledge interstitial shown **once per
 * browser** before a visitor can use the hosted demo, so nobody uploads sensitive data without
 * first being told what the demo actually is.
 *
 * It exists because the hosted demo is a *single, shared, anonymous* instance: history is
 * instance-wide (no per-user scoping in anonymous mode — `XTALATE_API_KEYS=` empty), so any visitor
 * can see another visitor's conversions and download their outputs, and the free-tier container is
 * ephemeral with only a lazy expiry horizon — bytes are not erased on a guaranteed schedule. The
 * always-on {@link DemoBanner} states the ephemeral posture in passing; this gate makes the privacy
 * consequence impossible to miss and requires a deliberate acknowledgment (P1: never let a user be
 * surprised by what happens to their data).
 *
 * Gated on the **same** `NEXT_PUBLIC_DEMO_BANNER` build flag as the banner (inlined at build time):
 * the baked demo image sets it, a self-host never does — a private instance you control shows no
 * gate at all. The acknowledgment persists in `localStorage` (the app's existing preference
 * pattern), so it blocks once and then stays out of the way; clearing storage re-arms it.
 *
 * A client component on purpose: the flag is a `NEXT_PUBLIC_` value, and the acknowledgment lives in
 * `localStorage`, which is read in an effect — so the server render and the first client render both
 * produce nothing (no hydration mismatch), and the dialog appears immediately after hydration,
 * before any upload interaction is possible.
 */

export const DEMO_PRIVACY_ACK_KEY = "xtalate-demo-privacy-ack";

export function DemoPrivacyGate() {
  const isDemo = process.env.NEXT_PUBLIC_DEMO_BANNER === "1";
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const acknowledgeRef = useRef<HTMLButtonElement>(null);

  // Decide visibility on the client only: show the gate on the demo when this browser has not yet
  // acknowledged it. Runs after hydration so `localStorage` is available and no SSR mismatch occurs.
  useEffect(() => {
    if (!isDemo) return;
    let acknowledged = false;
    try {
      acknowledged = localStorage.getItem(DEMO_PRIVACY_ACK_KEY) === "1";
    } catch {
      // Storage unavailable (private mode): fail safe by showing the warning rather than hiding it.
      acknowledged = false;
    }
    if (!acknowledged) setOpen(true);
  }, [isDemo]);

  const acknowledge = useCallback(() => {
    try {
      localStorage.setItem(DEMO_PRIVACY_ACK_KEY, "1");
    } catch {
      // Best-effort: if the choice can't persist, the gate simply reappears next visit — never worse.
    }
    setOpen(false);
  }, []);

  // While open: lock body scroll, move focus into the dialog, and keep Tab within it. Escape does
  // *not* dismiss — this is a deliberate acknowledgment, not an incidental popover.
  useEffect(() => {
    if (!open) return;
    acknowledgeRef.current?.focus();

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        return;
      }
      if (event.key !== "Tab") return;
      const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled])',
      );
      if (!focusables || focusables.length === 0) return;
      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!isDemo || !open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      // A backdrop click must not dismiss: acknowledgment is required, so the scrim is inert.
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="demo-privacy-title"
        aria-describedby="demo-privacy-body"
        data-testid="demo-privacy-gate"
        className="w-full max-w-lg rounded-xl border border-line-strong bg-surface p-6 shadow-xl"
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-warning">
          Public demo — read before uploading
        </p>
        <h2 id="demo-privacy-title" className="mt-2 text-xl font-semibold text-strong">
          Don&rsquo;t upload sensitive or private data
        </h2>
        <div id="demo-privacy-body" className="mt-3 space-y-3 text-sm text-body">
          <p>
            This is a <strong className="text-strong">shared, anonymous demo</strong>. It has no
            accounts and no per-user privacy: files you convert, their names, and the conversion
            reports appear in a history that <strong className="text-strong">anyone else using the
            demo can see</strong>, and your converted output can be downloaded by them.
          </p>
          <p>
            It is also <strong className="text-strong">ephemeral</strong> — data lives only until the
            instance restarts and is not guaranteed to be erased on a schedule. Treat anything you
            upload here as public.
          </p>
          <p>
            For confidential, proprietary, or personal data, run Xtalate locally (the CLI never
            uploads a file anywhere) or{" "}
            <Link
              href="/docs/self-hosting"
              className="underline underline-offset-2 hover:text-strong"
            >
              self-host your own private instance
            </Link>
            .
          </p>
        </div>
        <div className="mt-6 flex justify-end">
          <Button ref={acknowledgeRef} onClick={acknowledge}>
            I understand — continue
          </Button>
        </div>
      </div>
    </div>
  );
}
