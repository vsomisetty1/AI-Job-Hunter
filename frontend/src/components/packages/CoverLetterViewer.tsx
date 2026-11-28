"use client";

// The cover letter as text, with how it was written and what to check.
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";

import { Downloads } from "./Downloads";
import { PackageShell } from "./PackageShell";

export function CoverLetterViewer({ id }: { id: string }) {
  return (
    <PackageShell id={id} tab="cover-letter">
      {(pkg) => {
        const cl = pkg.cover_letter;
        if (!cl) return <Alert>This package has no cover letter. Regenerate it to include one.</Alert>;
        return (
          <div className="grid gap-6 lg:grid-cols-3">
            <Card
              className="lg:col-span-2"
              title={`Cover letter (version ${cl.version_number})`}
              actions={<Downloads id={pkg.id} doc="cover-letter" label="Download" />}
            >
              {/* Plain text, never HTML. */}
              <div className="whitespace-pre-wrap text-sm leading-relaxed" aria-label="Cover letter text">
                {cl.content}
              </div>
            </Card>
            <Card title="About this letter">
              <p className="text-sm">
                {cl.word_count} words ·{" "}
                {cl.method === "claude" ? `written by ${cl.model ?? "Claude"}, checked against your resume` : "built from your resume"}
              </p>
              {(cl.generation.notes ?? []).length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
                  {cl.generation.notes!.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              {(cl.generation.facts ?? []).length > 0 && (
                <details className="mt-3 text-xs text-zinc-600 dark:text-zinc-400">
                  <summary className="cursor-pointer">Facts it uses</summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {cl.generation.facts!.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
                </details>
              )}
            </Card>
          </div>
        );
      }}
    </PackageShell>
  );
}
