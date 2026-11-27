"use client";

// Recent discovery runs with per-company results.
import { Fragment, useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { useDiscoveryRun } from "@/hooks/useJobs";
import { formatDateTime } from "@/lib/format";
import type { DiscoveryRun } from "@/types";

import { RUN_TONE } from "./RunPanel";

function RunDetails({ id }: { id: string }) {
  const { data } = useDiscoveryRun(id);
  if (!data) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (data.details.length === 0) return <p className="text-sm text-zinc-500">No companies were due.</p>;
  return (
    <table className="w-full text-left text-xs">
      <thead className="text-zinc-500">
        <tr>
          <th className="py-1 pr-3">Company</th>
          <th className="py-1 pr-3">Result</th>
          <th className="py-1 pr-3">Found</th>
          <th className="py-1 pr-3">New</th>
          <th className="py-1 pr-3">Updated</th>
          <th className="py-1 pr-3">Skipped</th>
          <th className="py-1 pr-3">Expired</th>
          <th className="py-1">Notes</th>
        </tr>
      </thead>
      <tbody>
        {data.details.map((d) => (
          <tr key={d.company_id} className="align-top">
            <td className="py-1 pr-3">
              {d.name} <span className="text-zinc-500">({d.source})</span>
            </td>
            <td className="py-1 pr-3">
              <Badge tone={d.status === "ok" ? "green" : "red"}>{d.status}</Badge>
            </td>
            <td className="py-1 pr-3 tabular-nums">{d.found}</td>
            <td className="py-1 pr-3 tabular-nums">{d.inserted}</td>
            <td className="py-1 pr-3 tabular-nums">{d.updated}</td>
            <td className="py-1 pr-3 tabular-nums">{d.skipped + d.invalid}</td>
            <td className="py-1 pr-3 tabular-nums">{d.expired}</td>
            <td className="py-1 text-zinc-500">
              {[
                d.error,
                d.invalid ? `${d.invalid} failed validation` : null,
                ...Object.entries(d.skip_reasons).map(([r, n]) => `${n} ${r}`),
                ...d.notes,
              ]
                .filter(Boolean)
                .join("; ")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function RunHistory({ runs }: { runs: DiscoveryRun[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <Card title="Run history">
      {runs.length === 0 ? (
        <p className="text-sm text-zinc-500">No runs yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-zinc-500">
              <tr>
                <th className="py-2 pr-4">Started</th>
                <th className="py-2 pr-4">Trigger</th>
                <th className="py-2 pr-4">Status</th>
                <th className="py-2 pr-4">Companies</th>
                <th className="py-2 pr-4">Found / new / updated / skipped</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {runs.map((r) => (
                <Fragment key={r.id}>
                  <tr>
                    <td className="py-2 pr-4 whitespace-nowrap">{formatDateTime(r.started_at)}</td>
                    <td className="py-2 pr-4">{r.trigger}</td>
                    <td className="py-2 pr-4">
                      <Badge tone={RUN_TONE[r.status]}>{r.status}</Badge>
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {r.companies_succeeded}/{r.companies_total}
                      {r.companies_failed > 0 && <span className="ml-1 text-red-600">({r.companies_failed} failed)</span>}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">
                      {r.jobs_found} / {r.jobs_inserted} / {r.jobs_updated} / {r.jobs_skipped}
                    </td>
                    <td className="py-2 text-right">
                      <button
                        type="button"
                        className="text-indigo-600 hover:underline dark:text-indigo-400"
                        aria-expanded={open === r.id}
                        onClick={() => setOpen(open === r.id ? null : r.id)}
                      >
                        {open === r.id ? "Hide" : "Details"}
                      </button>
                    </td>
                  </tr>
                  {open === r.id && (
                    <tr>
                      <td colSpan={6} className="bg-zinc-50 p-3 dark:bg-zinc-950">
                        <RunDetails id={r.id} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
