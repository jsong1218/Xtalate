import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppHeader } from "@/components/shell/AppHeader";
import { DemoBanner } from "@/components/shell/DemoBanner";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Xtalate — loss-aware file conversion",
  description:
    "The trusted translation layer between computational chemistry file formats: a converter that tells you exactly what it kept, what it lost, and why.",
};

// Applied before first paint so a persisted dark choice never flashes light. Kept in sync with
// THEME_STORAGE_KEY in lib/theme/ThemeProvider.tsx; default is light. Runs at the top of <body> so it
// executes before the styled content is painted.
const noFlashThemeScript = `(function(){try{var t=localStorage.getItem('xtalate-theme');document.documentElement.setAttribute('data-theme',t==='dark'?'dark':'light');}catch(e){document.documentElement.setAttribute('data-theme','light');}})();`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: the no-flash script above sets data-theme before React hydrates, so
    // the server-rendered attribute may differ from the client's persisted choice — expected.
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <body className="min-h-screen bg-surface text-strong antialiased">
        <script dangerouslySetInnerHTML={{ __html: noFlashThemeScript }} />
        <Providers>
          {/*
            Skip link — the first focusable element on every page, so a keyboard or screen-reader
            user can jump past the shell's nav straight to the page content. Visually hidden until
            focused (Part 7 §4). The target below is focusable (tabIndex -1) so activating this moves
            focus there, not just the scroll position.
          */}
          <a
            href="#main-content"
            className="sr-only focus-visible:not-sr-only focus-visible:absolute focus-visible:left-4 focus-visible:top-4 focus-visible:z-50 focus-visible:rounded-md focus-visible:bg-inverse focus-visible:px-4 focus-visible:py-2 focus-visible:text-sm focus-visible:font-medium focus-visible:text-inverse-fg"
          >
            Skip to main content
          </a>
          {/* The public-demo banner (v1.1 M39-S1): rendered only when NEXT_PUBLIC_DEMO_BANNER is
              set, i.e. only on the Hugging Face Spaces demo image — a self-host never sees it. */}
          <DemoBanner />
          <AppHeader />
          <div
            id="main-content"
            tabIndex={-1}
            className="mx-auto max-w-5xl px-4 py-8 focus:outline-none"
          >
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
