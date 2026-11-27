"use client";

// Approve / reject / regenerate / mark as submitted. Nothing here applies to the job:
// "Mark as submitted" only records that you applied yourself.
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { errorMessage } from "@/lib/api/client";
import { packagesApi } from "@/lib/api/packages";
import type { PackageDetail } from "@/types";

const INPUT =
  "w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950";

export function PackageActions({ pkg, onChange }: { pkg: PackageDetail; onChange: (p?: PackageDetail) => void }) {
  const router = useRouter();
  const [mode, setMode] = useState<"none" | "approve" | "reject">("none");
  const [text, setText] = useState("");
  const [useLlm, setUseLlm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (action: () => Promise<PackageDetail | void>) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await action();
      setMode("none");
      setText("");
      onChange(updated ?? undefined);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const canDecide = pkg.status === "generated" || pkg.status === "reviewed";
  const canReject = canDecide || pkg.status === "approved";
  const canRegenerate = ["generated", "reviewed", "approved", "rejected", "failed"].includes(pkg.status);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {canDecide && (
          <Button onClick={() => setMode(mode === "approve" ? "none" : "approve")} disabled={busy}>
            Approve
          </Button>
        )}
        {canReject && (
          <Button variant="danger" onClick={() => setMode(mode === "reject" ? "none" : "reject")} disabled={busy}>
            Reject
          </Button>
        )}
        {pkg.status === "approved" && (
          <Button variant="secondary" disabled={busy} onClick={() => run(() => packagesApi.markSubmitted(pkg.id))}>
            I applied with this package
          </Button>
        )}
        {canRegenerate && (
          <>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const started = await packagesApi.regenerate(pkg.id, useLlm);
                  router.push(`/packages/${started.package_id}`);
                })
              }
            >
              Regenerate
            </Button>
            <label className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-400">
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
              Reword with Claude (uses the API)
            </label>
          </>
        )}
      </div>
      {mode !== "none" && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() =>
              mode === "approve" ? packagesApi.approve(pkg.id, text) : packagesApi.reject(pkg.id, text.trim()),
            );
          }}
        >
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{mode === "approve" ? "Notes (optional)" : "Why reject it?"}</span>
            <textarea className={INPUT} value={text} onChange={(e) => setText(e.target.value)} rows={2} />
          </label>
          <Button type="submit" variant={mode === "approve" ? "primary" : "danger"} disabled={busy || (mode === "reject" && !text.trim())}>
            {mode === "approve" ? "Confirm approval" : "Confirm rejection"}
          </Button>
        </form>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}
