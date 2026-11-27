// Root layout: navigation + content.
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/layout/Sidebar";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Job Hunter",
  description: "Personal AI job-search assistant",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 md:flex-row md:px-6">
          <aside className="md:w-48 md:shrink-0">
            <p className="mb-4 px-3 text-lg font-semibold">AI Job Hunter</p>
            <Sidebar />
          </aside>
          <main className="min-w-0 flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}
