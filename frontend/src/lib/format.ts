// Small formatting and form-conversion helpers.

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2021-03" -> "Mar 2021", "2021" -> "2021". */
export function formatYearMonth(d: string | null | undefined): string {
  if (!d) return "";
  const [y, m] = d.split("-");
  return m ? `${MONTHS[Number(m) - 1] ?? m} ${y}` : y;
}

export function formatRange(start: string | null, end: string | null, current: boolean): string {
  const s = formatYearMonth(start);
  const e = current ? "Present" : formatYearMonth(end);
  return s && e ? `${s} – ${e}` : s || e;
}

export function formatDuration(months: number | null | undefined): string {
  if (!months) return "";
  const y = Math.floor(months / 12);
  const m = months % 12;
  return [y && `${y} yr${y > 1 ? "s" : ""}`, m && `${m} mo`].filter(Boolean).join(" ");
}

/** Textarea (one item per line) <-> list. Blank lines are dropped. */
export function linesToList(text: string): string[] {
  return text
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function listToLines(items: string[] | null | undefined): string {
  return (items ?? []).join("\n");
}

/** Comma-separated input <-> list, de-duplicated case-insensitively. */
export function csvToList(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const v = raw.trim();
    if (v && !seen.has(v.toLowerCase())) {
      seen.add(v.toLowerCase());
      out.push(v);
    }
  }
  return out;
}

/** Empty string -> null, for optional text fields. */
export function orNull(v: string): string | null {
  const t = v.trim();
  return t ? t : null;
}

/** Only http(s) URLs are rendered as links (never javascript:, data:, ...). */
export function safeUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
