"use client";

// Search and browse discovered jobs.
import Link from "next/link";
import { useEffect, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useJobSearch } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import type { JobSearch } from "@/types";

import { JobsTable } from "./JobsTable";

const PAGE_SIZE = 50;
const SELECT =
  "rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950";

export function JobsPage() {
  const [text, setText] = useState("");
  const [filters, setFilters] = useState<JobSearch>({ sort: "newest", offset: 0, limit: PAGE_SIZE });

  // Debounce typing so every keystroke is not a request.
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => ({ ...f, q: text.trim(), offset: 0 })), 300);
    return () => clearTimeout(t);
  }, [text]);

  const { data, error, isLoading } = useJobSearch(filters);
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
            {data.total === 0 && !filters.q && !filters.source && !filters.remote_type ? (
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
