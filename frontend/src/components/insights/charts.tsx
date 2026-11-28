// Small, dependency-free charts for analytics. Every chart is single-series
// (one hue, no legend needed), every mark has a hover tooltip, and every chart
// sits next to its numbers (text or a table) so nothing depends on colour.
import type { ReactNode } from "react";

import type { FunnelStep, HistoryPoint, RateStat, SegmentStat } from "@/types";

export function pct(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

/** "42% (5 of 12)" */
export function rateText(r: RateStat | null | undefined): string {
  if (!r || !r.n) return "—";
  return `${pct(r.rate)} (${r.k} of ${r.n})`;
}

export function ciText(r: RateStat | null | undefined): string {
  if (!r || r.low === null || r.high === null) return "";
  return `95% interval ${pct(r.low)}–${pct(r.high)}`;
}

/** Horizontal bar for a rate, with its 95 % interval as a whisker. */
export function RateBar({ rate, label }: { rate: RateStat; label: string }) {
  if (!rate.n || rate.rate === null) {
    return <span className="text-xs text-zinc-400">no data</span>;
  }
  const tip = `${label}: ${rateText(rate)}. ${ciText(rate)}`;
  return (
    <div className="flex items-center gap-2" title={tip}>
      <svg viewBox="0 0 100 10" className="h-3 w-28 shrink-0" role="img" aria-label={tip}>
        <rect x="0" y="3" width="100" height="4" rx="2" className="fill-zinc-100 dark:fill-zinc-800" />
        <rect
          x="0"
          y="2"
          width={Math.max(1, rate.rate * 100)}
          height="6"
          rx="2"
          className="fill-indigo-500 dark:fill-indigo-400"
        />
        {rate.low !== null && rate.high !== null && (
          <line
            x1={rate.low * 100}
            x2={rate.high * 100}
            y1="5"
            y2="5"
            strokeWidth="1"
            className="stroke-zinc-500 dark:stroke-zinc-400"
          />
        )}
      </svg>
      <span className="whitespace-nowrap text-xs tabular-nums">{rateText(rate)}</span>
    </div>
  );
}

/** Funnel: one bar per step, length = count; conversion from the previous step as text. */
export function Funnel({ steps }: { steps: FunnelStep[] }) {
  const max = Math.max(1, ...steps.map((s) => s.count));
  return (
    <ol className="space-y-2" aria-label="Funnel">
      {steps.map((s) => {
        const tip = `${s.label}: ${s.count}${s.from_previous ? `, ${pct(s.from_previous.rate)} of the step before` : ""}`;
        return (
          <li key={s.stage} className="grid grid-cols-[10rem_1fr_7rem] items-center gap-3 text-sm" title={tip}>
            <span className="text-zinc-600 dark:text-zinc-400">{s.label}</span>
            <div className="h-5 rounded bg-zinc-100 dark:bg-zinc-800">
              <div
                className="h-5 rounded bg-indigo-500 dark:bg-indigo-400"
                style={{ width: `${(100 * s.count) / max}%`, minWidth: s.count ? 4 : 0 }}
              />
            </div>
            <span className="text-right tabular-nums">
              {s.count}
              {s.from_previous && s.from_previous.n > 0 && (
                <span className="ml-1 text-xs text-zinc-500">({pct(s.from_previous.rate)})</span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** One metric over time (small multiple). Points carry a hover tooltip. */
export function Sparkline({
  points,
  pick,
  label,
}: {
  points: HistoryPoint[];
  pick: (p: HistoryPoint) => number | null;
  label: string;
}) {
  const values = points.map((p) => ({ at: p.at, v: pick(p) })).filter((p) => p.v !== null) as {
    at: string;
    v: number;
  }[];
  const last = values.at(-1)?.v ?? null;
  const w = 160;
  const h = 40;
  const x = (i: number) => (values.length <= 1 ? w / 2 : (i * (w - 8)) / (values.length - 1) + 4);
  const y = (v: number) => h - 4 - v * (h - 8);
  return (
    <figure className="space-y-1">
      <figcaption className="flex items-baseline justify-between text-xs text-zinc-500">
        <span>{label}</span>
        <span className="text-sm font-medium text-zinc-900 tabular-nums dark:text-zinc-100">{pct(last)}</span>
      </figcaption>
      {values.length === 0 ? (
        <p className="text-xs text-zinc-400">No history yet</p>
      ) : (
        <svg viewBox={`0 0 ${w} ${h}`} className="h-10 w-full" role="img" aria-label={`${label} over time`}>
          <line x1="0" x2={w} y1={h - 4} y2={h - 4} strokeWidth="1" className="stroke-zinc-200 dark:stroke-zinc-700" />
          <polyline
            fill="none"
            strokeWidth="2"
            strokeLinejoin="round"
            className="stroke-indigo-500 dark:stroke-indigo-400"
            points={values.map((p, i) => `${x(i)},${y(p.v)}`).join(" ")}
          />
          {values.map((p, i) => (
            <circle key={p.at} cx={x(i)} cy={y(p.v)} r="4" className="fill-indigo-500 dark:fill-indigo-400">
              <title>{`${new Date(p.at).toLocaleDateString()}: ${pct(p.v)}`}</title>
            </circle>
          ))}
        </svg>
      )}
    </figure>
  );
}

export function Kpi({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="text-xs uppercase tracking-wide text-zinc-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

/** Response / interview / offer rates per group, as a table with bars. */
export function SegmentTable({
  rows,
  name,
  extra,
  empty = "No data yet.",
}: {
  rows: SegmentStat[];
  name: string;
  extra?: (row: SegmentStat) => ReactNode;
  empty?: string;
}) {
  if (rows.length === 0) return <p className="text-sm text-zinc-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-zinc-500">
          <tr>
            <th className="py-2 pr-4">{name}</th>
            <th className="py-2 pr-4 text-right">Packages</th>
            <th className="py-2 pr-4 text-right">Submitted</th>
            <th className="py-2 pr-4">Response rate</th>
            <th className="py-2 pr-4">Interview rate</th>
            <th className="py-2 pr-4">Offer rate</th>
            <th className="py-2 pr-4 text-right">Median days to reply</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {rows.map((r) => (
            <tr key={r.key} className="align-middle">
              <td className="py-2 pr-4">
                <div className="font-medium">{r.label}</div>
                {extra && <div className="mt-1">{extra(r)}</div>}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.packages}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.submitted}</td>
              <td className="py-2 pr-4">
                <RateBar rate={r.response_rate} label={`${r.label} response rate`} />
              </td>
              <td className="py-2 pr-4">
                <RateBar rate={r.interview_rate} label={`${r.label} interview rate`} />
              </td>
              <td className="py-2 pr-4">
                <RateBar rate={r.offer_rate} label={`${r.label} offer rate`} />
              </td>
              <td className="py-2 pr-4 text-right tabular-nums">
                {r.median_days_to_response === null ? "—" : r.median_days_to_response.toFixed(0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const STAGE_LABEL: Record<string, string> = {
  recruiter_response: "Recruiter response",
  recruiter_screen: "Recruiter screen",
  phone_screen: "Phone screen",
  technical_interview: "Technical interview",
  hiring_manager_interview: "Hiring manager interview",
  onsite: "Onsite",
  final_round: "Final round",
  offer: "Offer",
  rejection: "Rejection",
  withdrawal: "Withdrawn",
  package_generated: "Package generated",
  package_approved: "Package approved",
  submitted: "Application submitted",
};
