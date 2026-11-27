"use client";

// Tracked company boards: add by platform + board name, pause, remove.
import { type FormEvent, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { errorMessage } from "@/lib/api/client";
import { companiesApi } from "@/lib/api/jobs";
import { formatRelative, safeUrl } from "@/lib/format";
import type { Company, JobSource } from "@/types";

const SELECT =
  "rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950";
const EXAMPLES: Record<JobSource, string> = {
  greenhouse: "job-boards.greenhouse.io/<board>",
  lever: "jobs.lever.co/<board>",
  ashby: "jobs.ashbyhq.com/<board>",
};

export function CompaniesCard({ companies, onChanged }: { companies: Company[]; onChanged: () => void }) {
  const [source, setSource] = useState<JobSource>("greenhouse");
  const [slug, setSlug] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function act(key: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(key);
    setError(null);
    setMessage(null);
    try {
      await fn();
      if (done) setMessage(done);
      onChanged();
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    const name = slug.trim();
    if (!name) return;
    if (await act("add", () => companiesApi.add(source, name), `Added ${name}.`)) setSlug("");
  }

  return (
    <Card title={`Tracked companies (${companies.filter((c) => c.is_tracked).length})`}>
      <form onSubmit={add} className="mb-4 flex flex-wrap items-end gap-2">
        <label className="text-sm">
          <span className="mb-1 block font-medium">Platform</span>
          <select className={SELECT} value={source} onChange={(e) => setSource(e.target.value as JobSource)}>
            <option value="greenhouse">Greenhouse</option>
            <option value="lever">Lever</option>
            <option value="ashby">Ashby</option>
          </select>
        </label>
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block font-medium">Board name</span>
          <input
            className={`${SELECT} w-full`}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder={`From ${EXAMPLES[source]}`}
            pattern="[A-Za-z0-9][A-Za-z0-9._\-]*"
            maxLength={100}
          />
        </label>
        <Button type="submit" disabled={busy === "add" || !slug.trim()}>
          {busy === "add" ? "Checking…" : "Add"}
        </Button>
      </form>
      {error && <Alert tone="error">{error}</Alert>}
      {message && <Alert>{message}</Alert>}
      {companies.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">No companies yet. Add one above or pick from the suggestions.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-zinc-500">
              <tr>
                <th className="py-2 pr-4">Company</th>
                <th className="py-2 pr-4">Last crawl</th>
                <th className="py-2 pr-4">Active jobs</th>
                <th className="py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {companies.map((c) => {
                const href = safeUrl(c.careers_url);
                return (
                  <tr key={c.id} className={c.is_tracked ? undefined : "opacity-60"}>
                    <td className="py-2 pr-4">
                      <span className="font-medium">{c.name}</span>
                      <span className="ml-2 text-xs text-zinc-500">
                        {href ? (
                          <a href={href} target="_blank" rel="noopener noreferrer" className="hover:underline">
                            {c.source}/{c.slug}
                          </a>
                        ) : (
                          `${c.source}/${c.slug}`
                        )}
                      </span>
                      {!c.is_tracked && (
                        <span className="ml-2">
                          <Badge>paused</Badge>
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      {c.last_crawl_status ? (
                        <>
                          <Badge tone={c.last_crawl_status === "ok" ? "green" : "red"}>{c.last_crawl_status}</Badge>
                          <span className="ml-2 text-xs text-zinc-500">{formatRelative(c.last_crawled_at)}</span>
                          {c.last_error && (
                            <span className="block text-xs text-red-600 dark:text-red-400" title={c.last_error}>
                              {c.consecutive_failures}× {c.last_error.slice(0, 80)}
                            </span>
                          )}
                        </>
                      ) : (
                        <span className="text-zinc-500">never</span>
                      )}
                    </td>
                    <td className="py-2 pr-4 tabular-nums">{c.active_jobs}</td>
                    <td className="py-2">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          disabled={busy === c.id}
                          onClick={() => act(c.id, () => companiesApi.setTracked(c.id, !c.is_tracked))}
                        >
                          {c.is_tracked ? "Pause" : "Resume"}
                        </Button>
                        {c.active_jobs === 0 && (
                          <Button
                            variant="ghost"
                            disabled={busy === c.id}
                            aria-label={`Remove ${c.name}`}
                            onClick={() => act(c.id, () => companiesApi.remove(c.id), `Removed ${c.name}.`)}
                          >
                            Remove
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
