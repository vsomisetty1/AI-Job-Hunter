// Jobs, companies and discovery API calls.

import type {
  Company,
  DirectoryEntry,
  DiscoveryRun,
  DiscoveryRunDetail,
  DiscoveryStarted,
  JobDetail,
  JobRaw,
  JobSearch,
  JobSource,
  JobSummary,
  Page,
  ScoringStarted,
  ScoringSummary,
  SourceHealth,
} from "@/types";

import { apiFetch } from "./client";

/** Query string from search params; empty values are left out. */
export function searchQuery(params: JobSearch): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue;
    qs.set(key, String(value));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export const jobsApi = {
  search: (params: JobSearch) => apiFetch<Page<JobSummary>>(`/jobs${searchQuery(params)}`),
  get: (id: string) => apiFetch<JobDetail>(`/jobs/${id}`),
  raw: (id: string) => apiFetch<JobRaw>(`/jobs/${id}/raw`),
};

export const companiesApi = {
  list: () => apiFetch<Company[]>("/companies"),
  directory: () => apiFetch<DirectoryEntry[]>("/companies/directory"),
  add: (source: JobSource, slug: string) =>
    apiFetch<Company>("/companies", { method: "POST", body: JSON.stringify({ source, slug }) }),
  addSuggested: (boards: { source: JobSource; slug: string }[]) =>
    apiFetch<Company[]>("/companies/suggested", { method: "POST", body: JSON.stringify({ boards }) }),
  setTracked: (id: string, is_tracked: boolean) =>
    apiFetch<Company>(`/companies/${id}`, { method: "PATCH", body: JSON.stringify({ is_tracked }) }),
  remove: (id: string) => apiFetch<void>(`/companies/${id}`, { method: "DELETE" }),
};

export const discoveryApi = {
  start: (companyIds?: string[]) =>
    apiFetch<DiscoveryStarted>("/discovery/runs", {
      method: "POST",
      body: JSON.stringify(companyIds ? { company_ids: companyIds } : {}),
    }),
  runs: (limit = 20) => apiFetch<Page<DiscoveryRun>>(`/discovery/runs?limit=${limit}`),
  run: (id: string) => apiFetch<DiscoveryRunDetail>(`/discovery/runs/${id}`),
  health: (probe = false) => apiFetch<SourceHealth[]>(`/discovery/health${probe ? "?probe=true" : ""}`),
};

export const scoringApi = {
  run: () => apiFetch<ScoringStarted>("/scoring/runs", { method: "POST" }),
  summary: () => apiFetch<ScoringSummary>("/scoring/summary"),
};
