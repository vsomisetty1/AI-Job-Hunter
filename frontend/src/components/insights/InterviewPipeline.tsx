"use client";

// Interview pipeline: every submitted application by where it stands, and a
// panel to record what happened (responses, interviews, offers, rejections,
// withdrawals) and update it later.
import Link from "next/link";
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useOutcomes, usePipeline } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";
import { outcomesApi } from "@/lib/api/insights";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { EventStatus, InterviewStage, PipelineItem } from "@/types";

import { STAGE_LABEL } from "./charts";
import { InsightsNav } from "./InsightsNav";

export const STAGES: InterviewStage[] = [
  "recruiter_response",
  "recruiter_screen",
  "phone_screen",
  "technical_interview",
  "hiring_manager_interview",
  "onsite",
  "final_round",
  "offer",
  "rejection",
  "withdrawal",
];
const ALWAYS_COMPLETED: InterviewStage[] = ["recruiter_response", "offer", "rejection", "withdrawal"];
const STATUSES: EventStatus[] = ["completed", "scheduled", "cancelled", "no_show"];
const STATUS_LABEL: Record<EventStatus, string> = {
  completed: "completed",
  scheduled: "scheduled",
  cancelled: "cancelled",
  no_show: "no-show",
};

const COLUMNS: { key: string; label: string; match: (p: PipelineItem) => boolean }[] = [
  { key: "waiting", label: "Waiting for a reply", match: (p) => p.status === "submitted" && !p.responded_at },
  { key: "talking", label: "Responded", match: (p) => p.status === "submitted" && !!p.responded_at },
  { key: "interview", label: "Interviewing", match: (p) => p.status === "interview" },
  { key: "offer", label: "Offer", match: (p) => p.status === "offer" },
  { key: "closed", label: "Rejected or withdrawn", match: (p) => p.status === "rejected" || p.status === "withdrawn" },
];

const localNow = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

function EventForm({ applicationId, onSaved }: { applicationId: string; onSaved: () => void }) {
  const [stage, setStage] = useState<InterviewStage>("recruiter_response");
  const [status, setStatus] = useState<EventStatus>("completed");
  const [when, setWhen] = useState(localNow());
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fixed = ALWAYS_COMPLETED.includes(stage);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await outcomesApi.addEvent(applicationId, {
        stage,
        status: fixed ? "completed" : status,
        occurred_at: new Date(when).toISOString(),
        notes: notes.trim() || null,
      });
      setNotes("");
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const input =
    "rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-950";
  return (
    <div className="space-y-2 rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="text-sm font-medium">Record what happened</div>
      <div className="flex flex-wrap gap-2">
        <label className="flex flex-col text-xs text-zinc-500">
          Stage
          <select className={input} value={stage} onChange={(e) => setStage(e.target.value as InterviewStage)}>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-zinc-500">
          Status
          <select
            className={input}
            value={fixed ? "completed" : status}
            disabled={fixed}
            onChange={(e) => setStatus(e.target.value as EventStatus)}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-zinc-500">
          When
          <input type="datetime-local" className={input} value={when} onChange={(e) => setWhen(e.target.value)} />
        </label>
      </div>
      <label className="flex flex-col text-xs text-zinc-500">
        Notes
        <textarea className={input} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      {error && <Alert tone="error">{error}</Alert>}
      <Button disabled={busy || !when} onClick={save}>
        Save
      </Button>
    </div>
  );
}

function OutcomePanel({ id, onChange }: { id: string; onChange: () => void }) {
  const { data, error, mutate } = useOutcomes(id);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  if (error) return <Alert tone="error">{errorMessage(error)}</Alert>;
  if (!data) return <p className="text-sm text-zinc-500">Loading…</p>;
  const refresh = () => {
    void mutate();
    onChange();
  };
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
  return (
    <div className="space-y-4">
      <div>
        <div className="text-lg font-semibold">{data.job_title}</div>
        <div className="text-sm text-zinc-500">
          {data.company_name} · applied {formatDateTime(data.submitted_at)}
          {data.package_id && (
            <>
              {" "}
              ·{" "}
              <Link href={`/packages/${data.package_id}`} className="underline">
                package
              </Link>
            </>
          )}
        </div>
      </div>
      {actionError && <Alert tone="error">{actionError}</Alert>}
      {data.interview_events.length === 0 ? (
        <p className="text-sm text-zinc-500">Nothing recorded yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
          {data.interview_events.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="font-medium">{STAGE_LABEL[e.stage]}</span>
              <span className="text-xs text-zinc-500">{formatDateTime(e.occurred_at)}</span>
              {ALWAYS_COMPLETED.includes(e.stage) ? (
                <Badge>completed</Badge>
              ) : (
                <select
                  aria-label={`Status of ${STAGE_LABEL[e.stage]}`}
                  className="rounded border border-zinc-300 bg-white px-1 py-0.5 text-xs dark:border-zinc-700 dark:bg-zinc-950"
                  value={e.status}
                  disabled={busy}
                  onChange={(ev) =>
                    act(() => outcomesApi.updateEvent(id, e.id, { status: ev.target.value as EventStatus }))
                  }
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {STATUS_LABEL[s]}
                    </option>
                  ))}
                </select>
              )}
              {e.notes && <span className="w-full text-xs text-zinc-500">{e.notes}</span>}
              <Button variant="ghost" disabled={busy} onClick={() => act(() => outcomesApi.deleteEvent(id, e.id))}>
                Delete
              </Button>
            </li>
          ))}
        </ul>
      )}
      <EventForm applicationId={id} onSaved={refresh} />
    </div>
  );
}

export function InterviewPipeline() {
  const { data, error, isLoading, mutate } = usePipeline();
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Interview pipeline</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Record every reply, interview, offer, rejection or withdrawal. Analytics and recommendations are only as
          good as these records.
        </p>
        <InsightsNav />
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && data.length === 0 && (
        <Card>
          <p className="text-sm text-zinc-500">
            No submitted applications yet. Submit one from{" "}
            <Link href="/applications" className="underline">
              Applications
            </Link>{" "}
            or mark a package as applied.
          </p>
        </Card>
      )}
      {data && data.length > 0 && (
        <div className="grid gap-6 lg:grid-cols-[1fr_24rem]">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {COLUMNS.map((col) => {
              const items = data.filter(col.match);
              return (
                <section key={col.key} aria-label={col.label} className="space-y-2">
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                    {col.label} ({items.length})
                  </h2>
                  {items.map((p) => (
                    <button
                      key={p.application_id}
                      onClick={() => setSelected(p.application_id)}
                      aria-pressed={selected === p.application_id}
                      className={`w-full rounded-md border p-2 text-left text-sm ${
                        selected === p.application_id
                          ? "border-indigo-400 bg-indigo-50 dark:border-indigo-700 dark:bg-indigo-950"
                          : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
                      }`}
                    >
                      <div className="font-medium">{p.job_title}</div>
                      <div className="text-xs text-zinc-500">{p.company_name}</div>
                      <div className="mt-1 flex flex-wrap gap-1 text-xs">
                        {p.current_stage && <Badge tone="indigo">{STAGE_LABEL[p.current_stage]}</Badge>}
                        {p.next_scheduled && (
                          <Badge tone="amber">
                            {STAGE_LABEL[p.next_scheduled.stage]} {formatDateTime(p.next_scheduled.occurred_at)}
                          </Badge>
                        )}
                        {!p.current_stage && <span className="text-zinc-500">applied {formatRelative(p.submitted_at)}</span>}
                      </div>
                    </button>
                  ))}
                </section>
              );
            })}
          </div>
          <Card>
            {selected ? (
              <OutcomePanel id={selected} onChange={() => void mutate()} />
            ) : (
              <p className="text-sm text-zinc-500">Pick an application to record or update its outcome.</p>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
