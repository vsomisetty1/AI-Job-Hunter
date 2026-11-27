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

/** "$120k – $150k", "€90k+", or "" when unknown. Amounts are yearly. */
export function formatSalary(min: number | null, max: number | null, currency: string | null): string {
  if (min == null && max == null) return "";
  const fmt = (n: number) => {
    const short = n >= 1000 ? `${Math.round(n / 1000)}k` : String(n);
    const symbol = ({ USD: "$", EUR: "€", GBP: "£", CAD: "CA$", AUD: "A$", INR: "₹" } as Record<string, string>)[
      currency ?? ""
    ];
    return symbol ? `${symbol}${short}` : `${short}${currency ? ` ${currency}` : ""}`;
  };
  if (min != null && max != null) return min === max ? fmt(min) : `${fmt(min)} – ${fmt(max)}`;
  return min != null ? `${fmt(min)}+` : `up to ${fmt(max as number)}`;
}

/** "3 min ago", "2 h ago", "5 d ago"; falls back to a date after 30 days. */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 30 * 86400) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}
