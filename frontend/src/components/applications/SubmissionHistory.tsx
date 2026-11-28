"use client";

// Submission history: every automation run with its outcome, timestamps and errors.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { useSubmissions } from "@/hooks/useApplications";
import { errorMessage } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import type { SubmissionStatus } from "@/types";

import { ApplicationsNav } from "./ApplicationsNav";
import { SubmissionStatusBadge } from "./SubmissionStatusBadge";

const FILTERS: { key: string; label: string; statuses: SubmissionStatus[] }[] = [
  { key: "all", label: "All", statuses: [] },
  { key: "submitted", label: "Submitted", statuses: ["submitted"] },
  { key: "failed", label: "Failed", statuses: ["failed"] },
  { key: "cancelled", label: "Cancelled", statuses: ["cancelled"] },
];

export function SubmissionHistory() {
  const [filter, setFilter] = useState(FILTERS[0]);
  const { data, error, isLoading } = useSubmissions(filter.statuses);
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Submission history</h1>
        <ApplicationsNav />
      </div>
      <div role="tablist" aria-label="Filter" className="flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            role="tab"
            aria-selected={f.key === filter.key}
            onClick={() => setFilter(f)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              f.key === filter.key
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      <Card>
        {error && <Alert tone="error">{errorMessage(error)}</Alert>}
        {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
        {data && data.items.length === 0 && <p className="py-6 text-center text-sm text-zinc-500">No runs yet.</p>}
        {data && data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-zinc-500">
                <tr>
                  <th className="py-2 pr-4">Job</th>
                  <th className="py-2 pr-4">Status</th>
                  <th className="py-2 pr-4">Started</th>
                  <th className="py-2 pr-4">Confirmed by you</th>
                  <th className="py-2 pr-4">Finished</th>
                  <th className="py-2 pr-4">Attempts</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {data.items.map((s) => (
                  <tr key={s.id} className="align-top">
                    <td className="py-2 pr-4">
                      <Link href={`/applications/${s.id}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                        {s.job_title}
                      </Link>
                      <div className="text-xs text-zinc-500">
                        {s.company_name} · {s.platform}
                      </div>
                    </td>
                    <td className="py-2 pr-4">
                      <SubmissionStatusBadge status={s.status} />
                      {s.error && <div className="mt-1 max-w-sm text-xs text-red-700 dark:text-red-400">{s.error}</div>}
                    </td>
                    <td className="whitespace-nowrap py-2 pr-4 text-xs">{formatDateTime(s.started_at ?? s.queued_at)}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-xs">{s.confirmed_at ? formatDateTime(s.confirmed_at) : "—"}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-xs">
                      {formatDateTime(s.submitted_at ?? s.failed_at ?? s.cancelled_at ?? null)}
                    </td>
                    <td className="py-2 pr-4 text-xs">{s.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
