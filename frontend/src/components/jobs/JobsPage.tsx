"use client";

// Search and browse discovered jobs.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useJobSearch, useScoringSummary } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import type { JobSearch } from "@/types";

import { JobsTable } from "./JobsTable";
import { ScoringBar } from "./ScoringBar";

const PAGE_SIZE = 50;
const SELECT =
  "rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950";

export function JobsPage() {
  // Links from recommendations pre-set filters: /jobs?min_score=85&q=backend
  const params = useSearchParams();
  const linkedMin = Number(params.get("min_score"));
  const [text, setText] = useState(params.get("q") ?? "");
  const [filters, setFilters] = useState<JobSearch>({
    sort: "score",
    filter_state: "passed",
    offset: 0,
    limit: PAGE_SIZE,
    ...(linkedMin > 0 && linkedMin <= 100 ? { min_score: linkedMin } : {}),
  });

  // Debounce typing so every keystroke is not a request.
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ({ ...f, q: text.trim(), offset: 0 })), 300);
    return () => clearTimeout(t);
  }, [text]);

  const { data, error, isLoading, mutate } = useJobSearch(filters);
  const { data: summary } = useScoringSummary();
  const set = (patch: Partial<JobSearch>) => setFilters((f) => ({ ...f, ...patch, offset: 0 }));
  const offset = filters.offset ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <Link href="/discovery" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">
          Discovery &amp; companies →
        </Link>
      </div>
      <ScoringBar onDone={() => void mutate()} />
      <Card>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="min-w-60 flex-1 text-sm">
            <span className="mb-1 block font-medium">Search</span>
            <input
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Title, company or location"
              className={`${SELECT} w-full`}
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Show</span>
            <select
              className={SELECT}
              value={filters.filter_state ?? "all"}
              onChange={(e) => set({ filter_state: e.target.value as JobSearch["filter_state"] })}
            >
              <option value="passed">Matches</option>
              <option value="rejected">Filtered out</option>
              <option value="pending">Not filtered yet</option>
              <option value="all">All</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Min score</span>
            <select
              className={SELECT}
              value={filters.min_score ?? ""}
              onChange={(e) => set({ min_score: e.target.value ? Number(e.target.value) : undefined })}
            >
              <option value="">Any</option>
              <option value="40">40+</option>
              <option value="60">60+</option>
              <option value="75">75+</option>
              <option value="90">90+</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Source</span>
            <select
              className={SELECT}
              value={filters.source ?? ""}
              onChange={(e) => set({ source: e.target.value as JobSearch["source"] })}
            >
              <option value="">All</option>
              <option value="greenhouse">Greenhouse</option>
              <option value="lever">Lever</option>
              <option value="ashby">Ashby</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Workplace</span>
            <select
              className={SELECT}
              value={filters.remote_type ?? ""}
              onChange={(e) => set({ remote_type: e.target.value as JobSearch["remote_type"] })}
            >
              <option value="">Any</option>
              <option value="remote">Remote</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">On-site</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Sort</span>
            <select
              className={SELECT}
              value={filters.sort}
              onChange={(e) => set({ sort: e.target.value as JobSearch["sort"] })}
            >
              <option value="score">Best score</option>
              <option value="newest">Newest found</option>
              <option value="posted">Posted date</option>
              <option value="title">Title</option>
              <option value="company">Company</option>
            </select>
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input
              type="checkbox"
              checked={!!filters.include_expired}
              onChange={(e) => set({ include_expired: e.target.checked })}
            />
            Include expired
          </label>
        </div>

        {error && <Alert tone="error">{errorMessage(error)}</Alert>}
        {isLoading && !data && <p className="text-sm text-zinc-500">Loading…</p>}
        {data && (
          <>
            {data.total === 0 && summary?.jobs_active === 0 ? (
              <Alert>
                No jobs yet. Add companies and run discovery on the{" "}
                <Link href="/discovery" className="font-medium underline">
                  Discovery
                </Link>{" "}
                page.
              </Alert>
            ) : (
              <JobsTable jobs={data.items} />
            )}
            <div className="mt-4 flex items-center justify-between text-sm text-zinc-500">
              <span>
                {data.total === 0
                  ? "0 jobs"
                  : `${offset + 1}–${offset + data.items.length} of ${data.total} jobs`}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setFilters((f) => ({ ...f, offset: Math.max(0, offset - PAGE_SIZE) }))}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  disabled={offset + PAGE_SIZE >= data.total}
                  onClick={() => setFilters((f) => ({ ...f, offset: offset + PAGE_SIZE }))}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
