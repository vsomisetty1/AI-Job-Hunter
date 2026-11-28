// Agent activity: what every agent and pipeline stage did, how long it took and what it cost.
import { AgentRunsTable } from "@/components/activity/AgentRunsTable";

export default function ActivityPage() {
  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Agent activity</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Every agent run and pipeline stage, with its outcome, timing, tokens and cost.
        </p>
      </header>
      <AgentRunsTable />
    </div>
  );
}
