"use client";

// One discovered job: details, requirements, and the raw board payload.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useJob, useJobRaw } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import { formatDateTime, formatSalary, safeUrl } from "@/lib/format";

import { GeneratePackage } from "@/components/packages/GeneratePackage";

import { ScoreBadge } from "./ScoreBadge";
import { FilterCard, ScoreCard } from "./ScoreDetails";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1 text-sm">
      <dt className="w-32 shrink-0 text-zinc-500">{label}</dt>
      <dd className="min-w-0 break-words">{children || "—"}</dd>
    </div>
  );
}

function RawPayload({ id }: { id: string }) {
  const { data, error } = useJobRaw(id);
  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  if (!data) return <p className="text-sm text-zinc-500">Loading…</p>;
  return (
    <pre
      aria-label="Raw job payload"
      className="max-h-[32rem] overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100"
    >
      {JSON.stringify(data.raw, null, 2)}
    </pre>
  );
}

export function JobDetailView({ id }: { id: string }) {
  const { data: job, error } = useJob(id);
  const [showRaw, setShowRaw] = useState(false);

  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  if (!job) return <p className="text-sm text-zinc-500">Loading…</p>;

  const url = safeUrl(job.url);
  const applyUrl = safeUrl(job.apply_url);
  const salary = formatSalary(job.salary_min, job.salary_max, job.salary_currency);

  return (
    <div className="space-y-6">
      <div>
        <Link href="/jobs" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
          ← All jobs
        </Link>
        <h1 className="mt-2 flex flex-wrap items-center gap-3 text-2xl font-semibold">
          {job.title} <ScoreBadge score={job.score} method={job.score_method} />
        </h1>
        <p className="text-zinc-600 dark:text-zinc-400">
          {job.company_name}
          {job.location && ` · ${job.location}`}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge tone={job.status === "expired" ? "red" : "indigo"}>{job.status}</Badge>
          <Badge>{job.remote_type}</Badge>
          {job.employment_type && <Badge>{job.employment_type.replace("_", " ")}</Badge>}
          {url && (
            <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
              View posting ↗
            </a>
          )}
          {applyUrl && applyUrl !== url && (
            <a href={applyUrl} target="_blank" rel="noopener noreferrer" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
              Apply page ↗
            </a>
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          {job.requirements.length > 0 && (
            <Card title="Requirements">
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {job.requirements.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </Card>
          )}
          <Card title="Description">
            {/* Plain text from the backend (HTML is stripped there); never rendered as HTML. */}
            <div className="whitespace-pre-wrap text-sm leading-relaxed">{job.description || "No description."}</div>
          </Card>
        </div>
        <div className="space-y-6">
          <GeneratePackage jobId={job.id} expired={job.status === "expired"} />
          <ScoreCard scores={job.scores} />
          <FilterCard result={job.filter_result} />
          <Card title="Details">
            <dl>
              <Row label="Compensation">{salary || job.compensation_text}</Row>
              {salary && job.compensation_text && <Row label="As posted">{job.compensation_text}</Row>}
              <Row label="Source">
                <span className="capitalize">{job.source}</span> #{job.external_id}
              </Row>
              <Row label="Posted">{formatDateTime(job.posted_at)}</Row>
              <Row label="First seen">{formatDateTime(job.first_seen_at)}</Row>
              <Row label="Last seen">{formatDateTime(job.last_seen_at)}</Row>
              {job.expired_at && <Row label="Expired">{formatDateTime(job.expired_at)}</Row>}
            </dl>
          </Card>
          <Card
            title="Raw data"
            actions={
              <Button variant="secondary" onClick={() => setShowRaw((v) => !v)}>
                {showRaw ? "Hide" : "Show"} raw JSON
              </Button>
            }
          >
            {showRaw ? (
              <RawPayload id={job.id} />
            ) : (
              <p className="text-sm text-zinc-500">The posting exactly as the job board returned it.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
