"use client";

// Filtering & scoring status for the Jobs page, with a "Re-score" button.
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useScoringSummary } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import { scoringApi } from "@/lib/api/jobs";
import { formatRelative } from "@/lib/format";

export function ScoringBar({ onDone }: { onDone?: () => void }) {
  const { data, mutate } = useScoringSummary();
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const start = async () => {
    setError(null);
    setStarting(true);
    try {
      await scoringApi.run();
      await mutate();
      onDone?.();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  if (!data) return null;
  const running = data.task_running || starting;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <p className="text-zinc-600 dark:text-zinc-400" aria-label="Scoring status">
        {data.profile_id ? (
          <>
            <strong className="text-zinc-900 dark:text-zinc-100">{data.jobs_passed}</strong> match your
            filters, {data.jobs_rejected} filtered out
            {data.jobs_duplicate > 0 && ` (${data.jobs_duplicate} duplicates)`}
            {data.jobs_unfiltered > 0 && `, ${data.jobs_unfiltered} waiting`} · {data.jobs_scored} scored
            {data.claude_enabled && data.claude_available &&
              ` · ${data.jobs_claude_scored} by Claude (${data.claude_calls_today}/${data.claude_daily_limit} today)`}
            {data.last_run_at && ` · last run ${formatRelative(data.last_run_at)}`}
          </>
        ) : (
          <>
            Upload a resume on the{" "}
            <Link href="/resumes" className="font-medium underline">
              Resumes
            </Link>{" "}
            page to get scores.
          </>
        )}
      </p>
      <div className="flex items-center gap-3">
        {error && (
          <span role="alert" className="text-red-700 dark:text-red-400">
            {error}
          </span>
        )}
        <Link href="/settings" className="text-indigo-600 hover:underline dark:text-indigo-400">
          Preferences
        </Link>
        <Button variant="secondary" onClick={start} disabled={running}>
          {running ? "Scoring…" : "Re-score"}
        </Button>
      </div>
    </div>
  );
}
