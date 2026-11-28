// Learning & insights API: outcome tracking (interview pipeline) and analytics.
import type {
  AnalyticsSummary,
  ApplicationOutcomes,
  ApplicationStatus,
  BoardStat,
  CompanyStat,
  EventStatus,
  HistoryPoint,
  InsightsReport,
  InterviewStage,
  PipelineItem,
  Recommendation,
  ResumeAnalytics,
  TimelineEntry,
} from "@/types";

import { apiFetch } from "./client";

export interface EventInput {
  stage: InterviewStage;
  status: EventStatus;
  occurred_at: string;
  notes?: string | null;
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const outcomesApi = {
  pipeline: (status: ApplicationStatus[] = []) => {
    const qs = new URLSearchParams();
    for (const s of status) qs.append("status", s);
    return apiFetch<PipelineItem[]>(`/applications${qs.size ? `?${qs.toString()}` : ""}`);
  },
  get: (id: string) => apiFetch<ApplicationOutcomes>(`/applications/${id}`),
  timeline: (limit = 200) => apiFetch<TimelineEntry[]>(`/applications/timeline?limit=${limit}`),
  addEvent: (id: string, body: EventInput) =>
    apiFetch<ApplicationOutcomes>(`/applications/${id}/events`, json("POST", body)),
  updateEvent: (id: string, eventId: string, body: Partial<EventInput>) =>
    apiFetch<ApplicationOutcomes>(`/applications/${id}/events/${eventId}`, json("PATCH", body)),
  deleteEvent: (id: string, eventId: string) =>
    apiFetch<void>(`/applications/${id}/events/${eventId}`, { method: "DELETE" }),
};

export const insightsApi = {
  summary: () => apiFetch<AnalyticsSummary>("/insights/summary"),
  companies: () => apiFetch<CompanyStat[]>("/insights/companies"),
  boards: () => apiFetch<BoardStat[]>("/insights/boards"),
  resumes: () => apiFetch<ResumeAnalytics>("/insights/resumes"),
  insights: () => apiFetch<InsightsReport>("/insights"),
  recommendations: (includeDismissed = false) =>
    apiFetch<Recommendation[]>(`/insights/recommendations?include_dismissed=${includeDismissed}`),
  setState: (key: string, state: "dismissed" | "done" | null) =>
    apiFetch<{ key: string; state: string | null }>(
      `/insights/recommendations/${encodeURIComponent(key)}/state`,
      json("PUT", { state }),
    ),
  history: () => apiFetch<HistoryPoint[]>("/insights/history"),
  refresh: () => apiFetch<{ stored: boolean; records: number; computed_at: string }>("/insights/refresh", { method: "POST" }),
  setIndustry: (companyId: string, industry: string) =>
    apiFetch<unknown>(`/companies/${companyId}`, json("PATCH", { industry })),
};
