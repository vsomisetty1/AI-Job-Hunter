"use client";

// Recommendations: what to change, why (with your numbers), and where to act.
// Nothing is changed for you; dismiss or mark done to keep the list current.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useInsightsReport, useRecommendations } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";
import { insightsApi } from "@/lib/api/insights";

import { InsightCard } from "./AnalyticsDashboard";
import { InsightsNav } from "./InsightsNav";

const PRIORITY_TONE = { high: "red", medium: "amber", low: "neutral" } as const;
const CATEGORY = { targeting: "Targeting", profile: "Profile", process: "Process", data: "Your data" } as const;

export function RecommendationsPage() {
  const [showAll, setShowAll] = useState(false);
  const { data, error, isLoading, mutate } = useRecommendations(showAll);
  const { data: report } = useInsightsReport();
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const setState = async (key: string, state: "dismissed" | "done" | null) => {
    setBusy(key);
    setActionError(null);
    try {
      await insightsApi.setState(key, state);
      await mutate();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Recommendations</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Each one comes from your own history, with the numbers behind it. The app never changes your settings or
          profile for you.
        </p>
        <InsightsNav />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
        Show dismissed and done
      </label>
      {(error || actionError) && <Alert tone="error">{actionError ?? errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && data.length === 0 && (
        <Card>
          <p className="text-sm text-zinc-500">No recommendations right now.</p>
        </Card>
      )}
      <ul className="space-y-3">
        {data?.map((r) => (
          <li key={r.key}>
            <Card>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={PRIORITY_TONE[r.priority]}>{r.priority}</Badge>
                <Badge>{CATEGORY[r.category]}</Badge>
                {r.state && <Badge tone="green">{r.state}</Badge>}
                <h2 className="text-base font-semibold">{r.title}</h2>
              </div>
              <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">{r.rationale}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Link
                  href={r.action_href}
                  className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-500"
                >
                  {r.action_label}
                </Link>
                {r.state ? (
                  <Button variant="secondary" disabled={busy === r.key} onClick={() => setState(r.key, null)}>
                    Restore
                  </Button>
                ) : (
                  <>
                    <Button variant="secondary" disabled={busy === r.key} onClick={() => setState(r.key, "done")}>
                      Done
                    </Button>
                    <Button variant="ghost" disabled={busy === r.key} onClick={() => setState(r.key, "dismissed")}>
                      Dismiss
                    </Button>
                  </>
                )}
              </div>
            </Card>
          </li>
        ))}
      </ul>
      {report && report.insights.length > 0 && (
        <Card title="All insights">
          <p className="text-xs text-zinc-500">{report.message}</p>
          <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {report.insights.map((i) => (
              <InsightCard key={i.key} insight={i} />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
