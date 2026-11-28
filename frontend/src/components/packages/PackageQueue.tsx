"use client";

// Package approval queue: packages waiting for review first, then the rest by status.
import Link from "next/link";
import { useState } from "react";

import { ScoreBadge } from "@/components/jobs/ScoreBadge";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { usePackages } from "@/hooks/usePackages";
import { errorMessage } from "@/lib/api/client";
import { formatRelative } from "@/lib/format";
import type { PackageStatus } from "@/types";

import { PackageStatusBadge } from "./PackageStatusBadge";

export const QUEUES: { key: string; label: string; statuses: PackageStatus[] }[] = [
  { key: "review", label: "Needs review", statuses: ["generating", "generated", "reviewed"] },
  { key: "approved", label: "Approved", statuses: ["approved"] },
  { key: "submitted", label: "Submitted", statuses: ["submitted"] },
  { key: "closed", label: "Rejected & failed", statuses: ["rejected", "failed"] },
  { key: "all", label: "All", statuses: [] },
];

export function PackageQueue() {
  const [queue, setQueue] = useState(QUEUES[0]);
  const { data, error, isLoading } = usePackages(queue.statuses);
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Application packages</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Review each tailored resume, cover letter and set of answers, then approve or reject it. Nothing is
          sent to an employer from here.
        </p>
      </div>
      <div role="tablist" aria-label="Package queues" className="flex flex-wrap gap-1">
        {QUEUES.map((q) => (
          <button
            key={q.key}
            role="tab"
            aria-selected={q.key === queue.key}
            onClick={() => setQueue(q)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              q.key === queue.key
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            }`}
          >
            {q.label}
          </button>
        ))}
      </div>
      <Card>
        {error && <Alert tone="error">{errorMessage(error)}</Alert>}
        {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
        {data && data.items.length === 0 && (
          <p className="py-6 text-center text-sm text-zinc-500">
            {queue.key === "review" ? (
              <>
                Nothing to review. Open a job on the{" "}
                <Link href="/jobs" className="font-medium underline">
                  Jobs
                </Link>{" "}
                page and generate a package.
              </>
            ) : (
              "No packages here."
            )}
          </p>
        )}
        {data && data.items.length > 0 && (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-zinc-500">
              <tr>
                <th className="py-2 pr-4">Score</th>
                <th className="py-2 pr-4">Job</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">To check</th>
                <th className="py-2 pr-4">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {data.items.map((p) => (
                <tr key={p.id}>
                  <td className="py-2 pr-4">
                    <ScoreBadge score={p.score} method={p.score_method === "claude" ? "claude" : "rules"} />
                  </td>
                  <td className="py-2 pr-4">
                    <Link href={`/packages/${p.id}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                      {p.job_title}
                    </Link>
                    <div className="text-xs text-zinc-500">
                      {p.company_name} · version {p.version_number}
                    </div>
                  </td>
                  <td className="py-2 pr-4">
                    <PackageStatusBadge status={p.status} />
                    {p.error && <div className="mt-1 text-xs text-red-700 dark:text-red-400">{p.error}</div>}
                  </td>
                  <td className="py-2 pr-4 text-xs">
                    {p.answers_needing_review > 0
                      ? `${p.answers_needing_review} answer${p.answers_needing_review > 1 ? "s" : ""}`
                      : "—"}
                  </td>
                  <td className="whitespace-nowrap py-2 pr-4 text-zinc-500">{formatRelative(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
