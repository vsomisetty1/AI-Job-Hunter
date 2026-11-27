"use client";

// Job-search preferences: what the rule filter keeps and how jobs are scored.
import { type FormEvent, useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { TextArea, TextField } from "@/components/ui/Field";
import { errorMessage } from "@/lib/api/client";
import { csvToList, linesToList, listToLines, orNull } from "@/lib/format";
import type { EmploymentType, RemotePreference, Settings, SettingsUpdate } from "@/types";

const SELECT =
  "w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950";

export const EMPLOYMENT_TYPES: { value: EmploymentType; label: string }[] = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "temporary", label: "Temporary" },
  { value: "internship", label: "Internship" },
];

const REMOTE: { value: RemotePreference; label: string; hint: string }[] = [
  { value: "any", label: "Any", hint: "Remote, hybrid and on-site jobs" },
  { value: "remote_only", label: "Remote only", hint: "Only remote jobs" },
  { value: "hybrid", label: "Hybrid", hint: "Hybrid or remote jobs" },
  { value: "onsite", label: "On-site", hint: "On-site or hybrid jobs" },
];

interface FormState {
  locations: string;
  remote: RemotePreference;
  jobTypes: EmploymentType[];
  salaryMin: string;
  salaryTarget: string;
  currency: string;
  sponsorship: boolean;
  workAuthorization: string;
  visaStatus: string;
  companies: string;
  keywords: string;
  claudeEnabled: boolean;
  claudeMinScore: string;
  relocate: "" | "yes" | "no";
}

function toForm(s: Settings): FormState {
  return {
    locations: s.preferred_locations.join(", "),
    remote: s.remote_preference,
    jobTypes: s.job_types,
    salaryMin: s.salary_min?.toString() ?? "",
    salaryTarget: s.salary_target?.toString() ?? "",
    currency: s.salary_currency,
    sponsorship: s.requires_sponsorship,
    workAuthorization: s.work_authorization ?? "",
    visaStatus: s.visa_status ?? "",
    companies: listToLines(s.excluded_companies),
    keywords: s.excluded_keywords.join(", "),
    claudeEnabled: s.claude_scoring_enabled,
    claudeMinScore: String(s.claude_scoring_min_score),
    relocate: s.willing_to_relocate == null ? "" : s.willing_to_relocate ? "yes" : "no",
  };
}

const toInt = (v: string): number | null => (v.trim() === "" ? null : Math.round(Number(v)));

/** The PATCH body: only fields whose value differs from the saved settings. */
export function settingsPatch(saved: Settings, f: FormState): SettingsUpdate {
  const next: SettingsUpdate = {
    preferred_locations: csvToList(f.locations),
    remote_preference: f.remote,
    job_types: f.jobTypes,
    salary_min: toInt(f.salaryMin),
    salary_target: toInt(f.salaryTarget),
    salary_currency: f.currency.trim().toUpperCase(),
    requires_sponsorship: f.sponsorship,
    work_authorization: orNull(f.workAuthorization),
    visa_status: orNull(f.visaStatus),
    excluded_companies: linesToList(f.companies),
    excluded_keywords: csvToList(f.keywords),
    claude_scoring_enabled: f.claudeEnabled,
    claude_scoring_min_score: toInt(f.claudeMinScore) ?? 0,
    willing_to_relocate: f.relocate === "" ? null : f.relocate === "yes",
  };
  const patch: SettingsUpdate = {};
  for (const [key, value] of Object.entries(next) as [keyof SettingsUpdate, unknown][]) {
    if (JSON.stringify(value) !== JSON.stringify(saved[key])) {
      (patch as Record<string, unknown>)[key] = value;
    }
  }
  return patch;
}

export function SettingsForm({
  settings,
  onSave,
}: {
  settings: Settings;
  onSave: (patch: SettingsUpdate) => Promise<unknown>;
}) {
  const [form, setForm] = useState<FormState>(() => toForm(settings));
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch }));

  const salaryError =
    toInt(form.salaryMin) != null &&
    toInt(form.salaryTarget) != null &&
    (toInt(form.salaryMin) as number) > (toInt(form.salaryTarget) as number)
      ? "The minimum salary cannot be above the target."
      : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (salaryError) return;
    const patch = settingsPatch(settings, form);
    if (Object.keys(patch).length === 0) {
      setMessage({ tone: "info", text: "Nothing changed." });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      await onSave(patch);
      setMessage({ tone: "info", text: "Saved. Jobs are being filtered and scored again." });
    } catch (err) {
      setMessage({ tone: "error", text: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  const toggleType = (t: EmploymentType) =>
    set({ jobTypes: form.jobTypes.includes(t) ? form.jobTypes.filter((x) => x !== t) : [...form.jobTypes, t] });

  return (
    <form onSubmit={submit} className="space-y-6" aria-label="Job search preferences">
      <Card title="Where and how you work">
        <div className="grid gap-4 md:grid-cols-2">
          <TextField
            label="Preferred locations"
            value={form.locations}
            onChange={(e) => set({ locations: e.target.value })}
            placeholder="San Francisco, New York, Remote"
          />
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">Workplace</span>
            <select
              className={SELECT}
              value={form.remote}
              onChange={(e) => set({ remote: e.target.value as RemotePreference })}
            >
              {REMOTE.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}: {r.hint}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          Comma-separated. Cities, states, countries and common abbreviations (NYC, SF, US, UK) match. Add
          &quot;Remote&quot; to keep every remote job wherever it is based. Jobs without a location are kept.
        </p>
        <fieldset className="mt-4">
          <legend className="mb-1 text-sm font-medium text-zinc-700 dark:text-zinc-300">Employment types</legend>
          <div className="flex flex-wrap gap-4">
            {EMPLOYMENT_TYPES.map((t) => (
              <label key={t.value} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.jobTypes.includes(t.value)} onChange={() => toggleType(t.value)} />
                {t.label}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-zinc-500">None selected keeps every type.</p>
        </fieldset>
      </Card>

      <Card title="Salary">
        <div className="grid gap-4 md:grid-cols-3">
          <TextField
            label="Minimum (yearly)"
            type="number"
            min={0}
            value={form.salaryMin}
            onChange={(e) => set({ salaryMin: e.target.value })}
          />
          <TextField
            label="Target (yearly)"
            type="number"
            min={0}
            value={form.salaryTarget}
            onChange={(e) => set({ salaryTarget: e.target.value })}
          />
          <TextField
            label="Currency"
            value={form.currency}
            maxLength={3}
            onChange={(e) => set({ currency: e.target.value })}
          />
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          Jobs whose posted pay cannot reach the minimum are filtered out; jobs without a salary are kept. The
          target is used for scoring.
        </p>
        {salaryError && (
          <p role="alert" className="mt-2 text-sm text-red-700 dark:text-red-400">
            {salaryError}
          </p>
        )}
      </Card>

      <Card title="Work authorization">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.sponsorship}
            onChange={(e) => set({ sponsorship: e.target.checked })}
          />
          I need visa sponsorship
        </label>
        <p className="mt-1 text-xs text-zinc-500">
          When checked, jobs whose posting rules out sponsorship (or requires citizenship) are filtered out.
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <TextField
            label="Work authorization"
            value={form.workAuthorization}
            onChange={(e) => set({ workAuthorization: e.target.value })}
            placeholder="e.g. Authorized to work in the US"
          />
          <TextField
            label="Visa status"
            value={form.visaStatus}
            onChange={(e) => set({ visaStatus: e.target.value })}
            placeholder="e.g. H-1B"
          />
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">Willing to relocate</span>
            <select
              className={SELECT}
              value={form.relocate}
              onChange={(e) => set({ relocate: e.target.value as FormState["relocate"] })}
            >
              <option value="">Not stated (answers ask you)</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </label>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          Application answers about sponsorship, authorization and relocation come from these fields.
        </p>
      </Card>

      <Card title="Exclusions">
        <div className="grid gap-4 md:grid-cols-2">
          <TextArea
            label="Excluded companies"
            hint="One per line."
            value={form.companies}
            onChange={(e) => set({ companies: e.target.value })}
          />
          <TextArea
            label="Excluded keywords"
            hint="Comma-separated. Matched as whole words in the title, requirements and description."
            value={form.keywords}
            onChange={(e) => set({ keywords: e.target.value })}
          />
        </div>
      </Card>

      <Card title="AI scoring (optional)">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.claudeEnabled}
            onChange={(e) => set({ claudeEnabled: e.target.checked })}
          />
          Also score my best matches with Claude
        </label>
        <p className="mt-1 text-xs text-zinc-500">
          Rule-based scoring always runs and costs nothing. Claude scoring needs ANTHROPIC_API_KEY on the
          backend, uses the API (billed per call), and is capped per run and per day.
        </p>
        <div className="mt-4 max-w-xs">
          <TextField
            label="Only jobs with a rule score of at least"
            type="number"
            min={0}
            max={100}
            value={form.claudeMinScore}
            disabled={!form.claudeEnabled}
            onChange={(e) => set({ claudeMinScore: e.target.value })}
          />
        </div>
      </Card>

      {message && <Alert tone={message.tone}>{message.text}</Alert>}
      <div className="flex justify-end">
        <Button type="submit" disabled={saving || !!salaryError}>
          {saving ? "Saving…" : "Save preferences"}
        </Button>
      </div>
    </form>
  );
}
