"use client";

// Company insights: applications, responses, interviews and offers per company.
// You can set each company's industry here (it is never guessed).
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Card } from "@/components/ui/Card";
import { useCompanyAnalytics } from "@/hooks/useInsights";
import { errorMessage } from "@/lib/api/client";
import { insightsApi } from "@/lib/api/insights";
import type { CompanyStat, SegmentStat } from "@/types";

import { SegmentTable } from "./charts";
import { DataNote, InsightsNav } from "./InsightsNav";

function IndustryField({ row, onSaved }: { row: CompanyStat; onSaved: () => void }) {
  const [value, setValue] = useState(row.industry ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    if ((row.industry ?? "") === value.trim()) return;
    try {
      await insightsApi.setIndustry(row.company_id, value.trim());
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <div className="flex items-center gap-2">
      <input
        aria-label={`Industry of ${row.label}`}
        placeholder="Industry (optional)"
        value={value}
        maxLength={80}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => e.key === "Enter" && void save()}
        className="w-40 rounded border border-zinc-300 bg-white px-2 py-0.5 text-xs dark:border-zinc-700 dark:bg-zinc-950"
      />
      <span className="text-xs text-zinc-500">{row.platform}</span>
      {error && <span className="text-xs text-red-700">{error}</span>}
    </div>
  );
}

export function CompanyInsights() {
  const { data, error, isLoading, mutate } = useCompanyAnalytics();
  const rows = data ?? [];
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Company insights</h1>
        <DataNote />
        <InsightsNav />
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && (
        <Card title="By company">
          <p className="mb-3 text-xs text-zinc-500">
            Set an industry to let the Learning Agent compare industries. Rates for a single company rest on few
            applications: read the counts, not just the percentages.
          </p>
          <SegmentTable
            rows={rows}
            name="Company"
            empty="No packages yet."
            extra={(r: SegmentStat) => {
              const row = rows.find((c) => c.key === r.key);
              return row ? <IndustryField row={row} onSaved={() => void mutate()} /> : null;
            }}
          />
        </Card>
      )}
    </div>
  );
}
