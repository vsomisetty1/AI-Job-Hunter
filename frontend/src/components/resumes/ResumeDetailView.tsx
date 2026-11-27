"use client";

// One resume: parsed data (view/edit), parse quality, versions.
import Link from "next/link";
import { useState } from "react";

import { Header } from "@/components/layout/Header";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useResume, useTask } from "@/hooks/useResumes";
import { errorMessage } from "@/lib/api/client";
import { resumesApi } from "@/lib/api/resumes";
import { formatBytes, formatDateTime } from "@/lib/format";

import { ParsedResumeEditor } from "./ParsedResumeEditor";
import { ParsedResumeView } from "./ParsedResumeView";
import { VersionHistory } from "./VersionHistory";

export function ResumeDetailView({ id }: { id: string }) {
  const { data: resume, error, isLoading, mutate } = useResume(id);
  const [editing, setEditing] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  useTask(taskId, (task) => {
    setTaskId(null);
    if (task.status !== "succeeded") setActionError(task.error ?? "Re-parsing failed.");
    void mutate();
  });

  if (isLoading) return <p className="text-sm text-zinc-500">Loading…</p>;
  if (error || !resume) return <Alert tone="error">{error ? errorMessage(error) : "Not found"}</Alert>;

  const meta = resume.parsed?.meta;
  const confidence = meta ? Math.round(meta.confidence * 100) : null;

  async function reparse(useLlm: boolean) {
    setActionError(null);
    try {
      setTaskId((await resumesApi.reparse(id, useLlm)).task_id);
    } catch (err) {
      setActionError(errorMessage(err));
    }
  }

  return (
    <>
      <Header
        title={resume.filename}
        description={
          <>
            {resume.file_type.toUpperCase()} · {formatBytes(resume.size_bytes)} · uploaded{" "}
            {formatDateTime(resume.created_at)} ·{" "}
            <Link href="/resumes" className="text-indigo-600 hover:underline dark:text-indigo-400">
              All resumes
            </Link>
          </>
        }
        actions={
          !editing && (
            <>
              <a
                href={resumesApi.downloadUrl(id)}
                className="inline-flex items-center rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium dark:border-zinc-700"
              >
                Download
              </a>
              <Button variant="secondary" disabled={!!taskId} onClick={() => void reparse(true)}>
                {taskId ? "Re-parsing…" : "Re-parse"}
              </Button>
              <Button disabled={!resume.parsed} onClick={() => setEditing(true)}>
                Edit parsed data
              </Button>
            </>
          )
        }
      />
      <div className="mb-4 space-y-2">
        {actionError && <Alert tone="error">{actionError}</Alert>}
        {meta && meta.warnings.length > 0 && <Alert tone="warning">{meta.warnings.join(" ")}</Alert>}
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Parsed data">
            {!resume.parsed ? (
              <p className="text-sm text-zinc-500">Not parsed yet.</p>
            ) : editing ? (
              <ParsedResumeEditor
                resumeId={id}
                initial={resume.parsed}
                onCancel={() => setEditing(false)}
                onSaved={() => {
                  setEditing(false);
                  void mutate();
                }}
              />
            ) : (
              <ParsedResumeView data={resume.parsed} />
            )}
          </Card>
        </div>
        <div className="space-y-6">
          <Card title="Parse quality">
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt>Method</dt>
                <dd>
                  <Badge tone={meta?.method === "llm_assisted" ? "indigo" : "neutral"}>
                    {meta?.method.replace("_", " ") ?? "—"}
                  </Badge>
                </dd>
              </div>
              <div className="flex justify-between">
                <dt>Confidence</dt>
                <dd>
                  {confidence !== null && (
                    <Badge tone={confidence >= 80 ? "green" : confidence >= 50 ? "amber" : "red"}>
                      {confidence}%
                    </Badge>
                  )}
                </dd>
              </div>
              {meta?.section_confidence
                .filter((s) => s.score < 1)
                .map((s) => (
                  <div key={s.section} className="flex justify-between text-zinc-500">
                    <dt className="capitalize">{s.section}</dt>
                    <dd>{Math.round(s.score * 100)}%</dd>
                  </div>
                ))}
            </dl>
            {resume.is_primary && (
              <p className="mt-3 text-xs text-zinc-500">
                Primary resume: your <Link href="/profile" className="underline">profile</Link> is built from it.
              </p>
            )}
          </Card>
          <Card title="Versions">
            <VersionHistory resumeId={id} versions={resume.versions} />
          </Card>
        </div>
      </div>
    </>
  );
}
