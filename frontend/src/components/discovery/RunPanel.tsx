"use client";

// Start a discovery run and follow it until it finishes.
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useDiscoveryRun } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import { discoveryApi } from "@/lib/api/jobs";
import type { DiscoveryRun, RunStatus } from "@/types";

export const RUN_TONE: Record<RunStatus, "green" | "amber" | "red" | "indigo" | "neutral"> = {
  running: "indigo",
  succeeded: "green",
  partial: "amber",
  failed: "red",
  cancelled: "neutral",
};

export function RunCounts({ run }: { run: DiscoveryRun }) {
  const items: [string, number][] = [
    ["companies", run.companies_total],
    ["found", run.jobs_found],
    ["new", run.jobs_inserted],
    ["updated", run.jobs_updated],
    ["unchanged", run.jobs_unchanged],
    ["skipped", run.jobs_skipped],
    ["expired", run.jobs_expired],
  ];
  return (
    <dl className="grid grid-cols-4 gap-3 sm:grid-cols-7">
      {items.map(([label, n]) => (
        <div key={label}>
          <dt className="text-xs uppercase text-zinc-500">{label}</dt>
          <dd className="text-lg font-semibold tabular-nums">{n}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RunPanel({
  trackedCount,
  latestId,
  onFinished,
}: {
  trackedCount: number;
  latestId: string | null;
  onFinished: () => void;
}) {
  const [startedId, setStartedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const runId = startedId ?? latestId;
  const { data: run } = useDiscoveryRun(runId);

  // Refresh companies, jobs and history once a run we watched running ends.
  const watching = useRef<string | null>(null);
  useEffect(() => {
    if (!run) return;
    if (run.status === "running") watching.current = run.id;
    else if (watching.current === run.id) {
      watching.current = null;
      onFinished();
    }
  }, [run, onFinished]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const started = await discoveryApi.start();
      setStartedId(started.run_id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const running = run?.status === "running";
  return (
    <Card
      title="Run discovery"
      actions={
        <Button onClick={start} disabled={busy || running || trackedCount === 0}>
          {running ? "Discovering…" : "Discover jobs now"}
        </Button>
      }
    >
      <p className="mb-3 text-sm text-zinc-500">
        Crawls all {trackedCount} tracked {trackedCount === 1 ? "company" : "companies"}. Scheduled runs
        refresh only companies that are due.
      </p>
      {trackedCount === 0 && <Alert>Track at least one company below first.</Alert>}
      {error && <Alert tone="error">{error}</Alert>}
      {run && (
        <div className="space-y-3" aria-live="polite">
          <div className="flex items-center gap-2 text-sm">
            <Badge tone={RUN_TONE[run.status]}>{run.status}</Badge>
            {run.duration_ms != null && <span className="text-zinc-500">{(run.duration_ms / 1000).toFixed(1)} s</span>}
            {run.error && <span className="text-red-600 dark:text-red-400">{run.error}</span>}
          </div>
          <RunCounts run={run} />
        </div>
      )}
    </Card>
  );
}
