"use client";

// SWR hooks for discovered jobs, tracked companies and discovery runs.

import useSWR from "swr";

import { companiesApi, discoveryApi, jobsApi } from "@/lib/api/jobs";
import type {
  Company,
  DirectoryEntry,
  DiscoveryRun,
  DiscoveryRunDetail,
  JobDetail,
  JobRaw,
  JobSearch,
  JobSummary,
  Page,
  SourceHealth,
} from "@/types";

export function useJobSearch(params: JobSearch) {
  return useSWR<Page<JobSummary>>(["jobs", JSON.stringify(params)], () => jobsApi.search(params), {
    keepPreviousData: true,
  });
}

export function useJob(id: string | null) {
  return useSWR<JobDetail>(id ? ["job", id] : null, () => jobsApi.get(id as string));
}

export function useJobRaw(id: string | null) {
  return useSWR<JobRaw>(id ? ["job-raw", id] : null, () => jobsApi.raw(id as string));
}

export function useCompanies() {
  return useSWR<Company[]>("companies", companiesApi.list);
}

export function useDirectory() {
  return useSWR<DirectoryEntry[]>("company-directory", companiesApi.directory);
}

/** Recent runs; polls every 2 s while one is running. */
export function useDiscoveryRuns() {
  return useSWR<Page<DiscoveryRun>>("discovery-runs", () => discoveryApi.runs(), {
    refreshInterval: (page) => (page?.items.some((r) => r.status === "running") ? 2000 : 0),
  });
}

export function useDiscoveryRun(id: string | null) {
  return useSWR<DiscoveryRunDetail>(id ? ["discovery-run", id] : null, () => discoveryApi.run(id as string), {
    refreshInterval: (run) => (run?.status === "running" ? 2000 : 0),
  });
}

export function useConnectorHealth(probe: boolean) {
  return useSWR<SourceHealth[]>(["connector-health", probe], () => discoveryApi.health(probe));
}
