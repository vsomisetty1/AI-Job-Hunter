// Fit score pill: green 75+, indigo 55+, amber 35+, red below; "—" when not scored.
import type { ScoringMethod } from "@/types";

export function scoreTone(score: number): string {
  if (score >= 75) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (score >= 55) return "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300";
  if (score >= 35) return "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
  return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300";
}

export function ScoreBadge({
  score,
  method,
}: {
  score: number | null | undefined;
  method?: ScoringMethod | null;
}) {
  if (score == null) {
    return (
      <span className="text-zinc-400" aria-label="Not scored">
        —
      </span>
    );
  }
  const by = method === "claude" ? "Claude" : "rules";
  return (
    <span
      className={`inline-flex min-w-10 items-center justify-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${scoreTone(score)}`}
      title={`Fit score ${score}/100 (${by})`}
      aria-label={`Score ${score} by ${by}`}
    >
      {score}
      {method === "claude" && <span aria-hidden>✦</span>}
    </span>
  );
}
