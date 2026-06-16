import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Digitalfire Archive Viewer",
  description: "Local viewer for the digitalfire.com archive",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-stone-50 text-stone-900 antialiased">
        <header className="border-b border-stone-200 bg-white">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center gap-3">
            <Link href="/" className="font-semibold">
              🏺 Digitalfire Archive
            </Link>
            <span className="text-sm text-stone-400">local viewer, reads data/db/digitalfire.sqlite</span>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
