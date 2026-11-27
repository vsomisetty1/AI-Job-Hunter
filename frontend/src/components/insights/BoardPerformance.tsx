"use client";

// Job board performance: Greenhouse, Lever and Ashby side by side.
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { useBoardAnalytics } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";

import { Funnel, SegmentTable } from "./charts";
import { DataNote, InsightsNav } from "./InsightsNav";

export function BoardPerformance() {
  const { data, error, isLoading } = useBoardAnalytics();
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Job board performance</h1>
        <DataNote />
        <InsightsNav />
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && (
        <>
          <Card title="Response, interview and offer rates">
            <SegmentTable rows={data} name="Board" empty="No packages yet." />
          </Card>
          <div className="grid gap-6 lg:grid-cols-3">
            {data.map((b) => (
              <Card key={b.key} title={`${b.label} funnel`}>
                <Funnel steps={b.funnel} />
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
