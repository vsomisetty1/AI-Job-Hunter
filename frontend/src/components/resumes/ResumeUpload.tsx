"use client";

// Drag-and-drop / file-picker upload with client-side checks.
import { useRef, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { checkResumeFile, resumesApi } from "@/lib/api/resumes";
import type { UploadResponse } from "@/types";

export function ResumeUpload({ onUploaded }: { onUploaded?: (r: UploadResponse) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [makePrimary, setMakePrimary] = useState(false);

  async function upload(file: File | undefined) {
    if (!file) return;
    const problem = checkResumeFile(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const result = await resumesApi.upload(file, makePrimary);
      onUploaded?.(result);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void upload(e.dataTransfer.files[0]);
        }}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center ${
          dragging
            ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
            : "border-zinc-300 dark:border-zinc-700"
        }`}
      >
        <p className="text-sm font-medium">
          {busy ? "Uploading and reading your resume…" : "Drop your resume here"}
        </p>
        <p className="text-xs text-zinc-500">PDF or DOCX, up to 10 MB</p>
        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="sr-only"
          aria-label="Resume file"
          onChange={(e) => void upload(e.target.files?.[0])}
        />
        <Button variant="secondary" disabled={busy} onClick={() => input.current?.click()}>
          Choose file
        </Button>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={makePrimary}
          onChange={(e) => setMakePrimary(e.target.checked)}
        />
        Use as my primary resume (rebuilds the profile)
      </label>
      {error && <Alert tone="error">{error}</Alert>}
    </div>
  );
}
