"use client";

// Analytics dashboard: headline rates, funnel, score accuracy, the insights that
// hold up, skill correlations and results by job family, plus the trend.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useAnalytics, useInsightsReport, useLearningHistory } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";
import { insightsApi } from "@/lib/api/insights";
import type { Insight } from "@/types";

import { Funnel, Kpi, RateBar, SegmentTable, Sparkline, ciText, pct, rateText } from "./charts";
import { DataNote, InsightsNav } from "./InsightsNav";

const CONFIDENCE_TONE = { high: "green", medium: "indigo", low: "amber", fact: "neutral" } as const;

export function InsightCard({ insight }: { insight: Insight }) {
  return (
    <li className="space-y-1 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{insight.title}</span>
        <Badge tone={CONFIDENCE_TONE[insight.confidence]}>
          {insight.confidence === "fact" ? "fact" : `${insight.confidence} confidence`}
        </Badge>
      </div>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{insight.detail}</p>
    </li>
  );
}

export function AnalyticsDashboard() {
  const { data, error, isLoading, mutate } = useAnalytics();
  const { data: report, mutate: mutateReport } = useInsightsReport();
  const { data: history, mutate: mutateHistory } = useLearningHistory();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const refresh = async () => {
    setBusy(true);
    setNote(null);
    try {
      const r = await insightsApi.refresh();
      setNote(r.stored ? "Learning Agent ran: a new snapshot was saved." : "Nothing changed since the last snapshot.");
      await Promise.all([mutate(), mutateReport(), mutateHistory()]);
    } catch (e) {
      setNote(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h1 className="text-2xl font-semibold">Analytics</h1>
          <Button variant="secondary" disabled={busy} onClick={refresh}>
            {busy ? "Analysing…" : "Run the Learning Agent"}
          </Button>
        </div>
        <DataNote />
        <InsightsNav />
      </div>
      {note && <Alert tone="info">{note}</Alert>}
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && (
        <>
          {!data.overview.enough_data && (
            <Alert tone="info">
              {data.overview.submitted} submitted application(s) so far. Rates are shown from the start, but
              comparisons and recommendations based on outcomes need at least {data.overview.min_sample}, with
              their outcomes{" "}
              <Link href="/insights/pipeline" className="underline">
                recorded
              </Link>
              .
            </Alert>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Kpi label="Submitted" value={data.overview.submitted} hint={`${data.overview.packages} packages built`} />
            <Kpi
              label="Response rate"
              value={pct(data.overview.response_rate.rate)}
              hint={`${rateText(data.overview.response_rate)} ${ciText(data.overview.response_rate)}`}
            />
            <Kpi
              label="Interview rate"
              value={pct(data.overview.interview_rate.rate)}
              hint={`${rateText(data.overview.interview_rate)} ${ciText(data.overview.interview_rate)}`}
            />
            <Kpi
              label="Offer rate"
              value={pct(data.overview.offer_rate.rate)}
              hint={`${rateText(data.overview.offer_rate)} ${ciText(data.overview.offer_rate)}`}
            />
            <Kpi
              label="Median days to reply"
              value={data.overview.median_days_to_response === null ? "—" : data.overview.median_days_to_response.toFixed(0)}
              hint={`${data.overview.awaiting_reply} awaiting, ${data.overview.no_reply_after_14_days} silent after 14 days`}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Conversion funnel">
              <Funnel steps={data.funnel} />
              <p className="mt-3 text-xs text-zinc-500">
                In brackets: share of the step before. Interview to offer: {rateText(data.overview.interview_to_offer)}.
              </p>
            </Card>
            <Card title="Insights">
              {!report ? (
                <p className="text-sm text-zinc-500">Loading…</p>
              ) : (
                <>
                  <p className="text-xs text-zinc-500">{report.message}</p>
                  {report.insights.length === 0 ? (
                    <p className="mt-3 text-sm text-zinc-500">Nothing stands out yet.</p>
                  ) : (
                    <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                      {report.insights.slice(0, 6).map((i) => (
                        <InsightCard key={i.key} insight={i} />
                      ))}
                    </ul>
                  )}
                  <Link href="/insights/recommendations" className="mt-2 inline-block text-sm font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                    What to do about it →
                  </Link>
                </>
              )}
            </Card>
          </div>

          <Card title="Score accuracy">
            <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">
              Does the job score predict interviews? <strong>{data.score_accuracy.interviewed.verdict}</strong>
              {data.score_accuracy.interviewed.auc !== null &&
                ` (AUC ${data.score_accuracy.interviewed.auc.toFixed(2)}; 0.5 is chance, 1.0 perfect; ${data.score_accuracy.interviewed.positives} interviewed vs ${data.score_accuracy.interviewed.negatives} not)`}
              .
            </p>
            <SegmentTable rows={data.score_accuracy.bands} name="Score band" empty="No submitted applications with a score yet." />
          </Card>

          <div className="space-y-6">
            <Card title="Results by job family">
              <SegmentTable rows={data.by_family} name="Family" />
            </Card>
            <Card title="Skills the jobs asked for">
              {data.skill_correlations.length === 0 ? (
                <p className="text-sm text-zinc-500">Needs a few submitted applications that asked for the same skill.</p>
              ) : (
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase text-zinc-500">
                    <tr>
                      <th className="py-2 pr-4">Skill</th>
                      <th className="py-2 pr-4 text-right">Asked</th>
                      <th className="py-2 pr-4">Interviews when you had it</th>
                      <th className="py-2">…when you did not</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                    {data.skill_correlations.slice(0, 12).map((s) => (
                      <tr key={s.skill}>
                        <td className="py-2 pr-4 font-medium">{s.skill}</td>
                        <td className="py-2 pr-4 text-right tabular-nums">{s.asked}</td>
                        <td className="py-2 pr-4">
                          <RateBar rate={s.have} label={`${s.skill}: had it`} />
                        </td>
                        <td className="py-2">
                          <RateBar rate={s.lack} label={`${s.skill}: missing`} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <Card title="Workplace">
            <SegmentTable rows={data.by_remote} name="Workplace" />
          </Card>

          <Card title="Trend (Learning Agent snapshots)">
            <div className="grid gap-6 sm:grid-cols-3">
              <Sparkline points={history ?? []} pick={(p) => p.response_rate} label="Response rate" />
              <Sparkline points={history ?? []} pick={(p) => p.interview_rate} label="Interview rate" />
              <Sparkline points={history ?? []} pick={(p) => p.offer_rate} label="Offer rate" />
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
