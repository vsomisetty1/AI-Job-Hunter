"use client";

// Shared frame for every package page: header, status, actions, tabs.
import Link from "next/link";
import type { ReactNode } from "react";

import { ScoreBadge } from "@/components/jobs/ScoreBadge";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { usePackage } from "@/hooks/usePackages";
import { errorMessage } from "@/lib/api/client";
import type { PackageDetail } from "@/types";

import { PackageActions } from "./PackageActions";
import { PackageStatusBadge } from "./PackageStatusBadge";

export type PackageTab = "overview" | "resume" | "diff" | "cover-letter" | "answers";

const TABS: { key: PackageTab; label: string; path: string }[] = [
  { key: "overview", label: "Review", path: "" },
  { key: "resume", label: "Tailored resume", path: "/resume" },
  { key: "diff", label: "Changes", path: "/diff" },
  { key: "cover-letter", label: "Cover letter", path: "/cover-letter" },
  { key: "answers", label: "Answers", path: "/answers" },
];

export function PackageShell({
  id,
  tab,
  children,
}: {
  id: string;
  tab: PackageTab;
  children: (pkg: PackageDetail, refresh: (p?: PackageDetail) => void) => ReactNode;
}) {
  const { data: pkg, error, mutate } = usePackage(id);
  const refresh = (p?: PackageDetail) => void (p ? mutate(p, { revalidate: false }) : mutate());

  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  if (!pkg) return <p className="text-sm text-zinc-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Link href="/packages" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
          ← Approval queue
        </Link>
        <h1 className="flex flex-wrap items-center gap-3 text-2xl font-semibold">
          {pkg.job_title} <ScoreBadge score={pkg.score} method={pkg.score_method === "claude" ? "claude" : "rules"} />
        </h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          <span>{pkg.company_name}</span>
          <span>· version {pkg.version_number}</span>
          <PackageStatusBadge status={pkg.status} />
          <Link href={`/jobs/${pkg.job_id}`} className="text-indigo-600 hover:underline dark:text-indigo-400">
            View job
          </Link>
        </p>
      </div>

      {pkg.status === "generating" && <Alert>Generating the package… this page updates by itself.</Alert>}
      {pkg.status === "failed" && <Alert tone="error">Generation failed: {pkg.error}</Alert>}
      {pkg.status === "superseded" && <Alert tone="warning">A newer version of this package exists.</Alert>}
      {pkg.status === "rejected" && pkg.rejection_reason && (
        <Alert tone="warning">Rejected: {pkg.rejection_reason}</Alert>
      )}

      {pkg.status !== "generating" && (
        <Card>
          <PackageActions pkg={pkg} onChange={refresh} />
        </Card>
      )}

      {pkg.status !== "generating" && pkg.status !== "failed" && (
        <>
          <nav aria-label="Package sections" className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
            {TABS.map((t) => (
              <Link
                key={t.key}
                href={`/packages/${pkg.id}${t.path}`}
                aria-current={t.key === tab ? "page" : undefined}
                className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
                  t.key === tab
                    ? "border-indigo-600 text-indigo-700 dark:text-indigo-300"
                    : "border-transparent text-zinc-600 hover:text-zinc-900 dark:text-zinc-400"
                }`}
              >
                {t.label}
                {t.key === "answers" && pkg.answers_needing_review > 0 && (
                  <span className="ml-1 rounded bg-amber-100 px-1.5 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                    {pkg.answers_needing_review}
                  </span>
                )}
              </Link>
            ))}
          </nav>
          {children(pkg, refresh)}
        </>
      )}
    </div>
  );
}
