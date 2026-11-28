"use client";

// Answers to common application questions, with their evidence. Editable while under review.
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { errorMessage } from "@/lib/api/client";
import { packagesApi } from "@/lib/api/packages";
import type { PackageAnswer, PackageDetail } from "@/types";

import { PackageShell } from "./PackageShell";

const SOURCE: Record<PackageAnswer["source"], string> = {
  profile: "from your profile",
  settings: "from your settings",
  rules: "drafted from facts",
  llm: "reworded by Claude",
  user: "written by you",
};

function AnswerCard({
  pkg,
  answer,
  onSaved,
}: {
  pkg: PackageDetail;
  answer: PackageAnswer;
  onSaved: () => void;
}) {
  const editable = pkg.status === "generated" || pkg.status === "reviewed";
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(answer.answer);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    try {
      await packagesApi.updateAnswer(pkg.id, answer.id, text.trim());
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <li className="space-y-2 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium">{answer.question}</p>
        {answer.needs_review && <Badge tone="amber">needs your input</Badge>}
        <Badge>{SOURCE[answer.source]}</Badge>
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            aria-label={`Answer to ${answer.question}`}
            className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="flex gap-2">
            <Button onClick={save} disabled={!text.trim()}>
              Save answer
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm">{answer.answer}</p>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-500">
        {answer.evidence.length > 0 && (
          <details>
            <summary className="cursor-pointer">Based on {answer.evidence.length} fact{answer.evidence.length > 1 ? "s" : ""}</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {answer.evidence.map((e, i) => (
                <li key={i}>
                  <span className="font-medium">{e.source}:</span> {e.fact}
                </li>
              ))}
            </ul>
          </details>
        )}
        {editable && !editing && (
          <button className="text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
      </div>
    </li>
  );
}

export function AnswersViewer({ id }: { id: string }) {
  return (
    <PackageShell id={id} tab="answers">
      {(pkg, refresh) => {
        const ordered = [...pkg.answers].sort((a, b) => Number(b.needs_review) - Number(a.needs_review));
        return (
          <Card title="Application answers">
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Built only from your profile, settings and the posting. Answers marked “needs your input” could not
              be answered from those facts or are personal; check them before approving.
            </p>
            <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {ordered.map((a) => (
                <AnswerCard key={a.id} pkg={pkg} answer={a} onSaved={() => refresh()} />
              ))}
            </ul>
          </Card>
        );
      }}
    </PackageShell>
  );
}
