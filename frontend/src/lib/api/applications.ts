// Application automation API (approval mode): fill an approved package into the
// job's application form, review it, then submit only with an explicit confirmation.
import type {
  AutomationLog,
  AutomationQueue,
  AutomationStatus,
  LogLevel,
  Page,
  SubmissionDetail,
  SubmissionStarted,
  SubmissionStatus,
  SubmissionSummary,
} from "@/types";

import { apiFetch, apiUrl } from "./client";

const post = <T>(path: string, body?: unknown) =>
  apiFetch<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const automationApi = {
  status: () => apiFetch<AutomationStatus>("/automation/status"),
  queue: () => apiFetch<AutomationQueue>("/automation/queue"),
  list: (params: { status?: SubmissionStatus[]; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    for (const s of params.status ?? []) qs.append("status", s);
    qs.set("limit", String(params.limit ?? 50));
    if (params.offset) qs.set("offset", String(params.offset));
    return apiFetch<Page<SubmissionSummary>>(`/automation/submissions?${qs.toString()}`);
  },
  get: (id: string) => apiFetch<SubmissionDetail>(`/automation/submissions/${id}`),
  start: (packageId: string) => post<SubmissionStarted>("/automation/submissions", { package_id: packageId }),
  edit: (id: string, key: string, value: string | boolean | string[]) =>
    apiFetch<SubmissionDetail>(`/automation/submissions/${id}/fields`, {
      method: "PATCH",
      body: JSON.stringify({ key, value }),
    }),
  retry: (id: string) => post<SubmissionStarted>(`/automation/submissions/${id}/retry`),
  cancel: (id: string) => post<SubmissionDetail>(`/automation/submissions/${id}/cancel`),
  // Approval mode: the backend only accepts an explicit confirm: true.
  submit: (id: string) => post<SubmissionStarted>(`/automation/submissions/${id}/submit`, { confirm: true }),
  logs: (params: { submissionId?: string; level?: LogLevel[]; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.submissionId) qs.set("submission_id", params.submissionId);
    for (const l of params.level ?? []) qs.append("level", l);
    qs.set("limit", String(params.limit ?? 100));
    if (params.offset) qs.set("offset", String(params.offset));
    return apiFetch<Page<AutomationLog>>(`/automation/logs?${qs.toString()}`);
  },
  screenshotUrl: (id: string, index: number) => apiUrl(`/automation/submissions/${id}/screenshots/${index}`),
};
