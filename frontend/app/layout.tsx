import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "Xtalate — loss-aware file conversion",
  description:
    "The trusted translation layer between computational chemistry file formats: a converter that tells you exactly what it kept, what it lost, and why.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-slate-900 antialiased">
        <Providers>
          <div className="mx-auto max-w-5xl px-4 py-8">{children}</div>
        </Providers>
      </body>
    </html>
  );
}
