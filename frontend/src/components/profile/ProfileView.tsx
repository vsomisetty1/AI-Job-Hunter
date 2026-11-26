// Read-only candidate profile.
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { formatDuration, formatRange, safeUrl } from "@/lib/format";
import type { CandidateProfile } from "@/types";

function Chips({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-sm text-zinc-500">None yet</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((s) => (
        <Badge key={s}>{s}</Badge>
      ))}
    </div>
  );
}

function Edited({ field, overrides }: { field: string; overrides: string[] }) {
  return overrides.includes(field) ? (
    <span className="ml-2 align-middle">
      <Badge tone="amber">edited</Badge>
    </span>
  ) : null;
}

export function ProfileView({ profile: p }: { profile: CandidateProfile }) {
  const links = [p.linkedin_url, p.portfolio_url].map(safeUrl).filter(Boolean) as string[];
  return (
    <div className="space-y-6">
      <Card>
        <h2 className="text-xl font-semibold">{p.full_name}</h2>
        {p.headline && (
          <p className="mt-1 text-zinc-700 dark:text-zinc-300">
            {p.headline}
            <Edited field="headline" overrides={p.overrides} />
          </p>
        )}
        <p className="mt-2 text-sm text-zinc-500">
          {[p.email, p.phone, p.location].filter(Boolean).join(" · ")}
        </p>
        {links.length > 0 && (
          <p className="mt-1 flex flex-wrap gap-x-3 text-sm">
            {links.map((l) => (
              <a key={l} href={l} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline dark:text-indigo-400">
                {l.replace(/^https?:\/\/(www\.)?/, "")}
              </a>
            ))}
          </p>
        )}
        <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            ["Seniority", p.seniority],
            ["Experience", p.years_of_experience != null ? `${p.years_of_experience} years` : null],
            ["Level", p.experience_level],
            ["Source", p.inference_source === "llm" ? "Claude" : "Rule-based"],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs uppercase text-zinc-500">{label}</dt>
              <dd className="font-medium first-letter:uppercase">{value ?? "—"}</dd>
            </div>
          ))}
        </dl>
        {p.summary && <p className="mt-4 text-sm">{p.summary}</p>}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={<>Target roles<Edited field="inferred_roles" overrides={p.overrides} /></>}>
          <Chips items={p.inferred_roles} />
        </Card>
        <Card title="Transferable roles">
          {p.transferable_roles.length ? (
            <ul className="space-y-2 text-sm">
              {p.transferable_roles.map((r) => (
                <li key={r.title}>
                  <span className="font-medium">{r.title}</span>
                  {r.rationale && <span className="text-zinc-500"> — {r.rationale}</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">
              {p.inference_source === "llm" ? "None suggested." : "Suggested when Claude is configured."}
            </p>
          )}
        </Card>
        <Card title={<>Skills<Edited field="skills" overrides={p.overrides} /></>}>
          <Chips items={p.skills} />
        </Card>
        <Card title="Industries">
          <Chips items={p.industries} />
        </Card>
      </div>

      <Card title="Career history">
        {p.career_history.length ? (
          <ol className="space-y-3 text-sm">
            {p.career_history.map((h, i) => (
              <li key={i} className="flex flex-wrap justify-between gap-2">
                <span>
                  <span className="font-medium">{h.title ?? "Role"}</span>
                  {h.company && <span className="text-zinc-500"> · {h.company}</span>}
                </span>
                <span className="text-zinc-500">
                  {formatRange(h.start_date, h.end_date, h.is_current)}
                  {h.duration_months ? ` (${formatDuration(h.duration_months)})` : ""}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-zinc-500">No roles found.</p>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Education">
          <p className="text-sm">{p.education_summary ?? "None listed"}</p>
        </Card>
        <Card title="Certifications">
          <p className="text-sm">{p.certification_summary ?? "None listed"}</p>
        </Card>
      </div>

      {p.career_analysis && (
        <Card title="Career analysis">
          <p className="text-sm">{p.career_analysis.narrative}</p>
          <p className="mt-2 text-sm">
            Trajectory: <Badge tone="indigo">{p.career_analysis.trajectory.replace("_", " ")}</Badge>
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            {(
              [
                ["Strengths", p.career_analysis.strengths],
                ["Gaps", p.career_analysis.gaps],
                ["Focus", p.career_analysis.recommended_focus],
              ] as [string, string[]][]
            ).map(([title, items]) => (
              <div key={title}>
                <h3 className="text-xs font-semibold uppercase text-zinc-500">{title}</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                  {items.length ? items.map((s) => <li key={s}>{s}</li>) : <li>None</li>}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
