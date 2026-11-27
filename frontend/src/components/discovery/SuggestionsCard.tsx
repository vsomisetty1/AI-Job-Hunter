"use client";

// Pick public company boards from the built-in suggestions list.
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useDirectory } from "@/hooks/useJobs";
import { errorMessage } from "@/lib/api/client";
import { companiesApi } from "@/lib/api/jobs";
import type { DirectoryEntry } from "@/types";

const key = (e: DirectoryEntry) => `${e.source}/${e.slug}`;

export function SuggestionsCard({ onChanged }: { onChanged: () => void }) {
  const { data, mutate } = useDirectory();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const available = (data ?? []).filter((e) => !e.added);
  if (data && available.length === 0) return null;

  function toggle(k: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  async function addPicked() {
    setBusy(true);
    setError(null);
    try {
      const boards = available.filter((e) => picked.has(key(e))).map(({ source, slug }) => ({ source, slug }));
      await companiesApi.addSuggested(boards);
      setPicked(new Set());
      await mutate();
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Suggested companies"
      actions={
        <>
          <Button variant="ghost" onClick={() => setPicked(new Set(available.map(key)))}>
            Select all
          </Button>
          <Button onClick={addPicked} disabled={busy || picked.size === 0}>
            Add {picked.size || ""} selected
          </Button>
        </>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      <div className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
        {available.map((e) => (
          <label key={key(e)} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={picked.has(key(e))} onChange={() => toggle(key(e))} />
            {e.name}
            <span className="text-xs text-zinc-500">{e.source}</span>
          </label>
        ))}
      </div>
    </Card>
  );
}
