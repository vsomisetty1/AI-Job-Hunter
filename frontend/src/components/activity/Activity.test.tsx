import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { json, routeFetch } from "@/test/factories";
import { renderSWR } from "@/test/swr";
import type { AgentActivitySummary, AgentRun } from "@/types";

import { AgentRunsTable, formatMs, formatUsd } from "./AgentRunsTable";

afterEach(() => vi.unstubAllGlobals());

const run = (overrides: Partial<AgentRun> = {}): AgentRun => ({
  id: "r1",
  agent_name: "job_scoring",
  status: "succeeded",
  job_id: null,
  application_id: null,
  input_summary: {},
  output_summary: {},
  error: null,
  input_tokens: 1200,
  output_tokens: 300,
  cost_usd: 0.0042,
  started_at: "2026-11-27T10:00:00Z",
  finished_at: "2026-11-27T10:00:02Z",
  duration_ms: 2300,
  ...overrides,
});

const summary: AgentActivitySummary = {
  days: 30,
  total_runs: 3,
  failed_runs: 1,
  total_cost_usd: 0.0042,
  agents: [
    {
      agent_name: "job_scoring",
      runs: 3,
      succeeded: 2,
      failed: 1,
      running: 0,
      input_tokens: 1200,
      output_tokens: 300,
      cost_usd: 0.0042,
      avg_duration_ms: 1500,
      last_run_at: "2026-11-27T10:00:00Z",
    },
  ],
};

const page = (items: AgentRun[], total = items.length) => json({ items, total, limit: 50, offset: 0 });

describe("AgentRunsTable", () => {
  it("shows per-agent totals and each run with its outcome and error", async () => {
    routeFetch({
      "GET /agent-runs/summary?days=30": () => json(summary),
      "GET /agent-runs/agents": () => json(["job_scoring", "resume_parser"]),
      "GET /agent-runs?limit=50&offset=0": () =>
        page([run(), run({ id: "r2", status: "failed", error: "Claude timed out", cost_usd: 0 })]),
    });
    renderSWR(<AgentRunsTable />);
    expect(await screen.findByText("3 runs, 1 failed, Claude cost $0.0042.")).toBeInTheDocument();
    const runs = await screen.findByRole("table", { name: "Agent runs" });
    expect(within(runs).getByText("Claude timed out")).toBeInTheDocument();
    expect(within(runs).getByText("failed")).toBeInTheDocument();
    expect(within(runs).getAllByText("1,200 / 300")).toHaveLength(2);
    expect(within(runs).getAllByText("2.3 s")).toHaveLength(2);
  });

  it("filters by agent and status", async () => {
    const fetch = routeFetch({
      "GET /agent-runs/summary?days=30": () => json(summary),
      "GET /agent-runs/agents": () => json(["job_scoring", "resume_parser"]),
      "GET /agent-runs?limit=50&offset=0": () => page([run()]),
      "GET /agent-runs?agent=resume_parser&limit=50&offset=0": () => page([]),
      "GET /agent-runs?agent=resume_parser&status=failed&limit=50&offset=0": () => page([]),
    });
    renderSWR(<AgentRunsTable />);
    await screen.findByRole("option", { name: "resume_parser" });
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "resume_parser");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    expect(await screen.findByText("No runs match.")).toBeInTheDocument();
    const urls = fetch.mock.calls.map((c) => String(c[0]));
    expect(urls.some((u) => u.endsWith("/agent-runs?agent=resume_parser&status=failed&limit=50&offset=0"))).toBe(
      true,
    );
  });

  it("says when nothing has run", async () => {
    routeFetch({
      "GET /agent-runs/summary?days=30": () => json({ ...summary, agents: [], total_runs: 0, failed_runs: 0 }),
      "GET /agent-runs/agents": () => json([]),
      "GET /agent-runs?limit=50&offset=0": () => page([]),
    });
    renderSWR(<AgentRunsTable />);
    expect(await screen.findByText("No agent has run in this period.")).toBeInTheDocument();
  });
});

describe("formatting", () => {
  it("formats durations and costs", () => {
    expect(formatMs(null)).toBe("—");
    expect(formatMs(850)).toBe("850 ms");
    expect(formatMs(2300)).toBe("2.3 s");
    expect(formatMs(90_000)).toBe("1.5 min");
    expect(formatUsd(0)).toBe("$0");
    expect(formatUsd(0.0042)).toBe("$0.0042");
    expect(formatUsd(1.234)).toBe("$1.23");
  });
});
