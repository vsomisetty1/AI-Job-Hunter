// Agent activity API calls (agent_runs).

import type { AgentActivitySummary, AgentRun, AgentRunStatus, Page } from "@/types";

import { apiFetch } from "./client";

export interface AgentRunFilter {
  agent?: string;
  status?: AgentRunStatus;
  limit?: number;
  offset?: number;
}

export const agentRunsApi = {
  list: (filter: AgentRunFilter = {}) => {
    const qs = new URLSearchParams();
    if (filter.agent) qs.set("agent", filter.agent);
    if (filter.status) qs.set("status", filter.status);
    qs.set("limit", String(filter.limit ?? 50));
    qs.set("offset", String(filter.offset ?? 0));
    return apiFetch<Page<AgentRun>>(`/agent-runs?${qs.toString()}`);
  },
  summary: (days = 30) => apiFetch<AgentActivitySummary>(`/agent-runs/summary?days=${days}`),
  agents: () => apiFetch<string[]>("/agent-runs/agents"),
};
