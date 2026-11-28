"use client";

// SWR hooks for application automation. Runs that are moving are polled.
import useSWR from "swr";

import { automationApi } from "@/lib/api/applications";
import type {
  AutomationLog,
  AutomationQueue,
  AutomationStatus,
  LogLevel,
  Page,
  SubmissionDetail,
  SubmissionStatus,
  SubmissionSummary,
} from "@/types";

export const MOVING: SubmissionStatus[] = ["queued", "in_progress", "submitting"];

export function useAutomationQueue() {
  return useSWR<AutomationQueue>("automation-queue", () => automationApi.queue(), {
    refreshInterval: (q) => (q?.active.some((s) => MOVING.includes(s.status)) ? 2000 : 15000),
  });
}

export function useSubmission(id: string | null) {
  return useSWR<SubmissionDetail>(id ? ["submission", id] : null, () => automationApi.get(id as string), {
    // While the form is open, keep the "browser open" flag fresh too.
    refreshInterval: (s) =>
      s && MOVING.includes(s.status) ? 1500 : s?.status === "waiting_for_review" ? 10000 : 0,
  });
}

export function useSubmissions(status: SubmissionStatus[]) {
  return useSWR<Page<SubmissionSummary>>(["submissions", status.join(",")], () =>
    automationApi.list({ status, limit: 100 }),
  );
}

export function useAutomationLogs(submissionId: string | undefined, level: LogLevel[]) {
  return useSWR<Page<AutomationLog>>(["automation-logs", submissionId ?? "", level.join(",")], () =>
    automationApi.logs({ submissionId, level, limit: 200 }),
    { refreshInterval: 5000 },
  );
}

export function useAutomationStatus() {
  return useSWR<AutomationStatus>("automation-status", () => automationApi.status());
}
