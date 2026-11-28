"use client";

// Package overview: what is in it, what to check, and the approval actions.
import Link from "next/link";
import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { packagesApi } from "@/lib/api/packages";
import { formatDateTime } from "@/lib/format";
import type { PackageDetail } from "@/types";

import { Downloads } from "./Downloads";
import { PackageShell } from "./PackageShell";

function Notes({ items }: { items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-zinc-700 dark:text-zinc-300">
      {items.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}

function Overview({ pkg, refresh }: { pkg: PackageDetail; refresh: (p?: PackageDetail) => void }) {
  // Opening a freshly generated package counts as reviewing it.
  const marked = useRef(false);
  useEffect(() => {
    if (pkg.status === "generated" && !marked.current) {
      marked.current = true;
      packagesApi.review(pkg.id).then(refresh, () => undefined);
    }
  }, [pkg.id, pkg.status, refresh]);

  const tr = pkg.tailored_resume;
  const needs = pkg.answers.filter((a) => a.needs_review);
  const timeline = [
    ["Generated", pkg.generated_at],
    ["Reviewed", pkg.reviewed_at],
    ["Approved", pkg.approved_at],
    ["Submitted", pkg.submitted_at],
    ["Rejected", pkg.rejected_at],
  ].filter(([, at]) => at) as [string, string][];

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card title="Tailored resume" actions={tr && <Downloads id={pkg.id} doc="resume" label="Resume" />}>
          {tr ? (
            <div className="space-y-3 text-sm">
              <p>{tr.change_summary}</p>
              <div className="flex flex-wrap gap-1">
                {(tr.tailoring.matched_skills ?? []).map((s) => (
                  <Badge key={s} tone="green">
                    {s}
                  </Badge>
                ))}
                {(tr.tailoring.missing_skills ?? []).map((s) => (
                  <Badge key={s} tone="amber">
                    missing: {s}
                  </Badge>
                ))}
              </div>
              <Notes items={tr.tailoring.notes} />
              <p className="flex gap-4">
                <Link href={`/packages/${pkg.id}/resume`} className="text-indigo-600 hover:underline dark:text-indigo-400">
                  Read it
                </Link>
                <Link href={`/packages/${pkg.id}/diff`} className="text-indigo-600 hover:underline dark:text-indigo-400">
                  See {tr.changes.length} change{tr.changes.length === 1 ? "" : "s"}
                </Link>
              </p>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">No tailored resume (it may have been deleted).</p>
          )}
        </Card>
        <Card
          title="Cover letter"
          actions={pkg.cover_letter && <Downloads id={pkg.id} doc="cover-letter" label="Letter" />}
        >
          {pkg.cover_letter ? (
            <div className="space-y-2 text-sm">
              <p>
                {pkg.cover_letter.word_count} words ·{" "}
                {pkg.cover_letter.method === "claude" ? "written by Claude, checked against your resume" : "built from your resume"}
              </p>
              <Notes items={pkg.cover_letter.generation.notes} />
              <Link href={`/packages/${pkg.id}/cover-letter`} className="text-indigo-600 hover:underline dark:text-indigo-400">
                Read it
              </Link>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">No cover letter in this package.</p>
          )}
        </Card>
        <Card title="Application answers">
          <p className="text-sm">
            {pkg.answers.length} answers
            {needs.length > 0 ? `, ${needs.length} need your input: ${needs.map((a) => a.question).join(" · ")}` : ", all from your profile and settings."}
          </p>
          <Link href={`/packages/${pkg.id}/answers`} className="mt-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400">
            Review answers
          </Link>
        </Card>
      </div>
      <div className="space-y-6">
        <Card title="Score">
          <p className="text-sm">
            {pkg.score_snapshot.overall ?? "—"}/100 ({pkg.score_snapshot.method === "claude" ? "Claude" : "rules"}) when
            generated.
          </p>
          {pkg.score_snapshot.rationale && <p className="mt-2 text-xs text-zinc-500">{pkg.score_snapshot.rationale}</p>}
        </Card>
        <Card title="Timeline">
          <dl className="space-y-1 text-sm">
            {timeline.map(([label, at]) => (
              <div key={label} className="flex justify-between gap-3">
                <dt className="text-zinc-500">{label}</dt>
                <dd>{formatDateTime(at)}</dd>
              </div>
            ))}
          </dl>
          {pkg.review_notes && <p className="mt-2 text-sm">Notes: {pkg.review_notes}</p>}
        </Card>
        <Card title="Original resume">
          <Downloads id={pkg.id} doc="original-resume" label="Original" />
          {pkg.generation.llm_used && (
            <p className="mt-2 text-xs text-zinc-500">Claude reworded parts of this package.</p>
          )}
        </Card>
      </div>
    </div>
  );
}

export function PackageReview({ id }: { id: string }) {
  return <PackageShell id={id} tab="overview">{(pkg, refresh) => <Overview pkg={pkg} refresh={refresh} />}</PackageShell>;
}
