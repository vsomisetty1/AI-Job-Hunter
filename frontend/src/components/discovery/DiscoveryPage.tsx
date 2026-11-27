"use client";

// Discovery dashboard: run discovery, manage company boards, monitor connectors.
import Link from "next/link";
import { useCallback } from "react";
import { useSWRConfig } from "swr";

import { Alert } from "@/components/ui/Alert";
import { useCompanies, useDiscoveryRuns } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";

import { CompaniesCard } from "./CompaniesCard";
import { ConnectorHealth } from "./ConnectorHealth";
import { RunHistory } from "./RunHistory";
import { RunPanel } from "./RunPanel";
import { SuggestionsCard } from "./SuggestionsCard";

export function DiscoveryPage() {
  const companies = useCompanies();
  const runs = useDiscoveryRuns();
  const { mutate } = useSWRConfig();

  const { mutate: refreshCompanies } = companies;
  const { mutate: refreshRuns } = runs;
  const refreshAll = useCallback(() => {
    void refreshCompanies();
    void refreshRuns();
    void mutate((k) => Array.isArray(k) && (k[0] === "jobs" || k[0] === "connector-health"));
    void mutate("company-directory");
  }, [refreshCompanies, refreshRuns, mutate]);
  const tracked = (companies.data ?? []).filter((c) => c.is_tracked).length;
  const latest = runs.data?.items[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Discovery</h1>
        <Link href="/jobs" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
          View discovered jobs →
        </Link>
      </div>
      {(companies.error || runs.error) && (
        <Alert tone="error">{errorMessage(companies.error ?? runs.error)}</Alert>
      )}
      <RunPanel trackedCount={tracked} latestId={latest?.id ?? null} onFinished={refreshAll} />
      <ConnectorHealth />
      <CompaniesCard companies={companies.data ?? []} onChanged={refreshAll} />
      <SuggestionsCard onChanged={refreshAll} />
      <RunHistory runs={runs.data?.items ?? []} />
    </div>
  );
}
