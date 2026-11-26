// Read-only view of parsed resume data.
import { Badge } from "@/components/ui/Badge";
import { formatRange, safeUrl } from "@/lib/format";
import type { ParsedResume } from "@/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
      {children}
    </section>
  );
}

export function ParsedResumeView({ data }: { data: ParsedResume }) {
  const c = data.contact;
  const contact = [c.email, c.phone, c.location].filter(Boolean).join(" · ");
  const links = [c.linkedin, c.github, c.portfolio, ...c.other_links]
    .map(safeUrl)
    .filter((l): l is string => l !== null);
  return (
    <div className="space-y-6 text-sm">
      <div>
        <p className="text-lg font-semibold">{c.name ?? "Name not found"}</p>
        {contact && <p className="text-zinc-600 dark:text-zinc-400">{contact}</p>}
        {links.length > 0 && (
          <p className="mt-1 flex flex-wrap gap-x-3">
            {links.map((l) => (
              <a key={l} href={l} target="_blank" rel="noopener noreferrer" className="text-indigo-600 hover:underline dark:text-indigo-400">
                {l.replace(/^https?:\/\/(www\.)?/, "")}
              </a>
            ))}
          </p>
        )}
      </div>
      {data.summary && (
        <Section title="Summary">
          <p>{data.summary}</p>
        </Section>
      )}
      {data.experience.length > 0 && (
        <Section title="Experience">
          <ul className="space-y-4">
            {data.experience.map((e, i) => (
              <li key={i}>
                <p className="font-medium">
                  {e.title ?? "Untitled role"}
                  {e.company && <span className="text-zinc-500"> · {e.company}</span>}
                </p>
                <p className="text-xs text-zinc-500">
                  {[formatRange(e.start_date, e.end_date, e.is_current), e.location].filter(Boolean).join(" · ")}
                </p>
                {e.bullets.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {e.bullets.map((b, j) => (
                      <li key={j}>{b}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {data.education.length > 0 && (
        <Section title="Education">
          <ul className="space-y-2">
            {data.education.map((e, i) => (
              <li key={i}>
                <p className="font-medium">{e.institution}</p>
                <p className="text-zinc-600 dark:text-zinc-400">
                  {[e.degree, e.field_of_study].filter(Boolean).join(", ")}
                  {(e.start_date || e.end_date) && ` · ${formatRange(e.start_date, e.end_date, false)}`}
                  {e.gpa && ` · GPA ${e.gpa}`}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {data.skills.length > 0 && (
        <Section title="Skills">
          <div className="flex flex-wrap gap-1.5">
            {data.skills.map((s) => (
              <Badge key={s}>{s}</Badge>
            ))}
          </div>
        </Section>
      )}
      {(
        [
          ["Certifications", data.certifications.map((x) => [x.name, x.issuer, x.date])],
          ["Projects", data.projects.map((x) => [x.name, x.description, x.url])],
          ["Publications", data.publications.map((x) => [x.title, x.venue, x.date])],
          ["Awards", data.awards.map((x) => [x.title, x.issuer, x.date])],
        ] as [string, (string | null)[][]][]
      )
        .filter(([, rows]) => rows.length > 0)
        .map(([title, rows]) => (
          <Section key={title} title={title}>
            <ul className="list-disc space-y-0.5 pl-5">
              {rows.map((r, i) => (
                <li key={i}>{r.filter(Boolean).join(" · ")}</li>
              ))}
            </ul>
          </Section>
        ))}
    </div>
  );
}
