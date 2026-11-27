"use client";

// Automation logs: what each run did, step by step (newest first).
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { useAutomationLogs } from "@/hooks/useApplications";
import { errorMessage } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import type { LogLevel } from "@/types";

import { ApplicationsNav } from "./ApplicationsNav";

const LEVELS: { key: string; label: string; levels: LogLevel[] }[] = [
  { key: "info", label: "Steps", levels: ["info", "warning", "error"] },
  { key: "problems", label: "Warnings & errors", levels: ["warning", "error"] },
  { key: "all", label: "Everything", levels: [] },
];
const TONE = { debug: "neutral", info: "indigo", warning: "amber", error: "red" } as const;

export function AutomationLogs({ submissionId }: { submissionId?: string }) {
  const [level, setLevel] = useState(LEVELS[0]);
  const { data, error, isLoading } = useAutomationLogs(submissionId, level.levels);
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Automation logs</h1>
        <ApplicationsNav />
        {submissionId && (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            One run only.{" "}
            <Link href={`/applications/${submissionId}`} className="underline">
              Back to its review
            </Link>{" "}
            ·{" "}
            <Link href="/applications/logs" className="underline">
              all runs
            </Link>
          </p>
        )}
      </div>
      <div role="tablist" aria-label="Level" className="flex flex-wrap gap-1">
        {LEVELS.map((l) => (
          <button
            key={l.key}
            role="tab"
            aria-selected={l.key === level.key}
            onClick={() => setLevel(l)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              l.key === level.key
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            }`}
          >
            {l.label}
          </button>
        ))}
      </div>
      <Card>
        {error && <Alert tone="error">{errorMessage(error)}</Alert>}
        {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
        {data && data.items.length === 0 && <p className="py-6 text-center text-sm text-zinc-500">No log entries.</p>}
        {data && data.items.length > 0 && (
          <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
            {data.items.map((log) => (
              <li key={log.id} className="flex flex-wrap gap-x-3 gap-y-1 py-2">
                <span className="whitespace-nowrap text-xs text-zinc-500">{formatDateTime(log.created_at)}</span>
                <Badge tone={TONE[log.level]}>{log.level}</Badge>
                {log.step && <span className="text-xs text-zinc-500">{log.step}</span>}
                <span className="min-w-0 flex-1">{log.message}</span>
                {!submissionId && (
                  <Link href={`/applications/${log.submission_id}`} className="text-xs text-indigo-600 hover:underline dark:text-indigo-400">
                    {log.company_name}: {log.job_title}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
