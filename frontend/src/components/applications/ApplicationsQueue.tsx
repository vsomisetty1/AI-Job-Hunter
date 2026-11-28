"use client";

// Applications queue: approved packages ready to fill, runs in progress or waiting
// for review, and failed runs (failure recovery).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useAutomationQueue } from "@/hooks/useApplications";
import { automationApi } from "@/lib/api/applications";
import { errorMessage } from "@/lib/api/client";
import { formatRelative } from "@/lib/format";
import type { SubmissionSummary } from "@/types";

import { ApplicationsNav, ApprovalModeNote } from "./ApplicationsNav";
import { FailureRecovery } from "./FailureRecovery";
import { SubmissionStatusBadge } from "./SubmissionStatusBadge";

const PLATFORM: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" };

function JobCell({ title, company, platform, href }: { title: string; company: string; platform: string; href?: string }) {
  return (
    <div>
      {href ? (
        <Link href={href} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
          {title}
        </Link>
      ) : (
        <span className="font-medium">{title}</span>
      )}
      <div className="text-xs text-zinc-500">
        {company} · {PLATFORM[platform] ?? platform}
      </div>
    </div>
  );
}

function ActiveRow({ s }: { s: SubmissionSummary }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <JobCell title={s.job_title} company={s.company_name} platform={s.platform} href={`/applications/${s.id}`} />
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <SubmissionStatusBadge status={s.status} />
        {s.status === "waiting_for_review" && (
          <>
            {s.missing_count > 0 && <Badge tone="amber">{s.missing_count} to fill in</Badge>}
            {s.problem_count > 0 && <Badge tone="red">{s.problem_count} problems</Badge>}
            {s.ready && <Badge tone="green">ready to submit</Badge>}
            {!s.live && <Badge>browser closed</Badge>}
          </>
        )}
        <span className="text-zinc-500">{formatRelative(s.updated_at)}</span>
        <Link
          href={`/applications/${s.id}`}
          className="rounded-md border border-zinc-300 px-2 py-1 font-medium hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          {s.status === "waiting_for_review" ? "Review" : "Open"}
        </Link>
      </div>
    </li>
  );
}

export function ApplicationsQueue() {
  const router = useRouter();
  const { data, error, isLoading, mutate } = useAutomationQueue();
  const [starting, setStarting] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const start = async (packageId: string) => {
    setStarting(packageId);
    setStartError(null);
    try {
      const started = await automationApi.start(packageId);
      router.push(`/applications/${started.submission_id}`);
    } catch (e) {
      setStartError(errorMessage(e));
      setStarting(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Applications</h1>
        <ApprovalModeNote />
        <ApplicationsNav />
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {startError && <Alert tone="error">{startError}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}

      {data && (
        <>
          <Card title="In progress and waiting for you">
            {data.active.length === 0 ? (
              <p className="text-sm text-zinc-500">No application forms are open.</p>
            ) : (
              <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {data.active.map((s) => (
                  <ActiveRow key={s.id} s={s} />
                ))}
              </ul>
            )}
          </Card>

          {data.needs_attention.length > 0 && (
            <Card title="Needs attention">
              <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {data.needs_attention.map((s) => (
                  <li key={s.id} className="space-y-2 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <JobCell
                        title={s.job_title}
                        company={s.company_name}
                        platform={s.platform}
                        href={`/applications/${s.id}`}
                      />
                      <span className="text-xs text-zinc-500">
                        attempt {s.attempts} · {formatRelative(s.failed_at ?? s.updated_at)}
                      </span>
                    </div>
                    <FailureRecovery submission={s} onChange={() => void mutate()} compact />
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Ready to fill">
            {data.ready.length === 0 ? (
              <p className="text-sm text-zinc-500">
                No approved packages waiting. Approve a package on the{" "}
                <Link href="/packages" className="font-medium underline">
                  Packages
                </Link>{" "}
                page first.
              </p>
            ) : (
              <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {data.ready.map((r) => (
                  <li key={r.package_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <JobCell
                      title={r.job_title}
                      company={r.company_name}
                      platform={r.platform}
                      href={`/packages/${r.package_id}`}
                    />
                    <div className="flex items-center gap-2">
                      {r.approved_at && (
                        <span className="text-xs text-zinc-500">approved {formatRelative(r.approved_at)}</span>
                      )}
                      {r.supported ? (
                        <Button disabled={starting !== null} onClick={() => start(r.package_id)}>
                          {starting === r.package_id ? "Opening…" : "Fill application form"}
                        </Button>
                      ) : (
                        <Badge>{r.platform} not supported</Badge>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
