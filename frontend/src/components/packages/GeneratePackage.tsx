"use client";

// On a job page: generate an application package, or open the existing one.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { usePackages } from "@/hooks/usePackages";
import { ApiError, errorMessage } from "@/lib/api/client";
import { packagesApi } from "@/lib/api/packages";

import { PackageStatusBadge } from "./PackageStatusBadge";

export function GeneratePackage({ jobId, expired }: { jobId: string; expired: boolean }) {
  const router = useRouter();
  const { data } = usePackages([], jobId);
  const [useLlm, setUseLlm] = useState(false);
  const [coverLetter, setCoverLetter] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = data?.items.find((p) => p.status !== "superseded");

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const started = await packagesApi.generate(jobId, useLlm, coverLetter);
      router.push(`/packages/${started.package_id}`);
    } catch (e) {
      const existing = e instanceof ApiError ? (e.details as { package_id?: string } | null)?.package_id : undefined;
      if (existing) router.push(`/packages/${existing}`);
      else setError(errorMessage(e));
      setBusy(false);
    }
  };

  return (
    <Card title="Application package">
      {current && current.status !== "rejected" && current.status !== "failed" ? (
        <div className="space-y-2 text-sm">
          <p className="flex items-center gap-2">
            Version {current.version_number} <PackageStatusBadge status={current.status} />
          </p>
          <Link href={`/packages/${current.id}`} className="text-indigo-600 hover:underline dark:text-indigo-400">
            Open package
          </Link>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-zinc-600 dark:text-zinc-400">
            A resume tailored to this job, a cover letter and answers to common questions, for you to review.
          </p>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={coverLetter} onChange={(e) => setCoverLetter(e.target.checked)} />
            Include a cover letter
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            Reword with Claude (uses the API; checked against your resume)
          </label>
          <Button onClick={generate} disabled={busy || expired}>
            {busy ? "Starting…" : current ? "Generate a new package" : "Generate package"}
          </Button>
          {expired && <p className="text-xs text-zinc-500">This job has expired.</p>}
          {error && (
            <p role="alert" className="text-red-700 dark:text-red-400">
              {error}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
