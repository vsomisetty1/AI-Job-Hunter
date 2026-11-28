"use client";

// Resume performance: which resume versions and package styles led to replies
// and interviews.
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { useResumeAnalytics } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";

import { SegmentTable } from "./charts";
import { DataNote, InsightsNav } from "./InsightsNav";

export function ResumePerformance() {
  const { data, error, isLoading } = useResumeAnalytics();
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Resume performance</h1>
        <DataNote />
        <InsightsNav />
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && (
        <>
          <Card title="Resume versions (the version each package was tailored from)">
            <SegmentTable rows={data.resume_variant} name="Resume version" />
          </Card>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Cover letter">
              <SegmentTable rows={data.cover_letter} name="Cover letter" />
            </Card>
            <Card title="How the resume was tailored">
              <SegmentTable rows={data.tailoring} name="Tailoring" />
            </Card>
            <Card title="Package version">
              <SegmentTable rows={data.regenerated} name="Package" />
            </Card>
            <Card title="How you applied">
              <SegmentTable rows={data.applied_via} name="Applied" empty="No submitted applications yet." />
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
