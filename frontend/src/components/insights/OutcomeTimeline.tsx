"use client";

// Outcome timeline: packages generated and approved, applications submitted and
// everything recorded after, newest first, grouped by day.
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { useTimeline } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";
import type { TimelineEntry } from "@/types";

import { STAGE_LABEL } from "./charts";
import { InsightsNav } from "./InsightsNav";

const TONE: Record<string, "neutral" | "green" | "amber" | "red" | "indigo"> = {
  package_generated: "neutral",
  package_approved: "neutral",
  submitted: "indigo",
  offer: "green",
  rejection: "red",
  withdrawal: "neutral",
};

function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", year: "numeric", month: "short", day: "numeric" });
}

export function OutcomeTimeline() {
  const { data, error, isLoading } = useTimeline();
  const groups = new Map<string, TimelineEntry[]>();
  for (const e of data ?? []) {
    const d = day(e.at);
    groups.set(d, [...(groups.get(d) ?? []), e]);
  }
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Outcome timeline</h1>
        <InsightsNav />
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && data.length === 0 && (
        <Card>
          <p className="text-sm text-zinc-500">Nothing yet: generate a package to start the timeline.</p>
        </Card>
      )}
      {[...groups.entries()].map(([d, entries]) => (
        <Card key={d} title={d}>
          <ol className="space-y-2">
            {entries.map((e, i) => (
              <li key={`${e.kind}-${e.at}-${i}`} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="w-14 text-xs tabular-nums text-zinc-500">
                  {new Date(e.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                </span>
                <Badge tone={TONE[e.kind] ?? "amber"}>{STAGE_LABEL[e.kind] ?? e.label}</Badge>
                {e.status && e.status !== "completed" && <Badge>{e.status.replace("_", "-")}</Badge>}
                <span>
                  <span className="font-medium">{e.job_title}</span>{" "}
                  <span className="text-zinc-500">at {e.company_name}</span>
                </span>
                {typeof e.detail.notes === "string" && (
                  <span className="w-full pl-16 text-xs text-zinc-500">{e.detail.notes}</span>
                )}
              </li>
            ))}
          </ol>
        </Card>
      ))}
    </div>
  );
}
