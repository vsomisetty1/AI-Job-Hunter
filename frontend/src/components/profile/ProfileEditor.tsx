"use client";

// Edit the profile's editable fields. Edited fields are kept on regeneration.
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextArea, TextField } from "@/components/ui/Field";
import { errorMessage } from "@/lib/api/client";
import { profileApi } from "@/lib/api/resumes";
import { csvToList, linesToList, orNull } from "@/lib/format";
import type { CandidateProfile, ProfileUpdate } from "@/types";

const SENIORITIES = [
  "intern", "entry", "junior", "mid", "senior", "staff", "principal", "lead", "manager",
  "director", "executive",
];

/** Only fields that differ from the profile are sent (so only they become overrides). */
export function diffProfile(p: CandidateProfile, form: ProfileUpdate): ProfileUpdate {
  const out: ProfileUpdate = {};
  for (const [key, value] of Object.entries(form) as [keyof ProfileUpdate, unknown][]) {
    if (JSON.stringify(value) !== JSON.stringify(p[key])) {
      (out as Record<string, unknown>)[key] = value;
    }
  }
  return out;
}

export function ProfileEditor({
  profile,
  onSaved,
  onCancel,
}: {
  profile: CandidateProfile;
  onSaved: (p: CandidateProfile) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState({
    full_name: profile.full_name,
    email: profile.email ?? "",
    phone: profile.phone ?? "",
    location: profile.location ?? "",
    linkedin_url: profile.linkedin_url ?? "",
    portfolio_url: profile.portfolio_url ?? "",
    headline: profile.headline ?? "",
    summary: profile.summary ?? "",
    seniority: profile.seniority ?? "",
    years: profile.years_of_experience?.toString() ?? "",
    skills: profile.skills.join(", "),
    industries: profile.industries.join(", "),
    roles: profile.inferred_roles.join("\n"),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof f) => (e: { target: { value: string } }) =>
    setF({ ...f, [key]: e.target.value });

  async function save() {
    setSaving(true);
    setError(null);
    const form: ProfileUpdate = {
      full_name: f.full_name.trim(),
      email: orNull(f.email),
      phone: orNull(f.phone),
      location: orNull(f.location),
      linkedin_url: orNull(f.linkedin_url),
      portfolio_url: orNull(f.portfolio_url),
      headline: orNull(f.headline),
      summary: orNull(f.summary),
      seniority: orNull(f.seniority),
      years_of_experience: f.years.trim() === "" ? null : Number(f.years),
      skills: csvToList(f.skills),
      industries: csvToList(f.industries),
      inferred_roles: linesToList(f.roles),
    };
    try {
      const patch = diffProfile(profile, form);
      onSaved(Object.keys(patch).length ? await profileApi.update(patch) : profile);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField label="Full name" required value={f.full_name} onChange={set("full_name")} />
        <TextField label="Email" type="email" value={f.email} onChange={set("email")} />
        <TextField label="Phone" value={f.phone} onChange={set("phone")} />
        <TextField label="Location" value={f.location} onChange={set("location")} />
        <TextField label="LinkedIn URL" type="url" value={f.linkedin_url} onChange={set("linkedin_url")} />
        <TextField label="Portfolio URL" type="url" value={f.portfolio_url} onChange={set("portfolio_url")} />
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-zinc-700 dark:text-zinc-300">Seniority</span>
          <select
            className="w-full rounded-md border border-zinc-300 bg-white px-2.5 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
            value={f.seniority}
            onChange={set("seniority")}
          >
            <option value="">Not set</option>
            {SENIORITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <TextField label="Years of experience" type="number" min={0} max={70} step={0.1}
                   value={f.years} onChange={set("years")} />
      </div>
      <TextField label="Headline" value={f.headline} onChange={set("headline")} />
      <TextArea label="Summary" value={f.summary} onChange={set("summary")} />
      <TextArea label="Target roles" hint="One per line" value={f.roles} onChange={set("roles")} />
      <TextArea label="Skills" hint="Comma-separated" value={f.skills} onChange={set("skills")} />
      <TextField label="Industries (comma-separated)" value={f.industries} onChange={set("industries")} />
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
        <Button variant="secondary" onClick={onCancel} disabled={saving}>Cancel</Button>
      </div>
    </form>
  );
}
