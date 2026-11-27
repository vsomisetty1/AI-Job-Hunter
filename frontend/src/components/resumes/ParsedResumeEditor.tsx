"use client";

// Edit parsed resume data. Saving creates a new "parsed" version on the server
// (the previous versions stay in the history).
import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { TextArea, TextField } from "@/components/ui/Field";
import { errorMessage } from "@/lib/api/client";
import { resumesApi } from "@/lib/api/resumes";
import { csvToList, linesToList, listToLines, orNull } from "@/lib/format";
import type { ContactInfo, ParsedResume } from "@/types";

type FieldKind = "text" | "lines" | "csv" | "checkbox";
interface FieldSpec {
  key: string;
  label: string;
  kind?: FieldKind;
  placeholder?: string;
}

// Field specs for each repeating section. Dates are "YYYY-MM" or "YYYY".
export const SECTIONS = {
  experience: {
    title: "Experience",
    empty: { title: null, company: null, location: null, start_date: null, end_date: null,
             is_current: false, bullets: [], skills: [] },
    fields: [
      { key: "title", label: "Title" },
      { key: "company", label: "Company" },
      { key: "location", label: "Location" },
      { key: "start_date", label: "Start", placeholder: "YYYY-MM" },
      { key: "end_date", label: "End", placeholder: "YYYY-MM" },
      { key: "is_current", label: "Current role", kind: "checkbox" },
      { key: "bullets", label: "Bullets (one per line)", kind: "lines" },
    ],
  },
  education: {
    title: "Education",
    empty: { institution: null, degree: null, field_of_study: null, start_date: null,
             end_date: null, gpa: null, honors: [] },
    fields: [
      { key: "institution", label: "Institution" },
      { key: "degree", label: "Degree" },
      { key: "field_of_study", label: "Field of study" },
      { key: "start_date", label: "Start", placeholder: "YYYY" },
      { key: "end_date", label: "End", placeholder: "YYYY" },
      { key: "gpa", label: "GPA" },
    ],
  },
  certifications: {
    title: "Certifications",
    empty: { name: "", issuer: null, date: null, expires: null, credential_id: null },
    fields: [
      { key: "name", label: "Name" },
      { key: "issuer", label: "Issuer" },
      { key: "date", label: "Date", placeholder: "YYYY" },
    ],
  },
  projects: {
    title: "Projects",
    empty: { name: "", description: null, url: null, technologies: [], bullets: [] },
    fields: [
      { key: "name", label: "Name" },
      { key: "description", label: "Description" },
      { key: "url", label: "URL" },
      { key: "technologies", label: "Technologies (comma-separated)", kind: "csv" },
      { key: "bullets", label: "Bullets (one per line)", kind: "lines" },
    ],
  },
  publications: {
    title: "Publications",
    empty: { title: "", venue: null, date: null, url: null },
    fields: [
      { key: "title", label: "Title" },
      { key: "venue", label: "Venue" },
      { key: "date", label: "Date", placeholder: "YYYY" },
    ],
  },
  awards: {
    title: "Awards",
    empty: { title: "", issuer: null, date: null, description: null },
    fields: [
      { key: "title", label: "Title" },
      { key: "issuer", label: "Issuer" },
      { key: "date", label: "Date", placeholder: "YYYY" },
    ],
  },
} satisfies Record<string, { title: string; empty: object; fields: FieldSpec[] }>;

type SectionKey = keyof typeof SECTIONS;
type Entry = Record<string, unknown>;

function EntryListEditor({
  section,
  items,
  onChange,
}: {
  section: SectionKey;
  items: Entry[];
  onChange: (items: Entry[]) => void;
}) {
  const spec = SECTIONS[section];
  const update = (i: number, key: string, value: unknown) =>
    onChange(items.map((item, j) => (j === i ? { ...item, [key]: value } : item)));

  return (
    <fieldset className="space-y-3">
      <legend className="mb-2 text-sm font-semibold">{spec.title}</legend>
      {items.map((item, i) => (
        <div key={i} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
          <div className="grid gap-3 sm:grid-cols-2">
            {(spec.fields as FieldSpec[]).map((f) => {
              const label = `${f.label} (${spec.title} ${i + 1})`;
              const value = item[f.key];
              if (f.kind === "checkbox") {
                return (
                  <label key={f.key} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      aria-label={label}
                      checked={Boolean(value)}
                      onChange={(e) => update(i, f.key, e.target.checked)}
                    />
                    {f.label}
                  </label>
                );
              }
              if (f.kind === "lines") {
                return (
                  <TextArea
                    key={f.key}
                    label={f.label}
                    aria-label={label}
                    className="sm:col-span-2"
                    value={listToLines(value as string[])}
                    onChange={(e) => update(i, f.key, e.target.value.split("\n"))}
                    onBlur={(e) => update(i, f.key, linesToList(e.target.value))}
                  />
                );
              }
              return (
                <TextField
                  key={f.key}
                  label={f.label}
                  aria-label={label}
                  placeholder={f.placeholder}
                  value={f.kind === "csv" ? ((value as string[]) ?? []).join(", ") : ((value as string) ?? "")}
                  onChange={(e) =>
                    update(i, f.key, f.kind === "csv" ? csvToList(e.target.value) : e.target.value)
                  }
                />
              );
            })}
          </div>
          <div className="mt-2 text-right">
            <Button variant="ghost" onClick={() => onChange(items.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        </div>
      ))}
      <Button variant="secondary" onClick={() => onChange([...items, { ...spec.empty }])}>
        Add {spec.title.toLowerCase().replace(/s$/, "")}
      </Button>
    </fieldset>
  );
}

/** Trim strings, turn "" into null, drop empty entries. */
export function normalizeParsed(data: ParsedResume): ParsedResume {
  const clean = (v: unknown): unknown => {
    if (typeof v === "string") return orNull(v);
    if (Array.isArray(v)) return v.map(clean).filter((x) => x !== null && x !== "");
    return v;
  };
  const cleanEntries = (items: Entry[], required: string) =>
    items
      .map((item) => Object.fromEntries(Object.entries(item).map(([k, v]) => [k, clean(v)])))
      .filter((item) => Object.values(item).some((v) => v && (!Array.isArray(v) || v.length)))
      .map((item) => (item[required] === null ? { ...item, [required]: "" } : item));
  const contact = Object.fromEntries(
    Object.entries(data.contact).map(([k, v]) => [k, Array.isArray(v) ? v : clean(v)]),
  ) as unknown as ContactInfo;
  return {
    ...data,
    contact,
    summary: data.summary ? orNull(data.summary) : null,
    experience: cleanEntries(data.experience as unknown as Entry[], "title") as never,
    education: cleanEntries(data.education as unknown as Entry[], "institution") as never,
    certifications: cleanEntries(data.certifications as unknown as Entry[], "name") as never,
    projects: cleanEntries(data.projects as unknown as Entry[], "name") as never,
    publications: cleanEntries(data.publications as unknown as Entry[], "title") as never,
    awards: cleanEntries(data.awards as unknown as Entry[], "title") as never,
  };
}

const CONTACT_FIELDS: [keyof ContactInfo, string][] = [
  ["name", "Name"],
  ["email", "Email"],
  ["phone", "Phone"],
  ["location", "Location"],
  ["linkedin", "LinkedIn URL"],
  ["github", "GitHub URL"],
  ["portfolio", "Portfolio URL"],
];

export function ParsedResumeEditor({
  resumeId,
  initial,
  onSaved,
  onCancel,
}: {
  resumeId: string;
  initial: ParsedResume;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [data, setData] = useState<ParsedResume>(initial);
  const [skills, setSkills] = useState(initial.skills.join(", "));
  const [changeSummary, setChangeSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const payload = normalizeParsed({ ...data, skills: csvToList(skills) });
      await resumesApi.saveParsed(resumeId, payload, changeSummary);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <fieldset className="grid gap-3 sm:grid-cols-2">
        <legend className="mb-2 text-sm font-semibold">Contact</legend>
        {CONTACT_FIELDS.map(([key, label]) => (
          <TextField
            key={key}
            label={label}
            value={(data.contact[key] as string | null) ?? ""}
            onChange={(e) => setData({ ...data, contact: { ...data.contact, [key]: e.target.value } })}
          />
        ))}
      </fieldset>
      <TextArea
        label="Summary"
        value={data.summary ?? ""}
        onChange={(e) => setData({ ...data, summary: e.target.value })}
      />
      <TextArea
        label="Skills"
        hint="Comma-separated"
        value={skills}
        onChange={(e) => setSkills(e.target.value)}
      />
      {(Object.keys(SECTIONS) as SectionKey[]).map((key) => (
        <EntryListEditor
          key={key}
          section={key}
          items={data[key] as unknown as Entry[]}
          onChange={(items) => setData({ ...data, [key]: items })}
        />
      ))}
      <TextField
        label="What changed? (optional)"
        value={changeSummary}
        onChange={(e) => setChangeSummary(e.target.value)}
      />
      {error && <Alert tone="error">{error}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save as new version"}
        </Button>
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
