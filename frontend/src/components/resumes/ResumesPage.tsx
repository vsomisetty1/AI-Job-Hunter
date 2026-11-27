"use client";

// Resume management: upload + list.
import Link from "next/link";
import { useState } from "react";

import { Header } from "@/components/layout/Header";
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { useResumes, useTask } from "@/hooks/useResumes";
import { errorMessage } from "@/lib/api/client";
import type { UploadResponse } from "@/types";

import { ResumeList } from "./ResumeList";
import { ResumeUpload } from "./ResumeUpload";

export function ResumesPage() {
  const { data, error, mutate } = useResumes();
  const [last, setLast] = useState<UploadResponse | null>(null);
  const { data: task } = useTask(last?.task_id ?? null);

  return (
    <>
      <Header title="Resumes" description="Upload a PDF or Word resume. It is parsed and versioned." />
      <div className="space-y-6">
        <Card title="Upload">
          <ResumeUpload
            onUploaded={(r) => {
              setLast(r);
              void mutate();
            }}
          />
          {last && (
            <div className="mt-3">
              <Alert tone={task?.status === "failed" ? "error" : "info"}>
                Uploaded <strong>{last.resume.filename}</strong>.{" "}
                {task?.status === "succeeded" ? (
                  <>
                    Processing finished. <Link href={`/resumes/${last.resume.id}`} className="underline">Review the parsed data</Link>
                    {last.resume.is_primary && (
                      <> or see your <Link href="/profile" className="underline">profile</Link></>
                    )}
                    .
                  </>
                ) : task?.status === "failed" ? (
                  <>Processing failed: {task.error}</>
                ) : (
                  <>Improving the parse and building your profile…</>
                )}
              </Alert>
            </div>
          )}
        </Card>
        <Card title="Your resumes">
          {error ? (
            <Alert tone="error">{errorMessage(error)}</Alert>
          ) : data ? (
            <ResumeList resumes={data} onChanged={() => void mutate()} />
          ) : (
            <p className="text-sm text-zinc-500">Loading…</p>
          )}
        </Card>
      </div>
    </>
  );
}
