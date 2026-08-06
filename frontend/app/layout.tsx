import type { Metadata } from "next";
import type { ReactNode } from "react";
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
          <div className="mx-auto max-w-5xl px-4 py-8">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
