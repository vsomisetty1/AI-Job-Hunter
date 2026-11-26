"use client";

// Version history; click a version to inspect its content.
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { resumesApi } from "@/lib/api/resumes";
import { formatDateTime } from "@/lib/format";
import type { ParsedResume, ResumeVersion, ResumeVersionSummary } from "@/types";

import { ParsedResumeView } from "./ParsedResumeView";

const SOURCE_LABEL = {
  upload: "Uploaded file",
  parser: "Parser",
  user_edit: "Your edit",
  tailoring: "Tailored",
} as const;

export function VersionHistory({
  resumeId,
  versions,
}: {
  resumeId: string;
  versions: ResumeVersionSummary[];
}) {
  const [open, setOpen] = useState<ResumeVersion | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function show(id: string) {
    setError(null);
    try {
      setOpen(await resumesApi.version(resumeId, id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
        {versions.map((v) => (
          <li key={v.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              <span className="font-medium">v{v.version_number}</span>{" "}
              <Badge tone={v.kind === "tailored" ? "indigo" : v.kind === "parsed" ? "green" : "neutral"}>
                {v.kind}
              </Badge>{" "}
              <span className="text-zinc-500">
                {SOURCE_LABEL[v.source]}
                {v.target_role && ` · ${v.target_role}`}
                {v.target_company && ` @ ${v.target_company}`}
                {v.change_summary && ` · ${v.change_summary}`}
              </span>
            </span>
            <span className="flex items-center gap-2 text-zinc-500">
              {formatDateTime(v.created_at)}
              {v.kind !== "original" && (
                <Button variant="ghost" onClick={() => void show(v.id)}>
                  View
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      {error && <Alert tone="error">{error}</Alert>}
      {open && (
        <div className="rounded-md border border-zinc-200 p-4 dark:border-zinc-800">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold">Version {open.version_number}</p>
            <Button variant="ghost" onClick={() => setOpen(null)}>
              Close
            </Button>
          </div>
          <ParsedResumeView data={open.content as unknown as ParsedResume} />
        </div>
      )}
    </div>
  );
}
