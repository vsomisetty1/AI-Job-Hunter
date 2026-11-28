"use client";

// SWR hooks for agent activity.

import useSWR from "swr";

import { type AgentRunFilter, agentRunsApi } from "@/lib/api/agentRuns";
import type { AgentActivitySummary, AgentRun, Page } from "@/types";

/** Refreshes every 10 s while any listed run is still running. */
export function useAgentRuns(filter: AgentRunFilter) {
  return useSWR<Page<AgentRun>>(["agent-runs", JSON.stringify(filter)], () => agentRunsApi.list(filter), {
    keepPreviousData: true,
    refreshInterval: (data) => (data?.items.some((r) => r.status === "running") ? 10_000 : 0),
  });
}

export function useAgentSummary(days: number) {
  return useSWR<AgentActivitySummary>(["agent-runs-summary", days], () => agentRunsApi.summary(days));
}

export function useAgentNames() {
  return useSWR<string[]>("agent-names", agentRunsApi.agents);
}
