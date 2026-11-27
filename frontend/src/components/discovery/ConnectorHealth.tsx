"use client";

// Per-platform health: tracked boards, failures, last success, optional live probe.
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useConnectorHealth } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import { formatRelative } from "@/lib/format";

export function ConnectorHealth() {
  const [probe, setProbe] = useState(false);
  const { data, error, isValidating, mutate } = useConnectorHealth(probe);
  return (
    <Card
      title="Connector health"
      actions={
        <Button
          variant="secondary"
          disabled={isValidating}
          onClick={() => (probe ? mutate() : setProbe(true))}
        >
          {isValidating && probe ? "Checking…" : "Check live"}
        </Button>
      }
    >
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      <div className="grid gap-3 sm:grid-cols-3">
        {data?.map((h) => (
          <div key={h.source} className="rounded-md border border-zinc-200 p-3 text-sm dark:border-zinc-800">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-medium">{h.display_name}</span>
              {h.probe ? (
                <Badge tone={h.probe.ok ? "green" : "red"}>{h.probe.ok ? "reachable" : "down"}</Badge>
              ) : (
                <Badge tone={h.companies_failing ? "amber" : "neutral"}>
                  {h.companies_failing ? `${h.companies_failing} failing` : "not probed"}
                </Badge>
              )}
            </div>
            <p className="text-zinc-500">
              {h.companies_tracked} tracked · {h.jobs_active} active jobs
            </p>
            <p className="text-zinc-500">
              Last success: {h.last_success_at ? formatRelative(h.last_success_at) : "never"}
            </p>
            {h.probe && (
              <p className="text-zinc-500">
                Probe {h.probe.board}: {h.probe.latency_ms} ms
                {h.probe.jobs_visible != null && `, ${h.probe.jobs_visible} jobs`}
                {h.probe.error && <span className="block text-red-600 dark:text-red-400">{h.probe.error}</span>}
              </p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
