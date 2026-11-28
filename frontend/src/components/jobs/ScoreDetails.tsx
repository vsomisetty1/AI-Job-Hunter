// Why a job got its score, and why the filter kept or dropped it.
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import type { FilterResult, JobScore } from "@/types";

import { ScoreBadge } from "./ScoreBadge";

const COMPONENT_LABELS: Record<string, string> = {
  skills: "Skills",
  relevance: "Title fit",
  seniority: "Seniority",
  location: "Location",
  salary: "Salary",
};

const RULE_LABELS: Record<string, string> = {
  duplicate: "Duplicate",
  company: "Company",
  keywords: "Keywords",
  location: "Location",
  remote: "Workplace",
  employment_type: "Employment type",
  salary: "Salary",
  sponsorship: "Sponsorship",
};

function Bar({ label, value, note }: { label: string; value: number | null; note?: string }) {
  return (
    <li className="text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-zinc-600 dark:text-zinc-400">{value ?? "n/a"}</span>
      </div>
      <div
        className="mt-1 h-1.5 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value ?? 0}
      >
        {value != null && <div className="h-full bg-indigo-500" style={{ width: `${value}%` }} />}
      </div>
      {note && <p className="mt-0.5 text-xs text-zinc-500">{note}</p>}
    </li>
  );
}

function SkillList({ title, skills, tone }: { title: string; skills: string[]; tone: "green" | "amber" }) {
  if (skills.length === 0) return null;
  return (
    <div>
      <h3 className="mb-1 text-xs font-semibold uppercase text-zinc-500">{title}</h3>
      <div className="flex flex-wrap gap-1">
        {skills.map((s) => (
          <Badge key={s} tone={tone}>
            {s}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function RulesScore({ score }: { score: JobScore }) {
  const components = score.breakdown.components ?? {};
  return (
    <div className="space-y-4">
      <ul className="space-y-3">
        {Object.entries(components).map(([name, c]) => (
          <Bar key={name} label={COMPONENT_LABELS[name] ?? name} value={c.score} note={c.summary} />
        ))}
      </ul>
      {score.breakdown.confidence != null && score.breakdown.confidence < 1 && (
        <p className="text-xs text-zinc-500">
          Based on {Math.round(score.breakdown.confidence * 100)}% of the scoring weight; the rest
          could not be judged from the posting.
        </p>
      )}
    </div>
  );
}

function ClaudeScore({ score }: { score: JobScore }) {
  const strengths = score.breakdown.strengths ?? [];
  const concerns = score.breakdown.concerns ?? [];
  return (
    <div className="space-y-4">
      {!score.is_current && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          Out of date: the job, your profile or your preferences changed since Claude scored it.
        </p>
      )}
      {score.rationale && <p className="text-sm">{score.rationale}</p>}
      <ul className="space-y-3">
        <Bar label="Skills" value={score.skills_score} />
        <Bar label="Seniority" value={score.seniority_score} />
        <Bar label="Interview chance" value={score.interview_probability} />
        <Bar label="Growth" value={score.growth_score} />
        <Bar label="Company" value={score.company_score} />
      </ul>
      {strengths.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-zinc-500">Strengths</h3>
          <ul className="list-disc pl-5 text-sm">
            {strengths.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      {concerns.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase text-zinc-500">Concerns</h3>
          <ul className="list-disc pl-5 text-sm">
            {concerns.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-zinc-500">
        {score.model}
        {score.input_tokens > 0 ? ` · ${score.input_tokens + score.output_tokens} tokens` : " · cached"}
      </p>
    </div>
  );
}

export function ScoreCard({ scores }: { scores: JobScore[] }) {
  if (scores.length === 0) {
    return (
      <Card title="Score">
        <p className="text-sm text-zinc-500">
          Not scored. Jobs are scored once they pass your filters and you have a profile.
        </p>
      </Card>
    );
  }
  const rules = scores.find((s) => s.scoring_method === "rules");
  const claude = scores.find((s) => s.scoring_method === "claude");
  const skills = (claude?.is_current ? claude : rules) ?? scores[0];
  return (
    <>
      {claude && (
        <Card title={<span className="flex items-center gap-2">Claude score <ScoreBadge score={claude.overall_score} method="claude" /></span>}>
          <ClaudeScore score={claude} />
        </Card>
      )}
      {rules && (
        <Card title={<span className="flex items-center gap-2">Rule-based score <ScoreBadge score={rules.overall_score} method="rules" /></span>}>
          <RulesScore score={rules} />
        </Card>
      )}
      <Card title="Skills">
        <div className="space-y-3">
          <SkillList title="You have" skills={skills.matched_skills} tone="green" />
          <SkillList title="Missing" skills={skills.missing_skills} tone="amber" />
          {skills.matched_skills.length + skills.missing_skills.length === 0 && (
            <p className="text-sm text-zinc-500">No recognised skills in this posting.</p>
          )}
        </div>
      </Card>
    </>
  );
}

export function FilterCard({ result }: { result: FilterResult | null }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Filters{" "}
          {result && <Badge tone={result.passed ? "green" : "red"}>{result.passed ? "kept" : "filtered out"}</Badge>}
        </span>
      }
    >
      {result ? (
        <ul className="space-y-1 text-sm">
          {result.checks.map((c) => (
            <li key={c.rule} className="flex gap-2">
              <span aria-label={c.passed ? "passed" : "failed"} className={c.passed ? "text-emerald-600" : "text-red-600"}>
                {c.passed ? "✓" : "✗"}
              </span>
              <span>
                <span className="font-medium">{RULE_LABELS[c.rule] ?? c.rule}:</span> {c.reason}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-zinc-500">Not checked against your preferences yet.</p>
      )}
    </Card>
  );
}
