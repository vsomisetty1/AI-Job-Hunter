// Table of discovered jobs.
import Link from "next/link";

import { Badge } from "@/components/ui/Badge";
import { formatRelative, formatSalary } from "@/lib/format";
import type { JobSummary, RemoteType } from "@/types";

import { ScoreBadge } from "./ScoreBadge";

const REMOTE_TONE: Record<RemoteType, "green" | "indigo" | "neutral" | "amber"> = {
  remote: "green",
  hybrid: "indigo",
  onsite: "neutral",
  unknown: "amber",
};

export function JobsTable({ jobs }: { jobs: JobSummary[] }) {
  if (jobs.length === 0) {
    return <p className="py-6 text-center text-sm text-zinc-500">No jobs match these filters.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-zinc-500">
          <tr>
            <th className="py-2 pr-4">Score</th>
            <th className="py-2 pr-4">Role</th>
            <th className="py-2 pr-4">Location</th>
            <th className="py-2 pr-4">Salary</th>
            <th className="py-2 pr-4">Source</th>
            <th className="py-2 pr-4">Found</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {jobs.map((job) => (
            <tr
              key={job.id}
              className={job.status === "expired" || job.status === "filtered" ? "opacity-60" : undefined}
            >
              <td className="py-2 pr-4">
                <ScoreBadge score={job.score} method={job.score_method} />
              </td>
              <td className="py-2 pr-4">
                <Link
                  href={`/jobs/${job.id}`}
                  className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                >
                  {job.title}
                </Link>
                <div className="text-xs text-zinc-500">
                  {job.company_name}
                  {job.employment_type && ` · ${job.employment_type.replace("_", " ")}`}
                  {job.status === "expired" && (
                    <span className="ml-1">
                      <Badge tone="red">expired</Badge>
                    </span>
                  )}
                </div>
                {job.filter_reason && (
                  <div className="mt-0.5 text-xs text-amber-700 dark:text-amber-400">
                    Filtered: {job.filter_reason}
                  </div>
                )}
              </td>
              <td className="py-2 pr-4">
                <div className="max-w-56 truncate" title={job.location ?? ""}>
                  {job.location || "—"}
                </div>
                <Badge tone={REMOTE_TONE[job.remote_type]}>{job.remote_type}</Badge>
              </td>
              <td className="whitespace-nowrap py-2 pr-4">
                {formatSalary(job.salary_min, job.salary_max, job.salary_currency) || "—"}
              </td>
              <td className="py-2 pr-4 capitalize">{job.source}</td>
              <td className="whitespace-nowrap py-2 pr-4 text-zinc-500" title={job.first_seen_at}>
                {formatRelative(job.posted_at ?? job.first_seen_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
