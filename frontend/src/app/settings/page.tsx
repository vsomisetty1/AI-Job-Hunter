"use client";

// Settings: job-search preferences used by filtering and scoring.
import { SettingsForm } from "@/components/settings/SettingsForm";
import { Alert } from "@/components/ui/Alert";
import { useSettings } from "@/hooks/useSettings";
import { errorMessage } from "@/lib/api/client";

export default function SettingsPage() {
  const { data, error, save } = useSettings();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Your preferences decide which jobs are kept and how they are scored. Saving re-scores your jobs.
        </p>
      </div>
      {error && <Alert tone="error">{errorMessage(error)}</Alert>}
      {!data && !error && <p className="text-sm text-zinc-500">Loading…</p>}
      {data && <SettingsForm settings={data} onSave={save} />}
    </div>
  );
}
