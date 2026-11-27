"use client";

// Application review: what was filled into the real form, what is missing, the
// form's own validation messages and screenshots. You can edit fields, retry,
// cancel, or submit; submitting needs an explicit confirmation.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useSubmission } from "@/hooks/useApplications";
import { automationApi } from "@/lib/api/applications";
import { errorMessage } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import type { EditableField, ReviewDoc, SubmissionDetail } from "@/types";

import { ApplicationsNav } from "./ApplicationsNav";
import { FailureRecovery } from "./FailureRecovery";
import { SubmissionStatusBadge } from "./SubmissionStatusBadge";

const STEPS = [
  { key: "opening", label: "Open the form" },
  { key: "uploading", label: "Upload documents" },
  { key: "filling", label: "Fill in answers" },
  { key: "validating", label: "Check the form" },
  { key: "review", label: "Wait for your review" },
];
const SOURCE: Record<string, string> = {
  resume: "your resume",
  profile: "your profile",
  settings: "your settings",
  package_answer: "package answer",
  package: "package",
  user: "entered by you",
  rule: "rule",
};

function docLine(label: string, doc: ReviewDoc | undefined) {
  const status = doc?.status ?? "not_asked";
  const tone = status === "uploaded" || status === "pasted" ? "green" : status === "not_asked" ? "neutral" : "red";
  const text =
    status === "uploaded"
      ? `uploaded${doc?.file ? `: ${doc.file}` : ""}`
      : status === "pasted"
        ? `pasted into “${doc?.field}”`
        : status === "not_asked"
          ? "not asked for by this form"
          : `not uploaded${doc?.reason ? `: ${doc.reason}` : ""}`;
  return (
    <li className="flex flex-wrap items-center gap-2">
      <Badge tone={tone}>{label}</Badge>
      <span>{text}</span>
    </li>
  );
}

function FieldEditor({
  field,
  initial,
  onSave,
  busy,
}: {
  field: Pick<EditableField, "key" | "label" | "kind" | "options">;
  initial: string;
  onSave: (value: string) => void;
  busy: boolean;
}) {
  const [value, setValue] = useState(initial);
  const id = `edit-${field.key}`;
  const control =
    field.options.length > 0 ? (
      <select id={id} value={value} onChange={(e) => setValue(e.target.value)} className="input">
        <option value="">Choose…</option>
        {field.options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    ) : field.kind === "textarea" ? (
      <textarea id={id} value={value} rows={3} onChange={(e) => setValue(e.target.value)} className="input" />
    ) : (
      <input id={id} value={value} onChange={(e) => setValue(e.target.value)} className="input" />
    );
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label htmlFor={id} className="sr-only">
        {field.label}
      </label>
      <div className="min-w-64 flex-1 [&_.input]:w-full [&_.input]:rounded-md [&_.input]:border [&_.input]:border-zinc-300 [&_.input]:px-2 [&_.input]:py-1 [&_.input]:text-sm dark:[&_.input]:border-zinc-700 dark:[&_.input]:bg-zinc-900">
        {control}
      </div>
      <Button variant="secondary" disabled={busy || !value.trim()} onClick={() => onSave(value)}>
        Save to form
      </Button>
    </div>
  );
}

function Progress({ step }: { step: string }) {
  const current = STEPS.findIndex((s) => s.key === step);
  return (
    <ol className="space-y-1 text-sm" aria-label="Progress">
      {STEPS.map((s, i) => (
        <li key={s.key} className={i < current ? "text-zinc-500 line-through" : i === current ? "font-medium" : "text-zinc-400"}>
          {i === current ? "→ " : ""}
          {s.label}
        </li>
      ))}
    </ol>
  );
}

function SubmitPanel({ sub, onDone }: { sub: SubmissionDetail; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = !sub.live
    ? "The browser window for this form is closed. Retry to reopen and refill it."
    : !sub.review.ready
      ? "Fill in the missing fields and fix the problems before submitting."
      : null;
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await automationApi.submit(sub.id);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2">
      {!open ? (
        <Button disabled={blocked !== null} onClick={() => setOpen(true)} title={blocked ?? undefined}>
          Submit application…
        </Button>
      ) : (
        <div className="space-y-3 rounded-md border border-indigo-200 p-3 dark:border-indigo-900">
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            <span>
              I reviewed the filled form and want to submit this application to {sub.company_name} now.
            </span>
          </label>
          <div className="flex gap-2">
            <Button disabled={!checked || busy} onClick={submit}>
              {busy ? "Submitting…" : "Submit to " + sub.company_name}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Not yet
            </Button>
          </div>
        </div>
      )}
      {blocked && <p className="text-xs text-zinc-500">{blocked}</p>}
      {error && <Alert tone="error">{error}</Alert>}
    </div>
  );
}

export function ApplicationReview({ id }: { id: string }) {
  const { data: sub, error, isLoading, mutate } = useSubmission(id);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [shot, setShot] = useState<number | null>(null);

  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  if (isLoading || !sub) return <p className="text-sm text-zinc-500">Loading…</p>;

  const refresh = () => void mutate();
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      refresh();
    } catch (e) {
      setActionError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const save = (key: string, value: string) =>
    act(async () => {
      const updated = await automationApi.edit(sub.id, key, value);
      await mutate(updated, { revalidate: false });
      setEditing(null);
    });

  const review = sub.review ?? {};
  const fields = new Map(sub.editable_fields.map((f) => [f.key, f]));
  const editorFor = (key: string, label: string, kind: string, value: string) => (
    <FieldEditor
      field={fields.get(key) ?? { key, label, kind, options: [] }}
      initial={value}
      busy={busy}
      onSave={(v) => save(key, v)}
    />
  );
  const latest = shot ?? sub.screenshots.length;
  const waiting = sub.status === "waiting_for_review";

  return (
    <div className="space-y-6">
      <ApplicationsNav />
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold">{sub.job_title}</h1>
          <SubmissionStatusBadge status={sub.status} />
          <Badge tone="indigo">approval mode</Badge>
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {sub.company_name} ·{" "}
          <a href={sub.apply_url} target="_blank" rel="noreferrer noopener" className="underline">
            application form
          </a>{" "}
          · attempt {sub.attempts}
          {sub.package_id && (
            <>
              {" "}
              ·{" "}
              <Link href={`/packages/${sub.package_id}`} className="underline">
                package
              </Link>
            </>
          )}{" "}
          ·{" "}
          <Link href={`/applications/logs?submission=${sub.id}`} className="underline">
            logs
          </Link>
        </p>
      </div>
      {actionError && <Alert tone="error">{actionError}</Alert>}

      {(sub.status === "queued" || sub.status === "in_progress") && (
        <Card title={sub.status === "queued" ? "Waiting for a browser" : "Filling the application form"}>
          <Progress step={sub.status === "queued" ? "" : sub.step} />
        </Card>
      )}
      {sub.status === "submitting" && <Alert tone="info">Submitting the application you confirmed…</Alert>}
      {sub.status === "submitted" && (
        <Alert tone="info">
          Submitted {formatDateTime(sub.submitted_at)} (you confirmed {formatDateTime(sub.confirmed_at)}).
          {sub.confirmation_text && <div className="mt-1 italic">“{sub.confirmation_text}”</div>}
        </Alert>
      )}
      {sub.status === "cancelled" && <Alert tone="warning">Cancelled. Nothing was submitted.</Alert>}
      {sub.status === "failed" && (
        <Card title="What went wrong">
          <FailureRecovery submission={sub} hint={sub.recovery_hint} onChange={refresh} />
        </Card>
      )}

      {waiting && (
        <>
          {!sub.live && (
            <Alert tone="warning">
              The browser window for this form was closed (idle, restarted, or crashed). Your edits are saved:
              Retry reopens the form and fills it again.
            </Alert>
          )}
          {review.captcha && (
            <Alert tone="warning">
              The site shows a CAPTCHA. Run the app with AUTOMATION_HEADLESS=false to solve it in the browser
              window, then submit again.
            </Alert>
          )}
          {review.form_changed && (
            <Alert tone="info">The form changed since the last attempt; every field was checked again.</Alert>
          )}
          <Card title="Review before submitting">
            <ul className="space-y-2 text-sm">
              {docLine("Resume", review.resume)}
              {docLine("Cover letter", review.cover_letter)}
              <li className="flex flex-wrap items-center gap-2">
                <Badge tone="green">Answers</Badge>
                <span>{review.answers?.length ?? 0} inserted</span>
              </li>
              <li className="flex flex-wrap items-center gap-2">
                <Badge tone={review.missing?.length ? "amber" : "green"}>Missing fields</Badge>
                <span>{review.missing?.length ?? 0}</span>
              </li>
              <li className="flex flex-wrap items-center gap-2">
                <Badge tone={review.problems?.length ? "red" : "green"}>Validation problems</Badge>
                <span>{review.problems?.length ?? 0}</span>
              </li>
            </ul>
            <div className="mt-4 flex flex-wrap gap-2 border-t border-zinc-200 pt-4 dark:border-zinc-800">
              <SubmitPanel sub={sub} onDone={refresh} />
              <Button variant="secondary" disabled={busy} onClick={() => act(() => automationApi.retry(sub.id))}>
                Retry (reopen and refill)
              </Button>
              <Button variant="danger" disabled={busy} onClick={() => act(() => automationApi.cancel(sub.id))}>
                Cancel
              </Button>
            </div>
          </Card>

          {(review.missing?.length ?? 0) > 0 && (
            <Card title="Missing fields">
              <ul className="space-y-4">
                {review.missing?.map((m) => (
                  <li key={m.key} className="space-y-1">
                    <div className="text-sm font-medium">{m.label}</div>
                    <div className="text-xs text-zinc-500">{m.reason}</div>
                    {m.kind !== "file" && editorFor(m.key, m.label, m.kind, "")}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {(review.problems?.length ?? 0) > 0 && (
            <Card title="Validation problems">
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {review.problems?.map((p, i) => (
                  <li key={i}>
                    {p.label && <strong>{p.label}: </strong>}
                    {p.message}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Answers inserted">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-zinc-500">
                <tr>
                  <th className="py-2 pr-4">Question</th>
                  <th className="py-2 pr-4">Answer</th>
                  <th className="py-2 pr-4">From</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {review.answers?.map((a) => (
                  <tr key={a.key} className="align-top">
                    <td className="py-2 pr-4">{a.label}</td>
                    <td className="py-2 pr-4">
                      {editing === a.key ? (
                        editorFor(a.key, a.label, a.kind, a.value)
                      ) : (
                        <span className="whitespace-pre-wrap">{a.value}</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 text-xs text-zinc-500">{SOURCE[a.source] ?? a.source}</td>
                    <td className="py-2 text-right">
                      {!a.sensitive && (
                        <Button variant="ghost" onClick={() => setEditing(editing === a.key ? null : a.key)}>
                          {editing === a.key ? "Close" : "Edit"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {(review.left_for_you?.length ?? 0) > 0 && (
            <Card title="Left for you">
              <p className="mb-2 text-xs text-zinc-500">
                Optional questions, consent boxes and anything no fact supports are never guessed.
              </p>
              <ul className="space-y-3 text-sm">
                {review.left_for_you
                  ?.filter((f) => !review.missing?.some((m) => m.key === f.key))
                  .map((f) => (
                    <li key={f.key} className="space-y-1">
                      <div>
                        <span className="font-medium">{f.label}</span>{" "}
                        <Badge tone={f.status === "consent" ? "amber" : "neutral"}>{f.status.replace("_", " ")}</Badge>
                      </div>
                      <div className="text-xs text-zinc-500">{f.reason}</div>
                      {f.kind !== "file" && !f.sensitive && editing === f.key
                        ? editorFor(f.key, f.label, f.kind, "")
                        : f.kind !== "file" &&
                          !f.sensitive && (
                            <Button variant="ghost" onClick={() => setEditing(f.key)}>
                              Answer
                            </Button>
                          )}
                    </li>
                  ))}
              </ul>
            </Card>
          )}
        </>
      )}

      {sub.screenshots.length > 0 && (
        <Card title="Screenshots">
          <div className="mb-3 flex flex-wrap gap-2">
            {sub.screenshots.map((s) => (
              <Button key={s.index} variant={s.index === latest ? "primary" : "secondary"} onClick={() => setShot(s.index)}>
                {s.index}. {s.label}
              </Button>
            ))}
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element -- served by the local API */}
          <img
            src={automationApi.screenshotUrl(sub.id, latest)}
            alt={`Screenshot ${latest}: ${sub.screenshots[latest - 1]?.label ?? ""}`}
            className="max-h-[48rem] w-full rounded border border-zinc-200 object-contain object-top dark:border-zinc-800"
          />
        </Card>
      )}
    </div>
  );
}
