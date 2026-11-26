"use client";

// Table of uploaded resumes with actions.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { resumesApi } from "@/lib/api/resumes";
import { formatBytes, formatDateTime } from "@/lib/format";
import type { Resume } from "@/types";

export function ResumeList({
  resumes,
  onChanged,
}: {
  resumes: Resume[];
  onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function act(id: string, fn: () => Promise<unknown>) {
    setBusyId(id);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  if (resumes.length === 0) {
    return <p className="text-sm text-zinc-500">No resumes yet. Upload one to get started.</p>;
  }

  return (
    <div className="space-y-3">
      {error && <Alert tone="error">{error}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-zinc-500">
            <tr>
              <th className="py-2 pr-4">File</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Uploaded</th>
              <th className="py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {resumes.map((r) => (
              <tr key={r.id}>
                <td className="py-2 pr-4">
                  <Link href={`/resumes/${r.id}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
                    {r.filename}
                  </Link>
                  <span className="ml-2 text-xs text-zinc-500">
                    {r.file_type.toUpperCase()} · {formatBytes(r.size_bytes)}
                  </span>
                  {r.is_primary && (
                    <span className="ml-2">
                      <Badge tone="indigo">Primary</Badge>
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4">
                  <Badge tone={r.parse_status === "parsed" ? "green" : r.parse_status === "failed" ? "red" : "amber"}>
                    {r.parse_status}
                  </Badge>
                  {r.parse_method === "llm_assisted" && (
                    <span className="ml-1">
                      <Badge>AI-assisted</Badge>
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4 text-zinc-500">{formatDateTime(r.created_at)}</td>
                <td className="py-2">
                  <div className="flex justify-end gap-1">
                    {!r.is_primary && (
                      <Button
                        variant="ghost"
                        disabled={busyId === r.id}
                        onClick={() => act(r.id, () => resumesApi.makePrimary(r.id))}
                      >
                        Make primary
                      </Button>
                    )}
                    <a
                      href={resumesApi.downloadUrl(r.id)}
                      className="rounded-md px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
                    >
                      Download
                    </a>
                    <Button
                      variant="ghost"
                      className="text-red-600 dark:text-red-400"
                      disabled={busyId === r.id}
                      onClick={() => {
                        if (window.confirm(`Delete ${r.filename}? This removes all its versions.`)) {
                          void act(r.id, () => resumesApi.remove(r.id));
                        }
                      }}
                    >
                      Delete
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
