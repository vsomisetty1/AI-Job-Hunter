"use client";

// Agent activity: per-agent totals and every run (agents and pipeline stages),
// with outcome, duration, tokens, cost and errors.
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { useAgentNames, useAgentRuns, useAgentSummary } from "@/hooks/useAgentRuns";
import { errorMessage } from "@/lib/api/client";
import { formatDateTime } from "@/lib/format";
import type { AgentRun, AgentRunStatus, AgentStat } from "@/types";

const PAGE = 50;
const STATUS_TONE: Record<AgentRunStatus, "green" | "red" | "amber" | "neutral"> = {
  succeeded: "green",
  failed: "red",
  running: "amber",
  cancelled: "neutral",
};

export function formatMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${(ms / 60_000).toFixed(1)} min`;
}

export function formatUsd(v: number): string {
  if (v === 0) return "$0";
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`;
}

const tokens = (i: number, o: number) => (i || o ? `${i.toLocaleString()} / ${o.toLocaleString()}` : "—");

const SUMMARY_COLUMNS: Column<AgentStat>[] = [
  { key: "agent", header: "Agent", cell: (a) => <span className="font-medium">{a.agent_name}</span> },
  { key: "runs", header: "Runs", cell: (a) => a.runs, className: "tabular-nums" },
  {
    key: "failed",
    header: "Failed",
    cell: (a) => (a.failed ? <Badge tone="red">{a.failed}</Badge> : 0),
    className: "tabular-nums",
  },
  { key: "avg", header: "Avg time", cell: (a) => formatMs(a.avg_duration_ms), className: "tabular-nums" },
  {
    key: "tokens",
    header: "Tokens in / out",
    cell: (a) => tokens(a.input_tokens, a.output_tokens),
    className: "tabular-nums",
  },
  { key: "cost", header: "Cost", cell: (a) => formatUsd(a.cost_usd), className: "tabular-nums" },
  { key: "last", header: "Last run", cell: (a) => formatDateTime(a.last_run_at) },
];

const RUN_COLUMNS: Column<AgentRun>[] = [
  { key: "started", header: "Started", cell: (r) => formatDateTime(r.started_at) },
  { key: "agent", header: "Agent", cell: (r) => r.agent_name },
  { key: "status", header: "Status", cell: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge> },
  { key: "time", header: "Time", cell: (r) => formatMs(r.duration_ms), className: "tabular-nums" },
  {
    key: "tokens",
    header: "Tokens in / out",
    cell: (r) => tokens(r.input_tokens, r.output_tokens),
    className: "tabular-nums",
  },
  { key: "cost", header: "Cost", cell: (r) => formatUsd(r.cost_usd), className: "tabular-nums" },
  {
    key: "error",
    header: "Error",
    cell: (r) => (r.error ? <span className="text-red-700 dark:text-red-400">{r.error}</span> : null),
  },
];

export function AgentRunsTable() {
  const [days, setDays] = useState(30);
  const [agent, setAgent] = useState("");
  const [status, setStatus] = useState<AgentRunStatus | "">("");
  const [offset, setOffset] = useState(0);
  const summary = useAgentSummary(days);
  const names = useAgentNames();
  const runs = useAgentRuns({ agent: agent || undefined, status: status || undefined, limit: PAGE, offset });
  const error = summary.error ?? runs.error;
  const total = runs.data?.total ?? 0;

  return (
    <div className="space-y-6">
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      <Card
        title="Agents"
        actions={
          <label className="text-sm">
            <span className="mr-2 text-zinc-500">Period</span>
            <select
              aria-label="Period"
              className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-950"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={1}>Last 24 hours</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={365}>Last year</option>
            </select>
          </label>
        }
      >
        {summary.data && (
          <p className="mb-3 text-sm text-zinc-600 dark:text-zinc-400">
            {summary.data.total_runs} runs, {summary.data.failed_runs} failed, Claude cost{" "}
            {formatUsd(summary.data.total_cost_usd)}.
          </p>
        )}
        <DataTable
          caption="Runs per agent"
          columns={SUMMARY_COLUMNS}
          rows={summary.data?.agents ?? []}
          rowKey={(a) => a.agent_name}
          empty={summary.data ? "No agent has run in this period." : "Loading…"}
        />
      </Card>

      <Card
        title="Runs"
        actions={
          <>
            <select
              aria-label="Agent"
              className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-950"
              value={agent}
              onChange={(e) => {
                setAgent(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">All agents</option>
              {(names.data ?? []).map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
            <select
              aria-label="Status"
              className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-950"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as AgentRunStatus | "");
                setOffset(0);
              }}
            >
              <option value="">Any status</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </>
        }
      >
        <DataTable
          caption="Agent runs"
          columns={RUN_COLUMNS}
          rows={runs.data?.items ?? []}
          rowKey={(r) => r.id}
          empty={runs.data ? "No runs match." : "Loading…"}
        />
        {total > PAGE && (
          <div className="mt-4 flex items-center justify-between text-sm text-zinc-500">
            <span>
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
                Previous
              </Button>
              <Button
                variant="secondary"
                disabled={offset + PAGE >= total}
                onClick={() => setOffset(offset + PAGE)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
