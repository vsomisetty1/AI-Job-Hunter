"use client";

// Every change from the original resume to the tailored one, with the reason.
import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { formatDateTime } from "@/lib/format";
import type { ResumeChange } from "@/types";

import { PackageShell } from "./PackageShell";

function asList(value: unknown): string[] | null {
  return Array.isArray(value) ? value.map(String) : null;
}

/** For reorders: before and after side by side, moved items marked. */
function ListDiff({ before, after }: { before: string[]; after: string[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {[
        ["Before", before],
        ["After", after],
      ].map(([label, items]) => (
        <div key={label as string}>
          <p className="mb-1 text-xs font-semibold uppercase text-zinc-500">{label as string}</p>
          <ol className="list-decimal space-y-0.5 pl-5">
            {(items as string[]).map((item, i) => {
              const moved = label === "After" && before.indexOf(item) !== i;
              return (
                <li key={`${item}-${i}`} className={moved ? "font-medium text-indigo-700 dark:text-indigo-300" : undefined}>
                  {item}
                </li>
              );
            })}
          </ol>
        </div>
      ))}
    </div>
  );
}

export function ChangeRow({ change }: { change: ResumeChange }) {
  const before = asList(change.before);
  const after = asList(change.after);
  return (
    <li className="space-y-2 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">
          <span className="capitalize">{change.section}</span>
          {change.item && <span className="text-zinc-500"> · {change.item}</span>}
          <span className="text-zinc-500"> · {change.field.replace("_", " ")}</span>
        </p>
        <time className="text-xs text-zinc-500" dateTime={change.at}>
          {formatDateTime(change.at)}
        </time>
      </div>
      <p className="text-sm text-zinc-700 dark:text-zinc-300">Why: {change.reason}</p>
      <div className="text-sm">
        {before && after ? (
          <ListDiff before={before} after={after} />
        ) : (
          <div className="grid gap-2 md:grid-cols-2">
            <p className="rounded bg-red-50 p-2 line-through decoration-red-400/60 dark:bg-red-950/40" aria-label="Before">
              {change.before == null ? "(empty)" : String(change.before)}
            </p>
            <p className="rounded bg-emerald-50 p-2 dark:bg-emerald-950/40" aria-label="After">
              {String(change.after)}
            </p>
          </div>
        )}
      </div>
    </li>
  );
}

export function ResumeDiffViewer({ id }: { id: string }) {
  return (
    <PackageShell id={id} tab="diff">
      {(pkg) => {
        const tr = pkg.tailored_resume;
        if (!tr) return <Alert tone="warning">This package has no tailored resume.</Alert>;
        return (
          <div className="space-y-6">
            <Card title={`${tr.changes.length} change${tr.changes.length === 1 ? "" : "s"} from your resume`}>
              <p className="mb-2 text-sm text-zinc-600 dark:text-zinc-400">
                Tailoring only reorders, respells and rewords. Employers, titles, dates and skills are never added.
              </p>
              {tr.changes.length === 0 ? (
                <p className="text-sm text-zinc-500">No changes: your resume already leads with what this job asks for.</p>
              ) : (
                <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {tr.changes.map((c, i) => (
                    <ChangeRow key={i} change={c} />
                  ))}
                </ul>
              )}
            </Card>
            {(tr.tailoring.rejected_rewrites ?? []).length > 0 && (
              <Card title="Suggestions that were dropped">
                <ul className="space-y-2 text-sm">
                  {tr.tailoring.rejected_rewrites!.map((r, i) => (
                    <li key={i}>
                      <span className="font-medium">{r.item}:</span> “{r.text}”
                      <span className="block text-xs text-red-700 dark:text-red-400">{r.problems.join("; ")}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        );
      }}
    </PackageShell>
  );
}
